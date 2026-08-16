#!/usr/bin/env python3
"""Create, apply, and verify deterministic same-year syllabus history."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from copy import deepcopy
from pathlib import Path
from typing import Iterable
from urllib.parse import urlparse

SCHEMA_VERSION = 1
ARTIFACT_KEYS = {"schemaVersion", "base", "target", "changes"}
SNAPSHOT_KEYS = {
    "academicYear", "retrievedAt", "subjectCount", "canonicalSha256",
    "source",
}
RAW_FIELDS = {
    "relative URL", "年度", "開講部局", "講義コード", "科目区分",
    "授業科目名", "担当教員名", "開講キャンパス", "開設期",
    "曜日・時限・講義室", "単位", "使用言語", "学習の段階",
    "対象学生", "授業の目標・概要等", "予習・復習への アドバイス",
    "履修上の注意 受講条件等", "メッセージ", "その他",
}


def canonical_bytes(data: dict) -> bytes:
    return json.dumps(
        data,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def canonical_sha256(data: dict) -> str:
    return hashlib.sha256(canonical_bytes(data)).hexdigest()


def read_json(path: Path, label: str) -> object:
    def reject_duplicate_keys(pairs):
        value = {}
        for key, item in pairs:
            if key in value:
                raise ValueError(f"duplicate JSON key: {key}")
            value[key] = item
        return value

    try:
        return json.loads(
            path.read_text(encoding="utf-8"),
            object_pairs_hook=reject_duplicate_keys,
        )
    except (OSError, json.JSONDecodeError, ValueError) as error:
        raise ValueError(f"invalid {label} JSON: {error}") from error


def _validate_subject_data(data: dict, source: str) -> None:
    parsed_source = urlparse(source) if isinstance(source, str) else None
    if (
        parsed_source is None
        or parsed_source.scheme != "https"
        or not parsed_source.netloc
    ):
        raise ValueError("source must be an HTTPS URL")
    if not data:
        raise ValueError("subject snapshot must not be empty")
    years = set()
    for lecture_code, record in data.items():
        if not isinstance(record, dict) or set(record) != RAW_FIELDS:
            raise ValueError(
                f"subject {lecture_code!r} does not match the 19-field contract"
            )
        if any(not isinstance(value, str) for value in record.values()):
            raise ValueError(
                f"subject {lecture_code!r} contains a non-string value"
            )
        if lecture_code != record["講義コード"]:
            raise ValueError(
                f"subject key {lecture_code!r} does not match its course code"
            )
        if not re.fullmatch(r"\d{4}年度", record["年度"]):
            raise ValueError("年度 must be YYYY年度")
        years.add(record["年度"])
    if len(years) != 1:
        raise ValueError("subject snapshot must contain exactly one academic year")


def validate_manifest(manifest: object) -> dict:
    if not isinstance(manifest, dict):
        raise ValueError("manifest must be an object")
    if manifest.get("schemaVersion") != SCHEMA_VERSION:
        raise ValueError("manifest schemaVersion must be 1")
    data_file = manifest.get("dataFile")
    if (
        not isinstance(data_file, str)
        or Path(data_file).name != data_file
        or not re.fullmatch(
            r"subject_details_main_[A-Za-z0-9._-]+\.json",
            data_file,
        )
    ):
        raise ValueError("manifest dataFile must be a safe generation filename")
    structure_report = manifest.get("structureReport")
    if (
        not isinstance(structure_report, dict)
        or set(structure_report) != {"dataFile", "sha256"}
        or not isinstance(structure_report["dataFile"], str)
        or not re.fullmatch(
            r"subject_structure_[A-Za-z0-9._-]+\.json",
            structure_report["dataFile"],
        )
        or not isinstance(structure_report["sha256"], str)
        or not re.fullmatch(r"[a-f0-9]{64}", structure_report["sha256"])
    ):
        raise ValueError("manifest must reference a validated structure report")
    academic_year = manifest.get("academicYear")
    retrieved_at = manifest.get("retrievedAt")
    subject_count = manifest.get("subjectCount")
    source = manifest.get("source")
    if not isinstance(academic_year, str) or not re.fullmatch(
        r"\d{4}年度", academic_year
    ):
        raise ValueError("manifest academicYear must have the form YYYY年度")
    if not isinstance(retrieved_at, str) or not re.fullmatch(
        r"\d{4}-\d{2}-\d{2}", retrieved_at
    ):
        raise ValueError("manifest retrievedAt must have the form YYYY-MM-DD")
    if (
        not isinstance(subject_count, int)
        or isinstance(subject_count, bool)
        or subject_count <= 0
    ):
        raise ValueError("manifest subjectCount must be a positive integer")
    if not isinstance(source, str):
        raise ValueError("manifest source must be a string")
    return manifest


def validate_snapshot(data: object, manifest: object) -> dict:
    manifest = validate_manifest(manifest)
    if not isinstance(data, dict):
        raise ValueError("subject snapshot must be an object")
    _validate_subject_data(data, manifest["source"])
    if len(data) != manifest["subjectCount"]:
        raise ValueError("manifest subjectCount does not match snapshot")
    years = {record["年度"] for record in data.values()}
    if years != {manifest["academicYear"]}:
        raise ValueError("manifest academicYear does not match snapshot")
    return {
        "academicYear": manifest["academicYear"],
        "retrievedAt": manifest["retrievedAt"],
        "subjectCount": len(data),
        "canonicalSha256": canonical_sha256(data),
        "source": manifest["source"],
    }


def create_diff(
    base_data: object,
    base_manifest: object,
    target_data: object,
    target_manifest: object,
) -> dict:
    base = validate_snapshot(base_data, base_manifest)
    target = validate_snapshot(target_data, target_manifest)
    if base["academicYear"] != target["academicYear"]:
        raise ValueError("history diff requires the same academic year")
    if base["retrievedAt"] >= target["retrievedAt"]:
        raise ValueError("target retrievedAt must be later than base retrievedAt")

    changes = []
    for lecture_code in sorted(set(base_data) | set(target_data)):
        before = base_data.get(lecture_code)
        after = target_data.get(lecture_code)
        if before is None:
            changes.append({
                "lectureCode": lecture_code,
                "type": "added",
                "after": deepcopy(after),
            })
        elif after is None:
            changes.append({
                "lectureCode": lecture_code,
                "type": "removed",
                "before": deepcopy(before),
            })
        elif before != after:
            fields = [
                {
                    "field": field,
                    "before": before[field],
                    "after": after[field],
                }
                for field in sorted(before)
                if before[field] != after[field]
            ]
            changes.append({
                "lectureCode": lecture_code,
                "type": "changed",
                "fields": fields,
            })
    return {
        "schemaVersion": SCHEMA_VERSION,
        "base": base,
        "target": target,
        "changes": changes,
    }


def _validate_snapshot_metadata(value: object, label: str) -> dict:
    if not isinstance(value, dict) or set(value) != SNAPSHOT_KEYS:
        raise ValueError(f"history {label} metadata has an invalid contract")
    if (
        not isinstance(value["academicYear"], str)
        or not re.fullmatch(r"\d{4}年度", value["academicYear"])
        or not isinstance(value["retrievedAt"], str)
        or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", value["retrievedAt"])
        or not isinstance(value["subjectCount"], int)
        or isinstance(value["subjectCount"], bool)
        or value["subjectCount"] <= 0
        or not isinstance(value["canonicalSha256"], str)
        or not re.fullmatch(r"[a-f0-9]{64}", value["canonicalSha256"])
        or not isinstance(value["source"], str)
    ):
        raise ValueError(f"history {label} metadata is invalid")
    return value


def validate_artifact(artifact: object) -> dict:
    if not isinstance(artifact, dict) or set(artifact) != ARTIFACT_KEYS:
        raise ValueError("history artifact has an invalid contract")
    if artifact["schemaVersion"] != SCHEMA_VERSION:
        raise ValueError("history artifact schemaVersion must be 1")
    base = _validate_snapshot_metadata(artifact["base"], "base")
    target = _validate_snapshot_metadata(artifact["target"], "target")
    if base["academicYear"] != target["academicYear"]:
        raise ValueError("history artifact crosses academic years")
    if base["retrievedAt"] >= target["retrievedAt"]:
        raise ValueError("history artifact dates are not increasing")
    changes = artifact["changes"]
    if not isinstance(changes, list):
        raise ValueError("history changes must be a list")
    lecture_codes = []
    for change in changes:
        if not isinstance(change, dict):
            raise ValueError("history change must be an object")
        lecture_code = change.get("lectureCode")
        change_type = change.get("type")
        if not isinstance(lecture_code, str) or not lecture_code:
            raise ValueError("history change lectureCode must be nonempty")
        lecture_codes.append(lecture_code)
        if change_type == "added":
            if set(change) != {"lectureCode", "type", "after"}:
                raise ValueError("invalid added history change")
        elif change_type == "removed":
            if set(change) != {"lectureCode", "type", "before"}:
                raise ValueError("invalid removed history change")
        elif change_type == "changed":
            if set(change) != {"lectureCode", "type", "fields"}:
                raise ValueError("invalid changed history change")
            fields = change["fields"]
            if not isinstance(fields, list) or not fields:
                raise ValueError("changed history entry requires fields")
            names = []
            for field in fields:
                if not isinstance(field, dict) or set(field) != {
                    "field", "before", "after",
                }:
                    raise ValueError("invalid changed history field")
                names.append(field["field"])
                if (
                    not isinstance(field["field"], str)
                    or not isinstance(field["before"], str)
                    or not isinstance(field["after"], str)
                    or field["before"] == field["after"]
                ):
                    raise ValueError("invalid changed history field value")
            if names != sorted(set(names)):
                raise ValueError("changed history fields are not deterministic")
        else:
            raise ValueError("unknown history change type")
    if lecture_codes != sorted(set(lecture_codes)):
        raise ValueError("history changes are not deterministic")
    return artifact


def _assert_snapshot(data: dict, metadata: dict, label: str) -> None:
    if len(data) != metadata["subjectCount"]:
        raise ValueError(f"{label} subject count does not match history")
    if canonical_sha256(data) != metadata["canonicalSha256"]:
        raise ValueError(f"{label} SHA-256 does not match history")
    years = {record.get("年度") for record in data.values()}
    if years != {metadata["academicYear"]}:
        raise ValueError(f"{label} academic year does not match history")
    _validate_subject_data(data, metadata["source"])


def apply_diff(data: object, artifact: object, reverse: bool = False) -> dict:
    if not isinstance(data, dict):
        raise ValueError("subject snapshot must be an object")
    artifact = validate_artifact(artifact)
    start = artifact["target"] if reverse else artifact["base"]
    finish = artifact["base"] if reverse else artifact["target"]
    _assert_snapshot(data, start, "input")
    result = deepcopy(data)
    changes = reversed(artifact["changes"]) if reverse else artifact["changes"]
    for change in changes:
        lecture_code = change["lectureCode"]
        change_type = change["type"]
        if change_type == "added":
            if reverse:
                if result.get(lecture_code) != change["after"]:
                    raise ValueError("added record does not match reverse input")
                del result[lecture_code]
            else:
                if lecture_code in result:
                    raise ValueError("added record already exists")
                result[lecture_code] = deepcopy(change["after"])
        elif change_type == "removed":
            if reverse:
                if lecture_code in result:
                    raise ValueError("removed record already exists in reverse")
                result[lecture_code] = deepcopy(change["before"])
            else:
                if result.get(lecture_code) != change["before"]:
                    raise ValueError("removed record does not match input")
                del result[lecture_code]
        else:
            if lecture_code not in result:
                raise ValueError("changed record is missing")
            record = result[lecture_code]
            for field in change["fields"]:
                expected = field["after"] if reverse else field["before"]
                replacement = field["before"] if reverse else field["after"]
                if record.get(field["field"]) != expected:
                    raise ValueError("changed field does not match input")
                record[field["field"]] = replacement
    _assert_snapshot(result, finish, "result")
    return result


def verify_chain(base_data: object, artifacts: Iterable[object]) -> dict:
    if not isinstance(base_data, dict):
        raise ValueError("subject snapshot must be an object")
    chain = [validate_artifact(artifact) for artifact in artifacts]
    if not chain:
        raise ValueError("history chain must not be empty")
    for previous, following in zip(chain, chain[1:]):
        if following["base"] != previous["target"]:
            raise ValueError("history chain is missing or out of order")
    current = deepcopy(base_data)
    for artifact in chain:
        current = apply_diff(current, artifact)
    restored = deepcopy(current)
    for artifact in reversed(chain):
        restored = apply_diff(restored, artifact, reverse=True)
    if canonical_sha256(restored) != canonical_sha256(base_data):
        raise ValueError("reverse history verification failed")
    return current


def write_json(path: Path, value: object) -> None:
    payload = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        indent=2,
    ) + "\n"
    path.write_text(payload, encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser()
    commands = parser.add_subparsers(dest="command", required=True)
    diff = commands.add_parser("diff")
    diff.add_argument("--base-data", required=True, type=Path)
    diff.add_argument("--base-manifest", required=True, type=Path)
    diff.add_argument("--target-data", required=True, type=Path)
    diff.add_argument("--target-manifest", required=True, type=Path)
    diff.add_argument("--output", required=True, type=Path)
    apply = commands.add_parser("apply")
    apply.add_argument("--base-data", required=True, type=Path)
    apply.add_argument("--diff", required=True, type=Path)
    apply.add_argument("--output", required=True, type=Path)
    verify = commands.add_parser("verify")
    verify.add_argument("--base-data", required=True, type=Path)
    verify.add_argument("--diff", required=True, action="append", type=Path)
    args = parser.parse_args()

    if args.command == "diff":
        artifact = create_diff(
            read_json(args.base_data, "base data"),
            read_json(args.base_manifest, "base manifest"),
            read_json(args.target_data, "target data"),
            read_json(args.target_manifest, "target manifest"),
        )
        write_json(args.output, artifact)
    elif args.command == "apply":
        result = apply_diff(
            read_json(args.base_data, "base data"),
            read_json(args.diff, "history artifact"),
        )
        write_json(args.output, result)
    else:
        result = verify_chain(
            read_json(args.base_data, "base data"),
            [read_json(path, "history artifact") for path in args.diff],
        )
        print(
            f"Verified {len(args.diff)} history artifact(s); "
            f"result SHA-256={canonical_sha256(result)}"
        )


if __name__ == "__main__":
    main()
