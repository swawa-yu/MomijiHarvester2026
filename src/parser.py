from bs4 import BeautifulSoup
from src.models import SubjectDetails


class Parser:
    @staticmethod
    def get_html_soup(html: str) -> BeautifulSoup:
        return BeautifulSoup(html, "html.parser")

    @staticmethod
    def parse_subject_page(html: str, base_url: str, faculty_name: str) -> SubjectDetails:
        soup = Parser.get_html_soup(html)

        # 表形式データを行単位で取得
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

        def normalize_label(key: str) -> str:
            return key.replace(" ", "").replace("\u3000", "").replace("\n", "").replace("<BR>", "").strip()

        def find_value(expected: str, alternates=None):
            alternates = alternates or []
            normalized_expected = normalize_label(expected)
            for k, v in raw.items():
                if normalize_label(k) == normalized_expected:
                    return v
            for alt in alternates:
                for k, v in raw.items():
                    if normalize_label(k) == normalize_label(alt):
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

        return SubjectDetails(**{k: v for k, v in data.items() if v is not None})
