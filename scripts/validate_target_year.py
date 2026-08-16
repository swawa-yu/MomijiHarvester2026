#!/usr/bin/env python3
"""Validate a requested crawl year against the consumer's active year."""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path


def validate_target_year(update_kind: str, target_year: str, manifest_path: Path) -> None:
    if update_kind not in {"same-year", "year-rollover"}:
        raise ValueError("update_kind must be same-year or year-rollover")
    if not re.fullmatch(r"\d{4}", target_year):
        raise ValueError("target_year must be a 4-digit year")
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ValueError(f"invalid consumer manifest: {error}") from error
    academic_year = manifest.get("academicYear") if isinstance(manifest, dict) else None
    match = re.fullmatch(r"(\d{4})年度", academic_year or "")
    if not match:
        raise ValueError("consumer manifest academicYear must have the form YYYY年度")
    active_year = int(match.group(1))
    target = int(target_year)
    expected = active_year if update_kind == "same-year" else active_year + 1
    if target != expected:
        raise ValueError(
            f"{update_kind} requires target_year={expected}, consumer active year is {active_year}"
        )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--update-kind", required=True)
    parser.add_argument("--target-year", required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    args = parser.parse_args()
    try:
        validate_target_year(args.update_kind, args.target_year, args.manifest)
    except ValueError as error:
        parser.error(str(error))
    print("target year gate passed")


if __name__ == "__main__":
    main()
