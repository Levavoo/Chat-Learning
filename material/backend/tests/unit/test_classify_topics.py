"""Unit tests for classify_topics batch script."""

import json

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).parent.parent.parent / "scripts"))

from classify_topics import (  # ty: ignore[unresolved-import]
    _build_prompt,
    _call_nova_lite,
    _parse_topic,
    _scan_unclassified,
    run,
)

SAMPLE_TAXONOMY = [
    {
        "id": "altersrente_regulaer",
        "domain": "rente",
        "label": "Regelaltersrente",
        "description": "Fragen zur regulaeren Altersrente",
    },
    {
        "id": "altersrente_fruehzeitig",
        "domain": "rente",
        "label": "Frühzeitige Altersrente",
        "description": "Fragen zur vorzeitigen Altersrente, Rente mit 63",
    },
    {
        "id": "reha_medizinisch",
        "domain": "reha",
        "label": "Medizinische Reha",
        "description": "Fragen zur medizinischen Rehabilitation",
    },
    {
        "id": "betriebliche_altersvorsorge",
        "domain": "sonstiges",
        "label": "Betriebliche Altersvorsorge",
        "description": "Fragen zur bAV",
    },
    {
        "id": "sonstiges_nicht_zuordenbar",
        "domain": "sonstiges",
        "label": "Sonstiges / nicht zuordenbar",
        "description": "Fragen, die zu keinem der anderen Sub-Themen passen",
    },
    {
        "id": "service_nicht_zuordenbar",
        "domain": "service",
        "label": "Service-/Beratungsanfrage (sonstige)",
        "description": "Allgemeine Dienstleistungs-, Kontakt- oder Beratungsanfragen",
    },
]
VALID_IDS = {t["id"] for t in SAMPLE_TAXONOMY}


class TestBuildPrompt:
    def test_prompt_contains_question(self):
        prompt = _build_prompt("Wann kann ich in Rente gehen?", SAMPLE_TAXONOMY)
        assert "Wann kann ich in Rente gehen?" in prompt

    def test_prompt_contains_all_topic_ids(self):
        prompt = _build_prompt("test question", SAMPLE_TAXONOMY)
        for topic in SAMPLE_TAXONOMY:
            assert topic["id"] in prompt

    def test_prompt_contains_descriptions(self):
        prompt = _build_prompt("test question", SAMPLE_TAXONOMY)
        assert "Fragen zur regulaeren Altersrente" in prompt

    def test_prompt_requests_json_response(self):
        prompt = _build_prompt("test question", SAMPLE_TAXONOMY)
        assert '"topic"' in prompt

    def test_prompt_contains_fallback_topic_ids(self):
        prompt = _build_prompt("test question", SAMPLE_TAXONOMY)
        assert "sonstiges_nicht_zuordenbar" in prompt
        assert "service_nicht_zuordenbar" in prompt

    def test_prompt_contains_fallback_guidance(self):
        prompt = _build_prompt("test question", SAMPLE_TAXONOMY)
        assert "Hinweise zur Zuordnung" in prompt
        assert "service_nicht_zuordenbar" in prompt
        assert "sonstiges_nicht_zuordenbar" in prompt
        assert "themenfremd" in prompt

    def test_prompt_contains_few_shot_examples(self):
        prompt = _build_prompt("test question", SAMPLE_TAXONOMY)
        assert "Beispiele:" in prompt
        assert "Wie wird das Wetter morgen?" in prompt
        assert "Wo finde ich das Formular V0800?" in prompt
        assert "Kann ich mit 63 in Rente gehen?" in prompt


class TestParseTopic:
    def test_valid_topic_extracted(self):
        response = '{"topic": "altersrente_regulaer"}'
        result = _parse_topic(response, VALID_IDS)
        assert result == "altersrente_regulaer"

    def test_topic_extracted_from_noisy_response(self):
        response = 'Sure, here is my answer: {"topic": "reha_medizinisch"} Hope that helps!'
        result = _parse_topic(response, VALID_IDS)
        assert result == "reha_medizinisch"

    def test_unknown_topic_returns_none(self):
        response = '{"topic": "xyz_unbekannt"}'
        result = _parse_topic(response, VALID_IDS)
        assert result is None

    def test_malformed_json_returns_none(self):
        response = "I cannot determine the topic."
        result = _parse_topic(response, VALID_IDS)
        assert result is None

    def test_empty_response_returns_none(self):
        result = _parse_topic("", VALID_IDS)
        assert result is None

    def test_fallback_sonstiges_nicht_zuordenbar_accepted(self):
        response = '{"topic": "sonstiges_nicht_zuordenbar"}'
        result = _parse_topic(response, VALID_IDS)
        assert result == "sonstiges_nicht_zuordenbar"

    def test_fallback_service_nicht_zuordenbar_accepted(self):
        response = '{"topic": "service_nicht_zuordenbar"}'
        result = _parse_topic(response, VALID_IDS)
        assert result == "service_nicht_zuordenbar"


class TestCallNovaLite:
    def test_successful_call_returns_text(self):
        import io

        mock_bedrock = MagicMock()
        response_body = json.dumps({
            "output": {"message": {"content": [{"text": '{"topic": "altersrente_regulaer"}'}]}}
        }).encode()
        mock_bedrock.invoke_model.return_value = {"body": io.BytesIO(response_body)}
        result = _call_nova_lite(mock_bedrock, "test prompt")
        assert result is not None
        assert "altersrente_regulaer" in result

    def test_throttling_retries_and_succeeds(self):
        import io

        from botocore.exceptions import ClientError

        mock_bedrock = MagicMock()
        throttle_error = ClientError(
            {"Error": {"Code": "ThrottlingException", "Message": "Rate exceeded"}}, "invoke_model"
        )
        response_body = json.dumps({
            "output": {"message": {"content": [{"text": '{"topic": "altersrente_regulaer"}'}]}}
        }).encode()
        success_response = {"body": io.BytesIO(response_body)}
        mock_bedrock.invoke_model.side_effect = [throttle_error, success_response]

        with patch("classify_topics.time.sleep"):
            result = _call_nova_lite(mock_bedrock, "test prompt")

        assert result is not None
        assert mock_bedrock.invoke_model.call_count == 2

    def test_max_retries_exceeded_returns_none(self):
        from botocore.exceptions import ClientError

        mock_bedrock = MagicMock()
        throttle_error = ClientError(
            {"Error": {"Code": "ThrottlingException", "Message": "Rate exceeded"}}, "invoke_model"
        )
        mock_bedrock.invoke_model.side_effect = [throttle_error, throttle_error, throttle_error]

        with patch("classify_topics.time.sleep"):
            result = _call_nova_lite(mock_bedrock, "test prompt")

        assert result is None
        assert mock_bedrock.invoke_model.call_count == 3


class TestRunDryRun:
    @patch("classify_topics.boto3")
    @patch("classify_topics._load_taxonomy")
    def test_dry_run_does_not_call_update_item(self, mock_load_taxonomy, mock_boto3):
        import io

        mock_load_taxonomy.return_value = SAMPLE_TAXONOMY
        mock_table = MagicMock()
        mock_boto3.resource.return_value.Table.return_value = mock_table
        mock_bedrock = MagicMock()
        mock_boto3.client.return_value = mock_bedrock

        mock_table.scan.return_value = {
            "Items": [{"session_id": "s1", "message_id": "m1", "message": "Wann kann ich in Rente gehen?"}]
        }

        response_body = json.dumps({
            "output": {"message": {"content": [{"text": '{"topic": "altersrente_regulaer"}'}]}}
        }).encode()
        mock_bedrock.invoke_model.return_value = {"body": io.BytesIO(response_body)}

        run(dry_run=True, limit=None, from_date_str=None)

        mock_table.update_item.assert_not_called()

    @patch("classify_topics.boto3")
    @patch("classify_topics._load_taxonomy")
    def test_items_with_existing_topic_not_updated(self, mock_load_taxonomy, mock_boto3):
        """Idempotency: items already classified are excluded by scan filter."""
        mock_load_taxonomy.return_value = SAMPLE_TAXONOMY
        mock_table = MagicMock()
        mock_boto3.resource.return_value.Table.return_value = mock_table
        mock_boto3.client.return_value = MagicMock()

        mock_table.scan.return_value = {"Items": []}

        run(dry_run=False, limit=None, from_date_str=None)

        mock_table.update_item.assert_not_called()


def test_scan_skips_rating_rows():
    from boto3.dynamodb.conditions import ConditionExpressionBuilder

    table = MagicMock()
    table.scan.return_value = {"Items": []}

    _scan_unclassified(table, from_ts_ms=None, limit=None)

    expression = ConditionExpressionBuilder().build_expression(table.scan.call_args.kwargs["FilterExpression"])
    assert "NOT begins_with" in expression.condition_expression
    assert "message_id" in expression.attribute_name_placeholders.values()
    assert "RATING#" in expression.attribute_value_placeholders.values()
