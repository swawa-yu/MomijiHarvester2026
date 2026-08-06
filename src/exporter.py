import json
import hashlib
import os
import re
import tempfile
from datetime import date
from pathlib import Path
from collections.abc import Mapping
from typing import Dict
from urllib.parse import urlparse

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
        if (not isinstance(lang_tag, str)
                or not re.fullmatch(r"[A-Za-z0-9_-]*", lang_tag)):
            raise ValueError("lang_tag contains unsafe characters")
        if not isinstance(subjects, Mapping):
            raise ValueError("subjects must be a mapping")
        data = {}
        for key, value in subjects.items():
            if hasattr(value, "model_dump"):
                value = value.model_dump(by_alias=True)
            elif isinstance(value, Mapping):
                value = dict(value)
            else:
                raise ValueError(
                    f"subject {key!r} must be a mapping or model_dump-capable")
            data[key] = value
        self._validate(data, source)
        content = json.dumps(data, ensure_ascii=False,
                             indent=2).encode("utf-8")
        digest = hashlib.sha256(content).hexdigest()[:12]
        normalized_lang_tag = lang_tag.removeprefix("_")
        suffix = f"_{normalized_lang_tag}" if normalized_lang_tag else ""
        output_path = os.path.join(
            self.output_dir,
            f"subject_details_main_{date.today().isoformat()}"
            f"{suffix}_{digest}.json",
        )
        manifest = {
            "dataFile": Path(output_path).name,
            "academicYear": next(iter(data.values()))["年度"],
            "retrievedAt": date.today().isoformat(),
            "subjectCount": len(data),
            "source": source,
        }
        self._atomic_write(output_path, content)
        self._atomic_write(
            os.path.join(self.output_dir, "subjectDataManifest.json"),
            json.dumps(manifest, ensure_ascii=False, indent=2).encode("utf-8"),
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
        parsed_source = urlparse(source) if isinstance(source, str) else None
        if (parsed_source is None or parsed_source.scheme != "https"
                or not parsed_source.netloc):
            raise ValueError("source must be an HTTPS URL")
        years = set()
        for key, subject in data.items():
            if set(subject) != fields:
                raise ValueError(
                    f"subject {key!r} does not match the 19-field contract")
            if any(not isinstance(value, str) for value in subject.values()):
                raise ValueError(
                    f"subject {key!r} contains a non-string value")
            if key != subject["講義コード"]:
                raise ValueError(
                    f"subject key {key!r} does not match its course code")
            if not re.fullmatch(r"\d{4}年度", subject["年度"]):
                raise ValueError("年度 must be YYYY年度")
            years.add(subject["年度"])
        if len(years) != 1:
            raise ValueError(
                "subject data must contain exactly one academic year")

    @staticmethod
    def _atomic_write(path: str, payload: bytes) -> None:
        destination = Path(path)
        temporary = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="wb", dir=destination.parent,
                prefix=f".{destination.name}.", delete=False
            ) as f:
                temporary = Path(f.name)
                f.write(payload)
            os.replace(temporary, destination)
        finally:
            if temporary is not None and temporary.exists():
                temporary.unlink()
