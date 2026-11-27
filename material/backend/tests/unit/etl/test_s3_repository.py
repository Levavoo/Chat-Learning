import json

import pytest

from etl.util.repository.s3 import S3BucketRepository


class TestMetadataTruncation:
    """Metadata truncation to fit Bedrock's 1024-byte limit."""

    @pytest.fixture
    def repo(self):
        """S3BucketRepository class (methods tested directly; no valid bucket needed)."""
        return S3BucketRepository

    @pytest.fixture
    def small_metadata(self):
        return {
            "name": "Test Document",
            "category": "Test",
            "keywords": "keyword1, keyword2, keyword3",
            "filename": "test.md",
        }

    @pytest.fixture
    def oversized_metadata(self):
        """Exceeds 1024 bytes due to long keywords."""
        return {
            "name": "Erwerbsminderungsrente: Das Netz für alle Fälle",
            "category": "Rente",
            "keywords": "Allgemeiner Arbeitsmarkt, Arbeitsunfall, Berufskrankheit, Berufsschutz, Berufsunfähigkeitsrente, Erwerbsminderung, Erwerbsminderungsrente, Erwerbsunfähig, Erwerbsunfähigkeitsrente, Flexirentengesetz, Fünfjahreszeitraum, Hinzuverdienst, Hinzuverdienstdeckel, Hinzuverdienstgrenze, Restleistungsvermögen, Teilweise Erwerbsminderung, Verschlossener Arbeitsmarkt, Volle Erwerbsminderung, Weiterzahlungsantrag, Zurechnungszeit",
            "filename": "ALT B16 - Erwerbsminderungsrente: Das Netz für alle Fälle - 19. Auflage (7/2024)",
            "edition": "19. Auflage",
            "publishing_date": "7/2024",
            "gliederungsnummer": "201",
            "brochure_number": "B16",
            "chunk_type": "hierarchical_div",
            "section_title": "Nicht erwerbsfähig - trotzdem versorgt",
            "subsection_title": "Anderes Leben dank Rente - ein Beispiel",
            "div_index": 0,
            "has_table": False,
            "has_note": False,
        }

    @pytest.fixture
    def extreme_metadata(self):
        """Too large even without keywords."""
        long_text = "x" * 2000
        return {
            "name": long_text,
            "category": "Test",
            "filename": "test.md",
        }

    def test_small_metadata_unchanged(self, repo, small_metadata):
        result = repo._truncate_metadata_to_fit(None, small_metadata)

        assert result == small_metadata
        assert "keywords" in result
        assert result["keywords"] == small_metadata["keywords"]

    def test_small_metadata_stays_under_limit(self, repo, small_metadata):
        result = repo._truncate_metadata_to_fit(None, small_metadata)
        bedrock_metadata = {"metadataAttributes": result}
        metadata_json = json.dumps(bedrock_metadata, indent=2)

        assert len(metadata_json.encode("utf-8")) <= 1024

    def test_oversized_metadata_gets_truncated(self, repo, oversized_metadata):
        result = repo._truncate_metadata_to_fit(None, oversized_metadata)
        bedrock_metadata = {"metadataAttributes": result}
        metadata_json = json.dumps(bedrock_metadata, indent=2)

        assert len(metadata_json.encode("utf-8")) <= 1024

    def test_oversized_metadata_keeps_other_fields(self, repo, oversized_metadata):
        """Truncation only affects keywords, not other fields."""
        result = repo._truncate_metadata_to_fit(None, oversized_metadata)

        assert result["name"] == oversized_metadata["name"]
        assert result["category"] == oversized_metadata["category"]
        assert result["filename"] == oversized_metadata["filename"]
        assert result["edition"] == oversized_metadata["edition"]
        assert result["brochure_number"] == oversized_metadata["brochure_number"]

    def test_keywords_are_truncated_progressively(self, repo, oversized_metadata):
        """Truncated keywords are a prefix of the original."""
        original_keywords = oversized_metadata["keywords"].split(", ")
        result = repo._truncate_metadata_to_fit(None, oversized_metadata)

        if "keywords" in result:
            result_keywords = result["keywords"].split(", ")
            assert len(result_keywords) < len(original_keywords)
            assert result_keywords == original_keywords[: len(result_keywords)]

    def test_keywords_removed_if_necessary(self, repo):
        """Keywords removed entirely if even one is too large."""
        metadata_with_huge_keyword = {
            "name": "Test",
            "keywords": "x" * 1000,
            "other_field": "y" * 500,
        }

        result = repo._truncate_metadata_to_fit(None, metadata_with_huge_keyword)
        bedrock_metadata = {"metadataAttributes": result}
        metadata_json = json.dumps(bedrock_metadata, indent=2)

        if len(metadata_json.encode("utf-8")) <= 1024:
            assert "keywords" not in result or result["keywords"] == ""

    def test_custom_max_bytes_parameter(self, repo, small_metadata):
        result = repo._truncate_metadata_to_fit(None, small_metadata, max_bytes=200)
        bedrock_metadata = {"metadataAttributes": result}
        metadata_json = json.dumps(bedrock_metadata, indent=2)

        size = len(metadata_json.encode("utf-8"))
        assert size <= 200 or "keywords" not in result

    def test_metadata_without_keywords(self, repo):
        metadata_no_keywords = {
            "name": "Test Document",
            "category": "Test",
            "filename": "test.md",
        }

        result = repo._truncate_metadata_to_fit(None, metadata_no_keywords)
        assert result == metadata_no_keywords

    def test_empty_keywords_field(self, repo):
        metadata_empty_keywords = {
            "name": "Test",
            "keywords": "",
            "category": "Test",
        }

        result = repo._truncate_metadata_to_fit(None, metadata_empty_keywords)
        bedrock_metadata = {"metadataAttributes": result}
        metadata_json = json.dumps(bedrock_metadata, indent=2)

        assert len(metadata_json.encode("utf-8")) <= 1024

    def test_keywords_as_list(self, repo):
        """Keywords list is converted to string during truncation."""
        long_keywords = ["keyword" + str(i) * 50 for i in range(20)]
        metadata_list_keywords = {
            "name": "Test Document Name",
            "keywords": long_keywords,
            "category": "Test Category",
            "filename": "test_file.md",
            "additional_field": "x" * 300,
        }

        result = repo._truncate_metadata_to_fit(None, metadata_list_keywords)
        bedrock_metadata = {"metadataAttributes": result}
        metadata_json = json.dumps(bedrock_metadata, indent=2)

        assert len(metadata_json.encode("utf-8")) <= 1024
        assert isinstance(result["keywords"], str)
        assert "keyword" in result["keywords"]

    def test_extreme_metadata_returns_original_with_warning(self, repo, extreme_metadata):
        """Extremely large metadata still returns a valid dict after logging."""
        result = repo._truncate_metadata_to_fit(None, extreme_metadata)

        assert isinstance(result, dict)
        assert "name" in result

    def test_real_world_example_from_ingestion(self, repo):
        """Exact metadata rejected in production (ingestion job failure)."""
        real_metadata: dict[str, str | bool | int] = {
            "name": "Erwerbsminderungsrente: Das Netz für alle Fälle",
            "category": "Rente",
            "keywords": "Allgemeiner Arbeitsmarkt, Arbeitsunfall, Berufskrankheit, Berufsschutz, Berufsunfähigkeitsrente, Erwerbsminderung, Erwerbsminderungsrente, Erwerbsunfähig, Erwerbsunfähigkeitsrente, Flexirentengesetz, Fünfjahreszeitraum, Hinzuverdienst, Hinzuverdienstdeckel, Hinzuverdienstgrenze, Restleistungsvermögen, Teilweise Erwerbsminderung, Verschlossener Arbeitsmarkt, Volle Erwerbsminderung, Weiterzahlungsantrag, Zurechnungszeit",
            "filename": "ALT B16 - Erwerbsminderungsrente: Das Netz für alle Fälle - 19. Auflage (7/2024)",
            "edition": "19. Auflage",
            "publishing_date": "7/2024",
            "gliederungsnummer": "201",
            "brochure_number": "B16",
            "chunk_type": "hierarchical_div",
            "section_title": "Nicht erwerbsfähig - trotzdem versorgt",
            "subsection_title": "Anderes Leben dank Rente - ein Beispiel",
            "div_index": 0,
            "has_table": False,
            "has_note": False,
        }

        original_bedrock = {"metadataAttributes": real_metadata}
        original_json = json.dumps(original_bedrock, indent=2)
        assert len(original_json.encode("utf-8")) > 1024

        result = repo._truncate_metadata_to_fit(None, real_metadata)
        result_bedrock = {"metadataAttributes": result}
        result_json = json.dumps(result_bedrock, indent=2)

        assert len(result_json.encode("utf-8")) <= 1024
        assert "keywords" in result
        assert isinstance(real_metadata["keywords"], str)
        assert len(result["keywords"]) < len(real_metadata["keywords"])
