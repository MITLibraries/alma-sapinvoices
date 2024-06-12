# ruff: noqa: PLR2004

import json

import pytest
from requests.exceptions import HTTPError

from sapinvoices import sample_data as sd


@pytest.mark.usefixtures("mocked_alma_sample_data")
def test_load_sample_data(alma_client):
    with open(
        "sample-data/sample-sap-invoice-data.json", encoding="utf-8"
    ) as sample_data_file:
        contents = json.load(sample_data_file)
    result = sd.load_sample_data(alma_client, contents)
    assert result == 4


@pytest.mark.usefixtures("mocked_alma_sample_data")
def test_create_vendor_if_needed_creates_vendor(caplog, alma_client):
    result = sd.create_vendor_if_needed(alma_client, {"code": "TestSAPVendor1"})
    assert result == "TestSAPVendor1"
    assert "Vendor 'TestSAPVendor1' created in Alma" in caplog.text


@pytest.mark.usefixtures("mocked_alma_sample_data")
def test_create_vendor_if_needed_vendor_exists(caplog, alma_client):
    result = sd.create_vendor_if_needed(alma_client, {"code": "TestSAPVendor2-S"})
    assert result == "TestSAPVendor2-S"
    assert (
        "Vendor 'TestSAPVendor2-S' already exists in Alma, not creating it" in caplog.text
    )


@pytest.mark.usefixtures("mocked_alma_sample_data")
def test_create_vendor_if_needed_raises_exception(caplog, alma_client):
    with pytest.raises(HTTPError):
        sd.create_vendor_if_needed(alma_client, {"code": "not-a-vendor"})
    assert '{"errorCode":"a-different-error"}' in caplog.text


@pytest.mark.usefixtures("mocked_alma_sample_data")
def test_get_next_vendor_invoice_number_existing_invoices(alma_client):
    result = sd.get_next_vendor_invoice_number(alma_client, "TestSAPVendor1")
    assert result == 3


@pytest.mark.usefixtures("mocked_alma_sample_data")
def test_get_next_vendor_invoice_number_no_existing_invoices(alma_client):
    result = sd.get_next_vendor_invoice_number(alma_client, "TestSAPVendor2-S")
    assert result == 1


@pytest.mark.usefixtures("mocked_alma_sample_data")
def test_get_next_vendor_invoice_number_nonconforming_numbers_exist(alma_client):
    result = sd.get_next_vendor_invoice_number(alma_client, "TestSAPVendor3")
    assert result == 1


@pytest.mark.usefixtures("mocked_alma_sample_data")
def test_create_invoices_with_lines(caplog, alma_client):
    invoices = [
        {"post_json": {}, "invoice_lines": [{"line1": "contents"}]},
        {
            "post_json": {},
            "invoice_lines": [{"line1": "contents"}, {"line2": "contents"}],
        },
    ]
    result = sd.create_invoices_with_lines(alma_client, invoices, "V1", 1)
    assert result == ["alma_id_0001", "alma_id_0002"]
    assert "Created invoice 'TestSAPInvoiceV1-2' with 2 lines" in caplog.text


@pytest.mark.usefixtures("mocked_alma_sample_data")
def test_create_invoice(caplog, alma_client):
    result = sd.create_invoice(alma_client, {"invoice": "has some data"})
    assert result == "alma_id_0001"
    assert 'Invoice created with data: {"id": "alma_id_0001"}' in caplog.text


@pytest.mark.usefixtures("mocked_alma_with_errors")
def test_create_invoice_raises_error(caplog, alma_client):
    with pytest.raises(HTTPError):
        sd.create_invoice(alma_client, {"invoice": "has some data"})
    assert "Error message" in caplog.text


@pytest.mark.usefixtures("mocked_alma_sample_data")
def test_create_invoice_lines(caplog, alma_client):
    invoice_lines = [
        {"line1": "line 1 contents"},
        {"line2": "line 2 contents"},
    ]
    result = sd.create_invoice_lines(alma_client, "alma_id_0001", invoice_lines)
    assert result == 2
    assert (
        "Invoice line created for invoice 'alma_id_0001' with data: "
        '{"id": "alma_id_0001"}' in caplog.text
    )


@pytest.mark.usefixtures("mocked_alma_sample_data")
def test_create_invoice_lines_raises_exception(caplog, alma_client):
    with pytest.raises(HTTPError):
        sd.create_invoice_lines(alma_client, "error_id", [{"invoice_lines": "line"}])
    assert "Error message" in caplog.text


@pytest.mark.usefixtures("mocked_alma_sample_data")
def test_process_invoices(caplog, alma_client):
    invoice_ids = ["alma_id_0001", "alma_id_0002", "alma_id_0003", "alma_id_0004"]
    result = sd.process_invoices(alma_client, invoice_ids)
    assert result == 4
    assert (
        "Invoice 'alma_id_0004' processed in Alma with response: "
        '{"id": "alma_id_0004"}' in caplog.text
    )


@pytest.mark.usefixtures("mocked_alma_sample_data")
def test_process_invoices_raises_exception(caplog, alma_client):
    with pytest.raises(HTTPError):
        sd.process_invoices(alma_client, ["error_id"])
    assert "Error message" in caplog.text
