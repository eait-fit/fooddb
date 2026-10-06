#!/bin/sh
# This worktree's dev stack, in the background, on this worktree's ports.
#
#   ./dev up [--api] [--worker] [--all]   bare: the shared Postgres and this worktree's databases
#   ./dev down                       stop everything this worktree started (the shared Postgres
#                                    stays up — the other worktrees use it)
#   ./dev restart [same flags]       bare: whatever `up` last asked for, including what has crashed
#   ./dev status                     this worktree
#   ./dev ls [--plain]               EVERY worktree on this machine, and what each is running
#   ./dev fetch [off|off-dump|fdc|table|match|all] [...]   queue work for the worker (`off --max-files 7`,
#                                    `fdc --dataset sr_legacy`, `table --source ciqual`; `off-dump` = the full
#                                    ~13 GB OFF dump, streamed, hours; `all` = FDC Foundation and SR Legacy,
#                                    CIQUAL, Matvaretabellen + 7 OFF deltas; never FDC Branded, ~3 GB)
#   ./dev jobs                       row counts, fetch runs and the pq queue for this worktree
#   ./dev cli <args…>                the fooddb CLI against this worktree's database
#   ./dev test [args…]               pytest PLUS the database suite against this worktree's own
#                                    TEST database (`uv run pytest` leaves that suite skipped)
#   ./dev logs [service]
#   ./dev db [up|down|migrate|psql|reset|drop|ls]   the shared Postgres and this worktree's databases
#   ./dev env [setup|show|clean] | url
#   ./dev install [--check]          every tool this repo needs, on macOS or Linux
#
# ─────────────────────────────────────────────────────────────────────────────────────────────
# Ported from eait's src/scripts/dev.sh; the reasoning there holds here.
#
# IT ADDS NOTHING TO THE DERIVATION: every port and database comes from scripts/dev_env.py through
# `.env.worktree`, and this file computes none of them.
#
# STOPPING ONE KILLS THE TREE IT STARTED and nothing else, by walking `ppid` (a nohup'd command is
# not reliably a process-group leader). A pidfile is never trusted on its own: the pid must be
# alive, running this service, AND running out of this worktree (`lsof -d cwd`), or the file is
# stale and removed rather than acted on. Two worktrees run identical commands; the working
# directory is the only thing that tells them apart.
# ─────────────────────────────────────────────────────────────────────────────────────────────
set -eu

cd "$(dirname "$0")/.."

# The PHYSICAL path, because `lsof` reports resolved paths.
ROOT=$(pwd -P)
STATE=.dev
LOGS="$STATE/logs"
UP_LOCK="$STATE/up.lock"
ALL_SERVICES="api worker"

die() { echo "dev: $*" >&2; exit 1; }

dev_env() { uv run --no-project python scripts/dev_env.py "$@"; }

ensure_env() {
  command -v uv >/dev/null || die 'uv is not installed — ./dev install'
  [ -d .venv ] || { echo '→ uv sync'; uv sync; }
  [ -f .env.worktree ] || { echo '→ deriving this worktree (scripts/dev_env.py setup)'; dev_env setup >/dev/null; }
}

main_worktree() {
  _m=$(git worktree list --porcelain | sed -n '1s/^worktree //p')
  if [ -d "$_m" ]; then (cd "$_m" && pwd -P); else echo "$_m"; fi
}

# A linked worktree without `.env.worktree` would answer slot 0's ports and database. A REFUSAL,
# not a warning, because `./dev url` exists to be substituted and stderr is invisible in `$( )`.
load_env() {
  if [ ! -f .env.worktree ] && [ "$ROOT" != "$(main_worktree)" ]; then
    die 'this worktree has no .env.worktree, so every port here would be the MAIN worktree'"'"'s. Run `./dev up` (or `./dev env setup`) first.'
  fi
  # The caller's environment must not outrank the derivation: an inherited FOODDB__BACKEND__DATABASE_URL
  # would aim this worktree's worker at another worktree's database.
  for _k in $(dev_env derived-keys); do unset "$_k"; done
  [ -f .env.worktree ] || dev_env setup >/dev/null
  set -a; . ./.env.worktree; set +a
}

# ── The service table ────────────────────────────────────────────────────────────────────────

# pq forks a child per task; macOS aborts forked children that touch Objective-C runtime state
# unless told not to.
svc_cmd() {
  case "$1" in
    api)    echo 'exec .venv/bin/fooddb serve' ;;
    worker) echo 'OBJC_DISABLE_INITIALIZE_FORK_SAFETY=YES exec .venv/bin/fooddb worker' ;;
  esac
}

# What the process must show in `ps` for its pidfile to count.
svc_needle() {
  case "$1" in
    api)    echo 'fooddb serve' ;;
    worker) echo 'fooddb worker' ;;
  esac
}

svc_port() {
  case "$1" in
    api) echo "${FOODDB__BACKEND__API_PORT-}" ;;
    *)   echo '' ;;
  esac
}

# The worker has no port: it is healthy when it is alive and has registered its schedules.
svc_health() {
  case "$1" in
    api)    curl -sf -o /dev/null --max-time 3 "$FOODDB_API_URL/livez" ;;
    worker) is_running_now worker && grep -q 'Starting PQ worker' "$LOGS/worker.log" 2>/dev/null ;;
  esac
}

svc_timeout() { echo 60; }

# ── Processes ────────────────────────────────────────────────────────────────────────────────

pid_of() { cat "$STATE/$1.pid" 2>/dev/null || true; }

proc_in_worktree() {
  require_proc_tools
  _cwd=$(lsof -a -d cwd -p "$1" -Fn 2>/dev/null | sed -n 's/^n//p' | head -1)
  case "$_cwd" in "$ROOT"|"$ROOT"/*) return 0 ;; *) return 1 ;; esac
}

# A machine without a working `ps` or `lsof` answers every pidfile question with "no", which looks
# exactly like a stale pidfile. Refuse rather than delete a pidfile on a question nobody asked.
_PROC_TOOLS=""
require_proc_tools() {
  [ -z "$_PROC_TOOLS" ] || return 0
  _PROC_TOOLS=asked
  [ -n "$(ps -o command= -p $$ 2>/dev/null)" ] || die 'no working `ps` — refusing to judge pidfiles. ./dev install'
  proc_in_worktree $$ || die 'no working `lsof` — refusing to judge pidfiles. ./dev install'
}

is_running_now() {
  _pid=$(pid_of "$1")
  [ -n "$_pid" ] || return 1
  require_proc_tools
  if kill -0 "$_pid" 2>/dev/null \
     && ps -o command= -p "$_pid" 2>/dev/null | grep -q "$(svc_needle "$1")" \
     && proc_in_worktree "$_pid"; then
    return 0
  fi
  rm -f "$STATE/$1.pid"
  return 1
}

is_running() { is_running_now "$1"; }

start_service() {
  if is_running "$1"; then
    echo "  $1: already running (pid $(pid_of "$1"))"
    return 0
  fi
  mkdir -p "$LOGS"
  # A fresh log per start: the worker's health check reads it, and a line from the last run must
  # not vouch for this one.
  [ ! -f "$LOGS/$1.log" ] || mv "$LOGS/$1.log" "$LOGS/$1.log.prev"
  # `</dev/null` matters on macOS: BSD nohup leaves stdin on the TTY.
  (
    set -m
    nohup sh -c "$(svc_cmd "$1")" </dev/null >>"$LOGS/$1.log" 2>&1 &
    echo $! >"$STATE/$1.pid"
  )
  echo "  $1: started (log: $LOGS/$1.log)"
}

# Every process descended from $1, parents first, itself excluded. One `ps` snapshot, taken before
# anything is signalled.
descendants() {
  _snap=$(ps -eo pid,ppid 2>/dev/null | awk 'NR > 1 { print $1, $2 }')
  _gen=$1
  _found=""
  _depth=0
  while [ -n "$_gen" ] && [ "$_depth" -lt 12 ]; do
    _next=$(echo "$_snap" | awk -v ps="$_gen" '
      BEGIN { n = split(ps, a, " "); for (i = 1; i <= n; i++) want[a[i]] = 1 }
      $2 in want && $1 != 1 { print $1 }')
    [ -n "$_next" ] || break
    _found="$_found $_next"
    _gen=$_next
    _depth=$((_depth + 1))
  done
  echo $_found
}

stop_service() {
  is_running "$1" || { rm -f "$STATE/$1.pid"; return 0; }
  _pid=$(pid_of "$1")
  _tree="$_pid $(descendants "$_pid")"
  for _p in $_tree; do kill -TERM "$_p" 2>/dev/null || true; done
  _waited=0
  while kill -0 "$_pid" 2>/dev/null && [ "$_waited" -lt 10 ]; do
    sleep 1
    _waited=$((_waited + 1))
  done
  for _p in $_tree; do
    kill -0 "$_p" 2>/dev/null && kill -KILL "$_p" 2>/dev/null
  done
  true
  rm -f "$STATE/$1.pid"
  # The listener can outlive its parent shell by a moment; `restart` would then trip its own port
  # check.
  _port=$(svc_port "$1")
  _waited=0
  while [ -n "$_port" ] && lsof -nP -iTCP:"$_port" -sTCP:LISTEN >/dev/null 2>&1 && [ "$_waited" -lt 5 ]; do
    sleep 1
    _waited=$((_waited + 1))
  done
  echo "  $1: stopped"
}

wait_for() {
  _waited=0
  printf '  waiting for %s' "$1"
  until svc_health "$1"; do
    # A dead service is not a slow one.
    _alive=$(pid_of "$1")
    if [ -z "$_alive" ] || ! kill -0 "$_alive" 2>/dev/null; then
      printf ' died on startup — see %s/%s.log\n' "$LOGS" "$1"
      return 1
    fi
    sleep 2
    _waited=$((_waited + 2))
    printf '.'
    if [ "$_waited" -ge "$(svc_timeout "$1")" ]; then
      printf ' not healthy after %ss — see %s/%s.log\n' "$_waited" "$LOGS" "$1"
      return 1
    fi
  done
  printf ' ok\n'
}

# ── Commands ─────────────────────────────────────────────────────────────────────────────────

# What a bare `./dev restart` brings back: this request UNIONED with what is already up, written by
# `up` because a service that crashed has no pidfile and is exactly the one you want back.
record() {
  mkdir -p "$STATE"
  _rec=""
  for svc in $ALL_SERVICES; do
    case " $SELECTED " in *" $svc "*) _rec="$_rec $svc"; continue ;; esac
    if is_running "$svc"; then _rec="$_rec $svc"; fi
  done
  printf '%s\n' "$_rec" >"$STATE/services"
}

parse_flags() {
  SELECTED=""
  for arg in "$@"; do
    case "$arg" in
      --api)    SELECTED="$SELECTED api" ;;
      --worker) SELECTED="$SELECTED worker" ;;
      --all)    SELECTED="api worker" ;;
      *) die "unknown flag: $arg (use --api/--worker/--all)" ;;
    esac
  done
  _seen=""
  for svc in $SELECTED; do
    case " $_seen " in *" $svc "*) ;; *) _seen="$_seen $svc" ;; esac
  done
  SELECTED="${_seen# }"
}

cmd_up() {
  parse_flags "$@"
  do_up
}

do_up() {
  mkdir -p "$STATE"
  mkdir "$UP_LOCK" 2>/dev/null || die "another \`./dev up\` is running here (or remove $UP_LOCK)"
  trap 'rmdir "$UP_LOCK" 2>/dev/null || true' EXIT
  trap 'rmdir "$UP_LOCK" 2>/dev/null || true; exit 130' INT TERM

  ensure_env
  load_env
  echo "Slot $FOODDB_SLOT — $FOODDB_DB_NAME"
  dev_env branch-check

  for svc in $SELECTED; do
    _port=$(svc_port "$svc")
    if [ -n "$_port" ] && ! is_running "$svc" && lsof -nP -iTCP:"$_port" -sTCP:LISTEN >/dev/null 2>&1; then
      die "port $_port ($svc) is already taken by another process — ./dev ls"
    fi
  done

  # Both services need the database, and so does a bare `up`.
  echo '→ Shared Postgres + this worktree'"'"'s databases'
  # Not a pipe: POSIX sh has no pipefail, and `db.sh up | sed` would report sed's success.
  _db_out=$(sh scripts/db.sh up) || die 'the database did not come up (above); nothing was started'
  printf '%s\n' "$_db_out" | sed 's/^/  /'

  if [ -z "$SELECTED" ]; then
    echo '  (no services asked for — pass --api/--worker/--all)'
    return 0
  fi

  record
  echo '→ Starting'
  for svc in $SELECTED; do start_service "$svc"; done

  echo '→ Health'
  _unhealthy=""
  for svc in $SELECTED; do wait_for "$svc" || _unhealthy="$_unhealthy $svc"; done

  echo ''
  for svc in $SELECTED; do
    case " $_unhealthy " in *" $svc "*) continue ;; esac
    case "$svc" in
      api)    echo "api     $FOODDB_API_URL  (docs: $FOODDB_API_URL/docs)" ;;
      worker) echo "worker  running — ./dev fetch all to fill the database" ;;
    esac
  done
  [ -z "$_unhealthy" ] || die "never came up:$_unhealthy — $LOGS has the reason"
}

cmd_down() {
  if [ ! -f .env.worktree ] && [ "$ROOT" != "$(main_worktree)" ]; then
    echo 'this worktree has not been derived — stopping anything its pidfiles still name'
    for svc in $ALL_SERVICES; do stop_service "$svc"; done
    return 0
  fi
  load_env
  echo "Stopping slot $FOODDB_SLOT — the shared Postgres stays up, other worktrees use it"
  for svc in $ALL_SERVICES; do stop_service "$svc"; done
}

cmd_restart() {
  parse_flags "$@"
  if [ -z "$SELECTED" ]; then
    SELECTED=$(cat "$STATE/services" 2>/dev/null || true)
    [ -n "$SELECTED" ] || die 'nothing to restart — start something first: ./dev up --all'
  fi
  load_env
  for svc in $SELECTED; do stop_service "$svc"; done
  do_up
}

cmd_status() {
  load_env
  echo "slot $FOODDB_SLOT · $FOODDB_DB_NAME"
  for svc in $ALL_SERVICES; do
    _port=$(svc_port "$svc")
    if ! is_running "$svc"; then
      echo "✗ $svc  ${_port:--}  not running"
    elif svc_health "$svc"; then
      echo "✓ $svc  ${_port:--}"
    else
      echo "· $svc  ${_port:--}  running, not answering yet"
    fi
  done
  # Freshness, from the API: a running worker that stopped fetching shows up here.
  if is_running api; then
    curl -s --max-time 3 "$FOODDB_API_URL/healthz" | uv run --no-project python -c '
import json, sys
r = json.load(sys.stdin)
for name, f in r["fetchers"].items():
    mark = "✓" if f["fresh"] else "✗"
    print(mark, "data ", name, " last ok:", f["last_ok"] or "never")
' || true
  fi
}

cmd_fetch() {
  ensure_env
  load_env
  is_running worker || echo 'note: the worker is not running here — jobs wait until `./dev up --worker`' >&2
  case "${1:-all}" in
    all)
      .venv/bin/fooddb enqueue fdc --dataset foundation
      .venv/bin/fooddb enqueue fdc --dataset sr_legacy
      .venv/bin/fooddb enqueue table --source ciqual
      .venv/bin/fooddb enqueue table --source cofid
      .venv/bin/fooddb enqueue table --source frida
      .venv/bin/fooddb enqueue table --source matvaretabellen
      .venv/bin/fooddb enqueue table --source mext
      .venv/bin/fooddb enqueue table --source tfda
      .venv/bin/fooddb enqueue off --max-files 7
      ;;
    off|off-dump|fdc|table|match|snapshot) .venv/bin/fooddb enqueue "$@" ;;
    *) die "unknown fetcher: $1 (off | off-dump | fdc | table | match | snapshot | all)" ;;
  esac
}

cmd_logs() {
  if [ -n "${1:-}" ]; then
    case " $ALL_SERVICES " in
      *" $1 "*) ;;
      *) die "unknown service: $1 (one of: $ALL_SERVICES)" ;;
    esac
    [ -f "$LOGS/$1.log" ] || die "$1 has not been started in this worktree yet"
    exec tail -f "$LOGS/$1.log"
  fi
  set -- "$LOGS"/*.log
  [ -f "$1" ] || die 'nothing has been started in this worktree yet'
  exec tail -f "$@"
}

case "${1:-}" in
  up)      shift; cmd_up "$@" ;;
  down)    cmd_down ;;
  restart) shift; cmd_restart "$@" ;;
  status)  cmd_status ;;
  ls)      shift; dev_env ls "$@" ;;
  logs)    shift; cmd_logs "$@" ;;
  db)      shift; exec sh scripts/db.sh "$@" ;;
  install) shift; exec sh scripts/install.sh "$@" ;;
  fetch)   shift; cmd_fetch "$@" ;;
  jobs)    ensure_env; load_env; exec .venv/bin/fooddb status ;;
  cli)     shift; ensure_env; load_env; exec .venv/bin/fooddb "$@" ;;
  # THE ONLY PLACE the database suite gets a database, and it is this worktree's TEST database,
  # migrated first. The suite writes, which is why it never gets the one you develop against.
  test)
    shift
    ensure_env
    load_env
    sh scripts/db.sh up test >/dev/null
    echo "FOODDB_TEST_DATABASE_URL=$FOODDB_TEST_DATABASE_URL"
    FOODDB__BACKEND__DATABASE_URL="$FOODDB_TEST_DATABASE_URL" exec uv run pytest "$@"
    ;;
  env)     shift; ensure_env; exec uv run --no-project python scripts/dev_env.py "${1:-show}" ;;
  url)     load_env; echo "$FOODDB_API_URL" ;;
  *)
    # The header of this file is the help, so there is one copy of it.
    awk 'NR > 1 && /^#/ { sub(/^# ?/, ""); print; next } NR > 1 { exit }' "$0"
    exit 1
    ;;
esac
