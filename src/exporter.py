import json
import os
from datetime import date
from pathlib import Path
from typing import Dict

from src.models import SubjectDetails


class Exporter:
    def __init__(self, output_dir: str = "output"):
        self.output_dir = output_dir
        Path(self.output_dir).mkdir(parents=True, exist_ok=True)

    def export(self, subjects: Dict[str, SubjectDetails], lang_tag: str = "") -> str:
        suffix = f"_{lang_tag}" if lang_tag else ""
        output_path = os.path.join(
            self.output_dir,
            f"subject_details_main_{date.today().isoformat()}{suffix}.json",
        )
        data = {k: v.model_dump(by_alias=True) for k, v in subjects.items()}
        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        return output_path
