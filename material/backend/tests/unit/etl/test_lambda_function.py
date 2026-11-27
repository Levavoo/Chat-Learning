import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from etl.lambda_function import (
    S3Handler,
    SQSHandler,
    _compute_stem,
    _delete_derived_outputs,
    handle_event,
    parse_s3_records,
)


class TestComputeStem:
    def test_xml_with_prefix(self):
        assert _compute_stem("IN/B01.xml") == "B01"

    def test_pdf_with_prefix(self):
        assert _compute_stem("IN/R0101.pdf") == "R0101"

    def test_spaces_stripped(self):
        assert _compute_stem("IN/FB 28.xml") == "FB28"

    def test_html_no_prefix(self):
        assert _compute_stem("faq.html") == "faq"

    def test_docs_prefix(self):
        assert _compute_stem("docs/R0101.pdf") == "R0101"

    def test_no_extension(self):
        assert _compute_stem("IN/somefile") == "somefile"


class TestParseS3Records:
    def _make_record(self, event_name: str, key: str, bucket: str = "source-bucket") -> dict:
        return {
            "eventName": event_name,
            "s3": {
                "bucket": {"name": bucket},
                "object": {"key": key},
            },
        }

    def _mock_router(self, bucket: str = "source-bucket", repo_name: str = "INGEST_BUCKET"):
        router = MagicMock()
        router.find_repositories.return_value = {repo_name: MagicMock()}
        return router

    def test_object_created_tagged_as_created(self):
        router = self._mock_router()
        records = [self._make_record("ObjectCreated:Put", "IN/B01.xml")]
        result = parse_s3_records(records, router)
        assert len(result) == 1
        assert result[0]["event_type"] == "created"

    def test_object_removed_tagged_as_removed(self):
        router = self._mock_router()
        records = [self._make_record("ObjectRemoved:Delete", "IN/B01.xml")]
        result = parse_s3_records(records, router)
        assert len(result) == 1
        assert result[0]["event_type"] == "removed"

    def test_other_event_types_skipped(self):
        router = self._mock_router()
        records = [self._make_record("ObjectRestore:Completed", "IN/B01.xml")]
        result = parse_s3_records(records, router)
        assert result == []

    def test_object_key_preserved(self):
        router = self._mock_router()
        records = [self._make_record("ObjectCreated:Put", "IN/B01.xml")]
        result = parse_s3_records(records, router)
        assert result[0]["object_key"] == "IN/B01.xml"

    def test_url_encoded_key_decoded(self):
        router = self._mock_router()
        records = [self._make_record("ObjectCreated:Put", "IN/FB%2028.xml")]
        result = parse_s3_records(records, router)
        assert result[0]["object_key"] == "IN/FB 28.xml"

    def test_missing_bucket_skipped(self):
        router = self._mock_router()
        records = [{"eventName": "ObjectCreated:Put", "s3": {"bucket": {"name": ""}, "object": {"key": "f.xml"}}}]
        result = parse_s3_records(records, router)
        assert result == []


class TestDeleteDerivedOutputs:
    def _make_route(self, destinations: dict):
        route = MagicMock()
        route.destinations = {name: MagicMock(repository=name, path=cfg["path"]) for name, cfg in destinations.items()}
        return route

    def test_calls_list_by_stem_and_delete(self):
        repo = MagicMock()
        repo.list_by_stem.return_value = ["docs/B01/B01_0000.md"]
        repos = {"OUTPUT_BUCKET": repo}
        route = self._make_route({"OUTPUT_BUCKET": {"path": "docs"}})

        _delete_derived_outputs(repos, route, "B01")

        repo.list_by_stem.assert_called_once_with("docs", "B01")
        repo.delete_objects.assert_called_once_with(["docs/B01/B01_0000.md"])

    def test_skips_if_no_keys_found(self):
        repo = MagicMock()
        repo.list_by_stem.return_value = []
        repos = {"OUTPUT_BUCKET": repo}
        route = self._make_route({"OUTPUT_BUCKET": {"path": "docs"}})

        _delete_derived_outputs(repos, route, "B01")

        repo.delete_objects.assert_not_called()

    def test_skips_missing_repo(self):
        repos: dict = {}
        route = self._make_route({"OUTPUT_BUCKET": {"path": "docs"}})
        _delete_derived_outputs(repos, route, "B01")

    def test_skips_repo_without_list_by_stem(self):
        """Repos without list_by_stem (e.g. HTML) are skipped."""
        repo = MagicMock(spec=[])
        repos = {"OUTPUT_BUCKET": repo}
        route = self._make_route({"OUTPUT_BUCKET": {"path": "docs"}})
        _delete_derived_outputs(repos, route, "B01")


class TestS3HandlerReplace:
    """Replace flow: delete stale outputs before running pipeline."""

    def _make_s3_event(self, key: str, event_name: str = "ObjectCreated:Put", bucket: str = "src-bucket") -> dict:
        return {
            "Records": [
                {
                    "eventSource": "aws:s3",
                    "eventName": event_name,
                    "s3": {"bucket": {"name": bucket}, "object": {"key": key}},
                }
            ]
        }

    @pytest.fixture
    def mock_router(self):
        router = MagicMock()
        router.find_repositories.return_value = {"INGEST_BUCKET": MagicMock(type="S3")}
        route = MagicMock()
        route.pipeline.name = "DITA_XML_PROCESSING"
        route.destinations = {"S3_Output": MagicMock(repository="OUTPUT_BUCKET", path="docs")}
        router.get_route.return_value = route
        pipeline_cfg = MagicMock()
        pipeline_cfg.transforms = []
        router.get_pipeline.return_value = pipeline_cfg
        match_result = MagicMock()
        match_result.route_config = route
        match_result.destinations = route.destinations
        router.match_route.return_value = match_result
        router.batch_match.return_value = {
            "DITA_XML_ROUTE": [{"object_key": "IN/B01.xml", "bucket_name": "src-bucket", "event_type": "created"}]
        }
        router.build_pipeline_config.return_value = {"transforms": [], "sources": {}, "destinations": {}}
        return router

    @pytest.mark.asyncio
    async def test_delete_called_before_pipeline_run(self, mock_router):
        call_order = []

        dest_repo = MagicMock()
        dest_repo.list_by_stem.return_value = ["docs/B01/B01_0000.md"]
        dest_repo.delete_objects = MagicMock(side_effect=lambda keys: call_order.append("delete"))

        with (
            patch("etl.lambda_function.get_router", return_value=mock_router),
            patch("etl.lambda_function.create_repository", return_value=dest_repo),
            patch("etl.lambda_function.Pipeline") as mock_pipeline_cls,
        ):
            mock_pipeline = MagicMock()
            mock_pipeline.run = AsyncMock(side_effect=lambda: call_order.append("run"))
            mock_pipeline_cls.create.return_value = mock_pipeline

            handler = S3Handler()
            await handler.handle_event(self._make_s3_event("IN/B01.xml"), None)

        assert "delete" in call_order
        assert "run" in call_order
        assert call_order.index("delete") < call_order.index("run")


class TestS3HandlerRemove:
    """Delete flow: ObjectRemoved triggers cleanup only."""

    def _make_removed_event(self, key: str = "IN/B01.xml", bucket: str = "src-bucket") -> dict:
        return {
            "Records": [
                {
                    "eventSource": "aws:s3",
                    "eventName": "ObjectRemoved:Delete",
                    "s3": {"bucket": {"name": bucket}, "object": {"key": key}},
                }
            ]
        }

    @pytest.fixture
    def mock_router(self):
        router = MagicMock()
        router.find_repositories.return_value = {"INGEST_BUCKET": MagicMock(type="S3")}
        route = MagicMock()
        route.pipeline.name = "DITA_XML_PROCESSING"
        route.destinations = {"S3_Output": MagicMock(repository="OUTPUT_BUCKET", path="docs")}
        router.get_route.return_value = route
        router.batch_match.return_value = {}  # no created events
        match_result = MagicMock()
        match_result.route_config = route
        router.match_route.return_value = match_result
        return router

    @pytest.mark.asyncio
    async def test_pipeline_not_run_on_removal(self, mock_router):
        dest_repo = MagicMock()
        dest_repo.list_by_stem.return_value = ["docs/B01/B01_0000.md"]

        with (
            patch("etl.lambda_function.get_router", return_value=mock_router),
            patch("etl.lambda_function.create_repository", return_value=dest_repo),
            patch("etl.lambda_function.Pipeline") as mock_pipeline_cls,
        ):
            handler = S3Handler()
            await handler.handle_event(self._make_removed_event(), None)

        mock_pipeline_cls.create.assert_not_called()

    @pytest.mark.asyncio
    async def test_delete_called_on_removal(self, mock_router):
        dest_repo = MagicMock()
        dest_repo.list_by_stem.return_value = ["docs/B01/B01_0000.md"]

        with (
            patch("etl.lambda_function.get_router", return_value=mock_router),
            patch("etl.lambda_function.create_repository", return_value=dest_repo),
            patch("etl.lambda_function.Pipeline"),
        ):
            handler = S3Handler()
            await handler.handle_event(self._make_removed_event(), None)

        dest_repo.delete_objects.assert_called_once_with(["docs/B01/B01_0000.md"])


class TestTombstoneHandling:
    """ObjectCreated for releases/*/deletes/{stem} must delete docs/{stem}/ (manifest-diff cleanup)."""

    def _make_created_event(self, key: str, bucket: str = "src-bucket") -> dict:
        return {
            "Records": [
                {
                    "eventSource": "aws:s3",
                    "eventName": "ObjectCreated:Put",
                    "s3": {"bucket": {"name": bucket}, "object": {"key": key}},
                }
            ]
        }

    @pytest.fixture
    def mock_router(self):
        router = MagicMock()
        router.find_repositories.return_value = {"INGEST_BUCKET": MagicMock(type="S3")}
        route = MagicMock()
        route.pipeline.name = "DITA_XML_PROCESSING"
        route.destinations = {"S3_Output": MagicMock(repository="OUTPUT_BUCKET", path="docs")}
        router.get_route.return_value = route
        match_result = MagicMock()
        match_result.route_config = route
        router.match_route.return_value = match_result
        router.batch_match.return_value = {}
        return router

    @pytest.mark.asyncio
    async def test_tombstone_triggers_docs_deletion(self, mock_router):
        dest_repo = MagicMock()
        dest_repo.list_by_stem.return_value = ["docs/B02/B02_0000.md"]

        with (
            patch("etl.lambda_function.get_router", return_value=mock_router),
            patch("etl.lambda_function.create_repository", return_value=dest_repo),
            patch("etl.lambda_function.Pipeline"),
        ):
            handler = S3Handler()
            await handler.handle_event(self._make_created_event("releases/v1.5.0/deletes/B02"), None)

        dest_repo.delete_objects.assert_called_once_with(["docs/B02/B02_0000.md"])

    @pytest.mark.asyncio
    async def test_tombstone_does_not_run_pipeline(self, mock_router):
        dest_repo = MagicMock()
        dest_repo.list_by_stem.return_value = ["docs/B02/B02_0000.md"]

        with (
            patch("etl.lambda_function.get_router", return_value=mock_router),
            patch("etl.lambda_function.create_repository", return_value=dest_repo),
            patch("etl.lambda_function.Pipeline") as mock_pipeline_cls,
        ):
            handler = S3Handler()
            await handler.handle_event(self._make_created_event("releases/v1.5.0/deletes/B02"), None)

        mock_pipeline_cls.create.assert_not_called()

    @pytest.mark.asyncio
    async def test_tombstone_does_not_affect_normal_xml_upload(self, mock_router):
        """Normal releases/ XML upload must NOT be intercepted as a tombstone."""
        dest_repo = MagicMock()
        dest_repo.list_by_stem.return_value = []
        mock_router.batch_match.return_value = {
            "DITA_XML_ROUTE_S3": [
                {"object_key": "releases/v1.5.0/xml/B01.xml", "bucket_name": "src-bucket", "event_type": "created"}
            ]
        }

        with (
            patch("etl.lambda_function.get_router", return_value=mock_router),
            patch("etl.lambda_function.create_repository", return_value=dest_repo),
            patch("etl.lambda_function.Pipeline") as mock_pipeline_cls,
        ):
            mock_pipeline = MagicMock()
            mock_pipeline.run = AsyncMock()
            mock_pipeline_cls.create.return_value = mock_pipeline

            handler = S3Handler()
            await handler.handle_event(self._make_created_event("releases/v1.5.0/xml/B01.xml"), None)

        # Pipeline should run for normal XML upload
        mock_pipeline_cls.create.assert_called_once()

    @pytest.mark.asyncio
    async def test_tombstone_stem_extracted_from_basename(self, mock_router):
        """Stem must be the bare basename of the tombstone key (no path, no ext)."""
        dest_repo = MagicMock()
        dest_repo.list_by_stem.return_value = []

        with (
            patch("etl.lambda_function.get_router", return_value=mock_router),
            patch("etl.lambda_function.create_repository", return_value=dest_repo),
            patch("etl.lambda_function.Pipeline"),
        ):
            handler = S3Handler()
            await handler.handle_event(self._make_created_event("releases/v1.5.0/deletes/V0090"), None)

        dest_repo.list_by_stem.assert_called_once_with("docs", "V0090")


class TestProcessRemovalReleasesGuard:
    """ObjectRemoved under releases/ must be ignored; lifecycle expiry (#489) would otherwise delete live docs/."""

    def _make_removed_event(self, key: str, bucket: str = "src-bucket") -> dict:
        return {
            "Records": [
                {
                    "eventSource": "aws:s3",
                    "eventName": "ObjectRemoved:Delete",
                    "s3": {"bucket": {"name": bucket}, "object": {"key": key}},
                }
            ]
        }

    @pytest.fixture
    def mock_router(self):
        router = MagicMock()
        router.find_repositories.return_value = {"INGEST_BUCKET": MagicMock(type="S3")}
        route = MagicMock()
        route.pipeline.name = "DITA_XML_PROCESSING"
        route.destinations = {"S3_Output": MagicMock(repository="OUTPUT_BUCKET", path="docs")}
        router.get_route.return_value = route
        router.batch_match.return_value = {}
        match_result = MagicMock()
        match_result.route_config = route
        router.match_route.return_value = match_result
        return router

    @pytest.mark.asyncio
    async def test_releases_xml_removal_is_ignored(self, mock_router):
        dest_repo = MagicMock()
        dest_repo.list_by_stem.return_value = ["docs/B01/B01_0000.md"]

        with (
            patch("etl.lambda_function.get_router", return_value=mock_router),
            patch("etl.lambda_function.create_repository", return_value=dest_repo),
            patch("etl.lambda_function.Pipeline"),
        ):
            handler = S3Handler()
            await handler.handle_event(self._make_removed_event("releases/v1.4.0/xml/B01.xml"), None)

        dest_repo.delete_objects.assert_not_called()

    @pytest.mark.asyncio
    async def test_releases_pdf_removal_is_ignored(self, mock_router):
        dest_repo = MagicMock()
        dest_repo.list_by_stem.return_value = ["docs/V0090/V0090_0000.md"]

        with (
            patch("etl.lambda_function.get_router", return_value=mock_router),
            patch("etl.lambda_function.create_repository", return_value=dest_repo),
            patch("etl.lambda_function.Pipeline"),
        ):
            handler = S3Handler()
            await handler.handle_event(self._make_removed_event("releases/v1.4.0/pdf/V0090.pdf"), None)

        dest_repo.delete_objects.assert_not_called()

    @pytest.mark.asyncio
    async def test_in_prefix_removal_still_triggers_cleanup(self, mock_router):
        """ObjectRemoved for IN/brochures/ must still clean up docs/ (no regression)."""
        dest_repo = MagicMock()
        dest_repo.list_by_stem.return_value = ["docs/B01/B01_0000.md"]

        with (
            patch("etl.lambda_function.get_router", return_value=mock_router),
            patch("etl.lambda_function.create_repository", return_value=dest_repo),
            patch("etl.lambda_function.Pipeline"),
        ):
            handler = S3Handler()
            await handler.handle_event(self._make_removed_event("IN/brochures/B01.xml"), None)

        dest_repo.delete_objects.assert_called_once_with(["docs/B01/B01_0000.md"])


class TestNoRecordsEvents:
    """Message with no processable records must be a no-op (#643: s3:TestEvent crashed on empty Records)."""

    @pytest.mark.asyncio
    async def test_module_handle_event_empty_records_is_noop(self):
        with patch.object(SQSHandler, "get_handler") as get_handler:
            await handle_event({"Records": []}, None)
            get_handler.assert_not_called()

    @pytest.mark.asyncio
    async def test_module_handle_event_missing_records_is_noop(self):
        with patch.object(SQSHandler, "get_handler") as get_handler:
            await handle_event({}, None)
            get_handler.assert_not_called()

    @pytest.mark.asyncio
    async def test_sqs_s3_test_event_is_ignored(self):
        """S3 validation event has no Records and must not reach a handler."""
        handler = SQSHandler()
        test_event_body = json.dumps({
            "Service": "Amazon S3",
            "Event": "s3:TestEvent",
            "Bucket": "renate-s3-retrieval-green-processed-preprod-a6c064ab",
        })
        event = {"Records": [{"body": test_event_body}]}
        with patch("etl.lambda_function.handle_event", new=AsyncMock()) as inner:
            await handler.handle_event(event, None)
            inner.assert_not_called()

    @pytest.mark.asyncio
    async def test_sqs_mixed_batch_drops_only_test_events(self):
        handler = SQSHandler()
        s3_body = json.dumps({"Records": [{"eventSource": "aws:s3", "s3": {"object": {"key": "x"}}}]})
        test_body = json.dumps({"Event": "s3:TestEvent", "Bucket": "b"})
        event = {"Records": [{"body": test_body}, {"body": s3_body}]}
        with patch("etl.lambda_function.handle_event", new=AsyncMock()) as inner:
            await handler.handle_event(event, None)
            inner.assert_awaited_once()
            assert inner.await_args is not None
            forwarded = inner.await_args.args[0]
            assert forwarded["Records"] == [{"eventSource": "aws:s3", "s3": {"object": {"key": "x"}}}]
