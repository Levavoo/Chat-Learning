"""Unit tests for SES inbox processor Lambda handler."""
# ruff: noqa: S101, D102

import sys
from io import BytesIO
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

# Add the lambda source directory to sys.path so we can import handler
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from conftest import (
    _make_ses_event,
    make_email_no_attachment,
    make_email_with_raw_zip,
    make_email_with_zip,
    make_lying_zip_bytes,
)


@pytest.fixture(autouse=True)
def _reload_handler():
    """Reload handler module for each test to pick up fresh env vars and mocks."""
    sys.modules.pop("handler", None)


@pytest.fixture()
def handler_module():
    """Import handler with mocked boto3 clients."""
    mock_s3 = MagicMock()
    mock_sns = MagicMock()
    mock_ses = MagicMock()

    with patch("boto3.client") as mock_client:

        def client_factory(service, **kwargs):
            if service == "s3":
                return mock_s3
            if service == "sns":
                return mock_sns
            if service == "sesv2":
                return mock_ses
            return MagicMock()

        mock_client.side_effect = client_factory

        import handler

        handler.s3_client = mock_s3
        handler.sns_client = mock_sns
        handler.ses_client = mock_ses

        yield handler, mock_s3, mock_sns, mock_ses


class TestHappyPath:
    """Valid, authenticated email with ZIP containing XML."""

    def test_extracts_xml_to_staging_bucket(self, ses_event, handler_module):
        handler, mock_s3, _mock_sns, _mock_ses = handler_module
        mock_s3.get_object.return_value = {"Body": BytesIO(make_email_with_zip())}

        result = handler.handler(ses_event, None)

        assert result["status"] == "success"
        assert len(result["files_written"]) == 1
        assert "A230_Altersrenten.xml" in result["files_written"][0]

        mock_s3.put_object.assert_called_once()
        call_kwargs = mock_s3.put_object.call_args[1]
        assert call_kwargs["Bucket"] == "ki-lab-digibro-dev-platform-ses-inbox-staging"
        assert call_kwargs["Key"].endswith("/A230_Altersrenten.xml")

    def test_multiple_files_in_zip(self, ses_event, handler_module):
        handler, mock_s3, _mock_sns, _mock_ses = handler_module
        mock_s3.get_object.return_value = {
            "Body": BytesIO(
                make_email_with_zip(
                    zip_contents={
                        "A230_Altersrenten.xml": b"<topic>one</topic>",
                        "B38_Rehabilitation.pdf": b"%PDF-1.4 content",
                    }
                )
            )
        }

        result = handler.handler(ses_event, None)

        assert result["status"] == "success"
        assert len(result["files_written"]) == 2
        assert mock_s3.put_object.call_count == 2

    def test_reply_sent_on_success(self, ses_event, handler_module):
        handler, mock_s3, _mock_sns, mock_ses = handler_module
        mock_s3.get_object.return_value = {"Body": BytesIO(make_email_with_zip())}

        handler.handler(ses_event, None)

        mock_ses.send_email.assert_called_once()
        assert mock_ses.send_email.call_args[1]["Destination"]["ToAddresses"] == ["renate@drv-bund.de"]


class TestSenderAuthentication:
    """SES verdicts, envelope sender, and From-header consistency."""

    def test_rejects_display_name_spoof(self, handler_module):
        """From: header claims an allowed address but envelope sender is an attacker."""
        handler, mock_s3, mock_sns, mock_ses = handler_module
        # Header claims renate@drv-bund.de, envelope is the attacker
        mock_s3.get_object.return_value = {"Body": BytesIO(make_email_with_zip(sender="renate@drv-bund.de"))}
        event = _make_ses_event(envelope_sender="attacker@evil.com")

        result = handler.handler(event, None)

        assert result["status"] == "quarantined"
        assert result["reason"] == "envelope_sender_not_allowed"
        mock_s3.put_object.assert_not_called()
        mock_ses.send_email.assert_not_called()
        mock_sns.publish.assert_called_once()

    def test_rejects_header_envelope_mismatch(self, handler_module):
        """Envelope sender is allowed but the From: header shows a different address."""
        handler, mock_s3, _mock_sns, mock_ses = handler_module
        mock_s3.get_object.return_value = {"Body": BytesIO(make_email_with_zip(sender="someone-else@drv-bund.de"))}
        event = _make_ses_event(envelope_sender="renate@drv-bund.de")

        result = handler.handler(event, None)

        assert result["status"] == "quarantined"
        assert result["reason"] == "header_envelope_mismatch"
        mock_s3.put_object.assert_not_called()
        mock_ses.send_email.assert_not_called()

    def test_rejects_spf_fail(self, handler_module):
        handler, mock_s3, _mock_sns, _mock_ses = handler_module
        mock_s3.get_object.return_value = {"Body": BytesIO(make_email_with_zip())}
        event = _make_ses_event(spf="FAIL")

        result = handler.handler(event, None)

        assert result["status"] == "quarantined"
        assert result["reason"] == "spfVerdict=FAIL"
        mock_s3.put_object.assert_not_called()

    def test_rejects_dkim_fail(self, handler_module):
        handler, mock_s3, _mock_sns, _mock_ses = handler_module
        mock_s3.get_object.return_value = {"Body": BytesIO(make_email_with_zip())}
        event = _make_ses_event(dkim="FAIL")

        result = handler.handler(event, None)

        assert result["status"] == "quarantined"
        assert result["reason"] == "dkimVerdict=FAIL"

    def test_rejects_dmarc_fail(self, handler_module):
        handler, mock_s3, _mock_sns, _mock_ses = handler_module
        mock_s3.get_object.return_value = {"Body": BytesIO(make_email_with_zip())}
        event = _make_ses_event(dmarc="FAIL")

        result = handler.handler(event, None)

        assert result["status"] == "quarantined"
        assert result["reason"] == "dmarcVerdict=FAIL"

    def test_rejects_missing_verdicts(self, handler_module):
        """A receipt without verdicts must not be treated as authenticated."""
        handler, mock_s3, _mock_sns, _mock_ses = handler_module
        mock_s3.get_object.return_value = {"Body": BytesIO(make_email_with_zip())}
        event = _make_ses_event()
        event["Records"][0]["ses"]["receipt"] = {"recipients": ["brochures@mail.digibro-team.de"]}

        result = handler.handler(event, None)

        assert result["status"] == "quarantined"
        assert result["reason"] == "spfVerdict=MISSING"

    def test_rejects_unknown_sender(self, handler_module):
        handler, mock_s3, mock_sns, _mock_ses = handler_module
        mock_s3.get_object.return_value = {"Body": BytesIO(make_email_with_zip(sender="hacker@example.com"))}
        event = _make_ses_event(envelope_sender="hacker@example.com")

        result = handler.handler(event, None)

        assert result["status"] == "quarantined"
        assert result["reason"] == "envelope_sender_not_allowed"
        mock_s3.put_object.assert_not_called()
        mock_sns.publish.assert_called_once()


class TestNoAttachment:
    """Authenticated email with no ZIP attachment."""

    def test_alerts_and_replies_on_missing_zip(self, ses_event, handler_module):
        handler, mock_s3, mock_sns, mock_ses = handler_module
        mock_s3.get_object.return_value = {"Body": BytesIO(make_email_no_attachment())}

        result = handler.handler(ses_event, None)

        assert result["status"] == "alert"
        assert result["reason"] == "no_extractable_attachments"
        mock_s3.put_object.assert_not_called()
        mock_sns.publish.assert_called_once()
        mock_ses.send_email.assert_called_once()


class TestMixedContent:
    """ZIP with mixed content - only XML/PDF extracted."""

    def test_skips_non_extractable_files(self, ses_event, handler_module):
        handler, mock_s3, _mock_sns, _mock_ses = handler_module
        mock_s3.get_object.return_value = {
            "Body": BytesIO(
                make_email_with_zip(
                    zip_contents={
                        "brochure.xml": b"<topic>valid</topic>",
                        "readme.txt": b"ignore me",
                        "image.png": b"\x89PNG",
                        "document.pdf": b"%PDF-1.4",
                    }
                )
            )
        }

        result = handler.handler(ses_event, None)

        assert result["status"] == "success"
        written_keys = result["files_written"]
        assert len(written_keys) == 2
        assert any("brochure.xml" in k for k in written_keys)
        assert any("document.pdf" in k for k in written_keys)


class TestUnhandledErrors:
    """Unexpected failures must not propagate (SES would retry and double-write)."""

    def test_swallows_s3_error_and_alerts(self, ses_event, handler_module):
        handler, mock_s3, mock_sns, _mock_ses = handler_module
        mock_s3.get_object.side_effect = RuntimeError("S3 exploded")

        result = handler.handler(ses_event, None)

        assert result["status"] == "error"
        assert result["reason"] == "unhandled_error"
        mock_sns.publish.assert_called_once()


class TestMessageIdSanitization:
    """Message-ID is attacker-controlled and must be safe for S3 keys."""

    def test_strips_path_traversal(self, handler_module):
        handler, _mock_s3, _mock_sns, _mock_ses = handler_module
        result = handler._safe_message_id("<foo/../../bar@example.com>", "fallback")
        assert "/" not in result
        assert ".." not in result

    def test_falls_back_when_empty(self, handler_module):
        handler, _mock_s3, _mock_sns, _mock_ses = handler_module
        assert handler._safe_message_id("<>", "ses-message-id") == "ses-message-id"
        assert handler._safe_message_id(None, "ses-message-id") == "ses-message-id"

    def test_key_has_no_traversal(self, handler_module):
        handler, mock_s3, _mock_sns, _mock_ses = handler_module
        mock_s3.get_object.return_value = {"Body": BytesIO(make_email_with_zip(message_id="<a/../../b@drv-bund.de>"))}

        result = handler.handler(_make_ses_event(), None)

        assert result["status"] == "success"
        key = result["files_written"][0]
        assert ".." not in key
        assert key.count("/") == 2


class TestVerifySignature:
    """verify_signature() is callable and a no-op."""

    def test_noop_stub(self, handler_module):
        handler, _mock_s3, _mock_sns, _mock_ses = handler_module
        import email as email_mod

        msg = email_mod.message_from_bytes(make_email_with_zip())
        assert handler.verify_signature(msg) is None


class TestSubjectParsing:
    """Subject parsing extracts metadata for S3 tags."""

    def test_valid_subject(self, handler_module):
        handler, _mock_s3, _mock_sns, _mock_ses = handler_module
        metadata = handler._parse_subject(
            "Aktualisierung Wissensspeicher - A230_009 - A230_Altersrenten.zip - Gültig ab: 2026-09-01"
        )
        assert metadata["gliederungsnummer"] == "A230"
        assert metadata["auflagennummer"] == "009"
        assert metadata["dateiname"] == "A230_Altersrenten.zip"
        assert metadata["gueltig_ab"] == "2026-09-01"

    def test_filename_with_spaces_and_hyphens(self, handler_module):
        handler, _mock_s3, _mock_sns, _mock_ses = handler_module
        metadata = handler._parse_subject(
            "Aktualisierung Wissensspeicher - A230_009 - Alters-renten Teil 2.zip - Gültig ab: 2026-09-01"
        )
        assert metadata["dateiname"] == "Alters-renten Teil 2.zip"
        assert metadata["gueltig_ab"] == "2026-09-01"

    def test_invalid_subject_returns_empty(self, handler_module):
        handler, _mock_s3, _mock_sns, _mock_ses = handler_module
        assert handler._parse_subject("Random subject line") == {}


class TestTagEncoding:
    """S3 object tags must be URL-encoded."""

    def test_umlauts_and_spaces_encoded(self, ses_event, handler_module):
        handler, mock_s3, _mock_sns, _mock_ses = handler_module
        mock_s3.get_object.return_value = {
            "Body": BytesIO(
                make_email_with_zip(
                    subject="Aktualisierung Wissensspeicher - A230_009 - Größe & Umfang.zip - Gültig ab: 2026-09-01"
                )
            )
        }

        result = handler.handler(ses_event, None)

        assert result["status"] == "success"
        tagging = mock_s3.put_object.call_args[1]["Tagging"]
        assert " " not in tagging
        assert "ö" not in tagging
        assert tagging.count("&") == 3


class TestExtractionSizeCaps:
    """Decompressed-size limits are enforced on bytes actually read.

    The uncompressed size in a ZIP central directory is attacker-controlled, so
    it is only used as a cheap pre-filter. These tests pin the behaviour for
    both an honest and a lying header.
    """

    def test_declared_size_over_limit_is_skipped(self, ses_event, handler_module):
        """An entry whose declared size exceeds the per-file cap is not read at all."""
        handler, mock_s3, _mock_sns, _mock_ses = handler_module
        mock_s3.get_object.return_value = {"Body": BytesIO(make_email_with_zip(zip_contents={"big.xml": b"x" * 4096}))}

        with patch.object(handler, "MAX_FILE_SIZE", 100):
            result = handler.handler(ses_event, None)

        assert result == {"status": "alert", "reason": "no_extractable_attachments"}
        mock_s3.put_object.assert_not_called()

    def test_cumulative_budget_counts_actual_bytes(self, ses_event, handler_module):
        """The shared budget accumulates real decompressed bytes and stops extraction.

        Uses a self-consistent lying header (declared 1 byte, stream expands to
        4 MB) for the first entry. CPython truncates the read to 1 byte, so the
        budget must grow by 1 - not by the 4 MB the stream holds, nor be inflated
        by a bogus declared value.
        """
        handler, _mock_s3, _mock_sns, _mock_ses = handler_module
        zip_bytes = make_lying_zip_bytes(declared_size=1, actual_size=4 * 1024 * 1024, patch_crc=True)

        budget = handler._ExtractionBudget()
        with handler.zipfile.ZipFile(BytesIO(zip_bytes)) as zf:
            stop = handler._extract_zip_entries(zf, [], budget)

        assert stop is False
        assert budget.total_bytes == 1

    def test_stops_when_budget_exhausted(self, ses_event, handler_module):
        """Once the cumulative cap is reached, extraction stops and alerts."""
        handler, mock_s3, _mock_sns, _mock_ses = handler_module
        contents = {f"file{i}.xml": b"x" * 512 for i in range(4)}
        mock_s3.get_object.return_value = {"Body": BytesIO(make_email_with_zip(zip_contents=contents))}

        with (
            patch.object(handler, "MAX_TOTAL_SIZE", 1024),
            patch.object(handler, "_send_alert") as mock_alert,
        ):
            result = handler.handler(ses_event, None)

        assert len(result["files_written"]) == 2
        mock_alert.assert_called_once()
        assert "compression bomb" in mock_alert.call_args[0][0]

    def test_lying_header_with_intact_crc_is_rejected(self, ses_event, handler_module):
        """Understated size without a matching CRC fails verification and alerts.

        This is the realistic bomb shape: the CRC still covers the full payload,
        so stopping at the declared size is detected as corruption.
        """
        handler, mock_s3, mock_sns, _mock_ses = handler_module
        zip_bytes = make_lying_zip_bytes(declared_size=1, actual_size=4 * 1024 * 1024, patch_crc=False)
        mock_s3.get_object.return_value = {"Body": BytesIO(make_email_with_raw_zip(zip_bytes))}

        result = handler.handler(ses_event, None)

        assert result == {"status": "alert", "reason": "no_extractable_attachments"}
        mock_s3.put_object.assert_not_called()
        alerts = [c[1]["Message"] for c in mock_sns.publish.call_args_list]
        assert any("Corrupted ZIP attachment" in a for a in alerts)

    def test_self_consistent_lying_header_truncates_without_blowup(self, ses_event, handler_module):
        """A self-consistent understated header yields a truncated file, not a huge read.

        Documents an accepted limitation: CPython bounds the read by the declared
        size, so a sender who also patches the CRC gets silent truncation. Memory
        stays bounded, and only an already-authenticated sender can reach this.
        """
        handler, mock_s3, _mock_sns, _mock_ses = handler_module
        zip_bytes = make_lying_zip_bytes(declared_size=1, actual_size=4 * 1024 * 1024, patch_crc=True)
        mock_s3.get_object.return_value = {"Body": BytesIO(make_email_with_raw_zip(zip_bytes))}

        result = handler.handler(ses_event, None)

        assert len(result["files_written"]) == 1
        body = mock_s3.put_object.call_args[1]["Body"]
        assert len(body) == 1

    def test_entry_count_cap(self, ses_event, handler_module):
        """Extraction stops after MAX_ENTRIES archive members are inspected."""
        handler, mock_s3, _mock_sns, _mock_ses = handler_module
        contents = {f"file{i:03d}.xml": b"<t/>" for i in range(10)}
        mock_s3.get_object.return_value = {"Body": BytesIO(make_email_with_zip(zip_contents=contents))}

        with patch.object(handler, "MAX_ENTRIES", 3):
            result = handler.handler(ses_event, None)

        assert len(result["files_written"]) == 3


class TestFromHeaderAmbiguity:
    """RFC 5322 allows multiple addresses in From:; we reject rather than pick one."""

    def test_rejects_multiple_from_addresses(self, handler_module):
        handler, mock_s3, mock_sns, _mock_ses = handler_module
        raw = make_email_with_zip(sender="renate@drv-bund.de, attacker@evil.com")
        mock_s3.get_object.return_value = {"Body": BytesIO(raw)}
        event = _make_ses_event(envelope_sender="renate@drv-bund.de")

        result = handler.handler(event, None)

        assert result["status"] == "quarantined"
        assert result["reason"] == "from_header_missing_or_ambiguous"
        mock_s3.put_object.assert_not_called()
        mock_sns.publish.assert_called_once()

    def test_rejects_missing_from_header(self, handler_module):
        handler, mock_s3, _mock_sns, _mock_ses = handler_module
        raw = make_email_with_zip(sender="")
        mock_s3.get_object.return_value = {"Body": BytesIO(raw)}
        event = _make_ses_event(envelope_sender="renate@drv-bund.de")

        result = handler.handler(event, None)

        assert result["status"] == "quarantined"
        assert result["reason"] == "from_header_missing_or_ambiguous"
