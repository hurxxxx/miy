from alembic import context

from codex_console.config import Settings
from codex_console.models import Base, database

url = context.config.attributes.get("database_url") or Settings().database_url
engine, _ = database(url)
try:
    with engine.connect().execution_options(console_write=True) as connection:
        context.configure(
            connection=connection,
            target_metadata=Base.metadata,
            version_table="console_alembic_version",
            render_as_batch=True,
        )
        with context.begin_transaction():
            context.run_migrations()
finally:
    engine.dispose()
