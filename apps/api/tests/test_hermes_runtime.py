from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from uuid import uuid4

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from miy_api.core.llm_errors import LlmProviderError
from miy_api.domains.auth.models import User
from miy_api.domains.hermes.models import (
    HermesProfileBinding,
    HermesRunProjection,
    HermesSessionBinding,
)
from miy_api.domains.hermes.repository import HermesRunRepository, utcnow_naive


def seed(db):
    user_id = str(uuid4())
    user = User(
        id=user_id,
        login_id=f"test-{user_id[:12]}",
        email=f"{user_id}@example.test",
        full_name="Runtime test",
        password_hash="not-used",
    )
    db.add(user)
    db.flush()
    binding = HermesProfileBinding(
        id=str(uuid4()),
        user_id=user_id,
        profile_name=f"miy-{uuid4().hex}",
        status="active",
        provider="openai",
        model="test",
    )
    db.add(binding)
    db.flush()
    return user, binding


def session_for(db, binding):
    row = HermesSessionBinding(
        id=str(uuid4()),
        user_id=binding.user_id,
        profile_binding_id=binding.id,
        hermes_session_id=f"session-{uuid4().hex}",
    )
    db.add(row)
    db.flush()
    return row


def stage(db, binding, session, **kwargs):
    return HermesRunRepository(db).stage(
        binding=binding,
        session=session,
        input_text="test",
        instructions=None,
        conversation_history=[],
        **kwargs,
    )


def test_database_capacity_is_atomic_across_independent_connections(application_postgres_dsn):
    engine = create_engine(application_postgres_dsn)
    try:
        with Session(engine) as db:
            _, binding = seed(db)
            ids = [stage(db, binding, session_for(db, binding)).id for _ in range(4)]
            db.commit()
        barrier = Barrier(4)

        def claim(run_id):
            with Session(engine) as db:
                barrier.wait(timeout=5)
                result = HermesRunRepository(db).claim_execution(
                    run_id, claim_token=uuid4().hex, lease_seconds=60, max_concurrent_runs=2
                )
                db.commit()
                return result

        with ThreadPoolExecutor(max_workers=4) as pool:
            results = list(pool.map(claim, ids))
        assert sum(result.acquired for result in results) == 2
        assert sum(result.reason == "capacity" for result in results) == 2
    finally:
        engine.dispose()


def test_same_conversation_orders_runs_but_another_session_can_start(application_postgres_dsn):
    engine = create_engine(application_postgres_dsn)
    try:
        with Session(engine) as db:
            _, binding = seed(db)
            session = session_for(db, binding)
            first = stage(db, binding, session)
            second = stage(db, binding, session)
            other = stage(db, binding, session_for(db, binding))
            repo = HermesRunRepository(db)
            assert (
                repo.claim_execution(second.id, claim_token="second", lease_seconds=60).reason
                == "session_busy"
            )
            assert repo.claim_execution(first.id, claim_token="first", lease_seconds=60).acquired
            assert repo.claim_execution(other.id, claim_token="other", lease_seconds=60).acquired
            db.rollback()
    finally:
        engine.dispose()


@pytest.mark.anyio
@pytest.mark.parametrize("remote_accepted,termination", [(True, "cancel"), (False, "timeout")])
async def test_cancel_during_admission_recovers_without_starting_another_run(
    application_postgres_dsn, monkeypatch, remote_accepted, termination
):
    import asyncio

    from sqlalchemy import select
    from sqlalchemy.orm import sessionmaker

    from miy_api.core.llm import (
        LlmPoolConfig,
        LlmTaskContext,
        PolicyDecision,
        ResolvedLlmExecution,
    )
    from miy_api.core.settings import get_settings
    from miy_api.domains.hermes import execution, workloads
    from miy_api.domains.hermes.client import HermesClientError
    from miy_api.domains.hermes.models import HermesDispatchOutbox, HermesRunInput
    from miy_api.domains.hermes.repository import HermesDispatchRepository

    engine = create_engine(application_postgres_dsn)
    factory = sessionmaker(engine, expire_on_commit=False)
    monkeypatch.setattr(workloads, "get_session_factory", lambda: factory)
    monkeypatch.setattr(
        workloads,
        "get_settings",
        lambda: get_settings().model_copy(update={"hermes_enabled": True}),
    )
    entered = asyncio.Event()
    admissions, stops = [], []
    control_available = False

    class Runtime:
        def __init__(self, **kwargs):
            pass

        async def create_run(self, profile, **kwargs):
            admissions.append(kwargs)
            if kwargs.get("cancel_admission"):
                if not control_available:
                    raise HermesClientError(
                        operation="cancel_run_admission",
                        status_code=503,
                        code="synthetic.unavailable",
                        message="Synthetic control outage",
                    )
                return {
                    "run_id": "run_accepted" if remote_accepted else "run_cancelled_reservation",
                    "status": "running" if remote_accepted else "cancelled",
                }
            assert len(admissions) == 1, "Recovery must never invoke native creation again"
            entered.set()
            await asyncio.Event().wait()  # Acceptance response never reaches the caller.

        async def stop_run(self, profile, native_id):
            stops.append(native_id)
            return {"status": "cancelled"}

        async def get_run(self, profile, native_id):
            return {"run_id": native_id, "status": "cancelled", "last_event": "run.cancelled"}

    monkeypatch.setattr(execution, "HermesRuntimeClient", Runtime)
    monkeypatch.setattr(workloads, "runtime_client", Runtime)
    try:
        with factory() as db:
            user, binding = seed(db)
            admit_runtime_apps(db, user.id)
            owner_id, binding_id = user.id, binding.id
            db.commit()

        async def ensure(db, **kwargs):
            return db.get(HermesProfileBinding, binding_id)

        monkeypatch.setattr(workloads, "ensure_profile_binding", ensure)
        config = LlmPoolConfig(
            "local",
            "openai",
            "http://model.test/v1",
            "",
            "test-model",
            "test-model",
            1,
            30,
            requires_credentials=False,
        )
        task = asyncio.create_task(
            workloads.run_workload(
                LlmTaskContext(
                    source="test",
                    task_kind="chatbot",
                    app_id="chatbot",
                    workload_id="chatbot",
                    actor_user_id=owner_id,
                ),
                ResolvedLlmExecution(
                    "local",
                    PolicyDecision("local_only", "local"),
                    config,
                    "test-model",
                    4096,
                    "none",
                ),
                {"messages": [{"role": "user", "content": "test"}]},
                timeout_seconds=0.2 if termination == "timeout" else 30,
            )
        )
        await asyncio.wait_for(entered.wait(), 5)
        if termination == "cancel":
            task.cancel()
        with pytest.raises(asyncio.CancelledError if termination == "cancel" else LlmProviderError):
            await asyncio.wait_for(task, 5)
        assert stops == []
        run_id = admissions[0]["idempotency_key"]
        with factory() as db:
            run = db.get(HermesRunProjection, run_id)
            assert run.status == "stopping" and run.hermes_run_id is None
            assert run.execution_claim_token is None
            assert db.get(HermesRunInput, run_id) is not None
            other = stage(db, db.get(HermesProfileBinding, binding_id), None)
            other_id = other.id
            assert (
                HermesRunRepository(db)
                .claim_execution(
                    other_id, claim_token="other", lease_seconds=60, max_concurrent_runs=1
                )
                .reason
                == "capacity"
            )
            db.commit()
            # Retry exhaustion cannot turn an unconfirmed stop into success/failure.
            execution.mark_hermes_run_terminal_failure(
                db, run_id=run_id, error_code="synthetic.exhausted", error_message="test"
            )
            outbox = db.scalar(
                select(HermesDispatchOutbox).where(HermesDispatchOutbox.run_id == run_id)
            )
            outbox.attempts, outbox.claim_token, outbox.status = 20, "publish", "claimed"
            db.flush()
            HermesDispatchRepository(db).mark_retry(
                outbox.id,
                claim_token="publish",
                error_code="synthetic.exhausted",
                retry_at=utcnow_naive(),
            )
            db.commit()
            assert outbox.status == "pending" and run.status == "stopping"
            # Cleanup remains possible after the execution profile is disabled.
            db.get(HermesProfileBinding, binding_id).status = "disabled"
            db.commit()

        async def recover():
            with factory() as db:
                return await execution.execute_hermes_run(
                    db,
                    run_id=run_id,
                    runtime_base_url="http://hermes.test",
                    api_key="synthetic",
                    request_timeout_seconds=1,
                    lease_seconds=60,
                    max_concurrent_runs=1,
                )

        with pytest.raises(HermesClientError):
            await recover()
        with factory() as db:
            run = db.get(HermesRunProjection, run_id)
            assert run.status == "stopping" and run.execution_claim_token is None
            assert db.get(HermesRunInput, run_id) is not None
        control_available = True
        assert await recover() == "cancelled"
        assert stops == (["run_accepted"] if remote_accepted else [])
        assert len(admissions) == 3
        assert all(
            {k: v for k, v in attempt.items() if k != "cancel_admission"} == admissions[0]
            for attempt in admissions[1:]
        )
        with factory() as db:
            assert db.get(HermesRunProjection, run_id).status == "cancelled"
            assert db.get(HermesRunInput, run_id) is None
            assert (
                HermesRunRepository(db)
                .claim_execution(
                    other_id, claim_token="other", lease_seconds=60, max_concurrent_runs=1
                )
                .acquired
            )
            db.rollback()
    finally:
        engine.dispose()


@pytest.mark.anyio
@pytest.mark.parametrize("claimed", [True])
async def test_public_stop_keeps_a_lost_acceptance_recoverable(application_postgres_dsn, claimed):
    from miy_api.domains.hermes.router import stop_run

    engine = create_engine(application_postgres_dsn)
    try:
        with Session(engine) as db:
            user, binding = seed(db)
            admit_runtime_apps(db, user.id)
            run = stage(db, binding, session_for(db, binding))
            repository = HermesRunRepository(db)
            if claimed:
                assert repository.claim_execution(
                    run.id, claim_token="lost-response", lease_seconds=60
                ).acquired
                repository.release_execution_claim(run.id, claim_token="lost-response")
            db.commit()
            response = await stop_run(run.id, db=db, current_user=user)
            assert response.status == ("stopping" if claimed else "cancelled")
            recovery = repository.claim_execution(run.id, claim_token="recover", lease_seconds=60)
            assert recovery.acquired is claimed
            db.rollback()
    finally:
        engine.dispose()


@pytest.mark.anyio
@pytest.mark.parametrize(
    "mode,contract",
    [
        ("sync", "structured"),
        ("stream", "text"),
        ("sync", "tool_request"),
        ("stream", "tool_result"),
        ("sync", "forced_final"),
        ("stream", "text_missing"),
        ("sync", "provision_failure"),
        ("stream", "execution_failure"),
    ],
)
async def test_workload_uses_durable_dispatch_and_validated_native_submission(
    application_postgres_dsn, monkeypatch, mode, contract
):
    import asyncio
    import json

    from pydantic import SecretStr
    from sqlalchemy import select
    from sqlalchemy.orm import sessionmaker
    from starlette.requests import Request

    from miy_api.core.llm import (
        LlmPoolConfig,
        LlmTaskContext,
        PolicyDecision,
        ResolvedLlmExecution,
    )
    from miy_api.core.settings import get_settings
    from miy_api.domains.auth.app_access_models import AppAccessPolicy
    from miy_api.domains.auth.models import CompanyAppControl
    from miy_api.domains.hermes import execution, mcp_router, workloads
    from miy_api.domains.hermes.client import HermesClientError
    from miy_api.domains.hermes.service import mcp_profile_bearer_secret

    # Model temperatures are policy metadata, not a native output-contract matrix.
    temperature = None

    def unavailable():
        raise HermesClientError(
            operation="fixture",
            status_code=503,
            code="fixture.unavailable",
            message="Synthetic control API outage",
        )

    engine = create_engine(application_postgres_dsn)
    factory = sessionmaker(engine, expire_on_commit=False)
    settings = get_settings().model_copy(
        update={
            "hermes_enabled": True,
            "hermes_mcp_shared_secret": SecretStr("synthetic-workload-mcp-secret"),
        }
    )
    monkeypatch.setattr(workloads, "get_settings", lambda: settings)
    monkeypatch.setattr(mcp_router, "get_settings", lambda: settings)
    monkeypatch.setattr(workloads, "get_session_factory", lambda: factory)
    expected_result = (
        {"value": 42}
        if contract == "structured"
        else {"content": "Application result received"}
        if contract in {"text", "text_missing", "tool_result", "forced_final"}
        else {"tool_calls": [{"name": "fixture.lookup", "arguments": {"value": 42}}]}
    )
    try:
        with factory() as db:
            user, binding = seed(db)
            owner_id, binding_id, profile_name = user.id, binding.id, binding.profile_name
            db.merge(CompanyAppControl(app_id="chatbot", enabled=True))
            db.flush()
            db.merge(AppAccessPolicy(app_id="chatbot", audience="all"))
            db.commit()

        async def ensure(db, **kwargs):
            if contract == "provision_failure":
                unavailable()
            assert kwargs["user"].id == owner_id
            assert kwargs["model_policy"].route == "local"
            assert kwargs["model_policy"].temperature == temperature
            return db.get(HermesProfileBinding, binding_id)

        monkeypatch.setattr(workloads, "ensure_profile_binding", ensure)
        attempts = []
        submissions = []

        class NativeRuntime:
            def __init__(self, **kwargs):
                pass

            async def create_run(self, profile, **kwargs):
                assert profile == profile_name
                assert kwargs["runtime_options"]["miy_policy"]["model"] == "test-model"
                assert kwargs["runtime_options"]["miy_policy"].get("temperature") == temperature
                assert "miy_submit_result" in kwargs["instructions"]
                if contract in {"tool_result", "forced_final"}:
                    assert '"role": "tool"' in kwargs["input_text"]
                    assert "Application evidence" in kwargs["input_text"]
                attempts.append(kwargs["idempotency_key"])
                if contract == "execution_failure":
                    unavailable()
                return {"run_id": "run_native_fixture", "status": "running"}

            async def iter_run_events(self, profile, run_id):
                results = (
                    () if contract == "text_missing" else ({"value": "wrong type"}, expected_result)
                )
                for result in results:
                    body = json.dumps(
                        {
                            "jsonrpc": "2.0",
                            "id": 1,
                            "method": "miy/submit",
                            "params": {"result": result},
                        }
                    ).encode()

                    async def receive():
                        return {"type": "http.request", "body": body, "more_body": False}

                    request = Request(
                        {"type": "http", "method": "POST", "path": "/", "headers": []}, receive
                    )
                    with factory() as db:
                        response = await mcp_router.handle_mcp_request(
                            request,
                            profile=profile,
                            authorization=f"Bearer {mcp_profile_bearer_secret(settings, profile)}",
                            mcp_session_id=None,
                            hermes_run_id=run_id,
                            db=db,
                        )
                        submissions.append(json.loads(response.body)["result"])
                yield {
                    "event": "run.completed",
                    "output": "done",
                    "usage": {"input_tokens": 7, "output_tokens": 3},
                }

        monkeypatch.setattr(execution, "HermesRuntimeClient", NativeRuntime)
        config = LlmPoolConfig(
            "local",
            "openai",
            "http://model.test/v1",
            "",
            "test-model",
            "test-model",
            1,
            30,
            requires_credentials=False,
        )
        context = LlmTaskContext(
            source="test",
            task_kind="chatbot",
            app_id="chatbot",
            workload_id="chatbot",
            actor_user_id=None,
            execution_user_id=owner_id,
            principal_kind="system",
        )
        resolved = ResolvedLlmExecution(
            "local", PolicyDecision("local_only", "local"), config, "test-model", 4096, "none"
        )
        payload = {"messages": [{"role": "user", "content": "Return a validated value"}]}
        if temperature is not None:
            payload["temperature"] = temperature
        options = dict(
            timeout_seconds=10,
            output_schema={
                "type": "object",
                "properties": {"value": {"type": "integer"}},
                "required": ["value"],
                "additionalProperties": False,
            },
        )
        if contract != "structured":
            options.pop("output_schema")
        if contract not in {"text", "text_missing", "structured"}:
            payload["tools"] = [
                {
                    "type": "function",
                    "function": {
                        "name": "fixture.lookup",
                        "parameters": {
                            "type": "object",
                            "properties": {"value": {"type": "integer"}},
                            "required": ["value"],
                            "additionalProperties": False,
                        },
                    },
                }
            ]
            if contract in {"tool_result", "forced_final"}:
                payload["messages"].extend(
                    [
                        {
                            "role": "assistant",
                            "content": None,
                            "tool_calls": [
                                {
                                    "id": "prior-call",
                                    "type": "function",
                                    "function": {
                                        "name": "fixture.lookup",
                                        "arguments": '{"value":42}',
                                    },
                                }
                            ],
                        },
                        {
                            "role": "tool",
                            "tool_call_id": "prior-call",
                            "content": "Application evidence",
                        },
                    ]
                )
            if contract == "forced_final":
                payload.pop("tools")
        if contract.endswith("_failure"):
            with pytest.raises(LlmProviderError) as error:
                if mode == "sync":
                    await asyncio.to_thread(
                        workloads.complete_workload, context, resolved, payload, **options
                    )
                else:
                    async for _ in workloads.stream_workload(context, resolved, payload, **options):
                        pytest.fail("An unavailable provider cannot return successful output")
            assert isinstance(error.value.__cause__, HermesClientError)
            assert error.value.pool == "local" and error.value.provider == "openai"
            assert "Synthetic" not in str(error.value)
            with factory() as db:
                runs = list(
                    db.scalars(
                        select(HermesRunProjection).where(HermesRunProjection.user_id == owner_id)
                    )
                )
                assert len(runs) == (1 if contract == "execution_failure" else 0)
                assert all(run.execution_claim_token is None for run in runs)
            return
        if contract == "text_missing":
            with pytest.raises(LlmProviderError, match="invalid_output"):
                if mode == "sync":
                    await asyncio.to_thread(
                        workloads.complete_workload, context, resolved, payload, **options
                    )
                else:
                    async for _ in workloads.stream_workload(context, resolved, payload, **options):
                        pytest.fail("Unsubmitted text must not become successful output")
            with factory() as db:
                run = db.get(HermesRunProjection, attempts[0])
                assert run.status == "invalid_output" and run.output_payload is None
            return
        if mode == "sync":
            if contract == "structured":
                from miy_api.domains.ai.gateway import AiGatewayRequest, complete_gateway_chat

                # Exercise the public registered facade all the way to durable
                # native submission, rather than mocking complete_workload.
                def complete_registered():
                    with factory() as db:
                        response = complete_gateway_chat(
                            AiGatewayRequest(
                                task_kind="chatbot",
                                workload_id="chatbot",
                                source="test",
                                app="chatbot",
                                principal_kind="system",
                                execution_user_id=owner_id,
                                workload_route="local",
                                workload_config=config,
                                requested_model="test-model",
                                max_tokens=4096,
                                messages=payload["messages"],
                                timeout_seconds=10,
                                output_schema=options["output_schema"],
                            ),
                            db,
                        )
                        return response.response

                result = await asyncio.to_thread(complete_registered)
            else:
                result = await asyncio.to_thread(
                    workloads.complete_workload, context, resolved, payload, **options
                )
        else:
            chunks = [
                chunk
                async for chunk in workloads.stream_workload(context, resolved, payload, **options)
            ]
            result = {"structured_output": chunks[-1].structured_output, "usage": chunks[-2].usage}
            if contract == "tool_request":
                assert chunks[0].kind == "tool_call_start"
                assert chunks[0].tool_name == "fixture.lookup"
                assert chunks[1].tool_call_id == chunks[0].tool_call_id
                assert json.loads(chunks[1].args_delta) == {"value": 42}
                assert chunks[-1].finish_reason == "tool_calls"
            elif contract in {"text", "tool_result", "forced_final"}:
                assert chunks[0].text == "Application result received"
                assert chunks[-1].finish_reason == "stop"
        if mode == "sync" and contract == "tool_request":
            assert result["choices"][0]["finish_reason"] == "tool_calls"
            assert (
                result["choices"][0]["message"]["tool_calls"][0]["function"]["name"]
                == "fixture.lookup"
            )
        if contract == "text":
            assert result["structured_output"] is None
            if mode == "sync":
                assert result["choices"][0]["message"] == expected_result
                assert result["choices"][0]["finish_reason"] == "stop"
        else:
            assert result["structured_output"] == expected_result
        assert result["usage"]["total_tokens"] == 10
        assert len(attempts) == 1
        assert [item["accepted"] for item in submissions] == [False, True]
        assert context.actor_user_id is None
        with factory() as db:
            run = db.scalar(
                select(HermesRunProjection).where(HermesRunProjection.id == attempts[0])
            )
            assert run.user_id == owner_id and run.owner_app_id == "chatbot"
            assert run.status == "completed" and run.allowed_app_ids == []
    finally:
        engine.dispose()


@pytest.mark.anyio
@pytest.mark.parametrize("capacity,occupied,mode", [(1, 1, "sync"), (3, 2, "stream")])
async def test_nested_generation_respects_capacity_without_waiting_for_its_parent(
    application_postgres_dsn, monkeypatch, capacity, occupied, mode
):
    import asyncio

    from sqlalchemy import select
    from sqlalchemy.orm import sessionmaker

    from miy_api.core.llm import (
        LlmPoolConfig,
        LlmTaskContext,
        PolicyDecision,
        ResolvedLlmExecution,
    )
    from miy_api.core.settings import get_settings
    from miy_api.domains.ai.tool_context import (
        ToolExecutionContext,
        bind_tool_execution_context,
    )
    from miy_api.domains.auth.app_access_models import AppAccessPolicy
    from miy_api.domains.auth.models import CompanyAppControl
    from miy_api.domains.hermes import execution, workloads

    engine = create_engine(application_postgres_dsn)
    factory = sessionmaker(engine, expire_on_commit=False)
    settings = get_settings().model_copy(
        update={
            "hermes_enabled": True,
            "hermes_max_concurrent_runs": capacity,
        }
    )
    monkeypatch.setattr(workloads, "get_settings", lambda: settings)
    monkeypatch.setattr(workloads, "get_session_factory", lambda: factory)
    attempts = []
    try:
        with factory() as db:
            user, binding = seed(db)
            owner_id, binding_id = user.id, binding.id
            db.merge(CompanyAppControl(app_id="chatbot", enabled=True))
            db.flush()
            db.merge(AppAccessPolicy(app_id="chatbot", audience="all"))
            parents = [stage(db, binding, session_for(db, binding)) for _ in range(occupied)]
            for parent in parents:
                assert (
                    HermesRunRepository(db)
                    .claim_execution(
                        parent.id,
                        claim_token=parent.id,
                        lease_seconds=60,
                        max_concurrent_runs=capacity,
                    )
                    .acquired
                )
            parent_ids = [parent.id for parent in parents]
            db.commit()

        async def ensure(db, **kwargs):
            return db.get(HermesProfileBinding, binding_id)

        class NativeRuntime:
            def __init__(self, **kwargs):
                pass

            async def create_run(self, profile, **kwargs):
                attempts.append(kwargs["idempotency_key"])
                return {"run_id": "native_nested", "status": "running"}

            async def iter_run_events(self, profile, run_id):
                with factory() as db:
                    run = db.get(HermesRunProjection, attempts[-1])
                    run.output_payload = {"content": "nested result"}
                    db.commit()
                yield {"event": "run.completed", "output": "nested result"}

        monkeypatch.setattr(workloads, "ensure_profile_binding", ensure)
        monkeypatch.setattr(execution, "HermesRuntimeClient", NativeRuntime)
        context = LlmTaskContext(
            source="test",
            task_kind="chatbot",
            app_id="chatbot",
            workload_id="chatbot",
            actor_user_id=owner_id,
        )
        config = LlmPoolConfig(
            "local",
            "openai",
            "http://model.test/v1",
            "",
            "test-model",
            "test-model",
            1,
            30,
            requires_credentials=False,
        )
        resolved = ResolvedLlmExecution(
            "local",
            PolicyDecision("local_only", "local"),
            config,
            "test-model",
            4096,
            "none",
        )

        async def invoke():
            payload = {"messages": [{"role": "user", "content": "Nested generation"}]}
            if mode == "sync":
                return await asyncio.to_thread(
                    workloads.complete_workload,
                    context,
                    resolved,
                    payload,
                    timeout_seconds=10,
                )
            return [
                chunk
                async for chunk in workloads.stream_workload(
                    context,
                    resolved,
                    payload,
                    timeout_seconds=10,
                )
            ]

        with bind_tool_execution_context(
            ToolExecutionContext(
                source="hermes-mcp",
                tool_name="meeting.extract_actions",
                agent_run_id=parent_ids[0],
            )
        ):
            if occupied == capacity:
                with pytest.raises(LlmProviderError, match="ended with failed"):
                    await asyncio.wait_for(invoke(), timeout=3)
            else:
                await asyncio.wait_for(invoke(), timeout=3)
        with factory() as db:
            child = db.scalar(
                select(HermesRunProjection).where(
                    HermesRunProjection.user_id == owner_id,
                    HermesRunProjection.kind == "workload",
                )
            )
            assert child.runtime_options["parent_run_id"] == parent_ids[0]
            assert child.execution_claim_token is None
            if occupied == capacity:
                assert child.status == "failed" and child.error_code == "hermes.nested_capacity"
                assert attempts == []
                for parent_id in parent_ids:
                    parent = db.get(HermesRunProjection, parent_id)
                    assert (
                        parent.status == "dispatching" and parent.execution_claim_token == parent_id
                    )
                    HermesRunRepository(db).append_event(parent_id, {"event": "run.completed"})
                db.commit()
                claim = HermesRunRepository(db).claim_execution(
                    child.id,
                    claim_token="late-outbox",
                    lease_seconds=60,
                    max_concurrent_runs=capacity,
                )
                assert not claim.acquired and claim.reason == "terminal"
            else:
                assert child.status == "completed" and len(attempts) == 1
    finally:
        engine.dispose()


def test_native_tool_budget_is_durable_and_atomic_per_run(application_postgres_dsn, monkeypatch):
    import asyncio
    import json

    from starlette.requests import Request

    from miy_api.domains.ai.registry import AiCapabilityRegistry
    from miy_api.domains.hermes import mcp_router

    registry = AiCapabilityRegistry()
    registry.register_llm_workload(
        workload_id="test.native_web",
        task_kind="test_native_web",
        owner_domain="ai",
        app_id="chatbot",
        description="Native tool admission contract",
        native_tools=("web_search", "web_extract"),
    )
    monkeypatch.setattr(mcp_router, "get_ai_capability_registry", lambda: registry)

    engine = create_engine(application_postgres_dsn)
    try:
        with Session(engine) as db:
            user, binding = seed(db)
            admit_runtime_apps(db, user.id)
            owner_id, binding_id = user.id, binding.id
            run = stage(
                db,
                binding,
                None,
                kind="workload",
                workload_id="test.native_web",
                runtime_options={
                    "native_tools": ["web_search", "terminal"],
                    "native_tool_limit": 1,
                },
            )
            run.status = "running"
            run_id = run.id
            db.commit()

        def identity(db, **kwargs):
            return db.get(HermesProfileBinding, binding_id), db.get(User, owner_id)

        def available(db, **kwargs):
            return None, [], db.get(HermesRunProjection, run_id)

        monkeypatch.setattr(mcp_router, "_resolve_mcp_identity", identity)
        monkeypatch.setattr(mcp_router, "_available_tools", available)
        barrier = Barrier(2)

        def admit(tool, concurrent=False):
            async def call():
                body = json.dumps(
                    {"id": 1, "method": "miy/native_admit", "params": {"tool": tool}}
                ).encode()

                async def receive():
                    return {"type": "http.request", "body": body, "more_body": False}

                with Session(engine) as db:
                    if concurrent:
                        barrier.wait(timeout=5)
                    response = await mcp_router.handle_mcp_request(
                        Request({"type": "http", "headers": []}, receive), profile="fixture", db=db
                    )
                    return json.loads(response.body)

            return asyncio.run(call())

        # Even a persisted tool name cannot grant a tool absent from the registry.
        assert "error" in admit("terminal")
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(lambda _: admit("web_search", True), range(2)))
        assert sorted(r["result"]["accepted"] for r in results) == [False, True]
        assert admit("web_search")["result"]["accepted"] is False
    finally:
        engine.dispose()


def admit_runtime_apps(db, user_id):
    from miy_api.domains.auth.app_access_models import AppAccessPolicy, AppUserGrant
    from miy_api.domains.auth.models import CompanyAppControl

    for app_id in ("chatbot", "mail"):
        db.merge(CompanyAppControl(app_id=app_id, enabled=True))
        db.flush()
        db.merge(AppAccessPolicy(app_id=app_id, audience="selected"))
        db.flush()
        db.merge(AppUserGrant(app_id=app_id, user_id=user_id))
    db.flush()


@pytest.mark.anyio
async def test_run_event_stream_releases_request_connection_before_streaming(
    application_postgres_dsn,
):
    from miy_api.domains.hermes import router

    engine = create_engine(application_postgres_dsn, pool_size=1, max_overflow=0)
    try:
        with Session(engine) as db:
            user, binding = seed(db)
            admit_runtime_apps(db, user.id)
            run = stage(db, binding, session_for(db, binding))
            db.commit()
            stream = router.stream_run_events(run.id, last_event_id=None, db=db, current_user=user)
            try:
                # The stream polls with its own short sessions. Its admission
                # read must not reserve another connection for the SSE lifetime.
                assert not db.in_transaction()
                assert engine.pool.checkedout() == 0
            finally:
                await stream.body_iterator.aclose()
    finally:
        engine.dispose()


@pytest.mark.anyio
@pytest.mark.parametrize("revocation", ["grant", "company", "user"])
async def test_run_reads_and_controls_recheck_current_owner_app_admission(
    application_postgres_dsn, revocation, monkeypatch
):
    from miy_api.domains.auth.app_access_models import AppUserGrant
    from miy_api.domains.auth.models import CompanyAppControl
    from miy_api.domains.hermes import router
    from miy_api.domains.hermes.schemas import HermesApprovalDecision, HermesSteerRequest

    engine = create_engine(application_postgres_dsn)
    try:
        with Session(engine) as db:
            user, binding = seed(db)
            admit_runtime_apps(db, user.id)
            chat = stage(db, binding, session_for(db, binding))
            mail = stage(db, binding, None, kind="workload", owner_app_id="mail")
            mail.output_payload = {"private_mail_result": "synthetic"}
            mail.hermes_run_id = "native-mail-run"
            db.commit()
            assert (
                router.get_run(mail.id, db=db, current_user=user).output_payload
                == mail.output_payload
            )
            stream = router.stream_run_events(mail.id, last_event_id=None, db=db, current_user=user)
            await stream.body_iterator.aclose()
            before = router.list_runs(None, None, 100, 0, db, user)
            assert before.total == 2
            assert {row.id for row in before.data} == {chat.id, mail.id}
            if revocation == "grant":
                db.delete(db.get(AppUserGrant, ("mail", user.id)))
            elif revocation == "company":
                db.get(CompanyAppControl, "mail").enabled = False
            else:
                user.login_blocked = True
            db.commit()
            page = router.list_runs(None, None, 1, 0, db, user)
            assert page.total == (0 if revocation == "user" else 1)
            assert [row.id for row in page.data] == ([] if revocation == "user" else [chat.id])
            assert router.list_runs(None, None, 1, 1, db, user).data == []
            for read in (router.get_run, router.stream_run_events):
                with pytest.raises(HTTPException) as denied:
                    read(mail.id, db=db, current_user=user)
                assert denied.value.status_code == 404
            monkeypatch.setattr(
                router, "runtime_client", lambda: pytest.fail("Denied control reached Hermes")
            )
            for control, kwargs in (
                (router.stop_run, {}),
                (router.steer_run, {"body": HermesSteerRequest(input="change")}),
                (
                    router.resolve_approval,
                    {"body": HermesApprovalDecision(request_id="pending", choice="once")},
                ),
            ):
                with pytest.raises(HTTPException) as denied:
                    await control(mail.id, db=db, current_user=user, **kwargs)
                assert denied.value.status_code == 404
            db.refresh(mail)
            assert mail.status == "pending"
    finally:
        engine.dispose()


@pytest.mark.anyio
@pytest.mark.parametrize("revoked_app", ["chatbot"])
async def test_open_run_stream_stops_before_next_batch_after_app_revocation(
    application_postgres_dsn, monkeypatch, revoked_app
):
    from sqlalchemy.orm import sessionmaker

    from miy_api.domains.auth.models import CompanyAppControl
    from miy_api.domains.hermes import router

    engine = create_engine(application_postgres_dsn)
    try:
        with Session(engine) as db:
            user, binding = seed(db)
            admit_runtime_apps(db, user.id)
            run = stage(db, binding, None, kind="workload", owner_app_id="mail")
            repo = HermesRunRepository(db)
            repo.append_event(run.id, {"event": "run.progress", "message": "before revocation"})
            db.commit()
            initial_events = repo.list_events_after(run.id, after_sequence=0)
            monkeypatch.setattr(router, "get_session_factory", lambda: sessionmaker(engine))
            stream = router._event_stream(run_id=run.id, user_id=user.id, after_sequence=0)
            for event in initial_events:
                assert f"id: {event.sequence}\n" in await anext(stream)
            with Session(engine) as authority:
                authority.get(CompanyAppControl, revoked_app).enabled = False
                HermesRunRepository(authority).append_event(
                    run.id, {"event": "run.progress", "message": "private result after revocation"}
                )
                authority.commit()
            assert await anext(stream) == 'event: error\ndata: {"code":"hermes.access_revoked"}\n\n'
            with pytest.raises(StopAsyncIteration):
                await anext(stream)
    finally:
        engine.dispose()


@pytest.mark.anyio
@pytest.mark.parametrize("saturation", ["both"])
async def test_structured_callback_completes_while_callers_exhaust_thread_capacity(
    application_postgres_dsn, monkeypatch, saturation
):
    import asyncio
    import threading

    from anyio import CapacityLimiter, to_thread
    from fastapi import FastAPI
    from httpx import ASGITransport, AsyncClient
    from pydantic import SecretStr
    from sqlalchemy.orm import sessionmaker

    from miy_api.core.settings import get_settings
    from miy_api.domains.hermes import mcp_router
    from miy_api.domains.hermes.service import mcp_profile_bearer_secret

    engine = create_engine(application_postgres_dsn)
    factory = sessionmaker(engine)
    monkeypatch.setattr(mcp_router, "get_session_factory", lambda: factory)
    settings = get_settings().model_copy(
        update={"hermes_mcp_shared_secret": SecretStr("synthetic-capacity-secret")}
    )
    monkeypatch.setattr(mcp_router, "get_settings", lambda: settings)
    default = to_thread.current_default_thread_limiter()
    previous_tokens = default.total_tokens
    default.total_tokens = 1
    operation_token = mcp_router._OPERATION_THREADS.set(CapacityLimiter(1))
    release = threading.Event()
    waiters = []

    def hold(entered):
        entered.set()
        assert release.wait(timeout=5), "Callback could not release waiting callers"

    try:
        with factory() as db:
            user, binding = seed(db)
            admit_runtime_apps(db, user.id)
            run = stage(
                db,
                binding,
                None,
                kind="workload",
                workload_id="chatbot",
                output_schema={
                    "type": "object",
                    "properties": {"value": {"type": "integer"}},
                    "required": ["value"],
                    "additionalProperties": False,
                },
            )
            run.hermes_run_id = "run_saturated_callback"
            run.status = "running"
            db.commit()
            run_id, profile = run.id, binding.profile_name
            token = mcp_profile_bearer_secret(settings, profile)
        for kind in ("default", "operations") if saturation == "both" else (saturation,):
            entered = threading.Event()
            call = (
                to_thread.run_sync(hold, entered)
                if kind == "default"
                else mcp_router._run_callback(hold, entered, operation=True)
            )
            waiters.append(asyncio.create_task(call))
            assert await asyncio.to_thread(entered.wait, 1)
        app = FastAPI()
        app.include_router(mcp_router.router)
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await asyncio.wait_for(
                client.post(
                    f"/internal/hermes/mcp?profile={profile}",
                    headers={
                        "Authorization": f"Bearer {token}",
                        "X-Hermes-Run-Id": "run_saturated_callback",
                    },
                    json={"id": 1, "method": "miy/submit", "params": {"result": {"value": 42}}},
                ),
                timeout=2,
            )
            assert response.status_code == 200
            assert response.json()["result"] == {"accepted": True}
        with factory() as db:
            assert db.get(HermesRunProjection, run_id).output_payload == {"value": 42}
        assert all(not task.done() for task in waiters)
    finally:
        release.set()
        await asyncio.gather(*waiters)
        default.total_tokens = previous_tokens
        mcp_router._OPERATION_THREADS.reset(operation_token)
        engine.dispose()
