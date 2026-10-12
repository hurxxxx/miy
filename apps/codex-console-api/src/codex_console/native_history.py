"""Read native history in bounded pages without changing its thread or turns."""

import asyncio
import json

from .errors import ConsoleError

MAX_HISTORY_BYTES = 64 * 1024 * 1024
MAX_HISTORY_TURNS = 1000
MAX_HISTORY_ITEMS = 20000
HISTORY_TIMEOUT_SECONDS = 60
TURN_PAGE_SIZE = 25


async def hydrate(call, thread, *, expected_thread_id):
    if not isinstance(thread, dict) or thread.get("id") != expected_thread_id:
        raise ConsoleError("codex_thread_mismatch", 503)
    size = 0
    item_count = 0
    turns = []
    turn_ids = set()

    def bounded(value):
        nonlocal size
        size += len(json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode())
        if size > MAX_HISTORY_BYTES:
            raise ConsoleError("codex_output_limit", 503)

    async def pages(method, params, limit):
        cursor = None
        seen = set()
        for _ in range(MAX_HISTORY_ITEMS + MAX_HISTORY_TURNS):
            page = await call(method, {**params, "limit": limit, "cursor": cursor})
            if not isinstance(page, dict) or not isinstance(page.get("data"), list):
                raise ConsoleError("codex_protocol_error", 503)
            bounded(page)
            if len(page["data"]) > limit:
                raise ConsoleError("codex_protocol_error", 503)
            yield page["data"]
            cursor = page.get("nextCursor")
            if cursor is None:
                return
            if (
                not isinstance(cursor, str)
                or not cursor
                or len(cursor.encode()) > 4096
                or cursor in seen
            ):
                raise ConsoleError("codex_protocol_error", 503)
            seen.add(cursor)
        raise ConsoleError("codex_output_limit", 503)

    try:
        async with asyncio.timeout(HISTORY_TIMEOUT_SECONDS):
            bounded(thread)
            async for page in pages(
                "thread/turns/list",
                {"threadId": expected_thread_id, "itemsView": "notLoaded", "sortDirection": "asc"},
                TURN_PAGE_SIZE,
            ):
                for native_turn in page:
                    if (
                        not isinstance(native_turn, dict)
                        or not isinstance(native_turn.get("id"), str)
                        or not native_turn["id"]
                        or native_turn["id"] in turn_ids
                        or native_turn.get("status")
                        not in ("inProgress", "completed", "failed", "interrupted")
                        or native_turn.get("items")
                    ):
                        raise ConsoleError("codex_protocol_error", 503)
                    if len(turns) >= MAX_HISTORY_TURNS:
                        raise ConsoleError("codex_output_limit", 503)
                    turn_ids.add(native_turn["id"])
                    turn = {**native_turn, "items": []}
                    item_ids = set()
                    # One item per response also bounds a turn containing many
                    # individually large command results by the transport limit.
                    async for items in pages(
                        "thread/items/list",
                        {
                            "threadId": expected_thread_id,
                            "turnId": turn["id"],
                            "sortDirection": "asc",
                        },
                        1,
                    ):
                        for entry in items:
                            if not isinstance(entry, dict) or entry.get("turnId") != turn["id"]:
                                raise ConsoleError("codex_thread_mismatch", 503)
                            item = entry.get("item")
                            if (
                                not isinstance(item, dict)
                                or not isinstance(item.get("id"), str)
                                or not item["id"]
                                or item["id"] in item_ids
                                or not isinstance(item.get("type"), str)
                                or not item["type"]
                            ):
                                raise ConsoleError("codex_protocol_error", 503)
                            item_count += 1
                            if item_count > MAX_HISTORY_ITEMS:
                                raise ConsoleError("codex_output_limit", 503)
                            item_ids.add(item["id"])
                            turn["items"].append(item)
                    turns.append(turn)
    except TimeoutError:
        raise ConsoleError("codex_request_uncertain", 503) from None
    return {**thread, "turns": turns}
