import json
import os
from pathlib import Path
import runpy
import subprocess
import sys
from types import ModuleType, SimpleNamespace

from fastapi.testclient import TestClient
import httpx
import pytest


ROOT = Path(__file__).resolve().parents[2]


@pytest.mark.parametrize("origin", [None, "https://council.example"])
async def test_worker_initializes_configuration(monkeypatch, origin):
    monkeypatch.delitem(sys.modules, "app.main", raising=False)
    monkeypatch.setattr(os, "environ", {})
    workers = ModuleType("workers")
    workers.DurableObject = type("DurableObject", (), {})
    workers.WorkerEntrypoint = type("WorkerEntrypoint", (), {})
    monkeypatch.setitem(sys.modules, "workers", workers)

    async def fetch(app, request, env):
        with TestClient(app) as client:
            return client.request(**request)

    asgi = ModuleType("asgi")
    asgi.fetch = fetch
    monkeypatch.setitem(sys.modules, "asgi", asgi)
    worker = SimpleNamespace(**runpy.run_path(str(ROOT / "server" / "worker.py")))
    bindings = {
        "NICRRON_API_KEY": "llm-key",
        "PRISMTRACE_API_KEY": "trace-key",
        "ELEVENLABS_API_KEY": "voice-key",
        "ELEVENLABS_MODEL": "custom-model",
        **{f"ELEVENLABS_VOICE_{member.upper()}": f"voice-{member}"
           for member in ("buffett", "cramer", "burry", "leopold")},
    }
    if origin:
        bindings["CORS_ORIGINS"] = origin
    council = worker.Council()
    council.env = SimpleNamespace(**bindings)

    async def request(method, url, **kwargs):
        return await council.fetch(SimpleNamespace(js_object={"method": method, "url": url, **kwargs}))

    response = await request("GET", "/api/health")
    assert response.status_code == 200
    assert response.json()["llm"] == "nicrron"
    assert response.json()["voice"] is True
    assert response.json()["prism"] is True
    for candidate in ("https://council.example", "https://other.example"):
        response = await request("OPTIONS", "/api/health", headers={
            "Origin": candidate, "Access-Control-Request-Method": "GET",
        })
        assert response.status_code == (200 if origin is None or candidate == origin else 400)
        assert response.headers.get("access-control-allow-origin") == (
            "*" if origin is None else candidate if candidate == origin else None
        )

    calls = []

    def speak(request):
        calls.append(request)
        return httpx.Response(200, content=b"ID3audio")

    real_client = httpx.AsyncClient
    monkeypatch.setattr(httpx, "AsyncClient", lambda **kwargs: real_client(
        transport=httpx.MockTransport(speak), **kwargs,
    ))
    for member in ("buffett", "cramer", "burry", "leopold"):
        for method in ("GET", "POST"):
            payload = {"member": member, "text": "hello"}
            response = await request(method, "/api/voice/speak", **{
                "params" if method == "GET" else "json": payload,
            })
            assert response.content == b"ID3audio"
            assert calls[-1].url.path.endswith(f"/voice-{member}")
            assert calls[-1].headers["xi-api-key"] == "voice-key"
            assert json.loads(calls[-1].content)["model_id"] == "custom-model"


@pytest.fixture
def uploader(tmp_path):
    upload = tmp_path / "upload.json"
    npx = tmp_path / "npx"
    npx.write_text(
        f"#!{sys.executable}\n"
        "import os, pathlib, sys\n"
        "assert sys.argv[1:] == ['wrangler', 'secret', 'bulk']\n"
        "pathlib.Path(os.environ['UPLOAD_PATH']).write_text(sys.stdin.read())\n"
    )
    npx.chmod(0o700)

    def run(contents):
        env_file = tmp_path / "input.env"
        if contents is not None:
            env_file.write_text(contents)
        result = subprocess.run(
            ["sh", str(ROOT / "set-secrets.sh"), str(env_file)],
            env={**os.environ, "PATH": f"{tmp_path}{os.pathsep}{os.environ['PATH']}",
                 "UPLOAD_PATH": str(upload)},
            capture_output=True, text=True,
        )
        return result, upload

    return run


def test_secret_upload_preserves_dotenv_values(uploader):
    result, upload = uploader('''
# dotenv input
export NICRRON_API_KEY=abc
NICRRON_MODEL=nicrron/auto # routing
PRISMTRACE_PROJECT_ID='project # one' # comment
PRISMTRACE_HOST="https://example.test/#fragment"
ELEVENLABS_MODEL="custom\\nmodel"
ELEVENLABS_VOICE_BURRY="${NICRRON_API_KEY}-voice"
CORS_ORIGINS = "https://one.example,https://two.example"
PLAID_CLIENT_ID="line one
line two"
ANCHOR_API_KEY=abc#literal
ELEVENLABS_API_KEY=
UNRELATED_KEY=ignored
''')
    assert result.returncode == 0, result.stderr
    assert json.loads(upload.read_text()) == {
        "NICRRON_API_KEY": "abc",
        "NICRRON_MODEL": "nicrron/auto",
        "PRISMTRACE_PROJECT_ID": "project # one",
        "PRISMTRACE_HOST": "https://example.test/#fragment",
        "ELEVENLABS_MODEL": "custom\nmodel",
        "ELEVENLABS_VOICE_BURRY": "abc-voice",
        "CORS_ORIGINS": "https://one.example,https://two.example",
        "PLAID_CLIENT_ID": "line one\nline two",
        "ANCHOR_API_KEY": "abc#literal",
    }
    assert not result.stdout


@pytest.mark.parametrize("contents", [None, 'NICRRON_API_KEY=abc\nELEVENLABS_MODEL="unterminated'])
def test_invalid_secret_file_never_uploads(uploader, contents):
    result, upload = uploader(contents)
    assert result.returncode != 0
    assert not upload.exists()
    assert "abc" not in result.stdout + result.stderr
