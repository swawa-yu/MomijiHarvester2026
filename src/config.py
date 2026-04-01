from pydantic import BaseModel, Field


class ScraperConfig(BaseModel):
    base_url: str = Field(..., description="トップページ URL")
    rate_limit_seconds: float = Field(0.5, description="1リクエストあたりの待機秒数")
    timeout_seconds: int = Field(10, description="HTTPタイムアウト")
    max_workers: int = Field(5, description="同時リクエスト数")
    output_dir: str = Field("output", description="JSON出力ディレクトリ")
    user_agent: str = Field(
        "MomijiHarvester/1.0 (+https://github.com/swawa-yu/MomijiHarvester2026)",
        description="HTTP User-Agentヘッダ",
    )
