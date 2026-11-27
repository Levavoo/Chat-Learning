"""Shared fixtures for SES inbox processor tests."""

import binascii
import os
import zipfile
from email.mime.application import MIMEApplication
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from io import BytesIO
from unittest.mock import patch

import pytest


@pytest.fixture(autouse=True)
def _env_vars():
    """Set required environment variables for all tests."""
    env = {
        "ALLOWED_SENDERS": "renate@drv-bund.de",
        "STAGING_BUCKET": "ki-lab-digibro-dev-platform-ses-inbox-staging",
        "INBOX_BUCKET": "ki-lab-digibro-dev-platform-ses-inbox",
        "SNS_ALERT_TOPIC_ARN": "arn:aws:sns:eu-central-1:831926590742:ki-lab-digibro-dev-platform-ses-inbox-alerts",
        "REPLY_FROM_ADDRESS": "brochures@mail.digibro-team.de",
    }
    with patch.dict(os.environ, env):
        yield


@pytest.fixture()
def ses_event():
    """Minimal SES Lambda event with all authentication verdicts passing."""
    return _make_ses_event()


def _make_ses_event(
    envelope_sender: str = "renate@drv-bund.de",
    spf: str = "PASS",
    dkim: str = "PASS",
    dmarc: str = "PASS",
) -> dict:
    """Build an SES Lambda event with configurable verdicts and envelope sender."""
    return {
        "Records": [
            {
                "ses": {
                    "mail": {
                        "messageId": "test-message-id-123",
                        "source": envelope_sender,
                        "commonHeaders": {"subject": "Test"},
                    },
                    "receipt": {
                        "recipients": ["brochures@mail.digibro-team.de"],
                        "spfVerdict": {"status": spf},
                        "dkimVerdict": {"status": dkim},
                        "dmarcVerdict": {"status": dmarc},
                    },
                }
            }
        ]
    }


def make_email_with_zip(
    sender: str = "renate@drv-bund.de",
    subject: str = "Aktualisierung Wissensspeicher - A230_009 - A230_Altersrenten.zip - Gültig ab: 2026-09-01",
    zip_contents: dict[str, bytes] | None = None,
    message_id: str = "<test-message-id-123@drv-bund.de>",
) -> bytes:
    """Build a MIME message with a ZIP attachment containing the given files."""
    msg = MIMEMultipart()
    msg["From"] = sender
    msg["To"] = "brochures@mail.digibro-team.de"
    msg["Subject"] = subject
    msg["Message-ID"] = message_id

    msg.attach(MIMEText("Brochure update attached.", "plain"))

    if zip_contents is None:
        zip_contents = {"A230_Altersrenten.xml": b"<topic>test</topic>"}

    zip_buffer = BytesIO()
    with zipfile.ZipFile(zip_buffer, "w") as zf:
        for name, content in zip_contents.items():
            zf.writestr(name, content)
    zip_buffer.seek(0)

    attachment = MIMEApplication(zip_buffer.read(), "zip")
    attachment.add_header("Content-Disposition", "attachment", filename="brochures.zip")
    msg.attach(attachment)

    return msg.as_bytes()


def make_email_no_attachment(
    sender: str = "renate@drv-bund.de",
    subject: str = "Just a question",
) -> bytes:
    """Build a plain text MIME message with no attachments."""
    msg = MIMEText("Hello, no attachment here.")
    msg["From"] = sender
    msg["To"] = "brochures@mail.digibro-team.de"
    msg["Subject"] = subject
    msg["Message-ID"] = "<test-no-attach@drv-bund.de>"
    return msg.as_bytes()


def make_lying_zip_bytes(
    entry_name: str = "bomb.xml",
    declared_size: int = 1,
    actual_size: int = 4 * 1024 * 1024,
    patch_crc: bool = False,
) -> bytes:
    """Build ZIP bytes whose headers understate the decompressed size.

    Writes ``actual_size`` bytes of highly compressible data, then rewrites the
    uncompressed-size field in both the local file header and the central
    directory to ``declared_size``.

    With ``patch_crc=False`` the CRC still covers the full payload, so a reader
    that stops at the declared size fails the CRC check. With ``patch_crc=True``
    the CRC is recomputed over the truncated prefix, making the header
    self-consistent and the truncation silent.
    """
    payload = b"\0" * actual_size

    buffer = BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr(entry_name, payload)
    raw = bytearray(buffer.getvalue())

    true_size = actual_size.to_bytes(4, "little")
    declared = declared_size.to_bytes(4, "little")
    true_crc = (binascii.crc32(payload) & 0xFFFFFFFF).to_bytes(4, "little")
    truncated_crc = (binascii.crc32(payload[:declared_size]) & 0xFFFFFFFF).to_bytes(4, "little")

    # Local file header (PK\x03\x04): CRC at +14, uncompressed size at +22.
    # Central directory header (PK\x01\x02): CRC at +16, uncompressed size at +24.
    for signature, size_offset, crc_offset in ((b"PK\x03\x04", 22, 14), (b"PK\x01\x02", 24, 16)):
        pos = raw.find(signature)
        while pos != -1:
            size_field = pos + size_offset
            if raw[size_field : size_field + 4] == true_size:
                raw[size_field : size_field + 4] = declared
                crc_field = pos + crc_offset
                if patch_crc and raw[crc_field : crc_field + 4] == true_crc:
                    raw[crc_field : crc_field + 4] = truncated_crc
            pos = raw.find(signature, pos + 1)

    return bytes(raw)


def make_email_with_raw_zip(
    zip_bytes: bytes,
    sender: str = "renate@drv-bund.de",
    subject: str = "Aktualisierung Wissensspeicher - A230_009 - bomb.xml - Gültig ab: 2026-09-01",
) -> bytes:
    """Wrap pre-built ZIP bytes in a MIME message with a ZIP attachment."""
    msg = MIMEMultipart()
    msg["From"] = sender
    msg["To"] = "brochures@mail.digibro-team.de"
    msg["Subject"] = subject
    msg["Message-ID"] = "<test-raw-zip@drv-bund.de>"
    msg.attach(MIMEText("Brochure update attached.", "plain"))

    attachment = MIMEApplication(zip_bytes, "zip")
    attachment.add_header("Content-Disposition", "attachment", filename="brochures.zip")
    msg.attach(attachment)

    return msg.as_bytes()
