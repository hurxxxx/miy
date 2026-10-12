import asyncio
from copy import deepcopy
from unittest.mock import AsyncMock

import pytest

from codex_console import native_history
from codex_console.errors import ConsoleError
from codex_console.rpc import MAX_MESSAGE_BYTES, CodexRPC


def run(coro):
    return asyncio.run(coro)


def turn(turn_id="turn-a", status="completed"):
    return {"id": turn_id, "status": status, "items": [], "error": None}


def entry(item_id="item-a", turn_id="turn-a", **values):
    return {"turnId": turn_id, "item": {"id": item_id, "type": "userMessage", **values}}


def test_history_larger_than_a_transport_message_is_preserved_in_small_pages():
    items = [
        entry(f"item-{i}", type="commandExecution", aggregatedOutput="x" * 500_000)
        for i in range(12)
    ]
    calls = []

    async def call(method, params):
        calls.append((method, params))
        if method == "thread/turns/list":
            assert params["itemsView"] == "notLoaded"
            return {"data": [turn()], "nextCursor": None}
        assert params["limit"] == 1
        index = int(params["cursor"] or 0)
        return {"data": [items[index]], "nextCursor": str(index + 1) if index < 11 else None}

    result = run(native_history.hydrate(call, {"id": "thread-a"}, expected_thread_id="thread-a"))
    assert len(result["turns"][0]["items"]) == 12
    assert sum(len(i["aggregatedOutput"]) for i in result["turns"][0]["items"]) > MAX_MESSAGE_BYTES
    assert result["turns"][0]["items"] == [i["item"] for i in items]
    assert len(calls) == 13


def test_turn_order_and_user_message_client_ids_survive_pagination():
    async def call(method, params):
        if method == "thread/turns/list":
            assert params["sortDirection"] == "asc"
            if params["cursor"] is None:
                return {"data": [turn()], "nextCursor": "next-turn"}
            return {"data": [turn("turn-b", "inProgress")], "nextCursor": None}
        return {
            "data": [entry(turn_id=params["turnId"], clientId="original-request")],
            "nextCursor": None,
        }

    result = run(native_history.hydrate(call, {"id": "thread-a"}, expected_thread_id="thread-a"))
    assert [t["id"] for t in result["turns"]] == ["turn-a", "turn-b"]
    assert result["turns"][-1]["status"] == "inProgress"
    assert result["turns"][-1]["items"][0]["clientId"] == "original-request"


@pytest.mark.parametrize("method,params,metadata_field", [
    ("thread/resume", {"threadId": "thread-a"}, "excludeTurns"),
    ("thread/read", {"threadId": "thread-a", "includeTurns": True}, "includeTurns"),
])
def test_classic_rpc_hydrates_metadata_only_history_without_mutating_input(
    method, params, metadata_field
):
    rpc = CodexRPC("codex", None, AsyncMock(), AsyncMock())
    original = deepcopy(params)
    rpc._call = AsyncMock(side_effect=[
        {"thread": {"id": "thread-a", "turns": []}, "sandbox": {"type": "readOnly"}},
        {"data": [turn()], "nextCursor": None},
        {"data": [entry(clientId="request-a")], "nextCursor": None},
    ])
    result = run(rpc.call(method, params))
    first_params = rpc._call.call_args_list[0].args[1]
    assert first_params[metadata_field] is (method == "thread/resume")
    assert params == original
    assert result["sandbox"] == {"type": "readOnly"}
    assert result["thread"]["turns"][0]["items"][0]["clientId"] == "request-a"


@pytest.mark.parametrize("baseline", [False, True])
def test_pinned_remote_controller_keeps_its_existing_history_contract(baseline):
    rpc = CodexRPC("codex", None, AsyncMock(), AsyncMock())
    rpc.sdk_baseline_probe = baseline
    rpc.remote_environment = None if baseline else object()
    rpc._call = AsyncMock(return_value={"thread": {"id": "thread-a", "turns": [turn()]}})
    params = {"threadId": "thread-a"}
    run(rpc.call("thread/resume", params))
    rpc._call.assert_awaited_once_with("thread/resume", params)


@pytest.mark.parametrize("page,code", [
    ({"data": None}, "codex_protocol_error"),
    ({"data": [turn(), turn()]}, "codex_protocol_error"),
    ({"data": [turn(status="unknown")]}, "codex_protocol_error"),
    ({"data": [turn()], "nextCursor": 5}, "codex_protocol_error"),
    ({"data": [turn()], "nextCursor": "x" * 4097}, "codex_protocol_error"),
])
def test_invalid_turn_pages_fail_closed(page, code, monkeypatch):
    monkeypatch.setattr(native_history, "TURN_PAGE_SIZE", 1)

    async def call(method, params):
        return page if method == "thread/turns/list" else {"data": [], "nextCursor": None}

    with pytest.raises(ConsoleError, match=code):
        run(native_history.hydrate(call, {"id": "thread-a"}, expected_thread_id="thread-a"))


def test_repeated_cursor_is_rejected_before_an_unbounded_loop():
    calls = []

    async def call(method, params):
        calls.append(params)
        return {"data": [], "nextCursor": "repeated"}

    with pytest.raises(ConsoleError, match="codex_protocol_error"):
        run(native_history.hydrate(call, {"id": "thread-a"}, expected_thread_id="thread-a"))
    assert len(calls) == 2


@pytest.mark.parametrize("value,code", [
    (entry(turn_id="other-turn"), "codex_thread_mismatch"),
    ({"turnId": "turn-a", "item": None}, "codex_protocol_error"),
    (entry(item_id=""), "codex_protocol_error"),
])
def test_items_must_belong_to_the_requested_turn(value, code):
    async def call(method, params):
        return {"data": [turn()] if method == "thread/turns/list" else [value], "nextCursor": None}

    with pytest.raises(ConsoleError, match=code):
        run(native_history.hydrate(call, {"id": "thread-a"}, expected_thread_id="thread-a"))


@pytest.mark.parametrize("limit", ["MAX_HISTORY_BYTES", "MAX_HISTORY_TURNS", "MAX_HISTORY_ITEMS"])
def test_total_history_budgets_are_enforced(limit, monkeypatch):
    monkeypatch.setattr(native_history, limit, 0)

    async def call(method, params):
        return {
            "data": [turn()] if method == "thread/turns/list" else [entry()],
            "nextCursor": None,
        }

    with pytest.raises(ConsoleError, match="codex_output_limit"):
        run(native_history.hydrate(call, {"id": "thread-a"}, expected_thread_id="thread-a"))


def test_history_timeout_preserves_uncertain_state(monkeypatch):
    monkeypatch.setattr(native_history, "HISTORY_TIMEOUT_SECONDS", 0.01)

    async def call(method, params):
        await asyncio.sleep(1)

    with pytest.raises(ConsoleError, match="codex_request_uncertain"):
        run(native_history.hydrate(call, {"id": "thread-a"}, expected_thread_id="thread-a"))
