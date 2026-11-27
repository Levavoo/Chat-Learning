"""Integration tests for extract_metadata_from_dita transform.

Makes real HTTP requests. Run with: pytest -m integration
"""

from pathlib import Path

import pytest
from requests import head

from etl.models import DataObject, DataType, PipelineItem
from etl.transform.extract_metadata import extract_metadata_from_dita, load_brochure_url_mapping

SEED_XML_DIR = Path(__file__).resolve().parents[5] / "cdk" / "seed-data" / "xml"


@pytest.fixture
def transform():
    return extract_metadata_from_dita()


@pytest.fixture
def dita_with_brochure_number():
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


def _make_item(data: bytes) -> PipelineItem:
    return PipelineItem(
        name="test",
        data_object=DataObject(name="test", data=data, data_type=DataType.XML, metadata={}),
    )


def _make_item_from_file(xml_path: Path) -> PipelineItem:
    data = xml_path.read_bytes()
    return PipelineItem(
        name=xml_path.stem,
        data_object=DataObject(name=xml_path.stem, data=data, data_type=DataType.XML, metadata={}),
    )


@pytest.mark.integration
class TestBrochureUrlValidation:
    def test_end_to_end_with_yaml_file(self, dita_with_brochure_number, tmp_path):
        """YAML on disk -> metadata contains brochure_url -> URL is accessible."""
        yaml_file = tmp_path / "brochure_urls.yaml"
        url = "https://www.deutsche-rentenversicherung.de/SharedDocs/Downloads/DE/Broschueren/national/die_richtige_altersrente_fuer_sie.html"
        yaml_file.write_text(f"B28: {url}\n")

        mapping = load_brochure_url_mapping(yaml_file)
        transform = extract_metadata_from_dita(brochure_url_mapping=mapping)
        item = _make_item(dita_with_brochure_number)
        result = transform.apply(item)

        metadata = result[0].data_object.metadata
        assert metadata["brochure_number"] == "B28"
        assert metadata["brochure_url"] == url

        response = head(metadata["brochure_url"], timeout=10)
        assert response.status_code == 200, f"URL returned status {response.status_code}"

    def test_brochure_url_resolved_from_mapping(self, tmp_path):
        """Real XML + YAML mapping -> brochure_url in metadata -> URL is accessible."""
        xml_path = (
            SEED_XML_DIR
            / "B28_–_Von_Altersgrenze_bis_Zeitrente_–_das_Rentenlexikon_(17._Auflage_5_2024)_dita_digibro.xml"  # noqa: RUF001
        )
        if not xml_path.exists():
            pytest.skip("B28 XML not found")

        url = "https://www.deutsche-rentenversicherung.de/SharedDocs/Downloads/DE/Broschueren/national/von_altersgrenze_bis_zeitrente_rentenlexikon.html"
        transform = extract_metadata_from_dita(brochure_url_mapping={"B28": url})

        item = _make_item_from_file(xml_path)
        result = transform.apply(item)

        metadata = result[0].data_object.metadata

        assert metadata["brochure_number"] == "B28"
        assert metadata["brochure_url"] == url
        assert metadata.get("name")

        response = head(metadata["brochure_url"], timeout=10)
        assert response.status_code == 200, f"URL returned status {response.status_code}"
