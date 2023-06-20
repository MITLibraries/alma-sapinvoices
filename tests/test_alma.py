import datetime
import urllib.parse

import pytest
import requests.exceptions
import requests_mock


def test_client_initializes_with_expected_values(alma_client):
    assert alma_client.base_url == "https://example.com"
    assert alma_client.headers == {
        "Authorization": "apikey just-for-testing",
        "Accept": "application/json",
        "Content-Type": "application/json",
    }
    assert alma_client.timeout == 10


def test_create_invoice(alma_client):
    test_url = "https://example.com/acq/invoices"
    test_payload = {"test": "invoice_data"}
    mocked_response = {"json": "invoice_response"}
    with requests_mock.Mocker() as mocker:
        mocker.post(test_url, json=mocked_response)
        assert alma_client.create_invoice(test_payload) == mocked_response
        assert mocker.last_request.method == "POST"
        assert mocker.last_request.json() == test_payload
        assert mocker.last_request.url == test_url


def test_create_invoice_line(alma_client):
    invoice_id = "123456789"
    test_url = f"https://example.com/acq/invoices/{invoice_id}/lines"
    test_payload = {"test": "invoice_line_data"}
    mocked_response = {"json": "invoice_line_response"}
    with requests_mock.Mocker() as mocker:
        mocker.post(test_url, json=mocked_response)
        assert (
            alma_client.create_invoice_line(invoice_id, test_payload) == mocked_response
        )
        assert mocker.last_request.method == "POST"
        assert mocker.last_request.json() == test_payload
        assert mocker.last_request.url == test_url


def test_create_vendor(alma_client):
    test_url = "https://example.com/acq/vendors"
    test_payload = {"test": "vendor_data"}
    mocked_response = {"json": "vendor_response"}
    with requests_mock.Mocker() as mocker:
        mocker.post(test_url, json=mocked_response)
        assert alma_client.create_vendor(test_payload) == mocked_response
        assert mocker.last_request.method == "POST"
        assert mocker.last_request.json() == test_payload
        assert mocker.last_request.url == test_url


def test_get_fund_by_code(alma_client):
    test_url = "https://example.com/acq/funds?q=fund_code~ABC&view=full"
    mocked_response = {"json": "fund_response"}
    with requests_mock.Mocker(case_sensitive=True) as mocker:
        mocker.get(
            test_url,
            json=mocked_response,
        )
        assert alma_client.get_fund_by_code("ABC") == mocked_response
        assert mocker.last_request.qs == urllib.parse.parse_qs(
            "q=fund_code~ABC&view=full"
        )
        assert mocker.last_request.url == test_url


def test_get_vendor_details(alma_client):
    test_url = "https://example.com/acq/vendors/BKHS"
    mocked_response = {"json": "vendor_response"}
    with requests_mock.Mocker(case_sensitive=True) as mocker:
        mocker.get(test_url, json=mocked_response)
        assert alma_client.get_vendor_details("BKHS") == mocked_response
        assert mocker.last_request.url == test_url


def test_get_vendor_invoices(alma_client):
    test_url = "https://example.com/acq/vendors/BKHS/invoices?limit=100&offset=0"
    invoice_records = {
        "invoice": [{"record_number": i} for i in range(5)],
        "total_record_count": 5,
    }
    with requests_mock.Mocker(case_sensitive=True) as mocker:
        mocker.get(
            test_url,
            json=invoice_records,
        )
        invoices = alma_client.get_vendor_invoices("BKHS")
        assert list(invoices) == invoice_records["invoice"]
        assert mocker.last_request.url == test_url


def test_mark_invoice_paid(alma_client):
    test_url = "https://example.com/acq/invoices/558809630001021?op=paid"
    invoice_id = "558809630001021"
    payment_date = datetime.datetime(2021, 7, 22)
    payment_amount = "120"
    payment_currency = "USD"
    test_payload = {
        "payment": {
            "voucher_date": payment_date.strftime("%Y-%m-%dT12:00:00Z"),
            "voucher_amount": payment_amount,
            "voucher_currency": {"value": payment_currency},
        }
    }
    mocked_response = {"payment": {"payment_status": {"value": "PAID"}}}
    with requests_mock.Mocker(case_sensitive=True) as mocker:
        mocker.post(
            test_url,
            json=mocked_response,
        )
        assert (
            alma_client.mark_invoice_paid(
                invoice_id,
                payment_date=payment_date,
                payment_amount=payment_amount,
                payment_currency=payment_currency,
            )
            is None
        )
        assert mocker.last_request.url == test_url
        assert mocker.last_request.method == "POST"
        assert mocker.last_request.json() == test_payload


def test_mark_invoice_paid_request_read_timeout(alma_client):
    test_url = "https://example.com/acq/invoices/558809630001021?op=paid"
    invoice_id = "558809630001021"
    payment_date = datetime.datetime(2021, 7, 22)
    payment_amount = "120"
    payment_currency = "USD"
    with requests_mock.Mocker(case_sensitive=True) as mocker:
        mocker.post(
            test_url,
            exc=requests.exceptions.ReadTimeout,
        )
        with pytest.raises(requests.exceptions.RequestException):
            alma_client.mark_invoice_paid(
                invoice_id,
                payment_date=payment_date,
                payment_amount=payment_amount,
                payment_currency=payment_currency,
            )


def test_mark_invoice_paid_request_status_error(alma_client):
    test_url = "https://example.com/acq/invoices/558809630001021?op=paid"
    invoice_id = "558809630001021"
    payment_date = datetime.datetime(2021, 7, 22)
    payment_amount = "120"
    payment_currency = "USD"
    with requests_mock.Mocker(case_sensitive=True) as mocker:
        mocker.post(test_url, json={}, status_code=404)
        with pytest.raises(requests.exceptions.RequestException):
            alma_client.mark_invoice_paid(
                invoice_id,
                payment_date=payment_date,
                payment_amount=payment_amount,
                payment_currency=payment_currency,
            )


def test_mark_invoice_paid_request_value_error(alma_client):
    test_url = "https://example.com/acq/invoices/558809630001021?op=paid"
    invoice_id = "558809630001021"
    payment_date = datetime.datetime(2021, 7, 22)
    payment_amount = "120"
    payment_currency = "USD"
    mocked_response = {"payment": {"payment_status": {"value": "FOO"}}}
    with requests_mock.Mocker(case_sensitive=True) as mocker:
        mocker.post(test_url, json=mocked_response)
        with pytest.raises(ValueError):
            alma_client.mark_invoice_paid(
                invoice_id,
                payment_date=payment_date,
                payment_amount=payment_amount,
                payment_currency=payment_currency,
            )


def test_get_invoices_by_status(alma_client):
    invoice_records = {
        "invoice": [{"record_number": i} for i in range(5)],
        "total_record_count": 5,
    }
    test_url = (
        "https://example.com/acq/invoices?invoice_workflow_status"
        "=test&limit=100&offset=0"
    )
    with requests_mock.Mocker() as mocker:
        mocker.get(
            test_url,
            json=invoice_records,
        )
        invoices = alma_client.get_invoices_by_status("test")
        assert list(invoices) == invoice_records["invoice"]
        assert mocker.last_request.url == test_url


def test_get_paged(alma_client):
    with requests_mock.Mocker() as mocker:
        mocker.get(
            "https://example.com/paged?limit=10&offset=0",
            complete_qs=True,
            json={
                "fake_records": [{"record_number": i} for i in range(10)],
                "total_record_count": 15,
            },
        )
        mocker.get(
            "https://example.com/paged?limit=10&offset=10",
            complete_qs=True,
            json={
                "fake_records": [{"record_number": i} for i in range(10, 15)],
                "total_record_count": 15,
            },
        )
        records = alma_client.get_paged(
            endpoint="paged",
            record_type="fake_records",
            limit=10,
        )
        assert len(list(records)) == 15


def test_process_invoice(alma_client):
    test_url = "https://example.com/acq/invoices/00000055555000000?op=process_invoice"
    mocked_response = {"json": "processed_invoice"}
    with requests_mock.Mocker() as mocker:
        mocker.post(
            test_url,
            json=mocked_response,
        )
        assert alma_client.process_invoice("00000055555000000") == mocked_response
        assert mocker.last_request.url == test_url
        assert mocker.last_request.method == "POST"
