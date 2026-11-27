"""Offline, deterministic reproduction of the generated KB Markdown corpus.

Runs the real transform chain over the seed source directory into a temporary
output tree, with contextual grounding and LLM enrichment forced off, then
scans the produced ``.md`` files with :mod:`etl.markdown_quality`. Transform
lists are read from ``config.yaml`` via the router so the gate cannot drift
from production pipeline definitions.
"""

import argparse
import asyncio
import json
import sys
import tempfile
from pathlib import Path

# Populate the Transform/Ingest/Output/Repository factory registries by importing
# their packages (each __init__ auto-imports its submodules for registration).
import etl.ingest
import etl.output
import etl.transform
import etl.util.repository  # noqa: F401
from etl.markdown_quality import build_report, load_acknowledgements, scan_corpus
from etl.util.logging_setup import get_logger

logger = get_logger("markdown_quality_gate")

_PIPELINE_BY_EXTENSION = {".xml": "DITA_XML_PROCESSING", ".pdf": "PDF_PROCESSING"}


class GenerationError(RuntimeError):
    """Raised when a seed file produces no Markdown output (a silent generation defect)."""


def _force_deterministic_environment() -> None:
    """Force the content-mutating and AWS-dependent steps off, keeping generation offline."""
    import os

    os.environ["CONTEXTUAL_GROUNDING_ENABLED"] = "false"
    os.environ["ENRICHMENT_ENABLED"] = "false"
    os.environ.setdefault("ETL_INGEST_BUCKET", "markdown-quality-gate-dummy-ingest")
    os.environ.setdefault("ETL_OUTPUT_BUCKET", "markdown-quality-gate-dummy-output")
    os.environ["CONFIG_PATH"] = str(Path(__file__).with_name("config.yaml"))


def _transform_lists() -> dict[str, list[str]]:
    """Read the real transform chains from config.yaml via the router (no hardcoding)."""
    from etl.config.pipeline import PipelineConfiguration
    from etl.pipeline.router import initialize_router

    # Fresh PipelineConfiguration re-reads CONFIG_PATH each call via its YAML source.
    router = initialize_router(PipelineConfiguration())  # ty: ignore[missing-argument]
    lists: dict[str, list[str]] = {}
    for pipeline_name in set(_PIPELINE_BY_EXTENSION.values()):
        pipeline = router.get_pipeline(pipeline_name)
        if pipeline is None:
            raise GenerationError(f"Pipeline {pipeline_name} is not defined in config.yaml")
        lists[pipeline_name] = list(pipeline.transforms)
    return lists


def _stage_sources(source_dir: Path, staging_dir: Path) -> dict[str, str]:
    """Copy seed files into ``staging_dir`` with spaces stripped (S3Ingest parity)."""
    mapping: dict[str, str] = {}
    for path in sorted(source_dir.iterdir()):
        if not path.is_file():
            continue
        pipeline_name = _PIPELINE_BY_EXTENSION.get(path.suffix.lower())
        if pipeline_name is None:
            continue
        # Mirror S3Ingest's space-stripping so chunk folder names match runtime.
        target_name = path.name.replace(" ", "")
        target = staging_dir / target_name
        if target.exists():
            raise GenerationError(f"Staged source name collision: {target_name}")
        target.write_bytes(path.read_bytes())
        mapping[target_name] = pipeline_name
    return mapping


async def _run_one(object_id: str, transforms: list[str], src_dir: Path, out_dir: Path) -> None:
    from etl.pipeline.base import Pipeline
    from etl.util.repository.base import Repository
    from etl.util.repository.local_filesystem import LocalFileSystemRepository

    config = {
        "transforms": transforms,
        "sources": {"primary": {"repository": "SRC", "objects": [object_id], "path": "."}},
        "destinations": {"out": {"repository": "OUT", "path": "docs"}},
    }
    repositories: dict[str, Repository] = {
        "SRC": LocalFileSystemRepository(str(src_dir)),
        "OUT": LocalFileSystemRepository(str(out_dir)),
    }
    await Pipeline.create(config, repositories).run()


async def generate_corpus(source_dir: Path, out_dir: Path) -> None:
    """Generate the Markdown corpus offline, failing closed if any seed yields no output."""
    import logging

    from etl.util.logging_setup import set_global_loglevel

    set_global_loglevel(logging.WARNING)
    _force_deterministic_environment()
    transform_lists = _transform_lists()

    with tempfile.TemporaryDirectory(prefix="mdq-src-") as staging:
        staging_dir = Path(staging)
        staged = _stage_sources(source_dir, staging_dir)
        if not staged:
            raise GenerationError(f"No .xml/.pdf seed files found under {source_dir}")

        for object_id, pipeline_name in staged.items():
            before = {p.relative_to(out_dir) for p in out_dir.rglob("*.md")}
            await _run_one(object_id, transform_lists[pipeline_name], staging_dir, out_dir)
            after = {p.relative_to(out_dir) for p in out_dir.rglob("*.md")}
            if after <= before:
                raise GenerationError(f"Seed file produced no Markdown output: {object_id}")


def generate_and_scan(source_dir: Path, out_dir: Path):
    """Generate the corpus into ``out_dir`` and return the sorted findings list."""
    asyncio.run(generate_corpus(source_dir, out_dir))
    return scan_corpus(out_dir)


# Tier -> interim_handling for auto-generated residue baseline entries.
_TIER_INTERIM = {"hard": "drop_fragment", "warning": "ingest_with_warning"}


def _document_folder(source: str) -> str:
    """Return the chunk's document folder (``docs/<stem>/``) for document-level baselining."""
    parent = source.rsplit("/", 1)[0]
    return f"{parent}/" if parent and parent != source else source


def build_baseline(findings) -> dict:
    """Group unreviewed findings into document-level ``source_fix_requested`` baseline entries.

    One entry per (rule, document-folder); entries go stale as source/extraction fixes clean each document.
    """
    seen: set[tuple[str, str]] = set()
    acknowledgements: list[dict] = []
    for finding in findings:
        folder = _document_folder(finding.source)
        key = (finding.rule, folder)
        if key in seen:
            continue
        seen.add(key)
        slug = folder.strip("/").replace("/", "-")
        acknowledgements.append({
            "id": f"md694-{finding.rule.split('.', 1)[-1]}-{slug}",
            "rule": finding.rule,
            "source": folder,
            "excerpt_prefix": "",
            "decision": "source_fix_requested",
            "interim_handling": _TIER_INTERIM[finding.tier],
            "rationale": (
                "Baseline: known generated-artifact residue in this document, pending "
                "source/extraction fixes. Remove this entry once the document regenerates clean."
            ),
        })
    return {"version": 1, "acknowledgements": sorted(acknowledgements, key=lambda a: a["id"])}


def main(argv: list[str] | None = None) -> int:
    """Reproduce, scan, and gate the generated Markdown corpus; write a JSON report."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-dir", type=Path, required=True)
    parser.add_argument("--acknowledgements", type=Path, required=True)
    parser.add_argument("--report", type=Path)
    parser.add_argument(
        "--emit-baseline",
        type=Path,
        help="Write a document-level source_fix_requested baseline for the current residue and exit 0.",
    )
    args = parser.parse_args(argv)

    with tempfile.TemporaryDirectory(prefix="mdq-out-") as out:
        findings = generate_and_scan(args.source_dir, Path(out))

    if args.emit_baseline:
        baseline = build_baseline(findings)
        args.emit_baseline.write_text(json.dumps(baseline, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        logger.info("Wrote %s baseline entries to %s", len(baseline["acknowledgements"]), args.emit_baseline)
        return 0

    acknowledgements = load_acknowledgements(args.acknowledgements)
    report = build_report(findings, acknowledgements)

    summary = report["summary"]
    logger.info(
        "KB markdown-quality gate: %s detected, %s unbaselined-hard, %s unreviewed-warning",
        summary["detected"],
        summary["hard_unbaselined"],
        summary["warning_unreviewed"],
    )
    for finding in report["findings"]:
        if finding["acknowledgement"] is None:
            logger.error(
                "%s:%s:%s %s [%s]: %s",
                finding["source"],
                finding["line"],
                finding["column"],
                finding["rule"],
                finding["tier"],
                finding["excerpt"],
            )
    for stale_id in report["stale_acknowledgement_ids"]:
        logger.warning("stale markdown-quality acknowledgement: %s", stale_id)

    if args.report:
        args.report.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return 1 if report["status"] == "failed" else 0


if __name__ == "__main__":
    sys.exit(main())
