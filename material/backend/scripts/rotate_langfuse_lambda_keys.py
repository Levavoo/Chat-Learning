"""Write a new LangFuse key pair into ``langfuse/<env>/lambda-api-keys`` (#979).

Runbook: ``docs/runbooks/langfuse_key_rotation.md``.

The new pair is asked for hidden (``getpass``) and sent with boto3 directly, so
it never appears in argv, shell history, files or output. Fields already in the
secret are kept; only ``publicKey``/``secretKey`` are replaced. Only the last
four characters of public keys are printed.

Guards (nothing is written if one fails):
- the AWS profile must point at the account that owns the stage,
- both keys must carry the LangFuse prefixes ``pk-lf-`` / ``sk-lf-``,
- the new public key must differ from the current one,
- the operator must type ``yes``.

Writing the secret does NOT reach warm Lambda containers: the chat handler
reads it once per cold start. See the runbook for how to force a restart.

Exit codes: 0 written and read back, 1 aborted or failed, 2 read-back mismatch.

Usage (from ``backend/``)::

    uv run python -m scripts.rotate_langfuse_lambda_keys --profile <aws-profile> --env qa
"""

from __future__ import annotations

import argparse
import getpass
import json
import sys
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

import boto3

REGION = "eu-central-1"

# Stage -> AWS account that owns langfuse/<env>/lambda-api-keys and the
# Lambdas reading it (cdk/parameter.ts). preprod is no longer promoted to but
# still references its secret, so it stays rotatable until it is torn down.
STAGE_ACCOUNTS: dict[str, str] = {
    "dev": "831926590742",
    "qa": "571600837515",
    "preprod": "271033482134",
    "prod": "718036735727",
}


class RotationAborted(Exception):
    """A guard failed; nothing was written."""


@dataclass(frozen=True)
class RotationResult:
    """Outcome of a rotation; carries only version IDs and public-key suffixes."""

    previous_version: str
    new_version: str
    old_public_suffix: str
    new_public_suffix: str
    read_back_ok: bool


def secret_id_for(env: str) -> str:
    """Return the Secrets Manager name the stage's chat Lambda reads."""
    return f"langfuse/{env}/lambda-api-keys"


def suffix(value: str) -> str:
    """Return the last four characters, the only part of a key that is printed."""
    return value[-4:] if value else ""


def check_account(env: str, actual_account: str) -> None:
    """Refuse to write into a secret of the wrong account (e.g. a prod pair into qa)."""
    expected = STAGE_ACCOUNTS[env]
    if actual_account != expected:
        raise RotationAborted(f"profile points at account {actual_account}, but {env} lives in {expected}")


def validate_new_pair(public_key: str, secret_key: str, current_public_key: str) -> None:
    """Reject pairs that are obviously wrong before anything is written."""
    if not public_key.startswith("pk-lf-") or not secret_key.startswith("sk-lf-"):
        raise RotationAborted("keys must start with pk-lf- / sk-lf-")
    if public_key == current_public_key:
        raise RotationAborted("new publicKey equals the current one")


def rotate(
    sm: Any,
    env: str,
    ask_secret: Callable[[str], str],
    confirm: Callable[[str], str],
    out: Callable[[str], None] = print,
) -> RotationResult:
    """Replace the key pair in the stage secret. ``sm`` is a Secrets Manager client."""
    secret_id = secret_id_for(env)

    response = sm.get_secret_value(SecretId=secret_id)
    previous_version = response["VersionId"]
    current = json.loads(response["SecretString"])
    del response

    old_public_key = current.get("publicKey", "")
    out(f"{secret_id}: current publicKey ends with …{suffix(old_public_key)}")
    out(f"Other fields kept: {sorted(k for k in current if k not in ('publicKey', 'secretKey'))}")

    public_key = ask_secret("New publicKey (pk-lf-…): ").strip()
    secret_key = ask_secret("New secretKey (sk-lf-…): ").strip()
    validate_new_pair(public_key, secret_key, old_public_key)

    if confirm(f"Write new pair (…{suffix(public_key)}) into {secret_id}? [yes/N] ") != "yes":
        raise RotationAborted("not confirmed")

    current.update(publicKey=public_key, secretKey=secret_key)
    written = sm.put_secret_value(SecretId=secret_id, SecretString=json.dumps(current))
    del current, secret_key

    check = json.loads(sm.get_secret_value(SecretId=secret_id)["SecretString"])
    read_back_ok = check.get("publicKey") == public_key
    del check

    return RotationResult(
        previous_version=previous_version,
        new_version=written["VersionId"],
        old_public_suffix=suffix(old_public_key),
        new_public_suffix=suffix(public_key),
        read_back_ok=read_back_ok,
    )


def main(argv: list[str] | None = None) -> int:
    """CLI entry point; returns the process exit code."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--profile", required=True, help="AWS profile of the stage account")
    parser.add_argument("--env", required=True, choices=sorted(STAGE_ACCOUNTS))
    ns = parser.parse_args(argv)

    session = boto3.Session(profile_name=ns.profile, region_name=REGION)
    try:
        account = session.client("sts").get_caller_identity()["Account"]
        check_account(ns.env, account)
        print(f"Account {account} ({ns.env})")
        result = rotate(session.client("secretsmanager"), ns.env, getpass.getpass, input)
    except RotationAborted as exc:
        print(f"Aborted: {exc}. Nothing written.", file=sys.stderr)
        return 1

    secret_id = secret_id_for(ns.env)
    status = "OK" if result.read_back_ok else "MISMATCH"
    print(f"Written. VersionId {result.new_version}, publicKey …{result.new_public_suffix}, read-back {status}")
    print(f"Old publicKey was …{result.old_public_suffix}. Delete it in LangFuse only after the restart is verified.")
    print(
        f"Rollback: aws --profile {ns.profile} --region {REGION} secretsmanager update-secret-version-stage "
        f"--secret-id {secret_id} --version-stage AWSCURRENT "
        f"--move-to-version-id {result.previous_version} --remove-from-version-id {result.new_version}"
    )
    return 0 if result.read_back_ok else 2


if __name__ == "__main__":
    sys.exit(main())
