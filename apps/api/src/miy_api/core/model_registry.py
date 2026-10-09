from __future__ import annotations


def import_all_models() -> None:
    """Register every SQLAlchemy model class with the shared metadata registry."""
    from miy_api.domains.agent_terminal import (
        models as agent_terminal_models,  # noqa: F401
    )
    from miy_api.domains.ai import approvals as ai_approvals  # noqa: F401
    from miy_api.domains.ai import interactions as ai_interactions  # noqa: F401
    from miy_api.domains.ai import (
        model_settings_models as ai_model_settings_models,  # noqa: F401
    )
    from miy_api.domains.ai.runtime import models as ai_runtime_models  # noqa: F401
    from miy_api.domains.ai_artifacts import models as ai_artifact_models  # noqa: F401
    from miy_api.domains.ai_graph import models as ai_graph_models  # noqa: F401
    from miy_api.domains.announcements import models as announcements_models  # noqa: F401
    from miy_api.domains.auth import app_access_models as app_access_models  # noqa: F401
    from miy_api.domains.auth import models as auth_models  # noqa: F401
    from miy_api.domains.bento import models as bento_models  # noqa: F401
    from miy_api.domains.community import models as community_models  # noqa: F401
    from miy_api.domains.conversations import (  # noqa: F401
        models as conversations_models,
    )
    from miy_api.domains.diagrams import models as diagrams_models  # noqa: F401
    from miy_api.domains.dm import models as dm_models  # noqa: F401
    from miy_api.domains.docs import models as docs_models  # noqa: F401
    from miy_api.domains.files import models as files_models  # noqa: F401
    from miy_api.domains.groups import models as group_models  # noqa: F401
    from miy_api.domains.hermes import models as hermes_models  # noqa: F401
    from miy_api.domains.hermes_terminal import (  # noqa: F401
        models as hermes_terminal_models,
    )
    from miy_api.domains.integrations import models as integration_models  # noqa: F401
    from miy_api.domains.independent_apps import models as independent_app_models  # noqa: F401
    from miy_api.domains.independent_apps import delivery_models as independent_delivery_models  # noqa: F401
    from miy_api.domains.independent_apps import bootstrap_models as independent_bootstrap_models  # noqa: F401
    from miy_api.domains.independent_apps import (
        registration_models as independent_registration_models,  # noqa: F401
    )
    from miy_api.domains.mail import models as mail_models  # noqa: F401
    from miy_api.domains.official_apps import models as official_app_models  # noqa: F401
    from miy_api.domains.official_apps import writer_models as official_writer_models  # noqa: F401
    from miy_api.domains.official_apps import writer_roles as official_writer_roles  # noqa: F401
    from miy_api.domains.official_apps import projection_models as official_projection_models  # noqa: F401
    from miy_api.domains.official_apps import file_extraction_models as file_extraction_models  # noqa: F401
    from miy_api.domains.official_apps import (  # noqa: F401
        file_materialization_effect_models,
    )
    from miy_api.domains.media import models as media_models  # noqa: F401
    from miy_api.domains.meeting import models as meeting_models  # noqa: F401
    from miy_api.domains.personal_widgets import (
        models as personal_widgets_models,  # noqa: F401
    )
    from miy_api.domains.planner import models as planner_models  # noqa: F401
    from miy_api.domains.pms import models as pms_models  # noqa: F401
    from miy_api.domains.pms import space_models as pms_space_models  # noqa: F401
    from miy_api.domains.rag import models as rag_models  # noqa: F401
    from miy_api.domains.recording import models as recording_models  # noqa: F401
    from miy_api.domains.recording import pipeline_models as recording_pipeline_models  # noqa: F401
    from miy_api.domains.official_apps import recording_publication_models  # noqa: F401
    from miy_api.domains.release_notes import models as release_notes_models  # noqa: F401
    from miy_api.domains.retrieval import models as retrieval_models  # noqa: F401
    from miy_api.domains.retrieval import docs_legacy_repair_models as docs_repair_models  # noqa: F401
    from miy_api.domains.search import models as search_models  # noqa: F401
    from miy_api.domains.usage import models as usage_models  # noqa: F401
    from miy_api.domains.video_chat import models as video_chat_models  # noqa: F401
    from miy_api.domains.whiteboard import models as whiteboard_models  # noqa: F401
    import miy_api.domains.official_apps.whiteboard_checked_models  # noqa: F401
