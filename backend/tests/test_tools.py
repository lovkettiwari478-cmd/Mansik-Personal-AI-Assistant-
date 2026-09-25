"""Tool system tests — validation, safety, SSRF protection, executor."""

from __future__ import annotations

import pytest

from mansik.config import get_settings
from mansik.database import db_session
from mansik.errors import NotFoundError, ValidationAppError
from mansik.models import User, UserSettings
from mansik.security.passwords import hash_password
from mansik.tools import ToolContext, execute_tool, registry
from mansik.tools.calculator import safe_calculate
from mansik.tools.web_tools import _assert_public_url


def _ctx(user_id="testuser0000000000000000000000ff"):
    db = db_session()
    try:
        user = db.get(User, user_id)
        if user is None:
            user = User(id=user_id, email="ctx@example.com", password_hash=hash_password("x"),
                        display_name="Ctx")
            db.add(user)
            db.add(UserSettings(user_id=user_id))
            db.commit()
        settings = db.get(UserSettings, user_id)
        return ToolContext(db=db, user=user, user_settings=settings)
    except Exception:
        db.rollback()
        raise


@pytest.mark.parametrize("expr,expected", [
    ("2+3", 5), ("(2+3)*7", 35), ("2**10", 1024), ("10/4", 2.5),
    ("sqrt(16)", 4), ("max(1, 5, 3)", 5), ("7 % 3", 1), ("-5 + 3", -2),
    ("2^8", 256), ("round(3.7)", 4),
])
def test_calculator_valid(expr, expected):
    assert safe_calculate(expr) == expected


@pytest.mark.parametrize("expr", [
    "__import__('os').system('ls')",  # code injection
    "open('/etc/passwd')",
    "exit()",
    "1/0",                            # division by zero
    "10**(10**6)",                    # huge exponent
    "abc + 1",                        # unknown name
    "(()",                            # syntax error
    "'a' + 'b'",                      # string concat
    "True + True",
])
def test_calculator_rejects_dangerous(expr):
    from mansik.errors import AppError
    with pytest.raises(AppError):
        safe_calculate(expr)


@pytest.mark.asyncio
async def test_executor_unknown_tool():
    with pytest.raises(NotFoundError):
        await execute_tool(_ctx(), "no.such.tool", {})


@pytest.mark.asyncio
async def test_executor_validates_params():
    result = await execute_tool(_ctx(), "math.calculate", {"expression": 12345})  # wrong type
    assert result.success is False
    assert "Invalid parameters" in result.error

    result = await execute_tool(_ctx(), "math.calculate",
                                {"expression": "1+1", "extra": "field"})
    assert result.success is False  # extra fields rejected


@pytest.mark.asyncio
async def test_executor_runs_calculator():
    result = await execute_tool(_ctx(), "math.calculate", {"expression": "6*7"})
    assert result.success is True
    assert result.output["result"] == 42


@pytest.mark.asyncio
async def test_executor_rejects_unknown_fields_strictly():
    result = await execute_tool(_ctx(), "time.now", {"injected": "param"})
    assert result.success is False


@pytest.mark.parametrize("url", [
    "http://127.0.0.1/x",
    "http://localhost/admin",
    "http://10.0.0.1/internal",
    "http://192.168.1.1/router",
    "http://169.254.169.254/latest/meta-data",  # cloud metadata
    "http://[::1]/",
    "http://0.0.0.0/",
    "http://172.16.0.1/x",
    "ftp://example.com/file",
    "http://user:pass@example.com/",
    "file:///etc/passwd",
])
def test_ssrf_protection_blocks_private_urls(url):
    # Some of these need DNS; localhost/loopback variants resolve locally.
    from mansik.errors import AppError
    with pytest.raises(AppError):
        _assert_public_url(url)


def test_ssrf_protection_allows_public():
    _assert_public_url("https://example.com/path")


@pytest.mark.asyncio
async def test_web_search_reports_unavailability_honestly(tmp_path, monkeypatch):
    monkeypatch.setenv("MANISK_TAVILY_API_KEY", "")
    monkeypatch.setenv("MANISK_ALLOW_DUCKDUCKGO_SEARCH", "false")
    get_settings.cache_clear()
    ctx = _ctx()
    result = await execute_tool(ctx, "web.search", {"query": "anything"})
    assert result.success is False
    assert "No search backend configured" in result.error


@pytest.mark.asyncio
async def test_email_tool_unavailable_without_smtp():
    ctx = _ctx()
    result = await execute_tool(ctx, "email.send", {"to": "a@b.co", "subject": "s", "body": "b"})
    assert result.success is False
    assert "not configured" in result.error.lower()


def test_registry_catalog():
    tools = registry.all()
    ids = [t.id for t in tools]
    assert len(ids) == len(set(ids)), "duplicate tool ids"
    expected = {"math.calculate", "time.now", "tasks.create", "tasks.list", "tasks.complete",
                "memory.save", "memory.search", "calendar.create_event", "calendar.list_upcoming",
                "web.search", "web.fetch", "files.list", "files.read_text", "files.delete",
                "notify.user", "email.send"}
    assert expected == set(ids)
    # every tool declares a risk
    for t in tools:
        assert t.risk in {"read", "low_risk_write", "high_risk_write",
                          "external_communication", "financial", "security", "device_control"}
