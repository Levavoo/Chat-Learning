import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))

import chunking_eval


def test_load_documents_reads_utf8_regardless_of_locale(tmp_path, monkeypatch):
    """Regression: open(f) used the OS codepage (cp1252 on Windows) and raised
    UnicodeDecodeError on UTF-8 docs with German umlauts before embedding."""
    docs_dir = tmp_path / "documents"
    docs_dir.mkdir()
    payload = {"doc_id": "R0101", "title": "Märkblatt über Rentenansprüche — €uro"}
    (docs_dir / "R0101.json").write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    monkeypatch.setattr(chunking_eval, "DOCS_DIR", docs_dir)

    docs = chunking_eval.load_documents()

    assert len(docs) == 1
    assert docs[0]["title"] == "Märkblatt über Rentenansprüche — €uro"
