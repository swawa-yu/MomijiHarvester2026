import json
import os
import subprocess
import sys
from copy import deepcopy

import pytest

from scripts.subject_history import (
    apply_diff,
    canonical_sha256,
    create_diff,
    read_json,
    validate_artifact,
    verify_chain,
)
from tests.test_exporter import subject


def record(code: str, title: str = "value", year: str = "2026年度") -> dict:
    return subject(code, year).model_copy(update={"title": title}).model_dump(
        by_alias=True
    )


def manifest(data: dict, date: str, year: str = "2026年度") -> dict:
    return {
        "schemaVersion": 1,
        "dataFile": f"subject_details_main_{date}.json",
        "academicYear": year,
        "retrievedAt": date,
        "subjectCount": len(data),
        "source": "https://example.test/syllabus/",
        "structureReport": {
            "dataFile": f"subject_structure_{date}.json",
            "sha256": "a" * 64,
        },
    }


def snapshots():
    base = {
        "10000100": record("10000100", "変更前"),
        "10000200": record("10000200", "削除"),
    }
    target = {
        "10000100": record("10000100", "変更後"),
        "10000300": record("10000300", "追加"),
    }
    return base, target


def test_diff_is_deterministic_and_preserves_raw_values():
    base, target = snapshots()
    first = create_diff(
        base, manifest(base, "2026-04-01"),
        target, manifest(target, "2026-04-02"),
    )
    second = create_diff(
        dict(reversed(list(base.items()))), manifest(base, "2026-04-01"),
        dict(reversed(list(target.items()))), manifest(target, "2026-04-02"),
    )

    assert first == second
    assert [change["type"] for change in first["changes"]] == [
        "changed", "removed", "added",
    ]
    assert first["changes"][0]["fields"] == [{
        "field": "授業科目名",
        "before": "変更前",
        "after": "変更後",
    }]
    assert first["changes"][1]["before"] == base["10000200"]
    assert first["changes"][2]["after"] == target["10000300"]


def test_apply_and_reverse_reconstruct_canonical_snapshots():
    base, target = snapshots()
    artifact = create_diff(
        base, manifest(base, "2026-04-01"),
        target, manifest(target, "2026-04-02"),
    )

    restored_target = apply_diff(base, artifact)
    restored_base = apply_diff(restored_target, artifact, reverse=True)

    assert canonical_sha256(restored_target) == canonical_sha256(target)
    assert canonical_sha256(restored_base) == canonical_sha256(base)


def test_verify_chain_rejects_missing_or_reordered_artifacts():
    base, middle = snapshots()
    final = deepcopy(middle)
    final["10000100"]["メッセージ"] = "年度内の追記"
    first = create_diff(
        base, manifest(base, "2026-04-01"),
        middle, manifest(middle, "2026-04-02"),
    )
    second = create_diff(
        middle, manifest(middle, "2026-04-02"),
        final, manifest(final, "2026-04-03"),
    )

    assert canonical_sha256(verify_chain(base, [first, second])) == (
        canonical_sha256(final)
    )
    with pytest.raises(ValueError, match="missing or out of order"):
        verify_chain(base, [second, first])
    with pytest.raises(ValueError, match="input SHA-256"):
        verify_chain(base, [second])


def test_rejects_cross_year_invalid_records_and_tampering():
    base, target = snapshots()
    with pytest.raises(ValueError, match="same academic year"):
        create_diff(
            base, manifest(base, "2026-04-01"),
            {"10000300": record("10000300", year="2027年度")},
            manifest({"10000300": record("10000300", year="2027年度")},
                     "2027-04-01", "2027年度"),
        )

    broken = deepcopy(base)
    broken["10000100"].pop("その他")
    with pytest.raises(ValueError, match="19-field contract"):
        create_diff(
            broken, manifest(broken, "2026-04-01"),
            target, manifest(target, "2026-04-02"),
        )

    unsafe_manifest = manifest(base, "2026-04-01")
    unsafe_manifest["dataFile"] = "../outside.json"
    with pytest.raises(ValueError, match="safe generation filename"):
        create_diff(
            base, unsafe_manifest,
            target, manifest(target, "2026-04-02"),
        )

    artifact = create_diff(
        base, manifest(base, "2026-04-01"),
        target, manifest(target, "2026-04-02"),
    )
    artifact["changes"][0]["fields"][0]["after"] = "改ざん"
    with pytest.raises(ValueError, match="result SHA-256"):
        apply_diff(base, artifact)


def test_rejects_schema_order_and_duplicate_change_corruption():
    base, target = snapshots()
    artifact = create_diff(
        base, manifest(base, "2026-04-01"),
        target, manifest(target, "2026-04-02"),
    )
    unsupported = {**artifact, "schemaVersion": 2}
    with pytest.raises(ValueError, match="schemaVersion"):
        validate_artifact(unsupported)

    reordered = deepcopy(artifact)
    reordered["changes"] = list(reversed(reordered["changes"]))
    with pytest.raises(ValueError, match="not deterministic"):
        validate_artifact(reordered)

    duplicated = deepcopy(artifact)
    duplicated["changes"].insert(1, deepcopy(duplicated["changes"][0]))
    with pytest.raises(ValueError, match="not deterministic"):
        validate_artifact(duplicated)


def test_artifact_round_trip_is_json_safe():
    base, target = snapshots()
    artifact = create_diff(
        base, manifest(base, "2026-04-01"),
        target, manifest(target, "2026-04-02"),
    )
    decoded = json.loads(json.dumps(artifact, ensure_ascii=False))
    assert apply_diff(base, decoded) == target


def test_cli_diff_apply_verify_and_duplicate_key_rejection(tmp_path):
    base, target = snapshots()
    paths = {
        "base_data": tmp_path / "base.json",
        "base_manifest": tmp_path / "base-manifest.json",
        "target_data": tmp_path / "target.json",
        "target_manifest": tmp_path / "target-manifest.json",
        "diff": tmp_path / "history.json",
        "restored": tmp_path / "restored.json",
    }
    paths["base_data"].write_text(json.dumps(base), encoding="utf-8")
    paths["base_manifest"].write_text(
        json.dumps(manifest(base, "2026-04-01")), encoding="utf-8"
    )
    paths["target_data"].write_text(json.dumps(target), encoding="utf-8")
    paths["target_manifest"].write_text(
        json.dumps(manifest(target, "2026-04-02")), encoding="utf-8"
    )
    environment = {**os.environ, "PYTHONPATH": "."}
    subprocess.run([
        sys.executable, "scripts/subject_history.py", "diff",
        "--base-data", str(paths["base_data"]),
        "--base-manifest", str(paths["base_manifest"]),
        "--target-data", str(paths["target_data"]),
        "--target-manifest", str(paths["target_manifest"]),
        "--output", str(paths["diff"]),
    ], check=True, env=environment)
    subprocess.run([
        sys.executable, "scripts/subject_history.py", "apply",
        "--base-data", str(paths["base_data"]),
        "--diff", str(paths["diff"]),
        "--output", str(paths["restored"]),
    ], check=True, env=environment)
    verified = subprocess.run([
        sys.executable, "scripts/subject_history.py", "verify",
        "--base-data", str(paths["base_data"]),
        "--diff", str(paths["diff"]),
    ], check=True, env=environment, capture_output=True, text=True)
    assert canonical_sha256(read_json(paths["restored"], "restored")) == (
        canonical_sha256(target)
    )
    assert "Verified 1 history artifact" in verified.stdout

    duplicate = tmp_path / "duplicate.json"
    duplicate.write_text('{"10000100":{},"10000100":{}}', encoding="utf-8")
    with pytest.raises(ValueError, match="duplicate JSON key"):
        read_json(duplicate, "duplicate")
