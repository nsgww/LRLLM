"""安全相关单元测试：SSRF 校验、API Key 鉴权、上传大小限制。

对应 docs/11-code-review-perf-security.md 的 S1 / S2 / S3。
"""

import asyncio

import pytest
from fastapi import Depends, FastAPI
from fastapi.responses import JSONResponse
from fastapi.testclient import TestClient

from app.api.deps import require_api_key
from app.core.config import Settings, _is_private_host
from app.core.errors import AppError

# ---------- S3: 出站地址校验 ----------


@pytest.mark.parametrize(
    "host",
    [
        "169.254.169.254",  # 云元数据
        "127.0.0.1",
        "0.0.0.0",
        "10.1.2.3",
        "192.168.0.1",
        "172.16.0.1",
        "172.31.255.254",
        "localhost",
    ],
)
def test_private_hosts_are_detected(host):
    assert _is_private_host(host) is True


@pytest.mark.parametrize("host", ["8.8.8.8", "api.openai.com", "172.32.0.1", "11.0.0.1"])
def test_public_hosts_are_allowed(host):
    assert _is_private_host(host) is False


@pytest.mark.parametrize(
    "host",
    [
        "2130706433",       # decimal == 127.0.0.1
        "0x7f000001",       # hex == 127.0.0.1
        "0177.0.0.1",       # octal == 127.0.0.1
        "0",                # == 0.0.0.0
        "::1",              # IPv6 loopback
        "fc00::1",          # IPv6 ULA
        "fe80::1",          # IPv6 link-local
        "::ffff:127.0.0.1", # IPv4-mapped IPv6
        "localhost.",       # trailing FQDN dot
    ],
)
def test_ip_literal_bypasses_are_detected(host):
    assert _is_private_host(host) is True


def test_public_ipv6_is_allowed():
    assert _is_private_host("2606:4700:4700::1111") is False


def test_base_url_rejects_non_http_scheme():
    with pytest.raises(ValueError, match="http/https"):
        Settings(_env_file=None, llm_base_url="file:///etc/passwd")


def test_base_url_without_host_is_rejected():
    with pytest.raises(ValueError, match="no host"):
        Settings(_env_file=None, llm_base_url="https://")


def test_metadata_endpoint_is_flagged():
    settings = Settings(
        _env_file=None, llm_base_url="http://169.254.169.254/latest/meta-data"
    )
    issues = settings.outbound_host_issues()
    assert len(issues) == 1
    assert "169.254.169.254" in issues[0]


def test_private_host_allowed_when_explicitly_opted_in():
    settings = Settings(
        _env_file=None,
        llm_base_url="http://192.168.1.50:8000/v1",
        allow_private_base_url=True,
    )
    assert settings.outbound_host_issues() == []


def test_public_base_url_passes():
    settings = Settings(_env_file=None, llm_base_url="https://api.openai.com/v1")
    assert settings.outbound_host_issues() == []


# ---------- S1: API Key 鉴权 ----------


def _settings_with_key(key: str, monkeypatch) -> None:
    monkeypatch.setattr(
        "app.api.deps.get_settings", lambda: Settings(_env_file=None, api_key=key)
    )


def _auth_app() -> FastAPI:
    """最小应用：仅挂鉴权依赖 + AppError 处理器（与 app.main 一致）。"""
    app = FastAPI()

    @app.exception_handler(AppError)
    async def _handler(_request, exc: AppError) -> JSONResponse:
        return JSONResponse(
            status_code=exc.http_status,
            content={"error": {"code": exc.code, "message": exc.message}},
        )

    @app.get("/x")
    async def x(_: None = Depends(require_api_key)) -> dict:
        return {"ok": True}

    return app


def test_auth_is_noop_when_key_unset(monkeypatch):
    _settings_with_key("", monkeypatch)
    assert TestClient(_auth_app()).get("/x").status_code == 200


def test_missing_key_is_rejected(monkeypatch):
    _settings_with_key("s3cret", monkeypatch)
    resp = TestClient(_auth_app()).get("/x")
    assert resp.status_code == 401
    # 响应不得泄露期望的密钥
    assert "s3cret" not in resp.text


def test_wrong_key_is_rejected(monkeypatch):
    _settings_with_key("s3cret", monkeypatch)
    resp = TestClient(_auth_app()).get("/x", headers={"Authorization": "Bearer wrong"})
    assert resp.status_code == 401


def test_correct_bearer_key_is_accepted(monkeypatch):
    _settings_with_key("s3cret", monkeypatch)
    resp = TestClient(_auth_app()).get("/x", headers={"Authorization": "Bearer s3cret"})
    assert resp.status_code == 200


def test_non_bearer_scheme_is_rejected(monkeypatch):
    _settings_with_key("s3cret", monkeypatch)
    resp = TestClient(_auth_app()).get("/x", headers={"Authorization": "Basic s3cret"})
    assert resp.status_code == 401


# ---------- S2: 上传大小限制 ----------


class _FakeUpload:
    """最小 UploadFile 替身：按块返回内容。"""

    def __init__(self, payload: bytes) -> None:
        self._payload = payload
        self._pos = 0

    async def read(self, size: int = -1) -> bytes:
        if size < 0:
            chunk = self._payload[self._pos :]
            self._pos = len(self._payload)
            return chunk
        chunk = self._payload[self._pos : self._pos + size]
        self._pos += len(chunk)
        return chunk


def test_upload_within_limit_is_read_fully(monkeypatch):
    from app.api.routers.documents import _read_upload

    monkeypatch.setattr(
        "app.api.routers.documents.get_settings",
        lambda: Settings(_env_file=None, max_upload_bytes=1024),
    )
    content = b"x" * 900
    assert asyncio.run(_read_upload(_FakeUpload(content))) == content


def test_upload_over_limit_raises_413(monkeypatch):
    from app.api.routers.documents import _read_upload
    from app.core.errors import AppError

    monkeypatch.setattr(
        "app.api.routers.documents.get_settings",
        lambda: Settings(_env_file=None, max_upload_bytes=1024),
    )
    with pytest.raises(AppError) as info:
        asyncio.run(_read_upload(_FakeUpload(b"x" * 4096)))
    assert info.value.code == "FILE_TOO_LARGE"
    assert info.value.http_status == 413


def test_upload_aborts_before_buffering_everything(monkeypatch):
    """超限时应立即停止读取，不得把整个流读完再判断。"""
    from app.api.routers.documents import _read_upload
    from app.core.errors import AppError

    monkeypatch.setattr(
        "app.api.routers.documents.get_settings",
        lambda: Settings(_env_file=None, max_upload_bytes=1024),
    )
    upload = _FakeUpload(b"x" * (100 * 1024 * 1024))
    with pytest.raises(AppError):
        asyncio.run(_read_upload(upload))
    # 读取位置应远小于总长度（1MiB 块 → 第 2 块即超限）
    assert upload._pos <= 2 * (1 << 20)


# ---------- S6/S7: 未分类异常不得泄露内部细节 ----------


def test_unhandled_exception_does_not_leak_internals():
    """兜底处理器必须返回通用文案，不能回显 str(exc)。"""
    from app.main import create_app

    app = create_app()

    @app.get("/__boom")
    async def _boom() -> dict:
        raise RuntimeError("SECRET dsn=postgres://user:pw@host sql=SELECT * FROM users")

    # raise_server_exceptions=False 模拟真实 uvicorn 行为
    client = TestClient(app, raise_server_exceptions=False)
    resp = client.get("/__boom")

    assert resp.status_code == 500
    assert "SECRET" not in resp.text
    assert "postgres://" not in resp.text
    payload = resp.json()["error"]
    assert payload["code"] == "INTERNAL_ERROR"
    assert payload["message"] == "internal server error"
    # request_id 保留，便于按日志对账
    assert payload["request_id"]
