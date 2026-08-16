import json
import hashlib
import os
import re
import tempfile
from datetime import date
from pathlib import Path
from collections.abc import Mapping
from typing import Dict, List, Optional
from urllib.parse import urlparse

from src.models import SubjectDetails


class Exporter:
    def __init__(self, output_dir: str = "output"):
        self.output_dir = output_dir

    def export(
        self,
        subjects: Dict[str, SubjectDetails],
        lang_tag: str = "",
        source: str = "https://momiji.hiroshima-u.ac.jp/syllabusHtml/",
        departments: Optional[Dict[str, List[str]]] = None,
        subject_structure_report: Optional[dict[str, object]] = None,
    ) -> str:
        """Write a subject generation and, when supplied, its department contract.

        ``departments`` is optional for backwards-compatible direct use of the
        exporter.  The crawler always supplies it from the same top-page
        snapshot used to discover faculty links.
        """
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
        full_digest = hashlib.sha256(content).hexdigest()
        digest = full_digest[:12]
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
        department_content = None
        department_path = None
        if departments is not None:
            self._validate_departments(departments)
            department_artifact = {
                "schemaVersion": 1,
                "academicYear": manifest["academicYear"],
                "retrievedAt": manifest["retrievedAt"],
                "source": manifest["source"],
                "subjectData": {
                    "dataFile": manifest["dataFile"],
                    "sha256": full_digest,
                    "subjectCount": manifest["subjectCount"],
                },
                "departments": departments,
            }
            department_content = json.dumps(
                department_artifact, ensure_ascii=False, indent=2
            ).encode("utf-8")
            department_digest = hashlib.sha256(department_content).hexdigest()
            department_path = os.path.join(
                self.output_dir,
                f"department_constants_{Path(output_path).stem}_"
                f"{department_digest[:12]}.json",
            )

        structure_content = None
        structure_path = None
        if subject_structure_report is not None:
            self._validate_subject_structure_report(
                subject_structure_report,
                manifest["subjectCount"],
            )
            structure_artifact = {
                "schemaVersion": 1,
                "academicYear": manifest["academicYear"],
                "retrievedAt": manifest["retrievedAt"],
                "source": manifest["source"],
                "subjectData": {
                    "dataFile": manifest["dataFile"],
                    "sha256": full_digest,
                    "subjectCount": manifest["subjectCount"],
                },
                "structure": subject_structure_report,
            }
            structure_content = json.dumps(
                structure_artifact, ensure_ascii=False, indent=2
            ).encode("utf-8")
            structure_digest = hashlib.sha256(structure_content).hexdigest()
            structure_path = os.path.join(
                self.output_dir,
                f"subject_structure_{Path(output_path).stem}_"
                f"{structure_digest[:12]}.json",
            )
            manifest["schemaVersion"] = 1
            manifest["structureReport"] = {
                "dataFile": Path(structure_path).name,
                "sha256": structure_digest,
            }

        # The manifest is the pointer to a publishable generation, so write it
        # only after every immutable generation file is in place.
        self._atomic_write(output_path, content)
        if department_path is not None and department_content is not None:
            self._atomic_write(department_path, department_content)
        if structure_path is not None and structure_content is not None:
            self._atomic_write(structure_path, structure_content)
        self._atomic_write(
            os.path.join(self.output_dir, "subjectDataManifest.json"),
            json.dumps(manifest, ensure_ascii=False, indent=2).encode("utf-8"),
        )
        return output_path

    @staticmethod
    def _validate_subject_structure_report(
        report: object,
        subject_count: int,
    ) -> None:
        expected_keys = {
            "subjectPageCount", "observedHeaders", "unknownHeaders",
            "missingHeaders", "headerPresence",
        }
        if not isinstance(report, dict) or set(report) != expected_keys:
            raise ValueError(
                "subject structure report does not match the version 1 contract"
            )
        if report["subjectPageCount"] != subject_count:
            raise ValueError(
                "subject structure page count does not match subject count"
            )
        for key in ("observedHeaders", "unknownHeaders", "missingHeaders"):
            values = report[key]
            if (
                not isinstance(values, list)
                or any(not isinstance(value, str) for value in values)
                or values != sorted(set(values))
            ):
                raise ValueError(
                    f"subject structure {key} must be sorted unique strings"
                )
        if report["unknownHeaders"] or report["missingHeaders"]:
            raise ValueError(
                "subject structure report contains contract drift"
            )
        header_presence = report["headerPresence"]
        if not isinstance(header_presence, dict):
            raise ValueError("subject structure headerPresence must be an object")
        for header, presence in header_presence.items():
            if not isinstance(header, str) or not isinstance(presence, dict):
                raise ValueError("invalid subject structure header presence")
            if set(presence) != {
                "presentCount", "presenceRate", "emptyCount", "emptyRate",
            }:
                raise ValueError("invalid subject structure presence fields")
            count = presence["presentCount"]
            rate = presence["presenceRate"]
            empty_count = presence["emptyCount"]
            empty_rate = presence["emptyRate"]
            if (
                not isinstance(count, int)
                or isinstance(count, bool)
                or not 0 <= count <= subject_count
                or not isinstance(rate, (int, float))
                or isinstance(rate, bool)
                or rate != count / subject_count
                or not isinstance(empty_count, int)
                or isinstance(empty_count, bool)
                or not 0 <= empty_count <= count
                or not isinstance(empty_rate, (int, float))
                or isinstance(empty_rate, bool)
                or empty_rate != empty_count / subject_count
            ):
                raise ValueError("invalid subject structure presence value")

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
    def _validate_departments(departments: object) -> None:
        expected_keys = {
            "kaikouBukyokuGakubus",
            "kaikouBukyokuDaigakuins",
        }
        if not isinstance(departments, dict) or set(departments) != expected_keys:
            raise ValueError(
                "departments must contain exactly kaikouBukyokuGakubus and "
                "kaikouBukyokuDaigakuins"
            )

        seen = set()
        for key in (
            "kaikouBukyokuGakubus",
            "kaikouBukyokuDaigakuins",
        ):
            values = departments[key]
            if not isinstance(values, list) or not values:
                raise ValueError(f"departments {key} must be a nonempty list")
            for value in values:
                if (
                    not isinstance(value, str)
                    or not value.strip()
                    or value != value.strip()
                ):
                    raise ValueError(
                        f"departments {key} must contain nonempty trimmed strings"
                    )
                if value in seen:
                    raise ValueError(f"departments contains duplicate: {value}")
                seen.add(value)

    @staticmethod
    def _atomic_write(path: str, payload: bytes) -> None:
        destination = Path(path)
        destination.parent.mkdir(parents=True, exist_ok=True)
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
