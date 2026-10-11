from __future__ import annotations


from miy_api.domains.docs.collab_codec import (
    CodecPayload,
    CodecProcessResult,
)


class FakeRunner:
    def __init__(self, responses: list[CodecPayload]) -> None:
        self.responses = responses
        self.calls: list[tuple[str, CodecPayload]] = []

    def run(self, mode: str, payload: CodecPayload) -> CodecPayload:
        self.calls.append((mode, payload))
        return self.responses.pop(0)


class FakeCommand:
    def __init__(self, result: CodecProcessResult) -> None:
        self.result = result
        self.calls: list[tuple[str, str]] = []

    def run(self, mode: str, payload_json: str) -> CodecProcessResult:
        self.calls.append((mode, payload_json))
        return self.result
