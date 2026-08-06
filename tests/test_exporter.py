import json
from pathlib import Path

import pytest

from src.exporter import Exporter
from src.models import SubjectDetails

FIELDS = {
    "relative URL", "年度", "開講部局", "講義コード", "科目区分",
    "授業科目名", "担当教員名", "開講キャンパス", "開設期",
    "曜日・時限・講義室", "単位", "使用言語", "学習の段階",
    "対象学生", "授業の目標・概要等", "予習・復習への アドバイス",
    "履修上の注意 受講条件等", "メッセージ", "その他",
}


def subject(code="10000100", year="2026年度"):
    values = {field: "value" for field in FIELDS}
    values.update({"relative URL": f"{year[:4]}_AA_{code}.html", "年度": year, "講義コード": code, "その他": ""})
    return SubjectDetails(**values)


def read(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


@pytest.mark.parametrize("year", ["2025年度", "2026年度"])
def test_exporter_writes_contract_and_manifest(tmp_path: Path, year: str):
    path = Exporter(str(tmp_path)).export({"10000100": subject(year=year)}, source="https://example.test/syllabus/")
    data = read(path)
    manifest = read(tmp_path / "subjectDataManifest.json")
    assert set(data["10000100"]) == FIELDS
    assert data["10000100"]["その他"] == ""
    assert manifest == {"dataFile": Path(path).name, "academicYear": year, "retrievedAt": manifest["retrievedAt"], "subjectCount": 1, "source": "https://example.test/syllabus/"}
    assert len(manifest["retrievedAt"]) == 10


@pytest.mark.parametrize("mutate, message", [
    (lambda x: x.update({"extra": "x"}), "contract"),
    (lambda x: x.pop("その他"), "contract"),
    (lambda x: x.update({"その他": 1}), "non-string"),
    (lambda x: x.update({"講義コード": "other"}), "course code"),
    (lambda x: x.update({"年度": "2025"}), "年度"),
])
def test_exporter_rejects_invalid_data_without_changing_outputs(tmp_path: Path, mutate, message):
    exporter = Exporter(str(tmp_path))
    valid = {"10000100": subject()}
    path = exporter.export(valid, source="https://example.test/syllabus/")
    manifest_path = tmp_path / "subjectDataManifest.json"
    before = (Path(path).read_bytes(), manifest_path.read_bytes())
    broken = subject().model_dump(by_alias=True)
    mutate(broken)
    with pytest.raises(ValueError, match=message):
        exporter.export({"10000100": broken}, source="https://example.test/syllabus/")
    assert (Path(path).read_bytes(), manifest_path.read_bytes()) == before


def test_exporter_rejects_mixed_year_empty_and_non_https(tmp_path: Path):
    exporter = Exporter(str(tmp_path))
    cases = [({}, "empty"), ({"a": subject("a", "2025年度"), "b": subject("b", "2026年度")}, "academic year"), ({"10000100": subject()}, "HTTPS")]
    for data, message in cases:
        source = "http://example.test/" if message == "HTTPS" else "https://example.test/"
        with pytest.raises(ValueError, match=message):
            exporter.export(data, source=source)


def test_exporter_uses_official_source_when_omitted(tmp_path: Path):
    path = Exporter(str(tmp_path)).export({"10000100": subject()})
    manifest = read(tmp_path / "subjectDataManifest.json")
    assert manifest["dataFile"] == Path(path).name
    assert manifest["source"] == "https://momiji.hiroshima-u.ac.jp/syllabusHtml/"
