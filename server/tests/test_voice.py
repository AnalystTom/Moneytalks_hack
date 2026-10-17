import json

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
    assert req.url.path == "/v1/text-to-dialogue"
    assert json.loads(req.content) == {"model_id": "eleven_v4", "inputs": [{"text": "I could be wrong.", "voice_id": "voice-burry"}]}
    assert req.headers["xi-api-key"] == "xi-test"
    assert b"I could be wrong." in req.content


def test_speak_get_for_audio_tags(client, eleven):
    assert client.get("/api/voice/speak", params={"member": "burry", "text": "hi"}).content == b"ID3fake-mp3"


def test_speak_without_keys_is_503(client):
    assert client.post("/api/voice/speak", json={"member": "burry", "text": "hi"}).status_code == 503


def test_speak_upstream_error_is_502(client, eleven, monkeypatch):
    mock_elevenlabs(monkeypatch, lambda r: httpx.Response(401))
    assert client.post("/api/voice/speak", json={"member": "burry", "text": "hi"}).status_code == 502


def test_existing_model_override_still_uses_tts(client, eleven, monkeypatch):
    monkeypatch.setenv("ELEVENLABS_MODEL", "eleven_multilingual_v2")
    assert client.post("/api/voice/speak", json={"member": "burry", "text": "hello"}).status_code == 200
    assert eleven[0].url.path == "/v1/text-to-speech/voice-burry"


def test_shared_voice_and_long_reply_preserve_all_text(client, eleven, monkeypatch):
    monkeypatch.setenv("ELEVENLABS_VOICE_ID", "shared-voice")
    text = "word " * 500
    response = client.post("/api/voice/speak", json={"member": "buffett", "text": text})
    assert response.status_code == 200
    parts = [json.loads(req.content)["inputs"][0] for req in eleven]
    assert all(part["voice_id"] == "shared-voice" and len(part["text"]) <= 2000 for part in parts)
    assert "".join(part["text"] for part in parts) == text


def test_automatic_voice_comes_from_provider(client, eleven, monkeypatch):
    def handler(request):
        if request.method == "GET":
            return httpx.Response(200, json={"voices": [{"voice_id": "available-voice"}]})
        assert json.loads(request.content)["inputs"][0]["voice_id"] == "available-voice"
        return httpx.Response(200, content=b"ID3", headers={"content-type": "audio/mpeg"})
    mock_elevenlabs(monkeypatch, handler)
    assert client.post("/api/voice/speak", json={"member": "buffett", "text": "hello"}).status_code == 200


def test_speech_rejects_non_audio(client, eleven, monkeypatch):
    mock_elevenlabs(monkeypatch, lambda _: httpx.Response(200, json={"error": "no audio"}))
    assert client.get("/api/voice/speak", params={"member": "burry", "text": "hi"}).status_code == 502


def test_speech_rejects_whitespace_before_provider_call(client, eleven):
    assert client.post("/api/voice/speak", json={"member": "burry", "text": "   "}).status_code == 422
    assert not eleven


def test_transcription_uses_scribe_and_records_actual_result(client, eleven, monkeypatch):
    traces = []

    async def span(*args, **kwargs):
        traces.append((args, kwargs))

    def handler(request):
        assert request.url.path == "/v1/speech-to-text"
        assert request.headers["xi-api-key"] == "xi-test"
        assert b"scribe_v2" in request.content and b"recorded-audio" in request.content
        return httpx.Response(200, json={"text": " What changed? "})

    monkeypatch.setattr(elevenlabs.prism, "span", span)
    mock_elevenlabs(monkeypatch, handler)
    response = client.post("/api/voice/transcribe", files={"file": ("question", b"recorded-audio", "audio/webm;codecs=opus")})
    assert response.json() == {"text": "What changed?"}
    assert traces[0][0][1:3] == ("voice.transcribe", "tool")
    assert traces[0][0][4:6] == ("What changed?", True)
    assert traces[0][1]["model"] == "scribe_v2"


@pytest.mark.parametrize("audio,kind,status", [(b"", "audio/webm", 422), (b"x", "text/plain", 415), (b"x" * (5 * 1024 * 1024 + 1), "audio/webm", 413)])
def test_invalid_upload_does_not_call_provider(client, eleven, audio, kind, status):
    response = client.post("/api/voice/transcribe", files={"file": ("question", audio, kind)})
    assert response.status_code == status
    assert not eleven


@pytest.mark.parametrize("payload,status", [({"text": ""}, 422), ({"text": None}, 422), ({"text": 12}, 422), (["invalid"], 502)])
def test_empty_or_invalid_transcript_never_fabricates_text(client, eleven, monkeypatch, payload, status):
    mock_elevenlabs(monkeypatch, lambda _: httpx.Response(200, json=payload))
    response = client.post("/api/voice/transcribe", files={"file": ("question", b"audio", "audio/webm")})
    assert response.status_code == status
    assert "text" not in response.json()


def test_transcription_without_key_is_explicit(client):
    response = client.post("/api/voice/transcribe", files={"file": ("question", b"audio", "audio/webm")})
    assert response.status_code == 503


def test_transcription_provider_error_is_traced_without_leaking_response(client, eleven, monkeypatch):
    traces = []

    async def span(*args, **kwargs):
        traces.append(args)

    monkeypatch.setattr(elevenlabs.prism, "span", span)
    mock_elevenlabs(monkeypatch, lambda _: httpx.Response(401, text="private upstream detail"))
    response = client.post("/api/voice/transcribe", files={"file": ("question", b"audio", "audio/webm")})
    assert response.status_code == 502
    assert "private" not in response.text
    assert traces[0][5] is False
