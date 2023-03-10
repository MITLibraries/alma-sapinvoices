import json
import os
from datetime import datetime

import boto3
import pytest
import requests_mock
from click.testing import CliRunner
from fabric.testing.fixtures import sftp as mocked_sftp  # noqa
from moto import mock_ses, mock_ssm

from sapinvoices.alma import AlmaClient


@pytest.fixture(autouse=True)
def aws_credentials():
    os.environ["AWS_ACCESS_KEY_ID"] = "testing"
    os.environ["AWS_SECRET_ACCESS_KEY"] = "testing"
    os.environ["AWS_SECURITY_TOKEN"] = "testing"
    os.environ["AWS_SESSION_TOKEN"] = "testing"


@pytest.fixture(autouse=True)
def test_env():
    os.environ = {
        "ALMA_API_URL": "https://example.com",
        "ALMA_API_READ_WRITE_KEY": "just-for-testing",
        "ALMA_API_TIMEOUT": "10",
        "LOG_LEVEL": "INFO",
        "SAP_DROPBOX_CLOUDCONNECTOR_JSON": json.dumps({"test": "test"}),
        "SAP_REPLY_TO_EMAIL": "replyto@example.com",
        "SAP_FINAL_RECIPIENT_EMAIL": "final@example.com",
        "SAP_REVIEW_RECIPIENT_EMAIL": "review@example.com",
        "SENTRY_DSN": None,
        "SES_SEND_FROM_EMAIL": "from@example.com",
        "SSM_PATH": "/test/example/",
        "WORKSPACE": "test",
    }
    yield


@pytest.fixture()
def runner():
    return CliRunner()


# API fixtures
@pytest.fixture()
def alma_client():
    return AlmaClient()


@pytest.fixture(autouse=True)
def mocked_ses():
    with mock_ses():
        ses = boto3.client("ses", region_name="us-east-1")
        ses.verify_email_identity(EmailAddress="from@example.com")
        yield ses


@pytest.fixture(name="test_sftp_private_key")
def test_sftp_private_key_fixture():
    with open(
        "tests/fixtures/sample-ssh-key", "r", encoding="utf-8"
    ) as test_ssh_key_file:
        yield test_ssh_key_file.read()


@pytest.fixture(autouse=True)
def mocked_ssm():
    with mock_ssm():
        ssm = boto3.client("ssm", region_name="us-east-1")

        ssm.put_parameter(
            Name="/test/example/SAP_SEQUENCE",
            Value="1001,20210722000000,ser",
            Type="StringList",
        )
        ssm.put_parameter(
            Name="/test/example/TEST_PARAM",
            Value="abc123",
            Type="SecureString",
        )
        yield ssm


@pytest.fixture()
def mocked_alma_no_invoices():
    with requests_mock.Mocker() as mocker:
        mocker.get(
            "https://example.com/acq/invoices?"
            "invoice_workflow_status=Waiting+to+be+Sent&limit=100&offset=0",
            json={"total_record_count": 0},
        )
        yield mocker


@pytest.fixture(autouse=True)
def mocked_alma():
    with requests_mock.Mocker(case_sensitive=True) as mocker:
        with open("tests/fixtures/invoices.json", encoding="utf-8") as invoices_file:
            mocker.get(
                "https://example.com/acq/invoices?"
                "invoice_workflow_status=Waiting+to+be+Sent",
                json=json.load(invoices_file),
            )
        mocker.post(
            "https://example.com/acq/invoices/0000055555000000?op=paid",
            complete_qs=True,
            json={"payment": {"payment_status": {"desc": "string", "value": "PAID"}}},
        )
        mocker.post(
            "https://example.com/acq/invoices/01?op=paid",
            complete_qs=True,
            json={"payment": {"payment_status": {"desc": "string", "value": "PAID"}}},
        )
        mocker.post(
            "https://example.com/acq/invoices/02?op=paid",
            complete_qs=True,
            json={"payment": {"payment_status": {"desc": "string", "value": "WRONG"}}},
        )
        mocker.post(
            "https://example.com/acq/invoices/03?op=paid",
            complete_qs=True,
            json={"payment": {"payment_status": {"desc": "string", "value": "PAID"}}},
        )

        with open(
            "tests/fixtures/vendor_aaa.json", encoding="utf-8"
        ) as vendor_aaa_file:
            mocker.get(
                "https://example.com/acq/vendors/AAA", json=json.load(vendor_aaa_file)
            )
        with open(
            "tests/fixtures/vendor_vend-s.json", encoding="utf-8"
        ) as vendor_s_file:
            mocker.get(
                "https://example.com/acq/vendors/VEND-S", json=json.load(vendor_s_file)
            )
        with open(
            "tests/fixtures/vendor_multibyte-address.json", encoding="utf-8"
        ) as vendor_multibyte_address_file:
            mocker.get(
                "https://example.com/acq/vendors/multibyte-address",
                json=json.load(vendor_multibyte_address_file),
            )
        with open(
            "tests/fixtures/vendor_no_address.json", encoding="utf-8"
        ) as vendor_no_address_file:
            mocker.get(
                "https://example.com/acq/vendors/vendor_no_address",
                json=json.load(vendor_no_address_file),
            )

        with open("tests/fixtures/funds.json", encoding="utf-8") as funds_file:
            funds = json.load(funds_file)
            mocker.get(
                "https://example.com/acq/funds?q=fund_code~ABC",
                json={"fund": [funds["fund"][0]], "total_record_count": 1},
            )
            mocker.get(
                "https://example.com/acq/funds?q=fund_code~DEF",
                json={"fund": [funds["fund"][1]], "total_record_count": 1},
            )
            mocker.get(
                "https://example.com/acq/funds?q=fund_code~GHI",
                json={"fund": [funds["fund"][2]], "total_record_count": 1},
            )
            mocker.get(
                "https://example.com/acq/funds?q=fund_code~JKL",
                json={"fund": [funds["fund"][3]], "total_record_count": 1},
            )
            mocker.get(
                "https://example.com/acq/funds?q=fund_code~over-encumbered",
                json={"total_record_count": 0},
            )
            mocker.get(
                "https://example.com/acq/funds?q=fund_code~also-over-encumbered",
                json={"total_record_count": 0},
            )

            yield mocker


@pytest.fixture()
def invoices_for_sap_with_different_payment_method():
    """a list of invoices which includes an invoice with
    a payment method other than ACCOUNTINGDEPARTMENT which should
    get filtered out when generating summary reports"""
    invoices = [
        {
            "date": datetime(2021, 5, 12),
            "id": "0000055555000000",
            "number": "456789",
            "type": "monograph",
            "payment method": "ACCOUNTINGDEPARTMENT",
            "total amount": 150,
            "currency": "USD",
            "vendor": {
                "name": "Danger Inc.",
                "code": "DANGER",
                "address": {
                    "lines": [
                        "123 salad Street",
                        "Second Floor",
                    ],
                    "city": "San Francisco",
                    "state or province": "CA",
                    "postal code": "94109",
                    "country": "US",
                },
            },
            "funds": {
                "123456-0000001": {
                    "amount": 150,
                    "cost object": "123456",
                    "G/L account": "0000001",
                },
            },
        },
        {
            "date": datetime(2021, 5, 11),
            "id": "0000055555000002",
            "number": "444555",
            "type": "monograph",
            "payment method": "ACCOUNTINGDEPARTMENT",
            "total amount": 1067.04,
            "currency": "USD",
            "vendor": {
                "name": "some library solutions from salad",
                "code": "YBPE-M",
                "address": {
                    "lines": [
                        "P.O. Box 123456",
                    ],
                    "city": "Atlanta",
                    "state or province": "GA",
                    "postal code": "30384-7991",
                    "country": "US",
                },
            },
            "funds": {
                "123456-0000001": {
                    "amount": 608,
                    "cost object": "123456",
                    "G/L account": "0000001",
                },
                "123456-0000002": {
                    "amount": 148.50,
                    "cost object": "123456",
                    "G/L account": "0000002",
                },
                "1123456-0000003": {
                    "amount": 235.54,
                    "cost object": "123456",
                    "G/L account": "0000003",
                },
                "123456-0000004": {
                    "amount": 75,
                    "cost object": "123456",
                    "G/L account": "0000004",
                },
            },
        },
        {
            "date": datetime(2021, 5, 12),
            "id": "0000055555000003",
            "number": "12345",
            "type": "monograph",
            "payment method": "BAZ",
            "total amount": 150,
            "currency": "USD",
            "vendor": {
                "name": "Foo Bar Books",
                "code": "FOOBAR",
                "address": {
                    "lines": [
                        "123 some street",
                    ],
                    "city": "San Francisco",
                    "state or province": "CA",
                    "postal code": "94109",
                    "country": "US",
                },
            },
            "funds": {
                "123456-0000001": {
                    "amount": 150,
                    "cost object": "123456",
                    "G/L account": "0000001",
                },
            },
        },
    ]
    return invoices


@pytest.fixture()
def invoices_for_sap():
    invoices = [
        {
            "date": datetime(2021, 5, 12),
            "id": "0000055555000000",
            "number": "456789",
            "type": "monograph",
            "payment method": "ACCOUNTINGDEPARTMENT",
            "total amount": 150,
            "currency": "USD",
            "vendor": {
                "name": "Danger Inc.",
                "code": "FOOBAR-M",
                "address": {
                    "lines": [
                        "123 salad Street",
                        "Second Floor",
                    ],
                    "city": "San Francisco",
                    "state or province": "CA",
                    "postal code": "94109",
                    "country": "US",
                },
            },
            "funds": {
                "123456-0000001": {
                    "amount": 150,
                    "cost object": "123456",
                    "G/L account": "0000001",
                },
            },
        },
        {
            "date": datetime(2021, 5, 11),
            "id": "0000055555000000",
            "number": "444555",
            "type": "monograph",
            "payment method": "ACCOUNTINGDEPARTMENT",
            "total amount": 1067.04,
            "currency": "USD",
            "vendor": {
                "name": "some library solutions from salad",
                "code": "YBPE-M",
                "address": {
                    "lines": [
                        "P.O. Box 123456",
                    ],
                    "city": "Atlanta",
                    "state or province": "GA",
                    "postal code": "30384-7991",
                    "country": "US",
                },
            },
            "funds": {
                "123456-0000001": {
                    "amount": 608,
                    "cost object": "123456",
                    "G/L account": "0000001",
                },
                "123456-0000002": {
                    "amount": 148.50,
                    "cost object": "123456",
                    "G/L account": "0000002",
                },
                "1123456-0000003": {
                    "amount": 235.54,
                    "cost object": "123456",
                    "G/L account": "0000003",
                },
                "123456-0000004": {
                    "amount": 75,
                    "cost object": "123456",
                    "G/L account": "0000004",
                },
            },
        },
        {
            "date": datetime(2021, 5, 12),
            "id": "0000055555000000",
            "number": "456789",
            "type": "monograph",
            "payment method": "ACCOUNTINGDEPARTMENT",
            "total amount": 150,
            "currency": "USD",
            "vendor": {
                "name": "one address line",
                "code": "FOOBAR-M",
                "address": {
                    "lines": [
                        "123 some street",
                    ],
                    "city": "San Francisco",
                    "state or province": "CA",
                    "postal code": "94109",
                    "country": "US",
                },
            },
            "funds": {
                "123456-0000001": {
                    "amount": 150,
                    "cost object": "123456",
                    "G/L account": "0000001",
                },
            },
        },
    ]
    return invoices


@pytest.fixture()
def problem_invoices():
    problem_invoice_list = [
        {
            "fund_errors": ["over-encumbered", "also-over-encumbered"],
            "multibyte_errors": [
                {"field": "vendor:address:lines:0", "character": "‑"},
                {"field": "vendor:city", "character": "ƒ"},
            ],
            "date": datetime(2021, 5, 12),
            "id": "9991",
            "number": "456789",
            "type": "monograph",
            "payment method": "ACCOUNTINGDEPARTMENT",
            "total amount": 150,
            "currency": "USD",
            "vendor": {
                "name": "Danger Inc.",
                "code": "FOOBAR-M",
                "address": {
                    "lines": [
                        "12‑3 salad Street",
                        "Second Floor",
                    ],
                    "city": "San ƒrancisco",
                    "state or province": "CA",
                    "postal code": "94109",
                    "country": "US",
                },
            },
        },
        {
            "fund_errors": ["also-over-encumbered"],
            "multibyte_errors": [{"field": "vendor:address:lines:0", "character": "‑"}],
            "date": datetime(2021, 5, 11),
            "id": "9992",
            "number": "444555",
            "type": "monograph",
            "payment method": "ACCOUNTINGDEPARTMENT",
            "total amount": 1067.04,
            "currency": "USD",
            "vendor": {
                "name": "some library solutions from salad",
                "code": "YBPE-M",
                "address": {
                    "lines": [
                        "P.O. Box 123456",
                    ],
                    "city": "Atlanta",
                    "state or province": "GA",
                    "postal code": "30384‑7991",
                    "country": "US",
                },
            },
        },
        {
            "vendor_address_error": "YBP-no-address",
            "date": datetime(2021, 5, 11),
            "id": "9993",
            "number": "444666",
            "type": "monograph",
            "payment method": "ACCOUNTINGDEPARTMENT",
            "total amount": 1067.04,
            "currency": "USD",
        },
    ]
    return problem_invoice_list


@pytest.fixture()
def sap_data_file():
    """a string representing a datafile of invoices to send to SAP

    this test data is formatted to make it more readable
    each line corresponds to a field in the SAP data file spec
    See https://docs.google.com/spreadsheets/d/1PSEYSlPaQ0g2LTEIR6hdyBPzWrZLRK2K/
    edit#gid=1667272331

    """
    sap_data = "B\
20210518\
20210518\
456789210512    \
X000\
400000\
          150.00\
 \
 \
  \
    \
 \
X\
Danger Inc.                        \
San Francisco                      \
123 salad Street                   \
 \
Second Floor                       \
94109     \
CA \
US \
                                                  \
                                   \
\n\
D\
0000001   \
123456      \
          150.00\
 \
\n\
B\
20210518\
20210518\
444555210511    \
X000\
400000\
         1067.04\
 \
 \
  \
    \
 \
X\
some library solutions from salad  \
Atlanta                            \
P.O. Box 123456                    \
 \
                                   \
30384-7991\
GA \
US \
                                                  \
                                   \
\n\
C\
0000001   \
123456      \
          608.00\
 \
\n\
C\
0000002   \
123456      \
          148.50\
 \
\n\
C\
0000003   \
123456      \
          235.54\
 \
\n\
D\
0000004   \
123456      \
           75.00\
 \
\n\
B\
20210518\
20210518\
456789210512    \
X000\
400000\
          150.00\
 \
 \
  \
    \
 \
X\
one address line                   \
San Francisco                      \
123 some street                    \
 \
                                   \
94109     \
CA \
US \
                                                  \
                                   \
\n\
D\
0000001   \
123456      \
          150.00\
 \
\n"
    return sap_data
