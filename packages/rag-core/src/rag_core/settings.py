"""统一配置源（pydantic-settings）。替换四处重复的 load_config()。

- 环境变量：前缀 ``RAG_`` + 嵌套分隔 ``__``；
  例 ``RAG_MYSQL__PASSWORD`` → ``settings.mysql.password``。
- 密钥统一 ``SecretStr``，取值用 ``.get_secret_value()``（防日志/repr 泄漏）。
- 也读取工作目录下的 ``.env``。
"""

from __future__ import annotations

from functools import lru_cache

from pydantic import BaseModel, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

__all__ = [
    "MySQLSettings",
    "RedisSettings",
    "EmbeddingSettings",
    "QdrantSettings",
    "YuqueSettings",
    "SearchSettings",
    "PipelineSettings",
    "PathSettings",
    "RbacSettings",
    "ExtractSettings",
    "Settings",
    "get_settings",
]


class MySQLSettings(BaseModel):
    host: str = "localhost"
    port: int = 3306
    user: str = "root"
    password: SecretStr = SecretStr("")
    database: str = "hro_python"
    charset: str = "utf8mb4"


class RedisSettings(BaseModel):
    host: str = "localhost"
    port: int = 6379
    password: SecretStr = SecretStr("")
    db: int = 0
    cache_ttl_min: int = 3600
    cache_ttl_max: int = 7200


class EmbeddingSettings(BaseModel):
    api_key: SecretStr = SecretStr("")
    model_endpoint: str = ""
    url: str = "https://ark.cn-beijing.volces.com/api/v3/embeddings/multimodal"
    vector_dim: int = 2048
    max_images_per_chunk: int = 3
    max_image_size_mb: int = 10


class QdrantSettings(BaseModel):
    url: str = "http://localhost:6333"
    collection: str = "knowledge_documents"


class YuqueSettings(BaseModel):
    token: SecretStr = SecretStr("")
    cookie: SecretStr = SecretStr("")


class SearchSettings(BaseModel):
    recall_limit: int = 100
    rrf_k: int = 20
    title_weight: int = 7


class PipelineSettings(BaseModel):
    chunk_size: int = 500
    chunk_overlap: int = 100


class PathSettings(BaseModel):
    data_root: str = "./output"


class RbacSettings(BaseModel):
    enabled: bool = False
    identity_header: str = "X-User-Id"


class ExtractSettings(BaseModel):
    """附件文本提取的外部工具与参数（D1=Linux：路径默认 None → 走 PATH/自动发现）。"""

    tesseract_cmd: str | None = None  # None → 走 PATH
    poppler_bin: str | None = None  # None → 走 PATH（pdf2image）
    libreoffice_bin: str | None = None  # None → 自动发现 soffice/libreoffice
    antiword_cmd: str = "antiword"
    pdftotext_cmd: str = "pdftotext"
    ocr_lang: str = "chi_sim+eng"
    ocr_max_pages: int = 20
    ocr_dpi: int = 200
    zip_max_files: int = 50
    zip_max_file_size_mb: int = 10


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="RAG_",
        env_nested_delimiter="__",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    mysql: MySQLSettings = MySQLSettings()
    redis: RedisSettings = RedisSettings()
    embedding: EmbeddingSettings = EmbeddingSettings()
    qdrant: QdrantSettings = QdrantSettings()
    yuque: YuqueSettings = YuqueSettings()
    search: SearchSettings = SearchSettings()
    pipeline: PipelineSettings = PipelineSettings()
    paths: PathSettings = PathSettings()
    rbac: RbacSettings = RbacSettings()
    extract: ExtractSettings = ExtractSettings()


@lru_cache
def get_settings() -> Settings:
    """进程内单例配置。"""
    return Settings()
