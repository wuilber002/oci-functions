# Updating an existing OCI Function

[Leia este procedimento em português](./fn_update.md) <span>&#x1f1e7;&#x1f1f7;</span>

This guide updates the Function **without creating another resource**. It finds
the Function by name, preserves its Application and configuration, builds a new
image, and deploys the current code.

> Run these commands in Cloud Shell, from the directory that contains `func.py`,
> `requirements.txt`, and `test_func.py` from this version of the project.

- [Updating an existing OCI Function](#updating-an-existing-oci-function)
  - [1. Prerequisites and Function identification](#1-prerequisites-and-function-identification)
  - [2. Retrieve the current Application and configuration](#2-retrieve-the-current-application-and-configuration)
  - [3. Configure the context and Registry](#3-configure-the-context-and-registry)
  - [4. Generate `func.yaml`](#4-generate-funcyaml)
  - [5. Module list](#5-module-list)
  - [6. Validate and deploy](#6-validate-and-deploy)
  - [7. Verify the update](#7-verify-the-update)
  - [8. Remove the temporary Auth Token](#8-remove-the-temporary-auth-token)

## 1. Prerequisites and Function identification

Set the name used in the previous deployment. The supplied name retains uppercase letters for readability, while the query automatically uses its lowercase form.

```bash
export FN_FUNC_NAME="Focus-Report-Extractor"
export OCI_DOMAIN_NAME="Default"

set | grep -E '^(OCI_USERNAME|FN_FUNC_NAME|OCI_DOMAIN_NAME|OCI_NAMESPACE|FN_FUNC_OCID)'
```

> OCI Search covers all *compartments* in the region configured in `OCI_REGION`.
> If the Function is in another region, change the context region before running
> this guide.

## 2. Retrieve the current Application and configuration

The following commands retrieve the Function's name and related OCIDs, as well as the variables to preserve in the new `func.yaml`.

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

> If `OCI_BUCKET_DESTINATION_REGION` has no value, the default is in use: the
> region where the Function is running.

## 3. Configure the context and Registry

`OCI_REGION` and `OCI_USERNAME` must be defined in Cloud Shell before this step.
The *Auth Token* is used as the password for `docker login`. This guide creates a
temporary *Auth Token* to update the Function and removes it at the end.

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

Use the *Auth Token* created in the previous step to authenticate with the
Registry. The following command passes it through standard input without showing it in the terminal.

> [!IMPORTANT]
> Wait a few minutes before proceeding so that the new token can 
> propagate and be used.

```bash
jq -r '.data.token' <<< "${AUTH_TOKEN_RESPONSE}" | docker login \
  --username "${OCI_NAMESPACE}/${OCI_DOMAIN_NAME}/${OCI_USERNAME}" \
  --password-stdin "${OCI_REGION}.ocir.io"
```

## 4. Generate `func.yaml`

The custom destination region is included only when it already exists in the
configuration. Otherwise, the new version automatically uses
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

> If the existing Function uses different memory or timeout values, preserve
> them in the file before deployment.

## 5. Module list

This file contains the Python modules required to run the `func.py` *script*.

```bash
cat << EOF > requirements.txt
oci>=2.155
fdk
EOF
```

## 6. Validate and deploy

```bash
python -m unittest -v
python -m py_compile func.py test_func.py
```

All tests must return *ok*.

```bash
fn --verbose deploy --app "${FN_APP_NAME}"
```

Deploying to the same Application with the same name updates the existing
Function. Its OCID, policies, Dynamic Group, and schedule remain unchanged.

> If the build fails with `no space left on device`, check available space with
> `df -h` and `podman system df`. After reviewing the resources, `podman system
> prune -a` removes unused images and cache; those images will be downloaded
> again on the next execution.

## 7. Verify the update

```bash
oci fn function get \
  --function-id "${FN_FUNC_OCID}" \
  --query 'data.{image:image,config:config,memory:"memory-in-mbs",timeout:"timeout-in-seconds"}' \
  --output json

fn invoke "${FN_APP_NAME}" "${FN_FUNC_NAME,,}"
```

In the JSON returned by the invocation, confirm that `erro`, `pending`,
`unknown`, `conflict`, and `metadata_incomplete` are all `0`.

If you encounter a problem, check the Function execution logs to identify the problem.

## 8. Remove the temporary Auth Token

After completing and validating the update, remove the *Auth Token* created by this guide. It does not affect the image already published or Function execution.

```bash
oci iam auth-token delete \
  --user-id "${OCI_CS_USER_OCID}" \
  --auth-token-id "${OCI_AUTH_TOKEN_OCID}" \
  --force

unset AUTH_TOKEN_RESPONSE
unset OCI_AUTH_TOKEN_OCID
```

