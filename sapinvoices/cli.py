import datetime
import json
import logging

import click

from sapinvoices import sap
from sapinvoices.alma import AlmaClient
from sapinvoices.config import configure_logger, configure_sentry, load_config_values
from sapinvoices.sample_data import load_sample_data

logger = logging.getLogger(__name__)


@click.group()
@click.pass_context
def main(ctx: click.Context) -> None:
    ctx.ensure_object(dict)
    ctx.obj["today"] = datetime.datetime.now(tz=datetime.UTC)


@main.command()
@click.option(
    "-l",
    "--log-level",
    envvar="LOG_LEVEL",
    help="Case-insensitive Python log level to use, e.g. debug or warning. Defaults to "
    "INFO if not provided or found in ENV.",
)
def create_sandbox_data(log_level: str | None) -> None:
    """Create sample data in the Alma sandbox instance.

    This command will not run in the production environment, and should never be run with
    production config values.
    """
    config_values = load_config_values()
    alma_client = AlmaClient()
    log_level = log_level or "INFO"
    root_logger = logging.getLogger()
    logger.info(configure_logger(root_logger, log_level))
    logger.info(configure_sentry())
    if config_values["WORKSPACE"] == "prod":
        logger.info("This command may not be run in the production environment, aborting")
        raise click.Abort
    alma_client = AlmaClient()
    with open(
        "sample-data/sample-sap-invoice-data.json", encoding="utf-8"
    ) as sample_invoice_file:
        contents = json.load(sample_invoice_file)
    invoices_created = load_sample_data(alma_client, contents)
    logger.info(
        "%s sample invoices created and ready for manual approval "
        "in the Alma sandbox UI",
        invoices_created,
    )


@main.command()
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
    ctx: click.Context,
    final_run: bool,  # noqa: FBT001
    real_run: bool,  # noqa: FBT001
    log_level: str | None,
) -> None:
    """Process invoices for payment via SAP.

    Retrieves "Waiting to be sent" invoices from Alma, extracts and formats data
    needed for submission to SAP for payment. If not a final run, creates and sends
    formatted review reports to Acquisitions staff. If a final run, creates and sends
    formatted cover sheets and summary reports to Acquisitions staff, submits data and
    control files to SAP, and marks invoices as paid in Alma after submission to SAP.
    """
    config_values = load_config_values()
    alma_client = AlmaClient()
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

    # Retrieve and sort invoices from Alma, log result or abort process if no invoices
    # retrieved
    invoice_records = sap.retrieve_sorted_invoices(alma_client)
    if len(invoice_records) > 0:
        logger.info("%s invoices retrieved from Alma", len(invoice_records))
    else:
        logger.info(
            "No invoices waiting to be sent in Alma, aborting SAP invoice process"
        )
        raise click.Abort
    # Parse retrieved invoices and extract data needed for SAP
    problem_invoices, parsed_invoices = sap.parse_invoice_records(
        alma_client, invoice_records
    )
    logger.info("%s problem invoices found.", len(problem_invoices))

    # Split invoices into monographs and serials
    monograph_invoices, serial_invoices = sap.split_invoices_by_field_value(
        parsed_invoices, "type", "monograph", "serial"
    )
    logger.info("%s monograph invoices retrieved and parsed.", len(monograph_invoices))
    logger.info("%s serial invoices retrieved and parsed.", len(serial_invoices))

    # Do the SAP run for monograph invoices, then serial invoices
    monograph_sequence_number = sap.generate_next_sap_sequence_number()
    serial_sequence_number = str(int(monograph_sequence_number) + 1)
    monograph_result = sap.run(
        alma_client,
        problem_invoices,
        monograph_invoices,
        "monograph",
        monograph_sequence_number,
        ctx.obj["today"],
        final_run,
        real_run,
    )
    serial_result = sap.run(
        alma_client,
        problem_invoices,
        serial_invoices,
        "serial",
        serial_sequence_number,
        ctx.obj["today"],
        final_run,
        real_run,
    )

    # Log the final outcome
    logger.info(
        "SAP invoice process completed for a %s "
        "run\n"
        "%i monograph invoices retrieved and "
        "processed:\n"
        "%i SAP monograph invoices\n"
        "%i other payment monograph invoices\n"
        "%i serial invoices retrieved and "
        "processed\n",
        ("final" if final_run else "review"),
        monograph_result["total invoices"],
        monograph_result["sap invoices"],
        monograph_result["other invoices"],
        serial_result["total invoices"],
    )
