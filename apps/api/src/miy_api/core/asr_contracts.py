from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Protocol

ASRBackendName = str


class TransientError(Exception):
    pass


class PermanentError(Exception):
    pass


@dataclass(frozen=True)
class ASRHealth:
    backend: ASRBackendName
    ready: bool
    detail: str | None = None


@dataclass(frozen=True)
class TranscriptSegment:
    start: float
    end: float
    text: str


@dataclass(frozen=True)
class TranscriptResult:
    text: str
    segments: list[TranscriptSegment]
    language: str | None = None
    duration_sec: float | None = None


class ASRBackend(Protocol):
    name: ASRBackendName

    def healthcheck(self, *, deep: bool = False) -> ASRHealth: ...

    def transcribe(
        self,
        audio_path: Path,
        *,
        language_hint: str | None = None,
        on_progress: Callable[[float], None] | None = None,
    ) -> TranscriptResult:
        """Transcribe synchronously on the initiating thread.

        Invoke on_progress on that same thread and propagate any exception it
        raises before continuing work or returning a result. The caller may
        commit and reacquire authority inside this callback; its Session is not
        thread safe. Asynchronous callbacks or swallowing their failures violate
        this backend contract. Callback failure is not proof that an already
        accepted remote request or native computation has been cancelled.
        """
        ...
