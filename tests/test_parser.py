import pytest
from src.parser import Parser
from src.models import SubjectDetails


def test_parse_subject_page_minimal():
    html = """
    <html><body>
      <div id='年度'>2025年度</div>
      <div id='講義コード'>10000100</div>
      <div id='科目区分'>大学教育入門</div>
      <div id='授業科目名'>大学教育入門[1総総,1文,1経]</div>
      <div id='担当教員名'>林 光緒</div>
    </body></html>
    """

    subject = Parser.parse_subject_page(html, "2025_AA_10000100.html", "教養教育")
    assert isinstance(subject, SubjectDetails)
    assert subject.講義コード == "10000100"
    assert subject.年度 == "2025年度"
    assert subject.開講部局 == "教養教育"
