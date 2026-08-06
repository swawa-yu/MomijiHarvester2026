from pathlib import Path
import pytest
from src.parser import Parser
from src.models import SubjectDetails


def test_parse_subject_page_minimal():
    html = """
    <html><body>
      <table>
        <tr><th>年度</th><td>2025年度</td></tr>
        <tr><th>講義コード</th><td>10000100</td></tr>
        <tr><th>科目区分</th><td>大学教育入門</td></tr>
        <tr><th>授業科目名</th><td>大学教育入門[1総総,1文,1経]</td></tr>
        <tr><th>担当教員名</th><td>林 光緒</td></tr>
      </table>
    </body></html>
    """

    subject = Parser.parse_subject_page(html, "2025_AA_10000100.html", "教養教育")
    assert isinstance(subject, SubjectDetails)
    assert subject.code == "10000100"
    assert subject.nendo == "2025年度"
    assert subject.faculty == "教養教育"


def test_parse_subject_page_with_actual_sample():
    html = Path("tests/sample/2026_AA_10000100.html").read_text(encoding="utf-8")
    subject = Parser.parse_subject_page(html, "2026_AA_10000100.html", "教養教育")

    assert subject.code == "10000100"
    assert subject.category == "大学教育入門"
    assert subject.title.startswith("大学教育入門")
    assert subject.instructor.replace(" ", "").replace("　", "") == "林光緒"
    assert "東広島" in subject.campus
    assert "1年次生" in subject.term
    assert subject.credits == "2.0"
    assert subject.language.startswith("B")
    obj = subject.model_dump(by_alias=True)
    assert "大学で学ぶということはどういうことか" in obj["授業の目標・概要等"]
    assert "受講または授業動画視聴前に" in obj["予習・復習への アドバイス"]
    assert "第1章、12章、15章" in obj["履修上の注意 受講条件等"]
    assert "今、みなさんは" in obj["メッセージ"]


def test_parse_department_lists_from_index_sample():
    html = Path("tests/sample/index.html").read_text(encoding="utf-8")
    departments = Parser.parse_department_lists(html)

    assert departments["kaikouBukyokuGakubus"][0] == "教養教育"
    assert "総合科学部総合科学科" in departments["kaikouBukyokuGakubus"]
    assert "法学部法学科夜間主コース" in departments["kaikouBukyokuGakubus"]
    assert "法学部" not in departments["kaikouBukyokuGakubus"]
    assert departments["kaikouBukyokuDaigakuins"][0] == "大学院共通教育（博士課程前期）"
    assert "人間社会科学研究科博士課程前期人文社会科学専攻人文学プログラム" in departments["kaikouBukyokuDaigakuins"]
    assert "人間社会科学研究科博士課程前期人文社会科学専攻" not in departments["kaikouBukyokuDaigakuins"]
