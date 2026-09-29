#!/usr/bin/env bash
# Source from release_validation after the CI database has been verified.
# The protected CI variable is a libpq URL; SQLAlchemy requires the pinned
# psycopg driver to be named explicitly.
case "${MTY_CI_POSTGRES_DSN:-}" in
  postgresql://*)
    mty_validation_dsn="postgresql+psycopg://${MTY_CI_POSTGRES_DSN#postgresql://}"
    ;;
  postgresql+psycopg://*)
    mty_validation_dsn="$MTY_CI_POSTGRES_DSN"
    ;;
  *)
    printf 'CI PostgreSQL DSN must use the PostgreSQL psycopg URL scheme.\n' >&2
    return 2
    ;;
esac
export MTY_POSTGRES_DSN="$mty_validation_dsn"
export MTY_TEST_POSTGRES_TEMPLATE_DSN="$mty_validation_dsn"
unset mty_validation_dsn
