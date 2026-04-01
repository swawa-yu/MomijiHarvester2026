from pydantic import BaseModel, Field


class SubjectDetails(BaseModel):
    relative_url: str = Field(..., alias="relative URL")
    年度: str
    開講部局: str
    講義コード: str
    科目区分: str
    授業科目名: str
    担当教員名: str
    開講キャンパス: str
    開設期: str
    曜日・時限・講義室: str
    単位: str
    使用言語: str
    学習の段階: str
    対象学生: str
    授業の目標・概要等: str
    予習・復習への アドバイス: str
    履修上の注意 受講条件等: str
    メッセージ: str
    その他: str
