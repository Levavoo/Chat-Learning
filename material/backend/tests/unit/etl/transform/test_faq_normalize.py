import gzip
import hashlib
from dataclasses import FrozenInstanceError
from pathlib import Path
from unittest.mock import patch

import pytest

from etl.transform.faq_normalize import (
    CONTACT_OPTIONAL,
    CONTACT_REQUIRED,
    REQUIRED_FAQ_METADATA_KEYS,
    FaqDocument,
    FaqItem,
    FaqMetadataError,
    build_faq_metadata,
    contact_boundary_mode,
    extract_faq_items,
    extract_publish_date,
    generated_faq_documents,
    normalize_heading_identity,
    select_document_faq_items,
    semantic_faq_hash,
    strip_page_chrome,
    validate_faq_metadata,
    validate_generated_faq_metadata,
)

MIDDLE_QUESTIONS = [
    "Wann kann ich in Rente gehen und was muss ich beachten?",
    "Gibt es Möglichkeiten, zusätzlich Geld für die Rente anzusparen?",
    "Wie beantrage ich meine Rente richtig?",
    "Wer kann mir weiterhelfen bei offenen Fragen?",
    "Ich habe meine Rentenzahlung nicht erhalten — was tun?",
    "Wird mein Einkommen auf meine Rente angerechnet?",
    "Welche Auswirkung hat es auf die gesetzliche Rentenversicherung wenn ich auswandere?",
    "Wie bekomme ich meine Renteninformation zugestellt?",
    "Ich bin selbstständig — welche Pflichten habe ich?",
    "Ich bin krank — was bedeutet das für meine Rente?",
]
CURRENT_FIRST_QUESTION = "Wie ändert sich die Auszahlung des Zuschlags für Erwerbsminderungsrenten?"
A_UND_B = "faq-a-und-b"
PFLEGEVERSICHERUNG = "faq-pflegeversicherung"
STEP_2_STEMS = (
    "faq-fruehstartrente",
    "faq-rentenanpassung-2026",
    "faq-a1-bescheinigung",
    "faq-rentenanspruch-international",
)


def _select_a_und_b(items: list[FaqItem]) -> list[FaqDocument]:
    return select_document_faq_items(items, source_stem=A_UND_B)


def _hash_a_und_b(html_content: str | bytes) -> str:
    return semantic_faq_hash(html_content, source_stem=A_UND_B)


def _make_full_faq_html(
    *,
    middle_questions: list[str] | None = None,
    include_aktuelles: bool = True,
    use_heading_buttons: bool = True,
    publish_date: str = "2024-01-15",
    aktuelles_content: str = "Breaking news today!",
    contact_content: str = "Contact us",
    anchors: list[str | None] | None = None,
    answer_overrides: dict[int, str | None] | None = None,
    extra_chrome: bool = True,
) -> str:
    if middle_questions is None:
        middle_questions = MIDDLE_QUESTIONS
    questions = [
        *(["Aktuelles — Neuigkeiten zur Rente"] if include_aktuelles else []),
        *middle_questions,
        "Ihre Frage war nicht dabei? Kontaktieren Sie uns!",
    ]
    resolved_anchors: list[str | None] = (
        [f"content-{index}" for index in range(len(questions))] if anchors is None else anchors
    )
    answer_overrides = answer_overrides or {}

    items = []
    for index, (question, anchor) in enumerate(zip(questions, resolved_anchors, strict=True)):
        default_answer = (
            aktuelles_content
            if include_aktuelles and index == 0
            else contact_content
            if index == len(questions) - 1
            else f"Answer for: {question}"
        )
        answer = answer_overrides.get(index, default_answer)
        anchor_attribute = f' aria-controls="{anchor}"' if anchor else ""
        heading = (
            f'<h2 class="c-accordion__heading"><button{anchor_attribute}>{question}</button></h2>'
            if use_heading_buttons
            else f'<h2 class="c-accordion__heading">{question}</h2>'
        )
        content_id = f' id="{anchor}"' if anchor else ""
        content = "" if answer is None else f'<div class="c-accordion__content"{content_id}><p>{answer}</p></div>'
        items.append(f"{heading}{content}")

    chrome = ""
    if extra_chrome:
        chrome = """
        <nav><a href="/home">Home</a></nav><header><h1>DRV FAQ</h1></header>
        <script>tracking()</script><style>.hidden { display: none; }</style><footer>Footer</footer>
        """
    return f"""<!DOCTYPE html><html><head>
<meta name="dc.date" content="{publish_date}"><meta name="dc.creator" content="DRV">
</head><body>{chrome}<div class="c-accordion">{"".join(items)}</div></body></html>"""


class TestStripPageChrome:
    def test_preserves_complete_accordion_and_date(self):
        result = strip_page_chrome(_make_full_faq_html(publish_date="2024-06-15"))
        assert len(extract_faq_items(result)) == 12
        assert b"2024-06-15" in result
        assert b"aria-controls" in result

    def test_removes_page_chrome_and_other_metadata(self):
        result = strip_page_chrome(_make_full_faq_html())
        for rejected in (b"<nav", b"<header", b"<footer", b"<script", b"<style", b"dc.creator"):
            assert rejected not in result

    def test_is_deterministic_utf8_bytes_without_heading_downgrade(self):
        raw = _make_full_faq_html()
        assert strip_page_chrome(raw) == strip_page_chrome(raw.encode())
        assert b"<h2" in strip_page_chrome(raw)


class TestExtractionAndSelection:
    def test_extracts_named_immutable_items(self):
        item = extract_faq_items(_make_full_faq_html())[1]
        assert isinstance(item, FaqItem)
        assert item.question == MIDDLE_QUESTIONS[0]
        assert item.anchor_id == "content-1"
        assert "Answer for" in item.content_html
        with pytest.raises(FrozenInstanceError):
            item.question = "changed"  # ty: ignore[invalid-assignment]

    def test_missing_answer_is_retained_for_fail_closed_validation(self):
        item = extract_faq_items(_make_full_faq_html(answer_overrides={1: None}))[1]
        assert item.content_html == ""
        with pytest.raises(ValueError, match="empty answer"):
            _select_a_und_b(extract_faq_items(_make_full_faq_html(answer_overrides={1: None})))

    def test_current_baseline_selects_ten_documents(self):
        documents = _select_a_und_b(extract_faq_items(_make_full_faq_html()))
        assert len(documents) == 10
        assert documents[0].display_name == "FAQ Rentenbeginn"
        assert documents[-1].display_name == "FAQ Krankheit, Reha, Erwerbsminderung"

    def test_layout_without_aktuelles_selects_first_item_as_document(self):
        documents = _select_a_und_b(
            extract_faq_items(
                _make_full_faq_html(
                    middle_questions=[CURRENT_FIRST_QUESTION, *MIDDLE_QUESTIONS],
                    include_aktuelles=False,
                    use_heading_buttons=False,
                )
            )
        )
        assert len(documents) == 11
        assert documents[0].question == CURRENT_FIRST_QUESTION
        assert documents[0].display_name == "FAQ Rentenbeginn"
        assert documents[0].anchor_id == "content-0"

    def test_buttonless_heading_uses_adjacent_content_id_as_anchor(self):
        items = extract_faq_items(_make_full_faq_html(include_aktuelles=False, use_heading_buttons=False))
        assert items[0].anchor_id == "content-0"
        assert "Answer for" in items[0].content_html

    def test_reordering_preserves_semantic_display_names(self):
        reordered = [MIDDLE_QUESTIONS[-1], *MIDDLE_QUESTIONS[1:-1], MIDDLE_QUESTIONS[0]]
        documents = _select_a_und_b(extract_faq_items(_make_full_faq_html(middle_questions=reordered)))
        assert documents[0].display_name == "FAQ Krankheit, Reha, Erwerbsminderung"
        assert documents[-1].display_name == "FAQ Rentenbeginn"

    def test_new_category_uses_source_heading_and_removal_reduces_output(self):
        new_heading = "Was passiert bei einem Umzug innerhalb Deutschlands?"
        expanded = _select_a_und_b(
            extract_faq_items(_make_full_faq_html(middle_questions=[*MIDDLE_QUESTIONS, new_heading]))
        )
        reduced = _select_a_und_b(extract_faq_items(_make_full_faq_html(middle_questions=MIDDLE_QUESTIONS[:-1])))
        assert len(expanded) == 11
        assert expanded[-1].display_name == new_heading
        assert len(reduced) == 9

    @pytest.mark.parametrize(
        ("questions", "message"),
        [
            (["Aktuelles", "Ihre Frage war nicht dabei?"], "at least one"),
            (["Aktuelles", *MIDDLE_QUESTIONS], "contact"),
            (["Aktuelles", "Aktuelles neu", *MIDDLE_QUESTIONS, "Ihre Frage war nicht dabei?"], "Aktuelles"),
            (
                ["Aktuelles", *MIDDLE_QUESTIONS, "Ihre Frage war nicht dabei?", "Ihre Frage war nicht dabei? Neu"],
                "contact",
            ),
            ([MIDDLE_QUESTIONS[0], "Aktuelles", *MIDDLE_QUESTIONS[1:], "Ihre Frage war nicht dabei?"], "first"),
            (["Aktuelles", "Ihre Frage war nicht dabei?", *MIDDLE_QUESTIONS], "last"),
        ],
    )
    def test_invalid_boundaries_fail_closed(self, questions, message):
        html = _make_arbitrary_faq(questions)
        with pytest.raises(ValueError, match=message):
            _select_a_und_b(extract_faq_items(html))

    def test_missing_and_duplicate_document_anchors_fail_closed(self):
        missing = ["boundary-current", None, *[f"a-{index}" for index in range(2, 11)], "boundary-contact"]
        with pytest.raises(ValueError, match="no anchor"):
            _select_a_und_b(extract_faq_items(_make_full_faq_html(anchors=missing)))

        duplicate: list[str | None] = [f"a-{index}" for index in range(12)]
        duplicate[2] = duplicate[1]
        with pytest.raises(ValueError, match="Duplicate FAQ anchor"):
            _select_a_und_b(extract_faq_items(_make_full_faq_html(anchors=duplicate)))

    def test_normalized_identity_handles_case_whitespace_and_umlauts(self):
        assert normalize_heading_identity("  ICH bin SELBSTSTÄNDIG — Test ") == "ich bin selbststandig test"


class TestContactBoundaryMode:
    """#987: contact boundary is ``required`` for A-und-B and ``optional`` per opt-in stem."""

    def test_modes_by_stem_and_strict_default(self):
        assert contact_boundary_mode(A_UND_B) == CONTACT_REQUIRED
        assert contact_boundary_mode(PFLEGEVERSICHERUNG) == CONTACT_OPTIONAL
        assert contact_boundary_mode("faq-unknown") == CONTACT_REQUIRED

    @pytest.mark.parametrize("stem", STEP_2_STEMS)
    def test_step_2_stems_are_optional(self, stem):
        """#1002: every new FAQ source opts into ``optional``."""
        assert contact_boundary_mode(stem) == CONTACT_OPTIONAL

    @pytest.mark.parametrize("stem", [A_UND_B, "faq-unknown"])
    def test_required_mode_rejects_missing_contact(self, stem):
        html = _make_arbitrary_faq(MIDDLE_QUESTIONS)
        with pytest.raises(ValueError, match="exactly one contact"):
            select_document_faq_items(extract_faq_items(html), source_stem=stem)

    def test_optional_mode_without_contact_keeps_every_item(self):
        html = _make_arbitrary_faq(MIDDLE_QUESTIONS)
        documents = select_document_faq_items(extract_faq_items(html), source_stem=PFLEGEVERSICHERUNG)
        assert [document.question for document in documents] == MIDDLE_QUESTIONS

    def test_optional_mode_excludes_final_contact_and_leading_aktuelles(self):
        html = _make_full_faq_html()
        optional = select_document_faq_items(extract_faq_items(html), source_stem=PFLEGEVERSICHERUNG)
        assert optional == _select_a_und_b(extract_faq_items(html))
        assert len(optional) == 10

    @pytest.mark.parametrize(
        ("questions", "message"),
        [
            ([*MIDDLE_QUESTIONS[:2], "Ihre Frage war nicht dabei?", *MIDDLE_QUESTIONS[2:]], "last"),
            ([*MIDDLE_QUESTIONS, "Ihre Frage war nicht dabei?", "Ihre Frage war nicht dabei? Neu"], "at most one"),
            ([MIDDLE_QUESTIONS[0], "Aktuelles", *MIDDLE_QUESTIONS[1:]], "first"),
            (["Ihre Frage war nicht dabei?"], "at least one"),
        ],
    )
    def test_optional_mode_still_fails_closed_on_misplaced_boundaries(self, questions, message):
        html = _make_arbitrary_faq(questions)
        with pytest.raises(ValueError, match=message):
            select_document_faq_items(extract_faq_items(html), source_stem=PFLEGEVERSICHERUNG)

    def test_adding_final_contact_keeps_optional_hash(self):
        without_contact = _make_full_faq_html(include_aktuelles=False).replace(
            '<h2 class="c-accordion__heading"><button aria-controls="content-10">'
            "Ihre Frage war nicht dabei? Kontaktieren Sie uns!</button></h2>"
            '<div class="c-accordion__content" id="content-10"><p>Contact us</p></div>',
            "",
        )
        with_contact = _make_full_faq_html(include_aktuelles=False)
        assert without_contact != with_contact
        assert semantic_faq_hash(without_contact, source_stem=PFLEGEVERSICHERUNG) == semantic_faq_hash(
            with_contact, source_stem=PFLEGEVERSICHERUNG
        )


ACTIVE_A_UND_B_FIXTURE = Path(__file__).parent / "fixtures" / "faq-a-und-b.html.gz"
ACTIVE_A_UND_B_PAGE_HASH = "1a45018dac265cf4afbbf21d1a354e71dd8aa9dd9aa48f91881cf902df02fc9f"
ACTIVE_A_UND_B_ARTIFACT_SHA256 = "4a4b2f3ced9437561c58bf026c6d7ee3eeef831825f91c957865b40a29ad1d38"


class TestActiveAUndBArtifact:
    """Regression proof for #987: the active A-und-B artifact is unchanged in ``required`` mode.

    Fixture is ``releases/faq/sha256-<ACTIVE_A_UND_B_PAGE_HASH>/html/faq-a-und-b.html``, gzipped so
    pre-commit text hooks cannot rewrite its bytes. The hash equals
    ``/dev/renate/faq-artifact-content-hash`` at the time of #987.
    """

    def test_selects_eleven_documents_and_matches_active_page_hash(self):
        html = gzip.decompress(ACTIVE_A_UND_B_FIXTURE.read_bytes())
        # Byte identity with the published artifact (manifest.artifact_sha256).
        assert hashlib.sha256(html).hexdigest() == ACTIVE_A_UND_B_ARTIFACT_SHA256
        assert len(_select_a_und_b(extract_faq_items(html))) == 11
        assert _hash_a_und_b(html) == ACTIVE_A_UND_B_PAGE_HASH
        assert _hash_a_und_b(strip_page_chrome(html)) == ACTIVE_A_UND_B_PAGE_HASH
        assert len(generated_faq_documents(html, A_UND_B)) == 11


def _make_arbitrary_faq(questions: list[str]) -> str:
    items = "".join(
        f'<h2 class="c-accordion__heading"><button aria-controls="a-{index}">{question}</button></h2>'
        f'<div class="c-accordion__content"><p>Answer {index}</p></div>'
        for index, question in enumerate(questions)
    )
    return f'<html><body><div class="c-accordion">{items}</div></body></html>'


class TestSemanticHashAndManifestDocuments:
    def test_hash_is_deterministic_canonical_sha256(self):
        raw = _make_full_faq_html()
        content_hash = _hash_a_und_b(raw)
        assert len(content_hash) == 64
        assert content_hash == _hash_a_und_b(strip_page_chrome(raw))

    def test_boundary_content_and_publish_date_are_excluded(self):
        first = _make_full_faq_html(aktuelles_content="Old", contact_content="Phone", publish_date="2024-01-01")
        second = _make_full_faq_html(aktuelles_content="New", contact_content="Email", publish_date="2025-01-01")
        assert _hash_a_und_b(first) == _hash_a_und_b(second)

    def test_first_item_is_hashed_when_aktuelles_is_absent(self):
        original = _make_full_faq_html(include_aktuelles=False)
        changed = original.replace(f"Answer for: {MIDDLE_QUESTIONS[0]}", "Changed first answer")
        assert _hash_a_und_b(original) != _hash_a_und_b(changed)

    def test_selected_content_and_order_change_hash(self):
        original = _make_full_faq_html()
        changed = original.replace("Answer for: Ich bin krank", "Changed answer")
        reordered = _make_full_faq_html(middle_questions=list(reversed(MIDDLE_QUESTIONS)))
        assert _hash_a_und_b(original) != _hash_a_und_b(changed)
        assert _hash_a_und_b(original) != _hash_a_und_b(reordered)

    def test_json_fields_make_delimiter_content_unambiguous(self):
        first = _make_full_faq_html(middle_questions=["Question: A"], answer_overrides={1: "B:C"})
        second = _make_full_faq_html(middle_questions=["Question"], answer_overrides={1: "A:B:C"})
        assert _hash_a_und_b(first) != _hash_a_und_b(second)

    def test_generated_documents_are_complete_and_ordered(self):
        documents = generated_faq_documents(_make_full_faq_html(), "faq-a-und-b")
        assert documents[0] == {
            "item_name": "faq-a-und-b/faq-a-und-b_0000",
            "display_name": "FAQ Rentenbeginn",
            "anchor_id": "content-1",
        }
        assert documents[-1]["item_name"] == "faq-a-und-b/faq-a-und-b_0009"

    def test_generated_documents_include_first_item_without_aktuelles(self):
        documents = generated_faq_documents(
            _make_full_faq_html(
                middle_questions=[CURRENT_FIRST_QUESTION, *MIDDLE_QUESTIONS],
                include_aktuelles=False,
                use_heading_buttons=False,
            ),
            "faq-a-und-b",
        )
        assert len(documents) == 11
        assert documents[0] == {
            "item_name": "faq-a-und-b/faq-a-und-b_0000",
            "display_name": "FAQ Rentenbeginn",
            "anchor_id": "content-0",
        }
        assert documents[-1]["item_name"] == "faq-a-und-b/faq-a-und-b_0010"


class TestExtractPublishDate:
    def test_extracts_or_omits_date(self):
        assert extract_publish_date(_make_full_faq_html(publish_date="2024-06-15")) == "2024-06-15"
        assert extract_publish_date("<html><head></head></html>") is None


class TestStructuralIdempotency:
    @pytest.fixture
    def transform(self):
        from etl.transform.filter_html import prepare_faq_html

        with patch(
            "etl.transform.filter_html.load_brochure_url_mapping",
            return_value={"faq-a-und-b.md": "https://example.com/faq"},
        ):
            yield prepare_faq_html()

    @staticmethod
    def _make_item(html_data: str | bytes):
        from etl.models import DataObject, DataType, PipelineItem

        return PipelineItem(
            name="faq-a-und-b.html",
            data_object=DataObject(name="faq-a-und-b.html", data=html_data, data_type=DataType.HTML, metadata={}),
        )

    def test_raw_and_stripped_generate_byte_identical_documents(self, transform):
        raw = _make_full_faq_html()
        stripped = strip_page_chrome(raw)
        raw_documents = transform.apply(self._make_item(raw))
        stripped_documents = transform.apply(self._make_item(stripped))

        assert len(raw_documents) == len(stripped_documents) == 10
        for raw_document, stripped_document in zip(raw_documents, stripped_documents, strict=True):
            assert raw_document.name == stripped_document.name
            assert raw_document.data_object.metadata == stripped_document.data_object.metadata
            assert raw_document.data_object.data == stripped_document.data_object.data

    def test_raw_and_stripped_without_aktuelles_generate_byte_identical_documents(self, transform):
        raw = _make_full_faq_html(
            middle_questions=[CURRENT_FIRST_QUESTION, *MIDDLE_QUESTIONS],
            include_aktuelles=False,
            use_heading_buttons=False,
        )
        stripped = strip_page_chrome(raw)
        raw_documents = transform.apply(self._make_item(raw))
        stripped_documents = transform.apply(self._make_item(stripped))

        assert len(raw_documents) == len(stripped_documents) == 11
        for raw_document, stripped_document in zip(raw_documents, stripped_documents, strict=True):
            assert raw_document.name == stripped_document.name
            assert raw_document.data_object.metadata == stripped_document.data_object.metadata
            assert raw_document.data_object.data == stripped_document.data_object.data


class TestFaqMetadataContract:
    @staticmethod
    def _document() -> FaqDocument:
        return FaqDocument(
            question="Wann kann ich in Rente gehen?",
            anchor_id="content-1",
            content_html="<p>Antwort</p>",
            display_name="FAQ Rentenbeginn",
        )

    def test_builder_yields_all_seven_canonical_keys(self):
        metadata = build_faq_metadata(
            self._document(),
            brochure_number="faq-a-und-b",
            brochure_url_base="https://drv.de/faq-a-und-b.html",
        )
        assert metadata == {
            "chunk_type": "faq",
            "category": "FAQ",
            "name": "FAQ Rentenbeginn",
            "section_title": "Wann kann ich in Rente gehen?",
            "title": "FAQ — Wann kann ich in Rente gehen?",
            "brochure_number": "faq-a-und-b",
            "brochure_url": "https://drv.de/faq-a-und-b.html#content-1",
        }
        assert set(metadata) == set(REQUIRED_FAQ_METADATA_KEYS)

    def test_builder_omits_url_when_base_is_falsy(self):
        metadata = build_faq_metadata(self._document(), brochure_number="faq-a-und-b", brochure_url_base=None)
        assert "brochure_url" not in metadata
        assert set(metadata) == set(REQUIRED_FAQ_METADATA_KEYS) - {"brochure_url"}

    def test_validate_accepts_complete_metadata(self):
        validate_faq_metadata(
            build_faq_metadata(
                self._document(),
                brochure_number="faq-a-und-b",
                brochure_url_base="https://drv.de/faq-a-und-b.html",
            )
        )

    @pytest.mark.parametrize("missing_key", sorted(REQUIRED_FAQ_METADATA_KEYS))
    def test_validate_raises_on_each_missing_key(self, missing_key):
        metadata = build_faq_metadata(
            self._document(),
            brochure_number="faq-a-und-b",
            brochure_url_base="https://drv.de/faq-a-und-b.html",
        )
        del metadata[missing_key]
        with pytest.raises(FaqMetadataError, match=missing_key):
            validate_faq_metadata(metadata)

    def test_validate_raises_on_empty_or_whitespace_value(self):
        metadata = build_faq_metadata(
            self._document(),
            brochure_number="faq-a-und-b",
            brochure_url_base="https://drv.de/faq-a-und-b.html",
        )
        metadata["section_title"] = "   "
        with pytest.raises(FaqMetadataError, match="section_title"):
            validate_faq_metadata(metadata)

    def test_validate_treats_none_value_as_missing(self):
        metadata: dict[str, object] = dict(
            build_faq_metadata(
                self._document(),
                brochure_number="faq-a-und-b",
                brochure_url_base="https://drv.de/faq-a-und-b.html",
            )
        )
        metadata["title"] = None
        with pytest.raises(FaqMetadataError, match="title"):
            validate_faq_metadata(metadata)

    def test_validate_generated_passes_for_every_document_with_mapping(self):
        validate_generated_faq_metadata(_make_full_faq_html(), "faq-a-und-b", "https://drv.de/faq-a-und-b.html")

    def test_validate_generated_fails_closed_without_url_base(self):
        with pytest.raises(FaqMetadataError, match="brochure_url"):
            validate_generated_faq_metadata(_make_full_faq_html(), "faq-a-und-b", None)
