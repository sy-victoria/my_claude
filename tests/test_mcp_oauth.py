"""本机模拟 MCP 与授权服务器，验证 OAuth PKCE 和恢复流程。"""

from __future__ import annotations

import base64
import hashlib
import json
import threading
import urllib.error
import urllib.parse
import urllib.request
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

from minicode.mcp_client import HttpMcpServer


def test_oauth_login_and_refresh(monkeypatch):
    observed: dict[str, object] = {"registrations": 0, "tokens": [], "mcp_auth": []}

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            origin = f"http://127.0.0.1:{self.server.server_port}"
            if self.path == "/.well-known/oauth-protected-resource/mcp":
                result = {"resource": origin + "/mcp", "authorization_servers": [origin]}
            elif self.path == "/.well-known/oauth-authorization-server":
                result = {"issuer": origin, "authorization_endpoint": origin + "/authorize",
                          "token_endpoint": origin + "/token", "registration_endpoint": origin + "/register"}
            else:
                self.send_error(404)
                return
            self._json(result)

        def do_POST(self):
            length = int(self.headers["Content-Length"])
            content = self.rfile.read(length)
            if self.path == "/register":
                observed["registrations"] += 1
                self._json({"client_id": "dynamic-client"})
                return
            if self.path == "/token":
                fields = urllib.parse.parse_qs(content.decode())
                observed["tokens"].append(fields)
                if fields["grant_type"] == ["authorization_code"]:
                    verifier = fields["code_verifier"][0]
                    digest = hashlib.sha256(verifier.encode()).digest()
                    challenge = base64.urlsafe_b64encode(digest).rstrip(b"=").decode()
                    assert challenge == observed["challenge"]
                    self._json({"access_token": "first", "refresh_token": "refresh-one",
                                "token_type": "Bearer", "expires_in": 3600})
                else:
                    self._json({"access_token": "second", "refresh_token": "refresh-two",
                                "token_type": "Bearer", "expires_in": 3600})
                return
            assert self.path == "/mcp"
            payload = json.loads(content)
            auth = self.headers.get("Authorization")
            observed["mcp_auth"].append(auth)
            if auth not in {"Bearer first", "Bearer second"}:
                self.send_response(401)
                self.send_header("WWW-Authenticate", f'Bearer resource_metadata="http://127.0.0.1:{self.server.server_port}/.well-known/oauth-protected-resource/mcp"')
                self.end_headers()
                return
            if "id" not in payload:
                self.send_response(202)
                self.end_headers()
                return
            result = {"content": [{"type": "text", "text": "ok"}]} if payload["method"] == "tools/call" else {}
            self._json({"jsonrpc": "2.0", "id": payload["id"], "result": result})

        def _json(self, data: dict) -> None:
            body = json.dumps(data).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *_args):
            pass

    server = HTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    origin = f"http://127.0.0.1:{server.server_port}"

    def open_browser(url: str) -> bool:
        params = urllib.parse.parse_qs(urllib.parse.urlparse(url).query)
        observed["challenge"] = params["code_challenge"][0]
        assert params["resource"] == [origin + "/mcp"]
        callback = params["redirect_uri"][0] + "?" + urllib.parse.urlencode({
            "state": params["state"][0], "code": "code-one"})
        wrong = params["redirect_uri"][0] + "?state=wrong&code=forged"
        def send_callbacks() -> None:
            try:
                urllib.request.urlopen(wrong, timeout=5).close()
            except urllib.error.HTTPError as exc:
                assert exc.code == 400
            urllib.request.urlopen(callback, timeout=5).close()
        threading.Thread(target=send_callbacks, daemon=True).start()
        return True

    monkeypatch.setattr("minicode.mcp_oauth.webbrowser.open", open_browser)
    try:
        client = HttpMcpServer("demo", origin + "/mcp", oauth={})
        client.initialize()
        assert client.call_tool("ping", {}) == "ok"
        assert observed["registrations"] == 1
        assert client.oauth is not None
        client.oauth.expires_at = 0
        assert client.call_tool("ping", {}) == "ok"
        assert observed["mcp_auth"][-1] == "Bearer second"
        assert [token["grant_type"][0] for token in observed["tokens"]] == ["authorization_code", "refresh_token"]
        assert all(token["resource"] == [origin + "/mcp"] for token in observed["tokens"])
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_oauth_headless_mode_does_not_start_browser(monkeypatch):
    monkeypatch.setattr("minicode.mcp_oauth.webbrowser.open", lambda _url: pytest.fail("browser opened"))
    client = HttpMcpServer("demo", "https://example.com/mcp", oauth={}, interactive=False)
    with pytest.raises(PermissionError, match="非交互运行"):
        client.oauth.authorize('Bearer resource_metadata="https://example.com/.well-known/oauth-protected-resource/mcp"')
