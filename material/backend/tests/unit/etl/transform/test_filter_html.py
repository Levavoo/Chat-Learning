import json
from pathlib import Path
from typing import cast
from unittest.mock import patch

import pytest

from etl.models import DataObject, DataType, PipelineItem
from etl.transform.extract_metadata import load_brochure_url_mapping
from etl.transform.faq_normalize import FaqMetadataError
from etl.transform.filter_html import prepare_faq_html

BASE_URL = "https://example.com/faq"
MAPPING = {"faq-a-und-b.md": BASE_URL}


def _make_accordion_html(
    questions: list[str],
    *,
    include_aktuelles: bool = True,
    use_heading_buttons: bool = True,
    with_anchors: bool = True,
    publish_date: str | None = "2024-01-01",
    include_contact: bool = True,
) -> str:
    items = []
    if include_aktuelles:
        items.append(
            '<h2 class="c-accordion__heading"><button aria-controls="boundary-current">Aktuelles</button></h2>'
            '<div class="c-accordion__content" id="boundary-current"><p>News</p></div>'
        )
    for i, q in enumerate(questions):
        anchor_attr = f'aria-controls="content-{i}"' if with_anchors else ""
        content_div_id = f'id="content-{i}"' if with_anchors else ""
        heading = (
            f'<h2 class="c-accordion__heading"><button {anchor_attr}>{q}</button></h2>'
            if use_heading_buttons
            else f'<h2 class="c-accordion__heading">{q}</h2>'
        )
        items.append(
            f"""
            {heading}
            <div class="c-accordion__content" {content_div_id}>
                <p>Answer for: {q}</p>
            </div>
            """
        )

    if include_contact:
        items.append(
            '<h2 class="c-accordion__heading"><button aria-controls="boundary-contact">'
            "Ihre Frage war nicht dabei?</button></h2>"
            '<div class="c-accordion__content" id="boundary-contact"><p>Contact</p></div>'
        )

    date_meta = f'<meta name="dc.date" content="{publish_date}">' if publish_date else ""
    return f"""<!DOCTYPE html>
<html>
<head>{date_meta}</head>
<body>
<div class="c-accordion">
    {"".join(items)}
</div>
</body>
</html>"""


def _make_item(html: str | bytes, name: str = "faq-a-und-b.html") -> PipelineItem:
    return PipelineItem(
        name=name,
        data_object=DataObject(name=name, data=html, data_type=DataType.HTML, metadata={}),
    )


@pytest.fixture
def transform():
    with patch("etl.transform.filter_html.load_brochure_url_mapping", return_value=MAPPING):
        yield prepare_faq_html()


@pytest.fixture
def twelve_question_html():
    return _make_accordion_html([f"Frage {i}" for i in range(13)])


class TestFanOut:
    def test_returns_one_item_per_question(self, transform, twelve_question_html):
        result = transform.apply(_make_item(twelve_question_html))
        assert len(result) == 13

    def test_each_item_is_pipeline_item(self, transform, twelve_question_html):
        result = transform.apply(_make_item(twelve_question_html))
        assert all(isinstance(r, PipelineItem) for r in result)

    def test_output_type_is_html(self, transform, twelve_question_html):
        result = transform.apply(_make_item(twelve_question_html))
        assert all(r.data_object.data_type == DataType.HTML for r in result)

    def test_bytes_input_decoded_correctly(self, transform, twelve_question_html):
        item = _make_item(twelve_question_html.encode("UTF-8"))
        result = transform.apply(item)
        assert len(result) == 13


class TestNaming:
    def test_chunk_name_pattern(self, transform, twelve_question_html):
        result = transform.apply(_make_item(twelve_question_html))
        for i, r in enumerate(result):
            assert r.name == f"faq-a-und-b/faq-a-und-b_{i:04d}"

    def test_unknown_category_uses_source_heading_as_display_name(self, transform, twelve_question_html):
        result = transform.apply(_make_item(twelve_question_html))
        for i, r in enumerate(result):
            assert r.data_object.metadata["name"] == f"Frage {i}"

    def test_brochure_number_set_to_base_name(self, transform, twelve_question_html):
        result = transform.apply(_make_item(twelve_question_html))
        for r in result:
            assert r.data_object.metadata["brochure_number"] == "faq-a-und-b"

    def test_no_name_collision(self, transform, twelve_question_html):
        result = transform.apply(_make_item(twelve_question_html))
        names = [r.name for r in result]
        assert len(names) == len(set(names))

    def test_faq_display_names_with_aktuelles_boundary(self, transform):
        questions = [
            "Wann kann ich in Rente gehen und was muss ich beachten?",
            "Gibt es Möglichkeiten, zusätzlich Geld für die Rente anzusparen?",
            "Wie beantrage ich meine Rente?",
            "Wer kann mir weiterhelfen bei Fragen?",
            "Ich habe meine Rentenzahlung nicht erhalten, was soll ich tun?",
            "Wird mein Einkommen auf meine Rente angerechnet?",
            "Welche Auswirkung hat es auf die gesetzliche Rentenversicherung wenn ich auswandere?",
            "Wie bekomme ich meine Renteninformation?",
            "Ich bin selbstständig — bin ich versicherungspflichtig?",
            "Ich bin krank — was nun?",
        ]
        html = _make_accordion_html(questions)
        result = transform.apply(_make_item(html))
        assert len(result) == 10  # boundaries skipped
        assert result[0].data_object.metadata["name"] == "FAQ Rentenbeginn"
        assert result[1].data_object.metadata["name"] == "FAQ Einzahlungen"
        assert result[9].data_object.metadata["name"] == "FAQ Krankheit, Reha, Erwerbsminderung"

    def test_first_item_is_document_when_aktuelles_is_absent(self, transform):
        questions = [
            "Wie ändert sich die Auszahlung des Zuschlags für Erwerbsminderungsrenten?",
            "Wann kann ich in Rente gehen und was muss ich beachten?",
        ]
        html = _make_accordion_html(
            questions,
            include_aktuelles=False,
            use_heading_buttons=False,
        )
        result = transform.apply(_make_item(html))
        assert len(result) == 2
        assert result[0].data_object.metadata["name"] == "FAQ Rentenbeginn"
        assert result[0].data_object.metadata["brochure_url"] == f"{BASE_URL}#content-0"


class TestContactBoundaryModeByStem:
    """#987: the item stem selects the contact-boundary mode."""

    PFLEGE_URL = (
        "https://www.deutsche-rentenversicherung.de/SharedDocs/FAQ/Pflegeversicherung/"
        "beitragsstaffelung/faq-liste-beitragsstaffelung-pflegeversicherung"
    )

    def test_optional_stem_without_contact_keeps_every_item_with_real_mapping(self):
        transform = prepare_faq_html()  # real brochure_urls.yaml
        html = _make_accordion_html(["Frage Alpha", "Frage Beta"], include_aktuelles=False, include_contact=False)
        result = transform.apply(_make_item(html, name="faq-pflegeversicherung.html"))
        assert [r.name for r in result] == [
            "faq-pflegeversicherung/faq-pflegeversicherung_0000",
            "faq-pflegeversicherung/faq-pflegeversicherung_0001",
        ]
        assert result[0].data_object.metadata["brochure_number"] == "faq-pflegeversicherung"
        assert result[1].data_object.metadata["brochure_url"] == f"{self.PFLEGE_URL}#content-1"

    def test_required_stem_without_contact_fails_closed(self, transform):
        html = _make_accordion_html(["Frage Alpha"], include_contact=False)
        with pytest.raises(ValueError, match="exactly one contact"):
            transform.apply(_make_item(html))


DRV_HOST = "https://www.deutsche-rentenversicherung.de"
FAQ_SOURCE_PATHS = {
    "faq-a-und-b": "/SharedDocs/FAQ/A-und-B/faq-a-und-b.html",
    "faq-pflegeversicherung": (
        "/SharedDocs/FAQ/Pflegeversicherung/beitragsstaffelung/faq-liste-beitragsstaffelung-pflegeversicherung"
    ),
    "faq-fruehstartrente": "/SharedDocs/FAQ/fruehstartrente/fruehstartrente_liste",
    "faq-rentenanpassung-2026": (
        "/SharedDocs/FAQ/Gesetzesaenderungen/Rentenanpassung/FAQ-Rentenanpassung-2026/Rentenanpassung-2026"
    ),
    "faq-a1-bescheinigung": "/SharedDocs/FAQ/a1_bescheinigung/a1_bescheinigung_faq_liste",
    "faq-rentenanspruch-international": (
        "/DRV/DE/Rente/Allgemeine-Informationen/Wissenswertes-zur-Rente/FAQs/International/Rentenanspruch"
    ),
}
STEP_2_STEMS = (
    "faq-fruehstartrente",
    "faq-rentenanpassung-2026",
    "faq-a1-bescheinigung",
    "faq-rentenanspruch-international",
)
PRIORITIES_PATH = Path(__file__).parents[4] / "data" / "brochure_priorities.json"


class TestFaqSourceConfiguration:
    """#1002: every FAQ source has a URL mapping and an A-tier ranking entry."""

    @pytest.mark.parametrize(("stem", "path"), FAQ_SOURCE_PATHS.items())
    def test_url_mapping_present(self, stem, path):
        assert load_brochure_url_mapping()[f"{stem}.md"] == f"{DRV_HOST}{path}"

    @pytest.mark.parametrize("stem", STEP_2_STEMS)
    def test_new_stem_without_contact_fans_out_with_real_mapping(self, stem):
        transform = prepare_faq_html()  # real brochure_urls.yaml
        html = _make_accordion_html(["Frage Alpha", "Frage Beta"], include_aktuelles=False, include_contact=False)
        result = transform.apply(_make_item(html, name=f"{stem}.html"))
        assert [r.name for r in result] == [f"{stem}/{stem}_0000", f"{stem}/{stem}_0001"]
        assert result[0].data_object.metadata["brochure_number"] == stem
        assert result[1].data_object.metadata["brochure_url"] == f"{DRV_HOST}{FAQ_SOURCE_PATHS[stem]}#content-1"

    @pytest.mark.parametrize("stem", FAQ_SOURCE_PATHS)
    def test_priority_entry_matches_a_und_b(self, stem):
        entries = {e["name"]: e for e in json.loads(PRIORITIES_PATH.read_text(encoding="utf-8"))}
        assert entries[stem]["prio"] == "A"
        assert entries[stem]["domain"] == "Mehrdeutig"
        assert entries[stem]["authority_boost"] == 1.15


class TestContent:
    def test_each_chunk_contains_only_its_question(self, transform):
        html = _make_accordion_html(["Frage Alpha", "Frage Beta", "Frage Gamma"])
        result = transform.apply(_make_item(html))
        assert "<h1>Frage Alpha</h1>" in result[0].data_object.data
        assert "Frage Beta" not in result[0].data_object.data
        assert "<h1>Frage Beta</h1>" in result[1].data_object.data
        assert "Frage Alpha" not in result[1].data_object.data

    def test_answer_content_preserved(self, transform):
        html = _make_accordion_html(["Frage Alpha"])
        result = transform.apply(_make_item(html))
        assert "Answer for: Frage Alpha" in result[0].data_object.data

    def test_publish_date_in_each_chunk(self, transform):
        html = _make_accordion_html(["Frage Alpha"], publish_date="2024-06-15")
        result = transform.apply(_make_item(html))
        assert "2024-06-15" in result[0].data_object.data

    def test_no_publish_date_when_absent(self, transform):
        html = _make_accordion_html(["Frage Alpha"], publish_date=None)
        result = transform.apply(_make_item(html))
        assert "date_of_publish" not in result[0].data_object.data

    def test_publish_date_in_head_not_body(self, transform):
        html = _make_accordion_html(["Frage Alpha"], publish_date="2024-06-15")
        output = transform.apply(_make_item(html))[0].data_object.data
        head_end = output.index("</head>")
        body_start = output.index("<body>")
        assert "date_of_publish" in output[:head_end]
        assert "date_of_publish" not in output[body_start:]

    def test_html_special_chars_in_question_are_escaped(self, transform):
        # Use & and > — < becomes a parsed tag in BS4 and is stripped from get_text()
        html = _make_accordion_html(["Vor- & Nachteile > Beispiel"])
        result = transform.apply(_make_item(html))
        data = result[0].data_object.data
        assert "&amp;" in data
        assert "&gt;" in data

    def test_question_without_answer_fails_closed(self, transform):
        html = """<!DOCTYPE html>
<html><body><div class="c-accordion">
    <h2 class="c-accordion__heading"><button aria-controls="current">Aktuelles</button></h2>
    <div class="c-accordion__content" id="current"><p>News</p></div>
    <h2 class="c-accordion__heading"><button aria-controls="missing">Frage ohne Antwort</button></h2>
    <h2 class="c-accordion__heading"><button aria-controls="contact">Ihre Frage war nicht dabei?</button></h2>
    <div class="c-accordion__content" id="contact"><p>Contact</p></div>
</div></body></html>"""
        with pytest.raises(ValueError, match="empty answer"):
            transform.apply(_make_item(html))


class TestURL:
    def test_brochure_url_with_anchor(self, transform):
        html = _make_accordion_html(["Frage Alpha"], with_anchors=True)
        result = transform.apply(_make_item(html))
        assert result[0].data_object.metadata["brochure_url"] == f"{BASE_URL}#content-0"

    def test_missing_anchor_fails_closed(self, transform):
        html = _make_accordion_html(["Frage Alpha"], with_anchors=False)
        with pytest.raises(ValueError, match="no anchor"):
            transform.apply(_make_item(html))

    def test_missing_url_mapping_fails_closed(self):
        with patch("etl.transform.filter_html.load_brochure_url_mapping", return_value={}):
            t = prepare_faq_html()
        html = _make_accordion_html(["Frage Alpha"])
        with pytest.raises(FaqMetadataError, match="brochure_url"):
            t.apply(_make_item(html))

    def test_anchor_ids_are_unique_per_chunk(self, transform):
        html = _make_accordion_html(["Q0", "Q1", "Q2"])
        result = transform.apply(_make_item(html))
        urls = [r.data_object.metadata["brochure_url"] for r in result]
        assert urls[0].endswith("#content-0")
        assert urls[1].endswith("#content-1")
        assert urls[2].endswith("#content-2")


class TestEdgeCases:
    def test_empty_accordion_fails_closed(self, transform):
        html = '<html><body><div class="c-accordion"></div></body></html>'
        with pytest.raises(ValueError, match="No FAQ accordion items"):
            transform.apply(_make_item(html))

    def test_no_accordion_fails_closed(self, transform):
        html = "<html><body><p>No FAQs here.</p></body></html>"
        with pytest.raises(ValueError, match="No FAQ accordion items"):
            transform.apply(_make_item(html))

    def test_unsupported_data_type_raises(self, transform):
        item = _make_item("irrelevant")
        item.data_object.data = cast(str, 12345)
        with pytest.raises(TypeError):
            transform.apply(item)


class TestCanonicalSidecarMetadata:
    def test_sidecar_contains_full_canonical_metadata(self, transform):
        html = _make_accordion_html(["Wann kann ich in Rente gehen und was muss ich beachten?"])
        result = transform.apply(_make_item(html))
        assert result[0].data_object.metadata == {
            "chunk_type": "faq",
            "category": "FAQ",
            "name": "FAQ Rentenbeginn",
            "section_title": "Wann kann ich in Rente gehen und was muss ich beachten?",
            "title": "FAQ — Wann kann ich in Rente gehen und was muss ich beachten?",
            "brochure_number": "faq-a-und-b",
            "brochure_url": f"{BASE_URL}#content-0",
        }

    def test_every_chunk_carries_chunk_type_and_category(self, transform):
        html = _make_accordion_html(["Frage Alpha", "Frage Beta", "Frage Gamma"])
        result = transform.apply(_make_item(html))
        for chunk in result:
            assert chunk.data_object.metadata["chunk_type"] == "faq"
            assert chunk.data_object.metadata["category"] == "FAQ"
