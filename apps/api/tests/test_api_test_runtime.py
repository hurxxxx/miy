from __future__ import annotations

import conftest
import pytest
from integration_infra import IntegrationInfra
from sqlalchemy import create_engine, text
from sqlalchemy import inspect as sqlalchemy_inspect


def _infra() -> IntegrationInfra:
    return IntegrationInfra(
        redis_url="redis://127.0.0.1:56380/0",
        minio_endpoint="http://127.0.0.1:59010",
        minio_access_key="test-access",
        minio_secret_key="test-secret",
        opensearch_url="http://127.0.0.1:59210",
        run_token="abc123",
    )


def test_database_reset_refuses_non_test_database() -> None:
    engine = create_engine("postgresql+psycopg://test:test@127.0.0.1:5432/application")
    try:
        with pytest.raises(RuntimeError, match="Refusing to reset non-test database"):
            conftest._reset_test_database(engine)
    finally:
        engine.dispose()


def test_database_setup_failure_removes_only_the_created_database(
    postgres_template_dsn: str, postgres_dsn: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    attempted_databases: list[str] = []

    def unavailable_extension(dsn: str) -> None:
        attempted_databases.append(conftest._database_from_dsn(dsn))
        raise RuntimeError("test extension unavailable")

    monkeypatch.setattr(conftest, "_ensure_pgvector_extension", unavailable_extension)
    engine = create_engine(conftest._dsn_for_database(postgres_template_dsn, "postgres"))
    try:
        with engine.connect() as connection:
            before = set(connection.scalars(text("SELECT datname FROM pg_database")))
        with pytest.raises(RuntimeError, match="test extension unavailable"):
            with conftest._native_test_database(postgres_template_dsn, role="setup_failure"):
                pytest.fail("Failed database setup must never yield a usable fixture")
        assert len(attempted_databases) == 1
        with engine.connect() as connection:
            after = set(connection.scalars(text("SELECT datname FROM pg_database")))
        assert attempted_databases[0] not in after
        # Other workers may create/drop databases concurrently. Preserve both the template
        # and a different test database, not merely non-test databases.
        template_name = conftest._database_from_dsn(postgres_template_dsn)
        untouched_name = conftest._database_from_dsn(postgres_dsn)
        assert {template_name, untouched_name} <= before & after
    finally:
        engine.dispose()


def _application_seed_rows(connection, table_names) -> dict[str, str]:
    return {
        table_name: connection.scalar(
            text(
                f"SELECT COALESCE(jsonb_agg(to_jsonb(row_data) "
                f"ORDER BY to_jsonb(row_data)::text), "
                f"'[]'::jsonb)::text FROM {table_name} AS row_data"
            )
        )
        for table_name in table_names
    }


def test_baseline_restore_failure_preserves_recording_authority_and_recovers(
    application_postgres_state: conftest.ApplicationPostgresState,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import psycopg

    engine = create_engine(application_postgres_state.dsn)
    original = conftest._run_postgres_cli

    def restore_failure(command, *, dsn):
        result = original(command, dsn=dsn)
        if command[0] == "pg_restore":
            from pathlib import Path

            generated = Path(command[command.index("--file") + 1])
            with generated.open("a") as output:
                output.write("\nSELECT public.synthetic_baseline_restore_failure();\n")
        return result

    def recording_guards(connection):
        return connection.execute(
            text("""
            SELECT c.relname,t.tgname,t.tgenabled,p.proname
            FROM pg_trigger t JOIN pg_class c ON c.oid=t.tgrelid
            JOIN pg_namespace n ON n.oid=c.relnamespace
            JOIN pg_proc p ON p.oid=t.tgfoid
            WHERE n.nspname='public' AND NOT t.tgisinternal
              AND c.relname IN ('recording_stage_commands','core_recording_publications','file_extraction_requests')
            ORDER BY 1,2
        """)
        ).all()

    try:
        conftest._restore_application_postgres_state(application_postgres_state)
        with engine.begin() as connection:
            expected = recording_guards(connection)
            expected_tables = set(sqlalchemy_inspect(connection).get_table_names())
            expected_revision = connection.scalar(text("SELECT version_num FROM alembic_version"))
            assert len(expected) == 10 and all(row[2] == "O" for row in expected)
            connection.execute(text("DELETE FROM app_access_policies"))
            seed_before = _application_seed_rows(
                connection, ("company_app_controls", "app_access_policies")
            )
        with monkeypatch.context() as patch:
            patch.setattr(conftest, "_run_postgres_cli", restore_failure)
            with pytest.raises(RuntimeError, match="synthetic_baseline_restore_failure"):
                conftest._restore_application_postgres_state(application_postgres_state)
        with engine.connect() as connection:
            assert recording_guards(connection) == expected
            assert _application_seed_rows(connection, seed_before) == seed_before
            with pytest.raises(Exception) as error:
                connection.execute(
                    text("UPDATE core_recording_publications SET state=state WHERE false")
                )
            assert error.value.orig.sqlstate == "42501"
            connection.rollback()
            with pytest.raises(Exception) as file_error:
                connection.execute(
                    text("UPDATE file_extraction_requests SET state=state WHERE false")
                )
            assert file_error.value.orig.sqlstate == "55000"
            connection.rollback()
            assert connection.scalar(text("SELECT count(*) FROM official_writer_principals")) == 0
        with psycopg.connect(
            application_postgres_state.dsn.replace("postgresql+psycopg://", "postgresql://", 1)
        ) as connection:
            with pytest.raises(psycopg.Error) as error:
                with connection.cursor().copy(
                    "COPY public.core_recording_publications (publication_id) FROM STDIN"
                ):
                    pass
            assert error.value.sqlstate == "42501"
        # Rollback preserves the prior composition; a subsequent exact restore
        # must still recover the canonical application seed.
        conftest._restore_application_postgres_state(application_postgres_state)
        with engine.connect() as connection:
            assert recording_guards(connection) == expected
            assert connection.scalar(text("SELECT count(*) FROM company_app_controls")) > 0
            assert connection.scalar(text("SELECT count(*) FROM app_access_policies")) > 0
            assert connection.scalar(text("SELECT count(*) FROM core_recording_publications")) == 0
            assert set(sqlalchemy_inspect(connection).get_table_names()) == expected_tables
            assert (
                connection.scalar(text("SELECT version_num FROM alembic_version"))
                == expected_revision
            )
    finally:
        engine.dispose()


def test_cleanup_refuses_resources_outside_the_current_run() -> None:
    infra = _infra()

    with pytest.raises(RuntimeError, match="outside this test run"):
        infra.cleanup_minio_bucket("miy-dev")
    with pytest.raises(RuntimeError, match="outside this test run"):
        infra.cleanup_opensearch_indices("miy-dev")


def test_current_run_cleanup_attempts_every_backend(monkeypatch) -> None:
    infra = _infra()
    calls: list[str] = []

    def fail_minio(_self) -> None:
        calls.append("minio")
        raise RuntimeError("minio unavailable")

    monkeypatch.setattr(IntegrationInfra, "_cleanup_current_minio", fail_minio)
    monkeypatch.setattr(
        IntegrationInfra,
        "cleanup_opensearch_indices",
        lambda _self, _prefix: calls.append("opensearch"),
    )
    monkeypatch.setattr(
        IntegrationInfra,
        "cleanup_current_postgres_databases",
        lambda _self: calls.append("postgres"),
    )

    with pytest.raises(ExceptionGroup, match="resource cleanup failed"):
        infra.cleanup_current_run()

    assert calls == ["minio", "opensearch", "postgres"]
