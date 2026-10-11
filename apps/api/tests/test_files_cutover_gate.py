from contextlib import contextmanager
from dataclasses import replace
from datetime import UTC, datetime, timedelta
import time
import signal
import os
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace

import pytest
from sqlalchemy import Column, DateTime, MetaData, String, Table, create_engine
from sqlalchemy.orm import sessionmaker

from miy_api.domains.files import cutover_gate as gate
from miy_api.domains.retrieval.files_cutover import FilesRetrievalCutoverStatus
from miy_api.domains.retrieval import files_generation_runner as generation
from miy_api.domains.retrieval.files_quality_judgments import FilesQualityJudgmentSnapshot
from miy_api.domains.search.models import SearchIndexJob
from miy_api.domains.rag.models import RagSyncJob
from miy_api.domains.source_access.resource_types import FILE_MANAGER_FILE_RESOURCE_TYPE
from test_files_generation_runner import (
    _FakeBackends,
    _FakeMaterializer,
    _inventory,
    _loaded_source_snapshot,
    _passing_v3_quality_artifact,
    _quality_corpus_bytes,
    _settings,
    _source_snapshot,
    generation_session_factory as generation_session_factory,
)


@pytest.fixture
def source_factory():
    # Only the read-only columns queried by this gate, without a platform schema
    # or migration claim. Full generation validation uses its existing fixture.
    engine = create_engine("sqlite+pysqlite:///:memory:")
    table = Table(
        "file_manager_files",
        MetaData(),
        Column("id", String, primary_key=True),
        Column("deleted_at", DateTime),
        Column("extraction_status", String),
        Column("extracted_at", DateTime),
    )
    table.create(engine)
    factory = sessionmaker(bind=engine)
    yield factory, table
    engine.dispose()


def _source(source_factory, *, status="ready", stamp=datetime(2026, 1, 1), deleted=False):
    factory, table = source_factory
    with factory.begin() as db:
        db.execute(
            table.insert().values(
                id="synthetic-file",
                extraction_status=status,
                extracted_at=stamp,
                deleted_at=datetime(2026, 1, 2) if deleted else None,
            )
        )
    return factory


def _enabled():
    return SimpleNamespace(rag_enabled=True, files_retrieval_enabled=True)


def _trap(*_args, **_kwargs):
    pytest.fail("inactive/empty/missing-stamp path constructed a verifier or Source session")


@pytest.mark.parametrize("flags", [(False, False), (False, True), (True, False)])
def test_inactive_flags_skip_source_and_backend_construction(flags):
    receipt = gate.check_files_content_cutover(
        settings=SimpleNamespace(rag_enabled=flags[0], files_retrieval_enabled=flags[1]),
        session_factory=_trap,
        verify_active=_trap,
    )
    assert receipt.mode == "inactive"
    assert receipt.gate_version == "files-result-stamp-v1"


def test_empty_means_actual_source_table_empty(source_factory):
    receipt = gate.check_files_content_cutover(
        settings=_enabled(), session_factory=source_factory[0], verify_active=_trap
    )
    assert receipt.mode == "empty_source"


def test_ready_source_without_result_stamp_refuses_before_backend(source_factory):
    factory = _source(source_factory, stamp=None)
    with pytest.raises(gate.FilesContentCutoverRefused) as caught:
        gate.check_files_content_cutover(
            settings=_enabled(), session_factory=factory, verify_active=_trap
        )
    assert caught.value.reason == "source_result_stamp_missing"


@pytest.mark.parametrize("status,deleted", [("pending", False), ("failed", False), ("ready", True)])
def test_nonempty_unready_or_tombstone_source_cannot_use_empty_bypass(
    source_factory, status, deleted
):
    factory = _source(source_factory, status=status, deleted=deleted, stamp=None)
    calls = []

    def verify():
        calls.append("full_inventory")
        return FilesRetrievalCutoverStatus(deployment_enabled=True, ready=False)

    with pytest.raises(gate.FilesContentCutoverRefused) as caught:
        gate.check_files_content_cutover(
            settings=_enabled(), session_factory=factory, verify_active=verify
        )
    assert caught.value.reason == "current_generation_not_ready"
    assert calls == ["full_inventory"]


@pytest.mark.parametrize("bad", [1, "true", None])
def test_flags_require_typed_booleans(bad):
    with pytest.raises(gate.FilesContentCutoverRefused) as caught:
        gate.check_files_content_cutover(
            settings=SimpleNamespace(rag_enabled=bad, files_retrieval_enabled=True),
            session_factory=_trap,
            verify_active=_trap,
        )
    assert caught.value.reason == "configuration_invalid"


@pytest.mark.parametrize("backend", ["opensearch", "qdrant"])
def test_actual_verify_active_blocks_old_unstamped_index_then_accepts_rebuilt_index(
    generation_session_factory, source_factory, monkeypatch, backend
):
    current = _loaded_source_snapshot(extracted_at=datetime(2026, 1, 1, tzinfo=UTC))
    # Reproduce the target branch builders: retain all identity/checksum/text
    # fields but actually omit only metadata.extracted_at from both envelopes.
    search_builder = generation.build_file_search_document
    rag_builder = generation.build_file_rag_projection

    def old_search(**kwargs):
        result = dict(search_builder(**kwargs))
        result["metadata"] = {k: v for k, v in result["metadata"].items() if k != "extracted_at"}
        return result

    def old_rag(**kwargs):
        result = rag_builder(**kwargs)
        return result.model_copy(
            update={"metadata": {k: v for k, v in result.metadata.items() if k != "extracted_at"}}
        )

    with monkeypatch.context() as historical:
        historical.setattr(generation, "build_file_search_document", old_search)
        historical.setattr(generation, "build_file_rag_projection", old_rag)
        old = _loaded_source_snapshot(extracted_at=datetime(2026, 1, 1, tzinfo=UTC))
    assert old.identity_sha256 == current.identity_sha256
    assert old.artifact_sha256 == current.artifact_sha256
    assert old.opensearch_projection_sha256 != current.opensearch_projection_sha256
    assert old.qdrant_projection_sha256 != current.qdrant_projection_sha256
    settings = _settings()
    settings.files_retrieval_enabled = True
    backends = _FakeBackends()
    backends.opensearch = replace(
        _inventory(resources=1),
        identity_sha256=current.identity_sha256,
        projection_sha256=current.opensearch_projection_sha256,
    )
    backends.qdrant = replace(
        _inventory(resources=1, records=current.qdrant_record_count),
        identity_sha256=current.identity_sha256,
        projection_sha256=current.qdrant_projection_sha256,
    )
    materializer = _FakeMaterializer(backends=backends, target_resources=1)
    runner = generation.FilesGenerationRunner(
        session_factory=generation_session_factory,
        settings=settings,
        backends=backends,
        source_snapshot_loader=lambda _db: current,
        materializer=materializer,
        active_release_probe=lambda _db: FilesRetrievalCutoverStatus(
            deployment_enabled=True, ready=True
        ),
        quality_judgment_validator=lambda _corpus: FilesQualityJudgmentSnapshot(
            acl_sha256="6" * 64, context_count=1, active_resource_count=1
        ),
    )
    runner.prepare(
        generation_key="v3-quality",
        baseline_mode=generation.FilesGenerationBaselineMode.ADOPT_PREPARED,
    )
    corpus = _quality_corpus_bytes()
    artifact = _passing_v3_quality_artifact(settings=settings, corpus_bytes=corpus).model_copy(
        update={
            "source_identity_sha256": current.identity_sha256,
            "source_artifact_sha256": current.artifact_sha256,
            "source_acl_envelope_sha256": current.acl_envelope_sha256,
        }
    )
    runner.validate(
        generation_key="v3-quality",
        writes_quiesced=True,
        reconciliation_watermark=0,
        quality_artifact=artifact,
        quality_corpus_bytes=corpus,
    )
    runner.cutover(
        generation_key="v3-quality",
        writes_quiesced=True,
        rollback_window=timedelta(days=7),
        quality_corpus_bytes=corpus,
    )
    factory = _source(source_factory)
    rebuilt = getattr(backends, backend)
    old_digest = getattr(old, backend + "_projection_sha256")
    setattr(backends, backend, replace(rebuilt, projection_sha256=old_digest))
    with pytest.raises(gate.FilesContentCutoverRefused) as caught:
        gate.check_files_content_cutover(
            settings=_enabled(), session_factory=factory, verify_active=runner.verify_active
        )
    assert caught.value.reason == backend + "_projection_content_mismatch"
    # No reindex/embedding is performed by the check. Explicit operator repair
    # is represented only by switching the synthetic inventory to rebuilt data.
    setattr(backends, backend, rebuilt)
    before_aliases = list(backends.alias_operations)
    receipt = gate.check_files_content_cutover(
        settings=_enabled(), session_factory=factory, verify_active=runner.verify_active
    )
    assert receipt.mode == "verified"
    assert backends.alias_operations == before_aliases
    assert materializer.calls == backends.prepare_calls == 0


def test_provider_exception_exposes_only_fixed_code(source_factory):
    factory = _source(source_factory)

    def fail():
        raise RuntimeError("synthetic-private-endpoint-or-body")

    with pytest.raises(gate.FilesContentCutoverRefused) as caught:
        gate.check_files_content_cutover(
            settings=_enabled(), session_factory=factory, verify_active=fail
        )
    assert caught.value.reason == "generation_verification_failed"
    assert caught.value.__cause__ is None
    assert str(caught.value) == "files_content_cutover_refused"


def _cli_composition(monkeypatch, source_factory, *, settings=None, verify=None, close=None):
    import miy_api.core.settings as settings_module
    import miy_api.core.db as db_module
    import miy_api.domains.retrieval.files_generation_backends as backend_module
    import miy_api.domains.retrieval.files_generation_materializer as materializer_module

    calls = []
    monkeypatch.setattr(settings_module, "get_settings", lambda: settings or _enabled())
    monkeypatch.setattr(db_module, "get_session_factory", lambda: source_factory[0])
    monkeypatch.setattr(gate, "_readonly_session", lambda factory: factory())

    class Backend:
        def __init__(self, _settings, *, embedding_dimensions_resolver):
            calls.append("backend")
            self.embedding = embedding_dimensions_resolver

        def close(self):
            calls.append("close")
            if close:
                close()

    class Materializer:
        def __init__(self, **kwargs):
            calls.append("materializer")
            for name in ("keyword_client_factory", "rag_service_factory"):
                with pytest.raises(gate.FilesContentCutoverRefused) as caught:
                    kwargs[name]()
                assert caught.value.reason == "verification_effect_forbidden"

    class Runner:
        def __init__(self, **kwargs):
            calls.append("runner")
            assert kwargs["materializer"].requires_empty_reconciliation is True
            with pytest.raises(gate.FilesContentCutoverRefused):
                kwargs["backends"].embedding(_settings())

        def verify_active(self):
            calls.append("verify")
            return (
                verify()
                if verify
                else FilesRetrievalCutoverStatus(deployment_enabled=True, ready=True)
            )

    monkeypatch.setattr(backend_module, "FilesPhysicalGenerationBackends", Backend)
    monkeypatch.setattr(materializer_module, "FilesCachedProjectionMaterializer", Materializer)
    monkeypatch.setattr(generation, "FilesGenerationRunner", Runner)
    return calls


@pytest.mark.parametrize("backend", ["keyword", "vector"])
@pytest.mark.parametrize("status,deleted", [("unsupported", False), ("ready", True)])
def test_actual_empty_resource_verification_refuses_pending_jobs_then_accepts_drained(
    generation_session_factory, source_factory, backend, status, deleted
):
    engine = generation_session_factory.kw["bind"]
    SearchIndexJob.__table__.create(engine)
    RagSyncJob.__table__.create(engine)
    backends = _FakeBackends()
    runner = generation.FilesGenerationRunner(
        session_factory=generation_session_factory,
        settings=_settings(),
        backends=backends,
        source_snapshot_loader=lambda _db: _source_snapshot(),
        materializer=gate._verification_materializer(
            session_factory=generation_session_factory, settings=_settings()
        ),
        active_release_probe=lambda _db: FilesRetrievalCutoverStatus(
            deployment_enabled=True, ready=True
        ),
    )
    runner.prepare(
        generation_key="empty-ready", baseline_mode=generation.FilesGenerationBaselineMode.EMPTY
    )
    runner.validate(
        generation_key="empty-ready",
        writes_quiesced=True,
        reconciliation_watermark=0,
        allow_empty_non_production=True,
    )
    runner.cutover(
        generation_key="empty-ready", writes_quiesced=True, rollback_window=timedelta(days=7)
    )
    factory = _source(source_factory, status=status, deleted=deleted, stamp=None)
    job = (
        SearchIndexJob(id="synthetic-job", entity_type="file", entity_id="synthetic-file")
        if backend == "keyword"
        else RagSyncJob(
            id="synthetic-job",
            resource_type=FILE_MANAGER_FILE_RESOURCE_TYPE,
            resource_id="synthetic-file",
        )
    )
    with generation_session_factory.begin() as db:
        db.add(job)
    with pytest.raises(gate.FilesContentCutoverRefused) as caught:
        gate.check_files_content_cutover(
            settings=_enabled(), session_factory=factory, verify_active=runner.verify_active
        )
    assert caught.value.reason == "projection_queues_not_drained"
    with generation_session_factory.begin() as db:
        db.get(type(job), "synthetic-job").status = "succeeded"
    assert (
        gate.check_files_content_cutover(
            settings=_enabled(), session_factory=factory, verify_active=runner.verify_active
        ).mode
        == "verified"
    )


@pytest.mark.parametrize("mode", ["inactive", "empty_source"])
def test_cli_bypass_constructs_no_backend_materializer_or_runner(
    source_factory, monkeypatch, capsys, mode
):
    calls = _cli_composition(
        monkeypatch,
        source_factory,
        settings=SimpleNamespace(rag_enabled=False, files_retrieval_enabled=True)
        if mode == "inactive"
        else None,
    )
    assert gate.main([]) == 0
    assert calls == []
    assert capsys.readouterr().out == f"status=ok gate=files-result-stamp-v1 result={mode}\n"


@pytest.mark.parametrize("failure", [None, "provider", "deadline"])
def test_cli_owns_total_deadline_and_bounded_cleanup_preserving_original_result(
    source_factory, monkeypatch, capsys, failure
):
    _source(source_factory)

    def verify():
        if failure == "provider":
            raise RuntimeError("synthetic-private-provider-text")
        if failure == "deadline":
            time.sleep(10)
        return FilesRetrievalCutoverStatus(deployment_enabled=True, ready=True)

    calls = _cli_composition(
        monkeypatch, source_factory, verify=verify, close=lambda: time.sleep(10)
    )
    monkeypatch.setattr(gate, "CHECK_SECONDS", 0.03)
    monkeypatch.setattr(gate, "CLEANUP_SECONDS", 0.03)
    start = time.monotonic()
    assert gate.main([]) == (0 if failure is None else 1)
    assert time.monotonic() - start < 1
    assert calls == ["backend", "materializer", "runner", "verify", "close"]
    output = capsys.readouterr()
    if failure is None:
        assert output.out == "status=ok gate=files-result-stamp-v1 result=verified\n"
    else:
        reason = "deadline_exceeded" if failure == "deadline" else "generation_verification_failed"
        assert output.err == f"status=failed gate=files-result-stamp-v1 reason={reason}\n"
    assert "synthetic-private" not in output.out + output.err


def test_cli_cleanup_base_interruption_keeps_verified_result(source_factory, monkeypatch, capsys):
    _source(source_factory)

    def interrupt():
        raise KeyboardInterrupt()

    _cli_composition(monkeypatch, source_factory, close=interrupt)
    assert gate.main([]) == 0
    assert "result=verified" in capsys.readouterr().out


def test_cli_has_no_force_complete_input(capsys):
    assert gate.main(["--complete"]) == 1
    assert (
        capsys.readouterr().err
        == "status=failed gate=files-result-stamp-v1 reason=arguments_invalid\n"
    )


def test_readonly_factory_installs_readonly_and_finite_sql_limits_before_queries(monkeypatch):
    from miy_api.core import model_registry

    calls = []
    monkeypatch.setattr(model_registry, "import_all_models", lambda: calls.append("models"))

    @contextmanager
    def factory():
        yield SimpleNamespace(execute=lambda statement: calls.append(str(statement)))

    with gate._readonly_session(factory):
        calls.append("query")
    assert calls == [
        "models",
        "SET TRANSACTION READ ONLY",
        "SET LOCAL statement_timeout = '5000ms'",
        "SET LOCAL lock_timeout = '5000ms'",
        "query",
    ]


def test_failed_deadline_install_restores_previous_signal_handler(monkeypatch):
    previous = signal.getsignal(signal.SIGALRM)
    timer = signal.setitimer

    def refuse_timer(which, seconds):
        if seconds:
            raise OSError("synthetic timer unavailable")
        return timer(which, seconds)

    monkeypatch.setattr(signal, "setitimer", refuse_timer)
    try:
        with pytest.raises(gate.FilesContentCutoverRefused) as caught:
            with gate._deadline(1):
                pytest.fail("failed timer must never enter check")
        assert caught.value.reason == "deadline_unavailable"
        assert signal.getsignal(signal.SIGALRM) is previous
    finally:
        signal.signal(signal.SIGALRM, previous)


def test_existing_caller_timer_is_preserved_and_check_never_runs():
    previous = signal.getsignal(signal.SIGALRM)
    signal.setitimer(signal.ITIMER_REAL, 5)
    try:
        with pytest.raises(gate.FilesContentCutoverRefused) as caught:
            with gate._deadline(1):
                pytest.fail("caller timer must never be replaced")
        assert caught.value.reason == "deadline_unavailable"
        assert signal.getsignal(signal.SIGALRM) is previous
        assert 4 < signal.getitimer(signal.ITIMER_REAL)[0] <= 5
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0)


def test_active_gate_registers_models_in_genuinely_fresh_process_before_compiling_queries(tmp_path):
    source = Path(__file__).resolve().parents[1] / "src"
    code = """
import sys
import os
from pathlib import Path
counts = {'env': 0, 'auth': 0, 'network': 0}
def audit(name, args):
    if name == 'open' and isinstance(args[0], (str, bytes, os.PathLike)):
        filename = Path(os.fsdecode(args[0])).name
        if filename == '.env' or filename.endswith('.env') or filename.startswith('.env.'):
            counts['env'] += 1
            raise AssertionError('environment file read')
        if filename in {'auth.json', '.auth_info', 'auth_info.json'}:
            counts['auth'] += 1
            raise AssertionError('authentication file read')
    if name == 'socket.connect':
        counts['network'] += 1
        raise AssertionError('network access')
sys.addaudithook(audit)
from contextlib import nullcontext
from types import SimpleNamespace
import dotenv
from pydantic_settings import DotEnvSettingsSource
dotenv.dotenv_values = lambda *args, **kwargs: {}
DotEnvSettingsSource._read_env_files = lambda self: {}
from miy_api.domains.files.cutover_gate import check_files_content_cutover
compiled = []
class ReadOnlyDb:
    no_autoflush = nullcontext()
    def __enter__(self): return self
    def __exit__(self, *_args): pass
    def scalar(self, statement):
        compiled.append(str(statement))
        return 0 if len(compiled) == 1 else None
def forbidden(): raise AssertionError('backend constructed')
receipt = check_files_content_cutover(
    settings=SimpleNamespace(rag_enabled=True, files_retrieval_enabled=True),
    session_factory=ReadOnlyDb, verify_active=forbidden)
assert receipt.mode == 'empty_source'
assert len(compiled) == 2
assert all('file_manager_files' in query for query in compiled)
assert counts == {'env': 0, 'auth': 0, 'network': 0}
print('fresh_process_queries=2 result=empty_source backend_calls=0 env=0 auth=0 network=0')
"""
    env = {
        "PATH": os.defpath,
        "HOME": str(tmp_path),
        "PYTHONPATH": str(source),
        "PYTHONDONTWRITEBYTECODE": "1",
        "MIY_ENV_PROFILE": "test",
        "MIY_POSTGRES_DSN": "postgresql+psycopg://contract:contract@127.0.0.1:1/contract",
        "MIY_LLM_HEALTHCHECK_ON_STARTUP": "0",
        "MIY_OTEL_ENABLED": "0",
    }
    result = subprocess.run(
        [sys.executable, "-c", code], env=env, capture_output=True, text=True, timeout=15
    )
    assert result.returncode == 0, result.stderr
    assert (
        result.stdout
        == "fresh_process_queries=2 result=empty_source backend_calls=0 env=0 auth=0 network=0\n"
    )
