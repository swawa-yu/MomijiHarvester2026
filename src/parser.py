from bs4 import BeautifulSoup
from src.models import SubjectDetails


class Parser:
    @staticmethod
    def get_html_soup(html: str) -> BeautifulSoup:
        return BeautifulSoup(html, "html.parser")

    @staticmethod
    def parse_subject_page(html: str, base_url: str, faculty_name: str) -> SubjectDetails:
        soup = Parser.get_html_soup(html)

        def get_text(selector: str, default: str = "") -> str:
            el = soup.select_one(selector)
            return el.get_text(strip=True) if el else default

        data = {
            "relative URL": base_url,
            "年度": get_text("#年度") if soup.select_one("#年度") else "",
            "開講部局": faculty_name,
            "講義コード": get_text("#講義コード"),
            "科目区分": get_text("#科目区分"),
            "授業科目名": get_text("#授業科目名"),
            "担当教員名": get_text("#担当教員名"),
            "開講キャンパス": get_text("#開講キャンパス"),
            "開設期": get_text("#開設期"),
            "曜日・時限・講義室": get_text("#曜日・時限・講義室"),
            "単位": get_text("#単位"),
            "使用言語": get_text("#使用言語"),
            "学習の段階": get_text("#学習の段階"),
            "対象学生": get_text("#対象学生"),
            "授業の目標・概要等": get_text("#授業の目標・概要等"),
            "予習・復習への アドバイス": get_text("#予習・復習への アドバイス"),
            "履修上の注意 受講条件等": get_text("#履修上の注意 受講条件等"),
            "メッセージ": get_text("#メッセージ"),
            "その他": get_text("#その他"),
        }

        # 一部ページでキー名が異なる場合は追加変換を実装
        return SubjectDetails(**{k: v for k, v in data.items() if v is not None})
