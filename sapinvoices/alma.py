import json
import logging
import time
from datetime import datetime
from typing import Generator, Optional
from urllib.parse import urljoin

import requests

from sapinvoices.config import load_config_values as load_alma_config

logger = logging.getLogger(__name__)


class AlmaClient:
    """AlmaClient class.

    An Alma API client with specific functionality necessary for SAP
    processing.

    Notes:
        - All requests to the Alma API include a 0.1 second wait to ensure we don't
          exceed the API rate limit.
        - If no records are found for a given endpoint with the provided parameters,
          Alma will still return a 200 success response with a json object of
          {"total_record_count": 0} and these methods will return that object.

    """

    def __init__(self) -> None:
        """Initialize AlmaClient instance."""
        alma_config = load_alma_config()
        self.base_url = alma_config["ALMA_API_URL"]
        self.headers = {
            "Authorization": f"apikey {alma_config['ALMA_API_READ_WRITE_KEY']}",
            "Accept": "application/json",
            "Content-Type": "application/json",
        }
        self.timeout = float(alma_config["TIMEOUT"])

    def create_invoice(self, invoice_json: dict) -> dict:
        """Create an invoice.

        Creates an invoice in alma using the acquisitions/invoices API endpoint

        Args:
            invoice_json: a python dict representing an invoice object as described here
            - https://developers.exlibrisgroup.com/alma/apis/docs/xsd/rest_invoice.xsd/

        """
        endpoint = "acq/invoices"
        result = requests.post(
            urljoin(self.base_url, endpoint),
            headers=self.headers,
            timeout=self.timeout,
            data=json.dumps(invoice_json),
        )
        result.raise_for_status()
        time.sleep(0.1)
        return result.json()

    def create_invoice_line(self, invoice_id: str, invoice_line_json: dict) -> dict:
        """Create an invoice line for a given invoice Id.

        Args:
            invoice_id: the alma id number of an invoice
            invoice_line_json: a python dict representing an invoice object as described
            here: https://developers.exlibrisgroup.com/alma/apis/docs/xsd/
            rest_invoice_line.xsd/

        """
        endpoint = f"acq/invoices/{invoice_id}/lines"
        result = requests.post(
            urljoin(self.base_url, endpoint),
            headers=self.headers,
            timeout=self.timeout,
            data=json.dumps(invoice_line_json),
        )
        result.raise_for_status()
        time.sleep(0.1)
        return result.json()

    def create_vendor(self, vendor_json: dict) -> dict:
        """Create a vendor record.

        Args:
            vendor_json: a python dict representing an invoice object as described
            here: https://developers.exlibrisgroup.com/alma/apis/docs/xsd/rest_vendor.xsd/

        """
        endpoint = "acq/vendors"
        result = requests.post(
            urljoin(self.base_url, endpoint),
            headers=self.headers,
            timeout=self.timeout,
            data=json.dumps(vendor_json),
        )
        result.raise_for_status()
        time.sleep(0.1)
        return result.json()

    def get_paged(
        self,
        endpoint: str,
        record_type: str,
        params: Optional[dict] = None,
        limit: int = 100,
        _offset: int = 0,
        _records_retrieved: int = 0,
    ) -> Generator[dict, None, None]:
        """Retrieve paginated results from the Alma API for a given endpoint.

        Args:
            endpoint: The paged Alma API endpoint to call, e.g. "acq/invoices".
            record_type: The type of record returned by the Alma API for the specified
                endpoint, e.g. "invoice" record_type returned by the "acq/invoices"
                endpoint. See <https://developers.exlibrisgroup.com/alma/apis/docs/xsd/
                rest_invoice.xsd/?tags=POST#invoice> for example.
            params: Any endpoint-specific params to supply to the GET request.
            limit: The maximum number of records to retrieve per page. Valid values are
                0-100.
            _offset: The offset value to supply to paged request. Should only be used
                internally by this method's recursion.
            _records_retrieved: The number of records retrieved so far for a given
                paged endpoint. Should only be used internally by this method's
                recursion.

        """
        params = params or {}
        params["limit"] = limit
        params["offset"] = _offset
        response = requests.get(
            url=urljoin(self.base_url, endpoint),
            params=params,
            headers=self.headers,
            timeout=self.timeout,
        )
        response.raise_for_status()
        time.sleep(0.1)
        total_record_count = response.json()["total_record_count"]
        records = response.json().get(record_type, [])
        records_retrieved = _records_retrieved + len(records)
        for record in records:
            yield record
        if records_retrieved < total_record_count:
            yield from self.get_paged(
                endpoint,
                record_type,
                params=params,
                limit=limit,
                _offset=_offset + limit,
                _records_retrieved=records_retrieved,
            )

    def get_fund_by_code(self, fund_code: str) -> dict:
        """Get fund details using the fund code."""
        endpoint = "acq/funds"
        params = {"q": f"fund_code~{fund_code}", "view": "full"}
        result = requests.get(
            urljoin(self.base_url, endpoint),
            headers=self.headers,
            params=params,
            timeout=self.timeout,
        )
        result.raise_for_status()
        time.sleep(0.1)
        return result.json()

    def get_invoices_by_status(self, status: str) -> Generator[dict, None, None]:
        """Get all invoices with a provided status."""
        invoice_params = {
            "invoice_workflow_status": status,
        }
        return self.get_paged("acq/invoices", "invoice", params=invoice_params)

    def get_vendor_details(self, vendor_code: str) -> dict:
        """Get vendor info from Alma."""
        endpoint = f"acq/vendors/{vendor_code}"
        result = requests.get(
            url=urljoin(self.base_url, endpoint),
            headers=self.headers,
            timeout=self.timeout,
        )
        result.raise_for_status()
        time.sleep(0.1)
        return result.json()

    def get_vendor_invoices(self, vendor_code: str) -> Generator[dict, None, None]:
        """Get invoices for a given vendor code."""
        endpoint = f"acq/vendors/{vendor_code}/invoices"
        return self.get_paged(endpoint, "invoice")

    def mark_invoice_paid(
        self,
        invoice_id: str,
        payment_date: datetime,
        payment_amount: str,
        payment_currency: str,
    ) -> dict:
        """Mark an invoice as paid using the invoice process endpoint."""
        endpoint = f"acq/invoices/{invoice_id}"
        params = {"op": "paid"}
        invoice_payment_data = {
            "payment": {
                "voucher_date": payment_date.strftime("%Y-%m-%dT12:00:00Z"),
                "voucher_amount": payment_amount,
                "voucher_currency": {"value": payment_currency},
            }
        }
        result = requests.post(
            url=urljoin(self.base_url, endpoint),
            headers=self.headers,
            params=params,
            timeout=self.timeout,
            data=json.dumps(invoice_payment_data),
        )
        result.raise_for_status()
        time.sleep(0.1)
        return result.json()

    def process_invoice(self, invoice_id: str) -> dict:
        """Move an invoice to in process using the invoice process endpoint."""
        endpoint = f"acq/invoices/{invoice_id}"
        params = {"op": "process_invoice"}
        result = requests.post(
            urljoin(self.base_url, endpoint),
            headers=self.headers,
            params=params,
            timeout=self.timeout,
            data="{}",
        )
        result.raise_for_status()
        time.sleep(0.1)
        return result.json()
