"""Integration tests that verify all brochure URLs in brochure_urls.yaml are valid.

Run with: pytest -m integration
"""

import pytest
import requests

from etl.transform.extract_metadata import load_brochure_url_mapping

BROCHURE_URL_MAPPING = load_brochure_url_mapping()


def pytest_generate_tests(metafunc):
    if "brochure_id" in metafunc.fixturenames and "url" in metafunc.fixturenames:
        metafunc.parametrize(
            "brochure_id,url",
            list(BROCHURE_URL_MAPPING.items()),
            ids=list(BROCHURE_URL_MAPPING.keys()),
        )


@pytest.mark.integration
class TestBrochureUrlsConfig:
    """Every URL in brochure_urls.yaml must be reachable without redirect."""

    def test_url_is_reachable_without_redirect(self, brochure_id: str, url: str) -> None:
        response = requests.head(url, allow_redirects=False, timeout=10)
        assert response.status_code == 200, f"{brochure_id}: expected 200 but got {response.status_code} for {url}"
