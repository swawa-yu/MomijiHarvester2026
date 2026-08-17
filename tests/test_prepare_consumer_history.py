import hashlib
import json
import subprocess
import sys
from copy import deepcopy
from pathlib import Path

import pytest

from scripts.prepare_consumer_history import prepare_history_update
from scripts.subject_history import canonical_sha256, read_json, verify_chain
from tests.test_subject_history import manifest, snapshots


def test_cli_module_help_runs_from_repository_root():
    result = subprocess.run(
        [sys.executable, "-m", "scripts.prepare_consumer_history", "--help"],
        cwd=Path(__file__).parents[1],
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert "--consumer-data-dir" in result.stdout


def write_classification_artifact(
    path: Path,
    base: dict,
    base_manifest: dict,
    target: dict,
    target_manifest: dict,
    schema_version: int = 1,
) -> Path:
    artifact = {
        "schemaVersion": schema_version,
        "comparisonType": (
            "same-academic-year"
            if base_manifest["academicYear"] == target_manifest["academicYear"]
            else "academic-year-rollover"
        ),
        "base": {
            "academicYear": base_manifest["academicYear"],
            "retrievedAt": base_manifest["retrievedAt"],
            "subjectCount": len(base),
            "canonicalSha256": canonical_sha256(base),
        },
        "target": {
            "academicYear": target_manifest["academicYear"],
            "retrievedAt": target_manifest["retrievedAt"],
            "subjectCount": len(target),
            "canonicalSha256": canonical_sha256(target),
        },
        "fields": {},
    }
    path.write_text(json.dumps(artifact), encoding="utf-8")
    return path


def write_generation(directory: Path, data: dict, date: str) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    academic_year = next(iter(data.values()))["年度"]
    metadata = manifest(data, date, academic_year)
    data_path = directory / metadata["dataFile"]
    manifest_path = directory / f"manifest-{date}.json"
    data_path.write_text(json.dumps(data), encoding="utf-8")
    manifest_path.write_text(json.dumps(metadata), encoding="utf-8")
    return manifest_path


def install_generation(
    consumer_data: Path,
    source_manifest: Path,
) -> None:
    metadata = json.loads(source_manifest.read_text(encoding="utf-8"))
    source_data = source_manifest.parent / metadata["dataFile"]
    (consumer_data / metadata["dataFile"]).write_bytes(source_data.read_bytes())
    (consumer_data / "subjectDataManifest.json").write_text(
        json.dumps(metadata), encoding="utf-8"
    )


def test_initializes_then_appends_verified_history_chain(tmp_path: Path):
    consumer_data = tmp_path / "consumer" / "data"
    incoming = tmp_path / "incoming"
    base, middle = snapshots()
    final = deepcopy(middle)
    final["10000100"]["メッセージ"] = "追記"

    base_manifest = write_generation(incoming, base, "2026-04-01")
    with pytest.raises(FileNotFoundError):
        prepare_history_update(consumer_data.parent / "missing", base_manifest)


def test_history_lifecycle_and_obsolete_latest(tmp_path: Path):
    consumer_data = tmp_path / "consumer" / "data"
    consumer_data.mkdir(parents=True)
    incoming = tmp_path / "incoming"
    base, middle = snapshots()
    final = deepcopy(middle)
    final["10000100"]["メッセージ"] = "追記"

    base_manifest = write_generation(incoming, base, "2026-04-01")
    first = prepare_history_update(consumer_data, base_manifest)
    assert first["mode"] == "initialize"
    assert first["artifactPath"] is None
    install_generation(consumer_data, base_manifest)

    middle_manifest = write_generation(incoming, middle, "2026-04-02")
    second = prepare_history_update(consumer_data, middle_manifest)
    assert second["mode"] == "append"
    assert second["obsoleteDataFile"] is None
    install_generation(consumer_data, middle_manifest)

    final_manifest = write_generation(incoming, final, "2026-04-03")
    third = prepare_history_update(consumer_data, final_manifest)
    assert third["mode"] == "append"
    assert third["obsoleteDataFile"] == manifest(middle, "2026-04-02")[
        "dataFile"
    ]

    index = read_json(
        consumer_data / "history" / "2026" / "index.json",
        "history index",
    )
    artifacts = [
        read_json(
            consumer_data / "history" / "2026" / pointer["dataFile"],
            "history artifact",
        )
        for pointer in index["artifacts"]
    ]
    restored = verify_chain(base, artifacts)
    assert canonical_sha256(restored) == canonical_sha256(final)


def test_initialization_keeps_same_year_legacy_regression_fixture(tmp_path: Path):
    consumer_data = tmp_path / "consumer" / "data"
    consumer_data.mkdir(parents=True)
    incoming = tmp_path / "incoming"
    base, target = snapshots()
    legacy_manifest = manifest(base, "2026-04-01")
    legacy_manifest.pop("schemaVersion")
    legacy_manifest.pop("structureReport")
    (consumer_data / legacy_manifest["dataFile"]).write_text(
        json.dumps(base), encoding="utf-8"
    )
    (consumer_data / "subjectDataManifest.json").write_text(
        json.dumps(legacy_manifest), encoding="utf-8"
    )
    incoming_manifest = write_generation(incoming, target, "2026-04-02")
    incoming_metadata = json.loads(incoming_manifest.read_text(encoding="utf-8"))
    classification = write_classification_artifact(
        tmp_path / "classification.json",
        base,
        legacy_manifest,
        target,
        incoming_metadata,
    )

    result = prepare_history_update(
        consumer_data,
        incoming_manifest,
        classification,
    )

    assert result["mode"] == "initialize"
    assert result["obsoleteDataFile"] is None
    assert result["classificationRelativePath"].startswith(
        "data/history/2026/classification_"
    )
    index = read_json(
        consumer_data / "history" / "2026" / "index.json",
        "history index",
    )
    assert len(index["classificationArtifacts"]) == 1


def test_fresh_same_year_preserves_active_as_baseline_and_appends_first_artifact(
    tmp_path: Path,
):
    consumer_data = tmp_path / "consumer" / "data"
    consumer_data.mkdir(parents=True)
    incoming = tmp_path / "incoming"
    base, target = snapshots()
    active_manifest = write_generation(incoming, base, "2026-04-07")
    install_generation(consumer_data, active_manifest)
    target_manifest = write_generation(incoming, target, "2026-08-16")
    classification = write_classification_artifact(
        tmp_path / "classification.json",
        base,
        json.loads(active_manifest.read_text(encoding="utf-8")),
        target,
        json.loads(target_manifest.read_text(encoding="utf-8")),
    )
    active_data_file = json.loads(active_manifest.read_text(encoding="utf-8"))["dataFile"]

    result = prepare_history_update(consumer_data, target_manifest, classification)

    assert result["mode"] == "initialize"
    assert result["artifactPath"] is not None
    assert result["artifactRelativePath"].startswith("data/history/2026/history_")
    assert result["obsoleteDataFile"] is None
    index = read_json(consumer_data / "history" / "2026" / "index.json", "index")
    assert index["baseline"]["dataFile"] == active_data_file
    assert index["latest"]["dataFile"] != active_data_file
    assert len(index["artifacts"]) == 1
    assert len(index["classificationArtifacts"]) == 1
    classification_file = index["classificationArtifacts"][0]["dataFile"]
    assert classification_file.startswith("classification_2026-04-07_2026-08-16_")
    assert index["artifacts"][0]["sha256"] == hashlib.sha256(
        Path(result["artifactPath"]).read_bytes()
    ).hexdigest()
    assert index["classificationArtifacts"][0]["sha256"] == hashlib.sha256(
        (consumer_data / "history" / "2026" / classification_file).read_bytes()
    ).hexdigest()
    assert result["classificationRelativePath"].endswith(classification_file)
    artifact = read_json(Path(result["artifactPath"]), "artifact")
    assert canonical_sha256(verify_chain(base, [artifact])) == canonical_sha256(target)
    assert (consumer_data / active_data_file).exists()


def test_fresh_same_year_same_generation_initializes_without_self_diff(tmp_path: Path):
    consumer_data = tmp_path / "consumer" / "data"
    consumer_data.mkdir(parents=True)
    incoming = tmp_path / "incoming"
    base, _ = snapshots()
    manifest_path = write_generation(incoming, base, "2026-04-07")
    install_generation(consumer_data, manifest_path)

    result = prepare_history_update(consumer_data, manifest_path)

    assert result["mode"] == "initialize"
    assert result["artifactPath"] is None
    index = read_json(consumer_data / "history" / "2026" / "index.json", "index")
    assert index["baseline"] == index["latest"]
    assert index["artifacts"] == []


def test_fresh_same_year_validation_failure_does_not_write_consumer_data(
    tmp_path: Path,
):
    consumer_data = tmp_path / "consumer" / "data"
    consumer_data.mkdir(parents=True)
    incoming = tmp_path / "incoming"
    base, target = snapshots()
    active_manifest = write_generation(incoming, base, "2026-04-07")
    install_generation(consumer_data, active_manifest)
    target_manifest = write_generation(incoming, target, "2026-08-16")
    classification = write_classification_artifact(
        tmp_path / "classification.json",
        base,
        json.loads(active_manifest.read_text(encoding="utf-8")),
        target,
        json.loads(target_manifest.read_text(encoding="utf-8")),
    )
    broken = json.loads(classification.read_text(encoding="utf-8"))
    broken["schemaVersion"] = 3
    classification.write_text(json.dumps(broken), encoding="utf-8")
    before = {
        path.relative_to(consumer_data): path.read_bytes()
        for path in consumer_data.rglob("*") if path.is_file()
    }

    with pytest.raises(ValueError, match="schemaVersion"):
        prepare_history_update(consumer_data, target_manifest, classification)

    after = {
        path.relative_to(consumer_data): path.read_bytes()
        for path in consumer_data.rglob("*") if path.is_file()
    }
    assert after == before
    assert not (consumer_data / "history" / "2026" / "index.json").exists()


def test_same_year_accepts_schema_version_2_and_records_pointer_sha(tmp_path: Path):
    consumer_data = tmp_path / "consumer" / "data"
    consumer_data.mkdir(parents=True)
    incoming = tmp_path / "incoming"
    base, target = snapshots()
    base_manifest = write_generation(incoming, base, "2026-04-01")
    prepare_history_update(consumer_data, base_manifest)
    install_generation(consumer_data, base_manifest)
    target_manifest = write_generation(incoming, target, "2026-04-02")
    classification = write_classification_artifact(
        tmp_path / "classification.json",
        base,
        json.loads(base_manifest.read_text(encoding="utf-8")),
        target,
        json.loads(target_manifest.read_text(encoding="utf-8")),
        schema_version=2,
    )

    result = prepare_history_update(consumer_data, target_manifest, classification)

    pointer = read_json(
        consumer_data / "history" / "2026" / "index.json", "index"
    )["classificationArtifacts"][0]
    assert result["classificationRelativePath"].endswith(pointer["dataFile"])
    assert pointer["sha256"] == hashlib.sha256(classification.read_bytes()).hexdigest()


def test_year_rollover_accepts_schema_version_2(tmp_path: Path):
    consumer_data, _, base, active_manifest, next_data, next_manifest = (
        rollover_fixture(tmp_path)
    )
    classification = write_classification_artifact(
        tmp_path / "classification.json",
        base,
        json.loads(active_manifest.read_text(encoding="utf-8")),
        next_data,
        json.loads(next_manifest.read_text(encoding="utf-8")),
        schema_version=2,
    )

    result = prepare_history_update(
        consumer_data,
        next_manifest,
        classification,
        update_kind="year-rollover",
    )

    index = read_json(consumer_data / "history" / "2027" / "index.json", "index")
    pointer = index["classificationArtifacts"][0]
    assert result["classificationRelativePath"].endswith(pointer["dataFile"])
    assert pointer["sha256"] == hashlib.sha256(classification.read_bytes()).hexdigest()


@pytest.mark.parametrize("schema_version", [None, 0, 3, True, "2"])
def test_unsupported_classification_schema_version_fails_before_writes(
    tmp_path: Path, schema_version: object
):
    consumer_data = tmp_path / "consumer" / "data"
    consumer_data.mkdir(parents=True)
    incoming = tmp_path / "incoming"
    base, target = snapshots()
    base_manifest = write_generation(incoming, base, "2026-04-01")
    prepare_history_update(consumer_data, base_manifest)
    install_generation(consumer_data, base_manifest)
    target_manifest = write_generation(incoming, target, "2026-04-02")
    classification = write_classification_artifact(
        tmp_path / "classification.json",
        base,
        json.loads(base_manifest.read_text(encoding="utf-8")),
        target,
        json.loads(target_manifest.read_text(encoding="utf-8")),
    )
    artifact = json.loads(classification.read_text(encoding="utf-8"))
    if schema_version is None:
        del artifact["schemaVersion"]
    else:
        artifact["schemaVersion"] = schema_version
    classification.write_text(json.dumps(artifact), encoding="utf-8")
    before = {
        path.relative_to(consumer_data): path.read_bytes()
        for path in consumer_data.rglob("*") if path.is_file()
    }

    with pytest.raises(ValueError, match="schemaVersion"):
        prepare_history_update(consumer_data, target_manifest, classification)

    after = {
        path.relative_to(consumer_data): path.read_bytes()
        for path in consumer_data.rglob("*") if path.is_file()
    }
    assert after == before


def test_rejects_tampered_chain_and_cross_year_update(tmp_path: Path):
    consumer_data = tmp_path / "consumer" / "data"
    consumer_data.mkdir(parents=True)
    incoming = tmp_path / "incoming"
    base, target = snapshots()
    base_manifest = write_generation(incoming, base, "2026-04-01")
    prepare_history_update(consumer_data, base_manifest)
    install_generation(consumer_data, base_manifest)
    target_manifest = write_generation(incoming, target, "2026-04-02")
    result = prepare_history_update(consumer_data, target_manifest)
    install_generation(consumer_data, target_manifest)

    Path(result["artifactPath"]).write_text("{}", encoding="utf-8")
    next_data = deepcopy(target)
    next_data["10000100"]["メッセージ"] = "next"
    next_manifest = write_generation(incoming, next_data, "2026-04-03")
    with pytest.raises(ValueError, match="file SHA-256"):
        prepare_history_update(consumer_data, next_manifest)

    other_year = {
        "20000100": {
            **next(iter(target.values())),
            "年度": "2027年度",
            "講義コード": "20000100",
        }
    }
    other_manifest = write_generation(incoming, other_year, "2027-04-01")
    with pytest.raises(ValueError, match="academicYear"):
        prepare_history_update(consumer_data, other_manifest)


def test_year_rollover_preserves_active_generation_and_creates_baselines(
    tmp_path: Path,
):
    consumer_data = tmp_path / "consumer" / "data"
    consumer_data.mkdir(parents=True)
    incoming = tmp_path / "incoming"
    base, target = snapshots()
    active_manifest = write_generation(incoming, base, "2026-04-01")
    install_generation(consumer_data, active_manifest)
    next_data = {
        "20000100": {
            **next(iter(target.values())),
            "年度": "2027年度",
            "講義コード": "20000100",
        }
    }
    next_manifest = write_generation(incoming, next_data, "2027-04-01")

    result = prepare_history_update(
        consumer_data, next_manifest, update_kind="year-rollover"
    )

    assert result["mode"] == "rollover"
    assert result["previousIndexRelativePath"] == "data/history/2026/index.json"
    assert result["obsoleteDataFile"] is None
    old_index = read_json(
        consumer_data / "history" / "2026" / "index.json", "old index"
    )
    new_index = read_json(
        consumer_data / "history" / "2027" / "index.json", "new index"
    )
    assert old_index["baseline"] == old_index["latest"]
    assert new_index["baseline"] == new_index["latest"]
    active_data_file = json.loads(
        active_manifest.read_text(encoding="utf-8")
    )["dataFile"]
    assert (consumer_data / active_data_file).exists()


def rollover_fixture(tmp_path: Path):
    consumer_data = tmp_path / "consumer" / "data"
    consumer_data.mkdir(parents=True)
    incoming = tmp_path / "incoming"
    base, target = snapshots()
    active_manifest = write_generation(incoming, base, "2026-04-01")
    install_generation(consumer_data, active_manifest)
    next_data = {
        "20000100": {
            **next(iter(target.values())),
            "年度": "2027年度",
            "講義コード": "20000100",
        }
    }
    next_manifest = write_generation(incoming, next_data, "2027-04-01")
    return consumer_data, incoming, base, active_manifest, next_data, next_manifest


def test_year_rollover_classification_is_recorded(tmp_path: Path):
    consumer_data, _, base, active_manifest, next_data, next_manifest = (
        rollover_fixture(tmp_path)
    )
    classification = write_classification_artifact(
        tmp_path / "classification.json",
        base,
        json.loads(active_manifest.read_text(encoding="utf-8")),
        next_data,
        json.loads(next_manifest.read_text(encoding="utf-8")),
    )

    result = prepare_history_update(
        consumer_data,
        next_manifest,
        classification,
        update_kind="year-rollover",
    )
    assert result["classificationRelativePath"].startswith(
        "data/history/2027/classification_"
    )
    assert len(read_json(
        consumer_data / "history" / "2027" / "index.json", "new index"
    )["classificationArtifacts"]) == 1


@pytest.mark.parametrize(
    ("year", "message"),
    [
        ("2026", "year-rollover requires a different academic year"),
        ("2028", "immediately following academic year"),
        ("2025", "immediately following academic year"),
    ],
)
def test_year_rollover_rejects_invalid_years_on_fresh_destination(
    tmp_path: Path, year: str, message: str
):
    consumer_data, incoming, _, _, target, _ = rollover_fixture(tmp_path)
    bad_data = {
        "30000100": {
            **next(iter(target.values())),
            "年度": f"{year}年度",
            "講義コード": "30000100",
        }
    }
    bad_manifest = write_generation(incoming, bad_data, f"{year}-04-01")

    with pytest.raises(ValueError, match=message):
        prepare_history_update(
            consumer_data, bad_manifest, update_kind="year-rollover"
        )
    assert not (consumer_data / "history" / year / "index.json").exists()


def test_year_rollover_keeps_verified_old_index_bytes_unchanged(tmp_path: Path):
    consumer_data, incoming, base, active_manifest, _, _ = rollover_fixture(tmp_path)
    prepare_history_update(consumer_data, active_manifest)
    install_generation(consumer_data, active_manifest)
    middle = snapshots()[1]
    middle_manifest = write_generation(incoming, middle, "2026-04-02")
    prepare_history_update(consumer_data, middle_manifest)
    install_generation(consumer_data, middle_manifest)
    old_index_path = consumer_data / "history" / "2026" / "index.json"
    old_index_bytes = old_index_path.read_bytes()
    next_data = {
        "20000100": {
            **next(iter(base.values())),
            "年度": "2027年度",
            "講義コード": "20000100",
        }
    }
    next_manifest = write_generation(incoming, next_data, "2027-04-01")

    result = prepare_history_update(
        consumer_data, next_manifest, update_kind="year-rollover"
    )

    assert result["previousIndexRelativePath"] == "data/history/2026/index.json"
    assert old_index_path.read_bytes() == old_index_bytes
    new_index = read_json(
        consumer_data / "history" / "2027" / "index.json", "new index"
    )
    assert new_index["baseline"] == new_index["latest"]


def test_year_rollover_rejects_tampered_old_chain_without_writes(tmp_path: Path):
    consumer_data, incoming, base, active_manifest, _, _ = rollover_fixture(tmp_path)
    prepare_history_update(consumer_data, active_manifest)
    install_generation(consumer_data, active_manifest)
    middle = snapshots()[1]
    middle_manifest = write_generation(incoming, middle, "2026-04-02")
    result = prepare_history_update(consumer_data, middle_manifest)
    install_generation(consumer_data, middle_manifest)
    Path(result["artifactPath"]).write_text("{}", encoding="utf-8")
    next_data = {
        "20000100": {
            **next(iter(base.values())),
            "年度": "2027年度",
            "講義コード": "20000100",
        }
    }
    next_manifest = write_generation(incoming, next_data, "2027-04-01")
    before = {
        path.relative_to(consumer_data): path.read_bytes()
        for path in consumer_data.rglob("*")
        if path.is_file()
    }

    with pytest.raises(ValueError, match="file SHA-256"):
        prepare_history_update(
            consumer_data, next_manifest, update_kind="year-rollover"
        )

    after = {
        path.relative_to(consumer_data): path.read_bytes()
        for path in consumer_data.rglob("*")
        if path.is_file()
    }
    assert after == before
    assert not (consumer_data / "history" / "2027" / "index.json").exists()


def test_year_rollover_rejects_existing_destination_index_independently(
    tmp_path: Path,
):
    consumer_data, _, _, _, _, next_manifest = rollover_fixture(tmp_path)
    prepare_history_update(consumer_data, next_manifest, update_kind="year-rollover")

    with pytest.raises(ValueError, match="destination history index already exists"):
        prepare_history_update(
            consumer_data, next_manifest, update_kind="year-rollover"
        )
