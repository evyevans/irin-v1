#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
: "${PG_BIN:?Set PG_BIN to the directory containing postgres/initdb/pg_ctl/psql}"
ATLAS_PG_TMP=$(mktemp -d "${TMPDIR:-/tmp}/atlas-pg.XXXXXX")
cleanup(){ "$PG_BIN/pg_ctl" -D "$ATLAS_PG_TMP/data" -m immediate stop >/dev/null 2>&1 || true; rm -rf "$ATLAS_PG_TMP"; }
trap cleanup EXIT
"$PG_BIN/initdb" -D "$ATLAS_PG_TMP/data" -A trust --no-locale >"$ATLAS_PG_TMP/init.log"
"$PG_BIN/pg_ctl" -D "$ATLAS_PG_TMP/data" -l "$ATLAS_PG_TMP/server.log" -o "-k $ATLAS_PG_TMP -c listen_addresses=''" start >/dev/null
"$PG_BIN/psql" -h "$ATLAS_PG_TMP" -U "$(id -un)" -d postgres -f tests/cloud_store.sql
# Both processes contend on the same expected revision; precisely one must commit.
"$PG_BIN/psql" -h "$ATLAS_PG_TMP" -U "$(id -un)" -d postgres -v ON_ERROR_STOP=1 -c "set role service_role; select public.atlas_store_commit(1,'concurrent-a','{\"version\":1,\"cash\":\"10000\"}');" >"$ATLAS_PG_TMP/a.log" 2>&1 &
atlas_pid_a=$!
"$PG_BIN/psql" -h "$ATLAS_PG_TMP" -U "$(id -un)" -d postgres -v ON_ERROR_STOP=1 -c "set role service_role; select public.atlas_store_commit(1,'concurrent-b','{\"version\":1,\"cash\":\"10000\"}');" >"$ATLAS_PG_TMP/b.log" 2>&1 &
atlas_pid_b=$!
atlas_success=0
if wait "$atlas_pid_a"; then atlas_success=$((atlas_success+1)); fi
if wait "$atlas_pid_b"; then atlas_success=$((atlas_success+1)); fi
[ "$atlas_success" = 1 ]
echo 'PASS: simultaneous writers produce exactly one commit; temporary cluster removed on exit.'

"$PG_BIN/createdb" -h "$ATLAS_PG_TMP" -U "$(id -un)" atlas_e2e
"$PG_BIN/psql" -h "$ATLAS_PG_TMP" -U "$(id -un)" -d atlas_e2e -v ON_ERROR_STOP=1 -f database/001_cloud_store.sql >/dev/null
"$PG_BIN/psql" -h "$ATLAS_PG_TMP" -U "$(id -un)" -d atlas_e2e -v ON_ERROR_STOP=1 -f database/002_audit_chain.sql >/dev/null
PGHOST="$ATLAS_PG_TMP" PGUSER="$(id -un)" PGDATABASE=atlas_e2e PYTHONPATH=. python3 tests/postgres_worker.py
