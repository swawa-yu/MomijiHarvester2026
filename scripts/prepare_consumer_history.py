#!/usr/bin/env python3
"""Prepare a verified repo-native history update for the momiji2 consumer."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import tempfile
from pathlib import Path

from scripts.subject_history import (
    canonical_sha256,
    create_diff,
    read_json,
    validate_manifest,
    validate_snapshot,
    verify_chain,
)

INDEX_SCHEMA_VERSION = 1
INDEX_KEYS = {
    "schemaVersion", "academicYear", "baseline", "latest", "artifacts",
}
INDEX_SNAPSHOT_KEYS = {
    "dataFile", "retrievedAt", "subjectCount", "canonicalSha256",
}
ARTIFACT_POINTER_KEYS = {"dataFile", "sha256"}


def _snapshot_pointer(data_file: str, metadata: dict) -> dict:
    return {
        "dataFile": data_file,
        "retrievedAt": metadata["retrievedAt"],
        "subjectCount": metadata["subjectCount"],
        "canonicalSha256": metadata["canonicalSha256"],
    }


def _validate_snapshot_pointer(value: object, label: str) -> dict:
    if not isinstance(value, dict) or set(value) != INDEX_SNAPSHOT_KEYS:
        raise ValueError(f"history index {label} has an invalid contract")
    if (
        not isinstance(value["dataFile"], str)
        or Path(value["dataFile"]).name != value["dataFile"]
        or not re.fullmatch(
            r"subject_details_main_[A-Za-z0-9._-]+\.json",
            value["dataFile"],
        )
        or not isinstance(value["retrievedAt"], str)
        or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", value["retrievedAt"])
        or not isinstance(value["subjectCount"], int)
        or isinstance(value["subjectCount"], bool)
        or value["subjectCount"] <= 0
        or not isinstance(value["canonicalSha256"], str)
        or not re.fullmatch(r"[a-f0-9]{64}", value["canonicalSha256"])
    ):
        raise ValueError(f"history index {label} is invalid")
    return value


def validate_index(value: object, academic_year: str) -> dict:
    if not isinstance(value, dict) or set(value) != INDEX_KEYS:
        raise ValueError("history index has an invalid contract")
    if value["schemaVersion"] != INDEX_SCHEMA_VERSION:
        raise ValueError("history index schemaVersion must be 1")
    if value["academicYear"] != academic_year:
        raise ValueError("history index academicYear does not match update")
    _validate_snapshot_pointer(value["baseline"], "baseline")
    _validate_snapshot_pointer(value["latest"], "latest")
    artifacts = value["artifacts"]
    if not isinstance(artifacts, list):
        raise ValueError("history index artifacts must be a list")
    filenames = []
    for pointer in artifacts:
        if not isinstance(pointer, dict) or set(pointer) != ARTIFACT_POINTER_KEYS:
            raise ValueError("history index artifact pointer is invalid")
        filename = pointer["dataFile"]
        sha256 = pointer["sha256"]
        if (
            not isinstance(filename, str)
            or Path(filename).name != filename
            or not re.fullmatch(r"history_[A-Za-z0-9._-]+\.json", filename)
            or not isinstance(sha256, str)
            or not re.fullmatch(r"[a-f0-9]{64}", sha256)
        ):
            raise ValueError("history index artifact pointer is invalid")
        filenames.append(filename)
    if len(filenames) != len(set(filenames)):
        raise ValueError("history index contains duplicate artifacts")
    if not artifacts and value["baseline"] != value["latest"]:
        raise ValueError("empty history index must have baseline as latest")
    return value


def _json_bytes(value: object) -> bytes:
    return (
        json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n"
    ).encode("utf-8")


def _atomic_write(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="wb",
            dir=path.parent,
            prefix=f".{path.name}.",
            delete=False,
        ) as output:
            temporary = Path(output.name)
            output.write(payload)
        os.replace(temporary, path)
    finally:
        if temporary is not None and temporary.exists():
            temporary.unlink()


def _load_verified_chain(
    consumer_data_dir: Path,
    history_dir: Path,
    index: dict,
) -> tuple[dict, list[dict]]:
    baseline_path = consumer_data_dir / index["baseline"]["dataFile"]
    baseline = read_json(baseline_path, "history baseline")
    if not isinstance(baseline, dict):
        raise ValueError("history baseline must be an object")
    if canonical_sha256(baseline) != index["baseline"]["canonicalSha256"]:
        raise ValueError("history baseline SHA-256 does not match index")
    artifacts = []
    for pointer in index["artifacts"]:
        path = history_dir / pointer["dataFile"]
        payload = path.read_bytes()
        if hashlib.sha256(payload).hexdigest() != pointer["sha256"]:
            raise ValueError("history artifact file SHA-256 does not match index")
        artifact = read_json(path, "history artifact")
        artifacts.append(artifact)
    if artifacts:
        reconstructed = verify_chain(baseline, artifacts)
    else:
        reconstructed = baseline
    if canonical_sha256(reconstructed) != index["latest"]["canonicalSha256"]:
        raise ValueError("history chain result does not match index latest")
    return reconstructed, artifacts


def prepare_history_update(
    consumer_data_dir: Path,
    incoming_manifest_path: Path,
) -> dict[str, object]:
    consumer_data_dir = consumer_data_dir.resolve(strict=True)
    incoming_manifest_path = incoming_manifest_path.resolve(strict=True)
    incoming_manifest = read_json(incoming_manifest_path, "incoming manifest")
    if not isinstance(incoming_manifest, dict):
        raise ValueError("incoming manifest must be an object")
    validate_manifest(incoming_manifest)
    incoming_data_path = incoming_manifest_path.parent / incoming_manifest.get(
        "dataFile", ""
    )
    incoming_data = read_json(incoming_data_path, "incoming data")
    incoming_metadata = validate_snapshot(incoming_data, incoming_manifest)
    academic_year = incoming_metadata["academicYear"]
    year = academic_year.removesuffix("年度")
    history_dir = consumer_data_dir / "history" / year
    index_path = history_dir / "index.json"
    incoming_pointer = _snapshot_pointer(
        incoming_manifest["dataFile"], incoming_metadata
    )

    if not index_path.exists():
        current_manifest_path = consumer_data_dir / "subjectDataManifest.json"
        if current_manifest_path.exists():
            current_manifest = read_json(current_manifest_path, "current manifest")
            if (
                not isinstance(current_manifest, dict)
                or current_manifest.get("academicYear") != academic_year
            ):
                raise ValueError(
                    "academicYear rollover must be handled before history initialization"
                )
        index = {
            "schemaVersion": INDEX_SCHEMA_VERSION,
            "academicYear": academic_year,
            "baseline": incoming_pointer,
            "latest": incoming_pointer,
            "artifacts": [],
        }
        _atomic_write(index_path, _json_bytes(index))
        return {
            "mode": "initialize",
            "indexPath": str(index_path),
            "indexRelativePath": f"data/history/{year}/index.json",
            "artifactPath": None,
            "artifactRelativePath": None,
            "obsoleteDataFile": None,
        }

    index = validate_index(read_json(index_path, "history index"), academic_year)
    current_manifest_path = consumer_data_dir / "subjectDataManifest.json"
    current_manifest = read_json(current_manifest_path, "current manifest")
    if not isinstance(current_manifest, dict):
        raise ValueError("current manifest must be an object")
    validate_manifest(current_manifest)
    current_data_path = consumer_data_dir / current_manifest.get("dataFile", "")
    current_data = read_json(current_data_path, "current data")
    current_metadata = validate_snapshot(current_data, current_manifest)
    current_pointer = _snapshot_pointer(
        current_manifest["dataFile"], current_metadata
    )
    if current_pointer != index["latest"]:
        raise ValueError("current consumer generation does not match index latest")
    reconstructed, existing_artifacts = _load_verified_chain(
        consumer_data_dir,
        history_dir,
        index,
    )
    if canonical_sha256(reconstructed) != canonical_sha256(current_data):
        raise ValueError("history chain does not reconstruct current consumer data")

    artifact = create_diff(
        current_data,
        current_manifest,
        incoming_data,
        incoming_manifest,
    )
    artifact_payload = _json_bytes(artifact)
    artifact_sha256 = hashlib.sha256(artifact_payload).hexdigest()
    artifact_filename = (
        f"history_{current_metadata['retrievedAt']}_"
        f"{incoming_metadata['retrievedAt']}_{artifact_sha256[:12]}.json"
    )
    artifact_path = history_dir / artifact_filename
    if artifact_path.exists() and artifact_path.read_bytes() != artifact_payload:
        raise ValueError("history artifact filename collision")

    prospective_chain = existing_artifacts + [artifact]
    reconstructed_target = verify_chain(
        read_json(
            consumer_data_dir / index["baseline"]["dataFile"],
            "history baseline",
        ),
        prospective_chain,
    )
    if canonical_sha256(reconstructed_target) != incoming_metadata[
        "canonicalSha256"
    ]:
        raise ValueError("prospective history chain does not reconstruct incoming data")

    updated_index = {
        **index,
        "latest": incoming_pointer,
        "artifacts": index["artifacts"] + [{
            "dataFile": artifact_filename,
            "sha256": artifact_sha256,
        }],
    }
    _atomic_write(artifact_path, artifact_payload)
    _atomic_write(index_path, _json_bytes(updated_index))
    obsolete = current_manifest["dataFile"]
    if obsolete == index["baseline"]["dataFile"]:
        obsolete = None
    return {
        "mode": "append",
        "indexPath": str(index_path),
        "indexRelativePath": f"data/history/{year}/index.json",
        "artifactPath": str(artifact_path),
        "artifactRelativePath": (
            f"data/history/{year}/{artifact_filename}"
        ),
        "obsoleteDataFile": obsolete,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--consumer-data-dir", required=True, type=Path)
    parser.add_argument("--incoming-manifest", required=True, type=Path)
    parser.add_argument("--github-output", type=Path)
    args = parser.parse_args()
    result = prepare_history_update(
        args.consumer_data_dir,
        args.incoming_manifest,
    )
    if args.github_output:
        with args.github_output.open("a", encoding="utf-8") as output:
            for key, value in result.items():
                if value is not None:
                    output.write(f"{key}={value}\n")
    else:
        print(json.dumps(result, ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()
