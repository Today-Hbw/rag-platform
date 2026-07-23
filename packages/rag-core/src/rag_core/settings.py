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
    "LocalSettings",
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
    # books 列表（非密钥：book_id/book_slug/namespace/title/token）JSON 配置路径。
    books_config: str = "config/connectors/yuque.json"
    # source_url 模板；部署侧按真实语雀空间覆盖以与旧产出对齐（见阶段4第5步等价对拍）。
    url_template: str = "https://www.yuque.com/{namespace}/{collection_slug}/{doc_key}"


class LocalSettings(BaseModel):
    """本地文件 connector：从目录树读 .md 作为文档源（多源抽象的验证/离线兜底）。"""

    root: str = ""  # markdown 根目录
    collection_id: str = "local"  # 该源的 collection 标识


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
    # 按 role_ids 过滤检索结果的总开关；false=旧行为(全量可见)。
    enabled: bool = False
    # 携带用户角色的请求头(业务系统置);检索时读它解析可见范围。
    roles_header: str = "X-Role-Ids"
    # 业务系统↔RAG 的共享服务令牌(证明调用方是业务系统)；空=不校验(兼容现状)。
    # 调用方置于 ``X-Service-Token`` 头(与用户 token 的 Authorization 头分开)。
    service_token: SecretStr = SecretStr("")

    # ---- introspection（token → role_ids，增量①）----
    # 业务系统的 token 内省接口。**空(默认)=离线/调试模式**：不调远程，直接信
    # ``X-Role-Ids`` 头(等价 bda10ab 旧行为)。有值=在线模式：拿用户 token 调它换 role_ids。
    introspect_url: str = ""
    # 调 introspection 的超时(秒)。
    introspect_timeout: float = 3.0
    # 内省结果(token→身份)的进程内缓存 TTL(秒)。0=不缓存。
    scope_cache_ttl: int = 300
    # 离线模式下的静态默认角色：X-Role-Ids 头缺失时兜底(JSON 数组，如 ``["12","34"]``)。
    default_role_ids: list[str] = []
    # 调 introspection 时附带的服务令牌头(让业务系统信任 RAG)；空=不带。
    introspect_service_token: SecretStr = SecretStr("")


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
    local: LocalSettings = LocalSettings()
    search: SearchSettings = SearchSettings()
    pipeline: PipelineSettings = PipelineSettings()
    paths: PathSettings = PathSettings()
    rbac: RbacSettings = RbacSettings()
    extract: ExtractSettings = ExtractSettings()


@lru_cache
def get_settings() -> Settings:
    """进程内单例配置。"""
    return Settings()
