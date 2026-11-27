r"""Liest Dashboard-KPIs direkt aus DynamoDB via `AnalyticsService` (read-only).

Standard-Zeitraum ist Prod-Go-Live (2026-09-15) bis jetzt.
"""

import argparse
import csv
import io
import logging
import os
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(message)s")
logger = logging.getLogger(__name__)

_GOLIVE_DATE = "2026-09-15"
_BAR_WIDTH = 30
_NO_VALUE = "\u2013"


def _parse_date_to_ms(value: str, *, end_of_day: bool = False) -> int:
    """Convert YYYY-MM-DD to Unix ms (UTC)."""
    try:
        parsed = datetime.strptime(value, "%Y-%m-%d").replace(tzinfo=UTC)
    except ValueError:
        raise argparse.ArgumentTypeError(f"Ungueltiges Datum '{value}' - erwartet YYYY-MM-DD") from None
    if end_of_day:
        parsed = parsed + timedelta(days=1) - timedelta(milliseconds=1)
    return int(parsed.timestamp() * 1000)


def _ms_to_date_str(ms: int) -> str:
    """Format Unix ms as 'YYYY-MM-DD HH:MM' in UTC."""
    return datetime.fromtimestamp(ms / 1000, tz=UTC).strftime("%Y-%m-%d %H:%M")


def _percent(numerator: int, denominator: int) -> str:
    """Format a ratio as a rounded percentage, or a placeholder if undefined."""
    if denominator == 0:
        return _NO_VALUE
    return f"{round(numerator / denominator * 100)} %"


def _rate_percent(rate: float | None) -> str:
    """Format an optional 0..1 rate as a rounded percentage."""
    if rate is None:
        return _NO_VALUE
    return f"{round(rate * 100)} %"


def _bar(count: int, max_count: int) -> str:
    """Render a horizontal bar proportional to max_count."""
    if max_count <= 0:
        return ""
    filled = max(1, round(count / max_count * _BAR_WIDTH)) if count > 0 else 0
    return "\u2588" * filled


def _format_header(table: str, from_ts: int, to_ts: int) -> list[str]:
    """Build the report header lines."""
    return [
        "=" * 68,
        "RENATE - Dashboard-Kennzahlen",
        "=" * 68,
        f"Tabelle:   {table}",
        f"Zeitraum:  {_ms_to_date_str(from_ts)}  bis  {_ms_to_date_str(to_ts)} (UTC)",
        f"Erstellt:  {datetime.now(tz=UTC).strftime('%Y-%m-%d %H:%M')} UTC",
        "",
    ]


def _format_kpis(data) -> list[str]:
    """Build the usage, feedback and guardrail KPI lines."""
    total_feedback = data.feedback_good_count + data.feedback_neutral_count + data.feedback_bad_count
    good = _percent(data.feedback_good_count, total_feedback)
    neutral = _percent(data.feedback_neutral_count, total_feedback)
    bad = _percent(data.feedback_bad_count, total_feedback)

    return [
        "NUTZUNG",
        f"  Sitzungen                    {data.total_sessions:>8}",
        f"  Nachrichten                  {data.total_messages:>8}",
        f"  Nachrichten je Sitzung       {data.avg_messages_per_session:>8}",
        "",
        "FEEDBACK",
        f"  Ruecklaufquote               {_percent(total_feedback, data.total_messages):>8}",
        f"  Positiv                      {data.feedback_good_count:>8}   {good}",
        f"  Neutral                      {data.feedback_neutral_count:>8}   {neutral}",
        f"  Negativ                      {data.feedback_bad_count:>8}   {bad}",
        "",
        "GUARDRAIL",
        f"  Blockiert-Rate               {_rate_percent(data.blocked_rate):>8}",
        "",
    ]


def _format_ranking(title: str, rows: list[tuple[str, int]]) -> list[str]:
    """Build a ranked list section with proportional bars."""
    if not rows:
        return []
    max_count = max(count for _, count in rows)
    width = max(len(label) for label, _ in rows)
    lines = [title]
    lines.extend(f"  {label:<{width}} {count:>6}  {_bar(count, max_count)}" for label, count in rows)
    lines.append("")
    return lines


def _truncate(value: str, limit: int = 44) -> str:
    """Shorten a label to at most limit characters."""
    return value if len(value) <= limit else value[: limit - 3] + "..."


def _format_text(data, table: str, from_ts: int, to_ts: int) -> str:
    """Render the analytics response as a readable terminal report."""
    out: list[str] = []
    out.extend(_format_header(table, from_ts, to_ts))
    out.extend(_format_kpis(data))
    out.extend(_format_ranking("TOP-THEMENFELDER", [(d.domain, d.count) for d in data.top_domains]))
    out.extend(_format_ranking("TOP-THEMEN", [(f"{t.topic} ({t.domain})", t.count) for t in data.top_topics]))
    out.extend(_format_ranking("TOP-QUELLEN", [(_truncate(s.source_name), s.count) for s in data.top_sources]))

    if data.total_messages == 0:
        out.extend([
            "Hinweis: Keine Daten im gewaehlten Zeitraum. Pruefe Tabellenname und Zeitraum.",
            "Die Items werden ueber den GSI 'domain-created_at-index' gelesen; Items ohne",
            "'domain'-Feld erscheinen nicht (siehe AnalyticsService._query_by_domains).",
            "",
        ])

    return "\n".join(out)


def _format_csv(data) -> str:
    """Render the analytics response as a flat CSV (pivot-friendly in Excel)."""
    buffer = io.StringIO()
    writer = csv.writer(buffer, delimiter=";")
    writer.writerow(["Bereich", "Bezeichnung", "Wert"])

    total_feedback = data.feedback_good_count + data.feedback_neutral_count + data.feedback_bad_count

    writer.writerow(["Nutzung", "Sitzungen", data.total_sessions])
    writer.writerow(["Nutzung", "Nachrichten", data.total_messages])
    writer.writerow(["Nutzung", "Durchschnitt Nachrichten je Sitzung", data.avg_messages_per_session])
    writer.writerow(["Feedback", "Rueckmeldungen insgesamt", total_feedback])
    writer.writerow(["Feedback", "Positiv", data.feedback_good_count])
    writer.writerow(["Feedback", "Neutral", data.feedback_neutral_count])
    writer.writerow(["Feedback", "Negativ", data.feedback_bad_count])
    writer.writerow(["Guardrail", "Blockiert-Rate in Prozent", round(data.blocked_rate * 100)])

    for d in data.top_domains:
        writer.writerow(["Themenfeld", d.domain, d.count])
    for t in data.top_topics:
        writer.writerow([f"Thema ({t.domain})", t.topic, t.count])
    for s in data.top_sources:
        writer.writerow(["Quelle", s.source_name, s.count])

    return buffer.getvalue()


def _build_arg_parser() -> argparse.ArgumentParser:
    """Construct the command line argument parser."""
    parser = argparse.ArgumentParser(
        description="Liest die Dashboard-KPIs direkt aus DynamoDB (read-only).",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--table",
        default=os.getenv("DYNAMODB_TABLE_NAME"),
        help="DynamoDB-Tabelle, z.B. renate-conversations-prod. Alternativ per DYNAMODB_TABLE_NAME.",
    )
    parser.add_argument(
        "--region",
        default=os.getenv("REGION", "eu-central-1"),
        help="AWS-Region (Default eu-central-1)",
    )
    parser.add_argument("--from-date", help=f"Startdatum YYYY-MM-DD (Default Go-Live {_GOLIVE_DATE})")
    parser.add_argument("--to-date", help="Enddatum YYYY-MM-DD, inklusiv (Default: jetzt)")
    parser.add_argument("--days", type=int, help="Alternativ zu --from-date: Anzahl Tage zurueck")
    parser.add_argument(
        "--format",
        choices=["text", "csv", "json"],
        default="text",
        help="Ausgabeformat (Default text)",
    )
    parser.add_argument(
        "--output",
        help="Zieldatei; Datum und Uhrzeit werden automatisch angehaengt. Ohne Angabe Ausgabe auf stdout.",
    )
    return parser


def _timestamped_path(path: str, output_format: str) -> str:
    """Insert a local-time timestamp before the suffix so repeat runs don't overwrite."""
    default_suffixes = {"csv": ".csv", "json": ".json", "text": ".txt"}
    target = Path(path).expanduser()
    suffix = target.suffix or default_suffixes[output_format]
    stamp = datetime.now().strftime("%Y-%m-%d_%H%M")
    return str(target.with_name(f"{target.stem}-{stamp}{suffix}"))


def _preflight(table: str, region: str) -> str | None:
    """Surface credential/table errors explicitly — AnalyticsService swallows them as empty results."""
    import boto3

    try:
        boto3.client("dynamodb", region_name=region).describe_table(TableName=table)
    except Exception as e:
        return f"{type(e).__name__}: {e}"
    return None


def _resolve_window(args: argparse.Namespace) -> tuple[int, int]:
    """Return (from_ts, to_ts) in Unix ms. Start precedence: --from-date, --days, Go-Live."""
    if args.to_date:
        to_ts = _parse_date_to_ms(args.to_date, end_of_day=True)
    else:
        to_ts = int(datetime.now(tz=UTC).timestamp() * 1000)

    if args.from_date:
        from_ts = _parse_date_to_ms(args.from_date)
    elif args.days is not None:
        from_ts = to_ts - args.days * 86_400_000
    else:
        from_ts = _parse_date_to_ms(_GOLIVE_DATE)

    return from_ts, to_ts


def main() -> int:
    """Query analytics and emit the report."""
    args = _build_arg_parser().parse_args()

    if not args.table:
        print(
            "Fehler: Kein Tabellenname. Setze --table oder DYNAMODB_TABLE_NAME,\n"
            "z.B. --table renate-conversations-prod",
            file=sys.stderr,
        )
        return 2

    # AnalyticsService reads table/region from the environment at construction.
    os.environ["DYNAMODB_TABLE_NAME"] = args.table
    os.environ["REGION"] = args.region

    if error := _preflight(args.table, args.region):
        print(
            "Fehler: Zugriff auf die Tabelle nicht moeglich.\n"
            f"  Tabelle: {args.table}\n"
            f"  Region:  {args.region}\n"
            f"  Ursache: {error}\n\n"
            "Pruefe die AWS-Credentials (z.B. AWS_PROFILE) und ob der Tabellenname\n"
            "zur gewuenschten Umgebung passt (renate-conversations-dev|qa|prod).",
            file=sys.stderr,
        )
        return 3

    from backend_orchestrator.services.analytics_service import AnalyticsService

    from_ts, to_ts = _resolve_window(args)

    data = AnalyticsService().get_analytics(from_ts=from_ts, to_ts=to_ts)

    if args.format == "json":
        rendered = data.model_dump_json(by_alias=True, indent=2)
    elif args.format == "csv":
        rendered = _format_csv(data)
    else:
        rendered = _format_text(data, args.table, from_ts, to_ts)

    if args.output:
        target = _timestamped_path(args.output, args.format)
        with open(target, "w", encoding="utf-8", newline="") as f:
            f.write(rendered)
        print(f"Report geschrieben: {target} ({args.format}, Tabelle {args.table})", file=sys.stderr)
    else:
        print(rendered)

    return 0


if __name__ == "__main__":
    sys.exit(main())
