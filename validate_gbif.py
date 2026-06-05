#!/usr/bin/env python3
"""Validate scientific names against the GBIF backbone taxonomy."""

from __future__ import annotations

import csv
import os
import sys
import time
from pathlib import Path

import requests
from dotenv import load_dotenv

GBIF_SPECIES_MATCH_URL = "https://api.gbif.org/v2/species/match"

TSV_COLUMNS = [
    "originalID",
    "originalScientificName",
    "matchType",
    "usageKey",
    "usageName",
    "usageCanonicalName",
    "usageAuthorship",
    "usageRank",
    "usageStatus",
    "synonym",
    "acceptedUsageKey",
    "acceptedUsageCanonicalName",
    "acceptedUsageAuthorship",
    "acceptedUsageRank",
    "kingdom",
    "phylum",
    "class",
    "order",
    "family",
    "genus",
    "datasetAlias",
    "status",
    "statusCode",
]

RANK_MAP = {
    "KINGDOM": "kingdom",
    "PHYLUM": "phylum",
    "CLASS": "class",
    "ORDER": "order",
    "FAMILY": "family",
    "GENUS": "genus",
}

RETRYABLE_HTTP_STATUS = {429, 502, 503, 504}

COMMON_CSV_ENCODINGS = ("utf-8-sig", "cp1252", "latin-1")


def empty_row(original_id: str, scientific_name: str) -> dict[str, str]:
    row = {col: "" for col in TSV_COLUMNS}
    row["originalID"] = original_id
    row["originalScientificName"] = scientific_name
    return row


def _field_value(obj: dict | None, key: str) -> str:
    if not obj:
        return ""
    value = obj.get(key)
    if value is None:
        return ""
    return str(value)


def parse_backbone_response(
    original_id: str,
    scientific_name: str,
    data: dict | None,
) -> dict[str, str]:
    row = empty_row(original_id, scientific_name)
    if not data:
        return row

    diagnostics = data.get("diagnostics") or {}
    row["matchType"] = _field_value(diagnostics, "matchType")

    usage = data.get("usage") or {}
    row["usageKey"] = _field_value(usage, "key")
    row["usageName"] = _field_value(usage, "name")
    row["usageCanonicalName"] = _field_value(usage, "canonicalName")
    row["usageAuthorship"] = _field_value(usage, "authorship")
    row["usageRank"] = _field_value(usage, "rank")
    row["usageStatus"] = _field_value(usage, "status")

    synonym = data.get("synonym")
    row["synonym"] = "" if synonym is None else str(synonym).lower()

    accepted = data.get("acceptedUsage") or {}
    row["acceptedUsageKey"] = _field_value(accepted, "key")
    row["acceptedUsageCanonicalName"] = _field_value(accepted, "canonicalName")
    row["acceptedUsageAuthorship"] = _field_value(accepted, "authorship")
    row["acceptedUsageRank"] = _field_value(accepted, "rank")

    for node in data.get("classification") or []:
        rank = (node.get("rank") or "").upper()
        col = RANK_MAP.get(rank)
        if col:
            row[col] = _field_value(node, "name")

    iucn = next(
        (
            status
            for status in data.get("additionalStatus") or []
            if status.get("datasetAlias") == "IUCN"
        ),
        None,
    )
    if iucn:
        row["datasetAlias"] = _field_value(iucn, "datasetAlias")
        row["status"] = _field_value(iucn, "status")
        row["statusCode"] = _field_value(iucn, "statusCode")

    return row


def _looks_like_html(text: str) -> bool:
    stripped = text.strip().lower()
    return stripped.startswith("<!doctype html") or stripped.startswith("<html")


def _is_retryable_error(exc: BaseException) -> bool:
    if isinstance(exc, requests.exceptions.RequestException):
        response = getattr(exc, "response", None)
        if response is not None:
            if response.status_code in RETRYABLE_HTTP_STATUS:
                return True
            try:
                if _looks_like_html(response.text):
                    return True
            except Exception:
                pass
        return isinstance(
            exc,
            (
                requests.exceptions.ConnectionError,
                requests.exceptions.Timeout,
                requests.exceptions.ChunkedEncodingError,
            ),
        )

    message = str(exc).lower()
    if _looks_like_html(message):
        return True
    return any(token in message for token in ("429", "502", "503", "504", "timeout"))


def _fetch_name_backbone(scientific_name: str) -> dict:
    response = requests.get(
        GBIF_SPECIES_MATCH_URL,
        params={"scientificName": scientific_name},
        headers={
            "User-Agent": (
                f"catplant-gbif-validation requests/{requests.__version__}"
            ),
        },
        timeout=60,
    )
    response.raise_for_status()
    if _looks_like_html(response.text):
        raise requests.exceptions.RequestException(
            f"Unexpected HTML response (HTTP {response.status_code})"
        )
    data = response.json()
    if not isinstance(data, dict):
        raise TypeError(f"Unexpected response type: {type(data).__name__}")
    return data


def call_name_backbone(
    scientific_name: str,
    *,
    max_retries: int,
    retry_backoff_seconds: float,
    delay_seconds: float,
) -> dict | None:
    last_error: BaseException | None = None

    for attempt in range(max_retries + 1):
        try:
            result = _fetch_name_backbone(scientific_name)
            time.sleep(delay_seconds)
            return result
        except Exception as exc:
            last_error = exc
            if attempt >= max_retries or not _is_retryable_error(exc):
                break
            wait = retry_backoff_seconds * (2**attempt)
            print(
                f"Retry {attempt + 1}/{max_retries} for '{scientific_name}' "
                f"after {wait:.1f}s: {exc}",
                file=sys.stderr,
            )
            time.sleep(wait)

    time.sleep(delay_seconds)
    if last_error is not None:
        print(
            f"API error for '{scientific_name}': {last_error}",
            file=sys.stderr,
        )
    return None


def _env_float(name: str, default: float) -> float:
    raw = os.getenv(name)
    if raw is None or raw.strip() == "":
        return default
    return float(raw)


def _env_int(name: str, default: int) -> int:
    raw = os.getenv(name)
    if raw is None or raw.strip() == "":
        return default
    return int(raw)


def _env_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None or raw.strip() == "":
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _detect_csv_delimiter(sample: str) -> str:
    if sample.count(";") > sample.count(","):
        return ";"
    return ","


def _file_decodes_as(path: Path, encoding: str, chunk_size: int = 1024 * 1024) -> bool:
    try:
        with path.open("rb") as fin:
            while chunk := fin.read(chunk_size):
                chunk.decode(encoding)
        return True
    except UnicodeDecodeError:
        return False


def _detect_csv_encoding(path: Path, preferred: str | None) -> str:
    if preferred:
        return preferred
    for encoding in COMMON_CSV_ENCODINGS:
        if _file_decodes_as(path, encoding):
            return encoding
    return "utf-8-sig"


def _load_completed_original_ids(output_path: Path) -> set[str]:
    if not output_path.is_file() or output_path.stat().st_size == 0:
        return set()
    with output_path.open(newline="", encoding="utf-8") as fin:
        reader = csv.DictReader(fin, delimiter="\t")
        return {
            row["originalID"]
            for row in reader
            if row.get("originalID") is not None
        }


def main() -> int:
    load_dotenv()

    input_csv = os.getenv("INPUT_CSV", "./data/input.csv")
    output_tsv = os.getenv("OUTPUT_TSV", "./data/output.tsv")
    delay_seconds = _env_float("API_DELAY_SECONDS", 0.5)
    max_retries = _env_int("API_MAX_RETRIES", 3)
    retry_backoff_seconds = _env_float("API_RETRY_BACKOFF_SECONDS", 2.0)
    progress_every = _env_int("PROGRESS_EVERY", 50)
    resume = _env_bool("RESUME", False)
    input_encoding = os.getenv("INPUT_CSV_ENCODING", "").strip() or None
    input_delimiter = os.getenv("INPUT_CSV_DELIMITER", "").strip() or None

    input_path = Path(input_csv)
    output_path = Path(output_tsv)

    if not input_path.is_file():
        print(f"Input CSV not found: {input_path}", file=sys.stderr)
        return 1

    output_path.parent.mkdir(parents=True, exist_ok=True)

    csv_encoding = _detect_csv_encoding(input_path, input_encoding)
    completed_ids = _load_completed_original_ids(output_path) if resume else set()
    if resume and completed_ids:
        print(
            f"Resuming: skipping {len(completed_ids)} originalIDs already in {output_path}",
            file=sys.stderr,
        )

    processed = 0
    skipped = 0
    last_written_id = ""
    last_written_name = ""

    output_exists = output_path.is_file() and output_path.stat().st_size > 0
    output_mode = "a" if resume and output_exists else "w"

    try:
        with input_path.open(newline="", encoding=csv_encoding) as fin, output_path.open(
            output_mode, newline="", encoding="utf-8"
        ) as fout:
            header_line = fin.readline()
            if not header_line:
                print("Input CSV has no header row.", file=sys.stderr)
                return 1

            delimiter = input_delimiter or _detect_csv_delimiter(header_line)
            fin.seek(0)
            reader = csv.DictReader(fin, delimiter=delimiter)
            if reader.fieldnames is None:
                print("Input CSV has no header row.", file=sys.stderr)
                return 1

            missing = {"originalID", "scientificName"} - set(reader.fieldnames)
            if missing:
                print(
                    f"Input CSV missing required columns: {', '.join(sorted(missing))}",
                    file=sys.stderr,
                )
                return 1

            writer = csv.DictWriter(
                fout,
                fieldnames=TSV_COLUMNS,
                delimiter="\t",
                extrasaction="ignore",
            )
            if output_mode == "w":
                writer.writeheader()

            for row in reader:
                original_id = row.get("originalID", "")
                scientific_name = (row.get("scientificName") or "").strip()

                if resume and original_id in completed_ids:
                    skipped += 1
                    continue

                if not scientific_name:
                    print(
                        f"Skipping empty scientificName for originalID={original_id!r}",
                        file=sys.stderr,
                    )
                    writer.writerow(empty_row(original_id, ""))
                    last_written_id = original_id
                    last_written_name = ""
                    continue

                data = call_name_backbone(
                    scientific_name,
                    max_retries=max_retries,
                    retry_backoff_seconds=retry_backoff_seconds,
                    delay_seconds=delay_seconds,
                )
                writer.writerow(
                    parse_backbone_response(original_id, scientific_name, data)
                )
                last_written_id = original_id
                last_written_name = scientific_name
                processed += 1

                if progress_every > 0 and processed % progress_every == 0:
                    print(f"Processed {processed} species...", file=sys.stderr)

    except UnicodeDecodeError as exc:
        print(
            f"Encoding error reading CSV ({csv_encoding!r}): {exc}",
            file=sys.stderr,
        )
        if last_written_id:
            print(
                f"Last successful row: originalID={last_written_id!r}, "
                f"scientificName={last_written_name!r}",
                file=sys.stderr,
            )
        print(
            "Try INPUT_CSV_ENCODING=cp1252 (common for Excel on Windows) "
            "and RESUME=true to continue.",
            file=sys.stderr,
        )
        return 1

    print(
        f"Done. Wrote {processed} API lookups to {output_path}"
        + (f" (skipped {skipped} already completed)" if skipped else ""),
        file=sys.stderr,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
