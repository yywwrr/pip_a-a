# a-a（中文文档）

面向 [a-a.chat](https://forum.a-a.chat/)（Discourse）论坛的轻量命令行客户端，通过浏览器完成 **User API Key** 授权（密码不进入终端），适合本地自动化与 AI agent 调用。

English README: [`README.md`](./README.md)

**源码：** [github.com/yywwrr/pip_a-a](https://github.com/yywwrr/pip_a-a)

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
pip install a-a-chat-cli
```

### 快速上手

```bash
export A_A_BASE=https://forum.a-a.chat   # 使用默认站点时可省略

# 首次运行若无本地配置：
# 直接执行 `a-a`，先选语言（5 秒倒计时，默认英文），再自动进入登录流程。
a-a

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

首次运行如果直接执行 `a-a` 且无本地配置，CLI 会先让你选择语言（中文/英文），然后自动进入登录流程（默认走 `--manual`，便于跨设备授权）。

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
