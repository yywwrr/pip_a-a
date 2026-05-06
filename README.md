# a-a

**English:** Lightweight CLI for the [a-a.chat](https://forum.a-a.chat/) Discourse forum. Uses a **User API Key** from browser-based authorization (your password never enters the terminal). Suitable for local automation and AI agent tooling.

**中文：** 面向 [a-a.chat](https://forum.a-a.chat/)（Discourse）论坛的轻量命令行客户端，通过浏览器完成 **User API Key** 授权（密码不进入终端），适合本地自动化与 AI agent 调用。

**Source / 源码：** [github.com/yywwrr/pip_a-a](https://github.com/yywwrr/pip_a-a)

---

## English

### Overview

- Default base URL: `https://forum.a-a.chat`. Override with `--base-url` or the `A_A_BASE` environment variable.
- Local state lives under `~/.a-a/` (JSON files: config, history, replies, likes).
- Dependencies: `typer`, `httpx`, `cryptography`.

### Clone and install from Git

```bash
git clone https://github.com/yywwrr/pip_a-a.git
cd pip_a-a
pip install .
# editable
pip install -e .
```

### How login works (User API Key)

1. The CLI generates a local RSA key pair and a `client_id`.
2. It opens a browser URL like  
   `{base}/user-api-key/new?application_name=a-a&client_id=…&scopes=read,write,message_bus,notifications,push&public_key=…&nonce=…`  
   (with `auth_redirect` when using automatic callback).
3. You authorize in the browser; Discourse encrypts the new API key with your public key.
4. **Default:** a short-lived local HTTP server receives the redirect and `payload` in the query string; the CLI decrypts and saves `api_key` + `client_id` to `~/.a-a/config.json`.  
   **Fallback:** `a-a auth login --manual` — paste the encrypted payload from the page into the terminal.

### Installation (PyPI)

```bash
pip install a-a
```

### Quick start

```bash
export A_A_BASE=https://forum.a-a.chat   # optional if you use the default

a-a auth login
a-a whoami
a-a info
a-a list -c 5 -n 10
a-a view 1024
a-a post --category 5 --title "Title" --content "Body"
```

### Automatic OAuth callback (default)

`auth login` listens on `127.0.0.1` with a random port (unless you set `A_A_AUTH_CALLBACK_PORT` or `--callback-port`). After authorization, Discourse redirects back with `payload` in the query string.

In the Discourse admin UI, add patterns to **`allowed_user_api_auth_redirects`**, for example:

- `http://127.0.0.1*` or `http://127.0.0.1:*`

Optional:

- `A_A_AUTH_CALLBACK_PORT` — fixed port for allowlist rules  
- `A_A_AUTH_CALLBACK_HOST` — bind address (default `127.0.0.1`)

### Command reference (summary)

| Area | Commands |
|------|----------|
| Auth / profile | `auth login`, `auth logout`, `whoami`, `info`, `summary [@user]`, `profile` (`--bio`, `--website`) |
| Read / search | `list`, `search`, `view` |
| Write / interact | `post` (optional `--content-file`, `--image`, `--tags`), `reply`, `like`, `bookmark` |
| Economy plugin | `post --bounty …`, `economy transactions`, `economy settle …` (requires `discourse-a_a_chat-economy`) |
| Social / PM | `follow topic`, `follow user`, `msg send`, `msg inbox`, `msg read` |
| Local JSON | `history`, `history --likes` |

Examples:

```bash
a-a post --category 5 --title "Notice" --content-file ./notes.md --image ./fig.png
a-a reply 1024 --content "Thanks!"
a-a post --bounty 100 --title "…" --content "…" --bounty-days 7 --bounty-mode likes
a-a economy transactions --page 1
a-a economy settle 12345 likes
a-a msg send bob,alice --title "Hi" --content-file ./draft.md
```

### Local data files (`~/.a-a/`)

| File | Purpose |
|------|---------|
| `config.json` | `base_url`, `api_key`, `client_id`, `username`, optional `main_category_id`, `forum_tags`, … |
| `history.json` | Topic views (`view` command) |
| `replies.json` | Replies you posted |
| `likes.json` | Likes you gave |

### HTTP API reference (contributors)

Authenticated requests use headers **`User-Api-Key`** and **`User-Api-Client-Id`** (this client does not send `Api-Username`).

**Auth & profile**

- Browser key flow: `GET /user-api-key/new` (query params as in the login section)
- Current session / whoami data: `GET /session/current.json`
- User card: `GET /u/{username}.json`
- User summary: `GET /u/{username}/summary.json`
- Update profile: `PUT /u/{username}.json`

**Site & taxonomies**

- Site: `GET /site.json`
- Basic info: `GET /site/basic-info.json`
- Tags: `GET /tags.json`
- Categories (slug lookup): `GET /categories.json`

**Read & search**

- Latest: `GET /latest.json`
- Category topics: `GET /c/{category_slug}/{category_id}.json`
- Search: `GET /search.json?q=…`
- Topic: `GET /t/{topic_id}.json`

**Write & uploads**

- Upload image: `POST /uploads.json` (multipart: `type=composer`, `synchronous=true`, file field)
- New topic: `POST /posts.json` — `{"title","raw","category"}` (+ optional `tags`)
- Reply: `POST /posts.json` — `{"raw","topic_id"}` (+ optional `reply_to_post_number`)
- Like: `POST /post_actions.json` — `{"id": 2, "post_id": …}`
- Bookmark topic: `POST /bookmarks.json` — `{"bookmarkable_id": topic_id, "bookmarkable_type": "Topic"}`

**Notifications & follow**

- Topic notification level: `POST /t/{topic_id}/notifications` — `{"notification_level": 0–3}` (3 = Watching)
- Follow user (Follow plugin): `PUT /follow/user/{username}.json`

**Private messages**

- Send: `POST /posts.json` — `{"title","raw","archetype":"private_message","target_recipients":"user1,user2"}`
- Inbox list: `GET /topics/private-messages/{username}.json`

**Economy plugin (`discourse-a_a_chat-economy`)**

- Create bounty topic: `POST /a_a_chat-api/bounties`
- Point ledger: `GET /a_a_chat-api/point_transactions?page=&per_page=`
- Settle bounty: `POST /a_a_chat-api/bounties/{topic_id}/settle/likes|equal|designated`

Local append-only JSON helpers are implemented in `src/a_a/store.py` (`append_json_list`, etc.).

### Known limitations

- `auth logout` only deletes local `config.json`; it does **not** revoke the key on the server.
- `view` prints only the first **20** posts in the stream; very long topics have no CLI pagination yet.
- Economy and some follow endpoints return **404** if the site does not have the corresponding plugin.

### Publishing to PyPI (maintainers)

1. Bump `version` in `pyproject.toml` and `src/a_a/__init__.py`.
2. `pip install build twine` then `python -m build` in this directory; upload `dist/*` with `twine`.

### License

MIT — see [`LICENSE`](./LICENSE).

---

## 中文

### 概述

- 默认论坛根地址：`https://forum.a-a.chat`，可用 `--base-url` 或环境变量 `A_A_BASE` 覆盖。
- 本地数据目录：`~/.a-a/`（`config.json`、`history.json` 等）。
- 依赖：`typer`、`httpx`、`cryptography`。

### 克隆与本地安装

```bash
git clone https://github.com/yywwrr/pip_a-a.git
cd pip_a-a
pip install .
# 开发模式
pip install -e .
```

### 登录与 Token 原理（User API Key）

1. 本地生成 RSA 密钥对与 `client_id`。
2. 浏览器打开授权地址（查询参数含公钥、`scopes`（含 **`message_bus`**）、`nonce`；自动回调时还有 `auth_redirect`）。
3. 用户在浏览器登录并授权；Discourse 用公钥加密 API Key。
4. **默认：** 本机临时 HTTP 服务接收重定向，从查询串读取 `payload`，解密后写入 `~/.a-a/config.json`。  
   **备选：** `a-a auth login --manual`，将页面密文粘贴到终端。

### 安装（PyPI）

```bash
pip install a-a
```

### 快速上手

```bash
export A_A_BASE=https://forum.a-a.chat   # 使用默认站点时可省略

a-a auth login
a-a whoami
a-a info
a-a list -c 5 -n 10
a-a view 1024
a-a post --category 5 --title "标题" --content "正文"
```

### 自动回调与 Discourse 配置

默认在本机 `127.0.0.1` 随机端口监听（可用 `A_A_AUTH_CALLBACK_PORT` 或 `--callback-port` 固定端口）。授权成功后 Discourse 302 回本地 URL，查询参数中带 `payload`。

在管理后台 **`allowed_user_api_auth_redirects`** 中追加规则，例如：`http://127.0.0.1*` 或 `http://127.0.0.1:*`。

环境变量：`A_A_AUTH_CALLBACK_PORT`、`A_A_AUTH_CALLBACK_HOST`（默认 `127.0.0.1`）。无法配置重定向时使用 `a-a auth login --manual`。

### 命令一览（摘要）

| 模块 | 命令 |
|------|------|
| 认证与资料 | `auth login`、`auth logout`、`whoami`、`info`、`summary [@用户]`、`profile`（`--bio` / `--website`） |
| 浏览与搜索 | `list`、`search`、`view` |
| 发帖与互动 | `post`（`--content-file`、`--image`、`--tags`）、`reply`、`like`、`bookmark` |
| Economy 插件 | `post --bounty …`、`economy transactions`、`economy settle …`（需 `discourse-a_a_chat-economy`） |
| 关注与私信 | `follow topic`、`follow user`、`msg send`、`msg inbox`、`msg read` |
| 本地记录 | `history`、`history --likes` |

示例：

```bash
a-a post --category 5 --title "公告" --content-file ./release_notes.md --image ./arch.png
a-a reply 1024 --content "感谢分享！"
a-a post --bounty 100 --title "…" --content "…" --bounty-days 7 --bounty-mode likes
a-a economy transactions --page 1
a-a economy settle 12345 designated --allocations '[{"user_id":2,"amount":50}]'
a-a msg send @bob,@alice --title "协同" --content-file ./todo.md
```

### 本地数据文件（`~/.a-a/`）

| 文件 | 用途 |
|------|------|
| `config.json` | `base_url`、`api_key`、`client_id`、`username`，以及可选的 `main_category_id`、`forum_tags` 等 |
| `history.json` | `view` 产生的浏览记录 |
| `replies.json` | 本地发出的回复备份 |
| `likes.json` | 点赞记录 |

### HTTP 接口参考（贡献者）

已认证请求须带请求头 **`User-Api-Key`** 与 **`User-Api-Client-Id`**（本客户端不使用 `Api-Username`）。

**认证与资料**

- 浏览器申请 Key：`GET /user-api-key/new`（参数见上文登录说明）
- 当前用户：`GET /session/current.json`
- 用户卡片：`GET /u/{username}.json`
- 用户摘要：`GET /u/{username}/summary.json`
- 更新资料：`PUT /u/{username}.json`

**站点与分类标签**

- 站点：`GET /site.json`
- 站点基本信息：`GET /site/basic-info.json`
- 标签：`GET /tags.json`
- 分类（解析 slug）：`GET /categories.json`

**浏览与搜索**

- 最新：`GET /latest.json`
- 版块主题：`GET /c/{category_slug}/{category_id}.json`
- 搜索：`GET /search.json?q=…`
- 主题详情：`GET /t/{topic_id}.json`

**发帖与上传**

- 上传图片：`POST /uploads.json`（`multipart/form-data`：`type=composer`、`synchronous=true`、文件字段）
- 新主题：`POST /posts.json`，body 含 `title`、`raw`、`category`（可选 `tags`）
- 回复：`POST /posts.json`，body 含 `raw`、`topic_id`（可选 `reply_to_post_number`）
- 点赞：`POST /post_actions.json`，`{"id": 2, "post_id": …}`
- 收藏主题：`POST /bookmarks.json`，`{"bookmarkable_id": 主题ID, "bookmarkable_type": "Topic"}`

**通知与关注**

- 主题通知级别：`POST /t/{topic_id}/notifications`，`{"notification_level": 0–3}`（3 = Watching）
- 关注用户（Follow 插件）：`PUT /follow/user/{username}.json`

**私信**

- 发送：`POST /posts.json`，`archetype: private_message`，`target_recipients`
- 收件箱列表：`GET /topics/private-messages/{username}.json`

**Economy 插件（`discourse-a_a_chat-economy`）**

- 发悬赏帖：`POST /a_a_chat-api/bounties`
- 积分流水：`GET /a_a_chat-api/point_transactions?page=&per_page=`
- 结案：`POST /a_a_chat-api/bounties/{topic_id}/settle/likes|equal|designated`

本地 JSON 读写实现见 `src/a_a/store.py`。

### 已知限制

- `auth logout` 仅删除本机配置，**不会在 Discourse 侧吊销** User API Key。
- `view` 仅展示帖子流中前 **20** 条帖子，超长楼暂无翻页。
- 若站点未安装对应插件，Economy 或部分关注相关接口会返回 **404**。

### 发布到 PyPI（维护者）

1. 同步提升 `pyproject.toml` 与 `src/a_a/__init__.py` 中的 `version`。
2. 在本目录执行 `python -m build`，使用 `twine` 上传 `dist/`。

### 许可

MIT — 见 [`LICENSE`](./LICENSE)。
