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


def write_generation(
    tmp_path: Path, year: int = 2026, retrieved_at: str = "2026-08-06"
) -> tuple[Path, dict]:
    academic_year = f"{year}年度"
    data_file = f"subject_details_main_{year}-08-06_deadbeef.json"
    data = json.dumps({"1": {"年度": academic_year}}).encode("utf-8") + b"\n"
    (tmp_path / data_file).write_bytes(data)
    manifest = {
        "schemaVersion": 1,
        "dataFile": data_file,
        "academicYear": academic_year,
        "retrievedAt": retrieved_at,
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
    structure = {
        "schemaVersion": 1,
        "academicYear": manifest["academicYear"],
        "retrievedAt": manifest["retrievedAt"],
        "subjectData": {
            "dataFile": data_file,
            "sha256": hashlib.sha256(data).hexdigest(),
            "subjectCount": 1,
        },
        "structure": {
            "subjectPageCount": 1,
            "unknownHeaders": [],
            "missingHeaders": [],
        },
    }
    structure_bytes = json.dumps(structure).encode("utf-8")
    structure_file = "subject_structure_generation.json"
    (tmp_path / structure_file).write_bytes(structure_bytes)
    manifest["structureReport"] = {
        "dataFile": structure_file,
        "sha256": hashlib.sha256(structure_bytes).hexdigest(),
    }
    (tmp_path / "subjectDataManifest.json").write_text(
        json.dumps(manifest), encoding="utf-8"
    )
    return tmp_path, manifest


def test_resolve_artifacts_returns_verified_generation(tmp_path: Path):
    output_dir, manifest = write_generation(tmp_path)

    result = resolve_artifacts(output_dir)

    assert result["data_file"] == manifest["dataFile"]
    assert result["year"] == "2026"
    assert result["subject_count"] == 1
    assert result["structure_path"].endswith(
        manifest["structureReport"]["dataFile"]
    )
    assert result["structure_sha256"] == manifest["structureReport"]["sha256"]


def test_resolve_artifacts_accepts_verified_unknown_header(tmp_path: Path):
    output_dir, manifest = write_generation(tmp_path)
    structure_path = output_dir / manifest["structureReport"]["dataFile"]
    structure = json.loads(structure_path.read_text(encoding="utf-8"))
    structure["structure"].update({
        "observedHeaders": ["追加項目"],
        "unknownHeaders": ["追加項目"],
        "headerPresence": {
            "追加項目": {
                "presentCount": 1, "presenceRate": 1.0,
                "emptyCount": 0, "emptyRate": 0.0,
            }
        },
    })
    payload = json.dumps(structure).encode("utf-8")
    structure_path.write_bytes(payload)
    manifest["structureReport"]["sha256"] = hashlib.sha256(payload).hexdigest()
    (output_dir / "subjectDataManifest.json").write_text(
        json.dumps(manifest), encoding="utf-8"
    )
    assert resolve_artifacts(output_dir)["subject_count"] == 1


def test_resolve_artifacts_returns_verified_2027_generation(tmp_path: Path):
    output_dir, manifest = write_generation(
        tmp_path, year=2027, retrieved_at="2027-08-06"
    )

    result = resolve_artifacts(output_dir)

    assert result["year"] == "2027"
    assert result["academic_year"] == "2027年度"
    assert result["data_file"] == "subject_details_main_2027-08-06_deadbeef.json"
    assert result["data_file"] == manifest["dataFile"]
    assert result["subject_count"] == 1
    assert Path(result["departments_path"]).name == (
        "department_constants_generation.json"
    )
    assert Path(result["structure_path"]).name == (
        "subject_structure_generation.json"
    )


def test_resolve_artifacts_rejects_structure_report_from_other_generation(
        tmp_path: Path):
    output_dir, manifest = write_generation(tmp_path)
    structure_path = output_dir / manifest["structureReport"]["dataFile"]
    structure = json.loads(structure_path.read_text(encoding="utf-8"))
    structure["subjectData"]["sha256"] = "0" * 64
    payload = json.dumps(structure).encode("utf-8")
    structure_path.write_bytes(payload)
    manifest["structureReport"]["sha256"] = hashlib.sha256(payload).hexdigest()
    (output_dir / "subjectDataManifest.json").write_text(
        json.dumps(manifest), encoding="utf-8"
    )

    with pytest.raises(ValueError, match="does not match manifest generation"):
        resolve_artifacts(output_dir)


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
            (" M", "data/subject_structure.json"),
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


def test_consumer_diff_allows_only_scoped_history_and_obsolete_data():
    data_file = "subject_details_main_2026-08-06_deadbeef.json"
    obsolete = "subject_details_main_2026-08-05_cafebabe.json"
    history_paths = (
        "data/history/2026/index.json",
        "data/history/2026/history_2026-08-05_2026-08-06_deadbeef.json",
        "data/history/2026/classification_2026-08-05_2026-08-06_cafebabe.json",
    )
    assert_allowed_changes(
        [
            ("??", history_paths[0]),
            ("??", history_paths[1]),
            ("??", history_paths[2]),
            (" D", f"data/{obsolete}"),
        ],
        data_file,
        history_paths,
        obsolete,
    )
    assert_allowed_patch_changes(
        [
            ("A", history_paths[0]),
            ("A", history_paths[1]),
            ("A", history_paths[2]),
            ("D", f"data/{obsolete}"),
        ],
        data_file,
        history_paths,
        obsolete,
    )
    with pytest.raises(ValueError, match="unsafe history path"):
        assert_allowed_changes(
            [("??", "data/history/../../README.md")],
            data_file,
            ("data/history/../../README.md",),
        )
    with pytest.raises(ValueError, match="different safe generation"):
        assert_allowed_changes([], data_file, (), data_file)
