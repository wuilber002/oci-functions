import os
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

# Optionally, if you also want to silence other urllib3 logs, you can target the broader 'urllib3' logger
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

# ==============================================================================
# função principal:
def handler(ctx, data: io.BytesIO=None):
    
    # -------------------------------------------------------------------------
    # Controle de estatísticas
    execusion_stat={
        'time': time.perf_counter(),
        'orig':0,
        'dest':0,
        'copy':0,
        'erro':0
    }

    # ---------------------------------------------------------------------
    # Carrega as variáveis de ambiente configuradas na função
    try:
        OCI_BUCKET_DESTINATION = os.getenv('OCI_BUCKET_DESTINATION')
        oci_config = {'tenancy': os.getenv('OCI_TENANCY_OCID')}
    except (Exception, ValueError) as ex:
        logging.getLogger().error(str(ex))

    # -------------------------------------------------------------
    # Autenticação via instance principal
    signer = oci.auth.signers.get_resource_principals_signer()
    oci_config['region'] = signer.region

    object_storage_client = oci.object_storage.ObjectStorageClient(
        config=oci_config,
        signer=signer,
        retry_strategy=CUSTOM_RETRY_STRATEGY
    )

    # -------------------------------------------------------------
    # Consulta o namespace do tenancy
    OCI_NAMESPACE = object_storage_client.get_namespace().data

    # -------------------------------------------------------------
    # Lista os arquivos disponiveis no bucket da ORACLE onde os arquivos
    # de billing são armazenados.
    oci_os_list_objects_resp = oci.pagination.list_call_get_all_results(
        object_storage_client.list_objects,
        namespace_name="bling",
        bucket_name=oci_config['tenancy'],
        prefix="FOCUS Reports"
    ).data

    bling_objects = list()
    for object in oci_os_list_objects_resp.objects:
        bling_objects.append(object.name)
    execusion_stat['orig'] = len(bling_objects)

    # -------------------------------------------------------------
    # Lista os arquivos disponiveis no bucket de destino, onde os 
    # arquivos de billing serão armazenados/arquivados.
    oci_os_list_objects_resp = oci.pagination.list_call_get_all_results(
        object_storage_client.list_objects,
        namespace_name=OCI_NAMESPACE,
        bucket_name=OCI_BUCKET_DESTINATION,
        prefix="FOCUS Reports"
    ).data

    archive_objects = list()
    for object in oci_os_list_objects_resp.objects:
        archive_objects.append(object.name)
    execusion_stat['dest'] = len(archive_objects)

    # -------------------------------------------------------------
    # Hora de verificar quais arquivos precisam ser copiados
    for bling_object in bling_objects:
        if not bling_object in archive_objects:
            copy_object_response = object_storage_client.copy_object(
                namespace_name="bling",
                bucket_name=oci_config['tenancy'],
                copy_object_details=oci.object_storage.models.CopyObjectDetails(
                    source_object_name=bling_object,
                    destination_region=oci_config['region'],
                    destination_namespace=OCI_NAMESPACE,
                    destination_bucket=OCI_BUCKET_DESTINATION,
                    destination_object_name=bling_object
                )
            )
            if copy_object_response.status != 202:
                logging.getLogger().error(f'Erro ao cópiar "{bling_object}". Status: {copy_object_response.status}')
                execusion_stat['erro'] += 1
            else:
                logging.getLogger().info(f'Arquivo "{bling_object}" copiado. Status: {copy_object_response.status}')
                execusion_stat['copy'] += 1

    execusion_stat['time'] = (time.perf_counter() - execusion_stat['time'])

    logging.getLogger().info(json.dumps(execusion_stat))

    return response.Response(
        ctx, 
        response_data=json.dumps(execusion_stat),
        headers={"Content-Type": "application/json"}
    )
