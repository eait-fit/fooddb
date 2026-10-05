#!/bin/sh
# The shared Postgres and this worktree's two databases in it.
#
#   ./dev db up [test]       start the shared Postgres; create this worktree's dev and test
#                            databases if missing; migrate the dev one (`test`: only the test one)
#   ./dev db down            stop the shared Postgres (EVERY worktree loses its database server)
#   ./dev db migrate [test]  apply fooddb's and pq's migrations
#   ./dev db psql [test]     psql into this worktree's dev (or test) database
#   ./dev db reset [--yes]   drop and recreate this worktree's dev database, then migrate
#   ./dev db drop [--yes]    drop this worktree's dev and test databases
#   ./dev db ls              every fooddb database on the shared server, with its size
#
# ONE SERVER, MANY DATABASES. Every worktree uses the same container (fixed compose project
# `fooddb`, fixed container name), and its own database inside it, named by scripts/dev_env.py.
# THE APP NEVER CREATES A DATABASE: `up` here does, explicitly, and only the two this worktree's
# derivation names.
set -eu

cd "$(dirname "$0")/.."
[ -f .env.worktree ] || uv run --no-project python scripts/dev_env.py setup >/dev/null
. ./.env.worktree
export FOODDB__BACKEND__DATABASE_URL FOODDB_TEST_DATABASE_URL

COMPOSE="docker compose -p fooddb -f docker-compose.yml"
CONTAINER=fooddb-db

die() { echo "db: $*" >&2; exit 1; }

q() { docker exec -i "$CONTAINER" psql -XqtA -U fooddb -d postgres -c "$1"; }

server_up() {
  docker info >/dev/null 2>&1 || die 'Docker is not running. Start Docker Desktop (or: ./dev install --check)'
  $COMPOSE up -d --wait >/dev/null 2>&1 || die "the shared Postgres did not come up — $COMPOSE logs db"
}

# Database names come from the derivation, which only emits [a-z0-9_], so quoting them is enough.
create_db() {
  [ "$(q "select 1 from pg_database where datname = '$1'")" = 1 ] && return 0
  q "create database \"$1\"" && echo "  created database $1"
}

drop_db() { q "drop database if exists \"$1\" with (force)" && echo "  dropped database $1"; }

migrate() {
  if [ "${1:-}" = test ]; then url=$FOODDB_TEST_DATABASE_URL; else url=$FOODDB__BACKEND__DATABASE_URL; fi
  FOODDB__BACKEND__DATABASE_URL=$url uv run fooddb migrate >/dev/null && echo "  migrated $(basename "$url")"
}

confirm() {
  [ "${1:-}" = --yes ] && return 0
  printf 'This deletes %s. Type its name to confirm: ' "$2"
  read -r _answer
  [ "$_answer" = "$2" ] || die 'not confirmed'
}

case "${1:-up}" in
  up)
    [ $# -eq 0 ] || shift
    server_up
    # `up test` touches only the test database: `./dev test` must never migrate the dev one.
    if [ "${1:-}" = test ]; then
      create_db "$FOODDB_TEST_DB_NAME"; migrate test
    else
      create_db "$FOODDB_DB_NAME"; create_db "$FOODDB_TEST_DB_NAME"; migrate
      echo "db: $FOODDB__BACKEND__DATABASE_URL"
    fi
    ;;
  down)
    echo 'Stopping the SHARED Postgres: every worktree loses its database server until `./dev db up`.'
    $COMPOSE stop
    ;;
  migrate) shift; server_up; migrate "${1:-}" ;;
  psql)
    shift
    if [ "${1:-}" = test ]; then db=$FOODDB_TEST_DB_NAME; else db=$FOODDB_DB_NAME; fi
    exec docker exec -it "$CONTAINER" psql -U fooddb -d "$db"
    ;;
  reset)
    shift; server_up
    confirm "${1:-}" "$FOODDB_DB_NAME"
    drop_db "$FOODDB_DB_NAME"; create_db "$FOODDB_DB_NAME"; migrate
    ;;
  drop)
    shift; server_up
    confirm "${1:-}" "$FOODDB_DB_NAME"
    drop_db "$FOODDB_DB_NAME"; drop_db "$FOODDB_TEST_DB_NAME"
    ;;
  ls)
    server_up
    q "select datname || '  ' || pg_size_pretty(pg_database_size(datname)) from pg_database where datname like 'fooddb%' order by 1"
    ;;
  *) die "unknown command: $1 (up | down | migrate | psql | reset | drop | ls)" ;;
esac
