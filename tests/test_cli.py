import json

import pytest

from sapinvoices.cli import main


@pytest.mark.usefixtures("mocked_alma_sample_data")
def test_create_sandbox_data(caplog, runner):
    result = runner.invoke(main, ["create-sandbox-data"])
    assert result.exit_code == 0
    assert (
        "4 sample invoices created and ready for manual approval in the Alma sandbox UI"
    ) in caplog.text


@pytest.mark.usefixtures("mocked_alma_sample_data")
def test_create_sandbox_data_not_in_prod(monkeypatch, caplog, runner):
    monkeypatch.setenv("WORKSPACE", "prod")
    result = runner.invoke(main, ["create-sandbox-data"])
    assert result.exit_code == 1
    assert (
        "This command may not be run in the production environment, aborting"
    ) in caplog.text


def test_sap_invoices_review_run(caplog, runner):
    result = runner.invoke(main, ["process-invoices"])

    assert "Logger 'root' configured with level=INFO" in caplog.text
    assert "alma-sapinvoices config settings loaded for environment: test" in caplog.text
    assert "Starting SAP invoices process with options" in caplog.text
    assert "Final run: False" in caplog.text
    assert "Real run: False" in caplog.text
    assert result.exit_code == 0


def test_sap_invoices_review_run_no_invoices(caplog, runner, mocked_alma_no_invoices):
    result = runner.invoke(main, ["process-invoices"])
    assert result.exit_code == 1
    assert "Real run: False" in caplog.text
    assert (
        "No invoices waiting to be sent in Alma, aborting SAP invoice process"
    ) in caplog.text


def test_sap_invoices_review_run_real_run(caplog, runner):
    result = runner.invoke(main, ["process-invoices", "--real-run"])
    assert result.exit_code == 0
    assert "Logger 'root' configured with level=INFO" in caplog.text
    assert "alma-sapinvoices config settings loaded for environment: test" in caplog.text
    assert "Starting SAP invoices process with options" in caplog.text
    assert "Final run: False" in caplog.text
    assert "Real run: True" in caplog.text


def test_sap_invoices_final_run(caplog, runner):
    result = runner.invoke(main, ["process-invoices", "--final-run"])
    assert result.exit_code == 0
    assert "Logger 'root' configured with level=INFO" in caplog.text
    assert "alma-sapinvoices config settings loaded for environment: test" in caplog.text
    assert "Starting SAP invoices process with options" in caplog.text
    assert "Final run: True" in caplog.text
    assert "Real run: False" in caplog.text


def test_sap_invoices_final_run_real_run(
    caplog,
    monkeypatch,
    runner,
    mocked_sftp,
    test_sftp_private_key,
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
    result = runner.invoke(main, ["process-invoices", "--final-run", "--real-run"])
    assert result.exit_code == 0
    assert "Logger 'root' configured with level=INFO" in caplog.text
    assert "alma-sapinvoices config settings loaded for environment: test" in caplog.text
    assert "Starting SAP invoices process with options" in caplog.text
    assert "Final run: True" in caplog.text
    assert "Real run: True" in caplog.text
    assert "Something went wrong marking invoice '02' paid in Alma." in caplog.text
    assert "SAP invoice process completed for a final run" in caplog.text
    assert "2 monograph invoices retrieved and processed:" in caplog.text
