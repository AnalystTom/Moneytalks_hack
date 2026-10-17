import httpx
import pytest

from app.services import elevenlabs


REAL_CLIENT = httpx.AsyncClient


def mock_elevenlabs(monkeypatch, handler):
    monkeypatch.setattr(elevenlabs.httpx, "AsyncClient", lambda **kw: REAL_CLIENT(transport=httpx.MockTransport(handler), **kw))


@pytest.fixture
def eleven(monkeypatch):
    monkeypatch.setenv("ELEVENLABS_API_KEY", "xi-test")
    monkeypatch.setenv("ELEVENLABS_VOICE_BURRY", "voice-burry")
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return httpx.Response(200, content=b"ID3fake-mp3", headers={"content-type": "audio/mpeg"})

    mock_elevenlabs(monkeypatch, handler)
    return calls


def test_speak_posts_to_member_voice(client, eleven):
    r = client.post("/api/voice/speak", json={"member": "burry", "text": "I could be wrong."})
    assert r.status_code == 200
    assert r.headers["content-type"] == "audio/mpeg"
    assert r.content == b"ID3fake-mp3"
    req = eleven[0]
    assert req.url.path == "/v1/text-to-speech/voice-burry"
    assert req.headers["xi-api-key"] == "xi-test"
    assert b"I could be wrong." in req.content


def test_speak_get_for_audio_tags(client, eleven):
    assert client.get("/api/voice/speak", params={"member": "burry", "text": "hi"}).content == b"ID3fake-mp3"


def test_speak_without_keys_is_503(client):
    assert client.post("/api/voice/speak", json={"member": "burry", "text": "hi"}).status_code == 503


def test_speak_upstream_error_is_502(client, eleven, monkeypatch):
    mock_elevenlabs(monkeypatch, lambda r: httpx.Response(401))
    assert client.post("/api/voice/speak", json={"member": "burry", "text": "hi"}).status_code == 502
