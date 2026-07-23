"""带外（out-of-band）用户令牌：login 换 token + 本地存储 + 读取。

铁律（REFACTOR_PLAN §5.2 铁律 3）：身份走传输层可信 token，**绝不做成 MCP 工具参数**；
登录走带外 CLI（``rag-mcp login``），token 存本地文件，MCP server 启动时加载、每请求
经 ``Authorization`` 头透传给 rag-search，**全程不经模型**。

零 rag-core 依赖（保持 rag-mcp 独立可发布）；仅用 stdlib + httpx。

登录契约（业务侧后续实现，现按此格式对接）：
    POST <login_url>  JSON {"phone": <手机号>, "code": <验证码>}
    → 200 {"token": "<user token>", ...(可含 expires_at 等)}
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

__all__ = [
    "ENV_TOKEN",
    "ENV_TOKEN_FILE",
    "ENV_LOGIN_URL",
    "ENV_SERVICE_TOKEN",
    "token_file_path",
    "load_token",
    "save_token",
    "clear_token",
    "login",
]

ENV_TOKEN = "RAG_MCP_TOKEN"
ENV_TOKEN_FILE = "RAG_MCP_TOKEN_FILE"
ENV_LOGIN_URL = "RAG_MCP_LOGIN_URL"
ENV_SERVICE_TOKEN = "RAG_MCP_SERVICE_TOKEN"


def token_file_path() -> Path:
    """令牌文件路径。``RAG_MCP_TOKEN_FILE`` 覆盖；否则平台配置目录下 ``rag-mcp/token.json``。"""
    override = os.environ.get(ENV_TOKEN_FILE)
    if override:
        return Path(override)
    if os.name == "nt":
        base = Path(os.environ.get("APPDATA") or (Path.home() / "AppData" / "Roaming"))
    else:
        base = Path(os.environ.get("XDG_CONFIG_HOME") or (Path.home() / ".config"))
    return base / "rag-mcp" / "token.json"


def save_token(token: str, *, base_url: str | None = None, extra: dict | None = None) -> Path:
    """把 token 写入本地文件（权限收敛 0600）。"""
    path = token_file_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    data: dict[str, Any] = {"token": token}
    if base_url:
        data["base_url"] = base_url
    if extra:
        data.update(extra)
    path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    try:
        os.chmod(path, 0o600)  # 限制权限（Windows 上无害）
    except OSError:
        pass
    return path


def load_token() -> str | None:
    """读取 token：优先 ``RAG_MCP_TOKEN`` 环境变量，其次本地文件；无则 None。"""
    env = os.environ.get(ENV_TOKEN)
    if env:
        return env
    path = token_file_path()
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    token = data.get("token")
    return token or None


def clear_token() -> bool:
    """删除本地 token 文件；删除了返回 True，本就不存在返回 False。"""
    path = token_file_path()
    if path.exists():
        path.unlink()
        return True
    return False


def login(login_url: str, phone: str, code: str, *, timeout: float = 10.0, client=None) -> dict:
    """带外登录：手机号 + 验证码 → 业务响应（至少含 ``token``）。

    ``client`` 可注入（须有 ``.post(url, json=, timeout=)``，用于测试）；缺省用 httpx。
    """
    http = client
    if http is None:
        import httpx

        http = httpx
    resp = http.post(login_url, json={"phone": phone, "code": code}, timeout=timeout)
    resp.raise_for_status()
    return resp.json()
