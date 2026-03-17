# ruff: noqa: PLR2004, FBT003

import collections
import datetime
import json
from unittest.mock import MagicMock, call, patch

import pytest
import requests

from sapinvoices import sap


@pytest.fixture
def problem_invoices():
    return {
        "id": "1",
        "errors": [
            sap.VendorError.no_address("foo"),
            sap.VendorError.invalid_financial_sys_code("123AB", "foo"),
        ],
    }, {
        "id": "2",
        "errors": [
            sap.MultibyteCharacterError("foo", "‑"),  # noqa: RUF001
            sap.MultibyteCharacterError("bar", "ƒ"),
            sap.NoFundReturnedError("foo"),
        ],
    }


@pytest.fixture
def generic_alma_invoice_record():
    return {
        "number": "123456",
        "vendor": {"value": "BKHS"},
        "id": "00000055555000000",
        "invoice_date": "2021-09-27Z",
        "total_amount": 100.00,
        "currency": {"value": "USD"},
        "payment_method": {"value": "ACCOUNTINGDEPARTMENT"},
        "invoice_lines": {
            "invoice_line": [
                {
                    "fund_distribution": [
                        {"fund_code": {"value": "FUND1"}, "amount": 50.00}
                    ]
                },
                {
                    "fund_distribution": [
                        {"fund_code": {"value": "FUND2"}, "amount": 50.00}
                    ]
                },
            ]
        },
    }


@pytest.fixture
def generic_alma_vendor_record():
    return {
        "name": "generic vendor",
        "code": "generic_vendor",
        "financial_sys_code": "123456",
        "contact_info": {
            "address": [
                {
                    "line1": "address line 1",
                    "line2": "address line 2",
                    "line3": "address line 3",
                    "line4": "address line 4",
                    "line5": "address line 5",
                    "city": "fooappolis",
                    "state_province": "FOO",
                    "postal_code": "12345-6789",
                    "country": {"value": "FOO"},
                    "address_type": [
                        {"value": "not-payment"},
                        {"value": "also-not-payment"},
                    ],
                },
                {
                    "line1": "payment address line 1",
                    "line2": "payment address line 2",
                    "line3": "payment address line 3",
                    "line4": "payment address line 4",
                    "line5": "payment address line 5",
                    "city": "barrappolis",
                    "state_province": "BAR",
                    "postal_code": "12345-6789",
                    "country": {"value": "BAR"},
                    "address_type": [{"value": "payment"}],
                },
            ]
        },
    }


@pytest.fixture
def generic_alma_fund_record_1():
    return {
        "total_record_count": 1,
        "fund": [{"external_id": "1234567-000001"}],
    }


@pytest.fixture
def generic_alma_fund_record_2():
    return {
        "total_record_count": 1,
        "fund": [{"external_id": "1234567-000002"}],
    }


def test_parse_invoice_records(alma_client):
    """Test parsing the list of invoices returned from Alma.

    Fixture data contains 6 alma invoice records, 3 of which have errors
    either in the invoice data itself or in the vendor data or fund data.

    """
    invoices = sap.retrieve_sorted_invoices(alma_client)
    problem_invoices, parsed_invoices = sap.parse_invoice_records(alma_client, invoices)
    assert len(parsed_invoices) == 3
    assert len(problem_invoices) == 3


def test_retrieve_sorted_invoices(alma_client):
    alma_client.get_invoices_by_status = MagicMock()
    alma_client.get_invoices_by_status.return_value = iter(
        [
            {"vendor": {"value": "BBB"}, "number": "456"},
            {"vendor": {"value": "AAA"}, "number": "123"},
            {"vendor": {"value": "BBB"}, "number": "123"},
        ]
    )
    invoices = sap.retrieve_sorted_invoices(alma_client)
    alma_client.get_invoices_by_status.assert_called_with("Waiting to be Sent")
    assert invoices[0]["vendor"]["value"] == "AAA"
    assert invoices[0]["number"] == "123"
    assert invoices[1]["vendor"]["value"] == "BBB"
    assert invoices[1]["number"] == "123"
    assert invoices[2]["vendor"]["value"] == "BBB"
    assert invoices[2]["number"] == "456"


def test_contains_multibyte_returns_list_of_multibyte_error_exception_objects():
    invoice_with_multibyte = {
        "foo": {
            "bar": [
                "this is a multibyte character ‑",  # noqa: RUF001
                "this is also ‑ a multibyte character",  # noqa: RUF001
                "this is not a multibyte character -",
            ]
        }
    }
    has_multibyte = sap.check_for_multibyte(invoice_with_multibyte)
    # check that both multibyte characters were identified and retured
    assert len(has_multibyte) == 2

    # check that both are the correct type of exception
    assert isinstance(has_multibyte[0], sap.MultibyteCharacterError)
    assert isinstance(has_multibyte[1], sap.MultibyteCharacterError)

    # check that the correct data was passed when instantiating the exception
    assert str(has_multibyte[0]) == str(
        sap.MultibyteCharacterError("foo: bar: line 1", "‑")  # noqa: RUF001
    )
    assert str(has_multibyte[1]) == str(
        sap.MultibyteCharacterError("foo: bar: line 2", "‑")  # noqa: RUF001
    )


def test_does_not_contain_multibyte_returns_zero_length_list():
    invoice_without_multibyte = {
        "id": {"level 2": ["this is not a multibyte character -"]}
    }
    no_multibyte = sap.check_for_multibyte(invoice_without_multibyte)
    assert len(no_multibyte) == 0


def test_parse_single_invoice_success(
    alma_client,
    generic_alma_invoice_record,
    generic_alma_vendor_record,
    generic_alma_fund_record_1,
    generic_alma_fund_record_2,
):
    alma_client.get_vendor_details = MagicMock(return_value=generic_alma_vendor_record)
    alma_client.get_fund_by_code = MagicMock(
        side_effect=[generic_alma_fund_record_1, generic_alma_fund_record_2]
    )

    invoice_data, _, _ = sap.parse_single_invoice(
        alma_client, generic_alma_invoice_record, {}, {}
    )

    assert "errors" not in invoice_data
    assert invoice_data["date"] == datetime.datetime(2021, 9, 27, tzinfo=datetime.UTC)
    assert invoice_data["id"] == "00000055555000000"
    assert invoice_data["number"] == "123456"
    assert invoice_data["type"] == "monograph"
    assert invoice_data["payment method"] == "ACCOUNTINGDEPARTMENT"
    assert invoice_data["total amount"] == 100.00
    assert invoice_data["currency"] == "USD"

    assert invoice_data["vendor"]["name"] == "generic vendor"
    assert invoice_data["vendor"]["code"] == "generic_vendor"
    assert invoice_data["vendor"]["sap_vendor_account"] == "123456"
    assert invoice_data["vendor"]["sap_vendor_type_flag"] == "0000"
    assert invoice_data["vendor"]["address"]["lines"] == [
        "payment address line 1",
        "payment address line 2",
        "payment address line 3",
        "payment address line 4",
        "payment address line 5",
    ]
    assert invoice_data["vendor"]["address"]["city"] == "barrappolis"
    assert invoice_data["vendor"]["address"]["state or province"] == "BAR"
    assert invoice_data["vendor"]["address"]["postal code"] == "12345-6789"
    assert invoice_data["vendor"]["address"]["country"] == "US"

    assert invoice_data["funds"]["1234567-000001"]["amount"] == 50.00
    assert invoice_data["funds"]["1234567-000001"]["cost object"] == "1234567"
    assert invoice_data["funds"]["1234567-000001"]["G/L account"] == "000001"
    assert invoice_data["funds"]["1234567-000002"]["amount"] == 50.00
    assert invoice_data["funds"]["1234567-000002"]["cost object"] == "1234567"
    assert invoice_data["funds"]["1234567-000002"]["G/L account"] == "000002"


def test_parse_single_invoice_uses_vendor_cache(
    alma_client,
    generic_alma_fund_record_1,
    generic_alma_fund_record_2,
    generic_alma_invoice_record,
):

    vendor_code = generic_alma_invoice_record["vendor"]["value"]

    # create cached vendor data using the vendor code from the
    # invoice. The shape of the vendor data doesn't matter for
    # this test, we just want to assert that the cached data is
    # used.
    cached_vendor_data = {vendor_code: {"cached": True}}
    alma_client.get_fund_by_code = MagicMock(
        side_effect=[generic_alma_fund_record_1, generic_alma_fund_record_2]
    )
    alma_client.get_vendor_details = MagicMock()
    sap_invoice_data, _, _ = sap.parse_single_invoice(
        alma_client, generic_alma_invoice_record, cached_vendor_data, {}
    )
    # check that we did NOT call the API
    alma_client.get_vendor_details.assert_not_called()
    # check that the vendor data in the sap invoice data matches what is in the cache
    assert sap_invoice_data["vendor"] == {"cached": True}


def test_parse_single_invoice_vendor_no_address_error(
    alma_client,
    generic_alma_invoice_record,
    generic_alma_vendor_record,
    generic_alma_fund_record_1,
    generic_alma_fund_record_2,
):
    # remove the vendor address from the vendor fixture data
    generic_alma_vendor_record["contact_info"]["address"] = []
    alma_client.get_vendor_details = MagicMock(return_value=generic_alma_vendor_record)
    alma_client.get_fund_by_code = MagicMock(
        side_effect=[generic_alma_fund_record_1, generic_alma_fund_record_2]
    )
    sap_invoice_data, _, _ = sap.parse_single_invoice(
        alma_client, generic_alma_invoice_record, {}, {}
    )
    assert sap_invoice_data.get("errors") is not None
    assert any(isinstance(e, sap.VendorError) for e in sap_invoice_data["errors"])


def test_parse_single_invoice_vendor_invalid_financial_sys_code_error(
    alma_client,
    generic_alma_invoice_record,
    generic_alma_vendor_record,
    generic_alma_fund_record_1,
    generic_alma_fund_record_2,
):
    # introduce an invalid SAP vendor ID in the vendor fixture data
    generic_alma_vendor_record["financial_sys_code"] = "INVALID"
    alma_client.get_vendor_details = MagicMock(return_value=generic_alma_vendor_record)
    alma_client.get_fund_by_code = MagicMock(
        side_effect=[generic_alma_fund_record_1, generic_alma_fund_record_2]
    )
    sap_invoice_data, _, _ = sap.parse_single_invoice(
        alma_client, generic_alma_invoice_record, {}, {}
    )
    assert sap_invoice_data.get("errors") is not None
    assert any(isinstance(e, sap.VendorError) for e in sap_invoice_data["errors"])


def test_parse_single_invoice_fund_error(
    alma_client, generic_alma_invoice_record, generic_alma_vendor_record
):
    alma_client.get_vendor_details = MagicMock(return_value=generic_alma_vendor_record)
    alma_client.get_fund_by_code = MagicMock(return_value={"total_record_count": 0})
    sap_invoice_data, _, _ = sap.parse_single_invoice(
        alma_client, generic_alma_invoice_record, {}, {}
    )
    assert sap_invoice_data.get("errors") is not None
    assert any(isinstance(e, sap.NoFundReturnedError) for e in sap_invoice_data["errors"])


def test_parse_single_invoice_populates_vendor_cache(
    alma_client,
    generic_alma_invoice_record,
    generic_alma_vendor_record,
    generic_alma_fund_record_1,
    generic_alma_fund_record_2,
):
    alma_client.get_vendor_details = MagicMock(return_value=generic_alma_vendor_record)
    alma_client.get_fund_by_code = MagicMock(
        side_effect=[generic_alma_fund_record_1, generic_alma_fund_record_2]
    )
    vendor_code = generic_alma_invoice_record["vendor"]["value"]
    _, updated_vendors, _ = sap.parse_single_invoice(
        alma_client, generic_alma_invoice_record, {}, {}
    )
    assert vendor_code in updated_vendors


def test_parse_single_invoice_multibyte_error(
    alma_client, generic_alma_invoice_record, generic_alma_fund_record_1
):
    with open("tests/fixtures/vendor_multibyte-address.json", encoding="utf-8") as f:
        alma_client.get_vendor_details = MagicMock(return_value=json.load(f))
    alma_client.get_fund_by_code = MagicMock(return_value=generic_alma_fund_record_1)
    sap_invoice_data, _, _ = sap.parse_single_invoice(
        alma_client, generic_alma_invoice_record, {}, {}
    )
    assert sap_invoice_data.get("errors") is not None
    assert any(
        isinstance(e, sap.MultibyteCharacterError) for e in sap_invoice_data["errors"]
    )


def test_extract_invoice_data_missing_data_raises_error():
    incomplete_invoice_record = {
        "number": "67890",
        "vendor": {"value": "BKHS", "desc": "The Bookhouse, Inc."},
    }
    with pytest.raises(KeyError):
        sap.extract_invoice_data(incomplete_invoice_record)


def test_get_purchase_type_serial():
    purchase_type = sap.get_purchase_type("test-S")
    assert purchase_type == "serial"


def test_get_purchase_type_monograph():
    purchase_type = sap.get_purchase_type("test")
    assert purchase_type == "monograph"


def test_parse_vendor_record(generic_alma_vendor_record):
    parsed_vendor_data, errors = sap.parse_vendor_record(generic_alma_vendor_record)
    assert errors is None
    assert parsed_vendor_data == {
        "name": "generic vendor",
        "code": "generic_vendor",
        "sap_vendor_account": "123456",
        "sap_vendor_type_flag": "0000",
        "address": {
            "lines": [
                "payment address line 1",
                "payment address line 2",
                "payment address line 3",
                "payment address line 4",
                "payment address line 5",
            ],
            "city": "barrappolis",
            "state or province": "BAR",
            "postal code": "12345-6789",
            "country": "US",
        },
    }


def test_parse_vendor_record_empty_address_list_raises_error(generic_alma_vendor_record):

    # empty out the vendor addresses
    generic_alma_vendor_record["contact_info"]["address"] = []

    parsed_vendor_record, vendor_errors = sap.parse_vendor_record(
        generic_alma_vendor_record
    )
    assert parsed_vendor_record is None
    assert any(isinstance(e, sap.VendorError) for e in vendor_errors)


def test_determine_vendor_payment_address_present():
    vendor_record = {
        "contact_info": {
            "address": [
                {"address_type": [{"value": "order", "desc": "Order"}]},
                {
                    "address_type": [
                        {"value": "claim", "desc": "Claim"},
                        {"value": "payment", "desc": "Payment"},
                    ]
                },
                {"address_type": [{"value": "returns", "desc": "Returns"}]},
            ],
        },
    }
    address = sap.determine_vendor_payment_address(vendor_record)
    assert address == {
        "address_type": [
            {"value": "claim", "desc": "Claim"},
            {"value": "payment", "desc": "Payment"},
        ]
    }


def test_determine_vendor_payment_address_not_present():
    vendor_record = {
        "contact_info": {
            "address": [
                {"address_type": [{"value": "order", "desc": "Order"}]},
                {"address_type": [{"value": "returns", "desc": "Returns"}]},
            ],
        },
    }
    address = sap.determine_vendor_payment_address(vendor_record)
    assert address == {"address_type": [{"value": "order", "desc": "Order"}]}


def test_no_address_field_in_vendor_data_raises_error():
    vendor_record = {"contact_info": {}}
    with pytest.raises(sap.VendorError):
        sap.determine_vendor_payment_address(vendor_record)


def test_empty_vendor_address_list_raises_error():
    vendor_record = {"contact_info": {"address": []}}
    with pytest.raises(sap.VendorError):
        sap.determine_vendor_payment_address(vendor_record)


def test_address_lines_from_address_all_present():
    address = {
        "line1": "Line 1 data",
        "line2": "Line 2 data",
        "line3": "Line 3 data",
        "line4": "Line 4 data",
        "line5": "Line 5 data",
    }
    lines = sap.address_lines_from_address(address)
    assert lines == [
        "Line 1 data",
        "Line 2 data",
        "Line 3 data",
        "Line 4 data",
        "Line 5 data",
    ]


def test_address_lines_from_address_some_present():
    address = {
        "line1": "Line 1 data",
        "line2": "Line 2 data",
        "line3": "Line 3 data",
    }
    lines = sap.address_lines_from_address(address)
    assert lines == ["Line 1 data", "Line 2 data", "Line 3 data"]


def test_address_lines_from_address_some_null():
    address = {
        "line1": "Line 1 data",
        "line2": "Line 2 data",
        "line3": "Line 3 data",
        "line4": None,
        "line5": None,
    }
    lines = sap.address_lines_from_address(address)
    assert lines == ["Line 1 data", "Line 2 data", "Line 3 data"]


def test_address_lines_from_address_none_present():
    address = {}
    lines = sap.address_lines_from_address(address)
    assert lines == []


def test_country_code_from_address_country_code_in_list():
    address = {"country": {"value": "ARGENTINA"}}
    code = sap.country_code_from_address(address)
    assert code == "AR"


def test_country_code_from_address_country_code_not_in_list():
    address = {"country": {"value": "Not a Country"}}
    code = sap.country_code_from_address(address)
    assert code == "US"


def test_country_code_from_address_country_not_present():
    address = {}
    code = sap.country_code_from_address(address)
    assert code == "US"


def test_get_fund_data_success(alma_client):
    retrieved_funds = {}
    with open(
        "tests/fixtures/invoice_waiting_to_be_sent.json", encoding="utf-8"
    ) as invoice_waiting_to_be_sent_file:
        invoice_record = json.load(invoice_waiting_to_be_sent_file)
        fund_data, retrieved_funds, fund_errors = sap.get_and_parse_fund_data(
            alma_client, invoice_record, retrieved_funds
        )
    fund_data_ordereddict = collections.OrderedDict()
    fund_data_ordereddict["1234567-000001"] = {
        "amount": 3687.32,
        "cost object": "1234567",
        "G/L account": "000001",
    }
    fund_data_ordereddict["1234567-000002"] = {
        "amount": 299,
        "cost object": "1234567",
        "G/L account": "000002",
    }
    fund_data_ordereddict["1234567-000003"] = {
        "amount": 69.75,
        "cost object": "1234567",
        "G/L account": "000003",
    }

    assert fund_data == fund_data_ordereddict
    assert list(retrieved_funds) == ["JKL", "ABC", "DEF", "GHI"]
    assert fund_errors is None


def test_get_fund_data_fund_error(alma_client, generic_alma_invoice_record):
    fund_data_cache = {}
    with patch(
        "sapinvoices.sap.retrieve_fund_record",
        side_effect=sap.NoFundReturnedError("foo"),
    ):
        sap_fund_data, _, fund_errors = sap.get_and_parse_fund_data(
            alma_client, generic_alma_invoice_record, fund_data_cache
        )
    assert sap_fund_data is None
    assert len(fund_errors) == 2


def test_generate_report_success():
    invoices = [
        {
            "date": datetime.datetime(2021, 9, 27, tzinfo=datetime.UTC),
            "id": "00000055555000000",
            "number": "123456",
            "type": "monograph",
            "payment method": "ACCOUNTINGDEPARTMENT",
            "total amount": 4056.07,
            "currency": "USD",
            "vendor": {
                "name": "The Bookhouse, Inc.",
                "code": "BKHS",
                "address": {
                    "lines": [
                        "123 Main Street",
                        "Building 4",
                        "Suite 5",
                        "C/O Mickey Mouse",
                    ],
                    "city": "Anytown",
                    "state or province": None,
                    "postal code": "12345",
                    "country": "VU",
                },
            },
            "funds": {
                "1234567-000001": {
                    "amount": 3687.32,
                    "cost object": "1234567",
                    "G/L account": "000001",
                },
                "1234567-000002": {
                    "amount": 299,
                    "cost object": "1234567",
                    "G/L account": "000002",
                },
                "1234567-000003": {
                    "amount": 69.75,
                    "cost object": "1234567",
                    "G/L account": "000003",
                },
            },
        }
    ]
    today = datetime.datetime(2021, 10, 1, tzinfo=datetime.UTC)
    report = sap.generate_report(today, invoices)
    assert report == """

                                 MIT LIBRARIES


Date: 10/01/2021                          Vendor code   : BKHS
                                          Accounting ID :

Vendor:  The Bookhouse, Inc.
         123 Main Street
         Building 4
         Suite 5
         C/O Mickey Mouse
         Anytown, 12345
         VU

Invoice no.            Fiscal Account     Amount            Inv. Date
------------------     -----------------  -------------     ----------
123456210927           1234567 000001     3,687.32          09/27/2021
123456210927           1234567 000002     299.00            09/27/2021
123456210927           1234567 000003     69.75             09/27/2021


Total/Currency:             4,056.07      USD

Payment Method:  ACCOUNTINGDEPARTMENT


                       Departmental Approval __________________________________

                       Financial Services Approval ____________________________


\f"""


def test_generate_sap_report_email_final_run():
    email = sap.generate_sap_report_email(
        "Summary contents",
        "Report contents",
        "mono",
        datetime.datetime(2021, 10, 1, tzinfo=datetime.UTC),
        True,
    )
    assert email["From"] == "from@example.com"
    assert email["To"] == "final@example.com"
    assert email["Subject"] == "Libraries invoice feed - monos - 20211001"
    assert email["Reply-To"] == "replyto@example.com"
    assert email.get_content_type() == "multipart/mixed"
    assert email.get_body().get_content() == "Summary contents\n"
    attachment = next(email.iter_attachments())
    assert attachment.get_filename() == "cover_sheets_mono_20211001000000.txt"
    assert attachment.get_content() == "Report contents\n"


def test_generate_sap_report_email_review_run():
    email = sap.generate_sap_report_email(
        "Summary contents",
        "Report contents",
        "serial",
        datetime.datetime(2021, 10, 1, tzinfo=datetime.UTC),
        False,
    )
    assert email["From"] == "from@example.com"
    assert email["To"] == "review@example.com"
    assert email["Subject"] == "REVIEW libraries invoice feed - serials - 20211001"
    assert email["Reply-To"] == "replyto@example.com"
    assert email.get_content_type() == "multipart/mixed"
    assert email.get_body().get_content() == "Summary contents\n"
    attachment = next(email.iter_attachments())
    assert attachment.get_filename() == "review_serial_report_20211001000000.txt"
    assert attachment.get_content() == "Report contents\n"


def test_format_address_street_1_line():
    address_lines = ["123 salad Street"]
    (
        payee_name_line_2,
        street_or_po_box_num,
        payee_name_line_3,
    ) = sap.format_address_for_sap(address_lines)
    assert payee_name_line_2 == address_lines[0]
    assert street_or_po_box_num == " "
    assert payee_name_line_3 == " "


def test_format_address_street_2_lines():
    address_lines = ["123 salad Street", "Second Floor"]
    (
        payee_name_line_2,
        street_or_po_box_num,
        payee_name_line_3,
    ) = sap.format_address_for_sap(address_lines)
    assert payee_name_line_2 == address_lines[0]
    assert street_or_po_box_num == address_lines[1]
    assert payee_name_line_3 == " "


def test_format_address_street_3_lines():
    address_lines = ["123 salad Street", "Second Floor", "c/o salad guy"]
    (
        payee_name_line_2,
        street_or_po_box_num,
        payee_name_line_3,
    ) = sap.format_address_for_sap(address_lines)
    assert payee_name_line_2 == address_lines[0]
    assert street_or_po_box_num == address_lines[1]
    assert payee_name_line_3 == address_lines[2]


def test_format_address_po_box_1_line():
    address_lines = ["P.O. Box 123456"]
    (
        payee_name_line_2,
        street_or_po_box_num,
        payee_name_line_3,
    ) = sap.format_address_for_sap(address_lines)
    assert payee_name_line_2 == address_lines[0]
    assert street_or_po_box_num == " "
    assert payee_name_line_3 == " "


def test_format_address_po_box_2_lines():
    address_lines = ["c/o salad guy", "P.O. Box 123456"]
    (
        payee_name_line_2,
        street_or_po_box_num,
        payee_name_line_3,
    ) = sap.format_address_for_sap(address_lines)
    assert payee_name_line_2 == address_lines[0]
    assert street_or_po_box_num == address_lines[1]
    assert payee_name_line_3 == " "


def test_generate_sap_data_success(invoices_for_sap, sap_data_file):
    today = datetime.datetime(2021, 5, 18, tzinfo=datetime.UTC)
    report = sap.generate_sap_data(today, invoices_for_sap)
    assert report == sap_data_file


def test_calculate_invoices_total_amount():
    invoices = [dict(zip(["total amount"], [0.1], strict=True)) for x in range(100)]
    total_amount = sap.calculate_invoices_total_amount(invoices)
    assert total_amount == 10


def test_generate_summary_warning():
    problem_invoices = {
        "id": "1",
        "errors": [
            sap.VendorError.no_address("foo"),
            sap.VendorError.invalid_financial_sys_code("123AB", "foo"),
        ],
    }, {
        "id": "2",
        "errors": [
            sap.MultibyteCharacterError("foo", "‑"),  # noqa: RUF001
            sap.MultibyteCharacterError("bar", "ƒ"),
            sap.NoFundReturnedError("foo"),
        ],
    }
    warning_message = sap.generate_summary_warning(problem_invoices)
    assert warning_message == """Warning! Invoice: 1
No addresses found for vendor: foo

Invalid financial system code: 123AB, for vendor: foo.
Financial system code must be 6 digits long and contain only numbers.

Warning! Invoice: 2
Invoice field: foo
Contains multibyte character: ‑

Invoice field: bar
Contains multibyte character: ƒ

There was a problem retrieving data
for fund: foo

Please fix the above before starting a final-run

"""  # noqa: RUF001


def test_generate_summary(invoices_for_sap_with_different_payment_method):
    dfile = "dlibsapg.1001.202110518000000"
    cfile = "clibsapg.1001.202110518000000"
    problem_invoices = []
    summary = sap.generate_summary(
        problem_invoices, invoices_for_sap_with_different_payment_method, dfile, cfile
    )
    assert summary == """--- MIT Libraries--- Alma to SAP Invoice Feed



Data file: dlibsapg.1001.202110518000000

Control file: clibsapg.1001.202110518000000



Danger Inc.                            456789210512        150.00
some library solutions from salad      444555210511        1067.04

Total payment:       $1,217.04

Invoice count:       2


Authorized signature __________________________________


BAZ:\t12345\tFoo Bar Books\tFOOBAR
"""


def test_generate_sap_control(sap_data_file):
    invoice_total = 1367.40
    sap_control = sap.generate_sap_control(sap_data_file, invoice_total)
    assert sap_control[0:16] == "0000000000001182"
    assert sap_control[16:32] == "0000000000000009"
    assert sap_control[32:52] == "00000000000000000000"
    assert sap_control[52:72] == "00000000000000136740"
    assert sap_control[72:92] == "00000000000000136740"
    assert sap_control[92:112] == "00100100000000000000"
    assert len(sap_control.encode("utf-8")) == 113


def test_generate_next_sap_sequence_number(ssm_client):
    assert (
        ssm_client.get_parameter_value("/test/example/sap_sequence")
        == "1001,20210722000000,ser"
    )
    new_sap_sequence = sap.generate_next_sap_sequence_number()
    assert new_sap_sequence == "1002"


@pytest.mark.usefixtures("mocked_ssm_bad_sequence_number")
def test_generate_next_sap_sequence_number_fail(ssm_client):
    assert (
        ssm_client.get_parameter_value("/test/example/sap_sequence")
        == "1,20210722000000,ser"
    )
    with pytest.raises(sap.SapSequenceError):
        sap.generate_next_sap_sequence_number()


def test_update_sap_sequence(ssm_client):
    assert (
        ssm_client.get_parameter_value("/test/example/sap_sequence")
        == "1001,20210722000000,ser"
    )
    response = sap.update_sap_sequence(
        "1002", datetime.datetime(2021, 7, 23, tzinfo=datetime.UTC), "mono"
    )
    assert response["ResponseMetadata"]["HTTPStatusCode"] == 200
    assert (
        ssm_client.get_parameter_value("/test/example/sap_sequence")
        == "1002,20210723000000,mono"
    )


def test_generate_sap_file_names():
    data_file_name, control_file_name = sap.generate_sap_file_names(
        "1002", datetime.datetime(2021, 12, 17, tzinfo=datetime.UTC)
    )
    assert data_file_name == "dlibsapg.1002.20211217000000"
    assert control_file_name == "clibsapg.1002.20211217000000"


def test_mark_invoices_paid_all_successful(alma_client):
    date = datetime.datetime(2022, 1, 7, tzinfo=datetime.UTC)
    invoices = [
        {"id": "1", "total amount": "100", "currency": "USD"},
        {"id": "2", "total amount": "200", "currency": "GBH"},
        {"id": "3", "total amount": "300", "currency": "GBH"},
    ]
    alma_client.mark_invoice_paid = MagicMock(return_value=None)
    expected_calls = [
        call("1", date, "100", "USD"),
        call("2", date, "200", "GBH"),
        call("3", date, "300", "GBH"),
    ]
    paid_invoice_count = sap.mark_invoices_paid(
        alma_client, invoices, datetime.datetime(2022, 1, 7, tzinfo=datetime.UTC)
    )
    assert alma_client.mark_invoice_paid.call_args_list == expected_calls
    assert paid_invoice_count == 3


def test_mark_invoices_paid_error(alma_client, caplog):
    date = datetime.datetime(2022, 1, 7, tzinfo=datetime.UTC)
    invoices = [
        {"id": "1", "total amount": "100", "currency": "USD"},
        {"id": "2", "total amount": "200", "currency": "GBH"},
        {"id": "3", "total amount": "300", "currency": "GBH"},
    ]
    alma_client.mark_invoice_paid = MagicMock(
        side_effect=[
            {"payment": {"payment_status": {"value": "PAID"}}},
            ValueError,
            {"payment": {"payment_status": {"value": "PAID"}}},
        ]
    )

    expected_calls = [
        call("1", date, "100", "USD"),
        call("2", date, "200", "GBH"),
        call("3", date, "300", "GBH"),
    ]

    paid_invoice_count = sap.mark_invoices_paid(
        alma_client, invoices, datetime.datetime(2022, 1, 7, tzinfo=datetime.UTC)
    )
    assert alma_client.mark_invoice_paid.call_args_list == expected_calls
    assert paid_invoice_count == 2
    assert "Something went wrong marking invoice '2' paid in Alma." in caplog.text


def test_mark_invoices_paid_handles_request_exception(alma_client, caplog):
    date = datetime.datetime(2022, 1, 7, tzinfo=datetime.UTC)
    invoices = [
        {"id": "1", "total amount": "100", "currency": "USD"},
        {"id": "2", "total amount": "200", "currency": "GBH"},
        {"id": "3", "total amount": "300", "currency": "GBH"},
    ]
    alma_client.mark_invoice_paid = MagicMock(
        side_effect=[
            {"payment": {"payment_status": {"value": "PAID"}}},
            {"payment": {"payment_status": {"value": "PAID"}}},
            requests.exceptions.RequestException,
        ]
    )

    expected_calls = [
        call("1", date, "100", "USD"),
        call("2", date, "200", "GBH"),
        call("3", date, "300", "GBH"),
    ]
    paid_invoice_count = sap.mark_invoices_paid(
        alma_client, invoices, datetime.datetime(2022, 1, 7, tzinfo=datetime.UTC)
    )
    assert alma_client.mark_invoice_paid.call_args_list == expected_calls
    assert paid_invoice_count == 2
    assert "Something went wrong marking invoice '3' paid in Alma." in caplog.text


def test_run_not_final_not_real(
    alma_client,
    caplog,
    invoices_for_sap_with_different_payment_method,
    problem_invoices,
):
    result = sap.run(
        alma_client,
        problem_invoices,
        invoices_for_sap_with_different_payment_method,
        "monograph",
        "0003",
        datetime.datetime(2022, 1, 11, tzinfo=datetime.UTC),
        final_run=False,
        real_run=False,
    )
    assert result == {
        "total invoices": 3,
        "sap invoices": 2,
        "other invoices": 1,
    }
    assert "Monographs report:" in caplog.text


def test_run_not_final_real(
    caplog,
    alma_client,
    invoices_for_sap,
    problem_invoices,
):
    result = sap.run(
        alma_client,
        problem_invoices,
        invoices_for_sap,
        "monograph",
        "0003",
        datetime.datetime(2022, 1, 11, tzinfo=datetime.UTC),
        final_run=False,
        real_run=True,
    )
    assert result == {
        "total invoices": 3,
        "sap invoices": 3,
        "other invoices": 0,
    }
    assert "Monographs email sent with message ID:" in caplog.text


def test_run_final_not_real(
    caplog,
    alma_client,
    invoices_for_sap,
    problem_invoices,
):
    sap.run(
        alma_client,
        problem_invoices,
        invoices_for_sap,
        "monograph",
        "0003",
        datetime.datetime(2022, 1, 11, tzinfo=datetime.UTC),
        final_run=True,
        real_run=False,
    )
    assert "Monographs control file contents:" in caplog.text


def test_run_final_real(
    alma_client,
    monkeypatch,
    caplog,
    mocked_sftp,
    invoices_for_sap,
    test_sftp_private_key,
    problem_invoices,
):
    monkeypatch.setenv(
        "SAP_DROPBOX_CLOUDCONNECTOR_JSON",
        json.dumps(
            {
                "HOST": "example.com",
                "PORT": "8000",
                "KEY": test_sftp_private_key,
                "USER": "test-dropbox-user",
            }
        ),
    )

    sap.run(
        alma_client,
        problem_invoices,
        invoices_for_sap,
        "monograph",
        "0003",
        datetime.datetime(2022, 1, 11, tzinfo=datetime.UTC),
        final_run=True,
        real_run=True,
    )
    assert (
        "Sent control file 'clibsapg.0003.20220111000000' to SAP dropbox test"
        in caplog.text
    )
    assert (
        "SSM parameter '/test/example/sap_sequence' was updated to "
        "'0003,20220111000000,mono' with type=StringList" in caplog.text
    )
    assert "3 monograph invoices successfully marked as paid in Alma" in caplog.text
