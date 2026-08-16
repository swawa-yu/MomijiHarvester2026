import json
from copy import deepcopy
from pathlib import Path

import pytest

from scripts.prepare_consumer_history import prepare_history_update
from scripts.subject_history import canonical_sha256, read_json, verify_chain
from tests.test_subject_history import manifest, snapshots


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
