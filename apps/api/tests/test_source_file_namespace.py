"""Prepared Source stages must read canonical current execution metadata."""

import pytest
from sqlalchemy import text

from test_file_extraction_commands import c as c
from test_file_extraction_authority import extraction_prepared as extraction_prepared
from test_official_writer_roles import world as world, role_template as role_template
from test_independent_app_data import isolated_data_cluster as isolated_data_cluster

from miy_api.domains.files.extraction_contracts import FileExtractionRefused


def test_actual_source_temp_auth_session_cannot_hide_public_revocation(c):
    # The prepared Source has only the reviewed5 session metadata columns, no
    # credentials. TEMP is existing database capability, not a new role grant.
    with c.engine.begin() as connection:
        connection.execute(
            text(
                "CREATE TEMP TABLE auth_sessions AS SELECT id,user_id,expires_at,revoked_at,impersonator_user_id FROM public.auth_sessions"
            )
        )
        assert (
            connection.scalar(
                text("SELECT revoked_at FROM pg_temp.auth_sessions WHERE id=:id"),
                {"id": c.spec.execution_ref},
            )
            is None
        )
    with c.world.connect() as connection:
        connection.execute(
            "UPDATE public.auth_sessions SET revoked_at=clock_timestamp() WHERE id=%s",
            (c.spec.execution_ref,),
        )
        before = connection.execute(
            "SELECT (SELECT count(*) FROM public.file_extraction_requests),"
            "(SELECT count(*) FROM public.official_projection_outbox),"
            "(SELECT extraction_status FROM public.file_manager_files WHERE id=%s)",
            (c.spec.file_id,),
        ).fetchone()
    try:
        # A distinct Source Engine has no TEMP table and proves current public
        # revocation is an actual refusal, without stubbing current authority.
        from test_file_projection_roles import reader_engine
        from sqlalchemy.orm import Session
        from miy_api.domains.files.extraction_runner import FileExtractionRunner

        plain = reader_engine(c.world, c.roles.source)
        try:
            with pytest.raises(FileExtractionRefused) as error:
                FileExtractionRunner(lambda: Session(plain)).capture(
                    actor_user_id=c.spec.actor_user_id,
                    execution_ref=c.spec.execution_ref,
                    file_id=c.spec.file_id,
                )
            assert error.value.reason == "current_execution_denied"
        finally:
            plain.dispose()
        # This caller-owned pooled connection retains the valid fake row. The
        # trusted Source composition must nevertheless query public metadata.
        with pytest.raises(FileExtractionRefused) as error:
            c.runner.capture(
                actor_user_id=c.spec.actor_user_id,
                execution_ref=c.spec.execution_ref,
                file_id=c.spec.file_id,
            )
        assert error.value.reason == "current_execution_denied"
    finally:
        with c.engine.begin() as connection:
            connection.execute(text("DROP TABLE pg_temp.auth_sessions"))
        with c.world.connect() as connection:
            assert connection.execute(
                "SELECT revoked_at IS NOT NULL FROM public.auth_sessions WHERE id=%s",
                (c.spec.execution_ref,),
            ).fetchone()[0]
            after = connection.execute(
                "SELECT (SELECT count(*) FROM public.file_extraction_requests),"
                "(SELECT count(*) FROM public.official_projection_outbox),"
                "(SELECT extraction_status FROM public.file_manager_files WHERE id=%s)",
                (c.spec.file_id,),
            ).fetchone()
            assert after == before
        assert c.reads == []
