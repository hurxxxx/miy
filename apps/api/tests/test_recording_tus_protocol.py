from __future__ import annotations

import base64


def _encoded(value: str) -> str:
    return base64.b64encode(value.encode("utf-8")).decode("ascii")
