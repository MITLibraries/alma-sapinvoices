"""Sample data loader."""
import json
import logging
from typing import List

from requests.exceptions import HTTPError

from sapinvoices.alma import AlmaClient

logger = logging.getLogger(__name__)


def load_sample_data(alma_client: AlmaClient, sample_data_file_contents: dict) -> int:
    invoice_count = 0
    for vendor in sample_data_file_contents:
        vendor_code = create_vendor_if_needed(
            alma_client, sample_data_file_contents[vendor]["vendor_data"]
        )
        next_invoice_number = get_next_vendor_invoice_number(alma_client, vendor_code)
        invoice_ids = create_invoices_with_lines(
            alma_client,
            sample_data_file_contents[vendor]["invoices"],
            sample_data_file_contents[vendor]["abbreviation"],
            next_invoice_number,
        )
        process_invoices(alma_client, invoice_ids)
        invoice_count += len(invoice_ids)
    return invoice_count


def create_vendor_if_needed(alma_client: AlmaClient, vendor_data: dict) -> str:
    """Check if vendor exists in Alma, if not create it."""
    try:
        vendor_code = vendor_data["code"]
        alma_client.get_vendor_details(vendor_code)
        logger.info("Vendor '%s' already exists in Alma, not creating it", vendor_code)
    except HTTPError as err:
        if any(
            item.get("errorCode") == "402880"  # Code for vendor not found
            for item in err.response.json().get("errorList", {}).get("error", {})
        ):
            response_vendor_code = alma_client.create_vendor(vendor_data)["code"]
            logger.info("Vendor '%s' created in Alma", response_vendor_code)
        else:
            logger.error(err.response.text)
            raise err
    return vendor_code


def get_next_vendor_invoice_number(alma_client: AlmaClient, vendor_code: str) -> int:
    latest_number = 0
    vendor_invoices = alma_client.get_vendor_invoices(vendor_code)
    for invoice in vendor_invoices:
        invoice_number = invoice["number"]
        try:
            number_index = invoice_number.index("-") + 1
        except ValueError:
            continue
        number = int(invoice_number[number_index:])
        if number > latest_number:
            latest_number = number
    return latest_number + 1


def create_invoices_with_lines(
    alma_client: AlmaClient,
    invoices: List[dict],
    vendor_abbreviation: str,
    next_invoice_number: int,
) -> list[str]:
    created_invoice_ids = []
    for invoice in invoices:
        invoice_number = f"TestSAPInvoice{vendor_abbreviation}-{next_invoice_number}"
        invoice["post_json"]["number"] = invoice_number
        invoice_alma_id = create_invoice(alma_client, invoice["post_json"])
        created_invoice_ids.append(invoice_alma_id)

        lines_created = create_invoice_lines(
            alma_client, invoice_alma_id, invoice["invoice_lines"]
        )
        logger.info("Created invoice '%s' with %s lines", invoice_number, lines_created)

        next_invoice_number += 1
    return created_invoice_ids


def create_invoice(alma_client: AlmaClient, invoice_data: dict) -> str:
    """Create invoice in Alma and return invoice ID."""
    try:
        response = alma_client.create_invoice(invoice_data)
        logger.info("Invoice created with data: %s", json.dumps(response))
        return response["id"]
    except HTTPError as err:
        logger.error(err.response.text)
        raise err


def create_invoice_lines(
    alma_client: AlmaClient, invoice_alma_id: str, invoice_lines: List[dict]
) -> int:
    """Create invoice lines for a given invoice in Alma."""
    created_lines = 0
    for line in invoice_lines:
        try:
            response = alma_client.create_invoice_line(invoice_alma_id, line)
            logger.info(
                "Invoice line created for invoice '%s' with data: %s",
                invoice_alma_id,
                json.dumps(response),
            )
            created_lines += 1
        except HTTPError as err:
            logger.error(err.response.text)
            raise err
    return created_lines


def process_invoices(alma_client: AlmaClient, invoice_alma_ids: list[str]) -> int:
    processed = 0
    for invoice_id in invoice_alma_ids:
        try:
            response = alma_client.process_invoice(invoice_id)
            logger.info(
                "Invoice '%s' processed in Alma with response: %s ",
                invoice_id,
                json.dumps(response),
            )
            processed += 1
        except HTTPError as err:
            logger.error(err.response.text)
            raise err
    return processed
