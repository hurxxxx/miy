from __future__ import annotations

from miy_api.domains.conversations.scope_registry import (
    ConversationExperience,
)


def _ai_conversations_path(suffix: str = "") -> str:
    return f"/api/v1/chatbot/conversations{suffix}"


class _ExtensionConversationScopeAdapter:
    scope_ref = "external_plugin_record_scope"
    experience = ConversationExperience(owner_app_id="chatbot")

    def validate(self, **kwargs) -> None:
        del kwargs

    def system_prompt(self, **kwargs) -> str:
        del kwargs
        return "This conversation is scoped to an external plugin record."


class _MissingPromptConversationScopeAdapter:
    scope_ref = "missing_prompt_scope"
    experience = ConversationExperience(owner_app_id="chatbot")

    def validate(self, **kwargs) -> None:
        del kwargs

    def system_prompt(self, **kwargs) -> str:
        del kwargs
        return ""


class _CountingConversationScopeAdapter:
    scope_ref = "counting_scope"
    experience = ConversationExperience(owner_app_id="chatbot")

    def __init__(self) -> None:
        self.validate_calls = 0
        self.validated_resource_ids: list[str] = []

    def validate(self, **kwargs) -> None:
        self.validate_calls += 1
        self.validated_resource_ids.append(kwargs["scope_resource_id"])

    def system_prompt(self, **kwargs) -> str:
        del kwargs
        return "Scoped prompt."


class _UnboundConversationScopeAdapter:
    scope_ref = "unbound_scope"


class _DirectResponseConversationScopeAdapter:
    scope_ref = "direct_response_scope"
    experience = ConversationExperience(owner_app_id="chatbot")
    server_owned_artifact_types = frozenset({"plugin-analysis"})

    def validate(self, **kwargs) -> None:
        del kwargs

    def system_prompt(self, **kwargs) -> str:
        del kwargs
        return "Scoped prompt."

    def turn_context(self, **kwargs) -> dict:
        del kwargs
        return {
            "direct_response": "  fixed server response  ",
            "server_owned_artifact_types": ["turn-owned-artifact"],
        }
