# sapinvoices

Transmits ready-to-be-paid invoice data from Alma to MIT accounts payable department's SAP system
sets trasmitted invoice to paid in Alma

## Development

- To install with dev dependencies: `make install`
- To update dependencies: `make update`
- To run unit tests: `make test`
- To lint the repo: `make lint`
- To run the app: `pipenv run sapinvoices --help`

## Required ENV

- `SENTRY_DSN` = If set to a valid Sentry DSN, enables Sentry exception monitoring. This is not needed for local development.
- `WORKSPACE` = Set to `dev` for local development, this will be set to `stage` and `prod` in those environments by Terraform.
- `ALMA_API_URL` = Base URL for making Alma API calls
- `ALMA_API_READ_WRITE_KEY` = API key for making Alma API calls
- `SAP_DROPBOX_CONNECTION` = JSON formatted connection information for accessing SAP dropbox
- `SAP_REPLY_TO_EMAIL`
- `SAP_FINAL_RECIPIENT_EMAIL` = moira list to recieves final run emails
- `SAP_REVIEW_RECIPIENT_EMAIL` = moira list to recieve review run emails
- `SES_SEND_FROM_EMAIL`
- `SSM_PATH`
- `LOG_LEVEL`
