
import pytest

from etl.transform.custom_chunking import Chunk, CustomChunker


@pytest.fixture
def chunker():
    return CustomChunker()


def test_hierarchical_div_chunking(chunker):
    markdown = """## Section 1
Intro text.

### Subsection A
Content A.

### Subsection B
Content B.

### Subsection C
Content C.
"""
    metadata = {"brochure_number": "B01", "category": "Rehab"}
    chunks = chunker.chunk(markdown, metadata)

    # Expect 3 chunks (one for each subsection)
    assert len(chunks) == 3
    assert chunks[0].metadata["subsection_title"] == "Subsection A"
    assert chunks[0].metadata["div_index"] == 0
    assert chunks[2].metadata["subsection_title"] == "Subsection C"


def test_glossary_chunking(chunker):
    # Note: Logic expects double newlines between paragraphs
    markdown = """## Glossary

Term1

Definition for Term1.

Term2

Definition for Term2.

**Unser Tipp**: Note inside.
"""
    metadata = {"brochure_number": "B37"}
    chunks = chunker.chunk(markdown, metadata)

    assert len(chunks) == 2
    assert chunks[0].metadata["glossary_term"] == "Term1"
    assert chunks[1].metadata["glossary_term"] == "Term2"
    assert chunks[1].metadata["has_note"] is True
    assert "tip" in chunks[1].metadata["note_types"]


def test_flat_section_chunking(chunker):
    long_content = "A" * 2800
    markdown = f"## Flat Section\n{long_content}"

    metadata = {"brochure_number": "B38"}
    chunks = chunker.chunk(markdown, metadata)

    assert len(chunks) == 1
    assert chunks[0].metadata["chunk_type"] == "flat_section_split"
    assert "A" * 2800 in chunks[0].content


def test_metadata_enrichment(chunker):
    markdown = """
### Section with Table
| Col1 | Col2 |
|---|---|
| Val1 | Val2 |

**Bitte beachten Sie**: Important warning.
"""
    chunk = Chunk(content=markdown, metadata={})
    chunker._enrich_metadata(chunk)

    assert chunk.metadata["has_table"] is True
    assert chunk.metadata["has_note"] is True
    assert "important" in chunk.metadata["note_types"]
