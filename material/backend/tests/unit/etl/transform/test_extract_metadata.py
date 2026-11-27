
from pathlib import Path

import pytest

from etl.models import DataObject, DataType, PipelineItem
from etl.transform.extract_metadata import extract_metadata_from_dita, load_brochure_url_mapping

SEED_XML_DIR = Path(__file__).resolve().parents[5] / "cdk" / "seed-data" / "xml"


@pytest.fixture
def transform():
    return extract_metadata_from_dita()


@pytest.fixture
def sample_dita_with_prolog():
    return b"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE concept PUBLIC "-//OASIS//DTD DITA Concept//EN" "concept.dtd">
<concept id="test-concept">
  <title>Test Document Title</title>
  <prolog>
    <metadata>
      <category>insurance</category>
      <keywords>
        <keyword>policy</keyword>
        <keyword>coverage</keyword>
        <keyword>claims</keyword>
      </keywords>
      <data name="brochure" value="B42"/>
      <data name="document_type" value="concept"/>
      <data name="version" value="1.0"/>
    </metadata>
  </prolog>
  <conbody>
    <p>Document content here.</p>
  </conbody>
</concept>
"""


@pytest.fixture
def sample_dita_minimal():
    return b"""<?xml version="1.0" encoding="UTF-8"?>
<concept id="minimal">
  <title>Minimal Document</title>
  <conbody>
    <p>Content only.</p>
  </conbody>
</concept>
"""


@pytest.fixture
def sample_dita_nested_data():
    return b"""<?xml version="1.0" encoding="UTF-8"?>
<concept id="nested">
  <title>Nested Data Document</title>
  <prolog>
    <metadata>
      <data name="parent_field">
        <data name="child_field" value="nested_value"/>
      </data>
    </metadata>
  </prolog>
  <conbody>
    <p>Content with nested metadata.</p>
  </conbody>
</concept>
"""


@pytest.fixture
def custom_field_map():
    return {
        "brochure": "brochure_id",
        "document_type": "doc_type",
        "version": "doc_version",
    }


@pytest.fixture
def sample_dita_title_with_nested_b_tags():
    return b"""<?xml version='1.0' encoding='utf-8'?>
<!DOCTYPE topic PUBLIC "-//OASIS//DTD DITA 1.3 Topic//EN" "../dtd/topic.dtd">
<topic id="test_topic" xml:lang="de-DE">
  <title id="test-title"><b>Datenschutz:</b><b>Ihre Daten -</b><b>Ihre Rechte</b></title>
  <prolog>
    <metadata>
      <category>Service</category>
    </metadata>
    <data name="broschrennummer" value="F109"/>
  </prolog>
  <body>
    <p>Content here.</p>
  </body>
</topic>
"""


@pytest.fixture
def sample_dita_title_without_nested_tags():
    return b"""<?xml version='1.0' encoding='utf-8'?>
<!DOCTYPE topic PUBLIC "-//OASIS//DTD DITA 1.3 Topic//EN" "../dtd/topic.dtd">
<topic id="test_topic" xml:lang="de-DE">
  <title id="test-title">Simple Title Without Tags</title>
  <prolog>
    <metadata>
      <category>Service</category>
    </metadata>
    <data name="broschrennummer" value="B01"/>
  </prolog>
  <body>
    <p>Content here.</p>
  </body>
</topic>
"""


class TestExtractMetadataApply:

    def test_apply_returns_list_of_pipeline_items(self, transform, sample_dita_with_prolog):
        pytest.skip("Not implemented")

    def test_content_unchanged_after_extraction(self, transform, sample_dita_with_prolog):
        pytest.skip("Not implemented")

    def test_metadata_enriched_on_data_object(self, transform, sample_dita_with_prolog):
        pytest.skip("Not implemented")


class TestTitleExtraction:

    def test_extracts_title_from_concept(self, transform, sample_dita_with_prolog):
        pytest.skip("Not implemented")

    def test_handles_missing_title(self, transform):
        pytest.skip("Not implemented")

    def test_extracts_title_with_nested_b_tags(self, transform, sample_dita_title_with_nested_b_tags):
        # Arrange
        data_obj = DataObject(
            name="F109_test",
            data=sample_dita_title_with_nested_b_tags,
            data_type=DataType.XML,
            metadata={},
        )
        item = PipelineItem(name="F109_test", data_object=data_obj)

        # Act
        result = transform.apply(item)

        # Assert
        assert len(result) == 1
        metadata = result[0].data_object.metadata
        assert "name" in metadata
        assert metadata["name"] == "Datenschutz:Ihre Daten -Ihre Rechte"
        assert metadata["brochure_number"] == "F109"

    def test_extracts_title_without_nested_tags(self, transform, sample_dita_title_without_nested_tags):
        # Arrange
        data_obj = DataObject(
            name="B01_test",
            data=sample_dita_title_without_nested_tags,
            data_type=DataType.XML,
            metadata={},
        )
        item = PipelineItem(name="B01_test", data_object=data_obj)

        # Act
        result = transform.apply(item)

        # Assert
        assert len(result) == 1
        metadata = result[0].data_object.metadata
        assert "name" in metadata
        assert metadata["name"] == "Simple Title Without Tags"
        assert metadata["brochure_number"] == "B01"


class TestCategoryExtraction:

    def test_extracts_category(self, transform, sample_dita_with_prolog):
        pytest.skip("Not implemented")

    def test_handles_missing_category(self, transform, sample_dita_minimal):
        pytest.skip("Not implemented")


class TestKeywordsExtraction:

    def test_extracts_all_keywords(self, transform, sample_dita_with_prolog):
        pytest.skip("Not implemented")

    def test_handles_empty_keywords(self, transform, sample_dita_minimal):
        pytest.skip("Not implemented")

    def test_handles_single_keyword(self, transform):
        pytest.skip("Not implemented")


class TestDataFieldExtraction:

    def test_extracts_brochure_field(self, transform, sample_dita_with_prolog):
        pytest.skip("Not implemented")

    def test_extracts_document_type_field(self, transform, sample_dita_with_prolog):
        pytest.skip("Not implemented")

    def test_extracts_version_field(self, transform, sample_dita_with_prolog):
        pytest.skip("Not implemented")

    def test_applies_custom_field_map(self, custom_field_map, sample_dita_with_prolog):
        pytest.skip("Not implemented")

    def test_handles_nested_data_elements(self, transform, sample_dita_nested_data):
        pytest.skip("Not implemented")


class TestDataParser:

    def test_returns_dita_parser_instance(self, transform):
        pytest.skip("Not implemented")

    def test_parser_extracts_metadata(self, transform, sample_dita_with_prolog):
        pytest.skip("Not implemented")


class TestMetadataMerging:

    def test_preserves_existing_metadata(self, transform, sample_dita_with_prolog):
        pytest.skip("Not implemented")

    def test_extracted_metadata_supplements_existing(self, transform, sample_dita_with_prolog):
        pytest.skip("Not implemented")


class TestErrorHandling:

    def test_handles_invalid_xml(self, transform):
        pytest.skip("Not implemented")

    def test_handles_empty_content(self, transform):
        pytest.skip("Not implemented")

    def test_handles_non_dita_xml(self, transform):
        pytest.skip("Not implemented")


class TestLoadBrochureUrlMapping:

    def test_returns_empty_dict_for_missing_file(self, tmp_path):
        result = load_brochure_url_mapping(tmp_path / "nonexistent.yaml")
        assert result == {}

    def test_returns_empty_dict_for_empty_file(self, tmp_path):
        yaml_file = tmp_path / "empty.yaml"
        yaml_file.write_text("")
        result = load_brochure_url_mapping(yaml_file)
        assert result == {}

    def test_returns_empty_dict_for_comments_only(self, tmp_path):
        yaml_file = tmp_path / "comments.yaml"
        yaml_file.write_text("# just a comment\n")
        result = load_brochure_url_mapping(yaml_file)
        assert result == {}

    def test_loads_mapping(self, tmp_path):
        yaml_file = tmp_path / "mapping.yaml"
        yaml_file.write_text("B28: https://example.com/b28.html\nB42: https://example.com/b42.html\n")
        result = load_brochure_url_mapping(yaml_file)
        assert result == {
            "B28": "https://example.com/b28.html",
            "B42": "https://example.com/b42.html",
        }

    def test_handles_malformed_yaml_gracefully(self, tmp_path, caplog):
        yaml_file = tmp_path / "malformed.yaml"
        yaml_file.write_text("B28: https://example.com/b28.html\n  invalid: [unclosed bracket\nB42: no colon here")
        result = load_brochure_url_mapping(yaml_file)
        assert result == {}
        assert "Malformed YAML in brochure URL mapping file" in caplog.text


class TestBrochureUrlResolution:

    @pytest.fixture
    def dita_with_brochure_number(self):
        return b"""<?xml version="1.0" encoding="UTF-8"?>
<topic id="test">
  <title>Test Brochure</title>
  <prolog>
    <metadata>
      <category>national</category>
    </metadata>
    <data name="broschrennummer" value="B28"/>
  </prolog>
  <body><p>Content.</p></body>
</topic>
"""

    @pytest.fixture
    def dita_without_brochure_number(self):
        return b"""<?xml version="1.0" encoding="UTF-8"?>
<topic id="test">
  <title>Test No Brochure</title>
  <prolog>
    <metadata>
      <category>national</category>
    </metadata>
  </prolog>
  <body><p>Content.</p></body>
</topic>
"""

    def _make_item(self, data: bytes) -> PipelineItem:
        return PipelineItem(
            name="test",
            data_object=DataObject(name="test", data=data, data_type=DataType.XML, metadata={}),
        )

    def test_adds_brochure_url_when_mapping_exists(self, dita_with_brochure_number):
        transform = extract_metadata_from_dita(brochure_url_mapping={"B28": "https://example.com/b28.html"})
        item = self._make_item(dita_with_brochure_number)
        result = transform.apply(item)
        assert result[0].data_object.metadata["brochure_url"] == "https://example.com/b28.html"

    def test_warns_when_no_mapping_for_brochure(self, dita_with_brochure_number, caplog):
        transform = extract_metadata_from_dita(brochure_url_mapping={})
        item = self._make_item(dita_with_brochure_number)
        result = transform.apply(item)
        assert "brochure_url" not in result[0].data_object.metadata
        assert "No URL mapping found for brochure: B28" in caplog.text

    def test_skips_when_no_brochure_number(self, dita_without_brochure_number):
        transform = extract_metadata_from_dita(brochure_url_mapping={"B28": "https://example.com/b28.html"})
        item = self._make_item(dita_without_brochure_number)
        result = transform.apply(item)
        assert "brochure_url" not in result[0].data_object.metadata

    def test_end_to_end_with_yaml_file(self, dita_with_brochure_number, tmp_path):
        yaml_file = tmp_path / "brochure_urls.yaml"
        url = "https://www.deutsche-rentenversicherung.de/SharedDocs/Downloads/DE/Broschueren/national/die_richtige_altersrente_fuer_sie.html"
        yaml_file.write_text(f"B28: {url}\n")

        mapping = load_brochure_url_mapping(yaml_file)
        transform = extract_metadata_from_dita(brochure_url_mapping=mapping)
        item = self._make_item(dita_with_brochure_number)
        result = transform.apply(item)

        metadata = result[0].data_object.metadata
        assert metadata["brochure_number"] == "B28"
        assert metadata["brochure_url"] == url


class TestNewSchemaFields:

    @pytest.fixture
    def dita_new_schema(self):
        return b"""<?xml version="1.0" encoding="UTF-8"?>
<topic id="B14-19-w311a" xml:lang="de-DE" product="digibro">
  <title>Altersvorsorge</title>
  <prolog>
    <metadata>
      <keywords>
        <keyword otherprops="hauptstichwort">Altersvorsorge</keyword>
        <keyword>Riester-Rente</keyword>
        <keyword otherprops="hauptstichwort">Altersvorsorgeaufwendungen</keyword>
      </keywords>
    </metadata>
    <data name="rubrik" value="Zusaetzliche Altersvorsorge"/>
    <data name="kurztitel" value="Altersvorsorge planen"/>
    <data name="gliederungsnummer" value="600"/>
    <data name="broschuerennummer" value="B14"/>
    <data name="auflage" value="19. Auflage"/>
    <data name="veroeffentlichungsdatum" value="2/2026"/>
    <data name="sprache" value="DE"/>
    <data name="websitelink" value="https://example.com/altersvorsorge.html"/>
  </prolog>
  <body><p>Content.</p></body>
</topic>
"""

    def _make_item(self, data: bytes) -> PipelineItem:
        return PipelineItem(
            name="t",
            data_object=DataObject(name="t", data=data, data_type=DataType.XML, metadata={}),
        )

    def test_maps_broschuerennummer_to_brochure_number(self, transform, dita_new_schema):
        result = transform.apply(self._make_item(dita_new_schema))
        assert result[0].data_object.metadata["brochure_number"] == "B14"

    def test_maps_veroeffentlichungsdatum_to_publishing_date(self, transform, dita_new_schema):
        result = transform.apply(self._make_item(dita_new_schema))
        assert result[0].data_object.metadata["publishing_date"] == "2/2026"

    def test_promotes_rubrik_to_category(self, transform, dita_new_schema):
        result = transform.apply(self._make_item(dita_new_schema))
        metadata = result[0].data_object.metadata
        assert metadata["category"] == "Zusaetzliche Altersvorsorge"
        assert "rubrik" not in metadata

    def test_explicit_category_takes_precedence_over_rubrik(self, transform):
        xml = b"""<?xml version="1.0"?>
<topic id="t"><title>T</title>
  <prolog>
    <metadata><category>FromCategoryElement</category></metadata>
    <data name="rubrik" value="FromRubrikData"/>
  </prolog>
  <body><p>x</p></body>
</topic>"""
        result = transform.apply(self._make_item(xml))
        metadata = result[0].data_object.metadata
        assert metadata["category"] == "FromCategoryElement"
        assert "rubrik" not in metadata

    def test_extracts_short_title_language_websitelink(self, transform, dita_new_schema):
        metadata = transform.apply(self._make_item(dita_new_schema))[0].data_object.metadata
        assert metadata["short_title"] == "Altersvorsorge planen"
        assert metadata["language"] == "DE"
        assert metadata["brochure_url"] == "https://example.com/altersvorsorge.html"

    def test_websitelink_is_not_overwritten_by_yaml_lookup(self):
        xml = b"""<?xml version="1.0"?>
<topic id="t"><title>T</title>
  <prolog>
    <data name="broschuerennummer" value="B14"/>
    <data name="websitelink" value="https://from-xml.example.com/inline.html"/>
  </prolog>
  <body><p>x</p></body>
</topic>"""
        transform = extract_metadata_from_dita(
            brochure_url_mapping={"B14": "https://from-yaml.example.com/lookup.html"},
        )
        metadata = transform.apply(self._make_item(xml))[0].data_object.metadata
        assert metadata["brochure_url"] == "https://from-xml.example.com/inline.html"

    def test_extracts_primary_keywords_from_hauptstichwort(self, transform, dita_new_schema):
        metadata = transform.apply(self._make_item(dita_new_schema))[0].data_object.metadata
        assert metadata["keywords"] == "Altersvorsorge, Riester-Rente, Altersvorsorgeaufwendungen"
        assert metadata["primary_keywords"] == "Altersvorsorge, Altersvorsorgeaufwendungen"

    def test_no_primary_keywords_when_no_hauptstichwort(self, transform):
        xml = b"""<?xml version="1.0"?>
<topic id="t"><title>T</title>
  <prolog>
    <metadata><keywords><keyword>foo</keyword><keyword>bar</keyword></keywords></metadata>
  </prolog>
  <body><p>x</p></body>
</topic>"""
        metadata = transform.apply(self._make_item(xml))[0].data_object.metadata
        assert metadata["keywords"] == "foo, bar"
        assert "primary_keywords" not in metadata

    def test_real_new_schema_seed_file(self, transform):
        xml_path = SEED_XML_DIR / "600_Altersvorsorge-planen_DE_19-Aufl_2026-02_digibro.xml"
        if not xml_path.exists():
            pytest.skip("New-schema seed XML not present")
        item = PipelineItem(
            name=xml_path.stem,
            data_object=DataObject(
                name=xml_path.stem,
                data=xml_path.read_bytes(),
                data_type=DataType.XML,
                metadata={},
            ),
        )
        metadata = transform.apply(item)[0].data_object.metadata
        assert metadata["brochure_number"] == "B14"
        assert metadata["publishing_date"] == "2/2026"
        assert metadata["edition"] == "19. Auflage"
        assert metadata["category"] == "Zusätzliche Altersvorsorge"
        assert metadata["language"] == "DE"
        assert metadata["short_title"] == "Altersvorsorge planen"
        assert metadata["brochure_url"].startswith("https://www.deutsche-rentenversicherung.de/")
        assert "Altersvorsorge" in metadata["primary_keywords"]


class TestWithRealXmlFiles:

    def _make_item(self, xml_path: Path) -> PipelineItem:
        data = xml_path.read_bytes()
        return PipelineItem(
            name=xml_path.stem,
            data_object=DataObject(name=xml_path.stem, data=data, data_type=DataType.XML, metadata={}),
        )

    def _xml_files(self) -> list[Path]:
        return sorted(SEED_XML_DIR.glob("*.xml"))

    def test_all_seed_files_extract_brochure_number(self, transform):
        missing = []
        for xml_path in self._xml_files():
            item = self._make_item(xml_path)
            result = transform.apply(item)
            metadata = result[0].data_object.metadata
            if "brochure_number" not in metadata:
                missing.append(xml_path.name)
        assert missing == [], f"Files missing brochure_number: {missing}"

    @pytest.mark.parametrize(
        "filename, expected_number",
        [
            ("B01_Medizin.Reha__dita_digibro.xml", "B01"),
            ("B28_–_Von_Altersgrenze_bis_Zeitrente_–_das_Rentenlexikon_(17._Auflage_5_2024)_dita_digibro.xml", "B28"),  # noqa: RUF001
            ("F01_–_Kindererziehung__Ihr_Plus_für_die_Rente_–_19._Auflage_(4_2025)_dita_digibro.xml", "F01"),  # noqa: RUF001
            ("FB28_–_RV_Fit_(8._Auflage_7_2024)_dita_digibro.xml", "FB 28"),  # noqa: RUF001
        ],
    )
    def test_correct_brochure_number_extracted(self, transform, filename, expected_number):
        xml_path = SEED_XML_DIR / filename
        if not xml_path.exists():
            pytest.skip(f"{filename} not found")
        item = self._make_item(xml_path)
        result = transform.apply(item)
        assert result[0].data_object.metadata["brochure_number"] == expected_number

    def test_brochure_url_resolved_from_mapping(self, tmp_path):
        xml_path = (
            SEED_XML_DIR
            / "B28_–_Von_Altersgrenze_bis_Zeitrente_–_das_Rentenlexikon_(17._Auflage_5_2024)_dita_digibro.xml"  # noqa: RUF001
        )
        if not xml_path.exists():
            pytest.skip("B28 XML not found")

        url = "https://www.deutsche-rentenversicherung.de/SharedDocs/Downloads/DE/Broschueren/national/von_altersgrenze_bis_zeitrente_rentenlexikon.html"
        transform = extract_metadata_from_dita(brochure_url_mapping={"B28": url})

        item = self._make_item(xml_path)
        result = transform.apply(item)

        metadata = result[0].data_object.metadata

        assert metadata["brochure_number"] == "B28"
        assert metadata["brochure_url"] == url
        assert metadata.get("name")  # title should also be extracted

    def test_missing_mapping_logs_warning(self, tmp_path, caplog):
        xml_path = SEED_XML_DIR / "B01_Medizin.Reha__dita_digibro.xml"
        if not xml_path.exists():
            pytest.skip("B01 XML not found")

        transform = extract_metadata_from_dita(brochure_url_mapping={"B99": "https://example.com/other"})

        item = self._make_item(xml_path)
        result = transform.apply(item)

        metadata = result[0].data_object.metadata
        assert "brochure_url" not in metadata
        assert "No URL mapping found for brochure: B01" in caplog.text
