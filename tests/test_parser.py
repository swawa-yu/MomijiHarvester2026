from pathlib import Path
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
    gakubus = departments["kaikouBukyokuGakubus"]
    daigakuins = departments["kaikouBukyokuDaigakuins"]

    assert len(gakubus) == 40
    assert len(daigakuins) == 107
    assert len(gakubus) == len(set(gakubus))
    assert len(daigakuins) == len(set(daigakuins))
    assert gakubus[0] == "教養教育"
    assert gakubus[-1] == "IDEC国際連携機構"
    assert daigakuins[0] == "大学院共通教育（博士課程前期）"
    assert daigakuins[-1] == "IDEC国際連携機構（大学院）"

    assert "教育学部" in gakubus
    assert "人間社会科学研究科博士課程前期人文社会科学専攻心理学プログラム" in daigakuins
    assert "人間社会科学研究科博士課程前期人文社会科学専攻マネジメントプログラム" in daigakuins
    assert "人間社会科学研究科博士課程前期人文社会科学専攻ソーシャルデータサイエンスプログラム" in daigakuins
    assert "統合生命科学研究科博士課程後期統合生命科学専攻食品生命科学プログラム" in daigakuins
    law_index = gakubus.index("法学部")
    assert gakubus[law_index:law_index + 4] == [
        "法学部",
        "法学部法学科",
        "法学部法学科昼間コース",
        "法学部法学科夜間主コース",
    ]
    assert "人間社会科学研究科博士課程前期人文社会科学専攻" in daigakuins
    assert "大学院共通教育（博士課程前期）" not in gakubus


def test_parse_department_lists_handles_nested_inline_section_markup():
    html = """
    <font size="+2"> 学部 </font>
    <img src="syllabus_list.gif">
    <span>親<label><br>子</label></span><br>
    <font>大学院</font>装飾ラベル<br>
    <img src="syllabus_list.gif">
    <div>次の学部ラベル<br><font size="+2"> 大学院 </font></div><br>
    <img src="syllabus_list.gif">
    <span>大学院の親<br>大学院の子</span><br>
    <font size="+2"> 学部 </font>
    <img src="syllabus_list.gif">
    <p>p内の有効な学部ラベル<br><font size="+2"> 大学院 </font></p>
    <img src="syllabus_list.gif">
    p境界後の大学院ラベル<br>
    <font size="+2"> 学部 </font>
    <img src="syllabus_list.gif">
    table境界前の学部ラベル<br>
    <p>凡例テキスト<br><table><tr><td>凡例表</td></tr></table>
    <font size="+2"> 大学院 </font></p>
    <img src="syllabus_list.gif">
    table境界後の大学院ラベル<br>
    """

    departments = Parser.parse_department_lists(html)

    assert departments["kaikouBukyokuGakubus"] == [
        "親",
        "子",
        "大学院装飾ラベル",
        "次の学部ラベル",
        "p内の有効な学部ラベル",
        "table境界前の学部ラベル",
    ]
    assert departments["kaikouBukyokuDaigakuins"] == [
        "大学院の親",
        "大学院の子",
        "p境界後の大学院ラベル",
        "table境界後の大学院ラベル",
    ]
    assert "凡例テキスト" not in departments["kaikouBukyokuGakubus"]
