from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from alembic import command
from alembic.config import Config
import pytest
import sqlalchemy as sa
from sqlalchemy.orm import Session

from miy_api.domains.ai_artifacts.contracts import AiArtifactCreate
from miy_api.domains.ai_artifacts.models import AiArtifact
from miy_api.domains.ai_artifacts.repository import AiArtifactRepository

pytestmark = pytest.mark.migration


def _config(dsn: str) -> Config:
    root = Path(__file__).resolve().parents[1]
    config = Config(str(root / "alembic.ini"))
    config.set_main_option("script_location", str(root / "alembic"))
    config.set_main_option("sqlalchemy.url", dsn.replace("%", "%%"))
    return config


def _create_completed(engine: sa.Engine, artifact_type: str) -> tuple[str, str]:
    with Session(engine) as db:
        artifact = AiArtifactRepository(db).create_completed(
            AiArtifactCreate(
                owner_user_id="sequence-owner",
                app_id="chatbot",
                artifact_type=artifact_type,
                title="Sequence regression",
                content_text="Saved through the actual PostgreSQL repository.",
            )
        )
        db.commit()
        return artifact.id, artifact.artifact_number


@pytest.mark.parametrize("state", ["empty", "artifacts", "allocated", "unused"])
def test_artifact_sequences_restore_numbers_and_persist_completed_artifacts(
    postgres_dsn: str, state: str
) -> None:
    config = _config(postgres_dsn)
    command.upgrade(config, "miy_api_keys_20261001")
    engine = sa.create_engine(postgres_dsn)
    try:
        with engine.begin() as conn:
            conn.execute(
                sa.text("""
                INSERT INTO users (id, login_id, email, full_name, password_hash, status,
                    login_blocked, must_change_password, theme_preference, locale,
                    time_zone, date_format, created_at, updated_at)
                VALUES ('sequence-owner', 'sequence-owner', 'sequence@example.test',
                    'Sequence Owner', 'fixture', 'active', false, false, 'system',
                    'ko-KR', 'Asia/Seoul', 'korean', now(), now())
            """)
            )
            if state != "empty":
                # The largest suffix may be on an older date, not the newest report.
                for kind, number in (
                    ("report", "AIR-20260901-0000000042"),
                    ("report", "AIR-20260914-0000000003"),
                    ("analysis", "AIA-20260914-0000000007"),
                ):
                    conn.execute(
                        sa.insert(AiArtifact).values(
                            id=number,
                            artifact_number=number,
                            owner_user_id="sequence-owner",
                            app_id="chatbot",
                            artifact_type=kind,
                            title="Retained artifact",
                            content_type="text/markdown",
                            content_text="Retained content",
                        )
                    )
            if state in {"allocated", "unused"}:
                conn.execute(sa.text("CREATE SEQUENCE ai_report_artifact_number_seq START 100"))
                conn.execute(sa.text("CREATE SEQUENCE ai_analysis_artifact_number_seq START 200"))
                if state == "allocated":
                    conn.execute(sa.text("SELECT nextval('ai_report_artifact_number_seq')"))
                    conn.execute(sa.text("SELECT nextval('ai_analysis_artifact_number_seq')"))

        command.upgrade(config, "head")
        expected = {
            "empty": (1, 1),
            "artifacts": (43, 8),
            "allocated": (101, 201),
            "unused": (100, 200),
        }[state]
        created = []
        for kind, prefix, number in zip(("report", "analysis"), ("AIR", "AIA"), expected):
            artifact_id, artifact_number = _create_completed(engine, kind)
            assert artifact_number.startswith(f"{prefix}-")
            assert int(artifact_number.rsplit("-", 1)[1]) == number
            created.append(artifact_id)
        with Session(engine) as db:
            for artifact_id in created:
                artifact = db.get(AiArtifact, artifact_id)
                assert artifact is not None
                assert artifact.status == "completed"
                assert artifact.visibility == "private"
                assert artifact.content_sha256 and artifact.content_size_bytes
            if state != "empty":
                assert db.get(AiArtifact, "AIR-20260901-0000000042").content_text == (
                    "Retained content"
                )

        # Concurrent callers must receive distinct durable numbers, not max+1 races.
        with ThreadPoolExecutor(max_workers=4) as pool:
            concurrent = list(pool.map(lambda _: _create_completed(engine, "report"), range(4)))
        assert len({number for _, number in concurrent}) == 4
        assert sorted(int(number.rsplit("-", 1)[1]) for _, number in concurrent) == list(
            range(expected[0] + 1, expected[0] + 5)
        )

        # Rolling back application code must retain the repair and allocation position.
        command.downgrade(config, "miy_api_keys_20261001")
        _, rollback_number = _create_completed(engine, "report")
        assert int(rollback_number.rsplit("-", 1)[1]) == expected[0] + 5
        command.upgrade(config, "head")
        _, next_number = _create_completed(engine, "report")
        assert int(next_number.rsplit("-", 1)[1]) == expected[0] + 6
    finally:
        engine.dispose()
