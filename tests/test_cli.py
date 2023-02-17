import pytest

from sapinvoices.cli import sap


def test_create_sandbox_sap_data_(runner):
    result = runner.invoke(sap, ["create-sandbox-data"])
    assert result.exit_code == 0


def test_sap_invoices_review_run(runner):
    result = runner.invoke(sap, ["process-invoices"])
    assert result.exit_code == 0


@pytest.mark.xfail
def test_sap_invoices_review_run_no_invoices(runner):
    result = runner.invoke(sap, ["process-invoices"])
    assert result.exit_code == 1


def test_sap_invoices_review_run_real_run(runner):
    result = runner.invoke(sap, ["process-invoices", "--real-run"])
    assert result.exit_code == 0


def test_sap_invoices_final_run(runner):
    result = runner.invoke(sap, ["process-invoices", "--final-run"])
    assert result.exit_code == 0


def test_sap_invoices_final_run_real_run(runner):
    result = runner.invoke(sap, ["process-invoices", "--final-run", "--real-run"])
    assert result.exit_code == 0
