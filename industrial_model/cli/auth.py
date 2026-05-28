from __future__ import annotations

import base64
import hashlib
import html
import json
import os
import platform
import secrets
import ssl
import subprocess
import sys
import urllib.error
import urllib.parse
import urllib.request
import webbrowser
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from queue import Empty, Full, Queue
from threading import Thread
from typing import Any


@dataclass(frozen=True)
class LoginConfig:
    authority: str = "https://auth.cognite.com"
    client_id: str = "0404baaa-0a90-43a2-aba7-a110b53fb41c"
    redirect_uri: str = "https://localhost:3000/"
    port: int = 3000
    login_timeout_seconds: int = 300
    cert_dir: Path = Path.home() / ".cdf-login"


@dataclass(frozen=True)
class LoginOptions:
    org: str | None = None


@dataclass(frozen=True)
class TokenAuth:
    project: str | None
    base_url: str | None


@dataclass(frozen=True)
class Session:
    project: str
    base_url: str
    data_model: str  # "space/external_id/version"


DEFAULT_LOGIN_CONFIG = LoginConfig()
LOGIN_SCOPE = "openid profile email"


def _base64_url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode("ascii").rstrip("=")


def _random_base64_url(num_bytes: int = 32) -> str:
    return _base64_url(secrets.token_bytes(num_bytes))


def _pkce_challenge(verifier: str) -> str:
    return _base64_url(hashlib.sha256(verifier.encode("ascii")).digest())


def _fetch_json(url: str, data: bytes | None = None) -> dict[str, Any]:
    headers = {"Content-Type": "application/x-www-form-urlencoded"} if data else {}
    request = urllib.request.Request(
        url, data=data, headers=headers, method="POST" if data else "GET"
    )

    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            raw = response.read().decode("utf-8")
    except urllib.error.HTTPError as err:
        raw = err.read().decode("utf-8", errors="replace")
        try:
            payload = json.loads(raw) if raw else {}
        except json.JSONDecodeError:
            payload = {}
        message = (
            payload.get("error_description")
            or payload.get("error")
            or payload.get("message")
            or err.reason
        )
        raise RuntimeError(f"{url} failed with {err.code}: {message}") from err

    try:
        return json.loads(raw) if raw else {}
    except json.JSONDecodeError as err:
        raise RuntimeError(f"Expected JSON from {url}, got: {raw[:200]}") from err


def _discover_openid_configuration(authority: str) -> dict[str, Any]:
    discovery_url = urllib.parse.urljoin(
        authority.rstrip("/") + "/", ".well-known/openid-configuration"
    )
    return _fetch_json(discovery_url)


def _get_or_create_certificate(config: LoginConfig) -> tuple[Path, Path]:
    key_path = config.cert_dir / "localhost-key.pem"
    cert_path = config.cert_dir / "localhost-cert.pem"

    if key_path.exists() and cert_path.exists():
        return key_path, cert_path

    print("Generating self-signed certificate for HTTPS callback...", file=sys.stderr)
    config.cert_dir.mkdir(parents=True, exist_ok=True)

    try:
        subprocess.run(
            [
                "openssl",
                "req",
                "-x509",
                "-newkey",
                "rsa:2048",
                "-nodes",
                "-sha256",
                "-subj",
                "/CN=localhost",
                "-addext",
                "subjectAltName=DNS:localhost,IP:127.0.0.1,IP:::1",
                "-keyout",
                str(key_path),
                "-out",
                str(cert_path),
                "-days",
                "365",
            ],
            check=True,
            capture_output=True,
        )
    except (OSError, subprocess.CalledProcessError) as err:
        raise RuntimeError(
            "Failed to generate self-signed certificate. Install OpenSSL and retry."
        ) from err

    return key_path, cert_path


def _build_authorization_url(
    config: LoginConfig,
    discovery: dict[str, Any],
    verifier: str,
    state: str,
    org: str | None,
) -> str:
    authorization_endpoint = discovery.get("authorization_endpoint")
    if not isinstance(authorization_endpoint, str):
        raise RuntimeError(
            "OpenID discovery document is missing authorization_endpoint"
        )

    query = {
        "client_id": config.client_id,
        "redirect_uri": config.redirect_uri,
        "response_type": "code",
        "scope": LOGIN_SCOPE,
        "code_challenge": _pkce_challenge(verifier),
        "code_challenge_method": "S256",
        "state": state,
    }
    if org:
        query["organization_hint"] = org

    parts = list(urllib.parse.urlparse(authorization_endpoint))
    parts[4] = urllib.parse.urlencode(query)
    return urllib.parse.urlunparse(parts)


def _exchange_code_for_token(
    discovery: dict[str, Any], code: str, verifier: str, config: LoginConfig
) -> str:
    token_endpoint = discovery.get("token_endpoint")
    if not isinstance(token_endpoint, str):
        raise RuntimeError("OpenID discovery document is missing token_endpoint")

    body = urllib.parse.urlencode(
        {
            "grant_type": "authorization_code",
            "client_id": config.client_id,
            "code": code,
            "redirect_uri": config.redirect_uri,
            "code_verifier": verifier,
        }
    ).encode("utf-8")
    token_response = _fetch_json(token_endpoint, data=body)

    access_token = token_response.get("access_token")
    if not isinstance(access_token, str):
        raise RuntimeError("No access_token in token response")
    return access_token


def _callback_html(title: str, message: str) -> bytes:
    safe_title = html.escape(title)
    safe_message = html.escape(message)
    return (
        '<html><body style="font-family:system-ui;padding:40px;text-align:center">'
        f"<h1>{safe_title}</h1><p>{safe_message}</p></body></html>"
    ).encode()


def _create_callback_server(
    config: LoginConfig,
    discovery: dict[str, Any],
    verifier: str,
    expected_state: str,
    result_queue: Queue[tuple[str, str]],
) -> HTTPServer:
    class CallbackHandler(BaseHTTPRequestHandler):
        def log_message(self, format: str, *args: Any) -> None:
            return

        def _send_html(self, status: int, title: str, message: str) -> None:
            body = _callback_html(title, message)
            self.send_response(status)
            self.send_header("Content-Type", "text/html")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _complete(self, kind: str, value: str) -> None:
            try:
                result_queue.put_nowait((kind, value))
            except Full:
                pass

        def do_GET(self) -> None:
            url = urllib.parse.urlparse(self.path)
            if url.path != "/":
                self.send_response(404)
                self.end_headers()
                self.wfile.write(b"Not found")
                return

            params = urllib.parse.parse_qs(url.query)
            error = params.get("error", [None])[0]
            if error:
                message = params.get("error_description", [error])[0] or error
                self._send_html(400, "Authentication error", message)
                self._complete("error", message)
                return

            state = params.get("state", [None])[0]
            if state != expected_state:
                message = "Invalid OAuth state"
                self._send_html(400, "Authentication error", message)
                self._complete("error", message)
                return

            code = params.get("code", [None])[0]
            if not code:
                message = "No authorization code returned"
                self._send_html(400, "Authentication error", message)
                self._complete("error", message)
                return

            try:
                access_token = _exchange_code_for_token(
                    discovery, code, verifier, config
                )
            except Exception as err:
                message = str(err)
                self._send_html(400, "Authentication error", message)
                self._complete("error", message)
                return

            self._send_html(
                200,
                "Login successful",
                "You can close this window and return to the terminal.",
            )
            self._complete("token", access_token)

    key_path, cert_path = _get_or_create_certificate(config)
    server = HTTPServer(("127.0.0.1", config.port), CallbackHandler)
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.load_cert_chain(certfile=cert_path, keyfile=key_path)
    server.socket = context.wrap_socket(server.socket, server_side=True)
    return server


def _is_wsl() -> bool:
    if platform.system().lower() != "linux":
        return False
    if os.environ.get("WSL_DISTRO_NAME") or os.environ.get("WSL_INTEROP"):
        return True
    try:
        return "microsoft" in Path("/proc/version").read_text(encoding="utf-8").lower()
    except OSError:
        return False


def _wsl_drives_mount_point() -> str:
    try:
        config = Path("/etc/wsl.conf").read_text(encoding="utf-8")
    except OSError:
        return "/mnt/"

    for line in config.splitlines():
        stripped = line.strip()
        if stripped.startswith("root"):
            _, _, mount_point = stripped.partition("=")
            mount_point = mount_point.strip()
            return mount_point if mount_point.endswith("/") else f"{mount_point}/"
    return "/mnt/"


def _powershell_path() -> str:
    if _is_wsl():
        return str(
            Path(_wsl_drives_mount_point())
            / "c/Windows/System32/WindowsPowerShell/v1.0/powershell.exe"
        )
    windows_root = (
        os.environ.get("SYSTEMROOT") or os.environ.get("windir") or r"C:\Windows"
    )
    return str(Path(windows_root) / "System32/WindowsPowerShell/v1.0/powershell.exe")


def _powershell_start_args(url: str) -> list[str]:
    encoded_command = base64.b64encode(f'Start "{url}"'.encode("utf-16le")).decode(
        "ascii"
    )
    return [
        "-NoProfile",
        "-NonInteractive",
        "-ExecutionPolicy",
        "Bypass",
        "-EncodedCommand",
        encoded_command,
    ]


def _try_open(command: str, args: list[str]) -> bool:
    try:
        process = subprocess.Popen(
            [command, *args], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
        )
    except OSError:
        return False
    try:
        return process.wait(timeout=1) == 0
    except subprocess.TimeoutExpired:
        return True


def open_browser(url: str) -> None:
    system = platform.system().lower()

    if system == "darwin" and _try_open("open", [url]):
        return
    if system == "windows":
        if _try_open(_powershell_path(), _powershell_start_args(url)):
            return
        if _try_open("cmd", ["/c", "start", "", url]):
            return
    elif _is_wsl():
        if _try_open(_powershell_path(), _powershell_start_args(url)):
            return
        if _try_open("cmd.exe", ["/c", "start", "", url]):
            return
        if _try_open("wslview", [url]):
            return
    else:
        for command, args in (
            ("xdg-open", [url]),
            ("sensible-browser", [url]),
            ("gio", ["open", url]),
            ("python3", ["-m", "webbrowser", url]),
        ):
            if _try_open(command, args):
                return

    try:
        if webbrowser.open(url):
            return
    except Exception:
        pass

    raise RuntimeError("Could not open browser automatically")


def browser_login(
    options: LoginOptions | None = None, config: LoginConfig = DEFAULT_LOGIN_CONFIG
) -> str:
    verifier = _random_base64_url(64)
    state = _random_base64_url(32)
    options = options or LoginOptions()

    print("Fetching OpenID configuration...", file=sys.stderr)
    discovery = _discover_openid_configuration(config.authority)
    auth_url = _build_authorization_url(config, discovery, verifier, state, options.org)

    result_queue: Queue[tuple[str, str]] = Queue(maxsize=1)
    server = _create_callback_server(config, discovery, verifier, state, result_queue)
    server_thread = Thread(target=server.serve_forever, daemon=True)
    server_thread.start()

    print(
        f"Local HTTPS server listening on https://localhost:{config.port}",
        file=sys.stderr,
    )
    print("Opening browser for authentication...", file=sys.stderr)
    try:
        open_browser(auth_url)
    except Exception:
        print(
            "Could not open browser automatically."
            f"\nOpen this URL manually:\n{auth_url}",
            file=sys.stderr,
        )

    try:
        kind, value = result_queue.get(timeout=config.login_timeout_seconds)
    except Empty as err:
        raise TimeoutError(
            "Login timeout - no response received within 5 minutes"
        ) from err
    finally:
        server.shutdown()
        server.server_close()
        server_thread.join(timeout=5)

    if kind == "error":
        raise RuntimeError(value)
    return value


def save_session(session: Session, config: LoginConfig = DEFAULT_LOGIN_CONFIG) -> None:
    path = config.cert_dir / "session.json"
    payload = {
        "project": session.project,
        "base_url": session.base_url,
        "data_model": session.data_model,
    }
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    tmp.replace(path)


def load_session(config: LoginConfig = DEFAULT_LOGIN_CONFIG) -> Session | None:
    path = config.cert_dir / "session.json"
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(payload, dict):
        return None
    project = payload.get("project")
    base_url = payload.get("base_url")
    data_model = payload.get("data_model")
    if (
        not isinstance(project, str)
        or not isinstance(base_url, str)
        or not isinstance(data_model, str)
    ):
        return None
    return Session(project=project, base_url=base_url, data_model=data_model)


def decode_token_claims(token: str) -> dict[str, Any]:
    parts = token.split(".")
    if len(parts) != 3:
        return {}

    payload = parts[1]
    padding = "=" * (-len(payload) % 4)
    try:
        decoded = base64.urlsafe_b64decode(payload + padding).decode("utf-8")
        claims = json.loads(decoded)
    except (ValueError, json.JSONDecodeError):
        return {}
    return claims if isinstance(claims, dict) else {}


def extract_auth_from_token(token: str) -> TokenAuth:
    claims = decode_token_claims(token)
    projects = claims.get("projects")
    project = (
        projects[0]
        if isinstance(projects, list) and projects and isinstance(projects[0], str)
        else None
    )

    aud = claims.get("aud")
    if isinstance(aud, list):
        aud = next(
            (v for v in aud if isinstance(v, str) and v.startswith("https://")), None
        )
    base_url = aud if isinstance(aud, str) and aud.startswith("https://") else None

    return TokenAuth(project=project, base_url=base_url)
