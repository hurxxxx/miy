"""Project native async questions; deliver answers through ordinary user input."""

from pydantic import TypeAdapter, ValidationError
from sqlalchemy import func, select

from . import store
from .errors import ConsoleError
from .models import AsyncQuestion, Operation
from .schemas import AsyncQuestionPrompt

OPEN = ("pending", "unconfirmed", "sending", "uncertain")


def observe(db, task, turn_id, item, *, recovered=False):
    if item.get("type") != "agentMessage" or not item.get("questions") or not task.thread_id:
        return
    try:
        questions = TypeAdapter(list[AsyncQuestionPrompt]).validate_python(item["questions"])
    except ValidationError:
        return
    if not 1 <= len(questions) <= 10 or any(
        any(not option or len(option) > 2000 for option in (q.options or [])) for q in questions
    ):
        return
    row = db.scalar(
        select(AsyncQuestion).where(
            AsyncQuestion.task_id == task.id, AsyncQuestion.item_id == item["id"]
        )
    )
    if row:
        return  # History refreshes never reopen answered/dismissed questions.
    stage = "implement" if task.stage in {"implement", "review"} else "plan"
    if recovered and task.turn_id != turn_id:
        stage = "plan"  # Historical permissions cannot be inferred from today's task.
    row = AsyncQuestion(
        task_id=task.id,
        thread_id=task.thread_id,
        turn_id=turn_id,
        item_id=item["id"],
        questions=[q.model_dump() for q in questions],
        execution={
            "stage": stage,
            "permissions": task.permissions if stage == "implement" else "ask",
            "root": task.root,
            "model": task.model,
            "effort": task.effort,
        },
        state="unconfirmed" if recovered else "pending",
    )
    db.add(row)
    db.flush()
    store.changed(db, task, "question.pending", details={"question_id": row.id})


def state(db, row):
    operation = db.get(Operation, row.id)
    if operation and operation.state == "accepted":
        return "answered"
    if operation and operation.state in {"submitting", "uncertain", "pending"}:
        return "uncertain"
    if row.state in {"sending", "uncertain"} and operation and operation.state == "failed":
        return "pending"
    if row.state == "sending" and operation is None:
        return "pending"
    return row.state


def pending_condition():
    return (
        AsyncQuestion.state.in_(OPEN),
        ~select(Operation.id)
        .where(Operation.id == AsyncQuestion.id, Operation.state == "accepted")
        .exists(),
    )


def pending_count(db, task_id):
    return db.scalar(
        select(func.count())
        .select_from(AsyncQuestion)
        .where(AsyncQuestion.task_id == task_id, *pending_condition())
    )


def output(db, task_id):
    return [
        dict(
            id=q.id,
            item_id=q.item_id,
            turn_id=q.turn_id,
            questions=q.questions,
            state=state(db, q),
            answers=q.answers,
        )
        for q in db.scalars(
            select(AsyncQuestion)
            .where(AsyncQuestion.task_id == task_id)
            .order_by(AsyncQuestion.created_at, AsyncQuestion.id)
        )
    ]


def require(db, task_id, question_id):
    row = db.get(AsyncQuestion, question_id)
    if not row or row.task_id != task_id:
        raise ConsoleError("request_expired", 409)
    return row


async def answer(runtime, task_id, question_id, body, *, session_hash):
    # Separate from the runtime task gate: submit/steer own that gate themselves.
    async with runtime.task_gate("question:" + question_id):
        with runtime.factory.begin() as db:
            from .registration import turn_owner

            task = runtime.require_task(db, task_id)
            turn_owner(db, task, session_hash)
            runtime.require_allowed_task(task)
            row = require(db, task_id, question_id)
            current = state(db, row)
            if body.action == "dismiss":
                if current in {"sending", "uncertain"}:
                    raise ConsoleError("codex_request_uncertain", 409)
                if current != "answered":
                    row.state = "dismissed"
                    store.changed(db, task, "question.dismissed", details={"question_id": row.id})
                return
            answers = body.answers or {}
            if set(answers) != {str(i) for i in range(len(row.questions))} or any(
                len(values) != 1 or not values[0].strip() or len(values[0]) > 8000
                for values in answers.values()
            ):
                raise ConsoleError("invalid_answer", 422)
            if current == "answered":
                if row.answers != answers:
                    raise ConsoleError("duplicate_request", 409)
                return
            if current in {"sending", "uncertain", "dismissed"}:
                raise ConsoleError(
                    "request_expired" if current == "dismissed" else "codex_request_uncertain", 409
                )
            if row.thread_id != task.thread_id or row.execution["root"] != task.root:
                raise ConsoleError("thread_unavailable", 409)
            if row.answers is not None and row.answers != answers and db.get(Operation, row.id):
                raise ConsoleError("duplicate_request", 409)
            row.answers, row.state = answers, "sending"
            execution = dict(row.execution)
            active_turn = task.turn_id if task.status in {"running", "waiting"} else None
            text = "Answers to Codex questions:\n\n" + "\n\n".join(
                q["title"] + "\n" + answers[str(i)][0] for i, q in enumerate(row.questions)
            )
            if len(text) > 32000:
                raise ConsoleError("invalid_answer", 422)
            store.changed(db, task, "question.sending", details={"question_id": row.id})
        try:
            if active_turn:
                await runtime.steer(
                    task_id,
                    question_id,
                    text,
                    expected_turn_id=active_turn,
                    submission_digest=runtime.start_digest(
                        task_id,
                        text,
                        execution["stage"],
                        None,
                        (),
                        execution["model"],
                        execution["effort"],
                        execution["permissions"],
                    ),
                    registration_session_hash=session_hash,
                )
            else:
                await runtime.submit(
                    task_id,
                    question_id,
                    text,
                    execution["stage"],
                    model=execution["model"],
                    effort=execution["effort"],
                    permissions=execution["permissions"],
                    registration_session_hash=session_hash,
                )
        except BaseException:
            with runtime.factory.begin() as db:
                row = require(db, task_id, question_id)
                operation = db.get(Operation, question_id)
                row.state = (
                    "answered"
                    if operation and operation.state == "accepted"
                    else "uncertain"
                    if operation and operation.state != "failed"
                    else "pending"
                )
                store.changed(
                    db,
                    store.require_task(db, task_id),
                    "question.delivery_failed",
                    details={"question_id": row.id},
                )
            raise
        with runtime.factory.begin() as db:
            require(db, task_id, question_id).state = "answered"
            store.changed(
                db,
                store.require_task(db, task_id),
                "question.answered",
                details={"question_id": question_id},
            )
