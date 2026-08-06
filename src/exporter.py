import json
import os
import re
from datetime import date
from pathlib import Path
from typing import Dict

from src.models import SubjectDetails


class Exporter:
    def __init__(self, output_dir: str = "output"):
        self.output_dir = output_dir
        Path(self.output_dir).mkdir(parents=True, exist_ok=True)

    def export(
        self,
        subjects: Dict[str, SubjectDetails],
        lang_tag: str = "",
        source: str = "https://momiji.hiroshima-u.ac.jp/syllabusHtml/",
    ) -> str:
        suffix = f"_{lang_tag}" if lang_tag else ""
        output_path = os.path.join(
            self.output_dir,
            f"subject_details_main_{date.today().isoformat()}{suffix}.json",
        )
        data = {
            k: (v.model_dump(by_alias=True) if hasattr(v, "model_dump") else dict(v))
            for k, v in subjects.items()
        }
        self._validate(data, source)
        manifest = {
            "dataFile": Path(output_path).name,
            "academicYear": next(iter(data.values()))["年度"],
            "retrievedAt": date.today().isoformat(),
            "subjectCount": len(data),
            "source": source,
        }
        self._atomic_write(output_path, data)
        self._atomic_write(
            os.path.join(self.output_dir, "subjectDataManifest.json"), manifest
        )
        return output_path

    @staticmethod
    def _validate(data: dict, source: str) -> None:
        fields = {
            "relative URL", "年度", "開講部局", "講義コード", "科目区分",
            "授業科目名", "担当教員名", "開講キャンパス", "開設期",
            "曜日・時限・講義室", "単位", "使用言語", "学習の段階",
            "対象学生", "授業の目標・概要等", "予習・復習への アドバイス",
            "履修上の注意 受講条件等", "メッセージ", "その他",
        }
        if not data:
            raise ValueError("subject data must not be empty")
        if not isinstance(source, str) or not source.startswith("https://"):
            raise ValueError("source must be an HTTPS URL")
        years = set()
        for key, subject in data.items():
            if set(subject) != fields:
                raise ValueError(f"subject {key!r} does not match the 19-field contract")
            if any(not isinstance(value, str) for value in subject.values()):
                raise ValueError(f"subject {key!r} contains a non-string value")
            if key != subject["講義コード"]:
                raise ValueError(f"subject key {key!r} does not match its course code")
            if not re.fullmatch(r"\d{4}年度", subject["年度"]):
                raise ValueError("年度 must be YYYY年度")
            years.add(subject["年度"])
        if len(years) != 1:
            raise ValueError("subject data must contain exactly one academic year")

    @staticmethod
    def _atomic_write(path: str, payload: dict) -> None:
        destination = Path(path)
        temporary = destination.with_name(f".{destination.name}.tmp")
        try:
            with temporary.open("w", encoding="utf-8") as f:
                json.dump(payload, f, ensure_ascii=False, indent=2)
            os.replace(temporary, destination)
        finally:
            if temporary.exists():
                temporary.unlink()
