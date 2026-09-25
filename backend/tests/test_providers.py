"""AI provider architecture tests.

A real local HTTP server simulates an OpenAI-compatible API (clearly a
TEST DOUBLE, used only here) so the full provider path — HTTP, SSE
streaming, retries, fallback, JSON plan protocol — is exercised honestly.
"""

from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

from mansik.ai.providers import Provider, ProviderNotConfiguredError, ProviderRegistry
from mansik.config import get_settings


class FakeOpenAI(BaseHTTPRequestHandler):
    """Test double for an OpenAI-compatible /chat/completions endpoint."""

    behavior = {"fail_first": 0, "stream_chunks": ["Hello", " ", "world", "!"]}

    def do_POST(self):  # noqa: N802
        if self.path.endswith("/chat/completions"):
            length = int(self.headers.get("content-length", 0))
            body = json.loads(self.rfile.read(length) or b"{}")
            self.server.requests.append(body)
            if FakeOpenAI.behavior["fail_first"] > 0:
                FakeOpenAI.behavior["fail_first"] -= 1
                self.send_response(503)
                self.end_headers()
                return
            if body.get("stream"):
                self.send_response(200)
                self.send_header("content-type", "text/event-stream")
                self.end_headers()
                for chunk in FakeOpenAI.behavior["stream_chunks"]:
                    data = {"choices": [{"delta": {"content": chunk}}]}
                    self.wfile.write(f"data: {json.dumps(data)}\n\n".encode())
                self.wfile.write(b"data: [DONE]\n\n")
            else:
                content = "".join(FakeOpenAI.behavior["stream_chunks"])
                payload = {"choices": [{"message": {"content": content}}]}
                self.send_response(200)
                self.send_header("content-type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps(payload).encode())
        else:
            self.send_response(404)
            self.end_headers()

    def log_message(self, *args):
        pass


@pytest.fixture
def fake_provider_server():
    server = HTTPServer(("127.0.0.1", 0), FakeOpenAI)
    server.requests = []
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield server
    server.shutdown()


def _provider(server, **kw) -> Provider:
    return Provider(
        kind="openai-compatible",
        base_url=f"http://127.0.0.1:{server.server_port}/v1",
        api_key="test-key", model="fake-model",
        timeout=10.0, max_retries=2, max_tokens=100, temperature=0.1, **kw,
    )


@pytest.mark.asyncio
async def test_provider_chat_roundtrip(fake_provider_server):
    p = _provider(fake_provider_server)
    result = await p.chat([{"role": "user", "content": "hi"}])
    assert result == "Hello world!"
    # request shape (OpenAI-compatible)
    sent = fake_provider_server.requests[-1]
    assert sent["model"] == "fake-model"
    assert sent["messages"][0]["content"] == "hi"
    assert sent["max_tokens"] == 100


@pytest.mark.asyncio
async def test_provider_streaming(fake_provider_server):
    p = _provider(fake_provider_server)
    chunks = [c async for c in p.stream_chat([{"role": "user", "content": "hi"}])]
    assert chunks == ["Hello", " ", "world", "!"]


@pytest.mark.asyncio
async def test_provider_retries_on_5xx(fake_provider_server):
    FakeOpenAI.behavior["fail_first"] = 1
    p = _provider(fake_provider_server)
    result = await p.chat([{"role": "user", "content": "hi"}])
    assert result == "Hello world!"


@pytest.mark.asyncio
async def test_registry_fallback(fake_provider_server):
    FakeOpenAI.behavior["fail_first"] = 99  # primary always fails
    primary = _provider(fake_provider_server)
    FakeOpenAI.behavior["fail_first"] = 0
    fallback = Provider(
        kind="openai-compatible",
        base_url=f"http://127.0.0.1:{fake_provider_server.server_port}/v1",
        api_key=None, model="fallback-model", timeout=10.0, max_retries=0,
        max_tokens=100, temperature=0.1,
    )
    registry = ProviderRegistry(primary=primary, fallback=fallback)
    assert await registry.chat([{"role": "user", "content": "hi"}]) == "Hello world!"


@pytest.mark.asyncio
async def test_registry_not_configured_raises_honest_error():
    registry = ProviderRegistry(primary=None, fallback=None)
    with pytest.raises(ProviderNotConfiguredError) as exc:
        await registry.chat([{"role": "user", "content": "hi"}])
    assert "MANISK_AI_BASE_URL" in str(exc.value)


def test_registry_from_settings(monkeypatch):
    monkeypatch.setenv("MANISK_AI_BASE_URL", "https://integrate.api.nvidia.com/v1")
    monkeypatch.setenv("MANISK_AI_API_KEY", "nvapi-test")
    monkeypatch.setenv("MANISK_AI_MODEL", "meta/llama-3.1-nemotron-70b-instruct")
    get_settings.cache_clear()
    settings = get_settings()
    registry = ProviderRegistry.from_settings(settings)
    assert registry.configured
    assert registry.primary.model == "meta/llama-3.1-nemotron-70b-instruct"
    status = settings.public_status()["ai_provider"]
    assert status["configured"] is True
    assert "nvapi-test" not in json.dumps(status)  # never leak the key
    # cleanup
    for var in ("MANISK_AI_BASE_URL", "MANISK_AI_API_KEY", "MANISK_AI_MODEL"):
        monkeypatch.delenv(var)
    get_settings.cache_clear()
