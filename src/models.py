from pydantic import BaseModel, Field


class SubjectDetails(BaseModel):
    relative_url: str = Field(..., alias="relative URL")
    nendo: str = Field("", alias="年度")
    faculty: str = Field("", alias="開講部局")
    code: str = Field("", alias="講義コード")
    category: str = Field("", alias="科目区分")
    title: str = Field("", alias="授業科目名")
    instructor: str = Field("", alias="担当教員名")
    campus: str = Field("", alias="開講キャンパス")
    term: str = Field("", alias="開設期")
    schedule: str = Field("", alias="曜日・時限・講義室")
    credits: str = Field("", alias="単位")
    language: str = Field("", alias="使用言語")
    level: str = Field("", alias="学習の段階")
    target_students: str = Field("", alias="対象学生")
    course_overview: str = Field("", alias="授業の目標・概要等")
    preparation_advice: str = Field("", alias="予習・復習への アドバイス")
    enrolment_notes: str = Field("", alias="履修上の注意 受講条件等")
    message: str = Field("", alias="メッセージ")
    other: str = Field("", alias="その他")
