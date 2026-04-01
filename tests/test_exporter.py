import json
from pathlib import Path

from src.exporter import Exporter
from src.models import SubjectDetails


def test_exporter_writes_json(tmp_path: Path):
    subjects = {
        "10000100": SubjectDetails(
            **{
                "relative URL": "2026_AA_10000100.html",
                "年度": "2026年度",
                "開講部局": "教養教育",
                "講義コード": "10000100",
                "科目区分": "大学教育入門",
                "授業科目名": "大学教育入門[1総総,1文,1経]",
                "担当教員名": "林　光緒",
                "開講キャンパス": "東広島",
                "開設期": "1年次生 前期 １ターム",
                "曜日・時限・講義室": "(1T) 水1-4...",
                "単位": "2.0",
                "使用言語": "B : 日本語・英語",
                "学習の段階": "1 : 入門レベル",
                "対象学生": "1年次生全員",
                "授業の目標・概要等": "概要です",
                "予習・復習への アドバイス": "アドバイスです",
                "履修上の注意 受講条件等": "注意です",
                "メッセージ": "メッセージです",
                "その他": "",
            }
        )
    }

    exporter = Exporter(output_dir=str(tmp_path))
    path = exporter.export(subjects)

    data = json.loads(Path(path).read_text(encoding="utf-8"))
    assert "10000100" in data
    assert data["10000100"]["講義コード"] == "10000100"
