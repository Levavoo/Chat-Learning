from backend_orchestrator.response_parser import (
    extract_cited_indices,
    filter_sources_by_citations,
    parse_agent_response,
    sanitize_urls,
    unescape_literal_whitespace,
)


class TestExtractCitedIndices:
    def test_extracts_single_citation(self):
        text = "This is a fact [1] from the knowledge base."
        assert extract_cited_indices(text) == {1}

    def test_extracts_multiple_citations(self):
        text = "First fact [1] and second fact [2] and third [3]."
        assert extract_cited_indices(text) == {1, 2, 3}

    def test_handles_repeated_citations(self):
        text = "Fact [1] is important [1] and [2] as well [1]."
        assert extract_cited_indices(text) == {1, 2}

    def test_returns_empty_for_no_citations(self):
        text = "This text has no citations at all."
        assert extract_cited_indices(text) == set()

    def test_handles_multidigit_indices(self):
        text = "Source [10] and [99] are cited."
        assert extract_cited_indices(text) == {10, 99}

    def test_ignores_non_numeric_brackets(self):
        text = "This [text] has [no] numeric [citations]."
        assert extract_cited_indices(text) == set()


class TestFilterSourcesByCitations:
    def test_filters_to_cited_sources_only(self):
        sources = [
            {"sourceId": "doc1", "sourceName": "Doc 1", "sourceIndex": 1},
            {"sourceId": "doc2", "sourceName": "Doc 2", "sourceIndex": 2},
            {"sourceId": "doc3", "sourceName": "Doc 3", "sourceIndex": 3},
        ]
        response_text = "Info from [1] and [3]."

        result = filter_sources_by_citations(sources, response_text)

        assert len(result) == 2
        assert result[0]["sourceIndex"] == 1
        assert result[1]["sourceIndex"] == 3

    def test_returns_empty_when_no_citations(self):
        sources = [
            {"sourceId": "doc1", "sourceName": "Doc 1", "sourceIndex": 1},
        ]
        response_text = "No citations here."

        result = filter_sources_by_citations(sources, response_text)

        assert result == []

    def test_handles_empty_sources_list(self):
        result = filter_sources_by_citations([], "Text [1] with citation.")
        assert result == []

    def test_preserves_source_order(self):
        """Order matches original sources list, not citation order."""
        sources = [
            {"sourceId": "doc1", "sourceIndex": 1},
            {"sourceId": "doc2", "sourceIndex": 2},
            {"sourceId": "doc3", "sourceIndex": 3},
        ]
        response_text = "[3] comes first then [1]."

        result = filter_sources_by_citations(sources, response_text)

        assert result[0]["sourceIndex"] == 1
        assert result[1]["sourceIndex"] == 3


class TestSanitizeUrls:
    SOFT_HYPHEN = "­"
    UNICODE_HYPHEN = "‐"  # noqa: RUF001
    NON_BREAKING_HYPHEN = "‑"  # noqa: RUF001
    FIGURE_DASH = "‒"  # noqa: RUF001
    EN_DASH = "–"  # noqa: RUF001

    def test_soft_hyphen_removed_from_plain_text(self):
        text = f"hel{self.SOFT_HYPHEN}lo world"
        assert sanitize_urls(text) == "hello world"

    def test_soft_hyphen_removed_from_url(self):
        text = f"https://exam{self.SOFT_HYPHEN}ple.com/path"
        assert sanitize_urls(text) == "https://example.com/path"

    def test_unicode_hyphen_normalized_inside_url(self):
        text = f"see https://example.com/some{self.UNICODE_HYPHEN}page for info"
        assert sanitize_urls(text) == "see https://example.com/some-page for info"

    def test_non_breaking_hyphen_normalized_inside_url(self):
        text = f"https://example.com/a{self.NON_BREAKING_HYPHEN}b"
        assert sanitize_urls(text) == "https://example.com/a-b"

    def test_figure_dash_normalized_inside_url(self):
        text = f"https://example.com/a{self.FIGURE_DASH}b"
        assert sanitize_urls(text) == "https://example.com/a-b"

    def test_en_dash_normalized_inside_url(self):
        text = f"https://example.com/a{self.EN_DASH}b"
        assert sanitize_urls(text) == "https://example.com/a-b"

    def test_unicode_hyphens_not_replaced_outside_url(self):
        text = f"some{self.EN_DASH}text without a url"
        assert sanitize_urls(text) == text

    def test_surrounding_text_unchanged_when_url_normalized(self):
        text = f"before https://example.com/a{self.EN_DASH}b after"
        result = sanitize_urls(text)
        assert result.startswith("before ")
        assert result.endswith(" after")
        assert "https://example.com/a-b" in result

    def test_plain_text_unchanged(self):
        text = "hello world, no URLs here"
        assert sanitize_urls(text) == text

    def test_multiple_urls_all_normalized(self):
        text = f"https://a.com/x{self.EN_DASH}y and https://b.com/p{self.UNICODE_HYPHEN}q"
        result = sanitize_urls(text)
        assert "https://a.com/x-y" in result
        assert "https://b.com/p-q" in result


class TestBuildChatResponseTraceId:
    """`build_chat_response` must expose trace_id as camelCase traceId for score correlation."""

    def test_trace_id_present_in_serialized_response(self):
        from backend_orchestrator.response_parser import build_chat_response

        response = build_chat_response(
            session_id="sess-xyz",
            response_text="hello",
            used_chunks=[],
            request_time_epoch=1700000000000,
            message_id="msg-1",
            trace_id="deadbeef-dead-beef-dead-beefdeadbeef",
        )

        assert response["traceId"] == "deadbeef-dead-beef-dead-beefdeadbeef"

    def test_trace_id_defaults_to_none(self):
        from backend_orchestrator.response_parser import build_chat_response

        response = build_chat_response(
            session_id="sess-xyz",
            response_text="hello",
            used_chunks=[],
            request_time_epoch=1700000000000,
            message_id="msg-1",
        )

        assert response["traceId"] is None


class TestBuildChatResponseEvalMode:
    """``eval_mode`` gates eval-only payload additions; without it the public shape is unchanged."""

    def test_eval_payload_absent_without_opt_in(self):
        from backend_orchestrator.response_parser import build_chat_response

        response = build_chat_response(
            session_id="sess-xyz",
            response_text="hello",
            used_chunks=[
                {
                    "content": "c",
                    "contentType": "text",
                    "rank": 1,
                    "sectionTitle": "§ 1",
                    "domainTier": "S",
                }
            ],
            request_time_epoch=1700000000000,
            message_id="msg-1",
        )

        assert "allSources" not in response["message"]
        assert "all_sources" not in response["message"]
        chunk = response["message"]["usedChunks"][0]
        assert "sectionTitle" not in chunk
        assert "domainTier" not in chunk
        # Pre-existing nullable fields must stay in the wire payload — frontend relies on them.
        assert response["traceId"] is None
        assert response["message"]["feedback"] is None

    def test_eval_payload_included_when_eval_mode(self):
        from backend_orchestrator.response_parser import build_chat_response

        response = build_chat_response(
            session_id="sess-xyz",
            response_text="hello",
            used_chunks=[
                {
                    "content": "cited",
                    "contentType": "text",
                    "rank": 1,
                    "sectionTitle": "§ 1",
                    "domainTier": "S",
                }
            ],
            request_time_epoch=1700000000000,
            message_id="msg-1",
            all_sources=[
                {"content": "cited", "contentType": "text", "rank": 1},
                {"content": "uncited", "contentType": "text", "rank": 2, "sectionTitle": "§ 2"},
            ],
            eval_mode=True,
        )

        assert len(response["message"]["allSources"]) == 2
        assert response["message"]["allSources"][1]["sectionTitle"] == "§ 2"
        chunk = response["message"]["usedChunks"][0]
        assert chunk["sectionTitle"] == "§ 1"
        assert chunk["domainTier"] == "S"

    def test_all_sources_ignored_when_eval_mode_false(self):
        from backend_orchestrator.response_parser import build_chat_response

        response = build_chat_response(
            session_id="sess-xyz",
            response_text="hello",
            used_chunks=[],
            request_time_epoch=1700000000000,
            message_id="msg-1",
            all_sources=[{"content": "u", "contentType": "text", "rank": 1}],
            eval_mode=False,
        )

        assert "allSources" not in response["message"]

    def test_root_span_id_surfaced_in_eval_mode(self):
        """``root_span_id`` → camelCase ``rootSpanId`` so eval clients can post scores against (traceId, observationId)."""
        from backend_orchestrator.response_parser import build_chat_response

        response = build_chat_response(
            session_id="sess-xyz",
            response_text="hello",
            used_chunks=[],
            request_time_epoch=1700000000000,
            message_id="msg-1",
            root_span_id="deadbeefcafebabe",
            eval_mode=True,
        )

        assert response["message"]["rootSpanId"] == "deadbeefcafebabe"

    def test_root_span_id_absent_without_eval_mode(self):
        """``rootSpanId`` must never leak to normal callers."""
        from backend_orchestrator.response_parser import build_chat_response

        response = build_chat_response(
            session_id="sess-xyz",
            response_text="hello",
            used_chunks=[],
            request_time_epoch=1700000000000,
            message_id="msg-1",
            root_span_id="deadbeefcafebabe",
            eval_mode=False,
        )

        assert "rootSpanId" not in response["message"]
        assert "root_span_id" not in response["message"]


class TestParseAgentResponse:
    def test_returns_plain_text_as_is(self):
        text, docs = parse_agent_response("Simple response text")
        assert text == "Simple response text"
        assert docs is None

    def test_parses_result_from_json(self):
        import json

        response = json.dumps({"result": "Parsed result text"})
        text, _ = parse_agent_response(response)
        assert text == "Parsed result text"

    def test_extracts_related_documents(self):
        import json

        response = json.dumps({
            "result": "Response",
            "relatedDocuments": [{"name": "Doc1"}],
        })
        _, docs = parse_agent_response(response)
        assert docs == [{"name": "Doc1"}]


class TestUnescapeLiteralWhitespace:
    def test_converts_literal_newline_to_real_newline(self):
        assert unescape_literal_whitespace("line1\\nline2") == "line1\nline2"

    def test_converts_double_newline(self):
        assert unescape_literal_whitespace("para1\\n\\npara2") == "para1\n\npara2"

    def test_converts_literal_carriage_return_newline(self):
        assert unescape_literal_whitespace("a\\r\\nb") == "a\nb"

    def test_converts_literal_tab(self):
        assert unescape_literal_whitespace("col1\\tcol2") == "col1\tcol2"

    def test_noop_when_no_literal_escapes(self):
        text = "Eine Fachkraft ist eine Person mit anerkannter Qualifikation."
        assert unescape_literal_whitespace(text) is text

    def test_preserves_existing_real_newlines(self):
        text = "Wichtige Punkte:\n- Erstens\n- Zweitens"
        assert unescape_literal_whitespace(text) == text

    def test_reported_bullet_list_scenario(self):
        raw = "...zahlen gemeinsam Beiträge.\\n\\nWer gilt als Fachkraft?\\n- Berufliche Qualifikation: ..."
        expected = "...zahlen gemeinsam Beiträge.\n\nWer gilt als Fachkraft?\n- Berufliche Qualifikation: ..."
        assert unescape_literal_whitespace(raw) == expected
