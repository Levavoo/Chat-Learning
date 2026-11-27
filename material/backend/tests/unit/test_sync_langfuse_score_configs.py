"""Tests for the Langfuse Score Config sync (#941)."""

from __future__ import annotations

import base64
import io
import json
from unittest.mock import patch

import pytest

from scripts import sync_langfuse_score_configs as sync


class TestBuildTargets:
    """Pin categories derived from the Pydantic Literal aliases."""

    @pytest.fixture(autouse=True)
    def _targets(self) -> list[sync._ConfigTarget]:
        self.targets = sync.build_targets()
        return self.targets

    def _by_name(self, name: str) -> sync._ConfigTarget:
        matches = [t for t in self.targets if t.name == name]
        assert matches, f"missing target {name!r}: {[t.name for t in self.targets]}"
        return matches[0]

    def test_technical_correctivity_emits_likert_labels(self):
        target = self._by_name("user.technical_correctivity")
        assert target.data_type == "CATEGORICAL"
        assert target.categories == (
            ("Yes", 1),
            ("Likely yes", 2),
            ("Probably not", 3),
            ("No", 4),
            ("Cannot evaluate", 5),
        )

    def test_comparability_emits_comparability_labels(self):
        target = self._by_name("user.comparability_to_google_ai")
        assert target.categories == (
            ("Better", 1),
            ("Equally good", 2),
            ("Equally bad", 3),
            ("Worse", 4),
            ("Cannot evaluate", 5),
        )

    def test_helpfulness_emits_user_feedback_enum(self):
        """Helpfulness is NOT a Likert field."""
        target = self._by_name("user.helpfulness")
        assert target.categories == (("GOOD", 1), ("NEUTRAL", 2), ("BAD", 3))

    def test_used_scenario_stringifies_int_literal(self):
        """store_feedback emits str(int); config labels must match."""
        target = self._by_name("user.used_scenario")
        assert target.categories == (
            ("0", 0),
            ("1", 1),
            ("2", 2),
            ("3", 3),
            ("4", 4),
            ("5", 5),
            ("6", 6),
        )

    def test_deferred_fields_are_not_registered(self):
        """utility_value + further_development deferred until #939."""
        names = {t.name for t in self.targets}
        assert "user.utility_value" not in names
        assert "user.further_development" not in names

    def test_every_label_has_no_whitespace(self):
        """Trailing space on a Literal silently falls back to unmanaged on ingest."""
        for target in self.targets:
            for label, _ in target.categories:
                assert label == label.strip(), f"{target.name}: {label!r} has whitespace"


class TestBuildCategories:
    """Int Literals keep the arg as the Langfuse value so appends don't shift existing categories; string Literals fall back to positional 1..N."""

    def test_int_literal_uses_arg_as_value(self):
        # Non-sequential order: proves value is the arg, not idx + 1.
        categories = sync._build_categories((1, 2, 3, 4, 5, 6, 0), str)
        assert categories == (
            ("1", 1),
            ("2", 2),
            ("3", 3),
            ("4", 4),
            ("5", 5),
            ("6", 6),
            ("0", 0),
        )

    def test_string_literal_uses_positional_value(self):
        categories = sync._build_categories(("Yes", "No"), str)
        assert categories == (("Yes", 1), ("No", 2))

    def test_bool_literal_falls_back_to_positional(self):
        # bool is an int subclass in Python; keep it on positional values.
        categories = sync._build_categories((True, False), str)
        assert categories == (("True", 1), ("False", 2))


def _target(name: str, data_type: str = "CATEGORICAL") -> sync._ConfigTarget:
    return sync._ConfigTarget(name=name, data_type=data_type, categories=(("A", 1), ("B", 2)))


def _existing(
    name: str,
    *,
    data_type: str = "CATEGORICAL",
    categories: tuple[tuple[str, float], ...] = (("A", 1.0), ("B", 2.0)),
    is_archived: bool = False,
) -> sync._ExistingConfig:
    return sync._ExistingConfig(
        config_id=f"cfg-{name}",
        name=name,
        data_type=data_type,
        categories=categories,
        is_archived=is_archived,
    )


class TestPlan:
    def test_absent_name_is_create(self):
        actions = sync.plan([_target("user.x")], {})
        assert [a.kind for a in actions] == ["create"]

    def test_exact_match_is_noop(self):
        actions = sync.plan([_target("user.x")], {"user.x": _existing("user.x")})
        assert [a.kind for a in actions] == ["noop"]

    def test_categories_drift_is_update(self):
        drifted = _existing("user.x", categories=(("A", 1.0), ("C", 2.0)))
        actions = sync.plan([_target("user.x")], {"user.x": drifted})
        assert [a.kind for a in actions] == ["update"]

    def test_data_type_mismatch_is_conflict(self):
        bad = _existing("user.x", data_type="NUMERIC")
        actions = sync.plan([_target("user.x")], {"user.x": bad})
        assert [a.kind for a in actions] == ["conflict"]

    def test_archived_with_match_is_unarchive(self):
        archived = _existing("user.x", is_archived=True)
        actions = sync.plan([_target("user.x")], {"user.x": archived})
        assert [a.kind for a in actions] == ["unarchive"]

    def test_archived_with_drift_is_unarchive_plus_update(self):
        archived_drift = _existing(
            "user.x",
            categories=(("A", 1.0), ("C", 2.0)),
            is_archived=True,
        )
        actions = sync.plan([_target("user.x")], {"user.x": archived_drift})
        assert [a.kind for a in actions] == ["unarchive+update"]


class _FakeResponse:
    def __init__(self, payload: dict):
        self._payload = json.dumps(payload).encode()

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False

    def read(self):
        return self._payload


class TestApply:
    @pytest.fixture
    def urlopen(self):
        with patch.object(sync.urllib.request, "urlopen") as mock:
            mock.return_value = _FakeResponse({})
            yield mock

    def test_dry_run_issues_no_writes(self, urlopen):
        actions = [
            sync._Action(kind="create", target=_target("user.a"), existing=None),
            sync._Action(kind="update", target=_target("user.b"), existing=_existing("user.b")),
        ]
        code = sync.apply("https://langfuse.test", "Basic x", actions, dry_run=True)
        assert code == 0
        urlopen.assert_not_called()

    def test_conflict_exits_two_without_posts(self, urlopen):
        actions = [
            sync._Action(
                kind="conflict",
                target=_target("user.a"),
                existing=_existing("user.a", data_type="NUMERIC"),
            ),
        ]
        code = sync.apply("https://langfuse.test", "Basic x", actions, dry_run=False)
        assert code == 2
        urlopen.assert_not_called()

    def test_create_posts_full_body(self, urlopen):
        actions = [sync._Action(kind="create", target=_target("user.a"), existing=None)]
        code = sync.apply("https://langfuse.test", "Basic x", actions, dry_run=False)
        assert code == 0
        req = urlopen.call_args.args[0]
        assert req.get_method() == "POST"
        assert req.full_url.endswith("/api/public/score-configs")
        body = json.loads(req.data)
        assert body == {
            "name": "user.a",
            "dataType": "CATEGORICAL",
            "categories": [{"label": "A", "value": 1}, {"label": "B", "value": 2}],
        }

    def test_unarchive_patches_is_archived_only(self, urlopen):
        existing = _existing("user.a", is_archived=True)
        actions = [sync._Action(kind="unarchive", target=_target("user.a"), existing=existing)]
        code = sync.apply("https://langfuse.test", "Basic x", actions, dry_run=False)
        assert code == 0
        req = urlopen.call_args.args[0]
        assert req.get_method() == "PATCH"
        assert req.full_url.endswith(f"/api/public/score-configs/{existing.config_id}")
        assert json.loads(req.data) == {"isArchived": False}

    def test_update_patches_categories_only(self, urlopen):
        existing = _existing("user.a", categories=(("A", 1.0), ("C", 2.0)))
        actions = [sync._Action(kind="update", target=_target("user.a"), existing=existing)]
        code = sync.apply("https://langfuse.test", "Basic x", actions, dry_run=False)
        assert code == 0
        req = urlopen.call_args.args[0]
        assert req.get_method() == "PATCH"
        body = json.loads(req.data)
        assert body == {"categories": [{"label": "A", "value": 1}, {"label": "B", "value": 2}]}

    def test_unarchive_plus_update_patches_both(self, urlopen):
        existing = _existing("user.a", categories=(("A", 1.0), ("C", 2.0)), is_archived=True)
        actions = [sync._Action(kind="unarchive+update", target=_target("user.a"), existing=existing)]
        code = sync.apply("https://langfuse.test", "Basic x", actions, dry_run=False)
        assert code == 0
        body = json.loads(urlopen.call_args.args[0].data)
        assert body == {
            "isArchived": False,
            "categories": [{"label": "A", "value": 1}, {"label": "B", "value": 2}],
        }

    def test_http_error_returns_one(self):
        from email.message import Message

        with patch.object(sync.urllib.request, "urlopen") as mock:
            mock.side_effect = sync.urllib.error.HTTPError(
                "u",
                500,
                "oops",
                Message(),
                io.BytesIO(b"server exploded"),
            )
            actions = [sync._Action(kind="create", target=_target("user.a"), existing=None)]
            code = sync.apply("https://langfuse.test", "Basic x", actions, dry_run=False)
        assert code == 1


class TestFetchExistingConfigs:
    def test_pagination_stops_on_short_page(self):
        pages = iter([
            _FakeResponse({
                "data": [
                    {
                        "id": "c1",
                        "name": "user.a",
                        "dataType": "CATEGORICAL",
                        "categories": [{"label": "A", "value": 1}],
                        "isArchived": False,
                    },
                ]
                * 100
            }),
            _FakeResponse({
                "data": [
                    {
                        "id": "c2",
                        "name": "user.b",
                        "dataType": "CATEGORICAL",
                        "categories": [{"label": "B", "value": 2}],
                        "isArchived": True,
                    },
                ]
            }),
        ])
        with patch.object(sync.urllib.request, "urlopen", side_effect=lambda *_a, **_kw: next(pages)):
            existing = sync.fetch_existing_configs("https://langfuse.test", "Basic x")
        assert "user.a" in existing
        assert existing["user.b"].is_archived is True
        assert existing["user.b"].categories == (("B", 2.0),)


class TestBuildAuthHeader:
    def test_env_vars_resolve_to_basic_header(self, monkeypatch):
        monkeypatch.setenv("LANGFUSE_PUBLIC_KEY", "pk-lf-abc")
        monkeypatch.setenv("LANGFUSE_SECRET_KEY", "sk-lf-xyz")
        header = sync.build_auth_header()
        assert header.startswith("Basic ")
        decoded = base64.b64decode(header[len("Basic ") :]).decode()
        assert decoded == "pk-lf-abc:sk-lf-xyz"

    @pytest.mark.parametrize(
        ("missing"),
        [("LANGFUSE_PUBLIC_KEY",), ("LANGFUSE_SECRET_KEY",), ("LANGFUSE_PUBLIC_KEY", "LANGFUSE_SECRET_KEY")],
    )
    def test_missing_env_raises(self, monkeypatch, missing):
        monkeypatch.setenv("LANGFUSE_PUBLIC_KEY", "pk-lf-abc")
        monkeypatch.setenv("LANGFUSE_SECRET_KEY", "sk-lf-xyz")
        for name in missing:
            monkeypatch.delenv(name, raising=False)
        with pytest.raises(RuntimeError, match="LANGFUSE_PUBLIC_KEY \\+ LANGFUSE_SECRET_KEY"):
            sync.build_auth_header()


class TestRunEnvGuards:
    def test_missing_host_returns_three(self, monkeypatch):
        monkeypatch.delenv("LANGFUSE_HOST", raising=False)
        monkeypatch.setenv("LANGFUSE_PUBLIC_KEY", "pk")
        monkeypatch.setenv("LANGFUSE_SECRET_KEY", "sk")
        assert sync.run(dry_run=False) == 3

    def test_missing_keys_return_three(self, monkeypatch):
        monkeypatch.setenv("LANGFUSE_HOST", "https://langfuse.test")
        monkeypatch.delenv("LANGFUSE_PUBLIC_KEY", raising=False)
        monkeypatch.delenv("LANGFUSE_SECRET_KEY", raising=False)
        assert sync.run(dry_run=False) == 3
