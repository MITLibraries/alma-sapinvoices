"""Module with functions necessary for processing invoices to send to SAP."""

import base64
import collections
import datetime
import json
import logging
from io import StringIO
from math import fsum
from typing import Any, Literal

import fabric
import requests.exceptions
from paramiko import RSAKey

from sapinvoices.alma import AlmaClient
from sapinvoices.config import load_config_values
from sapinvoices.email import Email
from sapinvoices.ssm import SSM

logger = logging.getLogger(__name__)

with open("config/countries.json", encoding="UTF-8") as f:
    COUNTRIES = json.load(f)


class MultibyteCharacterError(Exception):
    """Exception raised when an invoice contains multibyte characters."""

    def __init__(self, field: str, character: str) -> None:
        self.field = field
        self.character = character
        super().__init__(
            f"Invoice field: {field}\nContains multibyte character: {character}"
        )


class VendorError(Exception):
    """Exception raised when a vendor record has errors."""

    @classmethod
    def invalid_financial_sys_code(
        cls, invalid_financial_sys_code: str, vendor_code: str
    ) -> "VendorError":
        return cls(
            f"Invalid financial system code: {invalid_financial_sys_code}, "
            f"for vendor: {vendor_code}.\n"
            "Financial system code must be 6 digits long and contain only numbers."
        )

    @classmethod
    def no_address(cls, vendor_code: str) -> "VendorError":
        return cls(f"No addresses found for vendor: {vendor_code}")


class NoFundReturnedError(Exception):
    """Exception raised when a fund is not returned by Alma.

    This likely means that the fund is not ready to be used in a PO-line, which could be
    because the fund is overexpended, overencumbered, or not active for the current fiscal
    period.
    """

    def __init__(self, fund_code: str) -> None:
        self.fund_code = fund_code
        super().__init__(f"There was a problem retrieving data\nfor fund: {fund_code}")


class SapSequenceError(Exception):
    """Exception raised when SAP sequence number is less than three digits."""


def retrieve_sorted_invoices(alma_client: AlmaClient) -> list:
    """Retrieve sorted invoices from Alma.

    Retrieve invoices from Alma with status 'Waiting to be sent' and return them
    sorted by vendor code and then by invoice number for the same vendor.
    """
    data = list(alma_client.get_invoices_by_status("Waiting to be Sent"))
    return sorted(data, key=lambda i: (i["vendor"].get("value", 0), i.get("number", 0)))


def parse_invoice_records(
    alma_client: AlmaClient, alma_invoice_records: list[dict]
) -> tuple[list[dict[Any, Any]], list[dict[Any, Any]]]:
    """Orchestrates parsing a list of Alma invoice records.

    Caches vendor and fund data so we only call the alma API once for each vendor or fund

    Separates invoices into those with errors that need manual review and those
    that can be sent to SAP.

    Returns:
        problem invoices: A list of invoices with errors
        parsed invoices: A list of invoices ready to be sent to SAP

    """
    parsed_invoices = []
    problem_invoices = []
    vendor_data_cache: dict[Any, Any] = {}
    fund_data_cache: dict[Any, Any] = {}
    for count, alma_invoice_record in enumerate(alma_invoice_records):
        logger.info(
            "Extracting data for invoice record %s, record %i of %i",
            alma_invoice_record["id"],
            count + 1,
            len(alma_invoice_records),
        )
        sap_invoice_data, vendor_data_cache, fund_data_cache = parse_single_invoice(
            alma_client, alma_invoice_record, vendor_data_cache, fund_data_cache
        )
        if sap_invoice_data.get("errors"):
            problem_invoices.append(sap_invoice_data)
        else:
            parsed_invoices.append(sap_invoice_data)
    return problem_invoices, parsed_invoices


def parse_single_invoice(
    alma_client: AlmaClient,
    alma_invoice_record: dict,
    vendor_data_cache: dict[Any, Any],
    fund_data_cache: dict[Any, Any],
) -> tuple[dict[Any, Any], dict[Any, Any], dict[Any, Any]]:
    """Parses an Alma invoice record, returning the data required by SAP.

    Some of the data we send to SAP is available directly in the alma invoice record.
    Vendor and fund data needs to be looked up in additional Alma API Calls.
    We cache the results of these additional API calls so we only have to make them
    once for a given vendor or fund.

    Returns:
        sap_invoice_data: parsed invoice data including vendor and fund info
        vendor_data_cache: vendor data retrieved from Alma. Already parsed for SAP
        fund_data_cache: fund data retrieved from Alma. Not parsed for SAP.

        * because of how fund amounts need to be accumulated, the fund data in the
        cache is just the raw fund record returned from Alma

    sap_invoice_data takes the following shape:
        {
            'date': datetime,
            'id': str,
            'number': str,
            'type': str,
            'payment method': str,
            'total amount': float,
            'currency': str,
            'vendor': {
                'name': str,
                'code': str,
                'sap_vendor_account': str,
                'sap_vendor_type_flag': str,
                'address': {
                    'lines': list[str],
                    'city': str,
                    'state or province': str,
                    'postal code': str,
                    'country': str,
                },
            },
            'funds': {
                external_id: {
                    'amount': float,
                    'cost object': str,
                    'G/L account': str,
                },
                ... # one entry for each unique fund external ID in the invoice
            },

            errors:[
                {
                    'type': str,
                    'message': str
                },
                ... # one entry for each error
            ]
        }
    """
    errors: list[VendorError | NoFundReturnedError | MultibyteCharacterError] = []
    sap_invoice_data = extract_invoice_data(alma_invoice_record)
    vendor_code = alma_invoice_record["vendor"]["value"]

    # get parsed vendor data and handle any errors raised in the process
    vendor_data, vendor_data_cache, vendor_errors = get_vendor_data(
        alma_client, vendor_code, vendor_data_cache
    )
    if vendor_errors:
        errors.extend(vendor_errors)
    else:
        sap_invoice_data["vendor"] = vendor_data

    # get parsed fund data and handle any errors raised in the process
    fund_data, fund_data_cache, fund_errors = get_and_parse_fund_data(
        alma_client, alma_invoice_record, fund_data_cache
    )
    if fund_errors:
        errors.extend(fund_errors)
    else:
        sap_invoice_data["funds"] = fund_data

    # check invoice data for multibyte characters
    multibyte_errors = check_for_multibyte(sap_invoice_data)
    if multibyte_errors:
        errors.extend(multibyte_errors)

    if errors:
        sap_invoice_data["errors"] = errors

    return sap_invoice_data, vendor_data_cache, fund_data_cache


def get_vendor_data(
    alma_client: AlmaClient,
    vendor_code: str,
    vendor_data_cache: dict,
) -> tuple[dict | None, dict, list[VendorError] | None]:
    """Retrieve parsed vendor data from cache or Alma API.

    Returns:
        The parsed vendor data, or None if there was an error.

        The (possibly) updated cache of parsed vendor data.

        A list of VendorError objects, or None there
        were no  vendor errors
    """
    if vendor_code not in vendor_data_cache:
        vendor_data, vendor_errors = parse_vendor_record(
            alma_client.get_vendor_details(vendor_code)
        )
        if vendor_errors:
            return None, vendor_data_cache, vendor_errors
        vendor_data_cache[vendor_code] = vendor_data

    return vendor_data_cache[vendor_code], vendor_data_cache, None


def check_for_multibyte(
    data: dict | list | str, path: str = ""
) -> list[MultibyteCharacterError]:
    """Check for the existence of multi-byte characters.

    Multi-byte characters are those that require more than
    one byte to be represented in UTF-8.

    WHY?: SAP system does not support multibyte characters.
    """
    errors: list[MultibyteCharacterError] = []

    if isinstance(data, dict):
        # for each key in the dict, recurse into the value,
        # building up the path as we go so we can report
        # the full field name in the error message
        for key, value in data.items():
            nested_path = f"{path}: {key}" if path else key
            errors.extend(check_for_multibyte(value, nested_path))

    elif isinstance(data, list):
        # for each item in the list, recurse into the item,
        # adding the index to the path so we can identify
        # which list element contains the error
        for i, item in enumerate(data):
            errors.extend(check_for_multibyte(item, f"{path}: line {i+1}"))

    elif isinstance(data, str):
        # base case - we've reached a string value, check each
        # character for multibyte encoding. if we find one,
        # add an error object to the list of errors.
        errors.extend(
            MultibyteCharacterError(path, char)
            for char in data
            if len(char.encode("utf-8")) > 1
        )

    # non-string, non-dict, non-list values (e.g. int, float, datetime)
    # are ignored since they cannot contain multibyte characters

    return errors


def extract_invoice_data(alma_invoice_record: dict) -> dict:
    """Extract data needed for SAP from Alma invoice record.

    see https://developers.exlibrisgroup.com/alma/apis/docs/xsd/rest_invoice.xsd/
    for a description of the fields in the Alma invoice record.

    This is the data we can extract directly from the invoice record without needing
    to make any additional API calls.

    """
    return {
        "date": datetime.datetime.strptime(
            alma_invoice_record["invoice_date"], "%Y-%m-%dZ"
        ).replace(tzinfo=datetime.UTC),
        "id": alma_invoice_record["id"],
        "number": alma_invoice_record["number"],
        "type": get_purchase_type(alma_invoice_record["vendor"]["value"]),
        "payment method": alma_invoice_record["payment_method"]["value"],
        "total amount": alma_invoice_record["total_amount"],
        "currency": alma_invoice_record["currency"]["value"],
    }


def get_purchase_type(vendor_code: str) -> Literal["serial", "monograph"]:
    """Determine purchase type (serial or monograph) based on vendor code."""
    if vendor_code.endswith("-S"):
        return "serial"
    return "monograph"


def parse_vendor_record(
    alma_vendor_record: dict,
) -> tuple[dict | None, list[VendorError] | None]:
    """Parse an Alma vendor record and return required vendor data for SAP.

    Returns:
        Parsed vendor data or None if there were any vendor errors

        A list of in vendor data which need manual review or
        None if there were no errors.
    """
    errors: list[VendorError] = []
    address = {}
    sap_vendor_account = ""
    sap_vendor_type_flag = ""

    try:
        address = determine_vendor_payment_address(alma_vendor_record)
    except VendorError as err:
        errors.append(err)

    try:
        sap_vendor_account, sap_vendor_type_flag = determine_sap_vendor_account(
            alma_vendor_record
        )
    except VendorError as err:
        errors.append(err)

    if errors:
        return None, errors

    return {
        "name": alma_vendor_record["name"],
        "code": alma_vendor_record["code"],
        "sap_vendor_account": sap_vendor_account,
        "sap_vendor_type_flag": sap_vendor_type_flag,
        "address": {
            "lines": address_lines_from_address(address),
            "city": address.get("city"),
            "state or province": address.get("state_province"),
            "postal code": address.get("postal_code"),
            "country": country_code_from_address(address),
        },
    }, None


def determine_vendor_payment_address(alma_vendor_record: dict) -> dict:
    """Determine payment address from Alma vendor record.

    Given an Alma vendor record, determines which of the addresses in the record is
    the payment address and returns it. If no address is marked as the payment address,
    returns the first address in the record.

    Returns:
        vendor address: The vendor address marked as the payment address in the
            vendor record. Otherwise, the first address in the record.

    Raises:
        VendorError: If the vendor record has no addresses.
    """
    try:
        for address in alma_vendor_record["contact_info"]["address"]:
            if any(
                "payment" in address_type.values()
                for address_type in address["address_type"]
            ):
                return address
        return alma_vendor_record["contact_info"]["address"][0]
    except (IndexError, KeyError) as exc:
        raise VendorError.no_address(alma_vendor_record.get("code", "")) from exc


def address_lines_from_address(address: dict) -> list:
    """Get non-null address lines from an Alma vendor address.

    Given an address from an Alma vendor record, return a list of the non-null
    address lines from the address.
    """
    line_names = ["line1", "line2", "line3", "line4", "line5"]
    return [
        address.get(line_name)
        for line_name in line_names
        if address.get(line_name) is not None
    ]


def country_code_from_address(address: dict) -> str:
    """Get SAP country code from an Alma vendor address.

    Returns a country code as required by SAP from a file of country/code
    lookup pairs, given a vendor address dict from an Alma vendor record. If there is
    no country value in the record OR the country value does not exist in the lookup
    file, returns 'US' as a default.
    """
    try:
        country = address["country"]["value"]
        return COUNTRIES[country]
    except KeyError:
        return "US"


def determine_sap_vendor_account(alma_vendor_record: dict) -> tuple[str, str]:
    """Assign the vendor account code and type flag.

    SAP requires a vendor account number and a vendor type flag for each invoice.
    SAP has a master file of vendor records which can be referenced via the vendor
    account number in the datafile we send.

    Libraries Acquisitions staff record the SAP vendor account number in the
    'financial system code' field in the Alma vendor record as necessary.

    If there is a financial system code in the Alma vendor record,
    we use that as the SAP vendor account number and we set the vendor type flag to "0000"
    indicating that this vendor has a master record in SAP.

    If the financial system code is blank, the SAP vendor account number
    is set to "400000", a one-time vendor account code in SAP,
    and we set the vendor type flag to "X000", indicating a one-time vendor.

    To be valid, the SAP vendor account number must be 6 digits long and contain
    only numbers.

    Returns:
        sap vendor account: The account number for the vendor in SAP
        sap vendor type flag: A flag indicating whether the account number is for a vendor
            from the master list or a one-time vendor

    Raises:
        VendorError: if the financial system code in the record is
            not a valid SAP vendor account code. Note that we just check well formedness
            of the account code here (length and numeric), but we do not check that
            the code is actually in use by SAP.
    """
    valid_number_of_digits = 6
    one_time_vendor_account = "400000"
    vendor_type_flag = {"one_time": "X000", "master": "0000"}
    sap_vendor = {}
    sap_vendor["sap_vendor_account"] = (
        alma_vendor_record.get("financial_sys_code") or one_time_vendor_account
    )
    # Check that the sap vendor account number is well formed (6 digits, numeric).
    # if not, raise a VendorError.
    if not (
        len(sap_vendor["sap_vendor_account"]) == valid_number_of_digits
        and sap_vendor["sap_vendor_account"].isdigit()
    ):
        raise VendorError.invalid_financial_sys_code(
            sap_vendor["sap_vendor_account"], alma_vendor_record.get("code", "")
        )

    sap_vendor["sap_vendor_type_flag"] = (
        vendor_type_flag["master"]
        if alma_vendor_record.get("financial_sys_code")
        else vendor_type_flag["one_time"]
    )
    return sap_vendor["sap_vendor_account"], sap_vendor["sap_vendor_type_flag"]


def get_and_parse_fund_data(
    alma_client: AlmaClient,
    alma_invoice_record: dict,
    fund_data_cache: dict,
) -> tuple[dict | None, dict, list[NoFundReturnedError] | None]:
    """Retrieve and parse fund data for an invoice.

    Returns:
        Parsed fund data or None if any fund were not
            retrieved successfully

        Updated fund records retrieved from Alma

        A list of errors encountered retrieving fund data or
            None if no errors were encountered

    """
    sap_fund_data: dict[str, Any] = {}
    errors: list[NoFundReturnedError] = []

    invoice_lines = alma_invoice_record["invoice_lines"]["invoice_line"]
    for invoice_line in invoice_lines:
        for fund_distribution in invoice_line["fund_distribution"]:
            fund_code = fund_distribution["fund_code"]["value"]
            amount = fund_distribution["amount"]
            try:
                alma_fund_record, fund_data_cache = retrieve_fund_record(
                    alma_client, fund_code, fund_data_cache
                )
            except NoFundReturnedError as err:
                errors.append(err)
                continue

            external_id = alma_fund_record["fund"][0]["external_id"].strip()
            cost_object, gl_account = external_id.split("-")

            if external_id in sap_fund_data:
                sap_fund_data[external_id]["amount"] += amount
            else:
                sap_fund_data[external_id] = {
                    "amount": amount,
                    "cost object": cost_object,
                    "G/L account": gl_account,
                }

    if errors:
        return None, fund_data_cache, errors

    return collections.OrderedDict(sorted(sap_fund_data.items())), fund_data_cache, None


def retrieve_fund_record(
    alma_client: AlmaClient,
    fund_code: str,
    fund_data_cache: dict,
) -> tuple[dict, dict]:
    """Retrieve an Alma fund record from cache or the Alma API.

    The Alma API call we make here will only return a record if the fund is ready to be
    used for a PO-Line. That is, the fund must be allocated and active
    in the current fiscal period. This excludes overexpended or overencumbered funds.

    If a fund is not ready to be used in a PO-line the Alma API will return
    {"total_record_count": 0}

    Returns:
        tuple: (alma_fund_record, updated fund_data_cache)

    Raises:
        FundNotFoundError: If the fund is not returned by the Alma API.

    """
    if fund_code in fund_data_cache:
        return fund_data_cache[fund_code], fund_data_cache

    logger.debug("Retrieving data for fund %s", fund_code)
    alma_fund_record = alma_client.get_fund_by_code(fund_code)

    # If a fund is not ready to be used in a PO-line (see above) the Alma API will return
    # a total record count of 0
    if alma_fund_record["total_record_count"] == 0:
        raise NoFundReturnedError(fund_code)

    fund_data_cache[fund_code] = alma_fund_record
    return alma_fund_record, fund_data_cache


def split_invoices_by_field_value(
    invoices: list[dict],
    field: str,
    first_value: str,
    second_value: str | None = None,
) -> tuple[list[dict[Any, Any]], list[dict[Any, Any]]]:
    """Split a list of parsed invoices into two based on an invoice field's value.

    Returns two lists, one of invoice dicts with the first value in the provided
    field, and another of invoice dicts with the second value in the provided field. If
    no second value is provided, the second list returned includes all invoices with
    anything other than the first value in the field.
    """
    invoices_with_first_value = []
    invoices_with_second_value = []
    for invoice in invoices:
        if invoice[field] == first_value:
            invoices_with_first_value.append(invoice)
        elif second_value is not None and invoice[field] == second_value:  # noqa: SIM114
            invoices_with_second_value.append(invoice)
        elif second_value is None:
            invoices_with_second_value.append(invoice)
    return invoices_with_first_value, invoices_with_second_value


def generate_report(today: datetime.datetime, invoices: list[dict]) -> str:
    today_string = today.strftime("%m/%d/%Y")
    report = ""
    for invoice in invoices:
        report += f"\n\n{'':33}MIT LIBRARIES\n\n\n"
        report += (
            f"Date: {today_string:<36}Vendor code    : {invoice['vendor']['code']}\n"
        )
        report += (
            f"{'VPF Supplier # :':>58} {invoice['vendor']['sap_vendor_account']}\n\n"
        )
        report += f"Vendor:  {invoice['vendor']['name']}\n"
        for line in invoice["vendor"]["address"]["lines"]:
            report += f"         {line}\n"
        report += "         "
        if invoice["vendor"]["address"]["city"]:
            report += f"{invoice['vendor']['address']['city']}, "
        if invoice["vendor"]["address"]["state or province"]:
            report += f"{invoice['vendor']['address']['state or province']} "
        if invoice["vendor"]["address"]["postal code"]:
            report += f"{invoice['vendor']['address']['postal code']}"
        report += f"\n         {invoice['vendor']['address']['country']}\n\n"
        report += (
            "Invoice no.            Fiscal Account     Amount            Inv. Date\n"
        )
        report += (
            "------------------     -----------------  -------------     ----------\n"
        )
        for fund in invoice["funds"]:
            report += f"{invoice['number'] + invoice['date'].strftime('%y%m%d'):<23}"
            report += (
                f"{invoice['funds'][fund]['cost object']} "
                f"{invoice['funds'][fund]['G/L account']}     "
            )
            report += f"{invoice['funds'][fund]['amount']:<18,.2f}"
            report += f"{invoice['date'].strftime('%m/%d/%Y')}\n"
        report += "\n\n"
        report += (
            f"Total/Currency:             {invoice['total amount']:,.2f}      "
            f"{invoice['currency']}\n\n"
        )
        report += f"Payment Method:  {invoice['payment method']}\n\n\n"
        report += f"{'Departmental Approval':>44} {'':_<34}\n\n"
        report += f"{'Financial Services Approval':>50} {'':_<28}\n\n\n"
        report += "\f"
    return report


def generate_sap_report_email(
    summary: str,
    report: str,
    purchase_type: Literal["mono", "serial"],
    date: datetime.datetime,
    final: bool,  # noqa: FBT001
) -> Email:
    sap_config = load_config_values()
    report_email = Email()
    if final:
        recipients = sap_config["SAP_FINAL_RECIPIENT_EMAIL"]
        subject_string = (
            f"Libraries invoice feed - {purchase_type}s - {date.strftime('%Y%m%d')}"
        )
        attachment_name = (
            f"cover_sheets_{purchase_type}_{date.strftime('%Y%m%d%H%M%S')}.txt"
        )
    else:
        recipients = sap_config["SAP_REVIEW_RECIPIENT_EMAIL"]
        subject_string = (
            f"REVIEW libraries invoice feed - {purchase_type}s - "
            f"{date.strftime('%Y%m%d')}"
        )
        attachment_name = (
            f"review_{purchase_type}_report_{date.strftime('%Y%m%d%H%M%S')}.txt"
        )
    report_email.populate(
        from_address=sap_config["SES_SEND_FROM_EMAIL"],
        to_addresses=recipients,
        reply_to=sap_config["SAP_REPLY_TO_EMAIL"],
        subject=subject_string,
        body=summary,
        attachments=[{"content": report, "filename": attachment_name}],
    )
    return report_email


def format_address_for_sap(address_lines: list) -> tuple[str, str, str]:
    """Assign payee address information to SAP data file fields."""
    payee_name_line_2 = address_lines[0]

    # if there is a second address line element we
    # assign it to the street_or_po_box_num field
    try:
        street_or_po_box_num = address_lines[1]
    except IndexError:
        street_or_po_box_num = " "

    # if there is a third address lines list element we assign it to payee_name_line_3
    try:
        payee_name_line_3 = address_lines[2]
    except IndexError:
        payee_name_line_3 = " "

    return payee_name_line_2, street_or_po_box_num, payee_name_line_3


def generate_sap_data(today: datetime.datetime, invoices: list[dict]) -> str:
    """Format invoice data for SAP.

    Given a list of pre-processed invoices and a date, returns a string of invoice
    data formatted according to Accounts Payable's specifications.
    See https://docs.google.com/spreadsheets/d/1PSEYSlPaQ0g2LTEIR6hdyBPzWrZLRK2K/
    edit#gid=1667272331 for specifications for data file

    """
    today_string = today.strftime("%Y%m%d")
    sap_data = ""
    for invoice in invoices:
        (
            payee_name_line_2,
            street_or_po_box_num,
            payee_name_line_3,
        ) = format_address_for_sap(invoice["vendor"]["address"]["lines"])
        sap_data += "B"
        # date string is supposed to be listed twice
        sap_data += f"{today_string}"  # Document Date
        sap_data += f"{today_string}"  # Baseline Date
        # we add the invoice date to the invoice number to create a hopefully unique
        # External Reference number
        sap_data += f"{invoice['number'] + invoice['date'].strftime('%y%m%d'): <16.16}"
        sap_data += f"{invoice['vendor']['sap_vendor_type_flag']}"
        sap_data += f"{invoice['vendor']['sap_vendor_account']}"
        sap_data += f"{invoice['total amount']:16.2f}"
        # sign of total amount. we don't send credits
        # so this will always be blank (positive)
        sap_data += " "
        sap_data += " "  # payment method
        sap_data += "  "  # payment method supplement
        sap_data += "    "  # payment terms
        sap_data += " "  # payment block
        sap_data += "X"  # individual payee in document
        sap_data += f"{invoice['vendor']['name']: <35.35}"
        sap_data += f"{invoice['vendor']['address']['city'] or ' ': <35.35}"
        sap_data += f"{payee_name_line_2: <35.35}"
        # We treat all addresses as street addresses.
        # PO Box indicator should always be blank.
        sap_data += " "  # PO Box indicator
        sap_data += f"{street_or_po_box_num: <35.35}"
        sap_data += f"{invoice['vendor']['address']['postal code'] or ' ': <10.10}"
        sap_data += f"{invoice['vendor']['address']['state or province'] or ' ': <3.3}"
        sap_data += f"{invoice['vendor']['address']['country'] or ' ': <3.3}"
        sap_data += f"{' ': <50.50}"  # Text: 50
        sap_data += f"{payee_name_line_3: <35.35}"
        sap_data += "\n"
        # write a line for each fund distribution in the invoice
        # the final line should begin with a "D"
        # all previous lines should begin with a "C"
        for i, fund in enumerate(invoice["funds"]):
            sap_data += "D" if i == len(invoice["funds"]) - 1 else "C"
            sap_data += (
                f"{invoice['funds'][fund]['G/L account']: <10.10}"
                f"{invoice['funds'][fund]['cost object']: <12.12}"
            )
            sap_data += f"{invoice['funds'][fund]['amount']:16.2f}"
            # sign of fund amount. we don't send credits
            # so this will always be blank (positive)
            sap_data += " "
            sap_data += "\n"
    return sap_data


def generate_summary_warning(problem_invoices: list) -> str:
    """Generate warning messages in summary output.

    Warns staff about invoice problems that need
    to be resolved before a final-run can take place.
    """
    sections = []
    for invoice in problem_invoices:
        invoice_lines = f'Warning! Invoice: {invoice["id"]}\n'
        invoice_lines += "\n\n".join(str(error) for error in invoice["errors"])
        sections.append(invoice_lines)
    sections.append("Please fix the above before starting a final-run")
    return "\n\n".join(sections) + "\n\n"


def generate_summary(
    problem_invoices: list,
    invoices: list[dict],
    data_file_name: str,
    control_file_name: str,
) -> str:
    excluded_invoices = ""
    invoice_count = 0
    sum_of_invoices = 0.0
    summary = "--- MIT Libraries--- Alma to SAP Invoice Feed\n\n\n\n"
    summary += f"Data file: {data_file_name}\n\n"
    summary += f"Control file: {control_file_name}\n\n\n\n"
    if problem_invoices:
        summary += generate_summary_warning(problem_invoices)
    for invoice in invoices:
        if invoice["payment method"] == "ACCOUNTINGDEPARTMENT":
            summary += f"{invoice['vendor']['name']: <39.39}"
            summary += f"{invoice['number'] + invoice['date'].strftime('%y%m%d'): <20.20}"
            summary += f"{invoice['total amount']:.2f}\n"
            sum_of_invoices += float(invoice["total amount"])
            invoice_count += 1
        else:
            excluded_invoices += f"{invoice['payment method']}:\t"
            excluded_invoices += f"{invoice['number']}\t"
            excluded_invoices += f"{invoice['vendor']['name']}\t"
            excluded_invoices += f"{invoice['vendor']['code']}\n"
    summary += f"\nTotal payment:       ${sum_of_invoices:,.2f}\n\n"
    summary += f"Invoice count:       {invoice_count}\n\n\n"
    summary += "Authorized signature __________________________________\n\n\n"
    summary += f"{excluded_invoices}"
    return summary


def generate_sap_control(sap_data_file: str, invoice_total: float) -> str:
    """Generate a control file for SAP.

    Given a string representing the data file to be sent to SAP and the
    total amount of the invoices in that data file, returns a string
    representing the corresponding control file. see
    https://wikis.mit.edu/confluence/display/SAPdev/MIT+SAP+Dropbox for
    control file format
    """
    # 0-16 count bytes
    sap_control_file = f"{len(sap_data_file.encode('utf-8')):016}"

    # 17-32 the spec says "record count", but accounts payable says that
    # this should be a count of the number of lines in the data file.
    sap_control_file += f"{len(sap_data_file.splitlines()):016}"

    # 33-52 credit total
    # we don't send credits to SAP so this will always be 20 0's
    sap_control_file += "".zfill(20)

    # 53-72 debit total - convert invoice total to string
    # remove decimal to convert dollars to cents
    # and 0-pad to 20 characters
    sap_control_file += f"{invoice_total:.2f}".replace(".", "").zfill(20)

    # 73-92 control 3 summarizing the data file
    # we just repeat the invoice total here
    sap_control_file += f"{invoice_total:.2f}".replace(".", "").zfill(20)

    # 93-112 control 4 summarizing the data file
    # Accounts payable told us to use this string
    sap_control_file += "00100100000000000000"

    # control file ends with a new line
    sap_control_file += "\n"

    return sap_control_file


def generate_next_sap_sequence_number() -> str:
    """Generate the next SAP sequence number.

    Get the current SAP sequence parameter from SSM and return only the sequence
    number incremented by 1.

    sequence number must be at least three digits (one or two digit numbers should be
    stored as zero-padded to three places)
    """
    ssm = SSM()
    sap_config = load_config_values()
    sap_sequence_parameter = ssm.get_parameter_value(sap_config["SAP_SEQUENCE_NUM"])
    split_parameter = sap_sequence_parameter.split(",")
    if len(split_parameter[0]) < 3:  # noqa: PLR2004
        message = (
            f"Invalid SAP sequence: '{split_parameter[0]}', "
            "number must be three or more digits."
        )
        raise SapSequenceError(message)
    return str(int(split_parameter[0]) + 1)


def update_sap_sequence(
    sap_sequence_number: str, date: datetime.datetime, sequence_type: str
) -> dict:
    """Update SAP sequence and post it to SSM Parameter Store."""
    ssm = SSM()
    sap_config = load_config_values()
    date_string = date.strftime("%Y%m%d").ljust(14, "0")
    new_sap_sequence = f"{sap_sequence_number},{date_string},{sequence_type}"
    return ssm.update_parameter_value(
        sap_config["SAP_SEQUENCE_NUM"], new_sap_sequence, "StringList"
    )


def calculate_invoices_total_amount(invoices: list[dict]) -> float:
    return fsum([invoice["total amount"] for invoice in invoices])


def generate_sap_file_names(
    sequence_number: str, date: datetime.datetime
) -> tuple[str, str]:
    date_string = date.strftime("%Y%m%d000000")
    data_file_name = f"dlibsapg.{sequence_number}.{date_string}"
    control_file_name = f"clibsapg.{sequence_number}.{date_string}"
    return data_file_name, control_file_name


def mark_invoices_paid(
    alma_client: AlmaClient, invoices: list[dict], date: datetime.datetime
) -> int:
    paid_invoice_count = 0
    for invoice in invoices:
        invoice_id = invoice["id"]
        logger.debug("Marking invoice '%s' paid", invoice_id)
        logger.debug("date: %s", date)
        logger.debug("total amount: %s", invoice["total amount"])
        logger.debug("currency: %s", invoice["currency"])
        try:
            alma_client.mark_invoice_paid(
                invoice_id, date, invoice["total amount"], invoice["currency"]
            )

            paid_invoice_count += 1
        except (requests.exceptions.RequestException, ValueError):
            logger.exception(
                "Something went wrong marking invoice '%s' paid in Alma.",
                invoice_id,
            )

    return paid_invoice_count


def run(
    alma_client: AlmaClient,
    problem_invoices: list,
    invoices: list[dict],
    invoices_type: Literal["monograph", "serial"],
    sap_sequence_number: str,  # Just the sequence number, e.g. "0003"
    date: datetime.datetime,
    final_run: bool,  # noqa: FBT001
    real_run: bool,  # noqa: FBT001
) -> dict:
    sap_config = load_config_values()
    dropbox_connection = json.loads(sap_config["SAP_DROPBOX_CLOUDCONNECTOR_JSON"])

    logger.info("Starting file generation process for run %s", invoices_type)
    data_file_name, control_file_name = generate_sap_file_names(sap_sequence_number, date)
    logger.info(
        "Generated next SAP file names: %s, %s", data_file_name, control_file_name
    )

    logger.info("Generating %ss summary", invoices_type)
    summary = generate_summary(
        problem_invoices, invoices, data_file_name, control_file_name
    )

    logger.info("Generating %ss report", invoices_type)
    report = generate_report(date, invoices)

    sap_invoices, other_payment_invoices = split_invoices_by_field_value(
        invoices, "payment method", "ACCOUNTINGDEPARTMENT"
    )

    if final_run:
        sap_invoices_total_amount = calculate_invoices_total_amount(sap_invoices)

        logger.info("Final run, generating files for SAP")
        data_file_contents = generate_sap_data(date, sap_invoices)
        control_file_contents = generate_sap_control(
            data_file_contents, sap_invoices_total_amount
        )
        logger.info(
            "%ss data file contents:\n%s", invoices_type.title(), data_file_contents
        )
        logger.info(
            "%ss control file contents:\n%s",
            invoices_type.title(),
            control_file_contents,
        )

        if real_run:
            logger.info("Real run, sending files to SAP dropbox")
            decoded_key = base64.b64decode(dropbox_connection["KEY"]).decode()
            pkey = RSAKey.from_private_key(StringIO(decoded_key))
            with fabric.Connection(
                host=dropbox_connection["HOST"],
                port=dropbox_connection["PORT"],
                user=dropbox_connection["USER"],
                connect_kwargs={
                    "pkey": pkey,
                    "look_for_keys": False,
                    "disabled_algorithms": {"pubkeys": ["rsa-sha2-256", "rsa-sha2-512"]},
                },
            ) as sftp_connection:
                sftp_connection.put(
                    StringIO(data_file_contents),
                    f"dropbox/{data_file_name}",
                )
                logger.info(
                    "Sent data file '%s' to SAP dropbox %s",
                    data_file_name,
                    sap_config["WORKSPACE"],
                )
                sftp_connection.put(
                    StringIO(control_file_contents),
                    f"dropbox/{control_file_name}",
                )
                logger.info(
                    "Sent control file '%s' to SAP dropbox %s",
                    control_file_name,
                    sap_config["WORKSPACE"],
                )

            # Update sequence numbers in SSM
            logger.info("Real run, updating SAP sequence in Parameter Store")
            update_sap_sequence(
                sap_sequence_number,
                date,
                "mono" if invoices_type == "monograph" else "ser",
            )

            # Update invoice statuses in Alma
            logger.info("Real run, marking invoices PAID in Alma")
            count = mark_invoices_paid(alma_client, invoices, date)
            logger.info(
                "%i %s invoices successfully marked as paid in Alma",
                count,
                invoices_type,
            )

    if real_run:
        email = generate_sap_report_email(
            summary,
            report,
            "mono" if invoices_type == "monograph" else invoices_type,
            date,
            final_run,
        )
        response = email.send()
        logger.info(
            "%ss email sent with message ID: %s",
            invoices_type.title(),
            response["MessageId"],
        )
    else:
        logger.info("%ss summary:\n%s\n", invoices_type.title(), summary)
        logger.info("%ss report:\n%s\n", invoices_type.title(), report)

    return {
        "total invoices": len(invoices),
        "sap invoices": len(sap_invoices),
        "other invoices": len(other_payment_invoices),
    }
