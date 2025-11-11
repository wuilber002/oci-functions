<h1> OCI Function: FinOps - Cloud Advisor Extractor </h1>

[Veja esse README em Portugues](./readme.md) <span>&#x1f1e7;&#x1f1f7;</span>

This set of files contains a Python ***Function*** developed to automate the process of downloading and uploading recommendations, categories, and actions recommended by your OCI **Cloud Advisor** to a *bucket* within the same *tenancy*.

<h2>Disclaimer</h3>

Before proceeding, it is essential to keep in mind that the use of any *scripts*, code, or commands contained in this repository is entirely at your own risk. The code authors are not responsible for any costs arising from the use of the content provided here.

We **recommend testing** all content in an appropriate environment and integrating the automation *scripts* with a robust monitoring infrastructure to track the process and mitigate potential failures.

This project is **not an official Oracle application** and therefore does not have formal support. Oracle is not responsible for any content presented here.

<h2>Overview</h2>

The Python script, designed to run on the serverless OCI Functions service, performs data extraction from the OCI API using the following calls:

- [**OCI Optimizer: `list-categories`**](https://oracle-cloud-infrastructure-python-sdk.readthedocs.io/en/latest/api/optimizer/client/oci.optimizer.OptimizerClient.html#oci.optimizer.OptimizerClient.list_categories)
- [**OCI Optimizer: `list-recommendations`**](https://oracle-cloud-infrastructure-python-sdk.readthedocs.io/en/latest/api/optimizer/client/oci.optimizer.OptimizerClient.html#oci.optimizer.OptimizerClient.list_recommendations)
- [**OCI Optimizer: `list-resource-actions`**](https://oracle-cloud-infrastructure-python-sdk.readthedocs.io/en/latest/api/optimizer/client/oci.optimizer.OptimizerClient.html#oci.optimizer.OptimizerClient.list_resource_actions)

<h3>Data Mapping and Localization</h3>

After extracting the lists of categories and recommendations, the script uses an external mapping file (mapping/dictionary) to translate the programmatic values ​​(keys) returned by the API in the name and description fields into user-readable values.

This mapping file must be provided in the same bucket used by the OCI Function as the destination for the extracted files. More information will be provided throughout this document.

> [!WARNING]
**It is mandatory** that the mapping file be periodically validated. New categories or recommendations provided by Oracle will not be automatically translated and must be manually entered into the dictionary to ensure data accuracy.

![OCI Cloud Shell: Open](images/oci-function-execution-flow.png)

![OCI Cloud Shell: Open](images/cloud-advisor-field-mapping.png)

<h2>Index</h2>

- [Requirements](#requirements)
  - [Permissions](#permissions)
  - [Networks](#networks)
- [Project Files](#project-files)
- [Cloud Shell](#cloud-shell)
  - [Architecture x86\_64](#architecture-x86_64)
  - [Environment Variables](#environment-variables)
- [Working Directory](#working-directory)
- [Clone the Git repository](#clone-the-git-repository)
- [OCI Container Registry](#oci-container-registry)
- [Bucket](#bucket)
- [OCI Function](#oci-function)
  - [OCI Function: Application](#oci-function-application)
  - [OCI Function: Context](#oci-function-context)
  - [OCI Function: Arquivos](#oci-function-arquivos)
    - [requirements.txt](#requirementstxt)
    - [func.yaml](#funcyaml)
    - [func.py](#funcpy)
  - [OCI Function: Build](#oci-function-build)
  - [OCI Function: Tagging](#oci-function-tagging)
  - [OCI Function: Dynamic Group](#oci-function-dynamic-group)
  - [OCI Function: Policy](#oci-function-policy)
- [Resource Scheduler](#resource-scheduler)
  - [Resource Scheduler: Dynamic Scheduling Criteria](#resource-scheduler-dynamic-scheduling-criteria)
  - [Resource Scheduler: Dynamic Group](#resource-scheduler-dynamic-group)
  - [Resource Scheduler: Policy](#resource-scheduler-policy)
  - [Resource Scheduler: Using an Existing Schedule](#resource-scheduler-using-an-existing-schedule)
- [Testing](#testing)
- [Logging](#logging)

## Requirements

To continue this procedure, it is necessary to **meet the following requirements:**

### Permissions

Permissions are divided into two groups of actions:

- **For Resource Creation:**
- Bucket
- Dynamic Group
- IAM Policy
- Function
- OCI Container Registry
- Resource Scheduler

- **For Resource Access:**
- Cloud Shell

### Networks

It is mandatory that you have a **VCN** created with a **Subnet** that has available IP addresses to allocate the *Function*. This *Subnet* must have **internet access** or have an active **Service Gateway**.

## Project Files

The following are the files that make up the project. Only two are essential; `readme.md` and `readme_en-US` can be ignored in the deployment process.

```BASH
.
├── cloud-advisor-mapping.json
├── func.py
├── readme.md
└── readme_en-US.md
```

| Item | Description |
|------|-----------|
|**cloud-advisor-mapping.json**|Mapping file (dictionary) for the names and descriptions of Cloud Advisor recommendations and categories.|
|**func.py**|The Python script that will be executed by the function.|
|readme.md|This documentation and help file.|
|readme_en-US.md|English version of this documentation and help file.|

## Cloud Shell

To begin creating and configuring resources, **open Cloud Shell**.

![OCI Cloud Shell: Open](images/oci-cloud-shell_open.gif)

### Architecture x86\_64

For the correct functioning of the resources involved in this procedure, we will use the **x86\_64 architecture** as the standard.

![OCI Cloud Shell: Open](images/oci-cloud-shell_change_arch.gif)

**Validate the architecture** with the command below. The expected return is "x86\_64:OK" for the correct configuration.

```BASH
[ "$(uname -m)" == "x86_64" ] && echo "$(uname -m):OK" || echo "$(uname -m):ERRO"
```

### Environment Variables

Before creating environment variables, verify that they have all been configured correctly.

```BASH
export FN_APP_NAME='FinOps'
export FN_FUNC_NAME='Cloud-Advisor-Extractor'
export FN_FUNC_TAG_VALUE='Scheduled-Function'
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

set|grep -E '^(FN_APP_NAME|FN_FUNC_NAME|FN_FUNC_TAG_VALUE|OCI_DOMAIN_NAME|OCI_USERNAME|OCI_BUCKET_NAME_DESTINATION|OCI_COMPARTMENT|OCI_SUBNET|OCI_REPO_NAME|OCI_NAMESPACE|OCI_BUCKET_ROOT_PATH|CLOUD_ADVISOR_MAPPING_FILE|CLOUD_ADVISOR_MAPPING_FILE_PATH|OCI_REGION|OCI_TENANCY)'
```

| Variable | Description |
|-|-|
|**FN_APP_NAME** | Name of the Application where the functions will be created.|
|**FN_FUNC_NAME** | Name of the **OCI Function**.|
|**FN_FUNC_TAG_VALUE** | Value used to identify the function that will be executed by the *Resource Scheduler*. The Key of the *free-form Tag* will be the name of the Function's Application, defined in the **FN_APP_NAME** variable.|
|**OCI_DOMAIN_NAME** | Name of the domain in which the user is created.|
|**OCI_USERNAME** | Name of the user to be used for authentication in the **OCI Registry**. This user will only be used during the configuration process.|
|**OCI_BUCKET_NAME_DESTINATION** | Name of the **Bucket** that will be used to store the files extracted by the **OCI Function**.|
|**OCI_COMPARTMENT** |OCID (*Oracle Cloud Identifier*) of the ***compartment*** where all resources (Function Application, OCI Function, OCI Registry, etc.) will be created.|
|**OCI_SUBNET** |OCID (*Oracle Cloud Identifier*) of the ***subnet*** in which the *function* will be created.|
|**OCI_REPO_NAME** |Name of the repository in the **OCI Registry** to store the *function's *images*.|
|**OCI_NAMESPACE** |Name of the **Object Storage** namespace in the Tenancy.|
|**OCI_BUCKET_ROOT_PATH** |Name of the **root directory** of the destination bucket for the files extracted by the **OCI Function**.|
|**CLOUD_ADVISOR_MAPPING_FILE** |Name of the Cloud Advisor **mapping file** (dictionary).|
|**CLOUD_ADVISOR_MAPPING_FILE_PATH**|Path to the Cloud Advisor mapping file (dictionary).|

In addition to these, other variables that are already predefined in the OCI Cloud Shell will be used:

| Variable | Description |
|-|-|
| **OCI_REGION** |Full name of the region to which the Cloud Shell is connected.|
| **OCI_TENANCY** |OCID (Oracle Cloud Identifier) ​​of the Tenancy to which we are logged in the Cloud Shell.|

## Working Directory

Let's create a working directory to organize all our files and then start creating the necessary artifacts and building our function.

```BASH
mkdir -p ~/oci-functions/${FN_FUNC_NAME,,}
cd ~/oci-functions/${FN_FUNC_NAME,,}
```

## Clone the Git repository

Clone this Git repository and/or make all the files mentioned in the [Project Files](#project-files) topic available in our working directory.

```BASH
git clone https://github.com/wuilber002/oci-functions.git
```

## OCI Container Registry

You must use an **Auth Token as your password** during the login process to the **OCI Container Registry**.

If you do not have an **Auth Token** created, generate a new one using the following command:

```BASH
oci iam auth-token create \
--user-id ${OCI_CS_USER_OCID} \
--description "OCI Container Registry" \
--raw-output \
--query 'data.token'
```

This is the command to *login* to the **OCI Container Registry**:

> [!TIP]
> If you have just created the **Auth Token**, **wait a few minutes** before using it. It may take some time for the *token* to propagate and be ready to log in to the OCI Container Registry.

```BASH
docker login -u "${OCI_NAMESPACE}/${OCI_DOMAIN_NAME}/${OCI_USERNAME}" ${OCI_REGION}.ocir.io
```

## Bucket

This bucket will receive all files extracted from the Cloud Advisor service for the Tenancy.

If you already have the bucket created, you can skip this part and export the OCI_BUCKET_NAME_DESTINATION variable with your bucket's name. Otherwise, create the bucket using the command below:

```BASH
oci os bucket create --name ${OCI_BUCKET_NAME_DESTINATION} \
--storage-tier "STANDARD" \
--namespace-name ${OCI_NAMESPACE} \
--compartment-id ${OCI_COMPARTMENT}
```

Now we will upload the *mapping* file (Dictionary) to the bucket in the **PATH** specified at the beginning of this procedure in the environment variable **${CLOUD_ADVISOR_MAPPING_FILE_PATH}**

Use the command below to upload the mapping file to the bucket we just created:

```BASH
oci os object put \
-bn ${OCI_BUCKET_NAME_DESTINATION} \
--file ${CLOUD_ADVISOR_MAPPING_FILE} \
--name "${CLOUD_ADVISOR_MAPPING_FILE_PATH}/${CLOUD_ADVISOR_MAPPING_FILE}"
```

## OCI Function

### OCI Function: Application

Create an **FN Application** with the x86\_64 architecture to host the function. If you already have one, export the OCID (Oracle Cloud Identifier) ​​to the environment variable ***FN_APP_OCID*** and the name to ***FN_APP_NAME*** for easier later use.

To create the application, use the command below, which exports the OCID (Oracle Cloud Identifier) ​​to an environment variable.

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

### OCI Function: Context

Some **context settings** need to be configured for the OCI Functions `fn` client.

```BASH
fn use context ${OCI_REGION}
fn update context oracle.compartment-id ${OCI_COMPARTMENT}
fn update context registry ${OCI_REGION}.ocir.io/${OCI_NAMESPACE}/${OCI_REPO_NAME}
fn update context oracle.image-compartment-id ${OCI_COMPARTMENT}
fn list context
```

### OCI Function: Arquivos

You need to have the files listed below in your working directory in Cloud Shell.

- `requirements.txt`
- `func.yaml`
- `func.py`

To create the `func.yaml` and `requirements.txt` files, you must use the commands below:

#### requirements.txt

This file contains the list of Python modules required to run the `func.py` script.

```BASH
cat << EOF > requirements.txt
oci>=2.155
fdk
EOF
```

#### func.yaml

Metadata file containing the configuration and characteristics of the function that will be created.

```BASH
cat << EOF > func.yaml
schema_version: 20180708
name: ${FN_FUNC_NAME,,}
version: 0.0.1
runtime: python
entrypoint: /python/bin/fdk /function/func.py handler
memory: 128
timeout: 300
config:
 OCI_BUCKET_DESTINATION: ${OCI_BUCKET_NAME_DESTINATION}
 OCI_TENANCY_OCID: ${OCI_TENANCY}
 OCI_BUCKET_ROOT_PATH: ${OCI_BUCKET_ROOT_PATH}
 CLOUD_ADVISOR_MAPPING_FILE_PATH: ${CLOUD_ADVISOR_MAPPING_FILE_PATH}/${CLOUD_ADVISOR_MAPPING_FILE}
EOF
```

To ensure the solution's flexibility, the function will use variables to receive data that may vary in each tenancy. Below is a description of each:

| Variable | Description |
|----------|--------------------|
|**OCI_BUCKET_DESTINATION** |Name of the *Bucket* that will be used to **store the files extracted by the OCI Function**.|
|**OCI_TENANCY_OCID** |The **OCI** (Oracle Cloud Identifier) ​​of the Tenancy.|
|**OCI_BUCKET_ROOT_PATH** |Name of the "root" folder located in the "Bucket" that will receive the files extracted by the OCI Function.|
|**CLOUD_ADVISOR_MAPPING_FILE_PATH**|Full path within the Bucket to the data *mapping* file, which maps the names and descriptions of the *Cloud Advisor* recommendations and categories.|

#### func.py

The `func.py` file needs to be uploaded if you haven't cloned the repository to our **work directory**.

![Cloud Shell Upload Steps](images/oci-cloud-shell_upload.gif)

After uploading using the button in the upper right corner, move the file to the **work directory** you created earlier.

```BASH
mv ~/func.py .
```

### OCI Function: Build

The next command will execute the following steps:

- Creates the *image* of the *function* with Python and all modules listed in `requirements.txt`;
- Creates the repository in the **OCI Container Registry** for uploading the *image*;
- Creates the *function* with the characteristics defined in `func.yaml` within the **Function Application**;
- Configures the environment variables.

```BASH
fn --verbose deploy --app "${FN_APP_NAME}"
```

After successfully building and deploying the function's image, you need to obtain the function's OCID (Oracle Cloud Identifier) ​​to grant it access to the necessary resources.

Run the command below to retrieve the **function's OCID** (Oracle Cloud Identifier):

```BASH
export FN_FUNC_OCID=$(oci fn function list \
--application-id ${FN_APP_OCID} \
--raw-output \
--query "data[?contains(\"display-name\", '${FN_FUNC_NAME,,}')].id | [0]")

set | grep -E '^(FN_FUNC_OCID)'
```

### OCI Function: Tagging

In order for the **Resource Scheduler** service to identify and select the correct resource for scheduled execution, it is necessary to **define the specific Free-form Tag** in the created *function*.

The *Resource Scheduler* will use this *tag* as a metadata filter to invoke the resource.

Use the following command to apply the *tag* to the *function*:

```BASH
oci fn function update \
--force \
--function-id ${FN_FUNC_OCID} \
--freeform-tags "{\"${FN_APP_NAME}\": \"${FN_FUNC_TAG_VALUE}\"}"
```

### OCI Function: Dynamic Group

To grant the necessary permissions for the function to access the Cloud Advisor service and the destination bucket, it is essential to create a Dynamic Group, as shown in the command below:

```BASH
export DYG_FUNCTION="${FN_APP_NAME}_${FN_FUNC_NAME}"

oci iam dynamic-group create \
--name ${DYG_FUNCTION} \
--description "Dynamic group for the function that extracts recommendations from Cloud Advisor.." \
--matching-rule "ALL {resource.type = 'fnfunc', resource.id = '${FN_FUNC_OCID}'}"
```

> [!NOTE]
The matching rule of this Dynamic Group will exclusively select our function, regardless of the creation compartment.

### OCI Function: Policy

This access policy will grant the *function* permission to query the **Cloud Advisor** API and the destination *bucket*, using the created dynamic group.

```BASH
cat <<EOF > /tmp/function_cloud_advisor_extractor.policy
[
    "Allow dynamic-group ${DYG_FUNCTION} to {OPTIMIZER_CATEGORY_INSPECT, OPTIMIZER_RECOMMENDATION_INSPECT, OPTIMIZER_RESOURCE_ACTION_INSPECT} in tenancy",
    "Allow dynamic-group ${DYG_FUNCTION} to read buckets in compartment id ${OCI_COMPARTMENT} WHERE target.bucket.name='${OCI_BUCKET_NAME_DESTINATION}'",
    "Allow dynamic-group ${DYG_FUNCTION} to manage objects in compartment id ${OCI_COMPARTMENT} WHERE ALL {target.bucket.name='${OCI_BUCKET_NAME_DESTINATION}', target.object.name='${OCI_BUCKET_ROOT_PATH}/*'}",
    "Allow dynamic-group ${DYG_FUNCTION} to read objects in compartment id ${OCI_COMPARTMENT} WHERE ALL {target.bucket.name='${OCI_BUCKET_NAME_DESTINATION}', target.object.name = '${CLOUD_ADVISOR_MAPPING_FILE_PATH}/${CLOUD_ADVISOR_MAPPING_FILE}'}"
]
EOF

oci iam policy create \
--name "${FN_APP_NAME}_${FN_FUNC_NAME}" \
--description "Permissions for the function that extracts recommendations from Cloud Advisor.." \
--compartment-id ${OCI_TENANCY} \
--statements file:///tmp/function_cloud_advisor_extractor.policy
```

## Resource Scheduler

For automated execution, we will use the OCI's **Resource Scheduler** PaaS service.

> [!NOTE]
If there is a pre-existing schedule that you wish to reuse, please proceed to the topic: [Resource Scheduler: Using an Existing Schedule](#resource-scheduler-using-an-existing-schedule)

---

The schedule to be created will be of the **dynamic** type, configured for **one daily execution** at the following time:

- **00:00 UTC** (Midnight).

It is crucial to note that the schedule is parameterized in the **UTC** (*Coordinated Universal Time*) time zone. For regions with offsets (e.g., **-3 hours** relative to UTC, such as the São Paulo, Brazil time zone), the execution times must be adjusted as needed.

### Resource Scheduler: Dynamic Scheduling Criteria

A dynamic schedule selects the resources to be executed at the time of invocation, based on previously defined filter criteria. We will adopt the following criteria:

- **Compartment:** Residing in the **Compartment** defined by the environment variable `OCI_COMPARTMENT`.
- **Free-form Tag:** Possess the **Free-form Tag** with the exact key and value: `FinOps: Scheduled-Function`.
- **Resource Type:** Be a resource of type **Function** (OCI Function).

Based on the listed criteria, we will create the **Resource Filter** JSON file, which will be used to identify the resources that will have their execution scheduled.

```BASH
cat <<EOF > /tmp/resource_scheduler-resource_filter.policy
[
  {
    "attribute": "RESOURCE_TYPE",
    "value": [
      "FunctionsFunction"
    ]
  },
  {
    "attribute": "COMPARTMENT_ID",
    "should-include-child-compartments": null,
    "value": "${OCI_COMPARTMENT}"
  },
  {
    "attribute": "DEFINED_TAGS",
    "value": [
      {
        "namespace": "FREEFORM_TAG",
        "tag-key": "${FN_APP_NAME}",
        "value": "${FN_FUNC_TAG_VALUE}"
      }
    ]
  }
]
EOF
```

And then, the command to **create the execution schedule**:

```BASH
export CRON_SCHEDULER="3"

export RESOURCE_SCHEDULER_OCID=$(oci resource-scheduler schedule create \
--display-name "${FN_APP_NAME} - Functions Scheduler" \
--description "Scheduling for the execution of FinOps process functions.." \
--compartment-id ${OCI_COMPARTMENT} \
--action "START_RESOURCE" \
--recurrence-details "0 ${CRON_SCHEDULER} * * *" \
--recurrence-type "CRON" \
--resource-filters file:///tmp/resource_scheduler-resource_filter.policy \
--raw-output \
--query 'data.id')

set | grep -E '^(RESOURCE_SCHEDULER_OCID)'
```

### Resource Scheduler: Dynamic Group

Similar to the *Function*, it is necessary to create a specific **Dynamic Group** for our scheduling, as shown in the command below:

```BASH
export DYG_RESOURCE_SCHEDULER="${FN_APP_NAME}-Functions_Scheduler"

oci iam dynamic-group create \
--name "${DYG_RESOURCE_SCHEDULER}" \
--description "Dynamic group for the Resource Scheduler that will execute the function that extracts recommendations from Cloud Advisor." \
--matching-rule "All {resource.type='resourceschedule', resource.id='${RESOURCE_SCHEDULER_OCID}'}"
```

> [!NOTE]
This Dynamic Group's matching rule will exclusively select our schedule, regardless of the compartment where it was created.

### Resource Scheduler: Policy

This access policy grants permission to the scheduling system to **invoke our function**, using the dynamic group that will be created.

```BASH
oci iam policy create \
--name "${FN_APP_NAME}-Functions_Scheduler" \
--description "Permissions to invoke functions from a specific compartment of the FinOps project.." \
--compartment-id ${OCI_COMPARTMENT} \
--statements "[\"Allow dynamic-group ${DYG_RESOURCE_SCHEDULER} to use functions-family in compartment id ${OCI_COMPARTMENT}\"]"
```

> [!IMPORTANT]
The access policy will be created in the same *compartment* as all other resources, as defined by the variable `OCI_COMPARTMENT`.

### Resource Scheduler: Using an Existing Schedule

If you created a schedule following any of the procedures in this GitHub project, **no additional action is required** for this function to run. The schedule created in the **Resource Scheduler** is configured as **dynamic** and will run all functions that meet the following criteria:

- **Compartment:** Reside in the same **Compartment** defined when the schedule was created.
- **Free-form Tag:** Possess the **Free-form Tag** `FinOps: Scheduled-Function`.
- **Resource Type:** Be a resource of type **Function**.

---

If your scenario is different and you wish to use a pre-existing schedule that is not dynamic, you can follow the procedure below:

Navigate through the console to the **Resource Scheduler** service (MENU > Governance & Administration > Resource Scheduler) and find the previously created schedule to which you want to add the function and edit it as shown below:

![OCI Cloud Shell: Open](images/oci-resource-scheduler-edit-schedule.gif)

## Testing

> [!TIP]
After successfully completing the creation process, **wait a few minutes**. This pause is crucial to ensure the system loads and updates the permission caches, especially the new policies granted to the OCI Function and the OCI Resource Scheduler.

To **verify the functionality** of the function, use the command below:

```BASH
fn invoke ${FN_APP_NAME} ${FN_FUNC_NAME,,}
```

This command will **invoke the function** and return the execution data. The expected result is similar to this:

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

| Item | Description |
|----------------------------|----------------------------------------------------------------------------------|
|categories_names|Number of category names changed by field mapping. |
|categories_descriptions|Number of category descriptions changed by field mapping. |
|recommendations_names|Number of recommendation names changed by field mapping. |
|recommendations_descriptions|Number of recommendation descriptions changed by field mapping. |
|categories_total |Total number of category names processed by the field mapping. |
|recommendations_total |Total number of recommendation names processed by the field mapping.|

## Logging

If problems or errors occur, **enable the *log* and monitor the events** to identify and correct any failures.

In this *link*, [Oracle Cloud: Problems invoking functions](https://docs.oracle.com/en-us/iaas/Content/Functions/Tasks/functionstroubleshooting_topic-Issues-invoking-functions.htm), you will find several **known problems** and possible **solutions** for each scenario.

> [!IMPORTANT]
**The *function* log is not enabled by default.** If necessary, you need to enable it manually.
