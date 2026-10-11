from __future__ import annotations

from miy_api.api_composition import RouterSpec
from miy_api.domains.dm.router import router as dm_router
from miy_api.domains.notifications.router import router as notifications_router
from miy_api.domains.personal_widgets.router import router as personal_widgets_router
from miy_api.domains.docs.router import router as docs_router
from miy_api.domains.docs.group_sharing import router as docs_group_sharing_router
from miy_api.domains.whiteboard.router import router as whiteboard_router
from miy_api.domains.whiteboard.group_sharing import router as whiteboard_group_sharing_router
from miy_api.domains.bento.router import router as bento_router
from miy_api.domains.diagrams.router import router as diagrams_router
from miy_api.domains.docs.router import ws_router as docs_ws_router
from miy_api.domains.whiteboard.router import ws_router as whiteboard_ws_router
from miy_api.domains.files.router import router as files_router
from miy_api.domains.pms.router import router as pms_router
from miy_api.domains.pms.group_bindings import router as pms_group_bindings_router
from miy_api.domains.meeting.router import router as meeting_router
from miy_api.domains.video_chat.router import router as video_chat_router
from miy_api.domains.recording.router import router as recording_router
from miy_api.domains.calendar.router import router as calendar_router
from miy_api.domains.community.router import router as community_router
from miy_api.domains.planner.router import router as planner_router
from miy_api.domains.announcements.router import router as announcements_router
from miy_api.domains.mail.router import router as mail_router


def official_router_specs() -> tuple[RouterSpec, ...]:
    return (
        RouterSpec(dm_router, "protected", 21, "official", "miy_api.domains.dm.router"),
        RouterSpec(
            notifications_router,
            "protected",
            25,
            "official",
            "miy_api.domains.notifications.router",
        ),
        RouterSpec(
            personal_widgets_router,
            "protected",
            26,
            "official",
            "miy_api.domains.personal_widgets.router",
        ),
        RouterSpec(docs_router, "protected", 27, "official", "miy_api.domains.docs.router", "docs"),
        RouterSpec(
            docs_group_sharing_router,
            "protected",
            28,
            "official",
            "miy_api.domains.docs.group_sharing",
            "docs",
        ),
        RouterSpec(
            whiteboard_router,
            "protected",
            29,
            "official",
            "miy_api.domains.whiteboard.router",
            "whiteboard",
        ),
        RouterSpec(
            whiteboard_group_sharing_router,
            "protected",
            30,
            "official",
            "miy_api.domains.whiteboard.group_sharing",
            "whiteboard",
        ),
        RouterSpec(
            bento_router, "protected", 31, "official", "miy_api.domains.bento.router", "bento"
        ),
        RouterSpec(
            diagrams_router,
            "protected",
            32,
            "official",
            "miy_api.domains.diagrams.router",
            "diagrams",
        ),
        RouterSpec(docs_ws_router, "public", 33, "official", "miy_api.domains.docs.router"),
        RouterSpec(
            whiteboard_ws_router, "public", 34, "official", "miy_api.domains.whiteboard.router"
        ),
        RouterSpec(
            files_router, "protected", 35, "official", "miy_api.domains.files.router", "files"
        ),
        RouterSpec(pms_router, "protected", 41, "official", "miy_api.domains.pms.router", "pms"),
        RouterSpec(
            pms_group_bindings_router,
            "protected",
            42,
            "official",
            "miy_api.domains.pms.group_bindings",
            "pms",
        ),
        RouterSpec(
            meeting_router, "protected", 43, "official", "miy_api.domains.meeting.router", "meeting"
        ),
        RouterSpec(
            video_chat_router,
            "protected",
            44,
            "official",
            "miy_api.domains.video_chat.router",
            "video-chat",
        ),
        RouterSpec(
            recording_router,
            "protected",
            45,
            "official",
            "miy_api.domains.recording.router",
            "recording",
        ),
        RouterSpec(calendar_router, "protected", 46, "official", "miy_api.domains.calendar.router"),
        RouterSpec(
            community_router,
            "protected",
            47,
            "official",
            "miy_api.domains.community.router",
            "community",
        ),
        RouterSpec(
            planner_router, "protected", 48, "official", "miy_api.domains.planner.router", "planner"
        ),
        RouterSpec(
            announcements_router,
            "protected",
            49,
            "official",
            "miy_api.domains.announcements.router",
        ),
        RouterSpec(mail_router, "protected", 52, "official", "miy_api.domains.mail.router", "mail"),
    )
