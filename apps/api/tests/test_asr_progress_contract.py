"""Built-in ASR callback ordering with synthetic transports/models only."""

from contextlib import nullcontext
from pathlib import Path
import sys
from threading import get_ident
from types import SimpleNamespace

import httpx
import pytest

from miy_api.core import asr


class StopPhase(Exception):
    pass


def backend_fixture(name, monkeypatch, steps):
    if name in {"cohere", "inference_gateway"}:
        cls = asr.CohereASRBackend if name == "cohere" else asr.InferenceGatewayASRBackend
        backend = cls(
            base_url="http://asr.invalid", api_key="synthetic", model="synthetic", timeout_seconds=1
        )

        def post(*args, **kwargs):
            steps.append("generate")
            return httpx.Response(200, json={"text": "Transcript"})

        monkeypatch.setattr(asr.httpx, "post", post)
        return backend
    if name == "qwen_asr":
        backend = asr.QwenASRBackend(model_repo="synthetic", device="")
        waveform = SimpleNamespace(squeeze=lambda _: "wave")
        monkeypatch.setitem(
            sys.modules, "torchaudio", SimpleNamespace(load=lambda _: (waveform, 16000))
        )
        monkeypatch.setitem(sys.modules, "torch", SimpleNamespace(no_grad=nullcontext))

        class Model:
            def generate(self, **kwargs):
                steps.append("generate")
                return []

        class Processor:
            def __call__(self, *args, **kwargs):
                return {}

            def batch_decode(self, *args, **kwargs):
                return ["Transcript"]

        monkeypatch.setattr(backend, "_load", lambda: (Model(), Processor()))
        return backend
    backend = asr.WhisperASRBackend(model_size="synthetic", device="cpu", compute_type="synthetic")

    class Model:
        def transcribe(self, *args, **kwargs):
            def segments():
                for i in range(2):
                    steps.append("generate")
                    yield SimpleNamespace(start=i, end=i + 1, text="Transcript")

            return segments(), SimpleNamespace(duration=2, language="en")

    monkeypatch.setattr(backend, "_load", lambda: Model())
    return backend


@pytest.mark.parametrize("name", ["cohere", "inference_gateway", "qwen_asr", "whisper"])
@pytest.mark.parametrize("fail_at", [None, 1, 2])
def test_builtin_callbacks_are_synchronous_and_propagate_exception(
    name, fail_at, monkeypatch, tmp_path
):
    steps = []
    backend = backend_fixture(name, monkeypatch, steps)
    audio = tmp_path / "synthetic.wav"
    audio.write_bytes(b"synthetic")
    origin = get_ident()
    progress = []

    def callback(value):
        assert get_ident() == origin
        progress.append(value)
        steps.append("callback")
        if len(progress) == fail_at:
            raise StopPhase()

    if fail_at:
        with pytest.raises(StopPhase):
            backend.transcribe(Path(audio), on_progress=callback)
        assert len(progress) == fail_at
        assert steps[-1] == "callback"
        assert steps.count("generate") == (fail_at if name == "whisper" else fail_at - 1)
    else:
        assert backend.transcribe(audio, on_progress=callback).text
        assert progress[-1] == 1.0
        assert steps.count("generate") == (2 if name == "whisper" else 1)
