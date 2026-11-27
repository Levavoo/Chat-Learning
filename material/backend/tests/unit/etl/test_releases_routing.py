"""Tests for releases/ prefix routing and stem derivation (Task 2, #487).

Locks: releases/v{semver}/xml/*.xml → DITA_XML_ROUTE_S3; .../md/*.md → MERKBLATT_MD_ROUTE_S3 (#501);
.../pdf/*.pdf → PDF_ROUTE_S3; retired IN/ routes do not match; _compute_stem is basename-based
with spaces stripped. The router is initialised from the real config.yaml.
"""

from pathlib import Path
from types import SimpleNamespace

import pytest
import yaml

from etl.lambda_function import _compute_stem, extract_object_metadata
from etl.pipeline.router import Router, initialize_router


@pytest.fixture(autouse=True)
def _reset_router():
    Router.reset()
    yield
    Router.reset()


@pytest.fixture()
def router():
    """Router initialised from the real config.yaml (no mocks)."""
    config_path = Path(__file__).resolve().parents[3] / "src/etl/config.yaml"
    assert config_path.is_file(), f"config.yaml not found at {config_path}"
    with config_path.open() as config_file:
        raw_config = yaml.safe_load(config_file)
    return initialize_router(SimpleNamespace(**raw_config))


class TestReleasesRouteMatching:
    def test_releases_xml_matches_dita_route(self, router):
        meta = extract_object_metadata("releases/v9.9.9/xml/B01.xml")
        meta["source"] = "aws:s3"
        meta["repositories"] = "INGEST_BUCKET"

        result = router.match_route(**meta)

        assert result is not None
        assert result.route_name == "DITA_XML_ROUTE_S3"

    def test_releases_md_matches_merkblatt_route(self, router):
        meta = extract_object_metadata("releases/v9.9.9/md/V0090.md")
        meta["source"] = "aws:s3"
        meta["repositories"] = "INGEST_BUCKET"

        result = router.match_route(**meta)

        assert result is not None
        assert result.route_name == "MERKBLATT_MD_ROUTE_S3"

    def test_releases_pdf_still_matches_pdf_route(self, router):
        """data_artifact_version and etl_version are independent pins.

        A post-#501 ETL image can still be pinned against a pre-#501 coordinate whose
        Merkblätter are PDFs; losing this route would silently ingest zero Merkblätter
        for that combination.
        """
        meta = extract_object_metadata("releases/v9.9.9/pdf/V0090.pdf")
        meta["source"] = "aws:s3"
        meta["repositories"] = "INGEST_BUCKET"

        result = router.match_route(**meta)

        assert result is not None
        assert result.route_name == "PDF_ROUTE_S3"

    def test_md_and_pdf_route_to_distinct_pipelines(self, router):
        """The .md path skips TEXT2MD; the legacy .pdf path keeps it (#501)."""
        md_meta = extract_object_metadata("releases/v9.9.9/md/V0090.md")
        md_meta["source"] = "aws:s3"
        md_meta["repositories"] = "INGEST_BUCKET"
        pdf_meta = extract_object_metadata("releases/v9.9.9/pdf/V0090.pdf")
        pdf_meta["source"] = "aws:s3"
        pdf_meta["repositories"] = "INGEST_BUCKET"

        md_pipeline = router.get_pipeline(router.match_route(**md_meta).route_config.pipeline.name)
        pdf_pipeline = router.get_pipeline(router.match_route(**pdf_meta).route_config.pipeline.name)

        md_transforms = list(md_pipeline.transforms)
        pdf_transforms = list(pdf_pipeline.transforms)

        assert md_transforms == ["CHUNK_MARKDOWN"]
        assert pdf_transforms == ["TEXT2MD", "CHUNK_MARKDOWN"]

    def test_releases_xml_with_space_in_name_matches_dita_route(self, router):
        meta = extract_object_metadata("releases/v9.9.9/xml/FB 28.xml")
        meta["source"] = "aws:s3"
        meta["repositories"] = "INGEST_BUCKET"

        result = router.match_route(**meta)

        assert result is not None
        assert result.route_name == "DITA_XML_ROUTE_S3"

    def test_releases_prefix_extracted_as_first_segment(self):
        meta = extract_object_metadata("releases/v9.9.9/xml/B01.xml")
        assert meta["prefix"] == "releases/"

    def test_releases_xml_postfix_is_dotxml(self):
        meta = extract_object_metadata("releases/v9.9.9/xml/B01.xml")
        assert meta["postfix"] == ".xml"

    def test_releases_pdf_postfix_is_dotpdf(self):
        meta = extract_object_metadata("releases/v9.9.9/pdf/V0090.pdf")
        assert meta["postfix"] == ".pdf"


class TestStrictFaqReleaseRouting:
    """Only the canonical content-addressed FAQ HTML key is accepted."""

    @staticmethod
    def _match(router, key: str):
        meta = extract_object_metadata(key)
        meta["source"] = "aws:s3"
        meta["repositories"] = "INGEST_BUCKET"
        return router.match_route(**meta)

    def test_canonical_versioned_faq_matches(self, router):
        key = f"releases/faq/sha256-{'a' * 64}/html/faq-a-und-b.html"
        result = self._match(router, key)
        assert result is not None
        assert result.route_name == "FAQ_RELEASE_ROUTE"

    def test_second_faq_source_matches_and_keeps_stem(self, router):
        """#987: every ``html/<stem>.html`` under a coordinate routes to FAQ; stem = file name."""
        key = f"releases/faq/sha256-{'a' * 64}/html/faq-pflegeversicherung.html"
        result = self._match(router, key)
        assert result is not None
        assert result.route_name == "FAQ_RELEASE_ROUTE"
        assert _compute_stem(key) == "faq-pflegeversicherung"

    @pytest.mark.parametrize(
        "key",
        [
            f"releases/faq/sha256-{'a' * 63}/html/faq-a-und-b.html",
            f"releases/faq/sha256-{'A' * 64}/html/faq-a-und-b.html",
            f"releases/faq/sha256-{'a' * 64}/faq-a-und-b.html",
            f"releases/faq/sha256-{'a' * 64}/html/Faq-A-und-B.html",
            f"releases/faq/sha256-{'a' * 64}/html/faq_a.html",
            f"releases/faq/sha256-{'a' * 64}/html/sub/faq-a-und-b.html",
            f"releases/faq/sha256-{'a' * 64}/html/.html",
            "releases/faq/latest/html/faq-a-und-b.html",
            "releases/faq/arbitrary.html",
            "releases/other/example.html",
        ],
    )
    def test_malformed_or_arbitrary_release_html_is_rejected(self, router, key):
        assert self._match(router, key) is None

    def test_deep_legacy_faq_is_rejected(self, router):
        assert self._match(router, "IN/faq/deep/path/faq-a-und-b.html") is None


class TestLegacyInPrefixRetired:
    """IN/ XML/PDF routing was retired in #488; ObjectCreated is ignored and ObjectRemoved cannot delete docs/."""

    def test_in_xml_no_longer_matches_any_route(self, router):
        meta = extract_object_metadata("IN/brochures/B01.xml")
        meta["source"] = "aws:s3"
        meta["repositories"] = "INGEST_BUCKET"

        result = router.match_route(**meta)

        assert result is None

    def test_in_pdf_no_longer_matches_any_route(self, router):
        meta = extract_object_metadata("IN/brochures/V0090.pdf")
        meta["source"] = "aws:s3"
        meta["repositories"] = "INGEST_BUCKET"

        result = router.match_route(**meta)

        assert result is None

    def test_in_faq_html_no_longer_matches_any_route(self, router):
        meta = extract_object_metadata("IN/faq/drv.html")
        meta["source"] = "aws:s3"
        meta["repositories"] = "INGEST_BUCKET"

        result = router.match_route(**meta)

        assert result is None


class TestObjectRemovedLegacyInNoOp:
    """ObjectRemoved for legacy IN/ objects must NOT delete derived outputs (#488)."""

    @pytest.mark.asyncio
    async def test_object_removed_for_in_brochure_xml_no_deletion(self, router):
        from unittest.mock import MagicMock, patch

        from etl.lambda_function import S3Handler

        dest_repo = MagicMock()

        with (
            patch("etl.lambda_function.get_router", return_value=router),
            patch("etl.lambda_function.create_repository", return_value=dest_repo),
            patch("etl.lambda_function.Pipeline"),
        ):
            router._repositories["INGEST_BUCKET"].config["bucket_name"] = "src-bucket"
            router._repositories["OUTPUT_BUCKET"].config["bucket_name"] = "out-bucket"

            handler_obj = S3Handler()
            event = {
                "Records": [
                    {
                        "eventSource": "aws:s3",
                        "eventName": "ObjectRemoved:Delete",
                        "s3": {"bucket": {"name": "src-bucket"}, "object": {"key": "IN/brochures/B01.xml"}},
                    }
                ]
            }
            await handler_obj.handle_event(event, None)

        dest_repo.list_by_stem.assert_not_called()
        dest_repo.delete_objects.assert_not_called()

    @pytest.mark.asyncio
    async def test_object_removed_for_in_brochure_pdf_no_deletion(self, router):
        from unittest.mock import MagicMock, patch

        from etl.lambda_function import S3Handler

        dest_repo = MagicMock()

        with (
            patch("etl.lambda_function.get_router", return_value=router),
            patch("etl.lambda_function.create_repository", return_value=dest_repo),
            patch("etl.lambda_function.Pipeline"),
        ):
            router._repositories["INGEST_BUCKET"].config["bucket_name"] = "src-bucket"
            router._repositories["OUTPUT_BUCKET"].config["bucket_name"] = "out-bucket"

            handler_obj = S3Handler()
            event = {
                "Records": [
                    {
                        "eventSource": "aws:s3",
                        "eventName": "ObjectRemoved:Delete",
                        "s3": {"bucket": {"name": "src-bucket"}, "object": {"key": "IN/brochures/V0090.pdf"}},
                    }
                ]
            }
            await handler_obj.handle_event(event, None)

        dest_repo.list_by_stem.assert_not_called()
        dest_repo.delete_objects.assert_not_called()

    @pytest.mark.asyncio
    async def test_object_removed_for_deep_in_faq_html_no_deletion(self, router):
        from unittest.mock import MagicMock, patch

        from etl.lambda_function import S3Handler

        dest_repo = MagicMock()

        with (
            patch("etl.lambda_function.get_router", return_value=router),
            patch("etl.lambda_function.create_repository", return_value=dest_repo),
            patch("etl.lambda_function.Pipeline"),
        ):
            router._repositories["INGEST_BUCKET"].config["bucket_name"] = "src-bucket"
            router._repositories["OUTPUT_BUCKET"].config["bucket_name"] = "out-bucket"

            handler_obj = S3Handler()
            event = {
                "Records": [
                    {
                        "eventSource": "aws:s3",
                        "eventName": "ObjectRemoved:Delete",
                        "s3": {
                            "bucket": {"name": "src-bucket"},
                            "object": {"key": "IN/faq/deep/path/faq-a-und-b.html"},
                        },
                    }
                ]
            }
            await handler_obj.handle_event(event, None)

        dest_repo.list_by_stem.assert_not_called()
        dest_repo.delete_objects.assert_not_called()


class TestReleasesComputeStem:
    """_compute_stem must produce identical stems regardless of key depth."""

    def test_stem_releases_xml(self):
        assert _compute_stem("releases/v9.9.9/xml/B01.xml") == "B01"

    def test_stem_releases_pdf(self):
        assert _compute_stem("releases/v9.9.9/pdf/V0090.pdf") == "V0090"

    def test_stem_releases_xml_space_stripped(self):
        assert _compute_stem("releases/v9.9.9/xml/FB 28.xml") == "FB28"

    def test_stem_releases_dita_long_name(self):
        key = "releases/v9.9.9/xml/210_Grundrente_DE_05-Aufl_2026-05_digibro.xml"
        assert _compute_stem(key) == "210_Grundrente_DE_05-Aufl_2026-05_digibro"

    def test_stem_in_xml_unchanged(self):
        assert _compute_stem("IN/B01.xml") == "B01"

    def test_stem_in_pdf_unchanged(self):
        assert _compute_stem("IN/R0101.pdf") == "R0101"


class TestTombstoneRealRouter:
    """_process_tombstone with the REAL router from config.yaml.

    Catches postfix/prefix bugs that mocked router.match_route stubs can hide.
    """

    def _make_tombstone_event(self, key: str, bucket: str = "src-bucket") -> dict:
        return {
            "Records": [
                {
                    "eventSource": "aws:s3",
                    "eventName": "ObjectCreated:Put",
                    "s3": {"bucket": {"name": bucket}, "object": {"key": key}},
                }
            ]
        }

    @pytest.fixture()
    def real_router_plain_buckets(self, router):
        """Config uses ${ETL_*_BUCKET} placeholders expanded by Lambda env; inject plain names for tests."""
        router._repositories["INGEST_BUCKET"].config["bucket_name"] = "src-bucket"
        router._repositories["OUTPUT_BUCKET"].config["bucket_name"] = "out-bucket"
        return router

    @pytest.mark.asyncio
    async def test_tombstone_calls_delete_objects_with_real_router(self, real_router_plain_buckets):
        """Catches the no-op bug where _process_tombstone leaked a stale postfix into dummy_meta."""
        from unittest.mock import MagicMock, patch

        from etl.lambda_function import S3Handler

        dest_repo = MagicMock()
        dest_repo.list_by_stem.return_value = ["docs/B02/B02_0000.md"]

        with (
            patch("etl.lambda_function.get_router", return_value=real_router_plain_buckets),
            patch("etl.lambda_function.create_repository", return_value=dest_repo),
            patch("etl.lambda_function.Pipeline"),
        ):
            handler = S3Handler()
            await handler.handle_event(self._make_tombstone_event("releases/v1.5.0/deletes/B02"), None)

        dest_repo.list_by_stem.assert_called_once_with("docs", "B02")
        dest_repo.delete_objects.assert_called_once_with(["docs/B02/B02_0000.md"])

    @pytest.mark.asyncio
    async def test_tombstone_with_space_in_stem_real_router(self, real_router_plain_buckets):
        from unittest.mock import MagicMock, patch

        from etl.lambda_function import S3Handler

        dest_repo = MagicMock()
        dest_repo.list_by_stem.return_value = ["docs/FB28/FB28_0000.md"]

        with (
            patch("etl.lambda_function.get_router", return_value=real_router_plain_buckets),
            patch("etl.lambda_function.create_repository", return_value=dest_repo),
            patch("etl.lambda_function.Pipeline"),
        ):
            handler = S3Handler()
            await handler.handle_event(self._make_tombstone_event("releases/v1.5.0/deletes/FB28"), None)

        dest_repo.list_by_stem.assert_called_once_with("docs", "FB28")
        dest_repo.delete_objects.assert_called_once_with(["docs/FB28/FB28_0000.md"])

    @pytest.mark.asyncio
    async def test_tombstone_does_not_run_pipeline_real_router(self, real_router_plain_buckets):
        from unittest.mock import MagicMock, patch

        from etl.lambda_function import S3Handler

        dest_repo = MagicMock()
        dest_repo.list_by_stem.return_value = ["docs/B01/B01_0000.md"]

        with (
            patch("etl.lambda_function.get_router", return_value=real_router_plain_buckets),
            patch("etl.lambda_function.create_repository", return_value=dest_repo),
            patch("etl.lambda_function.Pipeline") as mock_pipeline_cls,
        ):
            handler = S3Handler()
            await handler.handle_event(self._make_tombstone_event("releases/v1.5.0/deletes/B01"), None)

        mock_pipeline_cls.create.assert_not_called()
