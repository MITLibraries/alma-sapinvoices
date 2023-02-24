import logging
import os

import sentry_sdk

EXPECTED_ENVIRONMENT_VARIABLES = [
    "ALMA_API_URL",
    "ALMA_API_READ_WRITE_KEY",
    "SAP_DROPBOX_CONNECTION",
    "SAP_REPLY_TO_EMAIL",
    "SAP_FINAL_RECIPIENT_EMAIL",
    "SAP_REVIEW_RECIPIENT_EMAIL",
    "SES_SEND_FROM_EMAIL",
    "SSM_PATH",
    "WORKSPACE",
]


def configure_logger(logger: logging.Logger, log_level_string: str) -> str:
    if log_level_string.upper() not in logging.getLevelNamesMapping():
        raise ValueError(f"'{log_level_string}' is not a valid Python logging level")
    log_level = logging.getLevelName(log_level_string.upper())
    if log_level < 20:
        logging.basicConfig(
            format="%(asctime)s %(levelname)s %(name)s.%(funcName)s() line %(lineno)d: "
            "%(message)s"
        )
        logger.setLevel(log_level)
        for handler in logging.root.handlers:
            handler.addFilter(logging.Filter("sapinvoices"))
    else:
        logging.basicConfig(
            format="%(asctime)s %(levelname)s %(name)s.%(funcName)s(): %(message)s"
        )
        logger.setLevel(log_level)
    return (
        f"Logger '{logger.name}' configured with level="
        f"{logging.getLevelName(logger.getEffectiveLevel())}"
    )


def configure_sentry() -> str:
    env = os.getenv("WORKSPACE")
    sentry_dsn = os.getenv("SENTRY_DSN")
    if sentry_dsn and sentry_dsn.lower() != "none":
        sentry_sdk.init(sentry_dsn, environment=env)
        return f"Sentry DSN found, exceptions will be sent to Sentry with env={env}"
    return "No Sentry DSN found, exceptions will not be sent to Sentry"


def load_config_values() -> dict:
    settings = {
        variable: os.environ[variable] for variable in EXPECTED_ENVIRONMENT_VARIABLES
    }
    if "prod" in settings["SSM_PATH"] and settings["WORKSPACE"] != "prod":
        raise RuntimeError(
            "Production SSM_PATH may ONLY be used in the production "
            "environment. Check your env variables and try again."
        )
    return settings
