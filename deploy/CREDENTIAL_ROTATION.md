# 凭据轮换清单

> 背景：旧仓 `rag_yuque_qdrant` 的 `config.json` / `download_config.json` 含明文密钥，且已推送到 origin/main，**视为已泄漏**。无论新仓是否弃用旧历史，以下凭据**都必须轮换**——东西已经在远端和他人本地/fork/CI 缓存里了。
>
> 轮换后把新值填入本地 `.env`（不入库），并同步重启所有连接的服务。

| # | 凭据 | 旧位置 | 轮换入口 | 验证方式 | 责任人 | 状态 |
|---|------|--------|----------|----------|--------|:---:|
| 1 | 豆包 / 火山方舟 API Key | `config.json: doufan_api_key` | 火山方舟控制台重签 | 跑一次 embedding 探测成功 | | ⬜ |
| 2 | 语雀 API Token | `download_config.json: books[].token` | 语雀 → 设置 → Token 重新生成 | 拉一次知识库文档列表成功 | | ⬜ |
| 3 | 语雀浏览器 Cookie | `config.json: yuque_cookie` | 重新登录语雀获取（会话态，会过期） | 下载一个附件成功 | | ⬜ |
| 4 | MySQL 口令 | `config.json: mysql.password`（当前是 **root**） | 改口令；**建议顺手建最小权限应用账号**替代 root（只授 `rag_*` / `qdrant_yuque_kb_*` 表） | 应用账号连库读写成功 | | ⬜ |
| 5 | Redis 口令 | `config.json: redis.password` | 改 `requirepass` | 缓存读写成功 | | ⬜ |

## 防再次泄漏
- [ ] 新仓 `.gitignore` 已忽略 `.env` / `config.json` / `download_config.json`（已配置）
- [ ] 接入 gitleaks（CI + pre-commit，已配置 `.pre-commit-config.yaml` / `.github/workflows/ci.yml`）
- [ ] 旧仓 `rag_yuque_qdrant` 处置：本地记录可弃用；若远端仍在且仓库为私有，评估是否需清史或直接归档/删除（不影响新仓）
