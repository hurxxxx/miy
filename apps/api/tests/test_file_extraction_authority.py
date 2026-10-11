"""Fixed extraction transport on actual restricted disposable Source principals."""

import json
from hashlib import sha256
from types import SimpleNamespace
from uuid import uuid4

import pytest
from sqlalchemy.orm import Session

from _migration_revision_fixtures import migration_revision_world
from test_independent_app_data import isolated_data_cluster as isolated_data_cluster
from test_official_writer_roles import (
    ACTIVE as ACTIVE,
    activate as activate,
    move as move,
    role_template as role_template,
    world as current_head_world,  # noqa: F401
)
from miy_api.domains.files.models import FileManagerFile
from miy_api.domains.official_apps.file_extraction_roles import (
    install_file_extraction_guard,
    prepare_file_extraction_principal,
)
from miy_api.domains.official_apps.projection_contracts import ProjectionIntent
from miy_api.domains.official_apps.projection_outbox import append_projection_intent
from miy_api.domains.official_apps.writer import WriterIdentity
from miy_api.domains.official_apps.writer_contracts import SUITE_SCOPE
from miy_api.domains.retrieval.partitioning import ensure_default_partition

POLICY = "files-retrieval-v2/local-only-10m-v1"


@pytest.fixture
def world(current_head_world, request, tmp_path, monkeypatch):  # noqa: F811
    return migration_revision_world(
        current_head_world,
        request,
        tmp_path,
        monkeypatch,
        expected_revision="file_effect_20261007",
    )


@pytest.fixture
def extraction_prepared(world):
    old_source, _, _ = activate(world)
    # Allocation is a separate privileged Core setup, never a Source grant.
    with Session(world.engine) as db:
        partition = str(
            ensure_default_partition(
                db, source_namespace="files", candidate_scope_kind="company"
            ).id
        )
        db.commit()
    drain = move(world, ACTIVE, "active", state="draining", artifact=ACTIVE.artifact)
    owner = world.role(login=False)
    with Session(world.engine) as db:
        install_file_extraction_guard(db, world.actor, guard_owner=owner, expected=drain)
        db.commit()
    source = world.role()
    identity = WriterIdentity(SUITE_SCOPE, "legacy", drain.generation + 1, "sha256:" + "c" * 64)
    with Session(world.engine) as db:
        prepared = prepare_file_extraction_principal(
            db,
            world.actor,
            role_name=source,
            identity=identity,
            expected=drain,
            expected_state="draining",
        )
        assert prepared.profile_prepared
        source_oid = prepared.principal.role_oid
        db.commit()
    assert move(world, drain, "draining", state="active", artifact=identity.artifact) == identity
    return SimpleNamespace(
        source=source,
        old_source=old_source,
        owner=owner,
        identity=identity,
        partition=partition,
        source_oid=source_oid,
    )


def compact(value):
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False
    )


def seeded_request(world, prepared):
    identifier = str(uuid4())
    # Genuine Source initial pending intent is established independently before prepare.
    from test_file_projection_roles import reader_engine

    engine = reader_engine(world, prepared.source)
    try:
        with Session(engine) as db:
            file = FileManagerFile(
                id=identifier,
                owner_id=world.user_id,
                filename="Synthetic.txt",
                content_type="text/plain",
                size_bytes=14,
                storage_key="synthetic-owned/" + identifier,
                visibility="private",
                retrieval_partition_id=prepared.partition,
                extraction_status="pending",
                extraction_blocks=[],
                extraction_metadata={},
            )
            db.add(file)
            db.flush()
            event = append_projection_intent(
                db,
                intent=ProjectionIntent(
                    resource_type="file_manager_file",
                    resource_id=identifier,
                    retrieval_partition_id=prepared.partition,
                    change_kind="content",
                    desired_state="active",
                    operation="upsert",
                ),
                event_id=uuid4(),
            )
            input_data = dict(
                storage_key=file.storage_key,
                size_bytes=file.size_bytes,
                updated_at=file.updated_at.isoformat(timespec="microseconds"),
                filename=file.filename,
                content_type=file.content_type,
                owner_id=file.owner_id,
                visibility=file.visibility,
                corpus_id=None,
                folder_id=None,
                retrieval_partition_id=prepared.partition,
                source_version=None,
                source_content_checksum=None,
                pending_event_id=str(event.event_id),
                pending_event_digest=event.payload_digest,
            )
            db.commit()
    finally:
        engine.dispose()
    request_id, result_id, event_id = map(str, (uuid4(), uuid4(), uuid4()))
    input_canonical = compact(input_data)
    payload = compact(
        dict(
            protocol_version=1,
            request_id=request_id,
            result_id=result_id,
            event_id=event_id,
            file_id=identifier,
            actor_user_id=world.user_id,
            execution_ref=world.session_id,
            parser_policy=POLICY,
            input_canonical=input_canonical,
        )
    )
    return dict(
        request_id=request_id,
        result_id=result_id,
        event_id=event_id,
        file_id=identifier,
        actor_user_id=world.user_id,
        execution_ref=world.session_id,
        parser_policy=POLICY,
        request_payload=payload,
        request_digest=sha256(payload.encode()).hexdigest(),
        input_fingerprint=sha256(input_canonical.encode()).hexdigest(),
        state="prepared",
    )


def insert_request(conn, values):
    from psycopg import sql

    keys = list(values)
    return conn.execute(
        sql.SQL(
            "INSERT INTO file_extraction_requests ({}) VALUES ({}) RETURNING request_id"
        ).format(
            sql.SQL(",").join(map(sql.Identifier, keys)),
            sql.SQL(",").join([sql.Placeholder()] * len(keys)),
        ),
        list(values.values()),
    ).fetchone()[0]


def bind_request(world, prepared, values):
    token = str(uuid4())
    raw_sha = sha256(b"Synthetic text").hexdigest()
    with world.connect(prepared.source) as conn:
        insert_request(conn, values)
    with world.connect(prepared.source) as conn:
        conn.execute(
            "UPDATE file_extraction_requests SET state='claimed',claim_token=%s WHERE request_id=%s",
            (token, values["request_id"]),
        )
    with world.connect(prepared.source) as conn:
        conn.execute(
            "UPDATE file_extraction_requests SET state='input_bound',input_sha256=%s,input_byte_count=14 WHERE request_id=%s",
            (raw_sha, values["request_id"]),
        )
    return token, raw_sha


def terminal_parts(
    conn,
    values,
    checksum,
    *,
    outcome="ready",
    event=True,
    text_value="Synthetic text",
    metadata=None,
):
    from psycopg.types.json import Json

    content_checksum = checksum if outcome == "ready" else None
    error = (
        None
        if outcome == "ready"
        else "unsupported_source"
        if outcome == "unsupported"
        else "local_parser_failed"
    )
    blocks = (
        [
            {
                "document_id": values["file_id"],
                "block_id": values["file_id"] + ":1",
                "locator_kind": "paragraph",
                "locator_label": "Paragraph1",
                "block_kind": "paragraph",
                "text": "Synthetic text",
            }
        ]
        if outcome == "ready"
        else []
    )
    conn.execute(
        "UPDATE file_manager_files SET extraction_status=%s,extraction_content_checksum=%s,extraction_text=%s,extraction_blocks=%s,extraction_metadata=%s,extraction_error_code=%s,extracted_at=timezone('UTC',clock_timestamp()),updated_at=timezone('UTC',clock_timestamp()) WHERE id=%s",
        (
            outcome,
            content_checksum,
            text_value if outcome == "ready" else None,
            Json(blocks),
            Json(metadata or {}),
            error,
            values["file_id"],
        ),
    )
    if event:
        intent = ProjectionIntent(
            resource_type="file_manager_file",
            resource_id=values["file_id"],
            retrieval_partition_id=json.loads(
                json.loads(values["request_payload"])["input_canonical"]
            )["retrieval_partition_id"],
            change_kind="content" if outcome == "ready" else "delete",
            desired_state="active" if outcome == "ready" else "deleted",
            operation="upsert" if outcome == "ready" else "delete",
            content_checksum=content_checksum,
        )
        revision = (
            conn.execute(
                "SELECT max(source_revision) FROM official_projection_outbox WHERE resource_type='file_manager_file' AND resource_id=%s",
                (values["file_id"],),
            ).fetchone()[0]
            + 1
        )
        conn.execute(
            "INSERT INTO official_projection_outbox(event_id,resource_type,resource_id,source_revision,payload,payload_digest) VALUES(%s,%s,%s,%s,%s,%s)",
            (
                values["event_id"],
                intent.resource_type,
                intent.resource_id,
                revision,
                intent.canonical(),
                intent.digest(),
            ),
        )
    return error


def finish(conn, values, outcome, error=None, *, bad_digest=False):
    digest = conn.execute(
        "SELECT public.miy_file_extraction_result_digest(%s::uuid,%s)",
        (values["request_id"], outcome),
    ).fetchone()[0]
    conn.execute(
        "UPDATE file_extraction_requests SET state=%s,result_digest=%s,error_code=%s WHERE request_id=%s",
        (outcome, "a" * 64 if bad_digest else digest, error, values["request_id"]),
    )
    return digest


@pytest.mark.parametrize("world", ["file_effect_20261007"], indirect=True)
def test_fresh_protocol_downgrade_round_trip_preserves_sources(world):
    from alembic import command
    from test_alembic_migrations import _migration_config

    config = _migration_config(world.engine.url.render_as_string(hide_password=False))
    command.downgrade(config, "official_partition_20261007")
    with world.connect() as conn:
        assert (
            conn.execute("SELECT to_regclass('public.file_extraction_requests')").fetchone()[0]
            is None
        )
        assert (
            conn.execute("SELECT count(*) FROM users WHERE id=%s", (world.user_id,)).fetchone()[0]
            == 1
        )
        assert (
            conn.execute(
                "SELECT count(*) FROM pg_trigger WHERE tgname='miy_official_source_writer'"
            ).fetchone()[0]
            == 90
        )
    command.upgrade(config, "head")
    with world.connect() as conn:
        assert conn.execute("SELECT count(*) FROM file_extraction_requests").fetchone()[0] == 0
        assert (
            conn.execute("SELECT version_num FROM alembic_version").fetchone()[0]
            == "file_effect_20261007"
        )


@pytest.mark.parametrize("operation", ["exact_replay"])
def test_new_profile_preparation_transaction_and_replay(extraction_prepared, world, operation):
    from test_file_projection_roles import grants

    role = extraction_prepared.source if operation == "exact_replay" else world.role()
    before = grants(world, role)
    with world.connect() as conn:
        before_audit = conn.execute("SELECT count(*) FROM audit_logs").fetchone()[0]
    with Session(world.engine) as db:
        result = prepare_file_extraction_principal(
            db,
            world.actor,
            role_name=role,
            identity=extraction_prepared.identity,
            expected=extraction_prepared.identity,
            expected_state="active",
        )
        assert result.profile_prepared
        if operation == "exact_replay":
            db.commit()
        else:
            db.rollback()
    assert grants(world, role) == before
    with world.connect() as conn:
        assert conn.execute("SELECT count(*) FROM audit_logs").fetchone()[0] == before_audit
        assert conn.execute(
            "SELECT count(*) FROM official_writer_principals WHERE role_name=%s", (role,)
        ).fetchone()[0] == (1 if operation == "exact_replay" else 0)
    with world.connect(extraction_prepared.source) as conn:
        import psycopg

        with pytest.raises(psycopg.Error) as caught:
            with conn.transaction():
                conn.execute("SELECT password_hash FROM users")
        assert caught.value.sqlstate == "42501"
        with pytest.raises(psycopg.Error) as caught:
            with conn.transaction():
                conn.execute("SELECT id FROM users FOR SHARE")
        assert caught.value.sqlstate == "42501"
        with pytest.raises(psycopg.Error) as caught:
            with conn.transaction():
                conn.execute(
                    "UPDATE retrieval_projection_heads SET projection_version=projection_version WHERE false"
                )
        assert caught.value.sqlstate == "42501"
        with pytest.raises(psycopg.Error) as caught:
            with conn.transaction():
                conn.execute("DELETE FROM file_extraction_requests WHERE false")
        assert caught.value.sqlstate == "42501"


def add_corpus_input(world, prepared, values, *, metadata=False):
    from test_file_projection_roles import reader_engine
    from miy_api.domains.files.models import FileManagerCorpus, FileManagerFileSourceMetadata

    corpus_id = str(uuid4())
    engine = reader_engine(world, prepared.source)
    try:
        with Session(engine) as db:
            db.add(
                FileManagerCorpus(
                    id=corpus_id,
                    created_by_id=world.user_id,
                    name="Synthetic",
                    access_scope_kind="company",
                    retrieval_partition_id=prepared.partition,
                )
            )
            db.flush()
            file = db.get(FileManagerFile, values["file_id"])
            file.corpus_id = corpus_id
            if metadata:
                db.add(
                    FileManagerFileSourceMetadata(
                        file_id=file.id,
                        corpus_id=corpus_id,
                        external_id="synthetic",
                        external_id_sha256="a" * 64,
                        source_kind="synthetic",
                        source_id="synthetic",
                        source_id_sha256="b" * 64,
                        source_version="synthetic-v1",
                        content_checksum=sha256(b"Synthetic text").hexdigest(),
                        raw_metadata={},
                        acl_resolved=True,
                    )
                )
            db.flush()
            envelope = json.loads(values["request_payload"])
            data = json.loads(envelope["input_canonical"])
            data.update(
                corpus_id=corpus_id,
                updated_at=file.updated_at.isoformat(timespec="microseconds"),
                source_version="synthetic-v1" if metadata else None,
                source_content_checksum=sha256(b"Synthetic text").hexdigest() if metadata else None,
            )
            envelope["input_canonical"] = compact(data)
            values["input_fingerprint"] = sha256(envelope["input_canonical"].encode()).hexdigest()
            values["request_payload"] = compact(envelope)
            values["request_digest"] = sha256(values["request_payload"].encode()).hexdigest()
            db.commit()
    finally:
        engine.dispose()
    return corpus_id


@pytest.mark.parametrize(
    "mutation,mode",
    [("file_update", "after"), ("metadata_checksum", "after"), ("corpus_scope", "after")],
)
def test_actual_immediate_constraints_seal_all_captured_inputs(
    extraction_prepared, world, mutation, mode
):
    import psycopg

    values = seeded_request(world, extraction_prepared)
    corpus_id = add_corpus_input(
        world,
        extraction_prepared,
        values,
        metadata=mutation in {"metadata_version", "metadata_checksum", "metadata_delete"},
    )
    _, checksum = bind_request(world, extraction_prepared, values)
    with world.connect(extraction_prepared.source) as conn:
        with pytest.raises(psycopg.Error) as error:
            with conn.transaction():
                if mode == "before":
                    conn.execute("SET CONSTRAINTS miy_file_extraction_terminal IMMEDIATE")
                terminal_parts(conn, values, checksum)
                finish(conn, values, "ready")
                if mode == "after":
                    conn.execute("SET CONSTRAINTS ALL IMMEDIATE")
                if mutation == "file_update":
                    conn.execute(
                        "UPDATE file_manager_files SET extraction_text='invalid after terminal' WHERE id=%s",
                        (values["file_id"],),
                    )
                elif mutation == "file_delete":
                    conn.execute("DELETE FROM file_manager_files WHERE id=%s", (values["file_id"],))
                elif mutation == "tip":
                    intent = ProjectionIntent(
                        resource_type="file_manager_file",
                        resource_id=values["file_id"],
                        retrieval_partition_id=extraction_prepared.partition,
                        change_kind="delete",
                        desired_state="deleted",
                        operation="delete",
                    )
                    conn.execute(
                        "INSERT INTO official_projection_outbox(event_id,resource_type,resource_id,source_revision,payload,payload_digest) VALUES(%s,%s,%s,3,%s,%s)",
                        (
                            str(uuid4()),
                            intent.resource_type,
                            intent.resource_id,
                            intent.canonical(),
                            intent.digest(),
                        ),
                    )
                elif mutation == "metadata_insert":
                    conn.execute(
                        "INSERT INTO file_manager_file_source_metadata(file_id,corpus_id,external_id,external_id_sha256,source_kind,source_id,source_id_sha256,source_version,content_checksum,raw_metadata,acl_resolved,created_at,updated_at) VALUES(%s,%s,'synthetic',%s,'synthetic','synthetic',%s,'changed',%s,'{}',true,now(),now())",
                        (values["file_id"], corpus_id, "a" * 64, "b" * 64, checksum),
                    )
                elif mutation == "metadata_version":
                    conn.execute(
                        "UPDATE file_manager_file_source_metadata SET source_version='changed' WHERE file_id=%s",
                        (values["file_id"],),
                    )
                elif mutation == "metadata_checksum":
                    conn.execute(
                        "UPDATE file_manager_file_source_metadata SET content_checksum=%s WHERE file_id=%s",
                        ("d" * 64, values["file_id"]),
                    )
                elif mutation == "metadata_delete":
                    conn.execute(
                        "DELETE FROM file_manager_file_source_metadata WHERE file_id=%s",
                        (values["file_id"],),
                    )
                elif mutation == "corpus_partition":
                    conn.execute(
                        "UPDATE file_manager_corpora SET retrieval_partition_id=NULL WHERE id=%s",
                        (corpus_id,),
                    )
                elif mutation == "corpus_scope":
                    conn.execute(
                        "UPDATE file_manager_corpora SET access_scope_kind='owner' WHERE id=%s",
                        (corpus_id,),
                    )
                else:
                    conn.execute("DELETE FROM file_manager_corpora WHERE id=%s", (corpus_id,))
        assert error.value.sqlstate == "55000"
        assert error.value.diag.message_primary == "file_extraction_terminal_transaction_closed"
    with world.connect(extraction_prepared.source) as conn:
        assert conn.execute(
            "SELECT state,result_digest FROM file_extraction_requests WHERE request_id=%s",
            (values["request_id"],),
        ).fetchone() == ("input_bound", None)
        assert (
            conn.execute(
                "SELECT extraction_status FROM file_manager_files WHERE id=%s", (values["file_id"],)
            ).fetchone()[0]
            == "pending"
        )
        assert (
            conn.execute(
                "SELECT count(*) FROM official_projection_outbox WHERE event_id=%s",
                (values["event_id"],),
            ).fetchone()[0]
            == 0
        )
