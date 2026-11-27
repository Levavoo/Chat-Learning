"""Tests for the budget pacing Lambda handler (#579, RFC 0006).

Decision model:
- Tagesbudget = remaining_monthly / remaining_days
- Today's spend > Tagesbudget → Maintenance bis Mitternacht
- Next day → Reset (new daily budget from what's left)
"""

import json
from datetime import UTC, datetime
from unittest.mock import MagicMock, patch

import pytest
from botocore.exceptions import ClientError

from budget_pacing.handler import (
    REASON_BUDGET,
    REASON_MANUAL,
    REASON_NONE,
    calculate_daily_budget,
    get_today_spend,
    lambda_handler,
)

CONTEXT = MagicMock()


def _patch_now(day: int, month: int = 6, year: int = 2026):
    frozen = datetime(year, month, day, 6, 0, 0, tzinfo=UTC)

    class _FakeDatetime(datetime):
        @classmethod
        def now(cls, tz=None):
            return frozen

    return patch("budget_pacing.handler.datetime", _FakeDatetime)


@pytest.fixture()
def _env(monkeypatch):
    monkeypatch.setenv("ENV_NAME", "dev")
    monkeypatch.setenv("MONTHLY_BUDGET_USD", "7000")
    monkeypatch.setenv("KVS_ARN", "arn:aws:cloudfront::123456789012:key-value-store/abc")
    monkeypatch.setenv("CHAT_HANDLER_NAME", "renate-chat-dev")
    monkeypatch.setenv("SNS_TOPIC_ARN", "arn:aws:sns:eu-central-1:123456789012:renate-alerts-dev")
    monkeypatch.setenv("MAINTENANCE_REASON_PARAM", "/dev/renate/maintenance-reason")
    monkeypatch.setenv("DISTRIBUTION_ID", "EDFDVBD6EXAMPLE")


def _body(response):
    return json.loads(response["body"])


# ── Formula tests ─────────────────────────────────────────────────────────────


class TestCalculateDailyBudget:
    def test_day_1_full_budget(self):
        assert calculate_daily_budget(7000, 0, 1, 31) == pytest.approx(7000 / 31)

    def test_mid_month_partial_spend(self):
        # Day 15 of 30, 2100 spent through yesterday → (7000-2100) / 16 = 306.25
        assert calculate_daily_budget(7000, 2100, 15, 30) == pytest.approx(306.25)

    def test_last_day_gets_all_remaining(self):
        assert calculate_daily_budget(7000, 6000, 30, 30) == pytest.approx(1000)

    def test_overspent_month_gets_zero(self):
        assert calculate_daily_budget(7000, 8000, 15, 30) == 0.0


class TestGetTodaySpend:
    def test_normal_delta(self):
        assert get_today_spend(today_mtd=2300, yesterday_mtd=2100) == 200

    def test_negative_delta_clamped_to_zero(self):
        assert get_today_spend(today_mtd=2050, yesterday_mtd=2100) == 0.0

    def test_first_day_of_month(self):
        assert get_today_spend(today_mtd=45, yesterday_mtd=0) == 45


# ── Handler: enables maintenance when today's budget is exceeded ──────────────


@pytest.mark.usefixtures("_env")
class TestHandlerEnablesMaintenance:
    @patch("budget_pacing.handler.boto3.client")
    def test_enables_when_today_spend_exceeds_daily_budget(self, mock_client):
        # daily_budget = (7000-2100)/16 = 306.25; today_spend = 400 > 306.25
        clients = _mock_clients(yesterday_mtd=2100, today_mtd=2500)
        clients.ssm.get_parameter.return_value = {"Parameter": {"Value": REASON_NONE}}
        mock_client.side_effect = clients.factory

        with _patch_now(day=15, month=6):
            response = lambda_handler({}, CONTEXT)

        assert _body(response)["action"] == "enabled"
        clients.kvs.update_keys.assert_called_once()
        clients.awslambda.put_function_concurrency.assert_called_once()
        clients.sns.publish.assert_called_once()


# ── Handler: resets on new day ────────────────────────────────────────────────


@pytest.mark.usefixtures("_env")
class TestHandlerNextDayReset:
    @patch("budget_pacing.handler.boto3.client")
    def test_disables_on_new_day_when_today_under_budget(self, mock_client):
        # daily_budget = (7000-4500)/15 = 166.67; today_spend=0 < 166.67 → disable
        clients = _mock_clients(yesterday_mtd=4500, today_mtd=4500)
        clients.ssm.get_parameter.return_value = {"Parameter": {"Value": REASON_BUDGET}}
        mock_client.side_effect = clients.factory

        with _patch_now(day=16, month=6):
            response = lambda_handler({}, CONTEXT)

        assert _body(response)["action"] == "disabled"
        clients.awslambda.delete_function_concurrency.assert_called_once()
        clients.cloudfront.create_invalidation.assert_called_once()

    @patch("budget_pacing.handler.boto3.client")
    def test_stays_in_maintenance_if_still_over_on_same_day(self, mock_client):
        # today_spend=400 > daily_budget=306.25 → stays put
        clients = _mock_clients(yesterday_mtd=2100, today_mtd=2500)
        clients.ssm.get_parameter.return_value = {"Parameter": {"Value": REASON_BUDGET}}
        mock_client.side_effect = clients.factory

        with _patch_now(day=15, month=6):
            response = lambda_handler({}, CONTEXT)

        assert _body(response)["action"] == "noop"
        clients.kvs.update_keys.assert_not_called()

    @patch("budget_pacing.handler.boto3.client")
    def test_new_month_clears_budget_maintenance(self, mock_client):
        clients = _mock_clients_day1(today_mtd=0)
        clients.ssm.get_parameter.return_value = {"Parameter": {"Value": REASON_BUDGET}}
        mock_client.side_effect = clients.factory

        with _patch_now(day=1, month=7):
            response = lambda_handler({}, CONTEXT)

        assert _body(response)["action"] == "disabled"


# ── Handler: respects manual maintenance ──────────────────────────────────────


@pytest.mark.usefixtures("_env")
class TestHandlerRespectsManual:
    @patch("budget_pacing.handler.boto3.client")
    def test_over_budget_but_manual_is_noop(self, mock_client):
        clients = _mock_clients(yesterday_mtd=2100, today_mtd=2500)
        clients.ssm.get_parameter.return_value = {"Parameter": {"Value": REASON_MANUAL}}
        mock_client.side_effect = clients.factory

        with _patch_now(day=15, month=6):
            response = lambda_handler({}, CONTEXT)

        assert _body(response)["action"] == "noop_manual"
        clients.kvs.update_keys.assert_not_called()


# ── Handler: no action when under budget ──────────────────────────────────────


@pytest.mark.usefixtures("_env")
class TestHandlerNoAction:
    @patch("budget_pacing.handler.boto3.client")
    def test_under_budget_is_noop(self, mock_client):
        # today_spend = 5; daily_budget = (7000-100)/16 = 431 → under
        clients = _mock_clients(yesterday_mtd=100, today_mtd=105)
        clients.ssm.get_parameter.return_value = {"Parameter": {"Value": REASON_NONE}}
        mock_client.side_effect = clients.factory

        with _patch_now(day=15, month=6):
            response = lambda_handler({}, CONTEXT)

        assert _body(response)["action"] == "noop"
        clients.kvs.update_keys.assert_not_called()


# ── Handler: fail-safe ────────────────────────────────────────────────────────


@pytest.mark.usefixtures("_env")
class TestHandlerFailSafe:
    @patch("budget_pacing.handler.boto3.client")
    def test_cost_explorer_error_makes_no_change(self, mock_client):
        clients = _mock_clients(yesterday_mtd=100, today_mtd=105)
        clients.ce.get_cost_and_usage.side_effect = ClientError(
            {"Error": {"Code": "ThrottlingException", "Message": "slow down"}},
            "GetCostAndUsage",
        )
        mock_client.side_effect = clients.factory

        with _patch_now(day=15, month=6):
            response = lambda_handler({}, CONTEXT)

        assert _body(response)["action"] == "error"
        clients.kvs.update_keys.assert_not_called()
        clients.sns.publish.assert_called_once()

    @patch("budget_pacing.handler.boto3.client")
    def test_missing_ssm_parameter_treated_as_none(self, mock_client):
        # Missing SSM = "none" → today_spend=400 > budget=306.25 → enable
        clients = _mock_clients(yesterday_mtd=2100, today_mtd=2500)
        clients.ssm.get_parameter.side_effect = ClientError(
            {"Error": {"Code": "ParameterNotFound", "Message": "not found"}},
            "GetParameter",
        )
        mock_client.side_effect = clients.factory

        with _patch_now(day=15, month=6):
            response = lambda_handler({}, CONTEXT)

        assert _body(response)["action"] == "enabled"

    @patch("budget_pacing.handler.boto3.client")
    def test_kvs_write_failure_aborts_before_backend(self, mock_client):
        clients = _mock_clients(yesterday_mtd=2100, today_mtd=2500)
        clients.ssm.get_parameter.return_value = {"Parameter": {"Value": REASON_NONE}}
        clients.kvs.update_keys.side_effect = ClientError(
            {"Error": {"Code": "AccessDeniedException", "Message": "denied"}},
            "UpdateKeys",
        )
        mock_client.side_effect = clients.factory

        with _patch_now(day=15, month=6):
            response = lambda_handler({}, CONTEXT)

        assert _body(response)["action"] == "error"
        clients.awslambda.put_function_concurrency.assert_not_called()


# ── Test mock infrastructure ──────────────────────────────────────────────────


class _Clients:
    """Bundle of mocked boto3 clients."""

    def __init__(self):
        self.ce = MagicMock()
        self.ssm = MagicMock()
        self.kvs = MagicMock()
        self.kvs.describe_key_value_store.return_value = {"ETag": "etag-1"}
        self.cloudfront = MagicMock()
        self.awslambda = MagicMock()
        self.sns = MagicMock()

    def factory(self, service, **_kwargs):
        return {
            "ce": self.ce,
            "ssm": self.ssm,
            "cloudfront-keyvaluestore": self.kvs,
            "cloudfront": self.cloudfront,
            "lambda": self.awslambda,
            "sns": self.sns,
        }.get(service, MagicMock())


def _mock_clients(yesterday_mtd: float, today_mtd: float) -> _Clients:
    """Mock CE to return two calls: yesterday_mtd, then today_mtd."""
    c = _Clients()
    c.ce.get_cost_and_usage.side_effect = [
        {"ResultsByTime": [{"Total": {"UnblendedCost": {"Amount": str(yesterday_mtd)}}}]},
        {"ResultsByTime": [{"Total": {"UnblendedCost": {"Amount": str(today_mtd)}}}]},
    ]
    return c


def _mock_clients_day1(today_mtd: float) -> _Clients:
    """Mock CE for day 1 (only one CE call — yesterday_mtd is hardcoded to 0)."""
    c = _Clients()
    c.ce.get_cost_and_usage.return_value = {"ResultsByTime": [{"Total": {"UnblendedCost": {"Amount": str(today_mtd)}}}]}
    return c
