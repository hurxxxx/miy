import argparse
import getpass
import json
import stat
from pathlib import Path

import uvicorn
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, delete, inspect
from sqlalchemy.engine import make_url

from .app import create_app
from .auth import password_hash
from .config import Settings
from .models import Owner, WebSession, database

ROOT = Path(__file__).resolve().parents[2]


def migrate(url):
    if make_url(url).get_backend_name() == "sqlite":
        from .storage import process_guard

        with process_guard(url):
            engine, _ = database(url)
            try:
                if any(
                    not name.startswith("console_") for name in inspect(engine).get_table_names()
                ):
                    raise ValueError("Migrations require a dedicated console database")
            finally:
                engine.dispose()
            config = Config(str(ROOT / "alembic.ini"))
            config.set_main_option("script_location", str(ROOT / "sqlite_migrations"))
            config.attributes["database_url"] = url
            command.upgrade(config, "head")
        return
    engine = create_engine(url)
    try:
        if any(not name.startswith("console_") for name in inspect(engine).get_table_names()):
            raise ValueError("Migrations require a dedicated console database")
    finally:
        engine.dispose()
    config = Config(str(ROOT / "alembic.ini"))
    config.attributes["database_url"] = url
    command.upgrade(config, "head")


def main():
    parser = argparse.ArgumentParser(description="Private Codex console")
    parser.add_argument(
        "command",
        choices=(
            "serve",
            "manage",
            "templates",
            "migrate",
            "set-password",
            "openapi",
            "backup",
            "import-postgres",
        ),
    )
    parser.add_argument("--destination", type=Path, help="New backup file")
    parser.add_argument(
        "--source-env", type=Path, help="Private env file of the old PostgreSQL console"
    )
    args = parser.parse_args()
    if args.command == "openapi":
        print(json.dumps(create_app().openapi(), ensure_ascii=False))
        return
    settings = Settings()
    if args.command == "migrate":
        migrate(settings.database_url)
    elif args.command == "backup":
        from .transfer import backup

        if not args.destination:
            parser.error("backup requires --destination")
        backup(settings.database_url, args.destination)
        print("Consistent SQLite backup created and integrity verified")
    elif args.command == "import-postgres":
        from dotenv import dotenv_values

        from .transfer import import_postgres

        source = args.source_env
        if (
            not source
            or not source.is_file()
            or source.is_symlink()
            or stat.S_IMODE(source.stat().st_mode) & 0o077
        ):
            parser.error("import-postgres requires a private 0600 --source-env file")
        url = dotenv_values(source, interpolate=False).get("MTY_CODEX_CONSOLE_DATABASE_URL")
        if not url:
            parser.error("The source file must contain MTY_CODEX_CONSOLE_DATABASE_URL")
        try:
            counts = import_postgres(url, settings.database_url)
        except Exception:
            # Driver failures may contain source credentials or record contents.
            raise SystemExit(
                "Import failed; no SQLite destination was published and PostgreSQL was unchanged. "
                "Check source availability, stopped console services, "
                "schema and destination permissions."
            ) from None
        print(json.dumps({"verified_rows": counts}))
    elif args.command == "set-password":
        password = getpass.getpass("Console owner password (at least 12 characters): ")
        if len(password) < 12 or password != getpass.getpass("Repeat password: "):
            raise SystemExit("Passwords must match and contain at least 12 characters")
        engine, factory = database(settings.database_url)
        with factory.begin() as db:
            owner = db.get(Owner, 1)
            if owner:
                owner.password_hash = password_hash(password)
                owner.failed_logins, owner.locked_until = 0, None
            else:
                db.add(Owner(password_hash=password_hash(password)))
            db.execute(delete(WebSession))
        engine.dispose()
        print("Owner password updated; web sessions revoked. Codex login is unchanged.")
    else:
        uvicorn.run(
            create_app(
                settings,
                role={"manage": "management", "templates": "templates"}.get(
                    args.command, "session"
                ),
            ),
            host=settings.bind_host,
            port={"manage": settings.management_port, "templates": settings.template_port}.get(
                args.command, settings.port
            ),
            workers=1,
            access_log=False,
            proxy_headers=False,
        )


if __name__ == "__main__":
    main()
