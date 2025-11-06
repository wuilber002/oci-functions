import oci
import json
import logging
from datetime import datetime

from fdk import response

# Get the logger for urllib3.connectionpool
urllib3_logger = logging.getLogger('oci._vendor.urllib3.connectionpool')

# Set the logging level to WARNING (or INFO, ERROR, CRITICAL)
urllib3_logger.setLevel(logging.WARNING)
urllib3_root_logger = logging.getLogger('oci._vendor.urllib3')
urllib3_root_logger.setLevel(logging.WARNING)

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

def get_paginated_data(list_function, tenancy_id, **kwargs):
    """
    Função genérica para extrair dados de endpoints paginados da OCI.
    Retorna uma lista de objetos 'summary'.
    """
    data = []
    try:
        response = oci.pagination.list_call_get_all_results(
            list_function,
            compartment_id=tenancy_id,
            # Inclui todos os subcompartimentos, essencial para o Cloud Advisor
            compartment_id_in_subtree=True, 
            **kwargs
        )
        
        if hasattr(response.data, 'items'):
             data.extend(response.data.items)
        else:
             data.extend(response.data) 
    except Exception as e:
        logging.getLogger().error(f'Erro ao buscar dados com {list_function.__name__}: {e}')
    return data

def upload_to_object_storage(object_storage_client, object_name, data, bucket_name, root_path):
    """Realiza o upload de dados JSON (lista de dicts) para o OCI Object Storage."""
    
    try:
        namespace = object_storage_client.get_namespace().data
    except Exception as e:
        logging.getLogger().error(f'Erro ao obter o namespace: {e}. Verifique as permissões de IAM para Object Storage.')
        return

    hoje = datetime.now()
    data_path = hoje.strftime("%Y/%m/%d")
    object_path = f"{root_path}/{data_path}/{object_name}"
    
    # Serializa os dados JSON (lista de dicts)
    data_json_str = json.dumps(data, indent=4)
    data_bytes = data_json_str.encode('utf-8')
    
    try:
        object_storage_client.put_object(
            namespace_name=namespace,
            bucket_name=bucket_name,
            object_name=object_path,
            put_object_body=data_bytes,
            content_type="application/json"
        )
    except oci.exceptions.ServiceError as e:
        logging.getLogger().error(f'Erro no Object Storage ao enviar {object_name}: {e}')
    except Exception as e:
        logging.getLogger().error(f'Erro desconhecido ao enviar {object_name}: {e}')

def download_mapping_file(object_storage_client, bucket_name, mapping_file_path):
    """Baixa o arquivo JSON de mapeamento do Object Storage e retorna o dicionário."""
    
    try:
        namespace = object_storage_client.get_namespace().data
    except Exception as e:
        logging.getLogger().error(f'Erro ao obter o namespace: {e}. Verifique as permissões de IAM para Object Storage.')
        return {}
    
    try:
        response = object_storage_client.get_object(
            namespace_name=namespace,
            bucket_name=bucket_name,
            object_name=mapping_file_path
        )
        mapping_data = response.data.content.decode('utf-8')
        return json.loads(mapping_data)
        
    except oci.exceptions.ServiceError as e:
        if e.status == 404:
            logging.getLogger().error(f'ATENÇÃO: Arquivo de mapeamento "{mapping_file_path}" (404 Not Found). Os campos não serão traduzidos.')
        else:
            logging.getLogger().error(f'Erro ao baixar o arquivo de mapeamento: {e}')
        return {}
    except Exception as e:
        logging.getLogger().error(f'Erro ao processar o JSON de mapeamento: {e}')
        return {}

def translate_data(data_list, mapping_dict):
    """
    Traduz os campos 'name' e 'description' dos objetos usando o dicionário.
    Retorna uma tupla: (lista de dicts traduzidos, estatísticas de tradução).
    """
    stats = {
        'total_items': len(data_list),
        'names_translated': 0,
        'descriptions_translated': 0
    }
    
    if not mapping_dict:
        # Se o dicionário estiver vazio, apenas converte para dict e retorna
        return [oci.util.to_dict(item) for item in data_list], stats

    translated_list = []
    
    for item in data_list:
        item_dict = oci.util.to_dict(item)
        
        # 1. Aplica a tradução para 'name'
        if 'name' in item_dict:
            key = item_dict['name']
            translated_name = mapping_dict.get(key, key)
            if translated_name != key:
                item_dict['name'] = translated_name
                stats['names_translated'] += 1
            
        # 2. Aplica a tradução para 'description'
        if 'description' in item_dict:
            key = item_dict['description']
            translated_desc = mapping_dict.get(key, key)
            if translated_desc != key:
                item_dict['description'] = translated_desc
                stats['descriptions_translated'] += 1

        translated_list.append(item_dict)
    return translated_list, stats

# ---------------------------------------------------
# HANDLER PRINCIPAL DA OCI FUNCTION
# ---------------------------------------------------

def handler(ctx, data):
    """
    Ponto de entrada principal da OCI Function.
    """
    
    # 1. Leitura das Variáveis de Configuração
    try:
        cfg = ctx.Config()
        bucket_name = cfg["OCI_BUCKET_DESTINATION"]
        root_path = cfg["OCI_BUCKET_ROOT_PATH"]
        tenancy_id = cfg["OCI_TENANCY_OCID"]
        mapping_file_path = cfg["CLOUD_ADVISOR_MAPPING_FILE_PATH"]
    except Exception as e:
        error_msg=f'ERRO DE CONFIGURAÇÃO: Variáveis obrigatórias não encontradas no contexto da função: {e}'
        logging.getLogger().error(error_msg)
        return response.Response(ctx, response_data=error_msg,
            headers={"Content-Type": "text/plain; charset=utf-8"}
        )

    # 2. Inicializa os clientes e verifica a autenticação
    optimizer_client = get_oci_client(oci.optimizer.OptimizerClient)
    object_storage_client = get_oci_client(oci.object_storage.ObjectStorageClient)
    
    if not optimizer_client or not object_storage_client:
        # Se a autenticação falhou, o erro já foi impresso em get_oci_client
        return response.Response(ctx, response_data=f'Falha na inicialização dos clients OCI.',
            headers={"Content-Type": "text/plain; charset=utf-8"}
        )

    # 3. Inicializa o contador global
    GLOBAL_STATS = {
        'categories_names': 0,
        'categories_descriptions': 0,
        'categories_total': 0,
        'recommendations_names': 0,
        'recommendations_descriptions': 0,
        'recommendations_total': 0,
        'resource_actions_total': 0
    }

    # 4. Baixa o dicionário de mapeamento
    mapping_dict = download_mapping_file(object_storage_client, bucket_name, mapping_file_path)

    # 5. Extrai e Traduz Category Summaries
    logging.getLogger().info(f'>> 1/3: Extraindo e Traduzindo "Category Summaries"...')
    categories_oci = get_paginated_data(optimizer_client.list_categories, tenancy_id)
    categories_translated, cat_stats = translate_data(categories_oci, mapping_dict)
    upload_to_object_storage(object_storage_client, "categories.json", categories_translated, bucket_name, root_path)
    
    # Atualiza as estatísticas globais
    GLOBAL_STATS['categories_names'] = cat_stats['names_translated']
    GLOBAL_STATS['categories_descriptions'] = cat_stats['descriptions_translated']
    GLOBAL_STATS['categories_total'] = cat_stats['total_items']

    # 6. Extrai e Traduz Recommendation Summaries
    logging.getLogger().info(f'>> 2/3: Extraindo e Traduzindo "Recommendation Summaries"...')
    recommendations_oci = get_paginated_data( optimizer_client.list_recommendations, tenancy_id)
    recommendations_translated, rec_stats = translate_data(recommendations_oci, mapping_dict)
    upload_to_object_storage(object_storage_client, "recommendations.json", recommendations_translated, bucket_name, root_path)
    
    # Atualiza as estatísticas globais
    GLOBAL_STATS['recommendations_names'] = rec_stats['names_translated']
    GLOBAL_STATS['recommendations_descriptions'] = rec_stats['descriptions_translated']
    GLOBAL_STATS['recommendations_total'] = rec_stats['total_items']

    # 7. Extrai Resource Action Summaries (LISTA COMPLETA) - SEM TRADUÇÃO
    logging.getLogger().info(f'>> 3/3: Extraindo "Resource Action Summaries"...')
    resource_actions_oci = get_paginated_data(optimizer_client.list_resource_actions, tenancy_id)

    # Converte os objetos OCI brutos para dicionários Python para serialização
    resource_actions_raw = [oci.util.to_dict(item) for item in resource_actions_oci]
    upload_to_object_storage(object_storage_client, "resource_actions.json", resource_actions_raw, bucket_name, root_path)

    # Atualiza as estatísticas globais
    GLOBAL_STATS['resource_actions_total'] = len(resource_actions_raw)

    # 8. Resumo das estatísticas (retorno para o servico OCI Functions)
    if GLOBAL_STATS['categories_total'] == 0 or GLOBAL_STATS['recommendations_total'] == 0 or GLOBAL_STATS['resource_actions_total'] == 0:
        return {
            "status": "FAILED",
            "message": f"Falha na extracao de dados: Categories:{GLOBAL_STATS['categories_total']}, Recomendations:{GLOBAL_STATS['recommendations_total']}, Actions:{GLOBAL_STATS['resource_actions_total']}. Verifique os logs para mais detalhes."
        }, 404
    else:
        return response.Response(
            ctx, 
            response_data=json.dumps(GLOBAL_STATS),
            headers={"Content-Type": "application/json"}
        )