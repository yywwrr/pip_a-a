from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

ALIAS_ENV_VAR = "A_A_ALIAS"


def _normalized_alias() -> str:
    raw = (os.environ.get(ALIAS_ENV_VAR) or "").strip()
    if not raw:
        return ""
    if "/" in raw or "\\" in raw or raw in {".", ".."}:
        raise ValueError(
            f"Invalid {ALIAS_ENV_VAR}={raw!r}: alias must be a single folder name."
        )
    return raw


def _config_root_dir() -> Path:
    base = Path.home() / ".a-a"
    alias = _normalized_alias()
    return base / alias if alias else base


CONFIG_DIR = _config_root_dir()
CONFIG_PATH = CONFIG_DIR / "config.json"
HISTORY_PATH = CONFIG_DIR / "history.json"
REPLIES_PATH = CONFIG_DIR / "replies.json"
LIKES_PATH = CONFIG_DIR / "likes.json"


def ensure_dir() -> None:
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)


def load_config() -> dict[str, Any] | None:
    if not CONFIG_PATH.is_file():
        return None
    return json.loads(CONFIG_PATH.read_text(encoding="utf-8"))


def save_config(data: dict[str, Any]) -> None:
    ensure_dir()
    CONFIG_PATH.write_text(
        json.dumps(data, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )


def update_config(updates: dict[str, Any]) -> dict[str, Any]:
    """合并写入本地配置（保留未出现在 updates 中的键）。"""
    cfg = load_config() or {}
    cfg.update(updates)
    save_config(cfg)
    return cfg


def append_json_list(path: Path, item: dict[str, Any]) -> None:
    ensure_dir()
    items: list[Any] = []
    if path.is_file():
        raw = path.read_text(encoding="utf-8").strip()
        items = json.loads(raw) if raw else []
    items.append(item)
    path.write_text(json.dumps(items, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def read_json_list(path: Path) -> list[Any]:
    if not path.is_file():
        return []
    raw = path.read_text(encoding="utf-8").strip()
    if not raw:
        return []
    data = json.loads(raw)
    return data if isinstance(data, list) else []
