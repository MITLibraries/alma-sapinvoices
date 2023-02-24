import logging

import pytest

from sapinvoices.config import configure_logger, configure_sentry, load_config_values


def test_configure_logger_with_invalid_level_raises_error():
    logger = logging.getLogger(__name__)
    with pytest.raises(ValueError) as error:
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
        "SAP_DROPBOX_CLOUDCONNECTOR_JSON": "test",
        "SAP_REPLY_TO_EMAIL": "test",
        "SAP_FINAL_RECIPIENT_EMAIL": "test",
        "SAP_REVIEW_RECIPIENT_EMAIL": "test",
        "SES_SEND_FROM_EMAIL": "test",
        "SSM_PATH": "test",
        "TIMEOUT": "10",
        "WORKSPACE": "test",
    }


def test_load_config_values_from_defaults(monkeypatch):
    monkeypatch.delenv("ALMA_API_TIMEOUT", raising=False)
    assert load_config_values() == {
        "ALMA_API_URL": "https://example.com",
        "ALMA_API_READ_WRITE_KEY": "just-for-testing",
        "SAP_DROPBOX_CLOUDCONNECTOR_JSON": "test",
        "SAP_REPLY_TO_EMAIL": "test",
        "SAP_FINAL_RECIPIENT_EMAIL": "test",
        "SAP_REVIEW_RECIPIENT_EMAIL": "test",
        "SES_SEND_FROM_EMAIL": "test",
        "SSM_PATH": "test",
        "TIMEOUT": "30",
        "WORKSPACE": "test",
    }


def test_load_config_values_missing_config_raises_error(monkeypatch):
    with pytest.raises(KeyError):
        monkeypatch.delenv("ALMA_API_URL", raising=False)
        load_config_values()


def test_load_config_ssm_safety_check_raises_error(monkeypatch):
    monkeypatch.setenv("WORKSPACE", "whatever")
    monkeypatch.setenv("SSM_PATH", "/test/example/prod")
    with pytest.raises(RuntimeError) as error:
        load_config_values()
    assert str(error.value) == (
        "Production SSM_PATH may ONLY be used in the production environment. "
        "Check your env variables and try again."
    )


def test_load_config_ssm_safety_check_does_not_raise_error_in_prod(monkeypatch):
    monkeypatch.setenv("WORKSPACE", "prod")
    monkeypatch.setenv("SSM_PATH", "/test/example/prod")

    assert load_config_values() == {
        "ALMA_API_URL": "https://example.com",
        "ALMA_API_READ_WRITE_KEY": "just-for-testing",
        "SAP_DROPBOX_CLOUDCONNECTOR_JSON": "test",
        "SAP_REPLY_TO_EMAIL": "test",
        "SAP_FINAL_RECIPIENT_EMAIL": "test",
        "SAP_REVIEW_RECIPIENT_EMAIL": "test",
        "SES_SEND_FROM_EMAIL": "test",
        "SSM_PATH": "/test/example/prod",
        "WORKSPACE": "prod",
        "TIMEOUT": "10",
    }


def test_load_config_ssm_safety_check_does_not_raise_error_with_not_prod_path(
    monkeypatch,
):
    monkeypatch.setenv("WORKSPACE", "prod")
    monkeypatch.setenv("SSM_PATH", "/test/example/dev")

    assert load_config_values() == {
        "ALMA_API_URL": "https://example.com",
        "ALMA_API_READ_WRITE_KEY": "just-for-testing",
        "SAP_DROPBOX_CLOUDCONNECTOR_JSON": "test",
        "SAP_REPLY_TO_EMAIL": "test",
        "SAP_FINAL_RECIPIENT_EMAIL": "test",
        "SAP_REVIEW_RECIPIENT_EMAIL": "test",
        "SES_SEND_FROM_EMAIL": "test",
        "SSM_PATH": "/test/example/dev",
        "WORKSPACE": "prod",
        "TIMEOUT": "10",
    }
