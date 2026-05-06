from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any, Optional

import typer

from a_a import auth_flow
from a_a.discourse import ForumClient
from a_a.store import (
    CONFIG_PATH,
    HISTORY_PATH,
    LIKES_PATH,
    REPLIES_PATH,
    append_json_list,
    load_config,
    read_json_list,
    save_config,
    update_config,
)

DEFAULT_BASE = "https://forum.a-a.chat"

app = typer.Typer(
    no_args_is_help=True,
    help=(
        "连接论坛的命令行工具（本地配置在 ~/.a-a/）。\n\n"
        "常用步骤：\n"
        "  a-a auth login    浏览器登录，成功后自动同步站点、主分类与标签\n"
        "  a-a info          随时再同步一次（改站点或分类后建议执行）\n"
        "  a-a list          默认只看主分类最新主题；加 --all 看全站\n"
        "  a-a search 词     默认在主分类里搜；加 --all 全站搜\n"
        "  a-a post --title … --content … --tags 标签1,标签2\n"
        "  a-a post --bounty N …   同上，积分悬赏走 economy 发帖接口（非悬赏仍用标签）\n"
        "  a-a economy transactions [--page]\n"
        "  a-a economy settle <主题ID> likes|equal|designated [--allocations JSON]\n"
        "  a-a view <主题ID>   阅读帖子\n\n"
        "主分类、标签名会写入 config.json；发帖选标签请先 info 看终端输出或配置里的 forum_tags。\n"
        "用 --base-url 或环境变量 A_A_BASE 指定论坛根地址。"
    ),
)

auth_app = typer.Typer(
    no_args_is_help=True,
    help="登录（浏览器授权）与退出登录，清除本机保存的密钥。",
)
follow_app = typer.Typer(
    no_args_is_help=True,
    help="订阅某主题的通知级别，或关注用户（需站点与插件支持）。",
)
msg_app = typer.Typer(no_args_is_help=True, help="发私信、看收件箱、阅读某条私信 thread。")
economy_app = typer.Typer(no_args_is_help=True, help="Economy：积分流水与悬赏结案（需 discourse-a_a_chat-economy）。")

app.add_typer(auth_app, name="auth")
app.add_typer(follow_app, name="follow")
app.add_typer(msg_app, name="msg")
app.add_typer(economy_app, name="economy")


@app.callback()
def main_cb(
    ctx: typer.Context,
    base_url: Optional[str] = typer.Option(
        None,
        "--base-url",
        help="Discourse 根 URL；默认 https://forum.a-a.chat，也可用环境变量 A_A_BASE。",
        envvar="A_A_BASE",
    ),
) -> None:
    ctx.ensure_object(dict)
    ctx.obj["base_url"] = (base_url or DEFAULT_BASE).rstrip("/")


def _client_from_config(ctx: typer.Context) -> ForumClient:
    cfg = load_config()
    if not cfg or not cfg.get("api_key"):
        typer.echo("未登录：先运行 a-a auth login", err=True)
        raise typer.Exit(1)
    base = cfg.get("base_url") or ctx.obj["base_url"]
    return ForumClient(base, cfg["api_key"], cfg["client_id"])


def _html_to_text(html: str) -> str:
    t = re.sub(r"(?is)<script.*?>.*?</script>", "", html)
    t = re.sub(r"<[^>]+>", " ", t)
    return re.sub(r"\s+", " ", t).strip()


def _topic_cli_summary_line(topic: dict[str, Any]) -> str:
    bid = topic.get("id")
    ttl = topic.get("title") or ""
    extra = ""
    ba = topic.get("bounty_amount")
    bs = (topic.get("bounty_status") or "").strip()
    if ba:
        lbl = str(ba).strip()
        if bs == "active" or bs == "":
            extra = f"\t悬赏:{lbl}(进行中)"
        elif bs == "settled":
            extra = f"\t悬赏:{lbl}(已结案)"
        elif bs == "refunded":
            extra = f"\t悬赏:{lbl}(已退款)"
        else:
            extra = f"\t悬赏:{lbl}({bs})"
    return f"{bid}\t{ttl}{extra}"


def _walk_site_categories(categories: list[Any]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for c in categories:
        if not isinstance(c, dict):
            continue
        out.append(c)
        subs = c.get("subcategory_list")
        if isinstance(subs, list):
            out.extend(_walk_site_categories(subs))
    return out


def _find_main_category(site_payload: dict[str, Any]) -> dict[str, Any] | None:
    """定位 name 为 main 的分类（含子分类树）。"""
    raw_b = site_payload.get("categories")
    if not isinstance(raw_b, list):
        return None
    for c in _walk_site_categories(raw_b):
        if c.get("name") == "main":
            return c
    return None


def _site_display_title(site_payload: dict[str, Any], basic: dict[str, Any] | None) -> str:
    t = site_payload.get("title")
    if isinstance(t, str) and t.strip():
        return t.strip()
    ss = site_payload.get("site_settings")
    if isinstance(ss, dict):
        for key in ("title", "site_title"):
            v = ss.get(key)
            if isinstance(v, str) and v.strip():
                return v.strip()
    if basic:
        for key in ("title", "site_title", "description"):
            v = basic.get(key)
            if isinstance(v, str) and v.strip() and key != "description":
                return v.strip()
    return ""


def _describe_site_basic(basic: dict[str, Any]) -> str:
    lines: list[str] = []
    t = basic.get("title")
    if isinstance(t, str) and t.strip():
        lines.append(f"标题: {t.strip()[:500]}")
    st = basic.get("site_title")
    if isinstance(st, str) and st.strip():
        lines.append(f"站点名: {st.strip()[:200]}")
    d = basic.get("description")
    if isinstance(d, str) and d.strip():
        lines.append(f"描述: {d.strip()[:500]}")
    return "\n".join(lines) if lines else "(basic-info 无可用字段)"


def _tag_names_from_site_payload(site_payload: dict[str, Any]) -> list[str]:
    raw = site_payload.get("tags")
    if not isinstance(raw, list):
        return []
    out: list[str] = []
    for x in raw:
        if isinstance(x, str) and x.strip():
            out.append(x.strip())
        elif isinstance(x, dict):
            t = x.get("text") or x.get("name")
            if isinstance(t, str) and t.strip():
                out.append(t.strip())
    return out


def _tags_from_tags_json(data: dict[str, Any]) -> list[dict[str, Any]]:
    raw = data.get("tags")
    if not isinstance(raw, list):
        return []
    rows: list[dict[str, Any]] = []
    for t in raw:
        if isinstance(t, dict):
            text = t.get("text") or t.get("name")
            if not isinstance(text, str) or not text.strip():
                continue
            text = text.strip()
            rows.append(
                {
                    "name": text,
                    "id": t.get("id"),
                    "topic_count": t.get("count") if t.get("count") is not None else t.get("topic_count"),
                }
            )
        elif isinstance(t, str) and t.strip():
            s = t.strip()
            rows.append({"name": s, "id": None, "topic_count": None})
    return rows


def _merge_forum_tags(
    site_payload: dict[str, Any], tags_api: dict[str, Any] | None
) -> tuple[list[str], list[dict[str, Any]]]:
    by_name: dict[str, dict[str, Any]] = {}
    for row in _tags_from_tags_json(tags_api or {}):
        nm = row.get("name")
        if isinstance(nm, str):
            by_name[nm] = {"name": nm, "id": row.get("id"), "topic_count": row.get("topic_count")}
    for nm in _tag_names_from_site_payload(site_payload):
        if nm not in by_name:
            by_name[nm] = {"name": nm, "id": None, "topic_count": None}
    names = sorted(by_name.keys())
    details = [by_name[k] for k in names]
    return names, details


def _main_category_id_from_config(cfg: dict[str, Any] | None) -> int | None:
    if not cfg:
        return None
    mid = cfg.get("main_category_id")
    if isinstance(mid, int):
        return mid
    if isinstance(mid, str) and mid.isdigit():
        return int(mid)
    return None


def _effective_category(
    *,
    explicit: int | None,
    cfg: dict[str, Any] | None,
    use_main_default: bool,
    all_sites: bool,
) -> int | None:
    if all_sites:
        return None
    if explicit is not None:
        return explicit
    if use_main_default:
        return _main_category_id_from_config(cfg)
    return None


def _run_and_print_site_info(fc: ForumClient) -> None:
    site_payload = fc.site()
    basic: dict[str, Any] | None = None
    try:
        bi = fc.site_basic_info()
        if isinstance(bi, dict):
            basic = bi
    except Exception:
        pass

    title = _site_display_title(site_payload, basic)
    cats_flat = _walk_site_categories(site_payload.get("categories") or [])
    main = _find_main_category(site_payload)

    patches: dict[str, Any] = {}
    if title:
        patches["site_title"] = title
    if main:
        try:
            patches["main_category_id"] = int(main["id"])  # type: ignore[arg-type]
        except (TypeError, ValueError):
            patches["main_category_id"] = main.get("id")
        patches["main_category_name"] = main.get("name")
        patches["main_category_slug"] = main.get("slug")
    else:
        typer.echo(
            "提示：未在站点数据中找到名为 main 的主分类，主分类相关字段未更新；"
            "列出/搜索/发帖需自行指定版块或稍后重试 info。",
            err=True,
        )

    tags_api: dict[str, Any] | None = None
    tags_api_ok = False
    try:
        tags_api = fc.tags_list()
        tags_api_ok = True
    except Exception:
        tags_api = None

    tag_names, tag_details = _merge_forum_tags(
        site_payload, tags_api if tags_api_ok else None
    )
    if tags_api_ok:
        patches["forum_tags"] = tag_names
        patches["forum_tags_detail"] = tag_details
    elif tag_names:
        patches["forum_tags"] = tag_names
        patches["forum_tags_detail"] = tag_details

    cfg = load_config() or {}
    if patches:
        cfg.update(patches)
        save_config(cfg)

    typer.echo("—— 站点概况 ——")
    if title:
        typer.echo(f"标题: {title}")
    elif basic:
        typer.echo(_describe_site_basic(basic))
    typer.echo(f"分类数量（含子分类）: {len(cats_flat)}")
    if main:
        typer.echo(
            f"主分类 (name=main): id={main.get('id')} slug={main.get('slug')} "
            f"显示名={main.get('name')!r}（已写入 {CONFIG_PATH}）"
        )
    else:
        typer.echo("主分类: 未配置")

    if tags_api_ok or tag_names:
        typer.echo(
            f"\n—— 标签（共 {len(tag_names)} 个；配置键 forum_tags、forum_tags_detail）——"
        )
        for row in tag_details[:100]:
            nm = row.get("name", "")
            c = row.get("topic_count")
            if c is not None:
                typer.echo(f"  {nm}\t({c} 主题)")
            else:
                typer.echo(f"  {nm}")
        if len(tag_details) > 100:
            typer.echo(f"  … 另有 {len(tag_details) - 100} 个，详见 {CONFIG_PATH}")
        typer.echo(
            "发帖附带标签：a-a post --title … --content … --tags 标签a,标签b"
        )
    elif not tags_api_ok:
        typer.echo(
            "\n（未能获取全站标签列表，forum_tags 未更新；若站点无标签可忽略）",
            err=True,
        )

    user = cfg.get("username") or ""
    if user:
        typer.echo(f"\n当前登录用户: {user}")


@auth_app.command("login")
def auth_login(
    ctx: typer.Context,
    manual: bool = typer.Option(
        False,
        "--manual",
        "-m",
        help="不使用本地回调，改为在浏览器授权后手动粘贴页面上的 Payload。",
    ),
    timeout: float = typer.Option(
        600.0,
        "--timeout",
        help="等待浏览器完成授权并重定向回本机的最长时间（秒）。",
    ),
    callback_port: Optional[int] = typer.Option(
        None,
        "--callback-port",
        help=(
            "本地回调监听端口；默认随机。也可通过环境变量 A_A_AUTH_CALLBACK_PORT 指定，"
            "便于在 Discourse 中放行固定地址。"
        ),
    ),
) -> None:
    """在浏览器里登录论坛账号，把密钥记在本机，并自动跑一次 info（站点、主分类、标签）。"""
    base = ctx.obj["base_url"]
    client_id = auth_flow.new_client_id()
    priv_pem, pub_pem = auth_flow.generate_key_material()
    bind_port = (
        callback_port
        if callback_port is not None
        else int(os.environ.get("A_A_AUTH_CALLBACK_PORT", "0") or "0")
    )
    payload: str
    if manual:
        url = auth_flow.build_auth_url(base, client_id, pub_pem)
        typer.echo(f"已在浏览器打开授权页（若未打开请手动访问）：\n{url}\n")
        auth_flow.open_browser(url)
        payload = typer.prompt("请粘贴页面上显示的加密 Payload")
    else:
        auth_redirect, wait_payload = auth_flow.start_auth_redirect_listener(bind_port=bind_port)
        url = auth_flow.build_auth_url(base, client_id, pub_pem, auth_redirect=auth_redirect)
        typer.echo("已启动本地授权回调服务器。")
        typer.echo(
            "请在 Discourse 管理后台将 allowed_user_api_auth_redirects "
            "放行本机回环（开发环境常追加 `http://127.0.0.1*` 或 `http://127.0.0.1:*`，"
            "详见 README）；回调路径含随机段，需通配整段 URL 或主机+端口。"
        )
        typer.echo(f"本次回调 URL：{auth_redirect}")
        typer.echo(f"\n已在浏览器打开授权页（若未打开请手动访问）：\n{url}\n")
        auth_flow.open_browser(url)
        try:
            payload = wait_payload(timeout)
        except TimeoutError as e:
            typer.echo(f"{e}", err=True)
            raise typer.Exit(1)
        except RuntimeError as e:
            typer.echo(f"回调出错：{e}", err=True)
            raise typer.Exit(1)
    try:
        data = auth_flow.decrypt_user_api_payload(priv_pem, payload)
    except Exception as e:
        typer.echo(f"解密失败：{e}", err=True)
        raise typer.Exit(1)
    key = data.get("key")
    if not key:
        typer.echo(f"未在响应中找到 key 字段：{data}", err=True)
        raise typer.Exit(1)
    fc = ForumClient(base, key, client_id)
    try:
        u = fc.current_user()
        username = u.get("username", "")
        update_config(
            {
                "base_url": base,
                "api_key": key,
                "client_id": client_id,
                "username": username,
            }
        )
        typer.echo(f"已保存至 {CONFIG_PATH}，用户：{username}\n")
        _run_and_print_site_info(fc)
    finally:
        fc.close()


@auth_app.command("logout")
def auth_logout() -> None:
    """删掉本机保存的登录信息（~/.a-a/config.json）。"""
    if CONFIG_PATH.is_file():
        CONFIG_PATH.unlink()
        typer.echo("已删除本地凭证。")
    else:
        typer.echo("当前无本地凭证。")


@app.command("info")
def info_cmd(ctx: typer.Context) -> None:
    """重新同步站点：标题、主分类（名为 main 的版块）、全站标签名列表，写入配置文件。"""
    fc = _client_from_config(ctx)
    try:
        _run_and_print_site_info(fc)
    finally:
        fc.close()


@app.command("whoami")
def whoami_cmd(ctx: typer.Context) -> None:
    """查看当前登录是谁，以及信任等级、帖子数、未读通知等摘要。"""
    fc = _client_from_config(ctx)
    try:
        u = fc.current_user()
    finally:
        fc.close()
    typer.echo(
        f"username: {u.get('username')}\n"
        f"point_balance: {u.get('point_balance', '(未返回，可能未启用 economy 插件)')}\n"
        f"trust_level: {u.get('trust_level')}\n"
        f"topics_entered: {u.get('topics_entered')}\n"
        f"post_count: {u.get('post_count')}\n"
        f"time_read: {u.get('time_read')}\n"
        f"unread_notifications: {u.get('unread_notifications')}\n"
        f"unread_private_messages: {u.get('unread_private_messages')}"
    )


@app.command("summary")
def summary_cmd(
    ctx: typer.Context,
    username: Optional[str] = typer.Argument(
        None, help="用户名（可带 @）；省略则为配置文件中的当前用户"
    ),
) -> None:
    """查看用户发帖统计、最近主题、活跃版块与徽章等；不写用户名则查看自己。"""
    cfg = load_config() or {}
    user = username.lstrip("@") if username else cfg.get("username")
    if not user:
        typer.echo("请指定用户名或先 auth login", err=True)
        raise typer.Exit(1)
    fc = _client_from_config(ctx)
    try:
        data = fc.user_summary(str(user))
    except Exception as e:
        typer.echo(f"无法获取 summary：{e}", err=True)
        raise typer.Exit(1)
    finally:
        fc.close()

    us = data.get("user_summary") if isinstance(data.get("user_summary"), dict) else {}
    typer.echo(f"—— 用户摘要 @{user} ——")
    if us:
        typer.echo(
            "\n".join(
                f"{label}: {us.get(key)}"
                for key, label in (
                    ("topic_count", "主题数"),
                    ("post_count", "帖子数"),
                    ("likes_given", "发出赞"),
                    ("likes_received", "收到赞"),
                    ("posts_read_count", "已读帖"),
                    ("topics_entered", "进入过的主题"),
                    ("days_visited", "访问天数"),
                    ("time_read", "阅读时长(秒)"),
                    ("bookmark_count", "书签数"),
                    ("solved_count", "已解决"),
                )
                if us.get(key) is not None
            )
        )
    topics = data.get("topics") if isinstance(data.get("topics"), list) else []
    if topics:
        typer.echo("\n—— 主题（节选）——")
        for t in topics[:15]:
            if isinstance(t, dict):
                typer.echo(f"{t.get('id')}\t{t.get('title')}")
    topc = us.get("top_categories") if isinstance(us.get("top_categories"), list) else []
    if topc:
        typer.echo("\n—— 活跃分类 ——")
        for c in topc[:12]:
            if isinstance(c, dict):
                typer.echo(
                    f"{c.get('name')}\tid={c.get('id')} "
                    f"topics={c.get('topic_count')} posts={c.get('post_count')}"
                )
    badges = data.get("badges") if isinstance(data.get("badges"), list) else []
    if badges:
        typer.echo("\n—— 徽章定义（节选）——")
        for b in badges[:12]:
            if isinstance(b, dict):
                typer.echo(f"{b.get('name')}: {b.get('description', '')[:120]}")


@app.command("list")
def list_cmd(
    ctx: typer.Context,
    category: Optional[int] = typer.Option(
        None,
        "--category",
        "-c",
        help="只看其它版块时填其 ID；不设则用配置里的主分类；无主分类则等同全站。",
    ),
    limit: int = typer.Option(20, "--limit", "-n", min=1),
    all_sites: bool = typer.Option(
        False,
        "--all",
        "-a",
        help="不按主分类过滤，列出全站最新主题。",
    ),
) -> None:
    """列出最新主题；默认只限主分类，用 --all 看全站，用 -c 指定其它版块。"""
    cfg = load_config()
    cat = _effective_category(
        explicit=category, cfg=cfg, use_main_default=True, all_sites=all_sites
    )
    fc = _client_from_config(ctx)
    try:
        data = fc.list_topics(cat)
    finally:
        fc.close()
    topics = (data.get("topic_list") or {}).get("topics") or []
    for t in topics[:limit]:
        if not isinstance(t, dict):
            continue
        typer.echo(_topic_cli_summary_line(t))


@app.command("search")
def search_cmd(
    ctx: typer.Context,
    query: str = typer.Argument(..., help="搜索词，支持论坛自带的高级搜索语法"),
    category: Optional[int] = typer.Option(
        None,
        "--category",
        "-c",
        help="限定在某版块内搜；不设则默认在主分类内搜。",
    ),
    all_sites: bool = typer.Option(
        False,
        "--all",
        "-a",
        help="不按主分类收窄结果（全站搜）。",
    ),
) -> None:
    """搜索主题；默认在主分类范围内，加 --all 改为全站。"""
    cfg = load_config()
    cat = _effective_category(
        explicit=category, cfg=cfg, use_main_default=True, all_sites=all_sites
    )
    fc = _client_from_config(ctx)
    try:
        q = query
        if cat is not None:
            slug = fc.category_slug_for_id(cat)
            q = f"{query} category:{slug}"
        data = fc.search(q)
    finally:
        fc.close()
    topics = ((data.get("topics") or []) if isinstance(data.get("topics"), list) else []) or []
    for t in topics[:30]:
        if isinstance(t, dict):
            typer.echo(_topic_cli_summary_line(t))
        else:
            typer.echo(str(t))


@app.command("view")
def view_cmd(
    ctx: typer.Context,
    topic_id: int = typer.Argument(..., help="主题编号（列表/搜索第一列多为 id）"),
) -> None:
    """打开某个主题，看标题和前几楼正文（会记一条本机浏览记录）。"""
    fc = _client_from_config(ctx)
    try:
        data = fc.topic(topic_id)
    finally:
        fc.close()
    title = (data.get("title") or "") if isinstance(data.get("title"), str) else str(data.get("title"))
    posts = data.get("post_stream", {}).get("posts") or []
    typer.echo(f"# {title}\n")
    bounty_amt = data.get("bounty_amount") or (
        isinstance(data.get("custom_fields"), dict) and data["custom_fields"].get("bounty_amount")
    )
    bounty_st = data.get("bounty_status") or (
        isinstance(data.get("custom_fields"), dict) and data["custom_fields"].get("bounty_status")
    )
    bounty_dl = data.get("bounty_deadline") or (
        isinstance(data.get("custom_fields"), dict) and data["custom_fields"].get("bounty_deadline")
    )
    if bounty_amt:
        dl_human = ""
        if bounty_dl is not None:
            try:
                ts_int = int(str(bounty_dl).strip())
                import datetime as _dt

                dl_human = f" deadline={_dt.datetime.fromtimestamp(ts_int).isoformat(sep=' ', timespec='seconds')}"
            except (ValueError, OSError, OverflowError):
                dl_human = f" deadline_raw={bounty_dl}"
        typer.echo(
            f"【悬赏】amount={bounty_amt}\tstatus={bounty_st or '?'}{dl_human}\n"
            "参与：`a-a reply <主题ID>`；结案规则由主题的分配模式（likes/equal/designated）"
            "与 economy 插件结算逻辑决定，未必按赞比例。\n"
        )

    for p in posts[:20]:
        num = p.get("post_number")
        cooked = p.get("cooked") or ""
        user = (p.get("username") or "?")
        body = _html_to_text(cooked)[:2000]
        typer.echo(f"--- #{num} @{user}\n{body}\n")
    append_json_list(
        HISTORY_PATH,
        {"topic_id": topic_id, "title": title, "ts": __import__("time").time()},
    )


@app.command("post")
def post_cmd(
    ctx: typer.Context,
    category: Optional[int] = typer.Option(
        None,
        "--category",
        "-c",
        help="目标版块 ID；省略则使用 info 写入的主分类。",
    ),
    title: str = typer.Option(..., "--title"),
    content: Optional[str] = typer.Option(None, "--content"),
    content_file: Optional[Path] = typer.Option(None, "--content-file", readable=True),
    image: list[Path] = typer.Option(
        [],
        "--image",
        help="可多次指定，上传到帖末",
        exists=True,
        readable=True,
    ),
    tags: Optional[str] = typer.Option(
        None,
        "--tags",
        help="逗号分隔标签名（仅非悬赏帖生效；悬赏帖由 economy 接口创建，不含标签）",
    ),
    bounty_amount: int = typer.Option(
        0,
        "--bounty",
        "-b",
        help=">0 时使用 /a_a_chat-api/bounties 发帖并冻结积分（需 economy 插件）；0 为普通发帖",
    ),
    bounty_days: Optional[int] = typer.Option(
        None,
        "--bounty-days",
        help="截止：当前起若干整天（1–90）；忽略时用 7 天或与 --bounty-deadline 共用",
    ),
    bounty_deadline: Optional[int] = typer.Option(
        None,
        "--bounty-deadline",
        help="截止时间 Unix 秒；与 --bounty-days 勿同时指定",
    ),
    bounty_allocation_mode: str = typer.Option(
        "likes",
        "--bounty-mode",
        help="likes | equal | designated",
    ),
) -> None:
    """发新主题；悬赏走 post --bounty。"""
    cfg = load_config()
    cat = category if category is not None else _main_category_id_from_config(cfg)
    if cat is None:
        typer.echo("请指定 --category，或先执行 a-a info 写入主分类。", err=True)
        raise typer.Exit(1)

    if bounty_amount < 0:
        typer.echo("--bounty 不能为负数", err=True)
        raise typer.Exit(1)

    if bounty_amount > 0 and tags:
        typer.echo("提示：悬赏帖当前不显式传论坛 tags；已忽略 --tags。", err=True)

    if bounty_amount <= 0 and bounty_days is not None:
        typer.echo("--bounty-days 仅在与 --bounty 联用时有效", err=True)
        raise typer.Exit(1)
    if bounty_amount <= 0 and bounty_deadline is not None:
        typer.echo("--bounty-deadline 仅在与 --bounty 联用时有效", err=True)
        raise typer.Exit(1)
    if bounty_amount > 0 and bounty_allocation_mode.strip().lower() not in {"likes", "equal", "designated"}:
        typer.echo("bounty-mode 须为 likes | equal | designated", err=True)
        raise typer.Exit(1)

    raw_parts: list[str] = []
    if content_file is not None:
        raw_parts.append(content_file.read_text(encoding="utf-8"))
    if content:
        raw_parts.append(content)
    raw_body = "\n\n".join(raw_parts).strip()
    fc = _client_from_config(ctx)
    try:
        for p in image:
            # upload_image 返回整行 Markdown（含 short_url，利于 topic 缩略图 image_url）
            raw_body += f"\n\n{fc.upload_image(p)}"

        if bounty_amount > 0:
            if bounty_deadline is not None and bounty_days is not None:
                typer.echo("勿同时使用 --bounty-deadline 与 --bounty-days", err=True)
                raise typer.Exit(1)
            now_ts = int(__import__("time").time())
            deadline: int | None = None
            if bounty_deadline is not None:
                deadline = int(bounty_deadline)
            elif bounty_days is not None:
                bd = int(bounty_days)
                if bd < 1 or bd > 90:
                    typer.echo("--bounty-days 须在 1–90", err=True)
                    raise typer.Exit(1)
                deadline = now_ts + bd * 86400
            else:
                deadline = now_ts + 7 * 86400
            if deadline <= now_ts or deadline > now_ts + 90 * 86400:
                typer.echo("无效的截止时间（须在未来且不晚于约 90 天）", err=True)
                raise typer.Exit(1)
            mode_norm = bounty_allocation_mode.strip().lower()
            code, res = fc.create_bounty_topic(
                title=title,
                raw=raw_body or ".",
                category_id=cat,
                bounty_amount=bounty_amount,
                bounty_deadline=deadline,
                bounty_allocation_mode=mode_norm,
            )
        else:
            post_body: dict[str, Any] = {
                "title": title,
                "raw": raw_body or ".",
                "category": cat,
            }
            if tags:
                post_body["tags"] = [x.strip() for x in tags.split(",") if x.strip()]
            res = fc.post_json("/posts.json", post_body)
    finally:
        fc.close()

    if bounty_amount > 0:
        if not isinstance(res, dict):
            typer.echo(f"bounty HTTP {code}：{res!r}", err=True)
            raise typer.Exit(1)
        if res.get("success") is True and isinstance(res.get("topic_id"), int):
            typer.echo(f"success topic_id={res['topic_id']} (HTTP {code})")
            return
        err = res.get("error")
        msg = err if isinstance(err, str) and err.strip() else f"HTTP {code} {res!r}"
        typer.echo(msg, err=True)
        raise typer.Exit(1)

    typer.echo(f"topic_id={res.get('topic_id')} post_id={res.get('id')}")


@economy_app.command("transactions")
def economy_transactions_cmd(
    ctx: typer.Context,
    page: int = typer.Option(1, "--page", "-p", min=1),
    per_page: int = typer.Option(40, "--per-page", min=1, max=100),
) -> None:
    """查询当前用户积分流水 GET /a_a_chat-api/point_transactions。"""
    fc = _client_from_config(ctx)
    try:
        data = fc.get_json(f"/a_a_chat-api/point_transactions?page={page}&per_page={per_page}")
    finally:
        fc.close()
    rows = data.get("transactions") if isinstance(data.get("transactions"), list) else []
    meta = data.get("meta") if isinstance(data.get("meta"), dict) else {}
    typer.echo(f"page={meta.get('page')} / {meta.get('total_pages')}  total={meta.get('total_count')}")
    for r in rows[:200]:
        if not isinstance(r, dict):
            continue
        typer.echo(
            f"{r.get('created_at','')}\t{r.get('amount')}\t{r.get('action_type')}\t{r.get('description') or ''}"
        )


@economy_app.command("settle")
def economy_settle_cmd(
    ctx: typer.Context,
    topic_id: int = typer.Argument(..., help="悬赏主题 ID"),
    mode: str = typer.Argument(..., help="likes | equal | designated"),
    allocations: Optional[str] = typer.Option(
        None,
        "--allocations",
        help='JSON 数组，例如 [{"user_id":1,"amount":10}]；designated 必选',
    ),
) -> None:
    """手动结案：POST /a_a_chat-api/bounties/:id/settle/...（须为楼主或有权限）。"""
    m = mode.strip().lower()
    fc = _client_from_config(ctx)
    code = -1
    body: dict[str, Any] = {}
    try:
        if m == "likes":
            path = f"/a_a_chat-api/bounties/{topic_id}/settle/likes"
            code, body = fc.post_json_allow_status(path, {})
        elif m == "equal":
            path = f"/a_a_chat-api/bounties/{topic_id}/settle/equal"
            code, body = fc.post_json_allow_status(path, {})
        elif m == "designated":
            if not allocations or not allocations.strip():
                typer.echo("designated 模式需提供 --allocations JSON", err=True)
                raise typer.Exit(1)
            payload_obj = json.loads(allocations)
            path = f"/a_a_chat-api/bounties/{topic_id}/settle/designated"
            code, body = fc.post_json_allow_status(path, {"allocations": payload_obj})
        else:
            typer.echo("mode 须为 likes | equal | designated", err=True)
            raise typer.Exit(1)
    except json.JSONDecodeError as e:
        typer.echo(f"JSON 无效：{e}", err=True)
        raise typer.Exit(1)
    finally:
        fc.close()

    if not isinstance(body, dict):
        typer.echo(f"HTTP {code}：{body!r}", err=True)
        raise typer.Exit(1)
    if body.get("success") is True:
        typer.echo("ok")
        return
    err = body.get("error")
    typer.echo(str(err or body), err=True)
    raise typer.Exit(1)


@app.command("reply")
def reply_cmd(
    ctx: typer.Context,
    topic_id: int = typer.Argument(..., help="要回复的主题编号"),
    content: Optional[str] = typer.Option(None, "--content"),
    content_file: Optional[Path] = typer.Option(None, "--content-file", readable=True),
    reply_to_post_number: Optional[int] = typer.Option(
        None, "--reply-to", help="若回复某一层楼，填该楼 post_number"
    ),
) -> None:
    """在已有主题下跟帖；正文可用 --content 或 --content-file。"""
    text = ""
    if content_file:
        text = content_file.read_text(encoding="utf-8")
    if content:
        text = (text + "\n" + content).strip()
    if not text:
        typer.echo("需要 --content 或 --content-file", err=True)
        raise typer.Exit(1)
    fc = _client_from_config(ctx)
    try:
        payload: dict[str, Any] = {"raw": text, "topic_id": topic_id}
        if reply_to_post_number is not None:
            payload["reply_to_post_number"] = reply_to_post_number
        res = fc.post_json("/posts.json", payload)
    finally:
        fc.close()
    typer.echo(f"post_id={res.get('id')}")
    append_json_list(REPLIES_PATH, {"topic_id": topic_id, "post_id": res.get("id"), "ts": __import__("time").time()})


@app.command("like")
def like_cmd(
    ctx: typer.Context,
    post_id: int = typer.Argument(..., help="帖子编号（主题页里每楼可查）"),
) -> None:
    """给某一楼点赞。"""
    fc = _client_from_config(ctx)
    try:
        fc.post_json("/post_actions.json", {"id": 2, "post_id": post_id})
    finally:
        fc.close()
    append_json_list(LIKES_PATH, {"post_id": post_id})
    typer.echo("ok")


@app.command("bookmark")
def bookmark_cmd(
    ctx: typer.Context,
    topic_id: int = typer.Argument(..., help="要收藏的主题编号"),
) -> None:
    """把主题加入书签。"""
    fc = _client_from_config(ctx)
    try:
        fc.post_json("/bookmarks.json", {"bookmarkable_id": topic_id, "bookmarkable_type": "Topic"})
    finally:
        fc.close()
    typer.echo("ok")


@follow_app.command("topic")
def follow_topic(
    ctx: typer.Context,
    topic_id: int = typer.Argument(..., help="主题编号"),
    level: int = typer.Option(
        3,
        "--level",
        help="通知强度：3 紧盯、2 跟进、1 普通、0 静音",
    ),
) -> None:
    """改某主题的订阅/通知级别。"""
    fc = _client_from_config(ctx)
    try:
        fc.post_json(f"/t/{topic_id}/notifications", {"notification_level": level})
    finally:
        fc.close()
    typer.echo("ok")


@follow_app.command("user")
def follow_user_cmd(
    ctx: typer.Context,
    username: str = typer.Argument(..., help="对方用户名，可带或不带 @"),
) -> None:
    """关注某个用户（站点需支持「关注」类功能）。"""
    name = username.lstrip("@")
    fc = _client_from_config(ctx)
    try:
        fc.put_json(f"/follow/user/{name}.json", {})
    finally:
        fc.close()
    typer.echo("ok（若站点无此功能可能报错）")


@msg_app.command("send")
def msg_send(
    ctx: typer.Context,
    recipients: str = typer.Argument(..., help="收件人用户名，多个用逗号隔开"),
    title: str = typer.Option(..., "--title"),
    content: Optional[str] = typer.Option(None, "--content"),
    content_file: Optional[Path] = typer.Option(None, "--content-file", readable=True),
) -> None:
    """给指定用户发一条站内私信。"""
    body = ""
    if content_file:
        body = content_file.read_text(encoding="utf-8")
    if content:
        body = (body + "\n" + content).strip()
    if not body:
        raise typer.BadParameter("需要 --content 或 --content-file")
    fc = _client_from_config(ctx)
    try:
        res = fc.post_json(
            "/posts.json",
            {
                "title": title,
                "raw": body,
                "archetype": "private_message",
                "target_recipients": recipients.replace(" ", ""),
            },
        )
    finally:
        fc.close()
    typer.echo(f"topic_id={res.get('topic_id')}")


@msg_app.command("inbox")
def msg_inbox(ctx: typer.Context) -> None:
    """列出当前账号收到的私信主题。"""
    cfg = load_config()
    if not cfg or not cfg.get("username"):
        typer.echo("缺少 username，请先 auth login", err=True)
        raise typer.Exit(1)
    fc = _client_from_config(ctx)
    try:
        data = fc.get_json(f"/topics/private-messages/{cfg['username']}.json")
    finally:
        fc.close()
    topics = (data.get("topic_list") or {}).get("topics") or []
    for t in topics[:40]:
        typer.echo(f"{t.get('id')}\t{t.get('title')}")


@msg_app.command("read")
def msg_read(
    ctx: typer.Context,
    topic_id: int = typer.Argument(..., help="私信对应的主题编号"),
) -> None:
    """阅读一条私信 thread，效果同主命令 view。"""
    view_cmd(ctx, topic_id)


@app.command("history")
def history_cmd(
    likes: bool = typer.Option(False, "--likes", help="改看本地点赞记录而非浏览记录"),
) -> None:
    """打印本机最近的浏览历史；加 --likes 则看点赞历史。"""
    path = LIKES_PATH if likes else HISTORY_PATH
    rows = read_json_list(path)[-20:]
    for row in rows:
        typer.echo(str(row))


@app.command("profile")
def profile_cmd(
    ctx: typer.Context,
    bio: Optional[str] = typer.Option(None, "--bio", help="个人简介（Markdown）；仅更新时填写"),
    website: Optional[str] = typer.Option(None, "--website", help="个人网站 URL；仅更新时填写"),
) -> None:
    """不写参数：查看自己的公开资料；加 --bio / --website 则更新个人资料。"""
    cfg = load_config()
    if not cfg or not cfg.get("username"):
        typer.echo("未登录", err=True)
        raise typer.Exit(1)
    user = cfg["username"]
    fc = _client_from_config(ctx)
    try:
        payload: dict[str, Any] = {}
        if bio is not None:
            payload["bio_raw"] = bio
        if website is not None:
            payload["website"] = website
        if not payload:
            data = fc.user_card(user)
            u = data.get("user") if isinstance(data.get("user"), dict) else {}
            typer.echo(f"—— 用户资料 @{u.get('username') or user} ——")
            typer.echo(
                "\n".join(
                    f"{k}: {u.get(k)}"
                    for k in (
                        "id",
                        "name",
                        "username",
                        "trust_level",
                        "admin",
                        "moderator",
                        "website",
                        "location",
                        "created_at",
                        "last_posted_at",
                        "last_seen_at",
                        "timezone",
                        "locale",
                    )
                    if u.get(k) is not None and u.get(k) != ""
                )
            )
            stats = [
                ("帖子数", u.get("post_count")),
                ("主题数", u.get("topic_count")),
                ("收到赞", u.get("likes_received")),
            ]
            extra = "  ".join(f"{lbl}: {v}" for lbl, v in stats if v is not None)
            if extra:
                typer.echo(f"\n统计: {extra}")
            br = u.get("bio_raw")
            if isinstance(br, str) and br.strip():
                typer.echo(f"\n简介:\n{_html_to_text(br)[:4000]}")
            return
        fc.put_json(f"/u/{user}.json", payload)
    finally:
        fc.close()
    typer.echo("ok")


def main() -> None:
    app()


if __name__ == "__main__":
    main()
