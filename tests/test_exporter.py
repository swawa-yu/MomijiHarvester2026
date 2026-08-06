import json
import hashlib
import os
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

from src.exporter import Exporter
from src.models import SubjectDetails

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
            lambda data: exporter.export(data, source="https://example.test/"),
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
