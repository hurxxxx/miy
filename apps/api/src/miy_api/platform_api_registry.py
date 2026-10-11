from __future__ import annotations

from miy_api.api_composition import RouterSpec
from miy_api.domains.auth.router import router as auth_router
from miy_api.domains.auth.apps_router import router as apps_router
from miy_api.domains.ai.router import router as ai_router
from miy_api.domains.ai_graph.router import router as ai_graph_router
from miy_api.domains.ai_artifacts.router import router as ai_artifacts_router
from miy_api.domains.agent_terminal.router import router as agent_terminal_router
from miy_api.domains.agent_terminal.router import ws_router as agent_terminal_ws_router
from miy_api.domains.admin.router import router as admin_router
from miy_api.domains.admin.ai_model_settings_router import router as admin_ai_model_settings_router
from miy_api.domains.admin.document_processing_router import (
    router as admin_document_processing_router,
)
from miy_api.domains.admin.model_runtime_status_router import (
    router as admin_model_runtime_status_router,
)
from miy_api.domains.hermes.admin_router import router as admin_hermes_router
from miy_api.domains.groups.admin_router import router as admin_groups_router
from miy_api.domains.groups.directory_router import router as directory_router
from miy_api.domains.admin.app_access_router import router as admin_app_access_router
from miy_api.domains.integrations.admin_router import router as admin_platform_api_keys_router
from miy_api.domains.integrations.directory_router import router as directory_integrations_router
from miy_api.domains.integrations.app_router import router as app_integrations_router
from miy_api.domains.independent_apps.router import router as independent_apps_router
from miy_api.domains.usage.router import router as usage_router
from miy_api.domains.tetris.router import router as tetris_router
from miy_api.domains.content_access.router import router as content_access_router
from miy_api.domains.release_notes.router import router as release_notes_router
from miy_api.domains.realtime.router import ws_router as realtime_ws_router
from miy_api.domains.hermes.router import router as hermes_router
from miy_api.domains.hermes.mcp_router import router as hermes_mcp_router
from miy_api.domains.hermes_terminal.router import router as hermes_terminal_router
from miy_api.domains.hermes_terminal.router import ws_router as hermes_terminal_ws_router
from miy_api.domains.ocr.router import router as ocr_router
from miy_api.domains.retrieval.router import router as retrieval_router
from miy_api.domains.rag.router import router as rag_router
from miy_api.domains.search.router import router as search_router
from miy_api.domains.media.router import router as media_router


def platform_router_specs() -> tuple[RouterSpec, ...]:
    return (
        RouterSpec(auth_router, "public", 0, "platform", "miy_api.domains.auth.router"),
        RouterSpec(apps_router, "protected", 1, "platform", "miy_api.domains.auth.apps_router"),
        RouterSpec(ai_router, "protected", 2, "platform", "miy_api.domains.ai.router"),
        RouterSpec(ai_graph_router, "protected", 3, "platform", "miy_api.domains.ai_graph.router"),
        RouterSpec(
            ai_artifacts_router, "protected", 4, "platform", "miy_api.domains.ai_artifacts.router"
        ),
        RouterSpec(
            agent_terminal_router,
            "protected",
            5,
            "platform",
            "miy_api.domains.agent_terminal.router",
        ),
        RouterSpec(
            agent_terminal_ws_router,
            "public",
            6,
            "platform",
            "miy_api.domains.agent_terminal.router",
        ),
        RouterSpec(admin_router, "protected", 7, "platform", "miy_api.domains.admin.router"),
        RouterSpec(
            admin_ai_model_settings_router,
            "protected",
            8,
            "platform",
            "miy_api.domains.admin.ai_model_settings_router",
        ),
        RouterSpec(
            admin_document_processing_router,
            "protected",
            9,
            "platform",
            "miy_api.domains.admin.document_processing_router",
        ),
        RouterSpec(
            admin_model_runtime_status_router,
            "protected",
            10,
            "platform",
            "miy_api.domains.admin.model_runtime_status_router",
        ),
        RouterSpec(
            admin_hermes_router, "protected", 11, "platform", "miy_api.domains.hermes.admin_router"
        ),
        RouterSpec(
            admin_groups_router, "protected", 12, "platform", "miy_api.domains.groups.admin_router"
        ),
        RouterSpec(
            directory_router, "protected", 13, "platform", "miy_api.domains.groups.directory_router"
        ),
        RouterSpec(
            admin_app_access_router,
            "protected",
            14,
            "platform",
            "miy_api.domains.admin.app_access_router",
        ),
        RouterSpec(
            admin_platform_api_keys_router,
            "protected",
            15,
            "platform",
            "miy_api.domains.integrations.admin_router",
        ),
        RouterSpec(
            directory_integrations_router,
            "public",
            16,
            "platform",
            "miy_api.domains.integrations.directory_router",
        ),
        RouterSpec(
            app_integrations_router,
            "public",
            17,
            "platform",
            "miy_api.domains.integrations.app_router",
        ),
        RouterSpec(
            independent_apps_router,
            "public",
            18,
            "platform",
            "miy_api.domains.independent_apps.router",
        ),
        RouterSpec(usage_router, "protected", 19, "platform", "miy_api.domains.usage.router"),
        RouterSpec(tetris_router, "protected", 20, "platform", "miy_api.domains.tetris.router"),
        RouterSpec(
            content_access_router, "public", 22, "platform", "miy_api.domains.content_access.router"
        ),
        RouterSpec(
            release_notes_router,
            "protected",
            23,
            "platform",
            "miy_api.domains.release_notes.router",
        ),
        RouterSpec(realtime_ws_router, "public", 24, "platform", "miy_api.domains.realtime.router"),
        RouterSpec(hermes_router, "protected", 36, "platform", "miy_api.domains.hermes.router"),
        RouterSpec(
            hermes_mcp_router, "public", 37, "platform", "miy_api.domains.hermes.mcp_router"
        ),
        RouterSpec(
            hermes_terminal_router,
            "protected",
            38,
            "platform",
            "miy_api.domains.hermes_terminal.router",
        ),
        RouterSpec(
            hermes_terminal_ws_router,
            "public",
            39,
            "platform",
            "miy_api.domains.hermes_terminal.router",
        ),
        RouterSpec(ocr_router, "protected", 40, "platform", "miy_api.domains.ocr.router"),
        RouterSpec(
            retrieval_router, "protected", 50, "platform", "miy_api.domains.retrieval.router"
        ),
        RouterSpec(rag_router, "protected", 51, "platform", "miy_api.domains.rag.router"),
        RouterSpec(search_router, "protected", 53, "platform", "miy_api.domains.search.router"),
        RouterSpec(media_router, "protected", 54, "platform", "miy_api.domains.media.router"),
    )
