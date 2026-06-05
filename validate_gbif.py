#!/usr/bin/env python3
"""Validate scientific names against the GBIF backbone taxonomy via pygbif."""

from __future__ import annotations

import csv
import os
import sys
import time
from pathlib import Path

import requests
from dotenv import load_dotenv
from pygbif import species

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
            result = species.name_backbone(scientificName=scientific_name)
            if not isinstance(result, dict):
                raise TypeError(f"Unexpected response type: {type(result).__name__}")
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


def main() -> int:
    load_dotenv()

    input_csv = os.getenv("INPUT_CSV", "./data/input.csv")
    output_tsv = os.getenv("OUTPUT_TSV", "./data/output.tsv")
    delay_seconds = _env_float("API_DELAY_SECONDS", 0.5)
    max_retries = _env_int("API_MAX_RETRIES", 3)
    retry_backoff_seconds = _env_float("API_RETRY_BACKOFF_SECONDS", 2.0)

    input_path = Path(input_csv)
    output_path = Path(output_tsv)

    if not input_path.is_file():
        print(f"Input CSV not found: {input_path}", file=sys.stderr)
        return 1

    output_path.parent.mkdir(parents=True, exist_ok=True)

    processed = 0
    with input_path.open(newline="", encoding="utf-8") as fin, output_path.open(
        "w", newline="", encoding="utf-8"
    ) as fout:
        reader = csv.DictReader(fin)
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
        writer.writeheader()

        for row in reader:
            original_id = row.get("originalID", "")
            scientific_name = (row.get("scientificName") or "").strip()

            if not scientific_name:
                print(
                    f"Skipping empty scientificName for originalID={original_id!r}",
                    file=sys.stderr,
                )
                writer.writerow(empty_row(original_id, ""))
                continue

            data = call_name_backbone(
                scientific_name,
                max_retries=max_retries,
                retry_backoff_seconds=retry_backoff_seconds,
                delay_seconds=delay_seconds,
            )
            writer.writerow(parse_backbone_response(original_id, scientific_name, data))
            processed += 1

            if processed % 50 == 0:
                print(f"Processed {processed} names...", file=sys.stderr)

    print(f"Done. Wrote {processed} API lookups to {output_path}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
