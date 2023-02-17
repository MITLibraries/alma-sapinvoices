import datetime
import logging
from typing import Optional

import click

from sapinvoices.config import configure_logger, configure_sentry, load_config_values

logger = logging.getLogger(__name__)


@click.group()
@click.pass_context
def sap(ctx: click.Context) -> None:
    ctx.ensure_object(dict)
    ctx.obj["today"] = datetime.datetime.today()


@sap.command()
@click.pass_context
def create_sandbox_data(ctx: click.Context) -> None:
    """Create sample data in the Alma sandbox instance.

    In order to run successfully, the sandbox Acquisitions read/write API key must be
    set in config (in .env if running locally, or in SSM if on stage). This command
    will not run in the production environment, and should never be run with production
    config values.
    """
    logger.info("Creating sample data in Alma sandbox for today: %s", ctx.obj["today"])
    click.echo("sap data gets created in the sandbox...")


@sap.command()
@click.option(
    "--final-run",
    is_flag=True,
    help="Flag to indicate this is a final run and should include all steps of the "
    "process. Default if this flag is not passed is to do a review run, which only "
    "creates and sends summary and report files for review by stakeholders. Note: some "
    "steps of a final run will not be completed unless the '--real-run' flag is also "
    "passed, however that will write data to external systems and should thus be used "
    "with caution. See '--real-run' option documentation for details.",
)
@click.option(
    "--real-run",
    is_flag=True,
    help="USE WITH CAUTION. If '--real-run' flag is passed, files will be emailed "
    "to stakeholders and, if the '--final-run' flag is also passed, invoices will be "
    "sent to SAP and marked as paid in Alma. If this flag is not passed, this command "
    "defaults to a dry run, in which files will not be emailed or sent to SAP, instead "
    "their contents will be logged for review, and invoices will also not be marked as "
    "paid in Alma.",
)
@click.option(
    "-l",
    "--log-level",
    envvar="LOG_LEVEL",
    help="Case-insensitive Python log level to use, e.g. debug or warning. Defaults to "
    "INFO if not provided or found in ENV.",
)
@click.pass_context
def process_invoices(
    ctx: click.Context, final_run: bool, real_run: bool, log_level: Optional[str]
) -> None:
    """Process invoices for payment via SAP.

    Retrieves "Waiting to be sent" invoices from Alma, extracts and formats data
    needed for submission to SAP for payment. If not a final run, creates and sends
    formatted review reports to Acquisitions staff. If a final run, creates and sends
    formatted cover sheets and summary reports to Acquisitions staff, submits data and
    control files to SAP, and marks invoices as paid in Alma after submission to SAP.
    """
    config_values = load_config_values()
    log_level = log_level or "INFO"
    root_logger = logging.getLogger()
    logger.info(configure_logger(root_logger, log_level))
    logger.info(configure_sentry())

    logger.info(
        "alma-sapinvoices config settings loaded for environment: %s",
        config_values["WORKSPACE"],
    )

    logger.info("Starting SAP invoices process with options: \n")
    logger.info("Date: %s \n", ctx.obj["today"])
    logger.info("Final run: %s \n", final_run)
    logger.info("Real run: %s", real_run)
    click.echo("invoice processing happens...")
