from __future__ import annotations

import json
from types import SimpleNamespace

from fastapi.testclient import TestClient
import pytest

from dev_accounts import dev_login
from miy_api.core.llm import LlmCompletionResult
from miy_api.domains.bento import (
    BENTO_EDIT_WORKLOAD_ID,
    BENTO_GENERATE_WORKLOAD_ID,
    BENTO_PLAN_WORKLOAD_ID,
)
from miy_api.domains.bento import generation as bento_generation
from miy_api.domains.bento import router as bento_router
from miy_api.domains.bento.execution import execute_bento_agent_job


def _auth_headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _disable_bento_broker_publish(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        bento_router,
        "publish_pending_graph_dispatches",
        lambda *_args, **_kwargs: 0,
    )


def _complete_bento_job(
    client: TestClient,
    *,
    headers: dict[str, str],
    base: str,
    job_id: str,
) -> dict[str, object]:
    execute_bento_agent_job(job_id)
    response = client.get(f"{base}/ai-jobs/{job_id}", headers=headers)
    assert response.status_code == 200, response.text
    return response.json()


def _document_json(*, title: str, slide_id: str = "slide-1") -> str:
    return json.dumps(
        {
            "format": "bento/slides",
            "version": 1,
            "docId": "doc-1",
            "title": title,
            "size": {"width": 1280, "height": 720},
            "theme": {
                "background": "#FFFFFF",
                "color": "#1E2A3A",
                "accent": "#F7A600",
                "fontFamily": "sans-serif",
            },
            "slides": [
                {
                    "id": slide_id,
                    "background": "#FFFFFF",
                    "transition": "fade",
                    "elements": [],
                    "notes": "",
                }
            ],
            "modified": "2026-08-11T00:00:00Z",
        }
    )


def _generated_document(*, title: str, slide_count: int) -> str:
    return json.dumps(
        {
            "format": "bento/slides",
            "version": 1,
            "docId": "model-controlled-doc-id",
            "title": title,
            "size": {"width": 1280, "height": 720},
            "theme": {
                "background": "#101418",
                "color": "#F2F0EA",
                "accent": "#FF9E8A",
                "fontFamily": "system-ui, sans-serif",
            },
            "slides": [
                {
                    "id": f"slide-{index + 1:02d}",
                    "background": "#101418",
                    "transition": "fade",
                    "notes": f"Speaker guidance for slide {index + 1}",
                    "elements": [
                        {
                            "id": f"title-{index + 1:02d}",
                            "type": "text",
                            "x": 96,
                            "y": 96,
                            "w": 1088,
                            "h": 120,
                            "rotation": 0,
                            "opacity": 1,
                            "html": f"Slide {index + 1}",
                            "fontSize": 64,
                            "fontFamily": "system-ui, sans-serif",
                            "fontWeight": 700,
                            "color": "#F2F0EA",
                            "align": "left",
                            "valign": "top",
                            "lineHeight": 1.1,
                        }
                    ],
                }
                for index in range(slide_count)
            ],
            "modified": "2026-08-11T00:00:00Z",
        }
    )


def _tool_completion(document_json: str) -> LlmCompletionResult:
    return LlmCompletionResult(
        text="",
        model="local/qwen",
        finish_reason="stop",
        structured_output={"document_json": document_json},
    )


def _generated_plan(*, title: str, slide_count: int) -> str:
    return json.dumps(
        {
            "deck_title": title,
            "audience": "General audience",
            "objective": "Explain the topic clearly with editable visuals.",
            "narrative_arc": "Orient, explain, and apply.",
            "visual_system": {
                "mood": "Editorial and precise",
                "background": "#101418",
                "foreground": "#F2F0EA",
                "accent": "#FF9E8A",
                "font_family": "system-ui, sans-serif",
                "motif": "A continuous accent line connects the ideas.",
            },
            "slides": [
                {
                    "index": index + 1,
                    "purpose": f"Advance narrative step {index + 1}.",
                    "headline": f"Planned slide {index + 1}",
                    "key_message": f"Remember idea {index + 1}.",
                    "composition": ("editorial-cover" if index == 0 else "process-flow"),
                    "visual_anchor": "Build a labeled sequence with editable nodes and connectors.",
                    "content": ["First fact", "Second fact"],
                    "element_budget": {
                        "text": 4,
                        "shape": 4,
                        "chart": 0,
                        "table": 0,
                    },
                    "notes": f"Delivery guidance for slide {index + 1}.",
                }
                for index in range(slide_count)
            ],
        }
    )


def _plan_tool_completion(plan_json: str) -> LlmCompletionResult:
    return LlmCompletionResult(
        text="",
        model="local/qwen",
        finish_reason="stop",
        structured_output={"plan_json": plan_json},
    )


def test_bento_private_ownership_company_read_only_and_app_revocation(client: TestClient) -> None:
    administrator = dev_login(client)
    owner = dev_login(client, "delivery-hub-admin")
    member = dev_login(client, "delivery-hub-member")
    base = "/api/v1/bento"

    personal_response = client.post(
        f"{base}/items",
        headers=_auth_headers(owner["token"]),
        json={"title": "Private deck"},
    )
    assert personal_response.status_code == 201, personal_response.text
    personal = personal_response.json()

    company_response = client.post(
        f"{base}/items",
        headers=_auth_headers(owner["token"]),
        json={
            "title": "Shared deck",
            "visibility": "company",
            "company_admin_read_acknowledged": True,
        },
    )
    assert company_response.status_code == 201, company_response.text
    company_document = company_response.json()

    member_hub_response = client.get(
        f"{base}/hub",
        headers=_auth_headers(member["token"]),
    )
    assert member_hub_response.status_code == 200
    member_ids = [item["id"] for item in member_hub_response.json()["items"]]
    assert company_document["id"] in member_ids
    assert personal["id"] not in member_ids

    assert (
        client.get(
            f"{base}/items/{personal['id']}",
            headers=_auth_headers(member["token"]),
        ).status_code
        == 404
    )

    member_update = client.patch(
        f"{base}/items/{company_document['id']}",
        headers=_auth_headers(member["token"]),
        json={
            "version": company_document["version"],
            "document_json": _document_json(title="Shared deck edited"),
        },
    )
    assert member_update.status_code == 403, member_update.text

    member_visibility = client.patch(
        f"{base}/items/{company_document['id']}",
        headers=_auth_headers(member["token"]),
        json={"version": company_document["version"], "visibility": "personal"},
    )
    assert member_visibility.status_code == 403

    member_owned_response = client.post(
        f"{base}/items",
        headers=_auth_headers(member["token"]),
        json={
            "title": "Member deck",
            "visibility": "company",
            "company_admin_read_acknowledged": True,
        },
    )
    assert member_owned_response.status_code == 201, member_owned_response.text
    member_owned = member_owned_response.json()

    admin_visibility = client.patch(
        f"{base}/items/{member_owned['id']}",
        headers=_auth_headers(administrator["token"]),
        json={"version": member_owned["version"], "visibility": "personal"},
    )
    assert admin_visibility.status_code == 403, admin_visibility.text
    admin_read = client.get(
        f"{base}/items/{member_owned['id']}", headers=_auth_headers(administrator["token"])
    )
    assert admin_read.status_code == 200, admin_read.text
    assert admin_read.json()["can_edit"] is False
    assert admin_read.json()["can_manage"] is False
    owner_revert = client.patch(
        f"{base}/items/{member_owned['id']}",
        headers=_auth_headers(member["token"]),
        json={"version": member_owned["version"], "visibility": "personal"},
    )
    assert owner_revert.status_code == 409, owner_revert.text
    assert owner_revert.json()["code"] == "content.company_ownership_irreversible"
    private_member_deck = client.post(
        f"{base}/items", headers=_auth_headers(member["token"]), json={"title": "Member private"}
    )
    assert private_member_deck.status_code == 201, private_member_deck.text
    assert (
        client.get(
            f"{base}/items/{private_member_deck.json()['id']}",
            headers=_auth_headers(administrator["token"]),
        ).status_code
        == 404
    )
    disabled = client.put(
        "/api/v1/admin/apps/bento/access-policy",
        headers=_auth_headers(administrator["token"]),
        json={"enabled": False, "audience": "all", "user_ids": [], "group_ids": []},
    )
    assert disabled.status_code == 200, disabled.text
    for actor in (administrator, owner, member):
        denied = client.get(f"{base}/hub", headers=_auth_headers(actor["token"]))
        assert denied.status_code == 403, denied.text


@pytest.mark.usefixtures("configured_local_llm_control_plane")
def test_bento_ai_generation_uses_registered_local_workload_and_persists_document(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _disable_bento_broker_publish(monkeypatch)
    captured: list[dict[str, object]] = []

    def fake_execute(workload_id, context, db, **kwargs):
        del db
        captured.append(
            {
                "workload_id": workload_id,
                "context": context,
                "messages": kwargs["messages"],
                "temperature": kwargs["temperature"],
                "reasoning_effort": kwargs["reasoning_effort"],
                "stream_reasoning": kwargs["stream_reasoning"],
                "max_tokens": kwargs["max_tokens"],
                "output_schema": kwargs["output_schema"],
            }
        )
        if workload_id == BENTO_PLAN_WORKLOAD_ID:
            return SimpleNamespace(
                completion=_plan_tool_completion(
                    _generated_plan(title="AI launch plan", slide_count=4)
                )
            )
        return SimpleNamespace(
            completion=_tool_completion(_generated_document(title="AI launch plan", slide_count=4))
        )

    monkeypatch.setattr(bento_generation, "execute_llm", fake_execute)
    session = dev_login(client, "delivery-hub-admin")
    response = client.post(
        "/api/v1/bento/items/generate",
        headers=_auth_headers(session["token"]),
        json={
            "prompt": "신제품 출시 제안서를 작성해줘",
            "slide_count": 4,
            "language": "ko",
            "visibility": "personal",
        },
    )

    assert response.status_code == 202, response.text
    job = _complete_bento_job(
        client,
        headers=_auth_headers(session["token"]),
        base="/api/v1/bento",
        job_id=response.json()["id"],
    )
    assert job["status"] == "succeeded"
    created = client.get(
        f"/api/v1/bento/items/{job['result_document_id']}",
        headers=_auth_headers(session["token"]),
    ).json()
    document = json.loads(created["document_json"])
    assert created["title"] == "AI launch plan"
    assert created["visibility"] == "personal"
    assert document["docId"] != "model-controlled-doc-id"
    assert len(document["slides"]) == 4
    title_elements = [slide["elements"][0] for slide in document["slides"]]
    assert {element["role"] for element in title_elements} == {"title"}
    assert {element["morphId"] for element in title_elements} == {"bento-running-title"}
    assert [call["workload_id"] for call in captured] == [
        BENTO_PLAN_WORKLOAD_ID,
        BENTO_GENERATE_WORKLOAD_ID,
    ]
    plan_call, render_call = captured
    assert plan_call["temperature"] == 0.5
    assert plan_call["reasoning_effort"] == "medium"
    assert plan_call["stream_reasoning"] is True
    assert plan_call["max_tokens"] == 16_384
    assert plan_call["context"].source == "api.bento.generate.plan"
    assert plan_call["output_schema"]["required"] == ["plan_json"]
    assert plan_call["output_schema"]["x-miy-slide-count"] == 4
    assert "topic-specific storyboard" in plan_call["messages"][0]["content"]
    assert render_call["temperature"] == 0.5
    assert render_call["reasoning_effort"] == "none"
    assert render_call["stream_reasoning"] is False
    assert render_call["max_tokens"] == 32_768
    assert render_call["context"].app_id == "bento"
    assert render_call["output_schema"]["required"] == ["document_json"]
    assert render_call["output_schema"]["x-miy-slide-count"] == 4
    system_message = render_call["messages"][0]
    assert "Morph is Bento's signature" in system_message["content"]
    assert "Two columns: x=96 and 656" in system_message["content"]
    user_message = render_call["messages"][1]
    render_payload = json.loads(user_message["content"])
    assert render_payload["brief"] == "신제품 출시 제안서를 작성해줘"
    assert render_payload["presentation_plan"]["slides"][1]["composition"] == "process-flow"


@pytest.mark.usefixtures("configured_local_llm_control_plane")
def test_bento_ai_generation_rejects_invalid_model_output_without_creating_document(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _disable_bento_broker_publish(monkeypatch)
    model_calls = 0

    def fake_invalid_execute(workload_id, *_args, **_kwargs):
        nonlocal model_calls
        model_calls += 1
        if workload_id == BENTO_PLAN_WORKLOAD_ID:
            return SimpleNamespace(
                completion=_plan_tool_completion(
                    _generated_plan(title="Invalid output test", slide_count=3)
                )
            )
        return SimpleNamespace(completion=LlmCompletionResult(text="not JSON", model="local/qwen"))

    monkeypatch.setattr(bento_generation, "execute_llm", fake_invalid_execute)
    session = dev_login(client, "delivery-hub-admin")
    headers = _auth_headers(session["token"])
    base = "/api/v1/bento"
    before = client.get(f"{base}/hub", headers=headers).json()["total"]

    response = client.post(
        f"{base}/items/generate",
        headers=headers,
        json={"prompt": "invalid output test", "slide_count": 3},
    )

    assert response.status_code == 202
    job = _complete_bento_job(
        client,
        headers=headers,
        base=base,
        job_id=response.json()["id"],
    )
    assert job["status"] == "failed"
    assert job["error_code"] == "bento.agent.BentoGenerationError"
    assert model_calls == 2
    after = client.get(f"{base}/hub", headers=headers).json()["total"]
    assert after == before


@pytest.mark.usefixtures("configured_local_llm_control_plane")
def test_bento_ai_edit_preserves_document_identity_and_server_owned_fields(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _disable_bento_broker_publish(monkeypatch)
    captured: dict[str, object] = {}

    def fake_execute(workload_id, context, db, **kwargs):
        del db
        captured.update(
            workload_id=workload_id,
            context=context,
            messages=kwargs["messages"],
        )
        return SimpleNamespace(
            completion=_tool_completion(
                _generated_document(title="Revised launch plan", slide_count=1)
            )
        )

    monkeypatch.setattr(bento_generation, "execute_llm", fake_execute)
    current_document = json.loads(_generated_document(title="Original", slide_count=1))
    current_document["docId"] = "stable-document-id"
    current_document["collab"] = {"room": "private-room", "key": "never-send-this"}
    current_document["slides"][0]["comments"] = [
        {"id": "comment-1", "author": "Reviewer", "text": "Keep this", "at": "now"}
    ]

    session = dev_login(client, "delivery-hub-admin")
    headers = _auth_headers(session["token"])
    base = "/api/v1/bento"
    created_response = client.post(
        f"{base}/items",
        headers=headers,
        json={
            "title": "Original",
            "document_json": json.dumps(current_document),
        },
    )
    assert created_response.status_code == 201, created_response.text
    created = created_response.json()

    response = client.post(
        f"{base}/items/{created['id']}/ai-edit",
        headers=headers,
        json={
            "version": created["version"],
            "prompt": "문장을 더 간결하게 수정해줘",
            "language": "ko",
        },
    )

    assert response.status_code == 202, response.text
    job = _complete_bento_job(
        client,
        headers=headers,
        base=base,
        job_id=response.json()["id"],
    )
    revised = client.get(f"{base}/items/{job['result_document_id']}", headers=headers).json()
    revised_document = json.loads(revised["document_json"])
    assert revised["id"] == created["id"]
    assert revised["version"] == created["version"] + 1
    assert revised["title"] == "Revised launch plan"
    assert revised_document["docId"] == "stable-document-id"
    assert revised_document["collab"] == current_document["collab"]
    assert revised_document["slides"][0]["comments"] == current_document["slides"][0]["comments"]
    assert captured["workload_id"] == BENTO_EDIT_WORKLOAD_ID
    model_payload = json.loads(captured["messages"][1]["content"])
    assert model_payload["revision_instruction"] == "문장을 더 간결하게 수정해줘"
    assert "collab" not in model_payload["current_document"]
    assert "comments" not in model_payload["current_document"]["slides"][0]
    title_element = revised_document["slides"][0]["elements"][0]
    assert title_element["role"] == "title"
    assert title_element["morphId"] == "bento-running-title"

    def must_not_execute(*_args, **_kwargs):
        raise AssertionError("stale edit must not call model")

    monkeypatch.setattr(bento_generation, "execute_llm", must_not_execute)
    stale = client.post(
        f"{base}/items/{created['id']}/ai-edit",
        headers=headers,
        json={"version": created["version"], "prompt": "stale", "language": "ko"},
    )
    assert stale.status_code == 409
    assert stale.json()["code"] == "bento.version_conflict"
