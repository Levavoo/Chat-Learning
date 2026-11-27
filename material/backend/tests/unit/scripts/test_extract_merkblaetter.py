import hashlib

from scripts import extract_merkblaetter


def _layout_block(block_id: str, block_type: str, line_id: str) -> dict:
    return {
        "Id": block_id,
        "BlockType": block_type,
        "Relationships": [{"Type": "CHILD", "Ids": [line_id]}],
    }


def _line(block_id: str, text: str) -> dict:
    return {"Id": block_id, "BlockType": "LINE", "Text": text}


def test_later_layout_titles_become_sections_instead_of_replacing_document_title():
    blocks = [
        _layout_block("cover-title", "LAYOUT_TITLE", "cover-line"),
        _line("cover-line", "Erläuterungen zum Antrag auf Versichertenrente"),
        _layout_block("intro", "LAYOUT_TEXT", "intro-line"),
        _line("intro-line", "Einleitender Inhalt."),
        _layout_block("page-title", "LAYOUT_TITLE", "page-title-line"),
        _line("page-title-line", "Altersrente für langjährig Versicherte"),
        _layout_block("page-text", "LAYOUT_TEXT", "page-text-line"),
        _line("page-text-line", "Inhalt der Altersrente."),
        _layout_block("appendix-title", "LAYOUT_TITLE", "appendix-title-line"),
        _line("appendix-title-line", "Erläuterungen zur Anlage R0210"),
        _layout_block("appendix-text", "LAYOUT_TEXT", "appendix-text-line"),
        _line("appendix-text-line", "Inhalt der Anlage."),
    ]

    doc = extract_merkblaetter.process_blocks(blocks)

    assert doc["title"] == "Erläuterungen zum Antrag auf Versichertenrente"
    assert doc["sections"] == [
        {"title": "", "content": "Einleitender Inhalt."},
        {"title": "Altersrente für langjährig Versicherte", "content": "Inhalt der Altersrente."},
        {"title": "Erläuterungen zur Anlage R0210", "content": "Inhalt der Anlage."},
    ]


def test_repeated_document_title_does_not_split_a_section():
    blocks = [
        _layout_block("cover-title", "LAYOUT_TITLE", "cover-line"),
        _line("cover-line", "Merkblatt"),
        _layout_block("first", "LAYOUT_TEXT", "first-line"),
        _line("first-line", "Erster Absatz."),
        _layout_block("repeated-title", "LAYOUT_TITLE", "repeated-line"),
        _line("repeated-line", "Merkblatt"),
        _layout_block("second", "LAYOUT_TEXT", "second-line"),
        _line("second-line", "Zweiter Absatz."),
    ]

    doc = extract_merkblaetter.process_blocks(blocks)

    assert doc["sections"] == [{"title": "", "content": "Erster Absatz.\nZweiter Absatz."}]


def test_repairs_high_confidence_ocr_differences_from_embedded_pdf_text(monkeypatch, tmp_path):
    doc = {
        "title": "Erläuterungen zum Antrag auf Versichertenrente",
        "sections": [
            {
                "title": "14 Erklärung der Antragstellerin I des Antragstellers",
                "content": (
                    "Zeiten des Bezugs von Arbeitslosengeld Il zählen nicht mit.\n"
                    "Die Minderung Ihrer Erwerbsfähigkeit beträgt weniger als %."
                ),
            }
        ],
    }
    candidates = [
        "Erläuterungen zum Antrag auf Versichertenrente",
        "14 Erklärung der Antragstellerin / des Antragstellers",
        "Zeiten des Bezugs von Arbeitslosengeld II zählen nicht mit.",
        "Die Minderung Ihrer Erwerbsfähigkeit beträgt weniger als 40 %.",
    ]
    monkeypatch.setattr(extract_merkblaetter, "_pdf_paragraphs", lambda _path: candidates)

    repairs = extract_merkblaetter.repair_ocr_from_pdf(doc, tmp_path / "R0101.pdf")

    assert repairs == 3
    assert doc["sections"][0] == {
        "title": "14 Erklärung der Antragstellerin / des Antragstellers",
        "content": (
            "Zeiten des Bezugs von Arbeitslosengeld II zählen nicht mit.\n"
            "Die Minderung Ihrer Erwerbsfähigkeit beträgt weniger als 40 %."
        ),
    }


def test_does_not_replace_substantively_different_text(monkeypatch, tmp_path):
    doc = {
        "title": "Merkblatt",
        "sections": [{"title": "Rente", "content": "Diese Regel gilt für fünf Versicherungsjahre."}],
    }
    monkeypatch.setattr(
        extract_merkblaetter,
        "_pdf_paragraphs",
        lambda _path: ["Diese neue Regel gilt für zehn Versicherungsjahre und weitere Sonderfälle."],
    )

    repairs = extract_merkblaetter.repair_ocr_from_pdf(doc, tmp_path / "R0101.pdf")

    assert repairs == 0
    assert doc["sections"][0]["content"] == "Diese Regel gilt für fünf Versicherungsjahre."


def test_repairs_case_punctuation_and_slash_ocr_errors():
    candidates = [
        "Den gewöhnlichen Aufenthalt hat eine Person dort, wo sie dauerhaft verweilt.",
        "Bitte nennen Sie zum Beispiel die Pensionsregelungsbehörde. Die Angaben sind erforderlich.",
        "bei leiblichen Kindern / Adoptivkindern",
    ]

    assert extract_merkblaetter._repair_text_from_candidates(
        "Den gewöhnlichen Aufenthalt hat eine Person dort, WO sie dauerhaft verweilt.", candidates
    ).endswith("dort, wo sie dauerhaft verweilt.")
    assert "Pensionsregelungsbehörde. Die Angaben" in extract_merkblaetter._repair_text_from_candidates(
        "Bitte nennen Sie zum Beispiel die Pensionsregelungsbehörde Die Angaben sind erforderlich.", candidates
    )
    assert (
        extract_merkblaetter._repair_text_from_candidates("bei leiblichen Kindern I Adoptivkindern", candidates)
        == "bei leiblichen Kindern / Adoptivkindern"
    )


def test_restores_a_pdf_list_marker_dropped_by_textract():
    source = "selbst nicht in einer gesetzlichen Krankenversicherung pflichtversichert sein"
    candidate = f"- {source}"

    assert extract_merkblaetter._repair_text_from_candidates(source, [candidate], allow_list_marker=True) == candidate


def test_restores_a_list_marker_when_the_same_line_also_has_a_slash_ocr_error():
    source = "bei leiblichen Kindern I Adoptivkindern"
    candidate = "- bei leiblichen Kindern / Adoptivkindern"

    assert extract_merkblaetter._repair_text_from_candidates(source, [candidate], allow_list_marker=True) == candidate


def test_does_not_add_a_pdf_list_marker_to_a_section_title():
    source = "Hilfsmittel und technische Arbeitshilfen"
    candidate = f"- {source}"

    assert extract_merkblaetter._repair_text_from_candidates(source, [candidate]) == source


def test_separates_markdown_list_blocks_from_surrounding_paragraphs():
    lines = ["Einleitung", "- Punkt eins", "- Punkt zwei", "Folgeabsatz"]

    assert extract_merkblaetter._separate_markdown_list_blocks(lines) == [
        "Einleitung",
        "",
        "- Punkt eins",
        "- Punkt zwei",
        "",
        "Folgeabsatz",
    ]


def test_textract_cache_is_bound_to_pdf_content(monkeypatch, tmp_path):
    pdf_path = tmp_path / "R0101.pdf"
    pdf_path.write_bytes(b"first revision")
    expected_hash = hashlib.sha256(pdf_path.read_bytes()).hexdigest()[:16]
    monkeypatch.setattr(extract_merkblaetter, "_run_textract", lambda *_args: [{"Id": "first"}])

    extract_merkblaetter._get_textract_blocks(pdf_path, tmp_path / "cache", "bucket", "region", skip=False)

    assert (tmp_path / "cache" / f"R0101-{expected_hash}.json").exists()
