from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from miy_api.domains.auth.models import utcnow_naive
from miy_api.domains.retrieval.models import (
    RetrievalPartition,
    RetrievalProjectionEvent,
    RetrievalProjectionGeneration,
)
from miy_api.domains.retrieval.projection_generations import (
    RetrievalProjectionGenerationError,
    complete_generation_pair_cutover,
    create_projection_generation,
    mark_generation_baselining,
    mark_generation_replaying,
    mark_generation_validating,
    prepare_generation_pair_cutover,
    record_generation_validation,
)


_PARTITION_ID = "d1f35cd5-4fd1-442c-93ed-6a79afe0fa85"


@pytest.fixture
def generation_db() -> Session:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    for table in (
        RetrievalPartition.__table__,
        RetrievalProjectionEvent.__table__,
        RetrievalProjectionGeneration.__table__,
    ):
        table.create(engine)
    db = Session(engine, expire_on_commit=False)
    db.add(
        RetrievalPartition(
            id=_PARTITION_ID,
            source_namespace="generation-test",
            candidate_scope_kind="company",
            is_default_ingest=False,
        )
    )
    db.commit()
    try:
        yield db
    finally:
        db.close()
        engine.dispose()


def _ready_generation(db: Session, *, key: str) -> RetrievalProjectionGeneration:
    return _ready_backend_generation(db, backend="opensearch", key=key)


def _ready_backend_generation(
    db: Session,
    *,
    backend: str,
    key: str,
) -> RetrievalProjectionGeneration:
    schema_version = 3 if backend == "opensearch" else 1
    physical_prefix = "keyword" if backend == "opensearch" else "rag"
    generation = create_projection_generation(
        db,
        backend=backend,
        generation_key=key,
        physical_name=f"{physical_prefix}-v{schema_version}-{key}",
        alias_name=f"{physical_prefix}-live",
        schema_version=schema_version,
    )
    mark_generation_baselining(db, generation_id=generation.id)
    mark_generation_replaying(
        db,
        generation_id=generation.id,
        expected_projection_count=0,
    )
    mark_generation_validating(db, generation_id=generation.id)
    record_generation_validation(
        db,
        generation_id=generation.id,
        passed=True,
        details={"key_set": "passed", "acl_matrix": "passed"},
        content_checksum="a" * 64,
        config_checksum="b" * 64,
    )
    return generation


def _ready_pair(
    db: Session,
    *,
    key: str,
) -> tuple[RetrievalProjectionGeneration, RetrievalProjectionGeneration]:
    return (
        _ready_backend_generation(db, backend="opensearch", key=key),
        _ready_backend_generation(db, backend="qdrant", key=key),
    )


def test_pair_cutover_promotes_both_backends_and_rolls_back_the_previous_pair(
    generation_db: Session,
) -> None:
    first_opensearch, first_qdrant = _ready_pair(generation_db, key="first-pair")
    first_plan = prepare_generation_pair_cutover(
        generation_db,
        opensearch_generation_id=first_opensearch.id,
        qdrant_generation_id=first_qdrant.id,
        writes_quiesced=True,
    )
    complete_generation_pair_cutover(
        generation_db,
        plan=first_plan,
        rollback_expires_at=datetime.now(UTC).replace(tzinfo=None) + timedelta(days=7),
    )

    second_opensearch, second_qdrant = _ready_pair(generation_db, key="second-pair")
    second_plan = prepare_generation_pair_cutover(
        generation_db,
        opensearch_generation_id=second_opensearch.id,
        qdrant_generation_id=second_qdrant.id,
        writes_quiesced=True,
    )
    rollback_expires_at = datetime.now(UTC).replace(tzinfo=None) + timedelta(days=7)
    activated = complete_generation_pair_cutover(
        generation_db,
        plan=second_plan,
        rollback_expires_at=rollback_expires_at,
    )

    assert first_opensearch.state == "rollback"
    assert first_qdrant.state == "rollback"
    assert first_opensearch.rollback_expires_at == rollback_expires_at
    assert first_qdrant.rollback_expires_at == rollback_expires_at
    assert activated.opensearch.state == "active"
    assert activated.qdrant.state == "active"
    assert second_plan.opensearch.previous_generation_id == first_opensearch.id
    assert second_plan.qdrant.previous_generation_id == first_qdrant.id
    assert second_plan.opensearch.alias_name == "keyword-live"
    assert second_plan.opensearch.physical_name == "keyword-v3-second-pair"
    assert second_plan.opensearch.previous_physical_name == "keyword-v3-first-pair"
    assert second_plan.qdrant.alias_name == "rag-live"
    assert second_plan.qdrant.physical_name == "rag-v1-second-pair"
    assert second_plan.qdrant.previous_physical_name == "rag-v1-first-pair"


def test_pair_completion_rechecks_the_watermark_before_promoting(
    generation_db: Session,
) -> None:
    opensearch, qdrant = _ready_pair(generation_db, key="late-event")
    plan = prepare_generation_pair_cutover(
        generation_db,
        opensearch_generation_id=opensearch.id,
        qdrant_generation_id=qdrant.id,
        writes_quiesced=True,
    )
    generation_db.add(
        RetrievalProjectionEvent(
            resource_type="file_manager_file",
            resource_id="file-pair-late",
            projection_version=1,
            retrieval_partition_id=_PARTITION_ID,
            change_kind="content",
            desired_state="active",
            created_at=utcnow_naive(),
        )
    )
    generation_db.flush()

    with pytest.raises(RetrievalProjectionGenerationError, match="checkpoint is behind"):
        complete_generation_pair_cutover(
            generation_db,
            plan=plan,
            rollback_expires_at=datetime.now(UTC).replace(tzinfo=None) + timedelta(days=7),
        )

    assert opensearch.state == "activating"
    assert qdrant.state == "activating"


def test_pair_prepare_and_complete_are_each_atomic_in_the_callers_transaction(
    generation_db: Session,
) -> None:
    first_opensearch, first_qdrant = _ready_pair(generation_db, key="atomic-first")
    first_plan = prepare_generation_pair_cutover(
        generation_db,
        opensearch_generation_id=first_opensearch.id,
        qdrant_generation_id=first_qdrant.id,
        writes_quiesced=True,
    )
    complete_generation_pair_cutover(
        generation_db,
        plan=first_plan,
        rollback_expires_at=datetime.now(UTC).replace(tzinfo=None) + timedelta(days=7),
    )
    generation_db.commit()

    second_opensearch, second_qdrant = _ready_pair(generation_db, key="atomic-second")
    generation_db.commit()
    prepare_generation_pair_cutover(
        generation_db,
        opensearch_generation_id=second_opensearch.id,
        qdrant_generation_id=second_qdrant.id,
        writes_quiesced=True,
    )
    generation_db.rollback()

    assert generation_db.get(RetrievalProjectionGeneration, second_opensearch.id).state == "ready"
    assert generation_db.get(RetrievalProjectionGeneration, second_qdrant.id).state == "ready"

    second_plan = prepare_generation_pair_cutover(
        generation_db,
        opensearch_generation_id=second_opensearch.id,
        qdrant_generation_id=second_qdrant.id,
        writes_quiesced=True,
    )
    generation_db.commit()
    complete_generation_pair_cutover(
        generation_db,
        plan=second_plan,
        rollback_expires_at=datetime.now(UTC).replace(tzinfo=None) + timedelta(days=7),
    )
    generation_db.rollback()

    assert generation_db.get(RetrievalProjectionGeneration, first_opensearch.id).state == "active"
    assert generation_db.get(RetrievalProjectionGeneration, first_qdrant.id).state == "active"
    assert (
        generation_db.get(RetrievalProjectionGeneration, second_opensearch.id).state == "activating"
    )
    assert generation_db.get(RetrievalProjectionGeneration, second_qdrant.id).state == "activating"
