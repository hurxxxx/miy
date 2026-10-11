from __future__ import annotations

import httpx

from miy_api.core import asr


def test_inference_gateway_asr_posts_audio_to_backend(monkeypatch, tmp_path) -> None:
    audio_path = tmp_path / "sample.wav"
    audio_path.write_bytes(b"audio-bytes")
    captured: dict[str, object] = {}

    def fake_post(url, *, headers, files, data, timeout):
        uploaded = files["file"]
        captured.update(
            {
                "url": url,
                "headers": headers,
                "filename": uploaded[0],
                "content": uploaded[1].read(),
                "content_type": uploaded[2],
                "data": data,
                "timeout": timeout,
            }
        )
        return httpx.Response(
            200,
            json={
                "text": " 안녕하세요 ",
                "language": "ko",
                "duration_sec": 3.5,
            },
        )

    monkeypatch.setattr(asr.httpx, "post", fake_post)
    backend = asr.InferenceGatewayASRBackend(
        base_url="http://127.0.0.1:18080",
        api_key="local",
        model="transcribe-v1",
        timeout_seconds=123.0,
    )
    progress: list[float] = []

    result = backend.transcribe(audio_path, language_hint="ko", on_progress=progress.append)

    assert captured == {
        "url": "http://127.0.0.1:18080/v1/audio/transcriptions",
        "headers": {"Authorization": "Bearer local"},
        "filename": "sample.wav",
        "content": b"audio-bytes",
        "content_type": "application/octet-stream",
        "data": {"model": "transcribe-v1", "language": "ko"},
        "timeout": 123.0,
    }
    assert result.text == "안녕하세요"
    assert result.language == "ko"
    assert result.duration_sec == 3.5
    assert progress == [0.1, 1.0]
