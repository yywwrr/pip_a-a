from __future__ import annotations

import base64
import json
import os
import secrets
import socket
import time
import uuid
import webbrowser
from collections.abc import Callable
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import Any
from urllib.parse import quote, unquote, urlparse

from cryptography.hazmat.backends import default_backend
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa

# Discourse 官方 scope 名为 message_bus，不是 message（参见 UserApiKeyScope::SCOPES）。
SCOPES = "read,write,message_bus,notifications,push"

# 授权完成后 Discourse 302 到此路径，并在 query 中带上 payload=（参见 UserApiKeysController#create）。
CALLBACK_PREFIX = "/a-a/oauth/callback"
DEFAULT_CALLBACK_BIND = os.environ.get("A_A_AUTH_CALLBACK_HOST", "127.0.0.1")


def new_client_id() -> str:
    return str(uuid.uuid4())


def generate_key_material() -> tuple[bytes, str]:
    priv = rsa.generate_private_key(
        public_exponent=65537,
        key_size=2048,
        backend=default_backend(),
    )
    pub_pem = (
        priv.public_key()
        .public_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PublicFormat.SubjectPublicKeyInfo,
        )
        .decode()
    )
    priv_pem = priv.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    )
    return priv_pem, pub_pem


def build_auth_url(
    base_url: str,
    client_id: str,
    public_key_pem: str,
    *,
    nonce: str | None = None,
    auth_redirect: str | None = None,
) -> str:
    base = base_url.rstrip("/")
    pk = quote(public_key_pem, safe="")
    # Discourse requires nonce (same pattern as discourse-mcp: timestamp string).
    n = nonce if nonce is not None else str(int(time.time() * 1000))
    n_q = quote(n, safe="")
    q = (
        f"{base}/user-api-key/new?application_name=a-a&"
        f"client_id={client_id}&scopes={SCOPES}&public_key={pk}&nonce={n_q}"
    )
    if auth_redirect:
        q += "&auth_redirect=" + quote(auth_redirect, safe="")
    return q


class _RedirectPayloadHolder:
    __slots__ = ("payload", "error")

    def __init__(self) -> None:
        self.payload: str | None = None
        self.error: str | None = None


def _extract_payload_param(raw_query: str) -> str | None:
    """从原始查询串取出 ``payload``。**不能**用 ``parse_qs``：会把未编码的 ``+`` 当成空格，破坏 Base64。"""
    if not raw_query:
        return None
    for pair in raw_query.split("&"):
        if pair.startswith("payload="):
            return unquote(pair[len("payload=") :])
    return None


def _make_redirect_handler(expected_path: str, holder: _RedirectPayloadHolder) -> type[BaseHTTPRequestHandler]:
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, fmt: str, *args: Any) -> None:
            pass

        def do_GET(self) -> None:
            parsed = urlparse(self.path)
            if parsed.path.rstrip("/") != expected_path.rstrip("/"):
                self.send_error(404, "Not found")
                return
            extracted = _extract_payload_param(parsed.query)
            if not extracted:
                holder.error = "missing payload"
                self.send_error(400, "missing payload")
                return
            holder.payload = extracted
            body = (
                "<!DOCTYPE html><html><head><meta charset=\"utf-8\"><title>授权完成</title></head>"
                "<body><p>授权已完成，可关闭此页并返回终端。</p></body></html>"
            )
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write(body.encode())

    return Handler


def start_auth_redirect_listener(
    *,
    bind_host: str | None = None,
    bind_port: int = 0,
) -> tuple[str, Callable[[float], str]]:
    """启动本地 HTTP 服务并返回 ``(auth_redirect URL, wait_payload)``。

    在主线程用 ``handle_request`` + 套接字超时轮询，结束时 ``server_close``，避免后台
    ``serve_forever`` / ``shutdown`` 的竞态卡死。
    """
    host = (bind_host or DEFAULT_CALLBACK_BIND).strip() or "127.0.0.1"
    secret = secrets.token_urlsafe(16)
    expected_path = f"{CALLBACK_PREFIX}/{secret}"
    holder = _RedirectPayloadHolder()
    handler_cls = _make_redirect_handler(expected_path, holder)
    httpd = HTTPServer((host, bind_port), handler_cls)
    _, actual_port = httpd.server_address
    auth_redirect_url = f"http://{host}:{actual_port}{expected_path}"
    sock = httpd.socket
    prev_timeout = sock.gettimeout()
    sock.settimeout(0.35)

    def wait_payload(timeout_seconds: float) -> str:
        deadline = time.monotonic() + timeout_seconds
        try:
            while True:
                if holder.payload is not None:
                    return holder.payload
                if holder.error:
                    raise RuntimeError(holder.error)
                if time.monotonic() >= deadline:
                    raise TimeoutError(
                        "等待授权回调超时（请确认 Discourse 已允许该 auth_redirect，或改用 --manual）"
                    )
                try:
                    httpd.handle_request()
                except socket.timeout:
                    pass
        finally:
            try:
                sock.settimeout(prev_timeout)
            except OSError:
                pass
            try:
                httpd.server_close()
            except OSError:
                pass

    return auth_redirect_url, wait_payload


def decrypt_user_api_payload(priv_pem: bytes, b64_cipher: str) -> dict[str, Any]:
    priv = serialization.load_pem_private_key(priv_pem, password=None)
    normalized = "".join(b64_cipher.split())
    ct = base64.b64decode(normalized)
    key_size = priv.key_size // 8
    if len(ct) != key_size:
        raise ValueError(
            f"密文长度异常：{len(ct)} 字节（期望 RSA 模长 {key_size}）。"
            " 常见原因是回调 URL 里 payload 被截断，或查询串把 Base64 里的「+」当成了空格。"
        )
    try:
        plain = priv.decrypt(ct, padding.PKCS1v15())
    except Exception:
        plain = priv.decrypt(
            ct,
            padding.OAEP(
                mgf=padding.MGF1(algorithm=hashes.SHA1()),
                algorithm=hashes.SHA1(),
                label=None,
            ),
        )
    return json.loads(plain.decode())


def open_browser(url: str) -> None:
    webbrowser.open(url)
