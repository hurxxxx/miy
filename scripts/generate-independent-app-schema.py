"""Generate/check the published JSON Schema from the API's versioned wire contract."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from pydantic import BaseModel
from pydantic_core import to_jsonable_python

from miy_api.domains.independent_apps.contracts import AppDefinition


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    targets = (
        root / "packages/contracts/independent-app.schema.json",
        root / "apps/codex-console-api/src/codex_console/independent_app_schema.generated.json",
    )
    schema = AppDefinition.model_json_schema()
    # Pydantic omits default_factory values from its JSON Schema. Publish these
    # owned, static defaults so independent clients can compare the same canonical
    # definition without importing the platform application or guessing defaults.
    def defaults(model, node):
        for name, field in model.model_fields.items():
            if field.default_factory is not None:
                node["properties"][name]["default"] = to_jsonable_python(
                    field.get_default(call_default_factory=True)
                )
            annotation = field.annotation
            if isinstance(annotation, type) and issubclass(annotation, BaseModel):
                defaults(annotation, schema["$defs"][annotation.__name__])

    defaults(AppDefinition, schema)
    schema["$schema"] = "https://json-schema.org/draft/2020-12/schema"
    expected = json.dumps(schema, indent=2, ensure_ascii=False) + "\n"
    for target in targets:
        if args.check:
            if not target.exists() or target.read_text() != expected:
                print(f"{target.name} differs from the API contract")
                return 1
        else:
            target.write_text(expected)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
