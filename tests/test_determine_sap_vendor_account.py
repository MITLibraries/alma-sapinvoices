import pytest

from sapinvoices.sap import VendorError, determine_sap_vendor_account


def test_determine_sap_vendor_account_valid():
    vendor_record = {"financial_sys_code": "123456"}
    account, flag = determine_sap_vendor_account(vendor_record)
    assert account == "123456"
    assert flag == "0000"


def test_determine_sap_vendor_account_missing():
    vendor_record = {}
    account, flag = determine_sap_vendor_account(vendor_record)
    assert account == "400000"
    assert flag == "X000"


def test_determine_sap_vendor_account_invalid():
    vendor_record = {"financial_sys_code": "12A456"}  # not all digits
    with pytest.raises(VendorError):
        determine_sap_vendor_account(vendor_record)

    vendor_record = {"financial_sys_code": "12345"}  # too short
    with pytest.raises(VendorError):
        determine_sap_vendor_account(vendor_record)

    vendor_record = {"financial_sys_code": "1234567"}  # too long
    with pytest.raises(VendorError):
        determine_sap_vendor_account(vendor_record)
