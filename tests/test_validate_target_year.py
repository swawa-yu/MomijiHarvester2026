import json

import pytest

from scripts.validate_target_year import validate_target_year


def manifest(tmp_path, academic_year="2026年度"):
    path = tmp_path / "subjectDataManifest.json"
    path.write_text(json.dumps({"academicYear": academic_year}), encoding="utf-8")
    return path


@pytest.mark.parametrize("kind,target", [("same-year", "2026"), ("year-rollover", "2027")])
def test_valid_year_modes(tmp_path, kind, target):
    validate_target_year(kind, target, manifest(tmp_path))


@pytest.mark.parametrize(
    "kind,target",
    [("same-year", "2027"), ("year-rollover", "2026"), ("year-rollover", "2028"), ("same-year", "20x6")],
)
def test_invalid_year_modes(tmp_path, kind, target):
    with pytest.raises(ValueError):
        validate_target_year(kind, target, manifest(tmp_path))
