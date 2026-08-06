import hashlib
import json
from pathlib import Path

import pytest

from scripts.resolve_generation_artifacts import resolve_artifacts
from scripts.validate_consumer_update_diff import (
    assert_allowed_changes,
    assert_allowed_patch_changes,
    parse_name_status,
    parse_porcelain,
)


def write_generation(tmp_path: Path) -> tuple[Path, dict]:
    data_file = "subject_details_main_2026-08-06_deadbeef.json"
    data = '{"1": {"年度": "2026年度"}}\n'.encode("utf-8")
    (tmp_path / data_file).write_bytes(data)
    manifest = {
        "dataFile": data_file,
        "academicYear": "2026年度",
        "retrievedAt": "2026-08-06",
        "subjectCount": 1,
        "source": "https://example.test/",
    }
    (tmp_path / "subjectDataManifest.json").write_text(
        json.dumps(manifest), encoding="utf-8"
    )
    envelope = {
        "academicYear": manifest["academicYear"],
        "retrievedAt": manifest["retrievedAt"],
        "subjectData": {
            "dataFile": data_file,
            "sha256": hashlib.sha256(data).hexdigest(),
            "subjectCount": 1,
        },
    }
    (tmp_path / "department_constants_generation.json").write_text(
        json.dumps(envelope), encoding="utf-8"
    )
    return tmp_path, manifest


def test_resolve_artifacts_returns_verified_generation(tmp_path: Path):
    output_dir, manifest = write_generation(tmp_path)

    result = resolve_artifacts(output_dir)

    assert result["data_file"] == manifest["dataFile"]
    assert result["year"] == "2026"
    assert result["subject_count"] == 1


def test_resolve_artifacts_rejects_ambiguous_envelopes(tmp_path: Path):
    output_dir, _ = write_generation(tmp_path)
    (output_dir / "department_constants_second.json").write_text(
        "{}", encoding="utf-8"
    )

    with pytest.raises(ValueError, match="exactly one department envelope"):
        resolve_artifacts(output_dir)


def test_resolve_artifacts_rejects_path_escape(tmp_path: Path):
    output_dir, manifest = write_generation(tmp_path)
    manifest["dataFile"] = "../outside.json"
    (output_dir / "subjectDataManifest.json").write_text(
        json.dumps(manifest), encoding="utf-8"
    )

    with pytest.raises(ValueError, match="safe generation filename"):
        resolve_artifacts(output_dir)


def test_resolve_artifacts_rejects_output_injection_filename(tmp_path: Path):
    output_dir, manifest = write_generation(tmp_path)
    manifest["dataFile"] = "subject_details_main_2026\ninjected.json"
    (output_dir / "subjectDataManifest.json").write_text(
        json.dumps(manifest), encoding="utf-8"
    )

    with pytest.raises(ValueError, match="safe generation filename"):
        resolve_artifacts(output_dir)


def test_consumer_diff_allowlist_rejects_deletion_and_unknown_file():
    assert_allowed_changes(
        [
            ("A ", "data/subject_details_main_2026-08-06_deadbeef.json"),
            (" M", "data/subjectDataManifest.json"),
            (" M", "data/department_constants.json"),
            (" M", "data/derivedSubjectConstants.json"),
            (" M", "src/types/subjectConstants.ts"),
            (" M", "src/subject/activeSubjectData.ts"),
            (" M", "src/types/rawSubjectProperties.ts"),
        ],
        "subject_details_main_2026-08-06_deadbeef.json",
    )
    with pytest.raises(ValueError, match="D  data/subjectDataManifest.json"):
        assert_allowed_changes(
            [("D ", "data/subjectDataManifest.json")],
            "subject_details_main_2026-08-06_deadbeef.json",
        )
    with pytest.raises(ValueError, match="README.md"):
        assert_allowed_changes(
            [("M", "README.md")],
            "subject_details_main_2026-08-06_deadbeef.json",
        )


def test_consumer_diff_parser_allows_only_known_untracked_paths():
    data_file = "subject_details_main_2026-08-06_deadbeef.json"
    changes = parse_porcelain(
        (
            f"?? data/{data_file}\0"
            " M data/subjectDataManifest.json\0"
            "A  data/department_constants.json\0"
        ).encode()
    )
    assert_allowed_changes(changes, data_file)

    unknown = parse_porcelain(b"?? data/unexpected.json\0")
    with pytest.raises(ValueError, match="data/unexpected.json"):
        assert_allowed_changes(unknown, data_file)


def test_consumer_branch_diff_rejects_deletions_and_renames():
    data_file = "subject_details_main_2026-08-06_deadbeef.json"
    allowed = parse_name_status(
        f"A\tdata/{data_file}\0M\tdata/subjectDataManifest.json\0".encode()
    )
    assert_allowed_patch_changes(allowed, data_file)

    deleted = parse_name_status(b"D\tdata/subjectDataManifest.json\0")
    with pytest.raises(ValueError, match="D data/subjectDataManifest.json"):
        assert_allowed_patch_changes(deleted, data_file)
