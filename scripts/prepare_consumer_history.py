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
    "classificationArtifacts",
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
    classification_artifacts = value["classificationArtifacts"]
    if not isinstance(classification_artifacts, list):
        raise ValueError("history index classificationArtifacts must be a list")
    classification_filenames = []
    for pointer in classification_artifacts:
        if not isinstance(pointer, dict) or set(pointer) != ARTIFACT_POINTER_KEYS:
            raise ValueError("classification artifact pointer is invalid")
        filename = pointer["dataFile"]
        sha256 = pointer["sha256"]
        if (
            not isinstance(filename, str)
            or not re.fullmatch(
                r"classification_[A-Za-z0-9._-]+\.json", filename
            )
            or not isinstance(sha256, str)
            or not re.fullmatch(r"[a-f0-9]{64}", sha256)
        ):
            raise ValueError("classification artifact pointer is invalid")
        classification_filenames.append(filename)
    if len(classification_filenames) != len(set(classification_filenames)):
        raise ValueError("history index contains duplicate classification artifacts")
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
    for pointer in index["classificationArtifacts"]:
        payload = (history_dir / pointer["dataFile"]).read_bytes()
        if hashlib.sha256(payload).hexdigest() != pointer["sha256"]:
            raise ValueError(
                "classification artifact file SHA-256 does not match index"
            )
    return reconstructed, artifacts


def _prepare_classification_artifact(
    artifact_path: Path | None,
    history_dir: Path,
    baseline_data: object | None,
    baseline_manifest: object | None,
    incoming_data: dict,
    incoming_manifest: dict,
) -> tuple[dict | None, Path | None, bytes | None]:
    if artifact_path is None:
        return None, None, None
    artifact_path = artifact_path.resolve(strict=True)
    payload = artifact_path.read_bytes()
    artifact = read_json(artifact_path, "classification artifact")
    expected_keys = {"schemaVersion", "comparisonType", "base", "target", "fields"}
    if isinstance(artifact, dict) and "schemaVersion" not in artifact:
        raise ValueError("classification artifact schemaVersion must be 1 or 2")
    if not isinstance(artifact, dict) or set(artifact) != expected_keys:
        raise ValueError("classification artifact has an invalid contract")
    schema_version = artifact["schemaVersion"]
    if (
        isinstance(schema_version, bool)
        or not isinstance(schema_version, int)
        or schema_version not in {1, 2}
        or not isinstance(artifact["fields"], dict)
    ):
        raise ValueError("classification artifact schemaVersion must be 1 or 2")
    if baseline_data is None or not isinstance(baseline_manifest, dict):
        raise ValueError("classification artifact requires a consumer baseline")
    validation_manifest = baseline_manifest
    if baseline_manifest.get("schemaVersion") is None:
        validation_manifest = {
            **baseline_manifest,
            "schemaVersion": 1,
            "structureReport": {
                "dataFile": "subject_structure_legacy.json",
                "sha256": "0" * 64,
            },
        }
    base_metadata = validate_snapshot(baseline_data, validation_manifest)
    target_metadata = validate_snapshot(incoming_data, incoming_manifest)
    expected_type = (
        "same-academic-year"
        if base_metadata["academicYear"] == target_metadata["academicYear"]
        else "academic-year-rollover"
    )
    for label, observed, expected in (
        ("base", artifact["base"], base_metadata),
        ("target", artifact["target"], target_metadata),
    ):
        if not isinstance(observed, dict) or any(
            observed.get(field) != expected[field]
            for field in (
                "academicYear", "retrievedAt", "subjectCount",
                "canonicalSha256",
            )
        ):
            raise ValueError(
                f"classification artifact {label} does not match generation"
            )
    if artifact["comparisonType"] != expected_type:
        raise ValueError("classification artifact comparisonType is invalid")
    digest = hashlib.sha256(payload).hexdigest()
    filename = (
        f"classification_{base_metadata['retrievedAt']}_"
        f"{target_metadata['retrievedAt']}_{digest[:12]}.json"
    )
    destination = history_dir / filename
    if destination.exists() and destination.read_bytes() != payload:
        raise ValueError("classification artifact filename collision")
    return {"dataFile": filename, "sha256": digest}, destination, payload


def prepare_history_update(
    consumer_data_dir: Path,
    incoming_manifest_path: Path,
    classification_artifact_path: Path | None = None,
    update_kind: str = "same-year",
) -> dict[str, object]:
    if update_kind not in {"same-year", "year-rollover"}:
        raise ValueError("update_kind must be same-year or year-rollover")
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

    if update_kind == "year-rollover" and index_path.exists():
        raise ValueError("year-rollover destination history index already exists")

    if not index_path.exists():
        current_manifest_path = consumer_data_dir / "subjectDataManifest.json"
        current_manifest = None
        current_data = None
        if current_manifest_path.exists():
            current_manifest = read_json(current_manifest_path, "current manifest")
            if not isinstance(current_manifest, dict):
                raise ValueError("current manifest must be an object")
            current_year_value = current_manifest.get("academicYear")
            if not isinstance(current_year_value, str):
                raise ValueError("current manifest academicYear must be a string")
            current_year = current_year_value.removesuffix("年度")
            if current_year != year:
                if update_kind != "year-rollover":
                    raise ValueError(
                        "academicYear rollover must be handled before history initialization"
                    )
                try:
                    valid_rollover = int(year) == int(current_year) + 1
                except ValueError:
                    valid_rollover = False
                if not valid_rollover:
                    raise ValueError(
                        "year-rollover requires the immediately following academic year"
                    )
            elif update_kind == "year-rollover":
                raise ValueError(
                    "year-rollover requires a different academic year"
                )
            current_data = read_json(
                consumer_data_dir / current_manifest.get("dataFile", ""),
                "current data",
            )
            validation_manifest = current_manifest
            if current_manifest.get("schemaVersion") is None:
                validation_manifest = {
                    **current_manifest,
                    "schemaVersion": 1,
                    "structureReport": {
                        "dataFile": "subject_structure_legacy.json",
                        "sha256": "0" * 64,
                    },
                }
            current_metadata = validate_snapshot(current_data, validation_manifest)
            current_pointer = _snapshot_pointer(
                current_manifest["dataFile"], current_metadata
            )
        if update_kind == "year-rollover":
            if current_manifest is None or current_data is None:
                raise ValueError("year-rollover requires an active consumer generation")
            old_year = current_metadata["academicYear"].removesuffix("年度")
            old_index_path = consumer_data_dir / "history" / old_year / "index.json"
            old_index = None
            if old_index_path.exists():
                old_index = validate_index(
                    read_json(old_index_path, "history index"),
                    current_metadata["academicYear"],
                )
                if old_index["latest"] != current_pointer:
                    raise ValueError("old history index latest does not match active generation")
                old_reconstructed, _ = _load_verified_chain(
                    consumer_data_dir,
                    old_index_path.parent,
                    old_index,
                )
                if canonical_sha256(old_reconstructed) != canonical_sha256(current_data):
                    raise ValueError("old history chain does not reconstruct current consumer data")
            old_index_payload = None
            old_index_relative_path = f"data/history/{old_year}/index.json"
            if old_index is None:
                old_index = {
                    "schemaVersion": INDEX_SCHEMA_VERSION,
                    "academicYear": current_metadata["academicYear"],
                    "baseline": current_pointer,
                    "latest": current_pointer,
                    "artifacts": [],
                    "classificationArtifacts": [],
                }
                old_index_payload = _json_bytes(old_index)
            classification_pointer, classification_path, classification_payload = (
                _prepare_classification_artifact(
                    classification_artifact_path,
                    history_dir,
                    current_data,
                    current_manifest,
                    incoming_data,
                    incoming_manifest,
                )
            )
            new_index = {
                "schemaVersion": INDEX_SCHEMA_VERSION,
                "academicYear": academic_year,
                "baseline": incoming_pointer,
                "latest": incoming_pointer,
                "artifacts": [],
                "classificationArtifacts": (
                    [classification_pointer] if classification_pointer else []
                ),
            }
            if classification_path is not None and classification_payload is not None:
                _atomic_write(classification_path, classification_payload)
            if old_index_payload is not None:
                _atomic_write(old_index_path, old_index_payload)
            _atomic_write(history_dir / "index.json", _json_bytes(new_index))
            return {
                "mode": "rollover",
                "indexPath": str(index_path),
                "indexRelativePath": f"data/history/{year}/index.json",
                "previousIndexRelativePath": old_index_relative_path,
                "artifactPath": None,
                "artifactRelativePath": None,
                "classificationRelativePath": (
                    f"data/history/{year}/{classification_path.name}"
                    if classification_path else None
                ),
                "obsoleteDataFile": None,
            }
        if (
            current_manifest is not None
            and current_data is not None
            and current_metadata["academicYear"] == academic_year
            and current_pointer != incoming_pointer
        ):
            artifact = create_diff(
                current_data,
                validation_manifest,
                incoming_data,
                incoming_manifest,
            )
            classification_pointer, classification_path, classification_payload = (
                _prepare_classification_artifact(
                    classification_artifact_path,
                    history_dir,
                    current_data,
                    current_manifest,
                    incoming_data,
                    incoming_manifest,
                )
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
            if canonical_sha256(verify_chain(current_data, [artifact])) != (
                incoming_metadata["canonicalSha256"]
            ):
                raise ValueError(
                    "prospective history chain does not reconstruct incoming data"
                )
            index = {
                "schemaVersion": INDEX_SCHEMA_VERSION,
                "academicYear": academic_year,
                "baseline": current_pointer,
                "latest": incoming_pointer,
                "artifacts": [{
                    "dataFile": artifact_filename,
                    "sha256": artifact_sha256,
                }],
                "classificationArtifacts": (
                    [classification_pointer] if classification_pointer else []
                ),
            }
            if classification_path is not None and classification_payload is not None:
                _atomic_write(classification_path, classification_payload)
            _atomic_write(artifact_path, artifact_payload)
            _atomic_write(index_path, _json_bytes(index))
            return {
                "mode": "initialize",
                "indexPath": str(index_path),
                "indexRelativePath": f"data/history/{year}/index.json",
                "artifactPath": str(artifact_path),
                "artifactRelativePath": f"data/history/{year}/{artifact_filename}",
                "classificationRelativePath": (
                    f"data/history/{year}/{classification_path.name}"
                    if classification_path else None
                ),
                "obsoleteDataFile": None,
                "previousIndexRelativePath": None,
            }
        classification_pointer, classification_path, classification_payload = (
            _prepare_classification_artifact(
                classification_artifact_path,
                history_dir,
                current_data,
                current_manifest,
                incoming_data,
                incoming_manifest,
            )
        )
        index = {
            "schemaVersion": INDEX_SCHEMA_VERSION,
            "academicYear": academic_year,
            "baseline": incoming_pointer,
            "latest": incoming_pointer,
            "artifacts": [],
            "classificationArtifacts": (
                [classification_pointer] if classification_pointer else []
            ),
        }
        if classification_path is not None and classification_payload is not None:
            _atomic_write(classification_path, classification_payload)
        _atomic_write(index_path, _json_bytes(index))
        return {
            "mode": "initialize",
            "indexPath": str(index_path),
            "indexRelativePath": f"data/history/{year}/index.json",
            "artifactPath": None,
            "artifactRelativePath": None,
            "classificationRelativePath": (
                f"data/history/{year}/{classification_path.name}"
                if classification_path else None
            ),
            "obsoleteDataFile": None,
            "previousIndexRelativePath": None,
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
    classification_pointer, classification_path, classification_payload = (
        _prepare_classification_artifact(
            classification_artifact_path,
            history_dir,
            current_data,
            current_manifest,
            incoming_data,
            incoming_manifest,
        )
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
        "classificationArtifacts": index["classificationArtifacts"] + (
            [classification_pointer] if classification_pointer else []
        ),
    }
    if classification_path is not None and classification_payload is not None:
        _atomic_write(classification_path, classification_payload)
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
        "classificationRelativePath": (
            f"data/history/{year}/{classification_path.name}"
            if classification_path else None
        ),
        "obsoleteDataFile": obsolete,
        "previousIndexRelativePath": None,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--consumer-data-dir", required=True, type=Path)
    parser.add_argument("--incoming-manifest", required=True, type=Path)
    parser.add_argument("--classification-artifact", type=Path)
    parser.add_argument(
        "--update-kind", choices=("same-year", "year-rollover"), default="same-year"
    )
    parser.add_argument("--github-output", type=Path)
    args = parser.parse_args()
    result = prepare_history_update(
        args.consumer_data_dir,
        args.incoming_manifest,
        args.classification_artifact,
        args.update_kind,
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
