from pathlib import Path

import pytest

from src.parser import Parser, SubjectStructureError
from src.models import SubjectDetails


def subject_page(overrides=None, omitted=(), extra=()):
    values = {header: "" for header in Parser.SUBJECT_CONTRACT_HEADERS}
    values.update({
        "年度": "2026年度",
        "開講部局": "教養教育",
        "講義コード": "10000100",
        "科目区分": "大学教育入門",
        "授業科目名": "大学教育入門",
        "担当教員名": "林 光緒",
    })
    values.update(overrides or {})
    rows = [
        f"<tr><th>{header}</th><td>{value}</td></tr>"
        for header, value in values.items()
        if header not in omitted
    ]
    rows.extend(
        f"<tr><th>{header}</th><td>{value}</td></tr>"
        for header, value in extra
    )
    return f"<table>{''.join(rows)}</table>"


def test_parse_subject_page_minimal():
    html = subject_page({
        "年度": "2025年度",
        "授業科目名": "大学教育入門[1総総,1文,1経]",
    })

    subject = Parser.parse_subject_page(html, "2025_AA_10000100.html", "教養教育")
    assert isinstance(subject, SubjectDetails)
    assert subject.code == "10000100"
    assert subject.nendo == "2025年度"
    assert subject.faculty == "教養教育"


def test_unknown_header_is_projected_out_of_subject():
    subject = Parser.parse_subject_page(
        subject_page(extra=(("追加項目", "秘密の値"),)),
        "extra.html",
        "教養教育",
    )
    assert len(subject.model_dump(by_alias=True)) == 19
    assert "追加項目" not in subject.model_dump(by_alias=True)


def test_structure_summary_counts_unknown_empty_and_informational_headers():
    extra = (("追加項目", ""),) + tuple(
        (header, "説明") for header in Parser.INFORMATIONAL_HEADERS
    )
    _, first = Parser.inspect_subject_page_structure(
        subject_page(extra=extra), "first.html"
    )
    _, second = Parser.inspect_subject_page_structure(
        subject_page(extra=(("追加項目", "値"),)), "second.html"
    )
    report = Parser.summarize_subject_page_structures([first, second])
    assert report["unknownHeaders"] == ["追加項目"]
    assert report["headerPresence"]["追加項目"] == {
        "presentCount": 2, "presenceRate": 1,
        "emptyCount": 1, "emptyRate": 0.5,
    }
    for header in Parser.INFORMATIONAL_HEADERS:
        assert header not in report["unknownHeaders"]
        assert report["headerPresence"][header]["presentCount"] == 1


def test_duplicate_required_header_with_different_values_is_fatal():
    html = subject_page() + "<table><tr><th>年度</th><td>2025年度</td></tr></table>"
    with pytest.raises(SubjectStructureError):
        Parser.parse_subject_page(html, "duplicate.html", "教養教育")


def test_inspect_subject_structure_detects_added_removed_and_renamed_headers():
    _, added = Parser.inspect_subject_page_structure(
        subject_page(extra=(("新しい項目", "値"),)),
        "added.html",
    )
    assert added["unknownHeaders"] == ["新しい項目"]
    assert added["missingHeaders"] == []

    _, removed = Parser.inspect_subject_page_structure(
        subject_page(omitted=("使用言語",)),
        "removed.html",
    )
    assert removed["unknownHeaders"] == []
    assert removed["missingHeaders"] == ["使用言語"]

    renamed_html = subject_page(
        omitted=("使用言語",),
        extra=(("授業言語", "日本語"),),
    )
    _, renamed = Parser.inspect_subject_page_structure(
        renamed_html,
        "renamed.html",
    )
    assert renamed["unknownHeaders"] == ["授業言語"]
    assert renamed["missingHeaders"] == ["使用言語"]

    with pytest.raises(ValueError) as error:
        Parser.parse_subject_page(renamed_html, "renamed.html", "教養教育")
    assert "授業言語" in str(error.value)
    assert "使用言語" in str(error.value)


def test_summarize_subject_structure_reports_presence_and_empty_rates():
    _, complete = Parser.inspect_subject_page_structure(
        subject_page(),
        "complete.html",
    )
    _, missing = Parser.inspect_subject_page_structure(
        subject_page(omitted=("メッセージ",)),
        "missing.html",
    )

    report = Parser.summarize_subject_page_structures([complete, missing])

    assert report["subjectPageCount"] == 2
    assert report["missingHeaders"] == ["メッセージ"]
    assert report["headerPresence"]["年度"] == {
        "presentCount": 2,
        "presenceRate": 1,
        "emptyCount": 0,
        "emptyRate": 0,
    }
    assert report["headerPresence"]["メッセージ"] == {
        "presentCount": 1,
        "presenceRate": 0.5,
        "emptyCount": 1,
        "emptyRate": 0.5,
    }


def test_subject_structure_is_independent_of_row_order():
    html = subject_page()
    body = html.removeprefix("<table>").removesuffix("</table>")
    rows = [row + "</tr>" for row in body.split("</tr>") if row]
    reordered_html = f"<table>{''.join(reversed(rows))}</table>"

    _, original = Parser.inspect_subject_page_structure(html, "original.html")
    _, reordered = Parser.inspect_subject_page_structure(
        reordered_html,
        "reordered.html",
    )

    assert reordered["observedHeaders"] == original["observedHeaders"]
    assert reordered["emptyHeaders"] == original["emptyHeaders"]
    assert reordered["unknownHeaders"] == []
    assert reordered["missingHeaders"] == []


def test_parse_subject_page_rejects_missing_header_with_source_url():
    html = subject_page(omitted=("使用言語",))

    with pytest.raises(ValueError) as error:
        Parser.parse_subject_page(html, "missing-language.html", "教養教育")

    assert "Missing subject header(s)" in str(error.value)
    assert "使用言語" in str(error.value)
    assert "missing-language.html" in str(error.value)


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
