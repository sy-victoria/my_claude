"""远程 MCP 的 OAuth 授权码客户端；令牌只存在当前进程内存中。"""

from __future__ import annotations

import base64
import hashlib
import json
import secrets
import sys
import time
import urllib.parse
import urllib.request
import webbrowser
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import Any


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, request: urllib.request.Request, fp: Any, code: int,
                         msg: str, headers: Any, newurl: str) -> None:
        raise PermissionError("OAuth 端点不允许 HTTP 重定向")


def open_no_redirect(request: urllib.request.Request, timeout: float = 15) -> Any:
    """认证信息只发送到显式配置的端点。"""
    return urllib.request.build_opener(_NoRedirect()).open(request, timeout=timeout)


def _safe_url(url: str, *, local_ok: bool = False) -> str:
    parsed = urllib.parse.urlparse(url)
    if parsed.username or parsed.password or parsed.fragment:
        raise ValueError("OAuth URL 不得包含凭据或片段")
    if parsed.scheme == "https" and parsed.hostname:
        return url
    if local_ok and parsed.scheme == "http" and parsed.hostname in {"localhost", "127.0.0.1"}:
        return url
    raise ValueError("OAuth 端点必须使用 HTTPS")


def _json_request(url: str, data: dict[str, Any] | None = None) -> dict[str, Any]:
    """限制元数据和令牌响应大小，避免未受信任的远程服务耗尽内存。"""
    payload = None if data is None else json.dumps(data).encode()
    request = urllib.request.Request(url, payload,
                                     headers={"Accept": "application/json", "Content-Type": "application/json"})
    with open_no_redirect(request) as response:
        body = response.read(1_000_001)
    if len(body) > 1_000_000:
        raise ValueError("OAuth 响应超过 1 MB")
    result = json.loads(body)
    if not isinstance(result, dict):
        raise ValueError("OAuth 响应必须是 JSON 对象")
    return result


def _form_request(url: str, fields: dict[str, str]) -> dict[str, Any]:
    body = urllib.parse.urlencode(fields).encode()
    request = urllib.request.Request(url, body, headers={
        "Content-Type": "application/x-www-form-urlencoded", "Accept": "application/json"})
    with open_no_redirect(request) as response:
        content = response.read(1_000_001)
    if len(content) > 1_000_000:
        raise ValueError("OAuth 响应超过 1 MB")
    result = json.loads(content)
    if not isinstance(result, dict):
        raise ValueError("OAuth 响应必须是 JSON 对象")
    return result


class OAuthClient:
    """在 401 后发现服务端并完成 PKCE；同一进程内可刷新令牌。"""

    def __init__(self, resource: str, client_id: str | None = None,
                 scope: str | None = None, interactive: bool = True) -> None:
        if client_id is not None and (not isinstance(client_id, str) or not client_id):
            raise ValueError("oauth.client_id 必须是非空字符串")
        if scope is not None and not isinstance(scope, str):
            raise ValueError("oauth.scope 必须是字符串")
        self.resource = _safe_url(resource, local_ok=True)
        self.client_id = client_id
        self.scope = scope
        self.interactive = interactive
        self.access_token: str | None = None
        self.refresh_token: str | None = None
        self.expires_at = 0.0
        self.token_endpoint: str | None = None

    def _discover(self, challenge: str) -> dict[str, Any]:
        """只接受当前 MCP 服务器同源的元数据地址，防止恶意挑战引导访问别处。"""
        import re

        match = re.search(r'(?:^|[,\s])resource_metadata="([^"]+)"', challenge)
        if not match:
            raise PermissionError("MCP 服务器未提供 OAuth resource_metadata")
        metadata_url = _safe_url(match.group(1), local_ok=True)
        source = urllib.parse.urlparse(self.resource)
        target = urllib.parse.urlparse(metadata_url)
        if (source.scheme, source.hostname, source.port) != (target.scheme, target.hostname, target.port):
            raise PermissionError("MCP OAuth 元数据地址必须与服务器同源")
        resource_metadata = _json_request(metadata_url)
        if resource_metadata.get("resource") != self.resource:
            raise PermissionError("MCP OAuth 元数据的 resource 与服务器地址不一致")
        issuers = resource_metadata.get("authorization_servers")
        if not isinstance(issuers, list) or not issuers or not isinstance(issuers[0], str):
            raise ValueError("MCP OAuth 元数据缺少 authorization_servers")
        issuer = _safe_url(issuers[0], local_ok=True).rstrip("/")
        parsed = urllib.parse.urlparse(issuer)
        metadata_url = f"{parsed.scheme}://{parsed.netloc}/.well-known/oauth-authorization-server{parsed.path}"
        metadata = _json_request(metadata_url)
        if metadata.get("issuer", "").rstrip("/") != issuer:
            raise PermissionError("OAuth 授权服务器 issuer 不匹配")
        for key in ("authorization_endpoint", "token_endpoint"):
            endpoint = metadata.get(key)
            if not isinstance(endpoint, str):
                raise ValueError(f"OAuth 元数据缺少 {key}")
            _safe_url(endpoint, local_ok=True)
        self.token_endpoint = metadata["token_endpoint"]
        return metadata

    def _store_token(self, token: dict[str, Any]) -> None:
        access = token.get("access_token")
        if not isinstance(access, str) or not access:
            raise ValueError("OAuth 响应缺少 access_token")
        if token.get("token_type", "Bearer").lower() != "bearer":
            raise ValueError("OAuth 响应不是 Bearer token")
        self.access_token = access
        refresh = token.get("refresh_token")
        if isinstance(refresh, str) and refresh:
            self.refresh_token = refresh
        expires = token.get("expires_in", 3600)
        self.expires_at = time.monotonic() + max(0, float(expires) - 30)

    def refresh(self) -> bool:
        """刷新失败时返回 False，调用方再决定是否需要浏览器登录。"""
        if not self.refresh_token or not self.client_id or not self.token_endpoint:
            return False
        try:
            token = _form_request(self.token_endpoint, {
                "grant_type": "refresh_token", "refresh_token": self.refresh_token,
                "client_id": self.client_id, "resource": self.resource})
            self._store_token(token)
            return True
        except (OSError, ValueError):
            self.access_token = None
            self.refresh_token = None
            return False

    def authorize(self, challenge: str) -> None:
        """仅交互模式打开本机回调；无头任务必须预先提供 token_env。"""
        if self.refresh():
            return
        if not self.interactive:
            raise PermissionError("非交互运行无法完成 MCP OAuth 登录；请配置 token_env")
        metadata = self._discover(challenge)
        state = secrets.token_urlsafe(32)
        verifier = secrets.token_urlsafe(48)
        digest = hashlib.sha256(verifier.encode()).digest()
        challenge_value = base64.urlsafe_b64encode(digest).rstrip(b"=").decode()
        callback: dict[str, str] = {}

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self) -> None:
                parsed = urllib.parse.urlparse(self.path)
                if parsed.path != "/callback":
                    self.send_error(404)
                    return
                params = urllib.parse.parse_qs(parsed.query)
                if params.get("state", [None])[0] != state:
                    self.send_error(400, "OAuth state mismatch")
                    return
                callback["code"] = params.get("code", [""])[0]
                callback["error"] = params.get("error", [""])[0]
                self.send_response(200)
                self.end_headers()
                self.wfile.write(b"Authorization received. You may close this tab.")

            def log_message(self, *_args: Any) -> None:
                pass

        with HTTPServer(("127.0.0.1", 0), Handler) as callback_server:
            redirect_uri = f"http://127.0.0.1:{callback_server.server_port}/callback"
            if not self.client_id:
                registration = metadata.get("registration_endpoint")
                if not isinstance(registration, str):
                    raise ValueError("授权服务器不支持动态注册；请在用户 MCP 配置中提供 oauth.client_id")
                _safe_url(registration, local_ok=True)
                registered = _json_request(registration, {"client_name": "minicode", "redirect_uris": [redirect_uri],
                                                          "grant_types": ["authorization_code", "refresh_token"],
                                                          "token_endpoint_auth_method": "none"})
                self.client_id = registered.get("client_id")
                if not isinstance(self.client_id, str) or not self.client_id:
                    raise ValueError("OAuth 动态注册未返回 client_id")
            params = {"response_type": "code", "client_id": self.client_id,
                      "redirect_uri": redirect_uri, "state": state, "code_challenge": challenge_value,
                      "code_challenge_method": "S256", "resource": self.resource}
            if self.scope:
                params["scope"] = self.scope
            auth_url = metadata["authorization_endpoint"] + "?" + urllib.parse.urlencode(params)
            print(f"请在浏览器完成 MCP 授权：{auth_url}", file=sys.stderr)
            webbrowser.open(auth_url)
            deadline = time.monotonic() + 180
            while "code" not in callback and "error" not in callback and time.monotonic() < deadline:
                callback_server.timeout = min(1.0, deadline - time.monotonic())
                callback_server.handle_request()
        if callback.get("error"):
            raise PermissionError(f"MCP OAuth 授权失败：{callback['error']}")
        if not callback.get("code"):
            raise TimeoutError("等待 MCP OAuth 浏览器授权超时")
        token = _form_request(self.token_endpoint, {
            "grant_type": "authorization_code", "code": callback["code"],
            "redirect_uri": redirect_uri, "client_id": self.client_id,
            "code_verifier": verifier, "resource": self.resource})
        self._store_token(token)

    def token(self) -> str | None:
        if self.access_token and self.refresh_token and time.monotonic() >= self.expires_at:
            self.refresh()
        return self.access_token
