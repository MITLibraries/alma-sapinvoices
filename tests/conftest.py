import os

import pytest
from click.testing import CliRunner

from sapinvoices.alma import AlmaClient


@pytest.fixture(autouse=True)
def test_env():
    os.environ = {
        "ALMA_API_URL": "https://example.com",
        "ALMA_API_READ_WRITE_KEY": "just-for-testing",
        "ALMA_API_TIMEOUT": "10",
        "LOG_LEVEL": "DEBUG",
        "SAP_DROPBOX_CLOUDCONNECTOR_JSON": "test",
        "SAP_REPLY_TO_EMAIL": "test",
        "SAP_FINAL_RECIPIENT_EMAIL": "test",
        "SAP_REVIEW_RECIPIENT_EMAIL": "test",
        "SENTRY_DSN": None,
        "SES_SEND_FROM_EMAIL": "test",
        "SSM_PATH": "test",
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
