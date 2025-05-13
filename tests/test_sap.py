# ruff: noqa: PLR2004, FBT003

import collections
import datetime
import json
from unittest.mock import MagicMock, call

import pytest
import requests

from sapinvoices import sap


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


def test_parse_invoice_records(alma_client):
    invoices = sap.retrieve_sorted_invoices(alma_client)
    problem_invoices, parsed_invoices = sap.parse_invoice_records(alma_client, invoices)
    assert len(parsed_invoices) == 3
    assert len(problem_invoices) == 2
    assert problem_invoices[0]["fund_errors"][0] == "over-encumbered"
    assert problem_invoices[1]["fund_errors"][0] == "over-encumbered"
    assert problem_invoices[1]["multibyte_errors"][0] == {
        "character": "‑",  # noqa: RUF001 non-breaking hyphen, not hyphen-minus
        "field": "vendor:address:lines:0",
    }


def test_parse_invoice_with_no_address_vendor(alma_client):
    invoices_with_no_vendor_address = []

    with open(
        "tests/fixtures/invoice_with_no_vendor_address.json", encoding="utf-8"
    ) as invoice_no_vendor_address_file:
        invoices_with_no_vendor_address.append(json.load(invoice_no_vendor_address_file))
    problem_invoices, parsed_invoices = sap.parse_invoice_records(
        alma_client, invoices_with_no_vendor_address
    )
    assert len(parsed_invoices) == 0
    assert len(problem_invoices) == 1
    assert problem_invoices[0]["vendor_address_error"] == "vendor_no_address"


def test_contains_multibyte():
    invoice_with_multibyte = {
        "id": {
            "level 2": [
                "this is a multibyte character ‑",  # noqa: RUF001
                "this is also ‑ a multibyte character",  # noqa: RUF001
                "this is not a multibyte character -",
            ]
        }
    }
    has_multibyte = sap.check_for_multibyte(invoice_with_multibyte)
    assert has_multibyte[0]["field"] == "id:level 2:0"
    assert has_multibyte[0]["character"] == "‑"  # noqa: RUF001
    assert has_multibyte[1]["field"] == "id:level 2:1"


def test_does_not_contain_multibyte():
    invoice_without_multibyte = {
        "id": {"level 2": ["this is not a multibyte character -"]}
    }
    no_multibyte = sap.check_for_multibyte(invoice_without_multibyte)
    assert len(no_multibyte) == 0


def test_extract_invoice_data_all_present():
    with open(
        "tests/fixtures/invoice_waiting_to_be_sent.json", encoding="utf-8"
    ) as invoice_waiting_to_be_sent_file:
        invoice_record = json.load(invoice_waiting_to_be_sent_file)
    invoice_data = sap.extract_invoice_data(invoice_record)
    assert invoice_data == {
        "date": datetime.datetime(2021, 9, 27, tzinfo=datetime.UTC),
        "id": "00000055555000000",
        "number": "123456",
        "type": "monograph",
        "payment method": "ACCOUNTINGDEPARTMENT",
        "total amount": 4056.07,
        "currency": "USD",
    }


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


def test_populate_vendor_data(alma_client):
    with open("tests/fixtures/vendor_bkhs.json", encoding="utf-8") as vendor_bkhs_file:
        alma_client.get_vendor_details = MagicMock(
            return_value=json.load(vendor_bkhs_file)
        )
    vendor_data = sap.populate_vendor_data(alma_client, "BKHS")
    alma_client.get_vendor_details.assert_called_with("BKHS")
    assert vendor_data == {
        "name": "The Bookhouse, Inc.",
        "code": "BKHS",
        "address": {
            "lines": ["string", "string", "string", "string", "string"],
            "city": "string",
            "state or province": None,
            "postal code": "string",
            "country": "VU",
        },
    }


def test_populate_vendor_data_empty_address_list(alma_client):
    with open(
        "tests/fixtures/vendor_no_address.json", encoding="utf-8"
    ) as vendor_no_address_file:
        alma_client.get_vendor_details = MagicMock(
            return_value=json.load(vendor_no_address_file)
        )
    with pytest.raises(sap.VendorAddressError):
        sap.populate_vendor_data(alma_client, "vendor_no_address")


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
    with pytest.raises(sap.VendorAddressError):
        sap.determine_vendor_payment_address(vendor_record)


def test_empty_vendor_address_list_raises_error():
    vendor_record = {"contact_info": {"address": []}}
    with pytest.raises(sap.VendorAddressError):
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


def test_country_code_from_address_code_present():
    address = {"country": {"value": "USA"}}
    code = sap.country_code_from_address(address)
    assert code == "US"


def test_country_code_from_address_code_not_present():
    address = {"country": {"value": "Not a Country"}}
    code = sap.country_code_from_address(address)
    assert code == "US"


def test_country_code_from_address_country_not_present():
    address = {}
    code = sap.country_code_from_address(address)
    assert code == "US"


def test_populate_fund_data_success(alma_client):
    retrieved_funds = {}
    with open(
        "tests/fixtures/invoice_waiting_to_be_sent.json", encoding="utf-8"
    ) as invoice_waiting_to_be_sent_file:
        invoice_record = json.load(invoice_waiting_to_be_sent_file)
        fund_data, retrieved_funds = sap.populate_fund_data(
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


def test_populate_fund_data_fund_error(alma_client):
    with open(
        "tests/fixtures/invoice_with_over_encumbrance.json", encoding="utf-8"
    ) as invoice_with_over_encumbrance_file:
        invoice_record = json.load(invoice_with_over_encumbrance_file)
        retrieved_funds = {}
        with pytest.raises(sap.FundError) as err:
            sap.populate_fund_data(alma_client, invoice_record, retrieved_funds)
        assert err.value.fund_codes == ["also-over-encumbered", "over-encumbered"]


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
    assert (
        report
        == """

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
    )


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


def test_generate_summary_warning(problem_invoices):
    warning_message = sap.generate_summary_warning(problem_invoices)
    assert (
        warning_message
        == """Warning! Invoice: 9991
There was a problem retrieving data
for fund: over-encumbered

There was a problem retrieving data
for fund: also-over-encumbered

Invoice field: vendor:address:lines:0
Contains multibyte character: ‑

Invoice field: vendor:city
Contains multibyte character: ƒ

Warning! Invoice: 9992
There was a problem retrieving data
for fund: also-over-encumbered

Invoice field: vendor:address:lines:0
Contains multibyte character: ‑

Warning! Invoice: 9993
No addresses found for vendor: YBP-no-address

Please fix the above before starting a final-run

"""  # noqa: RUF001
    )


def test_generate_summary(invoices_for_sap_with_different_payment_method):
    dfile = "dlibsapg.1001.202110518000000"
    cfile = "clibsapg.1001.202110518000000"
    problem_invoices = []
    summary = sap.generate_summary(
        problem_invoices, invoices_for_sap_with_different_payment_method, dfile, cfile
    )
    assert (
        summary
        == """--- MIT Libraries--- Alma to SAP Invoice Feed



Data file: dlibsapg.1001.202110518000000

Control file: clibsapg.1001.202110518000000



Danger Inc.                            456789210512        150.00
some library solutions from salad      444555210511        1067.04

Total payment:       $1,217.04

Invoice count:       2


Authorized signature __________________________________


BAZ:\t12345\tFoo Bar Books\tFOOBAR
"""
    )


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
