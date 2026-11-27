"""Budget pacing Lambda — daily cost control with automatic maintenance mode.

Distributes the fixed monthly budget across the remaining days. Each day gets
a fresh budget calculated from what is left. When today's spend exceeds today's
budget, the service goes into maintenance until midnight. The next morning check
re-evaluates with a new daily allocation.

Fail-safe by design: any error leaves the maintenance state untouched.

State model (SSM `/<env>/renate/maintenance-reason`):
    none    — no maintenance active, pacing may enable
    budget  — pacing enabled maintenance, pacing may disable (next day)
    manual  — operator enabled maintenance, pacing must not touch it

See RFC 0006.
"""

import calendar
import json
import logging
import os
from datetime import UTC, datetime, timedelta
from typing import Any

import boto3
from botocore.exceptions import ClientError

logger = logging.getLogger()
logger.setLevel(os.getenv("LOG_LEVEL", "INFO"))

# Cost Explorer is only available via us-east-1 regardless of deployment region
CE_REGION = "us-east-1"

# CostTypes must match cdk/lib/constructs/monitoring/budget-alerts.ts so the
# pacing Lambda and the AWS Budget alerts see identical numbers.
CE_METRIC = "UnblendedCost"

REASON_NONE = "none"
REASON_BUDGET = "budget"
REASON_MANUAL = "manual"

WARNING_THRESHOLD = 0.8


class PacingError(Exception):
    """Raised when a step fails in a way that must abort without state change."""


def calculate_daily_budget(
    monthly_budget: float,
    month_to_date_spend_yesterday: float,
    current_day: int,
    days_in_month: int,
) -> float:
    """Return today's allowed spend.

    daily_budget = remaining_budget / remaining_days
    where remaining_budget = monthly_budget - spend through yesterday.
    Remaining_days includes today.
    Clamped at 0 — an already-overspent month gets no further allowance.
    """
    remaining_budget = monthly_budget - month_to_date_spend_yesterday
    remaining_days = days_in_month - current_day + 1
    if remaining_days <= 0:
        return 0.0
    return max(0.0, remaining_budget / remaining_days)


def get_today_spend(today_mtd: float, yesterday_mtd: float) -> float:
    """Return today's spend as the delta between today's MTD and yesterday's MTD.

    Cost Explorer's MTD includes today's partial data, so the difference
    gives us today's contribution. Clamped at 0 — late-settling adjustments
    from prior days can make the delta negative.
    """
    return max(0.0, today_mtd - yesterday_mtd)


def get_cost_for_period(start: str, end: str) -> float:
    """Read unblended cost for the given period from Cost Explorer.

    Start/End are ISO date strings. End is exclusive.
    """
    client = boto3.client("ce", region_name=CE_REGION)
    try:
        response = client.get_cost_and_usage(
            TimePeriod={"Start": start, "End": end},
            Granularity="MONTHLY",
            Metrics=["UNBLENDED_COST"],
        )
    except ClientError as e:
        raise PacingError(f"Cost Explorer unavailable: {e}") from e

    results = response.get("ResultsByTime", [])
    if not results:
        raise PacingError("Cost Explorer returned no results")

    total = 0.0
    for period in results:
        amount = period.get("Total", {}).get(CE_METRIC, {}).get("Amount")
        if amount is None:
            raise PacingError(f"Cost Explorer response missing {CE_METRIC}")
        total += float(amount)
    return total


def get_month_costs() -> tuple[float, float]:
    """Return (MTD through yesterday, MTD through today).

    Two separate queries:
    - month_start → today (= yesterday's settled costs)
    - month_start → tomorrow (= includes today's partial)

    On day 1, yesterday's MTD is 0 (no prior days in this month).
    """
    now = datetime.now(UTC)
    month_start = now.replace(day=1).strftime("%Y-%m-%d")
    today = now.strftime("%Y-%m-%d")
    tomorrow = (now + timedelta(days=1)).strftime("%Y-%m-%d")

    # Day 1: no yesterday in this month → 0.0; otherwise query CE for settled data.
    yesterday_mtd = 0.0 if now.day == 1 else get_cost_for_period(month_start, today)

    today_mtd = get_cost_for_period(month_start, tomorrow)
    return yesterday_mtd, today_mtd


def get_maintenance_reason(param_name: str) -> str:
    """Read the maintenance reason from SSM, defaulting to none."""
    client = boto3.client("ssm")
    try:
        response = client.get_parameter(Name=param_name)
    except ClientError as e:
        if e.response.get("Error", {}).get("Code") == "ParameterNotFound":
            logger.warning("maintenance-reason parameter missing, treating as none")
            return REASON_NONE
        raise PacingError(f"Cannot read {param_name}: {e}") from e
    value = response["Parameter"]["Value"].strip().lower()
    if value not in (REASON_NONE, REASON_BUDGET, REASON_MANUAL):
        raise PacingError(f"Unrecognized maintenance-reason '{value}'")
    return value


def set_maintenance_reason(param_name: str, reason: str) -> None:
    """Write the maintenance reason to SSM."""
    client = boto3.client("ssm")
    try:
        client.put_parameter(Name=param_name, Value=reason, Overwrite=True, Type="String")
    except ClientError as e:
        raise PacingError(f"Cannot write {param_name}: {e}") from e


def set_kvs_flag(kvs_arn: str, value: str) -> None:
    """Write the CloudFront KVS maintenance flag (edge first, same as the script).

    CloudFront KVS requires SigV4a signing which needs the awscrt library.
    The library is provided by the Lambda layer (CDK builds it at deploy time).
    """
    client = boto3.client("cloudfront-keyvaluestore")
    try:
        etag = client.describe_key_value_store(KvsARN=kvs_arn)["ETag"]
        client.update_keys(
            KvsARN=kvs_arn,
            IfMatch=etag,
            Puts=[{"Key": "maintenance", "Value": value}],
        )
    except ClientError as e:
        raise PacingError(f"Cannot write KVS flag: {e}") from e


def set_chat_concurrency(function_name: str, *, throttled: bool) -> None:
    """Throttle or restore the ChatHandler (backend second, after the edge)."""
    client = boto3.client("lambda")
    try:
        if throttled:
            client.put_function_concurrency(FunctionName=function_name, ReservedConcurrentExecutions=0)
        else:
            client.delete_function_concurrency(FunctionName=function_name)
    except ClientError as e:
        raise PacingError(f"Cannot change ChatHandler concurrency: {e}") from e


def invalidate_cache(distribution_id: str) -> None:
    """Invalidate CloudFront edge cache so cached maintenance pages are evicted.

    CACHING_OPTIMIZED has a 24h default TTL — without invalidation the stale
    maintenance page persists at the edge even after the KVS flag flips to off.
    Non-fatal: a failed invalidation logs an error but does not prevent the
    service from recovering (new requests still hit the CloudFront Function).
    """
    if not distribution_id:
        logger.warning("DISTRIBUTION_ID not set — skipping cache invalidation")
        return
    client = boto3.client("cloudfront")
    try:
        client.create_invalidation(
            DistributionId=distribution_id,
            InvalidationBatch={
                "Paths": {"Quantity": 1, "Items": ["/*"]},
                "CallerReference": f"budget-pacing-{datetime.now(UTC).strftime('%Y%m%dT%H%M%S')}",
            },
        )
    except ClientError:
        logger.exception("CloudFront invalidation failed (non-fatal)")


def notify(topic_arn: str, subject: str, message: str) -> None:
    """Publish an SNS notification. Never raises — alerting must not break control flow."""
    if not topic_arn:
        return
    try:
        boto3.client("sns").publish(TopicArn=topic_arn, Subject=subject[:100], Message=message)
    except ClientError:
        logger.exception("SNS publish failed")


def enable_maintenance(kvs_arn: str, chat_handler: str, param_name: str) -> None:
    """Enable maintenance, edge first, then record the reason."""
    set_kvs_flag(kvs_arn, "on")
    set_chat_concurrency(chat_handler, throttled=True)
    set_maintenance_reason(param_name, REASON_BUDGET)


def disable_maintenance(kvs_arn: str, chat_handler: str, param_name: str, distribution_id: str = "") -> None:
    """Disable maintenance, edge first, invalidate cache, then clear the reason."""
    set_kvs_flag(kvs_arn, "off")
    invalidate_cache(distribution_id)
    set_chat_concurrency(chat_handler, throttled=False)
    set_maintenance_reason(param_name, REASON_NONE)


def lambda_handler(event: dict[str, Any], context: Any) -> dict[str, Any]:
    """Scheduled entry point. Reads costs, decides, toggles maintenance.

    RFC 0006 decision model:
    - Tagesbudget = remaining_monthly / remaining_days
    - Today's spend > Tagesbudget → Maintenance bis Mitternacht
    - Next day → Reset (new daily budget from what's left)
    """
    env_name = os.getenv("ENV_NAME", "unknown")
    monthly_budget = float(os.getenv("MONTHLY_BUDGET_USD", "7000"))
    kvs_arn = os.getenv("KVS_ARN", "")
    chat_handler = os.getenv("CHAT_HANDLER_NAME", "")
    topic_arn = os.getenv("SNS_TOPIC_ARN", "")
    distribution_id = os.getenv("DISTRIBUTION_ID", "")
    param_name = os.getenv("MAINTENANCE_REASON_PARAM", f"/{env_name}/renate/maintenance-reason")

    now = datetime.now(UTC)
    current_day = now.day
    days_in_month = calendar.monthrange(now.year, now.month)[1]

    try:
        yesterday_mtd, today_mtd = get_month_costs()
        reason = get_maintenance_reason(param_name)
    except PacingError as e:
        logger.exception("Aborting without state change")
        notify(topic_arn, f"[{env_name}] Budget pacing error", str(e))
        return _result("error", error=str(e))

    today_spend = get_today_spend(today_mtd, yesterday_mtd)
    daily_budget = calculate_daily_budget(monthly_budget, yesterday_mtd, current_day, days_in_month)
    over_today = today_spend > daily_budget

    logger.info(
        "Budget pacing evaluated: %s",
        json.dumps({
            "yesterday_mtd": round(yesterday_mtd, 2),
            "today_mtd": round(today_mtd, 2),
            "today_spend": round(today_spend, 2),
            "daily_budget": round(daily_budget, 2),
            "over_today": over_today,
            "reason": reason,
            "day": f"{current_day}/{days_in_month}",
        }),
    )

    figures = (
        f"Environment: {env_name}\n"
        f"Day: {current_day} of {days_in_month}\n"
        f"Yesterday MTD: ${yesterday_mtd:,.2f}\n"
        f"Today's spend: ${today_spend:,.2f}\n"
        f"Today's budget: ${daily_budget:,.2f}\n"
        f"Monthly budget: ${monthly_budget:,.2f}"
    )

    # Manual maintenance always wins — never touch it.
    if reason == REASON_MANUAL:
        logger.info("Manual maintenance active — pacing takes no action")
        return _result("noop_manual", today_spend=today_spend, daily_budget=daily_budget)

    try:
        # New day and currently in budget-triggered maintenance → reset.
        # The check at 06:00 UTC is effectively the "midnight reset":
        # yesterday's costs are settled, and today is a fresh allocation.
        # If today is also over-budget already (unlikely at 06:00), the
        # second branch below will re-enable immediately.
        if reason == REASON_BUDGET and not over_today:
            disable_maintenance(kvs_arn, chat_handler, param_name, distribution_id)
            notify(
                topic_arn,
                f"[{env_name}] Maintenance DISABLED — new day, budget available",
                f"Service restored. Today's budget: ${daily_budget:,.2f}\n\n{figures}",
            )
            return _result("disabled", today_spend=today_spend, daily_budget=daily_budget)

        # Today's spend exceeded today's budget → shut down.
        if over_today and reason == REASON_NONE:
            enable_maintenance(kvs_arn, chat_handler, param_name)
            notify(
                topic_arn,
                f"[{env_name}] Maintenance ENABLED — daily budget exceeded",
                f"Today's spend (${today_spend:,.2f}) exceeded today's "
                f"budget (${daily_budget:,.2f}). Service offline until next check.\n\n{figures}",
            )
            return _result("enabled", today_spend=today_spend, daily_budget=daily_budget)
    except PacingError as e:
        logger.exception("Toggle failed")
        notify(topic_arn, f"[{env_name}] Budget pacing toggle failed", f"{e}\n\n{figures}")
        return _result("error", error=str(e), today_spend=today_spend, daily_budget=daily_budget)

    # Warning: approaching today's budget but not yet over it.
    if today_spend > WARNING_THRESHOLD * daily_budget and reason == REASON_NONE:
        notify(
            topic_arn,
            f"[{env_name}] Budget warning: {WARNING_THRESHOLD:.0%} of today's budget used",
            f"Approaching today's daily budget — not yet triggered.\n\n{figures}",
        )
        return _result("warning", today_spend=today_spend, daily_budget=daily_budget)

    return _result("noop", today_spend=today_spend, daily_budget=daily_budget)


def _result(action: str, **extra: Any) -> dict[str, Any]:
    """Shape the handler return value for logs and step-function style callers."""
    body = {"action": action, **extra}
    return {"statusCode": 200, "body": json.dumps(body)}
