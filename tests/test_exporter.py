import json
import hashlib
import os
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

from src.exporter import Exporter
from src.models import SubjectDetails
from src.parser import Parser

FIELDS = {
    # Independent copy of momiji2's RawSubject contract (19 aliases).
    "relative URL", "年度", "開講部局", "講義コード", "科目区分",
    "授業科目名", "担当教員名", "開講キャンパス", "開設期",
    "曜日・時限・講義室", "単位", "使用言語", "学習の段階",
    "対象学生", "授業の目標・概要等", "予習・復習への アドバイス",
    "履修上の注意 受講条件等", "メッセージ", "その他",
}


def subject(code="10000100", year="2026年度"):
    values = {field: "value" for field in FIELDS}
    values.update(
        {"relative URL": f"{year[:4]}_AA_{code}.html",
         "年度": year, "講義コード": code, "その他": ""})
    return SubjectDetails(**values)


def read(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def assert_hash_matches(path):
    digest = hashlib.sha256(Path(path).read_bytes()).hexdigest()[:12]
    assert Path(path).stem.endswith(f"_{digest}")


def departments():
    return {
        "kaikouBukyokuGakubus": ["教養教育"],
        "kaikouBukyokuDaigakuins": ["大学院共通教育（博士課程前期）"],
    }


def structure_report(subject_count=1):
    return {
        "subjectPageCount": subject_count,
        "observedHeaders": sorted(Parser.SUBJECT_CONTRACT_HEADERS),
        "unknownHeaders": [],
        "missingHeaders": [],
        "headerPresence": {
            header: {"presentCount": subject_count, "presenceRate": 1.0}
            for header in sorted(Parser.SUBJECT_CONTRACT_HEADERS)
        },
    }


def test_exporter_creates_output_directory_only_when_exporting(tmp_path: Path):
    output_dir = tmp_path / "not-created" / "nested-output"
    exporter = Exporter(str(output_dir))

    assert not output_dir.exists()
    exporter.export({"10000100": subject()})
    assert output_dir.exists()


@pytest.mark.parametrize("year", ["2025年度", "2026年度"])
def test_exporter_writes_contract_and_manifest(tmp_path: Path, year: str):
    path = Exporter(str(tmp_path)).export(
        {"10000100": subject(year=year),
         }, source="https://example.test/syllabus/")
    data = read(path)
    manifest = read(tmp_path / "subjectDataManifest.json")
    assert set(data["10000100"]) == FIELDS
    assert data["10000100"]["その他"] == ""
    assert manifest == {
        "dataFile": Path(path).name, "academicYear": year,
        "retrievedAt": manifest["retrievedAt"], "subjectCount": 1,
        "source": "https://example.test/syllabus/"}
    assert len(manifest["retrievedAt"]) == 10


def test_exporter_writes_department_contract_for_exact_subject_generation(
        tmp_path: Path):
    path = Exporter(str(tmp_path)).export(
        {"10000100": subject()},
        source="https://example.test/syllabus/",
        departments=departments(),
    )
    manifest = read(tmp_path / "subjectDataManifest.json")
    artifact_paths = list(tmp_path.glob("department_constants_*.json"))
    assert len(artifact_paths) == 1
    artifact = read(artifact_paths[0])
    subject_bytes = Path(path).read_bytes()
    assert artifact == {
        "schemaVersion": 1,
        "academicYear": manifest["academicYear"],
        "retrievedAt": manifest["retrievedAt"],
        "source": manifest["source"],
        "subjectData": {
            "dataFile": manifest["dataFile"],
            "sha256": hashlib.sha256(subject_bytes).hexdigest(),
            "subjectCount": manifest["subjectCount"],
        },
        "departments": departments(),
    }
    assert artifact_paths[0].stem.endswith(
        f"_{hashlib.sha256(artifact_paths[0].read_bytes()).hexdigest()[:12]}"
    )


def test_exporter_writes_bound_structure_report(tmp_path: Path):
    path = Exporter(str(tmp_path)).export(
        {"10000100": subject()},
        source="https://example.test/syllabus/",
        departments=departments(),
        subject_structure_report=structure_report(),
    )
    manifest = read(tmp_path / "subjectDataManifest.json")
    structure_path = tmp_path / manifest["structureReport"]["dataFile"]
    structure = read(structure_path)

    assert manifest["schemaVersion"] == 1
    assert hashlib.sha256(structure_path.read_bytes()).hexdigest() == (
        manifest["structureReport"]["sha256"]
    )
    assert structure["schemaVersion"] == 1
    assert structure["subjectData"] == {
        "dataFile": Path(path).name,
        "sha256": hashlib.sha256(Path(path).read_bytes()).hexdigest(),
        "subjectCount": 1,
    }
    assert structure["structure"] == structure_report()


@pytest.mark.parametrize("mutate, message", [
    (lambda report: report.update({"subjectPageCount": 2}), "page count"),
    (lambda report: report["unknownHeaders"].append("追加項目"), "drift"),
    (lambda report: report["missingHeaders"].append("年度"), "drift"),
    (
        lambda report: report["headerPresence"]["年度"].update(
            {"presenceRate": 0.5}
        ),
        "presence value",
    ),
])
def test_invalid_structure_report_preserves_previous_generation(
        tmp_path: Path, mutate, message):
    exporter = Exporter(str(tmp_path))
    exporter.export(
        {"10000100": subject()},
        source="https://example.test/",
        departments=departments(),
        subject_structure_report=structure_report(),
    )
    before = {path.name: path.read_bytes() for path in tmp_path.iterdir()}
    invalid = structure_report()
    mutate(invalid)

    with pytest.raises(ValueError, match=message):
        exporter.export(
            {"10000100": subject()},
            source="https://example.test/",
            departments=departments(),
            subject_structure_report=invalid,
        )

    assert {path.name: path.read_bytes() for path in tmp_path.iterdir()} == before


@pytest.mark.parametrize("mutate, message", [
    (lambda x: x.update({"extra": "x"}), "contract"),
    (lambda x: x.pop("その他"), "contract"),
    (lambda x: x.update({"その他": 1}), "non-string"),
    (lambda x: x.update({"講義コード": "other"}), "course code"),
    (lambda x: x.update({"年度": "2025"}), "年度"),
])
def test_exporter_rejects_invalid_data_without_changing_outputs(
        tmp_path: Path, mutate, message):
    exporter = Exporter(str(tmp_path))
    valid = {"10000100": subject()}
    path = exporter.export(valid, source="https://example.test/syllabus/")
    manifest_path = tmp_path / "subjectDataManifest.json"
    before = (Path(path).read_bytes(), manifest_path.read_bytes())
    broken = subject().model_dump(by_alias=True)
    mutate(broken)
    with pytest.raises(ValueError, match=message):
        exporter.export({"10000100": broken},
                        source="https://example.test/syllabus/")
    assert (Path(path).read_bytes(), manifest_path.read_bytes()) == before


@pytest.mark.parametrize("invalid, message", [
    ({"kaikouBukyokuGakubus": ["a"]}, "exactly"),
    ({"kaikouBukyokuGakubus": [], "kaikouBukyokuDaigakuins": ["b"]}, "nonempty"),
    ({"kaikouBukyokuGakubus": [" a"], "kaikouBukyokuDaigakuins": ["b"]}, "trimmed"),
    ({"kaikouBukyokuGakubus": ["a"], "kaikouBukyokuDaigakuins": ["a"]}, "duplicate"),
])
def test_invalid_departments_preserve_previous_generation_and_manifest(
        tmp_path: Path, invalid, message):
    exporter = Exporter(str(tmp_path))
    exporter.export(
        {"10000100": subject()},
        source="https://example.test/",
        departments=departments(),
    )
    before = {
        path.name: path.read_bytes()
        for path in tmp_path.iterdir()
    }
    with pytest.raises(ValueError, match=message):
        exporter.export(
            {"10000100": subject()},
            source="https://example.test/",
            departments=invalid,
        )
    assert {
        path.name: path.read_bytes()
        for path in tmp_path.iterdir()
    } == before


def test_exporter_rejects_mixed_year_empty_and_non_https(tmp_path: Path):
    exporter = Exporter(str(tmp_path))
    cases = [({}, "empty"), ({"a": subject("a", "2025年度"), "b": subject(
        "b", "2026年度")}, "academic year"), ({"10000100": subject()}, "HTTPS")]
    for data, message in cases:
        source = ("http://example.test/" if message == "HTTPS"
                  else "https://example.test/")
        with pytest.raises(ValueError, match=message):
            exporter.export(data, source=source)


def test_exporter_uses_official_source_when_omitted(tmp_path: Path):
    path = Exporter(str(tmp_path)).export({"10000100": subject()})
    manifest = read(tmp_path / "subjectDataManifest.json")
    assert manifest["dataFile"] == Path(path).name
    assert manifest["source"] == (
        "https://momiji.hiroshima-u.ac.jp/syllabusHtml/")
    assert_hash_matches(path)


def test_exporter_manifest_failure_preserves_previous_pointer_and_data(
        tmp_path: Path, monkeypatch):
    exporter = Exporter(str(tmp_path))
    old_path = exporter.export(
        {"10000100": subject()}, source="https://example.test/")
    manifest_path = tmp_path / "subjectDataManifest.json"
    old_data, old_manifest = Path(
        old_path).read_bytes(), manifest_path.read_bytes()
    original_replace = os.replace

    def fail_manifest(source, destination):
        if Path(destination).name == "subjectDataManifest.json":
            raise OSError("simulated manifest replacement failure")
        return original_replace(source, destination)

    monkeypatch.setattr("src.exporter.os.replace", fail_manifest)
    changed = subject().model_copy(update={"title": "changed"})
    with pytest.raises(OSError, match="manifest"):
        exporter.export({"10000100": changed}, source="https://example.test/")
    assert Path(old_path).read_bytes() == old_data
    assert manifest_path.read_bytes() == old_manifest
    assert json.loads(manifest_path.read_text(encoding="utf-8")
                      )["dataFile"] == Path(old_path).name
    orphan_paths = list(tmp_path.glob("subject_details_main_*.json"))
    assert len(orphan_paths) == 2
    assert old_path in {str(path) for path in orphan_paths}
    assert any(path != Path(old_path) and path.read_bytes()
               != old_data for path in orphan_paths)


def test_department_artifact_failure_preserves_previous_manifest(
        tmp_path: Path, monkeypatch):
    exporter = Exporter(str(tmp_path))
    old_path = exporter.export(
        {"10000100": subject()},
        source="https://example.test/",
        departments=departments(),
    )
    manifest_path = tmp_path / "subjectDataManifest.json"
    old_manifest = manifest_path.read_bytes()
    original_replace = os.replace

    def fail_department_artifact(source, destination):
        if Path(destination).name.startswith("department_constants_"):
            raise OSError("simulated department artifact replacement failure")
        return original_replace(source, destination)

    monkeypatch.setattr("src.exporter.os.replace", fail_department_artifact)
    changed = subject().model_copy(update={"title": "changed"})
    with pytest.raises(OSError, match="department artifact"):
        exporter.export(
            {"10000100": changed},
            source="https://example.test/",
            departments=departments(),
        )
    assert manifest_path.read_bytes() == old_manifest
    assert read(manifest_path)["dataFile"] == Path(old_path).name


def test_department_envelope_is_content_addressed_and_manifest_failure_keeps_old_artifact(
        tmp_path: Path, monkeypatch):
    exporter = Exporter(str(tmp_path))
    subjects = {"10000100": subject()}
    exporter.export(
        subjects, source="https://first.example.test/", departments=departments()
    )
    old_artifact = next(tmp_path.glob("department_constants_*.json"))
    old_bytes = old_artifact.read_bytes()
    original_replace = os.replace

    def fail_manifest(source, destination):
        if Path(destination).name == "subjectDataManifest.json":
            raise OSError("simulated manifest replacement failure")
        return original_replace(source, destination)

    monkeypatch.setattr("src.exporter.os.replace", fail_manifest)
    changed_departments = {
        "kaikouBukyokuGakubus": ["教養教育", "総合科学部"],
        "kaikouBukyokuDaigakuins": ["大学院共通教育（博士課程前期）"],
    }
    with pytest.raises(OSError, match="manifest"):
        exporter.export(
            subjects,
            source="https://second.example.test/",
            departments=changed_departments,
        )
    artifact_paths = list(tmp_path.glob("department_constants_*.json"))
    assert len(artifact_paths) == 2
    assert old_artifact.read_bytes() == old_bytes
    assert all(
        path.stem.endswith(f"_{hashlib.sha256(path.read_bytes()).hexdigest()[:12]}")
        for path in artifact_paths
    )


def test_exporter_generation_is_collision_safe(tmp_path: Path):
    exporter = Exporter(str(tmp_path))
    first = exporter.export({"10000100": subject()},
                            lang_tag="_en", source="https://example.test/")
    second = exporter.export({"10000100": subject()},
                             lang_tag="_en", source="https://example.test/")
    assert first == second
    assert_hash_matches(first)
    assert "__en_" not in Path(first).name
    assert not list(tmp_path.glob(".*"))


def test_different_valid_subjects_create_different_generations(tmp_path: Path):
    exporter = Exporter(str(tmp_path))
    first = exporter.export(
        {"10000100": subject()}, source="https://example.test/")
    changed = subject().model_copy(update={"title": "different"})
    second = exporter.export(
        {"10000100": changed}, source="https://example.test/")
    assert first != second
    assert_hash_matches(first)
    assert_hash_matches(second)


def test_concurrent_exports_keep_each_generation_and_manifest_consistent(
        tmp_path: Path):
    exporter = Exporter(str(tmp_path))
    inputs = [
        {str(10000100 + index): subject(str(10000100 + index))}
        for index in range(4)
    ]
    with ThreadPoolExecutor(max_workers=4) as pool:
        paths = list(pool.map(
            lambda data: exporter.export(
                data, source="https://example.test/", departments=departments()
            ),
            inputs))
    for path in paths:
        assert Path(path).exists()
        assert_hash_matches(path)
    manifest_path = tmp_path / "subjectDataManifest.json"
    assert manifest_path.exists()
    manifest = read(manifest_path)
    manifest_data = tmp_path / manifest["dataFile"]
    assert manifest_data.exists()
    assert_hash_matches(manifest_data)
    assert manifest["subjectCount"] == len(read(manifest_data))
    assert manifest["academicYear"] == "2026年度"
    assert manifest["source"] == "https://example.test/"
    artifact_paths = list(tmp_path.glob("department_constants_*.json"))
    assert len(artifact_paths) == len(paths)
    artifacts = [read(path) for path in artifact_paths]
    for path, artifact in zip(artifact_paths, artifacts):
        assert path.stem.endswith(
            f"_{hashlib.sha256(path.read_bytes()).hexdigest()[:12]}"
        )
        assert artifact["subjectData"]["sha256"] == hashlib.sha256(
            (tmp_path / artifact["subjectData"]["dataFile"]).read_bytes()
        ).hexdigest()
    assert any(
        artifact["subjectData"]["dataFile"] == manifest["dataFile"]
        for artifact in artifacts
    )
    assert not list(tmp_path.glob(".*"))


@pytest.mark.parametrize("lang_tag", ["../bad", "bad/name", "bad\nname"])
def test_exporter_rejects_unsafe_lang_tag(tmp_path: Path, lang_tag: str):
    with pytest.raises(ValueError, match="lang_tag"):
        Exporter(str(tmp_path)).export(
            {"10000100": subject()}, lang_tag=lang_tag)


def test_exporter_rejects_invalid_source_and_subject_container(tmp_path: Path):
    exporter = Exporter(str(tmp_path))
    with pytest.raises(ValueError, match="HTTPS"):
        exporter.export({"10000100": subject()}, source="https://")
    with pytest.raises(ValueError, match="mapping"):
        exporter.export([("10000100", subject())])
    with pytest.raises(ValueError, match="mapping"):
        exporter.export({"10000100": object()})
