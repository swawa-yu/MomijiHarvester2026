from pydantic import BaseModel, Field


class ScraperConfig(BaseModel):
    base_url: str = Field(..., description="トップページ URL")
    rate_limit_seconds: float = Field(
        0.1,
        ge=0,
        allow_inf_nan=False,
        description="1リクエストあたりの待機秒数",
    )
    timeout_seconds: int = Field(10, description="HTTPタイムアウト")
    max_retries: int = Field(3, ge=0, description="一時的HTTP失敗の最大再試行回数")
    retry_initial_delay_seconds: float = Field(
        0.5,
        ge=0,
        allow_inf_nan=False,
        description="最初の再試行までの待機秒数",
    )
    retry_backoff_max_seconds: float = Field(
        4.0,
        ge=0,
        allow_inf_nan=False,
        description="指数バックオフの待機上限秒数",
    )
    retry_after_max_seconds: float = Field(
        60.0,
        ge=0,
        allow_inf_nan=False,
        description="Retry-Afterに従う待機時間の安全上限秒数",
    )
    max_workers: int = Field(5, description="同時リクエスト数")
    output_dir: str = Field("output", description="JSON出力ディレクトリ")
    user_agent: str = Field(
        "MomijiHarvester/1.0 (+https://github.com/swawa-yu/MomijiHarvester2026)",
        description="HTTP User-Agentヘッダ",
    )
