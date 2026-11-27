import asyncio
import json
import os
from collections.abc import Mapping
from urllib.parse import unquote_plus

from etl.config.settings import settings
from etl.pipeline.base import Pipeline
from etl.pipeline.router import Router, get_router, initialize_router
from etl.util.aws.lmbda.handler import LambdaHandler
from etl.util.logging_setup import get_logger, set_global_loglevel
from etl.util.repository.base import Repository

logger = get_logger(__name__)

_KNOWN_EXTENSIONS = (".xml", ".pdf", ".html", ".htm", ".md", ".txt")
_KNOWN_PREFIXES = ("IN/", "docs/")
# Tombstone key pattern: releases/{version}/deletes/{stem}. ObjectCreated on this
# path deletes docs/{stem}/… instead of running an ETL pipeline — signals a
# brochure removed from the new release.
_TOMBSTONE_INFIX = "/deletes/"


# =============================================================================
# S3 Event Helpers
# =============================================================================


def extract_object_metadata(object_key: str) -> dict:
    """Extract prefix and postfix from an object key for route matching."""
    metadata = {"object_key": object_key}

    if "." in object_key:
        metadata["postfix"] = "." + object_key.rsplit(".", 1)[-1]

    if "/" in object_key:
        metadata["prefix"] = object_key[: object_key.index("/") + 1]

    return metadata


def parse_s3_records(records: list[dict], router: Router) -> list[dict]:
    """Parse S3 event records into metadata dicts for route matching.

    Both ObjectCreated and ObjectRemoved events are captured.
    Metadata includes 'event_type': 'created' | 'removed'.
    """
    objects_metadata: list[dict] = []

    for record in records:
        event_name = record.get("eventName", "")
        if event_name.startswith("ObjectCreated"):
            event_type = "created"
        elif event_name.startswith("ObjectRemoved"):
            event_type = "removed"
        else:
            continue

        s3_info = record.get("s3", {})
        bucket = s3_info.get("bucket", {}).get("name", "")
        object_key = unquote_plus(s3_info.get("object", {}).get("key", ""))

        if not bucket or not object_key:
            continue

        metadata = extract_object_metadata(object_key)
        metadata["source"] = "aws:s3"
        metadata["bucket_name"] = bucket
        metadata["event_type"] = event_type

        repos = router.find_repositories(bucket_name=bucket)
        if repos:
            metadata["repositories"] = next(iter(repos.keys()))

        objects_metadata.append(metadata)

    return objects_metadata


def _compute_stem(object_key: str) -> str:
    """Derive the document stem from a source S3 object key.

    Strips path prefixes, known extensions and spaces (``IN/FB 28.xml`` → ``FB28``).
    """
    name = os.path.basename(object_key)
    for ext in _KNOWN_EXTENSIONS:
        if name.lower().endswith(ext):
            name = name[: -len(ext)]
            break
    return name.replace(" ", "")


def _delete_derived_outputs(repos: Mapping[str, Repository], route, stem: str) -> None:
    """Delete all derived artifacts for a document stem from destination repos."""
    for dest in route.destinations.values():
        repo = repos.get(dest.repository)
        if repo is None:
            logger.warning(f"Destination repository {dest.repository!r} not found, skipping cleanup")
            continue
        if not hasattr(repo, "list_by_stem"):
            logger.debug(f"Repository {dest.repository!r} does not support list_by_stem, skipping cleanup")
            continue
        keys = repo.list_by_stem(dest.path, stem)  # type: ignore[attr-defined]  # ty: ignore[call-non-callable]
        if keys:
            logger.info(f"Deleting {len(keys)} stale artifacts for stem {stem!r} from {dest.repository!r}")
            repo.delete_objects(keys)


def create_repository(config) -> Repository:
    """Create a Repository instance from config."""
    return Repository.create(config.type, **config.to_kwargs())


# =============================================================================
# S3 Handler
# =============================================================================


class S3Handler(LambdaHandler):
    """Handler for S3 Lambda events."""

    _event_source = "aws:s3"

    async def handle_event(self, event, context):
        """Handle S3 event by processing object uploads through configured pipelines.

        Args:
            event: Lambda event containing S3 records.
            context: Lambda context object.

        """
        router = get_router()
        records = event.get("Records", [])

        objects_metadata = parse_s3_records(records, router)
        if not objects_metadata:
            logger.info("No valid S3 objects found in event")
            return

        created_metadata = [m for m in objects_metadata if m.get("event_type") == "created"]

        # Tombstone pre-pass: intercept releases/*/deletes/* before normal routing.
        tombstone_metadata = [m for m in created_metadata if _TOMBSTONE_INFIX in m.get("object_key", "")]
        for item_meta in tombstone_metadata:
            await self._process_tombstone(router, item_meta)
        created_metadata = [m for m in created_metadata if m not in tombstone_metadata]

        route_groups = router.batch_match(created_metadata) if created_metadata else {}

        if created_metadata:
            matched_keys = {item["object_key"] for items in route_groups.values() for item in items}
            unmatched = [m for m in created_metadata if m["object_key"] not in matched_keys]
            if unmatched:
                unmatched_keys = [m["object_key"] for m in unmatched]
                logger.warning(f"No route matched for {len(unmatched)} files: {unmatched_keys}")

        removed_metadata = [m for m in objects_metadata if m.get("event_type") == "removed"]
        for item_meta in removed_metadata:
            await self._process_removal(router, item_meta)

        if not route_groups and not removed_metadata:
            logger.warning("No files matched any configured route")
            return

        for route_name, matched_items in route_groups.items():
            await self._process_route_group(router, route_name, matched_items)

    async def _process_removal(self, router: Router, item_meta: dict) -> None:
        """Handle an ObjectRemoved event: delete derived artifacts, no pipeline.

        Objects under ``releases/`` are ignored here: their removal is lifecycle-driven,
        not operator intent. Intentional cross-release removal uses :meth:`_process_tombstone`.
        """
        object_key = item_meta.get("object_key", "")
        bucket = item_meta.get("bucket_name", "")

        if object_key.startswith("releases/"):
            logger.info(
                "ObjectRemoved ignored for historical release object %r (lifecycle expiry must not delete live docs/)",
                object_key,
            )
            return

        source_repos = router.find_repositories(bucket_name=bucket)
        if not source_repos:
            logger.warning(f"No repository configured for bucket: {bucket}")
            return

        # Match as if created to recover destinations.
        match_meta = {**item_meta, "event_type": "created"}
        match_result = router.match_route(**match_meta)
        if not match_result:
            logger.warning(f"No route matched for removed object {object_key!r}")
            return

        route = match_result.route_config
        repos = self._create_route_repositories(router, source_repos, route)
        stem = _compute_stem(object_key)
        logger.info(f"ObjectRemoved: cleaning up derived outputs for {object_key!r} (stem={stem!r})")
        _delete_derived_outputs(repos, route, stem)

    async def _process_tombstone(self, router: Router, item_meta: dict) -> None:
        """Handle a tombstone ObjectCreated event for an intentionally removed stem.

        Deletes derived ``docs/{stem}/…`` artifacts without running any ETL pipeline.
        Uses the XML route destinations (``docs/``) because both XML and PDF
        derived artifacts land there.
        """
        object_key = item_meta.get("object_key", "")
        bucket = item_meta.get("bucket_name", "")

        # Stem is the basename of the tombstone key: releases/v1.5.0/deletes/B02 → "B02"
        stem = os.path.basename(object_key)
        if not stem:
            logger.warning(f"Tombstone key has empty basename: {object_key!r}")
            return

        source_repos = router.find_repositories(bucket_name=bucket)
        if not source_repos:
            logger.warning(f"No repository configured for bucket: {bucket}")
            return

        # Re-derive prefix/postfix via a dummy ``.xml`` key so the router sees a real
        # extension (tombstone keys have no extension, which would misroute).
        dummy_key = f"releases/dummy/{stem}.xml"
        dummy_meta = {**item_meta, **extract_object_metadata(dummy_key), "event_type": "created"}
        match_result = router.match_route(**dummy_meta)
        if not match_result:
            logger.warning(f"Cannot resolve destination for tombstone stem {stem!r}")
            return

        route = match_result.route_config
        repos = self._create_route_repositories(router, source_repos, route)
        logger.info(f"Tombstone: deleting derived outputs for removed stem {stem!r} (key={object_key!r})")
        _delete_derived_outputs(repos, route, stem)

    async def _process_route_group(self, router: Router, route_name: str, matched_items: list[dict]) -> None:
        """Process a group of items matched to the same route."""
        route = router.get_route(route_name)
        pipeline_config = router.get_pipeline(route.pipeline.name) if route else None

        if not route or not pipeline_config:
            logger.warning(f"Route or pipeline not found: {route_name}")
            return

        bucket = matched_items[0].get("bucket_name", "")
        source_repos = router.find_repositories(bucket_name=bucket)

        if not source_repos:
            logger.warning(f"No repository configured for bucket: {bucket}")
            return

        source_repo_name = next(iter(source_repos.keys()))
        repos = self._create_route_repositories(router, source_repos, route)

        object_keys = [item["object_key"] for item in matched_items]
        match_result = router.match_route(**matched_items[0])

        if not match_result:
            return

        for key in object_keys:
            stem = _compute_stem(key)
            _delete_derived_outputs(repos, route, stem)

        pipeline_dict = router.build_pipeline_config(match_result, object_keys, source_repo_name)

        try:
            pipeline = Pipeline.create(pipeline_dict, repos)
            await pipeline.run()
            logger.info(f"Processed {len(object_keys)} objects via route {route_name}")
        except Exception:
            logger.exception(f"Failed to process route {route_name}")

    def _create_route_repositories(self, router: Router, source_repos: dict, route) -> dict[str, Repository]:
        """Create repository instances for source and destinations."""
        repos: dict[str, Repository] = {}

        for name, config in source_repos.items():
            repos[name] = create_repository(config)

        for dest in route.destinations.values():
            if dest.repository not in repos:
                dest_config = router.get_repository(dest.repository)
                if dest_config:
                    repos[dest.repository] = create_repository(dest_config)

        return repos


# =============================================================================
# SQS Handler (Delegate)
# =============================================================================


class SQSHandler(LambdaHandler):
    """Handler that unwraps SQS messages and delegates to appropriate handler."""

    _event_source = "aws:sqs"

    async def handle_event(self, event, context):
        """Handle SQS event by unwrapping messages and delegating to appropriate handler.

        Args:
            event: Lambda event containing SQS records.
            context: Lambda context object.

        """
        # Flatten records from SQS bodies; skip S3 test events (bucket-notification validation).
        all_records = []
        for sqs_record in event.get("Records", []):
            body = json.loads(sqs_record["body"])
            if body.get("Event") == "s3:TestEvent":
                logger.info(
                    "Ignoring S3 test event for bucket %s (notification config validation).",
                    body.get("Bucket", "<unknown>"),
                )
                continue
            all_records.extend(body.get("Records", []))

        if not all_records:
            logger.info("SQS batch contained no processable records; nothing to do.")
            return

        await handle_event({"Records": all_records}, context)


# =============================================================================
# Entry Points
# =============================================================================


async def handle_event(event, context):
    """Route event to the appropriate handler based on event source."""
    logger.debug(f"Received event: {json.dumps(event, indent=2)}")

    # No records = no eventSource to route on; no-op rather than raise.
    records = event.get("Records") or []
    if not records:
        logger.info("Event contains no records; nothing to process.")
        return

    event_source = records[0].get("eventSource", "")
    handler = LambdaHandler.get_handler(event_source)
    await handler.handle_event(event, context)


def lambda_handler(event, context):
    """Lambda entry point."""
    set_global_loglevel(settings.logging.log_level)

    if context and hasattr(context, "get_remaining_time_in_millis"):
        from etl.util.chunking.llm_enrichment import set_lambda_deadline
        set_lambda_deadline(context.get_remaining_time_in_millis())

    if not Router.is_initialized():
        initialize_router()

    asyncio.run(handle_event(event, context))
