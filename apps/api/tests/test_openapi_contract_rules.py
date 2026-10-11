from __future__ import annotations

from miy_api.openapi_contract_rules import validate_openapi_contract_rules


def messages(schema: dict) -> list[str]:
    return [finding.message for finding in validate_openapi_contract_rules(schema)]
