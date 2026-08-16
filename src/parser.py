from bs4 import BeautifulSoup
from typing import Optional
from src.models import SubjectDetails


class Parser:
    SUBJECT_CONTRACT_HEADERS = (
        "年度", "開講部局", "講義コード", "科目区分", "授業科目名",
        "担当教員名", "開講キャンパス", "開設期", "曜日・時限・講義室",
        "単位", "使用言語", "学習の段階", "対象学生", "授業の目標・概要等",
        "予習・復習への アドバイス", "履修上の注意 受講条件等", "メッセージ",
        "その他",
    )
    LEGACY_SOURCE_HEADERS = (
        "授業科目名 （フリガナ）", "英文授業科目名", "担当教員名 (フリガナ)",
        "授業の方法", "授業の方法 【詳細情報】", "週時間", "学問分野（分科）",
        "学問分野（分野）", "学習の成果", "成績評価の基準等", "授業計画",
        "教科書・参考書等", "教養教育での この授業の位置づけ", "教職専門科目",
        "教科専門科目", "実務経験", "実務経験の概要と それに基づく授業内容",
        "授業で使用する メディア・機器等", "授業で取り入れる 学習手法",
        "授業のキーワード", "【詳細情報】", "English",
    )

    @staticmethod
    def get_html_soup(html: str) -> BeautifulSoup:
        return BeautifulSoup(html, "html.parser")

    @staticmethod
    def _normalize_subject_header(header: str) -> str:
        return (
            header.replace(" ", "")
            .replace("\u3000", "")
            .replace("\n", "")
            .replace("<BR>", "")
            .strip()
        )

    @staticmethod
    def _extract_subject_raw(html: str) -> dict[str, str]:
        soup = Parser.get_html_soup(html)
        raw = {}
        for tr in soup.select("table tr"):
            ths = tr.select("th")
            tds = tr.select("td")
            if not ths or not tds:
                continue

            if len(ths) == len(tds):
                for th, td in zip(ths, tds):
                    label = th.get_text(separator=" ", strip=True).replace("\u3000", " ").strip()
                    value = td.get_text(separator=" ", strip=True).strip()
                    if label:
                        raw[label] = value
            elif len(ths) == 1:
                label = ths[0].get_text(separator=" ", strip=True).replace("\u3000", " ").strip()
                value = " ".join(td.get_text(separator=" ", strip=True) for td in tds).strip()
                if label:
                    raw[label] = value
            else:
                # それ以外の場合、見出しと値を対応させる
                pair_count = min(len(ths), len(tds))
                for i in range(pair_count):
                    label = ths[i].get_text(separator=" ", strip=True).replace("\u3000", " ").strip()
                    value = tds[i].get_text(separator=" ", strip=True).strip()
                    if label:
                        raw[label] = value
        return raw

    @classmethod
    def inspect_subject_page_structure(
        cls,
        html: str,
        source_url: str,
    ) -> tuple[dict[str, str], dict[str, object]]:
        raw = cls._extract_subject_raw(html)
        known_headers = cls.SUBJECT_CONTRACT_HEADERS + cls.LEGACY_SOURCE_HEADERS
        canonical_by_normalized = {
            cls._normalize_subject_header(header): header
            for header in known_headers
        }
        observed_headers = {
            canonical_by_normalized[normalized]
            for label in raw
            if (normalized := cls._normalize_subject_header(label))
            in canonical_by_normalized
        }
        unknown_headers = sorted(
            label
            for label in raw
            if cls._normalize_subject_header(label) not in canonical_by_normalized
        )
        missing_headers = [
            header
            for header in cls.SUBJECT_CONTRACT_HEADERS
            if header not in observed_headers
        ]
        return raw, {
            "sourceUrl": source_url,
            "observedHeaders": sorted(observed_headers),
            "unknownHeaders": unknown_headers,
            "missingHeaders": missing_headers,
        }

    @classmethod
    def summarize_subject_page_structures(
        cls,
        observations: list[dict[str, object]],
    ) -> dict[str, object]:
        page_count = len(observations)
        all_known_headers = sorted(
            cls.SUBJECT_CONTRACT_HEADERS + cls.LEGACY_SOURCE_HEADERS
        )
        presence_counts = {header: 0 for header in all_known_headers}
        unknown_headers = set()
        for observation in observations:
            for header in observation["observedHeaders"]:
                presence_counts[header] += 1
            unknown_headers.update(observation["unknownHeaders"])

        header_presence = {
            header: {
                "presentCount": count,
                "presenceRate": count / page_count if page_count else 0,
            }
            for header, count in presence_counts.items()
        }
        missing_headers = [
            header
            for header in cls.SUBJECT_CONTRACT_HEADERS
            if presence_counts[header] != page_count
        ]
        return {
            "subjectPageCount": page_count,
            "observedHeaders": [
                header for header, count in presence_counts.items() if count
            ],
            "unknownHeaders": sorted(unknown_headers),
            "missingHeaders": missing_headers,
            "headerPresence": header_presence,
        }

    @classmethod
    def parse_subject_page_with_structure(
        cls,
        html: str,
        base_url: str,
        faculty_name: str,
    ) -> tuple[SubjectDetails, dict[str, object]]:
        raw, structure = cls.inspect_subject_page_structure(html, base_url)
        unknown_headers = structure["unknownHeaders"]
        missing_headers = structure["missingHeaders"]
        if unknown_headers:
            structure_detail = (
                "Unknown subject header(s) "
                f"{', '.join(repr(header) for header in unknown_headers)}"
            )
            if missing_headers:
                structure_detail += (
                    "; missing expected header(s) "
                    f"{', '.join(repr(header) for header in missing_headers)}"
                )
            raise ValueError(
                f"{structure_detail} in {base_url}"
            )
        if missing_headers:
            raise ValueError(
                "Missing subject header(s) "
                f"{', '.join(repr(header) for header in missing_headers)} "
                f"in {base_url}"
            )

        def find_value(expected: str, alternates=None):
            alternates = alternates or []
            normalized_expected = cls._normalize_subject_header(expected)
            for k, v in raw.items():
                if cls._normalize_subject_header(k) == normalized_expected:
                    return v
            for alt in alternates:
                for k, v in raw.items():
                    if cls._normalize_subject_header(k) == cls._normalize_subject_header(alt):
                        return v
            return ""

        def normalize_text(text: str) -> str:
            return " ".join(text.replace("\r", " ").replace("\n", " ").split())

        data = {
            "relative URL": normalize_text(base_url),
            "年度": normalize_text(find_value("年度")),
            "開講部局": normalize_text(find_value("開講部局") or faculty_name),
            "講義コード": normalize_text(find_value("講義コード")),
            "科目区分": normalize_text(find_value("科目区分")),
            "授業科目名": normalize_text(find_value("授業科目名")),
            "担当教員名": normalize_text(find_value("担当教員名")),
            "開講キャンパス": normalize_text(find_value("開講キャンパス")),
            "開設期": normalize_text(find_value("開設期")),
            "曜日・時限・講義室": normalize_text(find_value("曜日・時限・講義室")),
            "単位": normalize_text(find_value("単位")),
            "使用言語": normalize_text(find_value("使用言語")),
            "学習の段階": normalize_text(find_value("学習の段階")),
            "対象学生": normalize_text(find_value("対象学生")),
            "授業の目標・概要等": normalize_text(find_value("授業の目標・概要等")),
            "予習・復習への アドバイス": normalize_text(find_value("予習・復習への アドバイス", alternates=["予習・復習へのアドバイス"])),
            "履修上の注意 受講条件等": normalize_text(find_value("履修上の注意 受講条件等", alternates=["履修上の注意受講条件等", "履修上の注意 受講条件等"])),
            "メッセージ": normalize_text(find_value("メッセージ")),
            "その他": normalize_text(find_value("その他")),
        }

        subject = SubjectDetails(**{k: v for k, v in data.items() if v is not None})
        return subject, structure

    @classmethod
    def parse_subject_page(
        cls,
        html: str,
        base_url: str,
        faculty_name: str,
    ) -> SubjectDetails:
        subject, _ = cls.parse_subject_page_with_structure(
            html,
            base_url,
            faculty_name,
        )
        return subject

    @staticmethod
    def _normalized_text(node) -> str:
        text = node.get_text(" ", strip=True).replace("\xa0", " ")
        return " ".join(text.split())

    @staticmethod
    def _section_name_from_header(node) -> Optional[str]:
        if getattr(node, "name", None) != "font" or node.get("size") != "+2":
            return None

        section_name = Parser._normalized_text(node)
        if section_name in {"学部", "大学院"}:
            return section_name
        return None

    @staticmethod
    def _extract_department_names_from_group(img):
        names = []
        row_parts = []
        transition_container = next(
            (
                node for node in img.next_siblings
                if getattr(node, "name", None) == "p"
                and node.find("table")
                and any(
                    Parser._section_name_from_header(font)
                    for font in node.find_all("font")
                )
            ),
            None,
        )

        def flush_row():
            name = "".join(row_parts).replace("\xa0", " ")
            name = " ".join(name.split())
            if name:
                names.append(name)
            row_parts.clear()

        for node in img.next_elements:
            # The legacy top page puts a table-based legend and the next
            # section header in a direct p after the list, outside row data.
            if node is transition_container:
                flush_row()
                break
            if Parser._section_name_from_header(node):
                flush_row()
                break
            is_list_marker = (
                getattr(node, "name", None) == "img"
                and node.get("src", "").endswith("syllabus_list.gif")
            )
            if is_list_marker:
                flush_row()
                break
            if getattr(node, "name", None) == "br":
                flush_row()
                continue
            if getattr(node, "name", None):
                continue

            text = str(node)
            if text.strip():
                row_parts.append(text)

        flush_row()
        return names

    @staticmethod
    def parse_department_lists(html: str) -> dict[str, list[str]]:
        soup = Parser.get_html_soup(html)
        result = {
            "kaikouBukyokuGakubus": [],
            "kaikouBukyokuDaigakuins": [],
        }
        seen_gakubu = set()
        seen_daigakuin = set()

        section_keys = {
            "学部": ("kaikouBukyokuGakubus", seen_gakubu),
            "大学院": ("kaikouBukyokuDaigakuins", seen_daigakuin),
        }

        for img in soup.select('img[src*="syllabus_list.gif"]'):
            section_name = next(
                (
                    Parser._section_name_from_header(font)
                    for font in img.find_all_previous("font")
                    if Parser._section_name_from_header(font)
                ),
                None,
            )
            section = section_keys.get(section_name)
            if section is None:
                continue

            result_key, seen = section
            names = Parser._extract_department_names_from_group(img)
            for name in names:
                if name not in seen:
                    seen.add(name)
                    result[result_key].append(name)

        return result
