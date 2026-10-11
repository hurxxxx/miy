"""Built-in ASR callback ordering with synthetic transports/models only."""

import sys
from contextlib import nullcontext
from types import SimpleNamespace

import httpx

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
