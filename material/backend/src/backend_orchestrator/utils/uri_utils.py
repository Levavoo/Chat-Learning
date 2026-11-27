"""URI and filename processing utilities."""

import re

# Chunk suffix appended by the ETL chunker, e.g. "..._0009".
_CHUNK_SUFFIX_RE = re.compile(r"_\d{4}$")
# Technical filename tail from the language/edition marker onwards,
# e.g. "_DE_20-Aufl_2025-08_digibro" (plus "_note_000" / "_table_000" suffixes).
_TECHNICAL_TAIL_RE = re.compile(r"_(?:DE|EN)_\d{1,3}-Aufl.*$|_digibro.*$|_(?:note|table)_\d{3}.*$", re.IGNORECASE)
# Leading Gliederungsnummer, e.g. "300_".
_LEADING_NUMBER_RE = re.compile(r"^\d{2,4}_")


def get_display_name(metadata: dict, source_uri: str) -> str:
    """Determine the optimal display name for a document source.

    Prioritises explicit metadata titles, then parent directory for chunks,
    then a readable label derived from the filename. A raw chunk filename
    is never returned: it exposes an internal storage artifact and (with its
    _NNNN suffix) makes two chunks of one brochure look like two sources.
    """
    display_name = metadata.get("name") or metadata.get("title")
    if display_name:
        return display_name

    filename = extract_filename_from_uri(source_uri)

    if filename.startswith("chunk_") and "s3://" in source_uri:
        try:
            parent_dir = source_uri.split("/")[-2]
        except IndexError:
            return derive_label_from_filename(filename)
        else:
            return derive_label_from_filename(parent_dir)

    return derive_label_from_filename(filename)


def derive_label_from_filename(filename: str) -> str:
    """Derive a human-readable label from an internal document filename.

    ``300_Rehabilitation_DE_20-Aufl_2025-08_digibro_0009.md`` -> ``Rehabilitation``
    ``R0815_0009.md`` -> ``R0815``
    """
    if not filename:
        return "Unbekanntes Dokument"

    stem = re.sub(r"\.(md|pdf|html|xml|json)$", "", filename, flags=re.IGNORECASE)
    stem = _CHUNK_SUFFIX_RE.sub("", stem)
    stem = _TECHNICAL_TAIL_RE.sub("", stem)
    stem = _LEADING_NUMBER_RE.sub("", stem)
    label = re.sub(r"[_-]+", " ", stem).strip()
    return label or "Unbekanntes Dokument"


def extract_filename_from_uri(uri: str) -> str:
    """Extract a clean filename from an S3 URI or file path."""
    if not uri:
        return "Unknown Document"

    path_parts = uri.split("/")
    return path_parts[-1]
