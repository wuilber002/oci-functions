import io
import oci
import time
import json
import logging

from fdk import response

# Get the logger for urllib3.connectionpool
urllib3_logger = logging.getLogger('oci._vendor.urllib3.connectionpool')

# Set the logging level to WARNING (or INFO, ERROR, CRITICAL)
urllib3_logger.setLevel(logging.WARNING)
urllib3_root_logger = logging.getLogger('oci._vendor.urllib3')
urllib3_root_logger.setLevel(logging.ERROR)

# -----------------------------------------------------------------------------
# https://docs.oracle.com/en-us/iaas/tools/python/2.155.0/sdk_behaviors/retries.html
CUSTOM_RETRY_STRATEGY = oci.retry.RetryStrategyBuilder(
    # Make up to 10 service calls
    max_attempts_check=True,
    max_attempts=10,

    # Don't exceed a total of 600 seconds for all service calls
    total_elapsed_time_check=True,
    total_elapsed_time_seconds=600,

    # Wait 45 seconds between attempts
    retry_max_wait_between_calls_seconds=45,

    # Use 2 seconds as the base number for doing sleep time calculations
    retry_base_sleep_time_seconds=2,

    # Retry on certain service errors:
    #
    #   - 5xx code received for the request
    #   - Any 429 (this is signified by the empty array in the retry config)
    #   - 400s where the code is QuotaExceeded or LimitExceeded
    service_error_check=True,
    service_error_retry_on_any_5xx=True,
    service_error_retry_config={
        400: ['QuotaExceeded', 'LimitExceeded'],
        429: []
    },

    # Use exponential backoff and retry with full jitter, but on throttles use
    # exponential backoff and retry with equal jitter
    backoff_type=oci.retry.BACKOFF_FULL_JITTER_EQUAL_ON_THROTTLE_VALUE
).get_retry_strategy()

def get_oci_client(service_client):
    """Cria e retorna o cliente OCI usando autenticação de Instance Principal."""
    # Instance Principal é o mecanismo de autenticação padrão e mais seguro para OCI Functions.
    try:
        signer = oci.auth.signers.get_resource_principals_signer()
        return service_client(
            config={},
            signer=signer,
            retry_strategy=CUSTOM_RETRY_STRATEGY
        )
    except Exception as e:
        # Se a autenticação falhar (normalmente por falta de Dynamic Group/Policy)
        logging.getLogger().error(f'ERRO DE AUTENTICAÇÃO: Falha ao obter credenciais de Instance Principal. Detalhes: {e}')
        # O retorno False será capturado no handler principal
        return False

def get_paginated_data(list_function, **kwargs):
    """
    Função genérica para extrair dados de endpoints paginados da OCI.
    Retorna uma lista de objetos 'summary'.
    """
    try:
        return(
            oci.pagination.list_call_get_all_results(
                list_function,
                **kwargs
            ).data
        )
    except Exception as e:
        logging.getLogger().error(f'Erro ao buscar dados com {list_function.__name__}: {e}')
        return(list())

# ---------------------------------------------------
# HANDLER PRINCIPAL DA OCI FUNCTION
# ---------------------------------------------------
def handler(ctx, data: io.BytesIO=None):
    """
    Ponto de entrada principal da OCI Function.
    """

    # 1. Leitura das Variáveis de Configuração
    try:
        cfg = ctx.Config()
        tenancy_id = cfg['OCI_TENANCY_OCID']
        oci_bucket_destination = cfg['OCI_BUCKET_DESTINATION']
        oci_bucket_destination_root_path = cfg["OCI_BUCKET_ROOT_PATH"]
        oci_resource_principal_region = cfg["OCI_RESOURCE_PRINCIPAL_REGION"]
    except Exception as e:
        error_msg=f'ERRO DE CONFIGURAÇÃO: Variáveis obrigatórias não encontradas no contexto da função: {e}'
        logging.getLogger().error(error_msg)
        return response.Response(ctx, response_data=error_msg,
            headers={"Content-Type": "text/plain; charset=utf-8"}
        )

    # 2. Inicializa os clientes e verifica a autenticação
    object_storage_client = get_oci_client(oci.object_storage.ObjectStorageClient)

    if not object_storage_client:
        # Se a autenticação falhou, o erro já foi impresso em get_oci_client
        return response.Response(ctx, response_data=f'Falha na inicialização do client OCI.',
            headers={"Content-Type": "text/plain; charset=utf-8"}
        )

    # 3. Inicializa o contador global e constantes
    OCI_BUCKET_PUBLIC_NAMESPACE = "bling"
    OCI_BUCKET_PUBLIC_ROOT_PATH = 'FOCUS Reports'
    OCI_NAMESPACE = object_storage_client.get_namespace().data
    execusion_stat={
        'time': time.perf_counter(),
        'orig':0,
        'dest':0,
        'copy':0,
        'erro':0
    }

    # 4. Lista os arquivos disponiveis no bucket da ORACLE onde
    # os arquivos de billing são armazenados.
    oci_os_list_objects_resp = get_paginated_data(
        object_storage_client.list_objects,
        namespace_name=OCI_BUCKET_PUBLIC_NAMESPACE,
        bucket_name=tenancy_id,
        prefix=OCI_BUCKET_PUBLIC_ROOT_PATH
    )
    bling_objects = list()
    for object in oci_os_list_objects_resp.objects:
        bling_objects.append(object.name.replace(OCI_BUCKET_PUBLIC_ROOT_PATH,''))
    execusion_stat['orig'] = len(bling_objects)

    # 5. Lista os arquivos disponiveis no bucket de destino, onde os 
    # arquivos de billing serão armazenados/arquivados.
    oci_os_list_objects_resp = get_paginated_data(
        object_storage_client.list_objects,
        namespace_name=OCI_NAMESPACE,
        bucket_name=oci_bucket_destination,
        prefix=oci_bucket_destination_root_path
    )
    archive_objects = list()
    for object in oci_os_list_objects_resp.objects:
        archive_objects.append(object.name.replace(oci_bucket_destination_root_path,''))
    execusion_stat['dest'] = len(archive_objects)

    # 6. Verifica quais arquivos precisam ser copiados e os copia
    for bling_object in bling_objects:
        if not bling_object in archive_objects:
            OBJECT_SRC=f'{OCI_BUCKET_PUBLIC_ROOT_PATH}{bling_object}'
            OBJECT_DST=f'{oci_bucket_destination_root_path}{bling_object}'
            copy_object_response = object_storage_client.copy_object(
                namespace_name="bling",
                bucket_name=tenancy_id,
                copy_object_details=oci.object_storage.models.CopyObjectDetails(
                    source_object_name=OBJECT_SRC,
                    destination_region=oci_resource_principal_region,
                    destination_namespace=OCI_NAMESPACE,
                    destination_bucket=oci_bucket_destination,
                    destination_object_name=OBJECT_DST
                )
            )
            if copy_object_response.status != 202:
                logging.getLogger().error(f'Erro ao cópiar "{bling_object}". Status: {copy_object_response.status}')
                execusion_stat['erro'] += 1
            else:
                logging.getLogger().info(f'Arquivo "{OBJECT_DST}" copiado. Status: {copy_object_response.status}')
                execusion_stat['copy'] += 1

    execusion_stat['time'] = (time.perf_counter() - execusion_stat['time'])

    logging.getLogger().info(json.dumps(execusion_stat))

    return response.Response(
        ctx, 
        response_data=json.dumps(execusion_stat),
        headers={"Content-Type": "application/json"}
    )
