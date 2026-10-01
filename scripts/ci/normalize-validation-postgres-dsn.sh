#!/usr/bin/env bash
# Source from release_validation after the CI database has been verified.
# The protected CI variable is a libpq URL; SQLAlchemy requires the pinned
# psycopg driver to be named explicitly.
case "${MIY_CI_POSTGRES_DSN:-}" in
  postgresql://*)
    miy_validation_dsn="postgresql+psycopg://${MIY_CI_POSTGRES_DSN#postgresql://}"
    ;;
  postgresql+psycopg://*)
    miy_validation_dsn="$MIY_CI_POSTGRES_DSN"
    ;;
  *)
    printf 'CI PostgreSQL DSN must use the PostgreSQL psycopg URL scheme.\n' >&2
    return 2
    ;;
esac
export MIY_POSTGRES_DSN="$miy_validation_dsn"
export MIY_TEST_POSTGRES_TEMPLATE_DSN="$miy_validation_dsn"
unset miy_validation_dsn
