# sapinvoices

Transmits ready-to-be-paid invoice data from Alma to MIT accounts payable department's SAP 
system and sets transmitted invoices to paid in Alma.

## Development

- To install with dev dependencies: `make install`
- To update dependencies: `make update`
- To run unit tests: `make test`
- To lint the repo: `make lint`
- To run the app: `pipenv run sap --help`

## Required ENV
```shell
ALMA_API_URL=# Base URL for making Alma API calls
ALMA_API_READ_WRITE_KEY=# API key for making Alma API calls
SAP_DROPBOX_CLOUDCONNECTOR_JSON=# JSON formatted connection information for accessing SAP dropbox
SAP_REPLY_TO_EMAIL=# reply-to email on emails to SAP recipient email lists
SAP_FINAL_RECIPIENT_EMAIL=# moira list to recieves final run emails
SAP_REVIEW_RECIPIENT_EMAIL=# moira list to recieve review run emails
SES_SEND_FROM_EMAIL=# email address that SES sends from
SAP_SEQUENCE_NUM=# the SSM path of the current SAP sequence number 
WORKSPACE=# Set to `dev` for local development, this will be set to `stage` and `prod` in those environments by Terraform.
```

## Optional ENV
```shell
ALMA_API_TIMEOUT=# Request timeout for Alma API calls. Defaults to 30 seconds if not set. 
LOG_LEVEL=# Set to a valid Python logging level (e.g. DEBUG, case-insensitive) if desired. Can also be passed as an option directly to the ccslips command. Defaults to INFO if not set or passed to the command.
SENTRY_DSN=# If set to a valid Sentry DSN, enables Sentry exception monitoring. This is not needed for local development.
```

## Local Testing
To test end-to-end with a connection to the test SAP Dropbox, the app must be run as an ECS task in the `stage` environment. 
1. Copy and install AWS CLI credentials for the `SAPInvoicesManagers` role for the `Stage-Workloads` AWS account.
2. Build and publish a new container to ECR
   1. Set local environment variables.
      ```
      export ECR_NAME_STAGE=alma-sapinvoices-stage
      export ECR_URL_STAGE=[URI copied from the alma-sapinvoices-stage ECR repository]
       ```
   2. Build and Publish
       ```
       make dist-stage
       make publish-stage
       ```
3. If needed for testing, create and approve sample invoices in alma sandbox (see below)
4. For the command and options you want to test, copy and run the corresponding command string from the `workloads-sapinvoices-stage` workspce in Terraform Cloud. 
5. Review cloudwatch logs to confirm that the command ran as expected.
6. If running with both `--real` and `--final` options, confirm in Alma sandbox that the sample invoices created in step 3 were marked as paid.

## Creating sample invoices in Alma Sandbox
Running the SAP Invoices process during local development or on staging requires that
there be sample invoices ready to be paid in the Alma sandbox. To simplify this, there
is a CLI command that will create four sample invoices in the sandbox. To do this:
  1. Ensure that the fund used in `sample-data/sample-sap-invoice-data.json` is active and has $$ allocated to in the Alma Sandbox.
  2. Ensure that you have the `Invoice Manager` role in Alma Sandbox.
  3. Copy and install AWS CLI credentials for the `SAPInvoicesManagers` role for either the `Dev1` or `Stage-Workloads` AWS account. 
  4. From corresponding (dev or stage) `sapinvoices` workspace in Terraform Cloud, copy and run the command string output named `aws_cli_run_task_create_sandbox_data`.
  5. Go to the Alma sandbox UI > Acquisitions module > Approve (Invoice) > Unassigned
     tab. There should be four invoices listed whose numbers start with TestSAPInvoice.
  6. For each of those invoices, using the three dots to the right of each invoice, choose "Edit"
     and then click "Approve" in the upper right corner.
  7. Once the invoices have been approved, they are ready to be paid and can be
     retrieved and processed using the `process-invoices` CLI command.

Note that sample invoices will remain in the Alma sandbox in the "Waiting to be Sent"
status until a "real", "final" sap-invoices process has been run, at which point they
will be marked as paid and new sample invoices will need to be created.