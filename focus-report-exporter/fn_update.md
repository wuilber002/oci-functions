# Atualização de uma OCI Function existente

[Read this procedure in English](./fn_update_en-US.md) <span>&#127482;&#127480;</span>

Este roteiro atualiza a Function **sem criar outro recurso**. Ele localiza a Function pelo nome, preserva sua Application e sua configuração, gera uma nova imagem e publica o código atual.

> Execute os comandos no Cloud Shell, dentro do diretório que contém `func.py`,
> `requirements.txt` e `test_func.py` desta versão do projeto.

- [Atualização de uma OCI Function existente](#atualização-de-uma-oci-function-existente)
  - [1. Pré-requisitos e identificação da Function](#1-pré-requisitos-e-identificação-da-function)
  - [2. Recuperar Application e configuração atual](#2-recuperar-application-e-configuração-atual)
  - [3. Configurar o contexto e o Registry](#3-configurar-o-contexto-e-o-registry)
  - [4. Gerar o `func.yaml`](#4-gerar-o-funcyaml)
  - [5. Lista de modulos](#5-lista-de-modulos)
  - [6. Validar e publicar](#6-validar-e-publicar)
  - [7. Verificar a atualização](#7-verificar-a-atualização)
  - [8. Remover o Auth Token temporário](#8-remover-o-auth-token-temporário)

## 1. Pré-requisitos e identificação da Function

Defina o nome usado no deploy anterior. O nome informado mantém as maiúsculas para leitura, mas a consulta usa automaticamente a versão em minúsculas.

```bash
export FN_FUNC_NAME="Focus-Report-Extractor"
export OCI_DOMAIN_NAME="Default"

set | grep -E '^(OCI_USERNAME|FN_FUNC_NAME|OCI_DOMAIN_NAME|OCI_NAMESPACE|FN_FUNC_OCID)'
```

> A consulta do OCI Search cobre todos os *compartments* da região configurada
> em `OCI_REGION`. Caso a Function esteja em outra região, altere a região do
> contexto antes de executar este roteiro.

## 2. Recuperar Application e configuração atual

Os comandos a seguir obtêm o nome e os OCIDs associados à Function, além das
variáveis que serão preservadas no novo `func.yaml`.

```bash
export OCI_NAMESPACE=$(oci os ns get \
  --query 'data' \
  --raw-output)

export OCI_USERNAME=$(oci iam user get \
  --user-id "${OCI_CS_USER_OCID}" \
  --query 'data.name' \
  --raw-output)

export FN_FUNC_OCID=$(oci search resource structured-search \
  --query-text "query functionsfunction resources where displayName = '${FN_FUNC_NAME,,}'" \
  --limit 1000 \
  --query 'data.items[0].identifier' \
  --raw-output)

export FN_APP_OCID=$(oci fn function get \
  --function-id "${FN_FUNC_OCID}" \
  --query 'data."application-id"' \
  --raw-output)

export FN_APP_NAME=$(oci fn application get \
  --application-id "${FN_APP_OCID}" \
  --query 'data."display-name"' \
  --raw-output)

export OCI_COMPARTMENT=$(oci fn function get \
  --function-id "${FN_FUNC_OCID}" \
  --query 'data."compartment-id"' \
  --raw-output)

export OCI_BUCKET_NAME_DESTINATION=$(oci fn function get \
  --function-id "${FN_FUNC_OCID}" \
  --query 'data.config.OCI_BUCKET_DESTINATION' \
  --raw-output)

export OCI_BUCKET_ROOT_PATH=$(oci fn function get \
  --function-id "${FN_FUNC_OCID}" \
  --query 'data.config.OCI_BUCKET_ROOT_PATH' \
  --raw-output)

export OCI_BUCKET_DESTINATION_REGION=$(oci fn function get \
  --function-id "${FN_FUNC_OCID}" \
  --query 'data.config.OCI_BUCKET_DESTINATION_REGION' \
  --raw-output)

export FN_IMAGE=$(oci fn function get \
  --function-id "${FN_FUNC_OCID}" \
  --query 'data.image' \
  --raw-output)

export OCI_REPO_NAME="${FN_APP_NAME,,}_${FN_FUNC_NAME,,}"

set | grep -E '^(OCI_USERNAME|FN_APP_NAME|FN_APP_OCID|OCI_REPO_NAME|FN_FUNC_OCID|OCI_COMPARTMENT|OCI_REGION|OCI_TENANCY|OCI_BUCKET_NAME_DESTINATION|OCI_BUCKET_ROOT_PATH|OCI_BUCKET_DESTINATION_REGION|FN_IMAGE_VERSION)'
```

> Se a variável `OCI_BUCKET_DESTINATION_REGION` não tiver um valor definido,
> estará em uso o padrão: a região onde a Function está em execução.

## 3. Configurar o contexto e o Registry

`OCI_REGION` e `OCI_USERNAME` devem estar definidos no Cloud Shell antes desta etapa. O *Auth Token* deve ser usado como senha no comando `docker login`.
Será criado um *Auth Token* temporário para atualizar a Function. O procedimento o remove ao final.

```bash
fn use context "${OCI_REGION}"
fn update context oracle.compartment-id "${OCI_COMPARTMENT}"
fn update context registry "${OCI_REGION}.ocir.io/${OCI_NAMESPACE}/${OCI_REPO_NAME}"
fn update context oracle.image-compartment-id "${OCI_COMPARTMENT}"
fn list context

AUTH_TOKEN_RESPONSE=$(oci iam auth-token create \
  --user-id "${OCI_CS_USER_OCID}" \
  --description "Temporary Token update FinOps Function" \
  --output json)

export OCI_AUTH_TOKEN_OCID=$(jq -r '.data.id' <<< "${AUTH_TOKEN_RESPONSE}")
```

Use o *Auth Token* criado no passo anterior para autenticar no Registry. O comando abaixo o fornece pela entrada padrão, sem exibi-lo no terminal.

> [!IMPORTANT]
> Aguarde alguns minutos para proceguir, para que o novo token
> sera propagado e seja possivel seu uso.`

```bash
jq -r '.data.token' <<< "${AUTH_TOKEN_RESPONSE}" | docker login \
  --username "${OCI_NAMESPACE}/${OCI_DOMAIN_NAME}/${OCI_USERNAME}" \
  --password-stdin "${OCI_REGION}.ocir.io"
```

## 4. Gerar o `func.yaml`

A região de destino customizada é incluída somente se ela já existia na
configuração. Caso contrário, a nova versão usará automaticamente
`OCI_RESOURCE_PRINCIPAL_REGION`.

```bash
REGION_CONFIG=""

if [[ -n "${OCI_BUCKET_DESTINATION_REGION}" && "${OCI_BUCKET_DESTINATION_REGION}" != "null" ]]; then
  REGION_CONFIG=" OCI_BUCKET_DESTINATION_REGION: ${OCI_BUCKET_DESTINATION_REGION}"
fi

cat << EOF > func.yaml
schema_version: 20180708
name: ${FN_FUNC_NAME,,}
version: ${FN_IMAGE##*:}
runtime: python
entrypoint: /python/bin/fdk /function/func.py handler
memory: 128
timeout: 300
config:
 OCI_BUCKET_DESTINATION: ${OCI_BUCKET_NAME_DESTINATION}
 OCI_TENANCY_OCID: ${OCI_TENANCY}
 OCI_BUCKET_ROOT_PATH: ${OCI_BUCKET_ROOT_PATH}
${REGION_CONFIG}
EOF

cat func.yaml
```

> Se a Function anterior usar valores diferentes de memória ou *timeout*,
> preserve-os no arquivo antes do deploy.

## 5. Lista de modulos

Esse arquivo contem a lista de módulos Python necessários para a execução do *script* `func.py`.

```BASH
cat << EOF > requirements.txt
oci>=2.155
fdk
EOF
```

## 6. Validar e publicar

```bash
python -m unittest -v
python -m py_compile func.py test_func.py
```

Todos os testes devem retorno *ok*

```bash
fn --verbose deploy --app "${FN_APP_NAME}"
```

O deploy na mesma Application e com o mesmo nome atualiza a Function existente.
O OCID, as policies, o Dynamic Group e o agendamento permanecem os mesmos.

> Se o build falhar com `no space left on device`, verifique o espaço disponível
> com `df -h` e `podman system df`. Após revisar os recursos, `podman system
> prune -a` remove imagens e cache sem uso; ele exigirá um novo download dessas
> imagens na próxima execução.

## 7. Verificar a atualização

```bash
oci fn function get \
  --function-id "${FN_FUNC_OCID}" \
  --query 'data.{image:image,config:config,memory:"memory-in-mbs",timeout:"timeout-in-seconds"}' \
  --output json

fn invoke "${FN_APP_NAME}" "${FN_FUNC_NAME,,}"
```

No JSON retornado pela invocação, confirme que `erro`, `pending`, `unknown`,
`conflict` e `metadata_incomplete` estão em `0`.

Caso encontre algum problema, consulte os logs da execusao da function para identificar o problema.

## 8. Remover o Auth Token temporário

Após concluir e validar a atualização, remova o *Auth Token* criado neste
procedimento. Isso não afeta a imagem já publicada nem a execução da Function.

```bash
oci iam auth-token delete \
  --user-id "${OCI_CS_USER_OCID}" \
  --auth-token-id "${OCI_AUTH_TOKEN_OCID}" \
  --force

unset AUTH_TOKEN_RESPONSE
unset OCI_AUTH_TOKEN_OCID
```

