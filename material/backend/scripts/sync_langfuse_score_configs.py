"""Idempotent sync of Langfuse Score Configs from ``FEEDBACK_SCORE_SCHEMA``.

Derives target configs from ``MessageFeedback`` Literals (``str | None`` fields
are skipped and logged). Diffs by name against GET: noop / update / unarchive /
unarchive+update / conflict (Langfuse rejects a ``dataType`` re-type).

Exit codes: 0 ok, 1 HTTP error, 2 dataType conflict, 3 missing LANGFUSE_* env.
"""

from __future__ import annotations

import argparse
import base64
import dataclasses
import json
import logging
import os
import sys
import typing
import urllib.error
import urllib.request
from types import UnionType
from typing import Any, Union, get_args, get_origin, get_type_hints

from backend_orchestrator.models.api_models import FEEDBACK_SCORE_SCHEMA, MessageFeedback

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("sync_langfuse_score_configs")

# `str | None` fields with no Literal pin (pending #939) — skipped so we never
# register a Score Config with empty categories.
_DEFERRED_FIELDS: frozenset[str] = frozenset({"utility_value", "further_development"})

# `used_scenario` is a Literal[int] but the wire payload is `str(raw)` — register
# the label in the string shape Langfuse actually sees.
_LABEL_COERCIONS: dict[str, typing.Callable[[Any], str]] = {
    "used_scenario": str,
}


@dataclasses.dataclass(frozen=True)
class _ConfigTarget:
    name: str
    data_type: str
    categories: tuple[tuple[str, int], ...]  # (label, value) pairs, numbering 1..N


@dataclasses.dataclass(frozen=True)
class _ExistingConfig:
    config_id: str
    name: str
    data_type: str
    categories: tuple[tuple[str, float], ...]
    is_archived: bool


def _literal_args_for_field(field: str) -> tuple[Any, ...] | None:
    """Return the ``typing.Literal`` args on ``MessageFeedback.<field>``, or None."""
    hints = get_type_hints(MessageFeedback)
    annotation = hints.get(field)
    if annotation is None:
        return None
    origin = get_origin(annotation)
    # `A | None` -> types.UnionType; Optional[A] -> typing.Union.
    if origin in (Union, UnionType):
        candidates = [a for a in get_args(annotation) if a is not type(None)]
    else:
        candidates = [annotation]
    for candidate in candidates:
        if get_origin(candidate) is typing.Literal:
            return get_args(candidate)
    return None


def _build_categories(
    literal_args: tuple[Any, ...],
    coerce: typing.Callable[[Any], str],
) -> tuple[tuple[str, int], ...]:
    """Derive (label, value) pairs from a Literal.

    Int Literals use the arg itself as the Langfuse value so bounded code-level
    sets (``_UsedScenario``) stay stable when a member is appended; string
    Literals fall back to ``idx + 1`` since no natural numeric value exists.
    """
    return tuple(
        (coerce(arg), arg if isinstance(arg, int) and not isinstance(arg, bool) else idx + 1)
        for idx, arg in enumerate(literal_args)
    )


def build_targets() -> list[_ConfigTarget]:
    """Build the target Score Config set from ``FEEDBACK_SCORE_SCHEMA`` + Literals."""
    targets: list[_ConfigTarget] = []
    deferred: list[str] = []
    for field, (score_name, data_type) in FEEDBACK_SCORE_SCHEMA.items():
        if field in _DEFERRED_FIELDS:
            deferred.append(field)
            continue
        literal_args = _literal_args_for_field(field)
        if literal_args is None:
            logger.warning(
                "%s: no Literal on MessageFeedback — skipping (tighten the alias or add to _DEFERRED_FIELDS)",
                field,
            )
            continue
        coerce = _LABEL_COERCIONS.get(field, str)
        categories = _build_categories(literal_args, coerce)
        _assert_label_hygiene(score_name, categories)
        targets.append(_ConfigTarget(name=score_name, data_type=data_type, categories=categories))
    if deferred:
        logger.info("Deferred fields (not registered — see #939): %s", deferred)
    return targets


def _assert_label_hygiene(score_name: str, categories: tuple[tuple[str, int], ...]) -> None:
    """Whitespace drift silently falls back to unmanaged on ingestion."""
    for label, _ in categories:
        if label != label.strip():
            raise RuntimeError(
                f"{score_name}: category label {label!r} has leading/trailing whitespace. "
                "Fix the Literal alias in api_models.py — Langfuse joins score ingest to config "
                "by exact label, whitespace included.",
            )


def build_auth_header() -> str:
    """Build Basic auth; RuntimeError on missing keys (mapped to exit code 3 by run())."""
    public_key = os.environ.get("LANGFUSE_PUBLIC_KEY")
    secret_key = os.environ.get("LANGFUSE_SECRET_KEY")
    if not public_key or not secret_key:
        raise RuntimeError("LANGFUSE_PUBLIC_KEY + LANGFUSE_SECRET_KEY env vars are required")
    auth = base64.b64encode(f"{public_key}:{secret_key}".encode()).decode()
    return f"Basic {auth}"


def _request(method: str, host: str, path: str, auth: str, body: dict | None = None) -> dict:
    data = json.dumps(body).encode() if body is not None else None
    headers = {"Authorization": auth}
    if data is not None:
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(f"{host}{path}", data=data, headers=headers, method=method)  # noqa: S310
    with urllib.request.urlopen(req, timeout=15) as resp:  # noqa: S310
        payload = resp.read()
    return json.loads(payload) if payload else {}


def fetch_existing_configs(host: str, auth: str) -> dict[str, _ExistingConfig]:
    """Paginate ``GET /api/public/score-configs``, keyed by name."""
    existing: dict[str, _ExistingConfig] = {}
    page = 1
    limit = 100
    while True:
        resp = _request("GET", host, f"/api/public/score-configs?page={page}&limit={limit}", auth)
        data = resp.get("data", [])
        for item in data:
            cats = tuple(
                (c["label"], float(c["value"])) for c in (item.get("categories") or [])
            )
            existing[item["name"]] = _ExistingConfig(
                config_id=item["id"],
                name=item["name"],
                data_type=item["dataType"],
                categories=cats,
                is_archived=bool(item.get("isArchived", False)),
            )
        if len(data) < limit:
            break
        page += 1
    return existing


@dataclasses.dataclass(frozen=True)
class _Action:
    kind: str  # 'create' | 'update' | 'unarchive' | 'unarchive+update' | 'conflict' | 'noop'
    target: _ConfigTarget
    existing: _ExistingConfig | None


def plan(targets: list[_ConfigTarget], existing: dict[str, _ExistingConfig]) -> list[_Action]:
    actions: list[_Action] = []
    for target in targets:
        existing_cfg = existing.get(target.name)
        if existing_cfg is None:
            actions.append(_Action(kind="create", target=target, existing=None))
            continue
        if existing_cfg.data_type != target.data_type:
            actions.append(_Action(kind="conflict", target=target, existing=existing_cfg))
            continue
        target_cats = [(label, float(value)) for label, value in target.categories]
        categories_match = list(existing_cfg.categories) == target_cats
        if existing_cfg.is_archived and categories_match:
            actions.append(_Action(kind="unarchive", target=target, existing=existing_cfg))
        elif existing_cfg.is_archived:
            actions.append(_Action(kind="unarchive+update", target=target, existing=existing_cfg))
        elif categories_match:
            actions.append(_Action(kind="noop", target=target, existing=existing_cfg))
        else:
            actions.append(_Action(kind="update", target=target, existing=existing_cfg))
    return actions


def _create_body(target: _ConfigTarget) -> dict:
    return {
        "name": target.name,
        "dataType": target.data_type,
        "categories": [{"label": label, "value": value} for label, value in target.categories],
    }


def _patch_body(action: _Action) -> dict:
    body: dict = {}
    if action.kind in ("unarchive", "unarchive+update"):
        body["isArchived"] = False
    if action.kind in ("update", "unarchive+update"):
        body["categories"] = [
            {"label": label, "value": value} for label, value in action.target.categories
        ]
    return body


def apply(host: str, auth: str, actions: list[_Action], dry_run: bool) -> int:
    """Apply the plan. Exit codes: 0 success/noop, 1 HTTP error, 2 conflict."""
    had_conflict = False
    had_error = False
    for action in actions:
        name = action.target.name
        if action.kind == "noop":
            logger.info("noop  %s", name)
            continue
        if action.kind == "conflict":
            had_conflict = True
            existing = action.existing
            assert existing is not None
            logger.error(
                "conflict %s: existing dataType=%s differs from target=%s. "
                "Langfuse cannot re-type a Score Config in place — archive via UI then re-run.",
                name,
                existing.data_type,
                action.target.data_type,
            )
            continue
        if dry_run:
            logger.info("[dry-run] %s %s", action.kind, name)
            continue
        try:
            if action.kind == "create":
                _request("POST", host, "/api/public/score-configs", auth, _create_body(action.target))
                logger.info("created %s", name)
            else:
                existing = action.existing
                assert existing is not None
                _request(
                    "PATCH",
                    host,
                    f"/api/public/score-configs/{existing.config_id}",
                    auth,
                    _patch_body(action),
                )
                logger.info("%s %s", action.kind, name)
        except urllib.error.HTTPError as exc:
            had_error = True
            logger.error("%s %s failed: HTTP %s — %s", action.kind, name, exc.code, exc.read().decode(errors="replace"))
        except urllib.error.URLError as exc:
            had_error = True
            logger.error("%s %s failed: %s", action.kind, name, exc)
    if had_conflict:
        return 2
    if had_error:
        return 1
    return 0


def run(dry_run: bool) -> int:
    host = os.environ.get("LANGFUSE_HOST")
    if not host:
        logger.error("LANGFUSE_HOST env var is required")
        return 3
    try:
        auth = build_auth_header()
    except RuntimeError as exc:
        logger.error("%s", exc)
        return 3
    # Surfaces a right-host / wrong-keys misconfiguration before the first write.
    public_key = os.environ["LANGFUSE_PUBLIC_KEY"]
    logger.info("LANGFUSE_HOST=%s LANGFUSE_PUBLIC_KEY=%s…", host, public_key[:8])
    targets = build_targets()
    logger.info("Target configs: %d", len(targets))
    existing = fetch_existing_configs(host, auth)
    logger.info("Existing configs: %d", len(existing))
    actions = plan(targets, existing)
    counts: dict[str, int] = {}
    for action in actions:
        counts[action.kind] = counts.get(action.kind, 0) + 1
    logger.info("Plan: %s (dry_run=%s)", counts, dry_run)
    return apply(host, auth, actions, dry_run)


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true", help="Log the plan without writing.")
    return parser.parse_args()


if __name__ == "__main__":
    args = _parse_args()
    sys.exit(run(dry_run=args.dry_run))
