#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""Sincroniza relatórios FOCUS gerenciados pela OCI para um bucket do cliente.

O fluxo lê origem e destino como sequências ordenadas, compara apenas objetos com
o mesmo caminho relativo e submete cópias assíncronas para objetos ausentes ou
divergentes. Assim, não é necessário manter o inventário inteiro em memória.
"""

import io
import json
import logging
import os
import time
from contextvars import ContextVar
from functools import wraps

import oci
from fdk import response

LOGGER = logging.getLogger(__name__)

# Suprime logs HTTP de baixo nível. Dependendo da versão da imagem, o SDK OCI
# pode usar o urllib3 empacotado ou o instalado como dependência direta.
for urllib3_logger_name in (
    "urllib3",
    "urllib3.connectionpool",
    "oci._vendor.urllib3",
    "oci._vendor.urllib3.connectionpool",
):
    logging.getLogger(urllib3_logger_name).setLevel(logging.WARNING)

# Mantém tentativas transitórias dentro do tempo máximo da Function.
# https://docs.oracle.com/en-us/iaas/tools/python/latest/sdk_behaviors/retries.html
CUSTOM_RETRY_STRATEGY = oci.retry.RetryStrategyBuilder(
    max_attempts_check=True,
    max_attempts=5,
    total_elapsed_time_check=True,
    total_elapsed_time_seconds=120,
    retry_max_wait_between_calls_seconds=20,
    retry_base_sleep_time_seconds=2,
    service_error_check=True,
    service_error_retry_on_any_5xx=True,
    service_error_retry_config={
        400: ["QuotaExceeded", "LimitExceeded"],
        429: [],
    },
    backoff_type=oci.retry.BACKOFF_FULL_JITTER_EQUAL_ON_THROTTLE_VALUE,
).get_retry_strategy()

# Origem imutável publicada pela OCI e prefixo usado no bucket do cliente.
PUBLIC_NAMESPACE = "bling"
PUBLIC_REPORT_PREFIX = "FOCUS Reports/"

# Controle de polling das cópias assíncronas e exclusão entre invocações.
WORK_REQUEST_TIMEOUT_SECONDS = 120
WORK_REQUEST_POLL_SECONDS = 2
WORK_REQUEST_INITIAL_WAIT_SECONDS = 5
LOCK_TTL_SECONDS = 900
LOCK_METADATA_KEY = "focus-lock-expires-at"

# O lock fica no contexto desta invocação para ser liberado inclusive em erros.
EXECUTION_LOCK = ContextVar("execution_lock", default=None)
# Campos usados no merge: nome ordena, MD5/tamanho comparam e ETag protege cópias.
OBJECT_SUMMARY_FIELDS = "name,size,etag,md5"

def get_oci_client(service_client):
    """Cria um cliente OCI autenticado pelo Resource Principal da Function."""
    try:
        signer = oci.auth.signers.get_resource_principals_signer()
        return service_client(
            config={},
            signer=signer,
            retry_strategy=CUSTOM_RETRY_STRATEGY,
        )
    except Exception as error:
        # Normalmente indica Resource Principal, Dynamic Group ou policy incorretos.
        LOGGER.error("Falha ao obter credenciais do Resource Principal: %s", error)
        return False


def make_response(ctx, response_data, status_code, content_type):
    """Monta uma resposta HTTP uniforme para a OCI Function."""
    return response.Response(
        ctx,
        response_data=response_data,
        status_code=status_code,
        headers={"Content-Type": content_type},
    )


def log_event(level, event, **details):
    """Registra um evento estruturado para facilitar consultas nos logs."""
    LOGGER.log(level, json.dumps({"event": event, **details}, default=str))


def release_lock_on_exit(function):
    """Garante a remoção do lock desta invocação, inclusive em erros."""
    @wraps(function)
    def wrapped(*args, **kwargs):
        try:
            return function(*args, **kwargs)
        finally:
            lock_context = EXECUTION_LOCK.get()
            if lock_context:
                release_execution_lock(*lock_context)
                EXECUTION_LOCK.set(None)
    return wrapped



def iter_paginated_data(list_function, **kwargs):
    """Produz páginas OCI sem reter todos os resultados em memória.

    A API ListObjects usa ``next_start_with`` e ``start`` para paginação. A
    paginação manual permite interromper a listagem quando o merge não precisar
    de mais páginas, reduzindo consumo para buckets com histórico extenso.
    """
    start = None
    try:
        while True:
            page_kwargs = dict(kwargs)
            if start:
                page_kwargs["start"] = start
            response_data = list_function(**page_kwargs)
            yield response_data.data
            start = getattr(response_data.data, "next_start_with", None)
            if not start:
                return
    except Exception as error:
        log_event(
            logging.ERROR,
            "object_list_failed",
            operation=list_function.__name__,
            error=str(error),
        )
        raise RuntimeError("Não foi possível listar os objetos.") from error


def normalize_prefix(prefix):
    """Normaliza um prefixo para ter uma única barra final, ou retornar vazio."""
    return f"{prefix.strip('/')}/" if prefix and prefix.strip('/') else ""


def get_destination_region(config):
    """Usa região configurada; na ausência, usa a região do Resource Principal."""
    return (
        config.get("OCI_BUCKET_DESTINATION_REGION")
        or os.environ.get("OCI_RESOURCE_PRINCIPAL_REGION")
    )


def iter_relative_summaries(
    list_function,
    relative_prefix,
    stats,
    page_stat,
    object_stat,
    skip_name=None,
    **kwargs,
):
    """Produz ``(nome_relativo, resumo)`` na ordem lexicográfica da OCI.

    Os nomes relativos tornam comparáveis os prefixos distintos da origem e do
    destino. As estatísticas são atualizadas durante o streaming, sem listas extras.
    """
    for page_data in iter_paginated_data(list_function, **kwargs):
        stats[page_stat] += 1
        for item in page_data.objects:
            if not item.name.startswith(relative_prefix):
                continue
            relative_name = item.name[len(relative_prefix):]
            if relative_name == skip_name:
                continue
            stats[object_stat] += 1
            yield relative_name, item


def objects_match(source, destination):
    """Compara tamanho e MD5; ETags não são comparáveis após uma cópia."""
    return (
        source.size == destination.size
        and source.md5 is not None
        and source.md5 == destination.md5
    )


def has_comparison_metadata(source, destination):
    """Indica se há MD5 suficiente para comparar o par de objetos com confiança."""
    return source.md5 is not None and (destination is None or destination.md5 is not None)


def get_lock_object_name(destination_prefix):
    """Retorna o objeto de lock fora da árvore de relatórios do destino."""
    return f"{destination_prefix}.focus-report-exporter.lock"


def acquire_execution_lock(client, namespace, bucket, destination_prefix):
    """Adquire lock no bucket e recupera com segurança um lock expirado.

    ``if_none_match='*'`` impede duas invocações simultâneas. Na recuperação, o
    ETag evita apagar um lock substituído por outra execução.
    """
    lock_name = get_lock_object_name(destination_prefix)
    expires_at = str(int(time.time()) + LOCK_TTL_SECONDS)

    try:
        lock_response = client.put_object(
            namespace_name=namespace,
            bucket_name=bucket,
            object_name=lock_name,
            put_object_body=b"",
            if_none_match="*",
            opc_meta={LOCK_METADATA_KEY: expires_at},
        )
        return lock_name, lock_response.headers.get("etag")
    except oci.exceptions.ServiceError as error:
        if error.status != 412:
            raise

    try:
        existing_lock = client.head_object(
            namespace_name=namespace,
            bucket_name=bucket,
            object_name=lock_name,
        )
        lock_expires_at = int(
            existing_lock.headers.get(f"opc-meta-{LOCK_METADATA_KEY}", "0")
        )
        if lock_expires_at >= time.time():
            return None

        client.delete_object(
            namespace_name=namespace,
            bucket_name=bucket,
            object_name=lock_name,
            if_match=existing_lock.headers.get("etag"),
        )
        return acquire_execution_lock(client, namespace, bucket, destination_prefix)
    except (ValueError, oci.exceptions.ServiceError) as error:
        LOGGER.warning("Não foi possível recuperar lock expirado: %s", error)
        return None


def release_execution_lock(client, namespace, bucket, lock):
    """Remove o lock somente quando seu ETag ainda pertence a esta execução."""
    if not lock:
        return

    lock_name, lock_etag = lock
    try:
        client.delete_object(
            namespace_name=namespace,
            bucket_name=bucket,
            object_name=lock_name,
            if_match=lock_etag,
        )
    except oci.exceptions.ServiceError as error:
        LOGGER.warning("Não foi possível remover o lock da execução: %s", error)


def serialize_oci_model(model):
    """Converte modelos OCI em dados seguros para o log estruturado."""
    return model.to_dict() if hasattr(model, "to_dict") else str(model)


def log_copy_failure(client, object_name, work_request_id, status):
    """Registra os detalhes OCI disponíveis para uma cópia que falhou.

    As consultas adicionais ocorrem somente após uma falha terminal, portanto
    não aumentam o custo normal de uma sincronização bem-sucedida.
    """
    details = {
        "object_name": object_name,
        "work_request_id": work_request_id,
        "status": status,
    }

    for detail_name, list_function in (
        ("errors", client.list_work_request_errors),
        ("logs", client.list_work_request_logs),
    ):
        try:
            response_data = list_function(
                work_request_id,
                limit=100,
                retry_strategy=oci.retry.NoneRetryStrategy(),
            )
            details[detail_name] = [
                serialize_oci_model(item) for item in response_data.data
            ]
        except Exception as error:
            details[f"{detail_name}_lookup_error"] = str(error)

    log_event(logging.ERROR, "copy_failed", **details)


def wait_for_copy_requests(client, requests, stats):
    """Espera as cópias submetidas e contabiliza somente requests concluídos.

    Todas as cópias são submetidas antes do primeiro polling para que o Object
    Storage já tenha iniciado o trabalho e sejam necessárias menos reconsultas.
    """
    pending = dict(requests)
    deadline = time.monotonic() + WORK_REQUEST_TIMEOUT_SECONDS

    if pending:
        # Aguarda uma vez antes do polling para aumentar a chance de status final.
        time.sleep(WORK_REQUEST_INITIAL_WAIT_SECONDS)

    while pending and time.monotonic() < deadline:
        for object_name, request in list(pending.items()):
            work_request_id, is_update = request
            try:
                status = client.get_work_request(
                    work_request_id,
                    retry_strategy=oci.retry.NoneRetryStrategy(),
                ).data.status
            except Exception as error:
                LOGGER.error('Erro ao consultar a cópia de "%s": %s', object_name, error)
                stats['unknown'] += 1
                del pending[object_name]
                continue

            if status == oci.object_storage.models.WorkRequest.STATUS_COMPLETED:
                stats['copy'] += 1
                if is_update:
                    stats['update'] += 1
                del pending[object_name]
            elif status in (
                oci.object_storage.models.WorkRequest.STATUS_FAILED,
                oci.object_storage.models.WorkRequest.STATUS_CANCELED,
            ):
                log_copy_failure(client, object_name, work_request_id, status)
                stats['erro'] += 1
                del pending[object_name]

        if pending:
            time.sleep(WORK_REQUEST_POLL_SECONDS)

    stats['pending'] = len(pending)
    if pending:
        LOGGER.warning(
            "%s cópia(s) ainda em processamento após o tempo de espera.", len(pending)
        )


def submit_copy(
    client,
    tenancy_id,
    source_name,
    source_object,
    destination_object,
    destination_namespace,
    destination_bucket,
    destination_region,
    destination_prefix,
    requests,
    stats,
):
    """Submete uma cópia ausente ou divergente, sem esperar sua finalização.

    As pré-condições por ETag protegem contra alterações entre a listagem e a
    cópia: objetos novos usam ``if-none-match`` e objetos existentes usam
    ``if-match`` do destino.
    """
    destination_name = f'{destination_prefix}{source_name}'
    if not has_comparison_metadata(source_object, destination_object):
        stats['metadata_incomplete'] += 1

    details = oci.object_storage.models.CopyObjectDetails(
        source_object_name=f'{PUBLIC_REPORT_PREFIX}{source_name}',
        source_object_if_match_e_tag=source_object.etag,
        destination_region=destination_region,
        destination_namespace=destination_namespace,
        destination_bucket=destination_bucket,
        destination_object_name=destination_name,
        destination_object_if_none_match_e_tag=(
            "*" if destination_object is None else None
        ),
        destination_object_if_match_e_tag=(
            destination_object.etag if destination_object else None
        ),
    )
    try:
        copy_response = client.copy_object(
            namespace_name=PUBLIC_NAMESPACE,
            bucket_name=tenancy_id,
            copy_object_details=details,
        )
    except oci.exceptions.ServiceError as error:
        if error.status == 412:
            log_event(logging.WARNING, "copy_conflict", object_name=source_name)
            stats['conflict'] += 1
        else:
            LOGGER.error('Erro ao copiar "%s": %s', source_name, error)
            stats['erro'] += 1
        return
    except Exception as error:
        LOGGER.error('Erro ao copiar "%s": %s', source_name, error)
        stats['erro'] += 1
        return

    work_request_id = copy_response.headers.get("opc-work-request-id")
    if copy_response.status != 202 or not work_request_id:
        LOGGER.error('Erro ao copiar "%s". Status: %s', source_name, copy_response.status)
        stats['erro'] += 1
        return
    requests[source_name] = (work_request_id, destination_object is not None)


@release_lock_on_exit
def handler(ctx, data: io.BytesIO = None):
    """Executa uma sincronização completa e idempotente dos relatórios FOCUS.

    ``data`` é aceito pela assinatura exigida pelo FDK, mas esta Function não usa
    corpo de requisição: toda a configuração vem do contexto da OCI Function.
    """

    # Lê a configuração obrigatória e resolve a região padrão quando não há override.
    try:
        cfg = ctx.Config()
        tenancy_id = cfg['OCI_TENANCY_OCID']
        destination_bucket = cfg["OCI_BUCKET_DESTINATION"]
        destination_prefix = normalize_prefix(cfg["OCI_BUCKET_ROOT_PATH"])
        destination_region = get_destination_region(cfg)
        if not destination_prefix or not destination_region:
            raise ValueError("Configuração de origem, destino ou região ausente")
    except Exception as error:
        error_msg = (
            "ERRO DE CONFIGURAÇÃO: Variáveis obrigatórias não encontradas no "
            f"contexto da função: {error}"
        )
        log_event(logging.ERROR, "configuration_failed", error=str(error))
        return make_response(ctx, error_msg, 400, "text/plain; charset=utf-8")

    # Cria o cliente autenticado pelo Resource Principal da própria Function.
    object_storage_client = get_oci_client(oci.object_storage.ObjectStorageClient)

    if not object_storage_client:
        return make_response(
            ctx, "Falha na inicialização do cliente OCI.", 503, "text/plain; charset=utf-8"
        )

    # Consulta o namespace do bucket de destino uma única vez por invocação.
    try:
        destination_namespace = object_storage_client.get_namespace().data
    except Exception as error:
        error_msg = f'ERRO DE OCI: Não foi possível obter o namespace: {error}'
        log_event(logging.ERROR, "namespace_lookup_failed", error=str(error))
        return make_response(ctx, error_msg, 502, "text/plain; charset=utf-8")
    # Mantém métricas de resultado e de custo da listagem para observabilidade.
    execution_stats = {
        "time": time.perf_counter(),
        "orig": 0,
        "dest": 0,
        "copy": 0,
        "update": 0,
        "same": 0,
        "erro": 0,
        "pending": 0,
        "unknown": 0,
        "conflict": 0,
        "metadata_incomplete": 0,
        "source_pages": 0,
        "destination_pages": 0,
        "destination_discarded": 0,
    }
    try:
        execution_lock = acquire_execution_lock(
            object_storage_client,
            destination_namespace,
            destination_bucket,
            destination_prefix,
        )
    except Exception as error:
        error_msg = f'ERRO DE OCI: Não foi possível criar o lock da execução: {error}'
        log_event(logging.ERROR, "lock_acquisition_failed", error=str(error))
        return make_response(ctx, error_msg, 502, "text/plain; charset=utf-8")

    if not execution_lock:
        error_msg = 'Execução já em andamento; tente novamente após a conclusão atual.'
        log_event(logging.WARNING, "execution_locked")
        return make_response(ctx, error_msg, 409, "text/plain; charset=utf-8")
    EXECUTION_LOCK.set(
        (object_storage_client, destination_namespace, destination_bucket, execution_lock)
    )

    # Faz merge dos fluxos ordenados, página a página. As páginas não precisam
    # coincidir: o nome relativo (ano/mês/dia/arquivo) é a chave da comparação.
    copy_requests = {}
    lock_relative_name = execution_lock[0][len(destination_prefix):]
    source_iterator = iter_relative_summaries(
        object_storage_client.list_objects,
        PUBLIC_REPORT_PREFIX,
        execution_stats,
        "source_pages",
        "orig",
        namespace_name=PUBLIC_NAMESPACE,
        bucket_name=tenancy_id,
        prefix=PUBLIC_REPORT_PREFIX,
        fields=OBJECT_SUMMARY_FIELDS,
    )
    try:
        source_current = next(source_iterator, None)
        if not source_current:
            # Sem arquivos na origem, não há caminho de destino a comparar.
            wait_for_copy_requests(object_storage_client, copy_requests, execution_stats)
            execution_stats["time"] = time.perf_counter() - execution_stats["time"]
            log_event(logging.INFO, "synchronization_completed", **execution_stats)
            return make_response(ctx, json.dumps(execution_stats), 200, "application/json")

        # Objetos anteriores ao primeiro arquivo da origem não podem corresponder
        # a ela. O ``start`` também deixa o objeto de lock fora da página útil.
        destination_iterator = iter_relative_summaries(
            object_storage_client.list_objects,
            destination_prefix,
            execution_stats,
            "destination_pages",
            "dest",
            skip_name=lock_relative_name,
            namespace_name=destination_namespace,
            bucket_name=destination_bucket,
            prefix=destination_prefix,
            start=f"{destination_prefix}{source_current[0]}",
            fields=OBJECT_SUMMARY_FIELDS,
        )
        destination_current = next(destination_iterator, None)
        while source_current:
            source_name, source_object = source_current
            while destination_current and destination_current[0] < source_name:
                # Arquivos históricos apenas no destino não exigem nenhuma ação.
                execution_stats["destination_discarded"] += 1
                destination_current = next(destination_iterator, None)

            destination_object = None
            if destination_current and destination_current[0] == source_name:
                destination_object = destination_current[1]
                destination_current = next(destination_iterator, None)

            if destination_object and objects_match(source_object, destination_object):
                execution_stats["same"] += 1
            else:
                submit_copy(
                    object_storage_client, tenancy_id, source_name, source_object,
                    destination_object, destination_namespace, destination_bucket,
                    destination_region, destination_prefix,
                    copy_requests, execution_stats,
                )

            source_current = next(source_iterator, None)

        while destination_current:
            execution_stats["destination_discarded"] += 1
            destination_current = next(destination_iterator, None)
    except RuntimeError as error:
        log_event(logging.ERROR, "object_merge_failed", error=str(error))
        return make_response(ctx, str(error), 502, "text/plain; charset=utf-8")

    # O polling só começa após submeter todas as cópias, reduzindo reconsultas.
    wait_for_copy_requests(object_storage_client, copy_requests, execution_stats)

    execution_stats["time"] = time.perf_counter() - execution_stats["time"]

    log_event(logging.INFO, "synchronization_completed", **execution_stats)
    return make_response(ctx, json.dumps(execution_stats), 200, "application/json")
