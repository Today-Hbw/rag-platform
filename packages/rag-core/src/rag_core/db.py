"""MySQL 连接工厂。统一自 download/clean_md/vectorize/search 四处逐字重复的 get_db_connection。"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pymysql

from .settings import Settings, get_settings

if TYPE_CHECKING:
    from pymysql.connections import Connection

__all__ = ["get_connection"]


def get_connection(settings: Settings | None = None) -> Connection:
    """按配置建 pymysql 连接（DictCursor）。密钥从 SecretStr 取值。"""
    s = (settings or get_settings()).mysql
    return pymysql.connect(
        host=s.host,
        port=s.port,
        user=s.user,
        password=s.password.get_secret_value(),
        database=s.database,
        charset=s.charset,
        cursorclass=pymysql.cursors.DictCursor,
    )
