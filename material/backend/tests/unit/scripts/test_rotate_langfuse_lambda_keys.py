"""Tests for the LangFuse Lambda key rotation helper (#979)."""

from __future__ import annotations

import json

import boto3
import pytest
from botocore.stub import Stubber

from scripts import rotate_langfuse_lambda_keys as rot

SECRET_ID = "langfuse/qa/lambda-api-keys"  # noqa: S105 -- secret name, not a value
ARN = "arn:aws:secretsmanager:eu-central-1:571600837515:secret:langfuse/qa/lambda-api-keys-AbCdEf"
V_OLD = "00000000-0000-0000-0000-000000000001"
V_NEW = "00000000-0000-0000-0000-000000000002"
V_OTHER = "00000000-0000-0000-0000-000000000003"
OLD = {"publicKey": "pk-lf-old-7960", "secretKey": "sk-lf-old-secret", "host": "https://lf.example"}
NEW_PK = "pk-lf-new-a5eb"
NEW_SK = "sk-lf-new-secret"


def _client() -> tuple[object, Stubber]:
    # Explicit dummy credentials: Stubber still signs, and the developer's
    # local AWS config must never be touched by a unit test.
    sm = boto3.client(
        "secretsmanager",
        region_name=rot.REGION,
        aws_access_key_id="testing",
        aws_secret_access_key="testing",  # noqa: S106 -- dummy for the Stubber
    )
    return sm, Stubber(sm)


def _answers(*values: str):
    it = iter(values)
    return lambda _prompt: next(it)


def _stub_read(stub: Stubber, payload: dict, version: str = V_OLD) -> None:
    stub.add_response(
        "get_secret_value",
        {"ARN": ARN, "Name": SECRET_ID, "VersionId": version, "SecretString": json.dumps(payload)},
        {"SecretId": SECRET_ID},
    )


class TestRotate:
    def test_replaces_only_the_key_pair_and_reads_back(self):
        sm, stub = _client()
        _stub_read(stub, OLD)
        expected = {**OLD, "publicKey": NEW_PK, "secretKey": NEW_SK}
        stub.add_response(
            "put_secret_value",
            {"ARN": ARN, "Name": SECRET_ID, "VersionId": V_NEW},
            {"SecretId": SECRET_ID, "SecretString": json.dumps(expected)},
        )
        _stub_read(stub, expected, version=V_NEW)
        printed: list[str] = []

        with stub:
            result = rot.rotate(sm, "qa", _answers(NEW_PK, NEW_SK), _answers("yes"), printed.append)
        stub.assert_no_pending_responses()

        assert result == rot.RotationResult(V_OLD, V_NEW, "7960", "a5eb", True)
        # Never print a secret key, and only suffixes of public keys.
        joined = "\n".join(printed)
        assert "sk-lf" not in joined
        assert NEW_PK not in joined and OLD["publicKey"] not in joined

    def test_read_back_mismatch_is_reported(self):
        sm, stub = _client()
        _stub_read(stub, OLD)
        stub.add_response("put_secret_value", {"ARN": ARN, "Name": SECRET_ID, "VersionId": V_NEW})
        _stub_read(stub, OLD, version=V_OTHER)

        with stub:
            result = rot.rotate(sm, "qa", _answers(NEW_PK, NEW_SK), _answers("yes"), lambda _: None)

        assert result.read_back_ok is False

    @pytest.mark.parametrize(
        ("public_key", "secret_key", "reason"),
        [
            ("pk-other", NEW_SK, "pk-lf-"),
            (NEW_PK, "sk-other", "sk-lf-"),
            (OLD["publicKey"], NEW_SK, "equals the current one"),
        ],
    )
    def test_invalid_pair_writes_nothing(self, public_key, secret_key, reason):
        sm, stub = _client()
        _stub_read(stub, OLD)  # no put_secret_value stubbed: a write would fail the test

        with stub, pytest.raises(rot.RotationAborted, match=reason):
            rot.rotate(sm, "qa", _answers(public_key, secret_key), _answers("yes"), lambda _: None)
        stub.assert_no_pending_responses()

    @pytest.mark.parametrize("answer", ["", "y", "YES", "no"])
    def test_anything_but_yes_writes_nothing(self, answer):
        sm, stub = _client()
        _stub_read(stub, OLD)

        with stub, pytest.raises(rot.RotationAborted, match="not confirmed"):
            rot.rotate(sm, "qa", _answers(NEW_PK, NEW_SK), _answers(answer), lambda _: None)


class TestCheckAccount:
    @pytest.mark.parametrize("env", sorted(rot.STAGE_ACCOUNTS))
    def test_matching_account_passes(self, env):
        rot.check_account(env, rot.STAGE_ACCOUNTS[env])

    def test_prod_key_into_qa_account_is_refused(self):
        with pytest.raises(rot.RotationAborted, match="lives in 718036735727"):
            rot.check_account("prod", rot.STAGE_ACCOUNTS["qa"])

    def test_preprod_stays_rotatable_while_its_secret_is_referenced(self):
        # cdk/parameter.ts still points preprod at langfuse/preprod/lambda-api-keys.
        assert rot.STAGE_ACCOUNTS["preprod"] == "271033482134"


class _FakeSession:
    """Stands in for boto3.Session; hands out the stubbed clients."""

    def __init__(self, account: str, sm: object):
        self._account = account
        self._sm = sm

    def client(self, name: str):
        if name == "sts":
            sts = boto3.client(
                "sts",
                region_name=rot.REGION,
                aws_access_key_id="testing",
                aws_secret_access_key="testing",  # noqa: S106 -- dummy for the Stubber
            )
            stub = Stubber(sts)
            stub.add_response(
                "get_caller_identity",
                {"Account": self._account, "Arn": "arn:aws:iam::000000000000:user/x", "UserId": "x"},
            )
            stub.activate()
            return sts
        return self._sm


class TestMain:
    """Guards must hold at the entry point, not only in the helpers."""

    def _run(self, monkeypatch, account: str, sm: object, answers: tuple[str, ...]) -> int:
        monkeypatch.setattr(rot.boto3, "Session", lambda **_kw: _FakeSession(account, sm))
        it = iter(answers)
        monkeypatch.setattr(rot.getpass, "getpass", lambda _p: next(it))
        monkeypatch.setattr("builtins.input", lambda _p: "yes")
        return rot.main(["--profile", "p", "--env", "qa"])

    def test_wrong_account_exits_1_and_writes_nothing(self, monkeypatch):
        sm, stub = _client()  # nothing stubbed: any Secrets Manager call fails the test
        with stub:
            code = self._run(monkeypatch, rot.STAGE_ACCOUNTS["prod"], sm, (NEW_PK, NEW_SK))
        assert code == 1
        stub.assert_no_pending_responses()

    def test_read_back_mismatch_exits_2(self, monkeypatch):
        sm, stub = _client()
        _stub_read(stub, OLD)
        stub.add_response("put_secret_value", {"ARN": ARN, "Name": SECRET_ID, "VersionId": V_NEW})
        _stub_read(stub, OLD, version=V_OTHER)
        with stub:
            code = self._run(monkeypatch, rot.STAGE_ACCOUNTS["qa"], sm, (NEW_PK, NEW_SK))
        assert code == 2

    def test_happy_path_exits_0(self, monkeypatch):
        sm, stub = _client()
        _stub_read(stub, OLD)
        expected = {**OLD, "publicKey": NEW_PK, "secretKey": NEW_SK}
        stub.add_response("put_secret_value", {"ARN": ARN, "Name": SECRET_ID, "VersionId": V_NEW})
        _stub_read(stub, expected, version=V_NEW)
        with stub:
            code = self._run(monkeypatch, rot.STAGE_ACCOUNTS["qa"], sm, (NEW_PK, NEW_SK))
        assert code == 0
        stub.assert_no_pending_responses()
