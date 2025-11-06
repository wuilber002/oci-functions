<h1> OCI Function: FinOps - Cloud Advisor Extractor </h1>

[View this README in English](./readme_en-US.md) <span>&#127482;&#127480;</span>

Este conjunto de arquivos contém uma ***Function*** em Python desenvolvida para automatizar o processo de *download* e *upload* das recomendações, categorias e ações recomendadas pelo **Cloud Advisor** da sua *Tenancy* OCI para um *bucket* dentro da mesma *tenancy*.

<h3> Isenção de responsabilidade </h3>

Antes de prosseguir, é fundamental ter em mente que a utilização de quaisquer *scripts*, códigos ou comandos contidos neste repositório é de sua total responsabilidade. Os autores dos códigos não se responsabilizam por quaisquer ônus decorrentes do uso do conteúdo aqui disponibilizado.

**Recomendamos testar** todo o conteúdo em um ambiente apropriado e integrar os *scripts* de automação a uma infraestrutura de monitoramento robusta, a fim de acompanhar o funcionamento do processo e mitigar possíveis falhas.

Este projeto **não é um aplicativo oficial da Oracle** e, portanto, não possui suporte formal. A Oracle não se responsabiliza por nenhum conteúdo aqui presente.

<h2> Visão geral </h2>

<h3>Index</h3>

- [Requirements](#requirements)
  - [Permissions](#permissions)
  - [Networking](#networking)
- [Overview](#overview)
  - [Data Mapping and Localization](#data-mapping-and-localization)
- [Project files](#project-files)
- [Cloud Shell](#cloud-shell)
  - [Architecture X86\_64](#architecture-x86_64)
  - [Environment variables](#environment-variables)
- [Work Directory](#work-directory)
- [Clone the Git repository](#clone-the-git-repository)
- [Function Application](#function-application)
- [OCI Function: context](#oci-function-context)
- [OCI Container Registry](#oci-container-registry)
- [Bucket](#bucket)
- [Function](#function)
  - [Files](#files)
  - [Build](#build)
  - [Configuration](#configuration)
  - [Dynamic Group for Function](#dynamic-group-for-function)
  - [Policy for Function](#policy-for-function)
- [Resource Scheduler](#resource-scheduler)
  - [Dynamic Group for Resource Scheduler](#dynamic-group-for-resource-scheduler)
  - [Policy for Resource Scheduler](#policy-for-resource-scheduler)
  - [Using existing scheduling](#using-existing-scheduling)
- [Testing](#testing)
- [Logging](#logging)

## Requirements

Para dar continuidade a este procedimento, é necessário **cumprir os requisitos** a seguir:

### Permissions

As permissões são divididas em dois grupos de ações:

- **Para Criação de Recursos:**
  - Bucket
  - Grupo Dinâmico (*Dynamic Group*)
  - Política de Acesso (*Policy*)
  - Function
  - OCI Container Registry
  - Resource Scheduler

- **Para Acesso a Recursos:**
  - Cloud Shell

### Networking

É mandatório que você possua uma **VCN** criada com uma **Subnet** que tenha endereços IP disponíveis para alocar a *Function*. Essa *Subnet* deve possuir **acesso à internet** ou ter um **Gateway de Serviços** ativo.

## Overview

O *script* em Python, projetado para ser executado no serviço *serverless* **OCI Functions**, realiza a extração de dados da API do OCI utilizando as seguintes chamadas:

- [**`OCI Optimizer: list-categories`**](https://oracle-cloud-infrastructure-python-sdk.readthedocs.io/en/latest/api/optimizer/client/oci.optimizer.OptimizerClient.html#oci.optimizer.OptimizerClient.list_categories)
- [**`OCI Optimizer: list-recommendations`**](https://oracle-cloud-infrastructure-python-sdk.readthedocs.io/en/latest/api/optimizer/client/oci.optimizer.OptimizerClient.html#oci.optimizer.OptimizerClient.list_recommendations)
- [**`OCI Optimizer: list-resource-actions`**](https://oracle-cloud-infrastructure-python-sdk.readthedocs.io/en/latest/api/optimizer/client/oci.optimizer.OptimizerClient.html#oci.optimizer.OptimizerClient.list_resource_actions)

### Data Mapping and Localization

Após a extração das listas de categorias e recomendações, o *script* utiliza um arquivo de mapeamento (*mapping*/dicionário) externo para traduzir os valores programáticos (*chaves*) retornados pela API nos campos de nome e descrição para valores **humanizados** (legíveis pelo usuário).

Este arquivo de mapeamento precisa ser **disponibilizado no mesmo *bucket*** utilizado pela OCI Function como destino para os arquivos extraídos. Mais informações serão fornecidas ao longo desse documento.

> [!WARNING]
**É mandatório** que o arquivo de mapeamento seja **periodicamente validado**. Novas categorias ou recomendações disponibilizadas pela Oracle **não serão traduzidas automaticamente** e precisam ser inseridas manualmente no dicionário para garantir a precisão dos dados.

![OCI Cloud Shell: Open](images/oci-function-execution-flow.png)

![OCI Cloud Shell: Open](images/cloud-advisor-field-mapping.png)

## Project files

A seguir estão os arquivos que compõem o projeto. Apenas quatro são essenciais; o `readme.md` pode ser ignorado no processo de implantação.

```BASH
.
├── cloud-advisor-mapping.json
├── func.py
├── func.yaml
├── readme.md
└── requirements.txt
```

| Item | Descrição |
|------|-----------|
|readme.md|Este arquivo de documentação e auxílio.|
|**func.py**|O *script* em Python que será executado pela *function*.|
|**func.yaml**|O arquivo de configurações e características para a criação da *function*.|
|**requirements.txt**|A lista de módulos Python necessários para a execução do *script* `func.py`.|
|**cloud-advisor-mapping.json**|Arquivo de mapping (dicionário) para os nomes e descrições das recomendações e categorias do *Cloud Advisor*.|

## Cloud Shell

Para iniciar a criação e a configuração dos recursos, **abra o Cloud Shell**.

![OCI Cloud Shell: Open](images/oci-cloud-shell_open.gif)

### Architecture X86\_64

Para o correto funcionamento dos recursos envolvidos neste procedimento, utilizaremos a **arquitetura x86\_64** como padrão.

![OCI Cloud Shell: Open](images/oci-cloud-shell_change_arch.gif)

**Valide a arquitetura** com o comando abaixo. O retorno esperado é "x86\_64:OK" para a configuração correta.

```BASH
[ "$(uname -m)" == "x86_64" ] && echo "$(uname -m):OK" || echo "$(uname -m):ERRO"
```

### Environment variables

Antes de criar as variáveis de ambiente, verifique se todas foram configuradas corretamente.

```BASH
export FN_APP_NAME='FinOps'
export FN_FUNC_NAME='Cloud-Advisor-Extractor'
export OCI_DOMAIN_NAME='Default'
export OCI_USERNAME='user.name@domain.com'
export OCI_BUCKET_NAME_DESTINATION='FinOps-Billing-Report'
export OCI_COMPARTMENT='ocid1.compartment.oc1..aaaaaaaa7_____1604'
export OCI_SUBNET='ocid1.subnet.oc1.<region>.aaaaaaaau_____1604'
export OCI_REPO_NAME="${FN_APP_NAME,,}_${FN_FUNC_NAME,,}"
export OCI_NAMESPACE=$(oci os ns get --raw-output --query 'data')
export OCI_BUCKET_ROOT_PATH='Cloud-Advisor'
export CLOUD_ADVISOR_MAPPING_FILE='cloud-advisor-mapping.json'
export CLOUD_ADVISOR_MAPPING_FILE_PATH='Dictionaries'

export OCI_USERNAME='igor.nicoli@gmail.com'
export OCI_COMPARTMENT='ocid1.compartment.oc1..aaaaaaaa7svbe2mrmcrmuaurzwup6dhs3xoer6jolwkgeu7fl4wxlnezwwba'
export OCI_SUBNET='ocid1.subnet.oc1.sa-saopaulo-1.aaaaaaaao6pdxdracwf42e22ryumuylaoyxnpwkosdxvqy6u4hlpcfzpq7xq'

set|grep -E '^(FN_APP_NAME|FN_FUNC_NAME|OCI_DOMAIN_NAME|OCI_USERNAME|OCI_BUCKET_NAME_DESTINATION|OCI_COMPARTMENT|OCI_SUBNET|OCI_REPO_NAME|OCI_NAMESPACE|OCI_BUCKET_ROOT_PATH|CLOUD_ADVISOR_MAPPING_FILE|CLOUD_ADVISOR_MAPPING_FILE_PATH|OCI_REGION|OCI_TENANCY)'
```

| Variavel | Descricao |
|-|-|
|**FN_APP_NAME**                    |Nome da Application onde as functions serão criadas.|
|**FN_FUNC_NAME**                   |Nome da **OCI Function**.|
|**OCI_DOMAIN_NAME**                |Nome do domínio no qual o usuário utilizado está criado.|
|**OCI_USERNAME**                   |Nome do usuário a ser utilizado para a autenticação no **OCI Registry**. Este usuário será utilizado apenas durante o processo de configuração.|
|**OCI_BUCKET_NAME_DESTINATION**    |Nome do **Bucket** que será utilizado para armazenar os arquivos extraidos pela **OCI Function**.|
|**OCI_COMPARTMENT**                |OCID (*Oracle Cloud Identifier*) do ***compartment*** onde todos os recursos (Function Application, OCI Function, OCI Registry, etc.) serão criados.|
|**OCI_SUBNET**                     |OCID (*Oracle Cloud Identifier*) da ***subnet*** na qual a *function* será criada.|
|**OCI_REPO_NAME**                  |Nome do repositório no **OCI Registry** para armazenar as *images* da *function*.|
|**OCI_NAMESPACE**                  |Nome do *namespace* do **Object Storage** do Tenancy.|
|**OCI_BUCKET_ROOT_PATH**           |Nome do **diretor raiz** do bucket de destino para os arquivos do Cloud Advisor.|
|**CLOUD_ADVISOR_MAPPING_FILE**     |Nome do **arquivo de mapping** (dicionário) do Cloud Advisor.|
|**CLOUD_ADVISOR_MAPPING_FILE_PATH**|Caminho para o **arquivo de mapping** (dicionário) do Cloud Advisor.|

Além dessas, serão utilizadas outras variáveis que já são previamente definidas no Cloud Shell da OCI:

| Variavel | Descricao |
|-|-|
| **OCI_REGION** |Nome completo da região na qual o *Cloud Shell* está conectado.|
| **OCI_TENANCY** |OCID (*Oracle Cloud Identifier*) do *Tenancy* à qual estamos logados no *Cloud Shell*.|

## Work Directory

Vamos **criar um diretório** para organizar todos os nossos arquivos e, em seguida, iniciar a **criação dos nossos arquivos** e o *build* da nossa *function*.

```BASH
mkdir -p ~/oci-functions/${FN_FUNC_NAME,,}
cd ~/oci-functions/${FN_FUNC_NAME,,}
```

## Clone the Git repository

Efetue o clone desse repositorio git ou disponibilize todos os arquivos mencionandos no topico [Project files](#project-files) em nosso diretorio de trabalho.

```BASH
git clone https://github.com/wuilber002/oci-functions.git
```

## Function Application

Crie uma **FN Application** com a arquitetura x86\_64 para hospedar a *function*.  Se já possuir uma, *export* o OCID (*Oracle Cloud Identifier*) para a variável de ambiente ***FN_APP_OCID*** e o nome para ***FN_APP_NAME*** para facilitar o uso posterior.

Para criar a *application*, utilize o comando abaixo, que já exporta o OCID (*Oracle Cloud Identifier*) para uma variável de ambiente.

```BASH
export FN_APP_OCID=$(oci fn application create \
--display-name ${FN_APP_NAME} \
--compartment-id ${OCI_COMPARTMENT} \
--subnet-ids "[\"${OCI_SUBNET}\"]" \
--shape "GENERIC_X86" \
--raw-output \
--query 'data.id')

set | grep -E '^(FN_APP_OCID)'
```

## OCI Function: context

É necessário realizar algumas **configurações de contexto** para o cliente `fn` do OCI Functions.

```BASH
fn use context ${OCI_REGION}
fn update context oracle.compartment-id ${OCI_COMPARTMENT}
fn update context registry ${OCI_REGION}.ocir.io/${OCI_NAMESPACE}/${OCI_REPO_NAME}
fn update context oracle.image-compartment-id ${OCI_COMPARTMENT}
fn list context
```

## OCI Container Registry

É fundamental utilizar um **Auth Token como senha** durante o processo de *login* no **OCI Container Registry**.

Caso você não possua um *Auth Token* criado, gere um novo utilizando o seguinte comando:

```BASH
oci iam auth-token create \
--user-id ${OCI_CS_USER_OCID} \
--description "OCI Container Registry" \
--raw-output \
--query 'data.token'
```

Este é o comando para efetuar o *login* no **OCI Container Registry**:

> [!TIP]
> Caso você tenha acabado de criar o **Auth Token**, **aguarde alguns minutos** antes de utilizá-lo. Pode levar um tempo até que o *token* seja propagado e esteja pronto para efetuar *login* no OCI Container Registry.

```BASH
docker login -u "${OCI_NAMESPACE}/${OCI_DOMAIN_NAME}/${OCI_USERNAME}" ${OCI_REGION}.ocir.io
```

## Bucket

Este *Bucket* receberá todos os arquivos extraidos do serviço **Cloud Advisor** para a *Tenancy*.

Caso você já possua o *Bucket* criado, voce pode pular essa parte e export a variavel **OCI_BUCKET_NAME_DESTINATION** com o nome do seu bucket. Caso contrario, crie o bucket com o mando abaixo:

```BASH
oci os bucket create --name ${OCI_BUCKET_NAME_DESTINATION} \
--storage-tier "STANDARD" \
--namespace-name ${OCI_NAMESPACE} \
--compartment-id ${OCI_COMPARTMENT}
```

Agora vamos subir o arquivo de *mapping* (Dicionario) para o bucket no **PATH** especificado no inicio desse procedimento na variavel de ambiente **${CLOUD_ADVISOR_MAPPING_FILE_PATH}**

Utilize o comando abaixo para fazer o upload do arquivo de mapping para o bucket que acabamos de criar:

```BASH
oci os object put \
-bn ${OCI_BUCKET_NAME_DESTINATION} \
--file ${CLOUD_ADVISOR_MAPPING_FILE} \
--name "${CLOUD_ADVISOR_MAPPING_FILE_PATH}/${CLOUD_ADVISOR_MAPPING_FILE}"
```

## Function

### Files

Você precisar ter os arquivos abaixo em seu diretório de trabalho no Cloud Shell. A função desses arquivos foi detalhada na seção [Project files](#project-files).

- `func.py`
- `func.yaml`
- `requirements.txt`

Caso você não tenha os arquivos `func.yaml` e `requirements.txt`, você pode cria-los com os comandos abaixo:

```BASH
cat << EOF > requirements.txt
oci>=2.155
fdk
EOF
```

```BASH
cat << EOF > func.yaml
schema_version: 20180708
name: ${FN_FUNC_NAME,,}
version: 0.0.1
runtime: python
entrypoint: /python/bin/fdk /function/func.py handler
memory: 128
timeout: 300
EOF
```

O arquivo `func.py` precisa ser enviado (via *upload*), se você não fez o clone do repositório, para o nosso **diretório de trabalho** (*work directory*).

![Cloud Shell Upload Steps](images/oci-cloud-shell_upload.gif)

Após realizar o upload utilizando o botão no canto superior direito, mova o arquivo para o **diretório de trabalho** (*work directory*) criado anteriormente.

```BASH
mv ~/func.py .
```

### Build

O próximo comando executará as seguintes etapas:

- Cria a *image* da *function* com Python e todos os módulos listados em `requirements.txt`.
- Cria o repositório no **OCI Container Registry** para o *upload* da *image*.
- Cria a *function* com as características definidas em `func.yaml` dentro da **Function Application**.

```BASH
fn --verbose deploy --app "${FN_APP_NAME}"
```

Após a conclusão bem-sucedida do *build* e do *deploy* da *image* da *function*, é necessário **obter o OCID** (*Oracle Cloud Identifier*) da *function* para liberar seu acesso aos recursos necessários.

Execute o comando abaixo para **consultar o OCID** (*Oracle Cloud Identifier*) da *function*:

```BASH
export FN_FUNC_OCID=$(oci fn function list \
--application-id ${FN_APP_OCID} \
--raw-output \
--query "data[?contains(\"display-name\", '${FN_FUNC_NAME,,}')].id | [0]")

set | grep -E '^(FN_FUNC_OCID)'
```

### Configuration

Para garantir a flexibilidade da solução, a *function* utilizará **variáveis** para receber dados que podem variar em cada *tenancy*.

| Variavel | Descrição |
|----------|-----------|
|OCI_BUCKET_DESTINATION|Nome do *Bucket* que será utilizado para **armazenar os arquivos extraídos pela OCI Function**.|
|OCI_TENANCY_OCID|O **OCID** (*Oracle Cloud Identifier*) da *Tenancy*.|
|OCI_BUCKET_ROOT_PATH|Nome da pasta "raiz" localizada no "Bucket" que ira receber os arquivos extraídos pela OCI Function.|
|CLOUD_ADVISOR_MAPPING_FILE_PATH|Caminho completo dentro do *Bukcet* para o arquivo de *mapping* de dados, que mapeia os nomes e descrições das recomendações e categorias do *Cloud Advisor*.|

```BASH
fn config function ${FN_APP_NAME} ${FN_FUNC_NAME,,} OCI_BUCKET_DESTINATION ${OCI_BUCKET_NAME_DESTINATION}
fn config function ${FN_APP_NAME} ${FN_FUNC_NAME,,} OCI_TENANCY_OCID ${OCI_TENANCY}
fn config function ${FN_APP_NAME} ${FN_FUNC_NAME,,} OCI_BUCKET_ROOT_PATH ${OCI_BUCKET_ROOT_PATH}
fn config function ${FN_APP_NAME} ${FN_FUNC_NAME,,} CLOUD_ADVISOR_MAPPING_FILE_PATH "${CLOUD_ADVISOR_MAPPING_FILE_PATH}/${CLOUD_ADVISOR_MAPPING_FILE}"
```

### Dynamic Group for Function

Para **conceder as permissões** necessárias para a *function* acessar o serviço do *Cloud Advisor* e o *bucket* de destino, é fundamental criar um **Grupo Dinâmico (Dynamic Group)**, conforme o comando abaixo:

```BASH
export DYG_FUNCTION="DYG_${FN_APP_NAME}_${FN_FUNC_NAME}_Function"

oci iam dynamic-group create \
--name ${DYG_FUNCTION} \
--description "Dynamic group para a function que extrai as recomendações do Cloud Advisor." \
--matching-rule "ALL {resource.type = 'fnfunc', resource.id = '${FN_FUNC_OCID}'}"
```

> [!NOTE]
A **`matching-rule`** deste **Grupo Dinâmico** selecionará exclusivamente nossa *function*, independentemente do *compartment* de criação.

### Policy for Function

Esta política de acesso concederá à *function* a liberação para consultar a API do **Cloud Advisor** e o *bucket* de destino, utilizando o grupo dinâmico criado.

```BASH
cat <<EOF > /tmp/function_cloud_advisor_extractor.policy
[
    "Allow dynamic-group ${DYG_FUNCTION} to {OPTIMIZER_CATEGORY_INSPECT, OPTIMIZER_RECOMMENDATION_INSPECT, OPTIMIZER_RESOURCE_ACTION_INSPECT} in tenancy",
    "Allow dynamic-group ${DYG_FUNCTION} to read buckets in compartment id ${OCI_COMPARTMENT} WHERE target.bucket.name='${OCI_BUCKET_NAME_DESTINATION}'",
    "Allow dynamic-group ${DYG_FUNCTION} to manage objects in compartment id ${OCI_COMPARTMENT} WHERE ALL {target.bucket.name='${OCI_BUCKET_NAME_DESTINATION}', target.object.name='${OCI_BUCKET_ROOT_PATH}/*'}",
    "Allow dynamic-group ${DYG_FUNCTION} to read objects in compartment id ${OCI_COMPARTMENT} WHERE ALL {target.bucket.name='${OCI_BUCKET_NAME_DESTINATION}', target.object.name = '"${CLOUD_ADVISOR_MAPPING_FILE_PATH}/${CLOUD_ADVISOR_MAPPING_FILE}"'}"
]
EOF

export POL_NAME="POL_${FN_APP_NAME}_${FN_FUNC_NAME}_Function"

oci iam policy create \
--name "${POL_NAME}" \
--description "Permissoes para a function que extrai as recomendacoes do Cloud Advisor." \
--compartment-id ${OCI_TENANCY} \
--statements file:///tmp/function_cloud_advisor_extractor.policy
```

## Resource Scheduler

Para a execução automatizada, utilizaremos o serviço PaaS de **Agendamento (Resource Scheduler)** do OCI.

> [!NOTE]
Caso você já tenha um agendamento criado e queria utiliza-lo, siga para o tópico: [Using existing scheduling](#using-existing-scheduling)

O agendamento será configurado para **duas execuções diárias**:

- **00:00 UTC** (Meia-noite)
- **12:00 UTC** (Meio-dia)

Lembre-se de que o agendamento é configurado no fuso horário **UTC**. Caso sua região tenha um deslocamento de **-3 horas** em relação ao UTC (como o fuso horário de São Paulo, Brasil), ajuste os horários de execução conforme necessário.

```BASH
export CRON_SCHEDULER="3,15"

export RESOURCE_SCHEDULER_OCID=$(oci resource-scheduler schedule create \
--display-name "${FN_APP_NAME} - ${FN_FUNC_NAME}" \
--description "${FN_APP_NAME} - ${FN_FUNC_NAME} Scheduler" \
--compartment-id ${OCI_COMPARTMENT} \
--action "START_RESOURCE" \
--recurrence-details "0 ${CRON_SCHEDULER} * * *" \
--recurrence-type "CRON" \
--resources "[{\"id\":\"${FN_FUNC_OCID}\",\"metadata\":null,\"parameters\":null}]" \
--raw-output \
--query 'data.id')

set | grep -E '^(RESOURCE_SCHEDULER_OCID)'
```

### Dynamic Group for Resource Scheduler

De forma análoga à *Function*, é necessário criar um **Grupo Dinâmico (Dynamic Group)** específico para o nosso agendamento, conforme o comando abaixo:

```BASH
export DYG_RESOURCE_SCHEDULER="DYG_${FN_APP_NAME}_${FN_FUNC_NAME}_Scheduler"

oci iam dynamic-group create \
--name ${DYG_RESOURCE_SCHEDULER} \
--description "Dynamic group para o Resource Scheduler que vai executar a function que extrai as recomendações do Cloud Advisor." \
--matching-rule "All {resource.type='resourceschedule', resource.id='${RESOURCE_SCHEDULER_OCID}'}"
```

> [!NOTE]
A **matching-rule** deste *Dynamic Group* selecionará exclusivamente o nosso agendamento, independentemente do compartment onde ela foi criada.

### Policy for Resource Scheduler

Esta política de acesso concederá permissão ao agendamento para **invocar a nossa *function***, utilizando o grupo dinâmico que será criado.

```BASH
export POL_RESOURCE_SCHEDULER="POL_${FN_APP_NAME}_${FN_FUNC_NAME}_Scheduler"

oci iam policy create \
--name "${POL_RESOURCE_SCHEDULER}" \
--description "Permissoes para invocar functions de um compartment especifico do projeto de FinOps." \
--compartment-id ${OCI_COMPARTMENT} \
--statements "[\"Allow dynamic-group ${DYG_RESOURCE_SCHEDULER} to use functions-family in compartment id ${OCI_COMPARTMENT}\"]"
```

> [!IMPORTANT]
A política de acesso será criada no mesmo *compartment* de todos os demais recursos, conforme definido pela variável `OCI_COMPARTMENT`.

### Using existing scheduling

Navegue pela console ate o serviço **Resource Scheduler** (MENU > Governance & Administration > Resource Scheduler) e encontre o agendamento previamente criado no qual deseja adicionar a function e a edite como demonstrado abaixo:

![OCI Cloud Shell: Open](images/oci-resource-scheduler-edit-schedule.gif)

## Testing

> [!TIP]
Após concluir o processo de criação com sucesso, **aguarde alguns minutos**. Essa pausa é crucial para garantir que o sistema carregue e atualize os *caches* de permissões, especialmente as novas políticas concedidas à OCI Function e ao OCI Resource Scheduler.

Para **verificar o funcionamento** da *function*, utilize o comando abaixo:

```BASH
fn invoke ${FN_APP_NAME} ${FN_FUNC_NAME,,}
```

Este comando **invocará a *function*** e retornará os dados de execução. O resultado esperado é semelhante a este:

```JSON
{
    "categories_names": 3,
    "categories_descriptions": 3,
    "categories_total": 3,
    "recommendations_names": 21,
    "recommendations_descriptions": 21,
    "recommendations_total": 21
}
```

|            Item            |                                    Descrição                                     |
|----------------------------|----------------------------------------------------------------------------------|
|categories_names            |Quantidade de nomes de **categorias** alteradas pelo mapping de campos.           |
|categories_descriptions     |Quantidade de descrições de **categorias** alteradas pelo mapping de campos.      |
|recommendations_names       |Quantidade de nomes de **recomendações** alteradas pelo mapping de campos.        |
|recommendations_descriptions|Quantidade de descrições de **recomendações** alteradas pelo mapping de campos.   |
|categories_total            |Quantidade total de nomes de **categorias** processadas pelo mapping de campos.   |
|recommendations_total       |Quantidade total de nomes de **recomendações** processadas pelo mapping de campos.|

## Logging

Caso ocorram problemas ou erros, **ative o *log* e acompanhe os eventos** para identificar e corrigir eventuais falhas.

Neste *link*, [Oracle Cloud: Problemas ao invocar funções](https://docs.oracle.com/en-us/iaas/Content/Functions/Tasks/functionstroubleshooting_topic-Issues-invoking-functions.htm), você encontrará diversos **problemas conhecidos** e possíveis **soluções** para cada cenário.

> [!IMPORTANT]
O **Log da *function* não é habilitado por padrão**. Se necessário você precisa ativá-lo manualmente.
