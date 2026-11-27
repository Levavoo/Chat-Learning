"""SES inbound email processor for brochure updates.

Receives raw MIME messages stored by SES in S3, authenticates the sender,
extracts ZIP attachments containing XML/PDF brochures, and writes them
to the staging bucket for downstream pre-processing.

Sender authentication uses three layers:
  1. SES SPF/DKIM/DMARC verdicts from the receipt event
  2. Envelope sender (mail.source) cross-checked against the From: header
  3. From: header matched against the ALLOWED_SENDERS allowlist

Extension point for #558: verify_signature() is a no-op stub that will
be replaced with S/MIME certificate validation.
"""

import email
import email.header
import email.utils
import json
import logging
import os
import re
import urllib.parse
import zipfile
from datetime import UTC, datetime
from email.message import Message
from io import BytesIO

import boto3

logger = logging.getLogger()
logger.setLevel(logging.INFO)

s3_client = boto3.client("s3")
sns_client = boto3.client("sns")
ses_client = boto3.client("sesv2")

ALLOWED_SENDERS = [s.strip().lower() for s in os.environ.get("ALLOWED_SENDERS", "").split(",") if s.strip()]
STAGING_BUCKET = os.environ.get("STAGING_BUCKET", "")
INBOX_BUCKET = os.environ.get("INBOX_BUCKET", "")
SNS_ALERT_TOPIC_ARN = os.environ.get("SNS_ALERT_TOPIC_ARN", "")
REPLY_FROM_ADDRESS = os.environ.get("REPLY_FROM_ADDRESS", "")

# Subject convention:
#   Aktualisierung Wissensspeicher - <Gliederung>_<Auflage> - <Dateiname> - Gültig ab: YYYY-MM-DD
# Dateiname may contain spaces and hyphens, so it is captured non-greedily up to
# the literal " - Gültig ab:" delimiter rather than a restrictive character class.
SUBJECT_PATTERN = re.compile(
    r"Aktualisierung Wissensspeicher\s*-\s*"
    r"(?P<gliederung>[A-Za-z0-9]+)_(?P<auflage>\d+)\s*-\s*"
    r"(?P<dateiname>.+?)\s*-\s*"
    r"Gültig ab:\s*(?P<gueltig_ab>\d{4}-\d{2}-\d{2})"
)

EXTRACTABLE_EXTENSIONS = {".xml", ".pdf"}
MAX_FILE_SIZE = 100 * 1024 * 1024  # 100 MB per extracted file
MAX_TOTAL_SIZE = 200 * 1024 * 1024  # 200 MB total decompressed per message
MAX_ENTRIES = 200  # max archive entries inspected per ZIP
REQUIRED_VERDICTS = ("spfVerdict", "dkimVerdict", "dmarcVerdict")
UNSAFE_KEY_CHARS = re.compile(r"[^A-Za-z0-9._-]")


def handler(event, context):
    """Lambda entry point. Invoked asynchronously by SES receipt rule.

    Always returns a result dict instead of raising. SES retries failed async
    invocations up to two more times, which would re-write already-processed
    attachments, so unexpected errors are caught, alerted on, and swallowed.
    The raw message stays in the inbox bucket for manual reprocessing.
    """
    try:
        return _process(event)
    except Exception as exc:
        logger.exception(json.dumps({"action": "unhandled_error"}))
        _send_alert(f"SES inbox processor failed with an unhandled error: {exc!r}")
        return {"status": "error", "reason": "unhandled_error"}


def _process(event: dict) -> dict:
    """Run the processing pipeline for one SES receipt event."""
    ses_record = event["Records"][0]["ses"]
    mail = ses_record["mail"]
    receipt = ses_record.get("receipt", {})

    bucket = INBOX_BUCKET
    key = f"raw/{mail['messageId']}"

    logger.info(json.dumps({"action": "fetch_raw_message", "bucket": bucket, "key": key}))
    raw_bytes = _fetch_from_s3(bucket, key)

    parsed = _parse_mime(raw_bytes)
    header_sender = _extract_sender(parsed)
    envelope_sender = (mail.get("source") or "").strip().lower()
    subject = _decode_header(parsed.get("Subject", ""))
    message_id = _safe_message_id(parsed.get("Message-ID"), mail["messageId"])

    metadata = _parse_subject(subject)
    today = datetime.now(UTC).strftime("%Y-%m-%d")

    log_base = {
        "header_sender": header_sender,
        "envelope_sender": envelope_sender,
        "subject": subject,
        "message_id": message_id,
        "metadata": metadata,
        "signature_status": "skipped",
    }

    # Step 1: Authenticate the sender (SES verdicts, envelope match, allowlist)
    rejection = _authenticate_sender(header_sender, envelope_sender, receipt)
    if rejection:
        logger.warning(json.dumps({**log_base, "action": "sender_rejected", "reason": rejection}))
        _send_alert(
            f"Rejected email.\n"
            f"Reason: {rejection}\n"
            f"From header: {header_sender}\n"
            f"Envelope sender: {envelope_sender}\n"
            f"Subject: {subject}\n"
            f"S3: s3://{bucket}/{key}"
        )
        # Deliberately no reply: the address is unauthenticated.
        return {"status": "quarantined", "reason": rejection}

    # Step 2: Signature verification (no-op stub for #558)
    verify_signature(parsed)

    # Step 3: Extract attachments
    attachments = _extract_attachments(parsed)
    if not attachments:
        logger.warning(json.dumps({**log_base, "action": "no_attachments"}))
        _send_alert(
            f"Email from {header_sender} has no extractable ZIP attachments.\n"
            f"Subject: {subject}\nS3: s3://{bucket}/{key}"
        )
        _send_reply(
            header_sender,
            subject,
            "Ihre E-Mail wurde empfangen, enthielt jedoch keinen verarbeitbaren ZIP-Anhang "
            "(erwartet: ZIP-Datei mit XML- oder PDF-Dateien).\n\n"
            "Bitte prüfen Sie den Anhang und senden Sie die E-Mail erneut.",
            success=False,
        )
        return {"status": "alert", "reason": "no_extractable_attachments"}

    # Step 4: Write to staging bucket
    written = _write_to_staging_bucket(attachments, message_id, today, metadata)
    logger.info(json.dumps({**log_base, "action": "processed", "files_written": written}))

    filenames = [w.rsplit("/", 1)[-1] for w in written]
    _send_reply(
        header_sender,
        subject,
        "Ihre Brochüren-Aktualisierung wurde erfolgreich empfangen und wird verarbeitet.\n\n"
        f"Verarbeitete Dateien ({len(filenames)}):\n" + "\n".join(f"  - {f}" for f in filenames),
        success=True,
    )

    return {"status": "success", "files_written": written}


def verify_signature(parsed: Message) -> None:
    """Verify S/MIME signature of the incoming email.

    Currently a no-op stub. Issue #558 will implement S/MIME certificate
    validation here. When implemented, this function should raise an
    exception on invalid/missing signatures, halting processing.
    """


def _authenticate_sender(header_sender: str, envelope_sender: str, receipt: dict) -> str | None:
    """Authenticate the sender. Returns a rejection reason, or None if accepted.

    Three independent checks, all of which must pass:

    1. SES SPF/DKIM/DMARC verdicts must be PASS. These are computed by SES
       against the envelope sender's domain and cannot be forged by the client.
    2. The envelope sender (SMTP MAIL FROM) must be on the allowlist. This is
       what SPF/DMARC actually authenticated.
    3. The From: header must match the envelope sender, so a passing SPF check
       for one domain cannot be used to display a different sender.

    Note: Lotus Notes/Domino adds a BATV prefix to the envelope sender
    (e.g. `prvs=tag=user@domain`). We strip this before comparison.
    """
    for verdict_key in REQUIRED_VERDICTS:
        status = (receipt.get(verdict_key) or {}).get("status")
        if status != "PASS":
            return f"{verdict_key}={status or 'MISSING'}"

    normalized_envelope = _strip_batv(envelope_sender)

    if not header_sender:
        return "from_header_missing_or_ambiguous"

    if normalized_envelope not in ALLOWED_SENDERS:
        return "envelope_sender_not_allowed"

    if header_sender != normalized_envelope:
        return "header_envelope_mismatch"

    return None


# BATV (Bounce Address Tag Validation) pattern: prvs=<tag>=<address>
_BATV_PATTERN = re.compile(r"^prvs=[0-9a-f]+=", re.IGNORECASE)


def _strip_batv(address: str) -> str:
    """Strip BATV prefix from an email address if present.

    Lotus Notes/Domino uses BATV to tag the envelope sender for bounce
    validation. Example: `prvs=67028d9b4=renate@drv-bund.de` → `renate@drv-bund.de`
    """
    return _BATV_PATTERN.sub("", address)


def _fetch_from_s3(bucket: str, key: str) -> bytes:
    """Download raw MIME message from S3."""
    response = s3_client.get_object(Bucket=bucket, Key=key)
    return response["Body"].read()


def _parse_mime(raw_bytes: bytes) -> Message:
    """Parse raw bytes into an email.message.Message."""
    return email.message_from_bytes(raw_bytes)


def _extract_sender(parsed: Message) -> str:
    """Extract the From: header email address.

    RFC 5322 permits multiple addresses in From:. ``parseaddr`` would silently
    return only the first, so a message could present one address to us and a
    different one to a human reader. Reject anything that is not exactly one
    address rather than picking one.
    """
    addresses = email.utils.getaddresses([_decode_header(parsed.get("From", ""))])
    if len(addresses) != 1:
        logger.warning(
            json.dumps({
                "action": "ambiguous_from_header",
                "address_count": len(addresses),
            })
        )
        return ""
    return addresses[0][1].strip().lower()


def _decode_header(value: str) -> str:
    """Decode MIME-encoded header value (e.g. =?ISO-8859-1?Q?...?=)."""
    parts = email.header.decode_header(value)
    decoded = []
    for part, charset in parts:
        if isinstance(part, bytes):
            decoded.append(part.decode(charset or "utf-8", errors="replace"))
        else:
            decoded.append(part)
    return " ".join(decoded)


def _safe_message_id(raw_message_id: str | None, fallback: str) -> str:
    """Build an S3-key-safe identifier from the Message-ID header.

    The header is attacker-controlled, so anything outside [A-Za-z0-9._-] is
    replaced and consecutive dots are collapsed. This prevents path traversal
    (``foo/../../bar``) and keeps the ``<date>/<message-id>/<file>`` prefix
    shape predictable for downstream scans.
    """
    candidate = (raw_message_id or "").strip().strip("<>").strip()
    sanitized = _sanitize_key_component(candidate)
    if not sanitized:
        sanitized = _sanitize_key_component(fallback)
    return sanitized[:200]


def _sanitize_key_component(value: str) -> str:
    """Replace unsafe characters and collapse dot runs so no ``..`` survives."""
    sanitized = UNSAFE_KEY_CHARS.sub("_", value)
    sanitized = re.sub(r"\.{2,}", ".", sanitized)
    return sanitized.strip("._-")


def _parse_subject(subject: str) -> dict:
    """Parse the subject line convention to extract metadata.

    Expected format:
      Aktualisierung Wissensspeicher - <Gliederung>_<Auflage> - <Dateiname> - Gültig ab: YYYY-MM-DD

    Returns metadata dict for S3 object tagging and structured logging.
    Does NOT affect S3 key generation (message-id is used for that).
    """
    match = SUBJECT_PATTERN.search(subject)
    if not match:
        return {}
    return {
        "gliederungsnummer": match.group("gliederung"),
        "auflagennummer": match.group("auflage"),
        "dateiname": match.group("dateiname").strip(),
        "gueltig_ab": match.group("gueltig_ab"),
    }


def _extract_attachments(parsed: Message) -> list[tuple[str, bytes]]:
    """Find ZIP attachments in the MIME message and extract XML/PDF files.

    Enforces a per-file size cap, a cumulative decompressed size cap, and an
    entry-count cap so a compression bomb cannot exhaust Lambda memory.

    Returns a list of (filename, content_bytes) tuples for extractable files.
    """
    results: list[tuple[str, bytes]] = []
    budget = _ExtractionBudget()

    for part in parsed.walk():
        if not _is_zip_part(part):
            continue

        payload = part.get_payload(decode=True)
        if not payload:
            continue

        try:
            with zipfile.ZipFile(BytesIO(payload)) as zf:
                if _extract_zip_entries(zf, results, budget):
                    return results
        except zipfile.BadZipFile:
            logger.exception(json.dumps({"action": "bad_zip", "filename": part.get_filename()}))
            _send_alert(f"Corrupted ZIP attachment: {part.get_filename()}")

    return results


class _ExtractionBudget:
    """Tracks cumulative decompressed bytes and inspected entries."""

    def __init__(self) -> None:
        self.total_bytes = 0
        self.entries_seen = 0


def _is_zip_part(part: Message) -> bool:
    """Return True if the MIME part looks like a ZIP attachment."""
    filename = part.get_filename()
    return part.get_content_type() in ("application/zip", "application/x-zip-compressed") or bool(
        filename and filename.lower().endswith(".zip")
    )


def _extract_zip_entries(
    zf: zipfile.ZipFile,
    results: list[tuple[str, bytes]],
    budget: _ExtractionBudget,
) -> bool:
    """Extract eligible entries from one archive into ``results``.

    Returns True if a global limit was hit and extraction must stop entirely.
    """
    for name in zf.namelist():
        if budget.entries_seen >= MAX_ENTRIES:
            logger.warning(json.dumps({"action": "stop_extraction", "reason": "entry_limit_reached"}))
            return True
        budget.entries_seen += 1

        if not _is_extractable_entry(name):
            continue

        info = zf.getinfo(name)

        # The uncompressed size in the central directory is attacker-controlled,
        # so this alone would not be a sufficient guard. It is safe as the primary
        # bound because CPython's ZipExtFile caps a read at file_size (it tracks a
        # remaining-bytes counter), so an understated header cannot make read()
        # return more than declared - it truncates instead, and the CRC check then
        # rejects the entry. An overstated header trips this check. Either way the
        # amount decompressed into memory is bounded by MAX_FILE_SIZE.
        if info.file_size > MAX_FILE_SIZE:
            logger.warning(
                json.dumps({
                    "action": "skip_file",
                    "filename": name,
                    "reason": "exceeds_declared_file_size",
                    "size": info.file_size,
                })
            )
            continue

        if budget.total_bytes >= MAX_TOTAL_SIZE:
            logger.warning(
                json.dumps({
                    "action": "stop_extraction",
                    "reason": "total_size_limit_reached",
                    "total_bytes": budget.total_bytes,
                })
            )
            _send_alert(
                "Extraction stopped: cumulative decompressed size limit reached "
                f"({MAX_TOTAL_SIZE} bytes). Possible compression bomb."
            )
            return True

        content = zf.read(name)

        # Count what was actually decompressed, not what the header claimed, so a
        # lying header cannot inflate or hide consumption of the shared budget.
        budget.total_bytes += len(content)
        results.append((os.path.basename(name), content))

    return False


def _is_extractable_entry(name: str) -> bool:
    """Return True if the archive entry is an XML/PDF file we want."""
    if name.endswith("/") or name.startswith(".") or name.startswith("__"):
        return False
    if os.path.splitext(name)[1].lower() not in EXTRACTABLE_EXTENSIONS:
        logger.info(json.dumps({"action": "skip_file", "filename": name, "reason": "extension_not_extractable"}))
        return False
    return True


def _write_to_staging_bucket(
    attachments: list[tuple[str, bytes]], message_id: str, date: str, metadata: dict
) -> list[str]:
    """Write extracted files to the staging bucket for pre-processing.

    Files land at: <YYYY-MM-DD>/<message-id>/<filename>
    """
    written = []
    tagging = urllib.parse.urlencode(metadata) if metadata else ""

    for filename, content in attachments:
        key = f"{date}/{message_id}/{filename}"
        put_args = {"Bucket": STAGING_BUCKET, "Key": key, "Body": content}
        if tagging:
            put_args["Tagging"] = tagging
        s3_client.put_object(**put_args)
        written.append(key)
        logger.info(json.dumps({"action": "write_staging", "bucket": STAGING_BUCKET, "key": key}))

    return written


def _send_alert(message: str) -> None:
    """Publish an alert message to the SNS topic."""
    if not SNS_ALERT_TOPIC_ARN:
        logger.warning("SNS_ALERT_TOPIC_ARN not configured, skipping alert")
        return
    try:
        sns_client.publish(
            TopicArn=SNS_ALERT_TOPIC_ARN,
            Subject="SES Inbox Alert",
            Message=message,
        )
    except Exception:
        logger.exception(json.dumps({"action": "alert_failed"}))


def _send_reply(recipient: str, original_subject: str, body: str, *, success: bool) -> None:
    """Send a confirmation or error reply to the sender via SES.

    Only sends to addresses in ALLOWED_SENDERS to prevent SES from being
    used to send to arbitrary external addresses.
    """
    if not REPLY_FROM_ADDRESS:
        logger.warning("REPLY_FROM_ADDRESS not configured, skipping reply")
        return
    if recipient.lower() not in ALLOWED_SENDERS:
        logger.warning(
            json.dumps({"action": "reply_skipped", "recipient": recipient, "reason": "not_in_allowed_senders"})
        )
        return

    prefix = "Bestätigung" if success else "Hinweis"
    subject = f"Re: {original_subject} [{prefix}]"

    try:
        ses_client.send_email(
            FromEmailAddress=REPLY_FROM_ADDRESS,
            Destination={"ToAddresses": [recipient]},
            Content={
                "Simple": {
                    "Subject": {"Data": subject, "Charset": "UTF-8"},
                    "Body": {"Text": {"Data": body, "Charset": "UTF-8"}},
                }
            },
        )
        logger.info(json.dumps({"action": "reply_sent", "recipient": recipient, "success": success}))
    except Exception:
        logger.exception(json.dumps({"action": "reply_failed", "recipient": recipient}))
