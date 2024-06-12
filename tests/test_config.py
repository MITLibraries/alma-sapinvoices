# ruff: noqa: PLR2004

import logging

import pytest

from sapinvoices.config import configure_logger, configure_sentry, load_config_values


def test_configure_logger_with_invalid_level_raises_error():
    logger = logging.getLogger(__name__)
    with pytest.raises(ValueError) as error:  # noqa: PT011
        configure_logger(logger, log_level_string="oops")
    assert "'oops' is not a valid Python logging level" in str(error)


def test_configure_logger_info_level_or_higher():
    logger = logging.getLogger(__name__)
    result = configure_logger(logger, log_level_string="info")
    assert logger.getEffectiveLevel() == 20
    assert result == "Logger 'tests.test_config' configured with level=INFO"


def test_configure_logger_debug_level_or_lower():
    logger = logging.getLogger(__name__)
    result = configure_logger(logger, log_level_string="DEBUG")
    assert logger.getEffectiveLevel() == 10
    assert result == "Logger 'tests.test_config' configured with level=DEBUG"


def test_configure_sentry_no_env_variable(monkeypatch):
    monkeypatch.delenv("SENTRY_DSN", raising=False)
    result = configure_sentry()
    assert result == "No Sentry DSN found, exceptions will not be sent to Sentry"


def test_configure_sentry_env_variable_is_none(monkeypatch):
    monkeypatch.setenv("SENTRY_DSN", "None")
    result = configure_sentry()
    assert result == "No Sentry DSN found, exceptions will not be sent to Sentry"


def test_configure_sentry_env_variable_is_dsn(monkeypatch):
    monkeypatch.setenv("SENTRY_DSN", "https://1234567890@00000.ingest.sentry.io/123456")
    result = configure_sentry()
    assert result == "Sentry DSN found, exceptions will be sent to Sentry with env=test"


def test_load_config_values_from_env():
    assert load_config_values() == {
        "ALMA_API_URL": "https://example.com",
        "ALMA_API_READ_WRITE_KEY": "just-for-testing",
        "SAP_DROPBOX_CLOUDCONNECTOR_JSON": '{"test": "test"}',
        "SAP_REPLY_TO_EMAIL": "replyto@example.com",
        "SAP_FINAL_RECIPIENT_EMAIL": "final@example.com",
        "SAP_REVIEW_RECIPIENT_EMAIL": "review@example.com",
        "SES_SEND_FROM_EMAIL": "from@example.com",
        "SAP_SEQUENCE_NUM": "/test/example/sap_sequence",
        "TIMEOUT": "10",
        "WORKSPACE": "test",
    }


def test_load_config_values_from_defaults(monkeypatch):
    monkeypatch.delenv("ALMA_API_TIMEOUT", raising=False)
    assert load_config_values() == {
        "ALMA_API_URL": "https://example.com",
        "ALMA_API_READ_WRITE_KEY": "just-for-testing",
        "SAP_DROPBOX_CLOUDCONNECTOR_JSON": '{"test": "test"}',
        "SAP_REPLY_TO_EMAIL": "replyto@example.com",
        "SAP_FINAL_RECIPIENT_EMAIL": "final@example.com",
        "SAP_REVIEW_RECIPIENT_EMAIL": "review@example.com",
        "SES_SEND_FROM_EMAIL": "from@example.com",
        "SAP_SEQUENCE_NUM": "/test/example/sap_sequence",
        "TIMEOUT": "30",
        "WORKSPACE": "test",
    }


def test_load_config_values_missing_config_raises_error(monkeypatch):
    monkeypatch.delenv("ALMA_API_URL", raising=False)
    with pytest.raises(KeyError):
        load_config_values()
