#!/usr/bin/env python3
"""Validate and locate the single generation produced by a crawl run."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path

SAFE_DATA_FILENAME = re.compile(
    r"^subject_details_main_[A-Za-z0-9._-]+\.json$"
)
SAFE_DEPARTMENT_FILENAME = re.compile(
    r"^department_constants_[A-Za-z0-9._-]+\.json$"
)
SAFE_STRUCTURE_FILENAME = re.compile(
    r"^subject_structure_[A-Za-z0-9._-]+\.json$"
)


def _regular_file(path: Path, label: str) -> Path:
    if path.is_symlink() or not path.is_file():
        raise ValueError(f"{label} must be a regular file: {path}")
    return path.resolve(strict=True)


def _child_file(
    output_dir: Path,
    filename: object,
    label: str,
    filename_pattern: re.Pattern[str],
) -> Path:
    if (
        not isinstance(filename, str)
        or not filename
        or Path(filename).name != filename
        or not filename_pattern.fullmatch(filename)
    ):
        raise ValueError(f"{label} must be a safe generation filename")
    candidate = output_dir / filename
    resolved = _regular_file(candidate, label)
    if resolved.parent != output_dir:
        raise ValueError(
            f"{label} must be directly inside the output directory"
        )
    return resolved


def _read_json(path: Path, label: str) -> object:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ValueError(f"Invalid {label} JSON: {error}") from error


def resolve_artifacts(output_dir: Path) -> dict[str, str | int]:
    output_dir = output_dir.resolve(strict=True)
    if not output_dir.is_dir() or output_dir.is_symlink():
        raise ValueError("output directory must be a real directory")

    manifest_path = _regular_file(
        output_dir / "subjectDataManifest.json", "manifest"
    )
    if manifest_path.parent != output_dir:
        raise ValueError(
            "manifest must be directly inside the output directory"
        )
    manifest = _read_json(manifest_path, "manifest")
    if not isinstance(manifest, dict):
        raise ValueError("manifest must be an object")

    data_path = _child_file(
        output_dir,
        manifest.get("dataFile"),
        "manifest dataFile",
        SAFE_DATA_FILENAME,
    )
    academic_year = manifest.get("academicYear")
    if not isinstance(academic_year, str):
        raise ValueError("manifest academicYear must be a string")
    year_match = re.fullmatch(r"(\d{4})年度", academic_year)
    if not year_match:
        raise ValueError("manifest academicYear must have the form YYYY年度")
    retrieved_at = manifest.get("retrievedAt")
    if not isinstance(retrieved_at, str) or not re.fullmatch(
        r"\d{4}-\d{2}-\d{2}", retrieved_at
    ):
        raise ValueError("manifest retrievedAt must have the form YYYY-MM-DD")
    subject_count = manifest.get("subjectCount")
    if (
        not isinstance(subject_count, int)
        or isinstance(subject_count, bool)
        or subject_count <= 0
    ):
        raise ValueError("manifest subjectCount must be a positive integer")

    envelopes = sorted(
        path
        for path in output_dir.iterdir()
        if SAFE_DEPARTMENT_FILENAME.fullmatch(path.name)
    )
    if len(envelopes) != 1:
        raise ValueError("expected exactly one department envelope")
    departments_path = _regular_file(envelopes[0], "department envelope")
    if departments_path.parent != output_dir:
        raise ValueError(
            "department envelope must be directly inside the output directory"
        )
    envelope = _read_json(departments_path, "department envelope")
    if not isinstance(envelope, dict) or not isinstance(
        envelope.get("subjectData"), dict
    ):
        raise ValueError("department envelope must contain subjectData")
    if envelope["subjectData"].get("dataFile") != manifest["dataFile"]:
        raise ValueError(
            "department envelope does not select the manifest data file"
        )
    if (
        envelope.get("academicYear") != academic_year
        or envelope.get("retrievedAt") != retrieved_at
    ):
        raise ValueError(
            "department envelope does not match manifest year/date"
        )

    data_sha256 = hashlib.sha256(data_path.read_bytes()).hexdigest()
    if envelope["subjectData"].get("sha256") != data_sha256:
        raise ValueError(
            "department envelope hash does not match manifest data"
        )
    if envelope["subjectData"].get("subjectCount") != subject_count:
        raise ValueError("department envelope count does not match manifest")

    if manifest.get("schemaVersion") != 1:
        raise ValueError("manifest schemaVersion must be 1")
    structure_binding = manifest.get("structureReport")
    if not isinstance(structure_binding, dict):
        raise ValueError("manifest must contain structureReport")
    structure_path = _child_file(
        output_dir,
        structure_binding.get("dataFile"),
        "structure report",
        SAFE_STRUCTURE_FILENAME,
    )
    structure_sha256 = hashlib.sha256(structure_path.read_bytes()).hexdigest()
    if structure_binding.get("sha256") != structure_sha256:
        raise ValueError("structure report hash does not match manifest")
    structure_envelope = _read_json(structure_path, "structure report")
    if (
        not isinstance(structure_envelope, dict)
        or structure_envelope.get("schemaVersion") != 1
        or not isinstance(structure_envelope.get("subjectData"), dict)
        or not isinstance(structure_envelope.get("structure"), dict)
    ):
        raise ValueError("structure report must use schemaVersion 1")
    structure_subject = structure_envelope["subjectData"]
    if (
        structure_envelope.get("academicYear") != academic_year
        or structure_envelope.get("retrievedAt") != retrieved_at
        or structure_subject.get("dataFile") != manifest["dataFile"]
        or structure_subject.get("sha256") != data_sha256
        or structure_subject.get("subjectCount") != subject_count
        or structure_envelope["structure"].get("subjectPageCount")
        != subject_count
    ):
        raise ValueError("structure report does not match manifest generation")
    structure = structure_envelope["structure"]
    if structure.get("missingHeaders") != []:
        raise ValueError("structure report contains missing headers")
    unknown_headers = structure.get("unknownHeaders", [])
    if unknown_headers:
        observed_headers = structure.get("observedHeaders")
        header_presence = structure.get("headerPresence")
        if (
            not isinstance(observed_headers, list)
            or not isinstance(header_presence, dict)
            or not set(unknown_headers).issubset(observed_headers)
            or any(header not in header_presence for header in unknown_headers)
        ):
            raise ValueError("structure report has inconsistent unknown headers")
        for header in unknown_headers:
            presence = header_presence[header]
            if (
                not isinstance(presence, dict)
                or presence.get("presentCount", 0) <= 0
                or presence.get("presenceRate")
                != presence["presentCount"] / subject_count
                or presence.get("emptyRate")
                != presence.get("emptyCount", -1) / subject_count
            ):
                raise ValueError("structure report has invalid unknown header presence")

    return {
        "manifest_path": str(manifest_path),
        "data_path": str(data_path),
        "departments_path": str(departments_path),
        "structure_path": str(structure_path),
        "structure_sha256": structure_sha256,
        "data_file": manifest["dataFile"],
        "academic_year": academic_year,
        "year": year_match.group(1),
        "retrieved_at": retrieved_at,
        "subject_count": subject_count,
        "data_sha256": data_sha256,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument("--github-output", type=Path)
    args = parser.parse_args()
    result = resolve_artifacts(args.output_dir)
    if args.github_output:
        with args.github_output.open("a", encoding="utf-8") as output:
            for key, value in result.items():
                if any(character in str(value) for character in "\r\n\0"):
                    raise ValueError(f"unsafe GitHub output value: {key}")
                output.write(f"{key}={value}\n")
    else:
        print(json.dumps(result, ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()
