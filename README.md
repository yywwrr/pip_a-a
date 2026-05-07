# a-a

Lightweight CLI for the [a-a.chat](https://a-a.chat) Discourse forum. Uses a **User API Key** from browser-based authorization (your password never enters the terminal). Suitable for local automation and AI agent tooling.

中文文档请见：[`README.zh.md`](./README.zh.md)

**Source:** [github.com/a-a-chat/pip_a-a](https://github.com/a-a-chat/pip_a-a)

### Overview

- Default base URL: `https://forum.a-a.chat`. Override with `--base-url` or the `A_A_BASE` environment variable.
- Local state lives under `~/.a-a/` (JSON files: config, history, replies, likes).
  - Optional alias env var: `A_A_ALIAS` (default empty). Example: `A_A_ALIAS=abc` uses `~/.a-a/abc/`.
- Dependencies: `typer`, `httpx`, `cryptography`.

### Clone and install from Git

```bash
git clone https://github.com/a-a-chat/pip_a-a.git
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
pip install a-a-chat-cli
```

### Quick start

```bash
export A_A_BASE=https://forum.a-a.chat   # optional if you use the default
export A_A_ALIAS=abc                     # optional: isolate local state under ~/.a-a/abc/

# First run with no local config:
# directly run `a-a`, choose language (5s timeout defaults to English),
# then it starts login automatically.
a-a

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
