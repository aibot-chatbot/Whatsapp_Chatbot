#!/usr/bin/env bash
# Copy the production database from Supabase Seoul (ap-northeast-2) to Singapore
# (ap-southeast-1). Runbook: README.md beside this file.
#
# Nothing here writes to the old project. Every step that writes to the new one
# is re-runnable: load-data truncates before it copies.
set -euo pipefail

OLD_REF=parjsxypengvubziwwjp
APP_SCHEMAS=(-n public -n supabase_migrations)
SECRETS_DIR="${OMNEXA_SECRETS_DIR:-$USERPROFILE/.omnexa-secrets}"
# Dumps hold customer data: they live beside the secrets, never in the repo.
WORK_DIR="$SECRETS_DIR/supabase-move"
HERE="$(cd "$(dirname "$0")" && pwd)"
export PATH="$PATH:/c/Program Files/PostgreSQL/18/bin"
PSQL=(psql -X -q -v ON_ERROR_STOP=1)
# Binary archives: on Windows a plain-text dump goes through text-mode I/O, which
# stripped the carriage returns inside 42 function bodies on the first dry run.
RESTORE=(pg_restore --exit-on-error --single-transaction)

env_value() { # <file> <key> -> value, surrounding quotes and CR stripped
  grep -m1 "^$2=" "$1" | cut -d= -f2- | sed -e 's/\r$//' -e "s/^[\"']//" -e "s/[\"']\$//"
}

load_secrets() {
  local f="$SECRETS_DIR/supabase-sg.env"
  [ -f "$f" ] || { echo "Missing $f - see README step 1." >&2; exit 1; }
  OLD_DB_PASSWORD=$(env_value "$f" OLD_DB_PASSWORD)
  NEW_REF=$(env_value "$f" NEW_PROJECT_REF)
  NEW_DB_PASSWORD=$(env_value "$f" NEW_DB_PASSWORD)
  export N8N_DB_PASSWORD; N8N_DB_PASSWORD=$(env_value "$SECRETS_DIR/n8n.env" DB_POSTGRESDB_PASSWORD)
  local v; for v in OLD_DB_PASSWORD NEW_REF NEW_DB_PASSWORD N8N_DB_PASSWORD; do
    [ -n "${!v}" ] || { echo "$v is empty." >&2; exit 1; }
  done
  [ "$NEW_REF" != "$OLD_REF" ] || { echo "NEW_PROJECT_REF is the old project." >&2; exit 1; }
}

conninfo() { # <ref> <user>; direct connection (IPv6), TLS required
  echo "host=db.$1.supabase.co port=5432 dbname=postgres user=$2 sslmode=require connect_timeout=15"
}
# The app schemas are read as postgres. n8n's schema is read as agent_n8n, which
# owns it: postgres has no privileges there, and the old project is not changed.
old_pg()  { local c=$1; shift; PGPASSWORD="$OLD_DB_PASSWORD" "$c" "$@" -d "$(conninfo "$OLD_REF" postgres)"; }
old_n8n() { local c=$1; shift; PGPASSWORD="$N8N_DB_PASSWORD" "$c" "$@" -d "$(conninfo "$OLD_REF" agent_n8n)"; }
new_pg()  { local c=$1; shift; PGPASSWORD="$NEW_DB_PASSWORD" "$c" "$@" -d "$(conninfo "$NEW_REF" postgres)"; }
new_n8n() { local c=$1; shift; PGPASSWORD="$N8N_DB_PASSWORD" "$c" "$@" -d "$(conninfo "$NEW_REF" agent_n8n)"; }

latest_dir() {
  [ -f "$WORK_DIR/LATEST" ] || { echo "No dump yet - run: $0 dump" >&2; exit 1; }
  cat "$WORK_DIR/LATEST"
}

fingerprint() { # <pg-runner> <n8n-runner>: every row, grant, function, policy...
  "$1" "${PSQL[@]}" -v schemas=public,supabase_migrations -f "$HERE/sql/fingerprint.sql"
  "$2" "${PSQL[@]}" -v schemas=agent_n8n -f "$HERE/sql/fingerprint.sql"
}

cmd_preflight() {
  old_pg  "${PSQL[@]}" -At -c "select 'old  postgres   ' || current_setting('server_version')"
  old_n8n "${PSQL[@]}" -At -c "select 'old  agent_n8n  ' || count(*) || ' n8n tables' from pg_tables where schemaname = 'agent_n8n'"
  new_pg  "${PSQL[@]}" -At -c "select 'new  postgres   ' || current_setting('server_version') || ', ' ||
      (select count(*) from pg_tables where schemaname = 'public') || ' public tables'"
}

cmd_dump() {
  local dir; dir="$WORK_DIR/$(date +%Y%m%d-%H%M%S)"; mkdir -p "$dir"
  local opts=(-Fc --no-statistics)
  old_pg  pg_dump "${opts[@]}" --schema-only "${APP_SCHEMAS[@]}" -f "$dir/app-schema.dump"
  old_pg  pg_dump "${opts[@]}" --data-only   "${APP_SCHEMAS[@]}" -f "$dir/app-data.dump"
  old_n8n pg_dump "${opts[@]}" --schema-only -n agent_n8n -f "$dir/n8n-schema.dump"
  old_n8n pg_dump "${opts[@]}" --data-only   -n agent_n8n -f "$dir/n8n-data.dump"
  # public already exists in every project. postgres may neither own objects as
  # supabase_admin nor change its default privileges; a fresh project already
  # carries the same platform defaults (compared on both projects 2026-10-10).
  pg_restore -l "$dir/app-schema.dump" \
    | grep -v -E '^[0-9]+; [0-9]+ [0-9]+ SCHEMA - public | supabase_admin$' > "$dir/app-schema.list"
  echo "$dir" > "$WORK_DIR/LATEST"
  echo "Dumped to $dir"
}

cmd_prepare_new() { # once, on the fresh project: role, grants, schema
  local dir; dir=$(latest_dir)
  local tables
  tables=$(new_pg "${PSQL[@]}" -At -c "select count(*) from pg_tables where schemaname = 'public'")
  if [ "$tables" != "0" ]; then
    echo "New project already has $tables public tables; prepare-new runs once, on a fresh project." >&2
    exit 1
  fi
  new_pg "${PSQL[@]}" -f "$HERE/sql/before-schema.sql"
  new_pg "${RESTORE[@]}" --schema-only -L "$dir/app-schema.list" "$dir/app-schema.dump"
  new_pg "${RESTORE[@]}" --schema-only "$dir/n8n-schema.dump"
  new_pg "${PSQL[@]}" -f "$HERE/sql/after-restore.sql"
  echo "Schema restored on $NEW_REF"
}

load_archive() { # <data archive>: one transaction, triggers and FK checks off
  # As Supabase's own restore guide does; n8n has circular foreign keys that no
  # load order satisfies. Supabase refuses this setting as a connection option,
  # so it is set inside the session. COPY data escapes \r, so the text pipe is safe.
  { echo "SET session_replication_role = replica;"; pg_restore --data-only -f - "$1"; } \
    | new_pg "${PSQL[@]}" --single-transaction -f -
}

cmd_load_data() { # empty the copy, then load the latest dump (dry run and cutover)
  local dir; dir=$(latest_dir)
  new_pg "${PSQL[@]}" -f "$HERE/sql/before-data.sql"
  load_archive "$dir/app-data.dump"
  load_archive "$dir/n8n-data.dump"
  new_pg "${PSQL[@]}" -f "$HERE/sql/after-restore.sql"
  echo "Data loaded from $dir"
}

cmd_verify() { # exact only while the old project takes no writes (the cutover)
  local dir; dir=$(latest_dir)
  fingerprint old_pg old_n8n > "$dir/old-fingerprint.txt"
  fingerprint new_pg new_n8n > "$dir/new-fingerprint.txt"
  if diff "$dir/old-fingerprint.txt" "$dir/new-fingerprint.txt" > "$dir/fingerprint.diff"; then
    echo "OK: $(grep -c '^data ' "$dir/new-fingerprint.txt") tables identical row for row;" \
      "$(wc -l < "$dir/new-fingerprint.txt") objects compared (grants, functions, policies, indexes...)"
  else
    echo "MISMATCH ($(grep -c '^[<>]' "$dir/fingerprint.diff") lines): $dir/fingerprint.diff" >&2
    grep '^[<>]' "$dir/fingerprint.diff" | cut -c1-160 | head -20 >&2
    exit 1
  fi
  # n8n rejects unverified certificates (DB_POSTGRESDB_SSL_CA); prove its CA file
  # also signs the new server, or n8n will not boot after the switch.
  PGPASSWORD="$N8N_DB_PASSWORD" psql -X -At -c "select 'OK: n8n CA verifies the new server'" \
    -d "host=db.$NEW_REF.supabase.co port=5432 dbname=postgres user=agent_n8n sslmode=verify-full sslrootcert=$(cygpath -m "$SECRETS_DIR/supabase-prod-ca-2021.crt") connect_timeout=15"
}

cmd_storage() {
  /c/Users/Vincent/Desktop/Whatsapp_Chatbot/.venv/Scripts/python.exe -I \
    "$(cygpath -w "$HERE/copy_storage.py")" "$(cygpath -w "$SECRETS_DIR")" "$OLD_REF" "$NEW_REF"
}

case "${1:-}" in
  preflight|dump|prepare-new|load-data|verify|storage) load_secrets; "cmd_${1//-/_}" ;;
  *) echo "usage: $0 preflight|dump|prepare-new|load-data|verify|storage" >&2; exit 2 ;;
esac
