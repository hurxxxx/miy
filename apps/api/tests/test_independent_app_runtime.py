"""Opt-in real local Docker proof; never pull images or contact a live platform."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from uuid import uuid4


from miy_api.domains.independent_apps.delivery import RuntimeSpec


ROOT = Path(__file__).resolve().parents[3]
TOOLCHAIN = "sha256:eefe09d5bd59a0b9f30ca40ef251ccc52bd63294969b23f090ef9576df135e52"
INGRESS = "sha256:6769dc3a703c719c1d2756bda113659be28ae16cf0da58dd5fd823d6b9a050ea"


def spec(**changes):
    return replace(
        RuntimeSpec(
            str(uuid4()),
            str(uuid4()),
            "runtime-fixture",
            TOOLCHAIN,
            "http://127.0.0.1:19391",
            "/healthz",
        ),
        **changes,
    )
