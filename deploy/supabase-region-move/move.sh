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

counts() { # <runner> <schema...>: "schema.table rows" per line, exact counts
  local runner=$1; shift
  local list; list=$(printf "'%s'," "$@"); list=${list%,}
  "$runner" "${PSQL[@]}" -At -c "select format('%s.%s %s', schemaname, tablename,
      (xpath('/row/c/text()', query_to_xml(format('select count(*) as c from %I.%I',
        schemaname, tablename), false, true, '')))[1]::text)
    from pg_tables where schemaname in ($list) order by 1"
}

cmd_preflight() {
  old_pg  "${PSQL[@]}" -At -c "select 'old  postgres   ' || current_setting('server_version')"
  old_n8n "${PSQL[@]}" -At -c "select 'old  agent_n8n  ' || count(*) || ' n8n tables' from pg_tables where schemaname = 'agent_n8n'"
  new_pg  "${PSQL[@]}" -At -c "select 'new  postgres   ' || current_setting('server_version') || ', ' ||
      (select count(*) from pg_tables where schemaname = 'public') || ' public tables'"
}

cmd_dump() {
  local dir; dir="$WORK_DIR/$(date +%Y%m%d-%H%M%S)"; mkdir -p "$dir"
  local opts=(--no-statistics --quote-all-identifiers)
  old_pg  pg_dump "${opts[@]}" --schema-only "${APP_SCHEMAS[@]}" -f "$dir/app-schema.sql"
  old_pg  pg_dump "${opts[@]}" --data-only   "${APP_SCHEMAS[@]}" -f "$dir/app-data.sql"
  old_n8n pg_dump "${opts[@]}" --schema-only -n agent_n8n -f "$dir/n8n-schema.sql"
  old_n8n pg_dump "${opts[@]}" --data-only   -n agent_n8n -f "$dir/n8n-data.sql"
  # public already exists in every project; objects Supabase created as
  # supabase_admin cannot be handed back to it by postgres.
  sed -i -e '/^CREATE SCHEMA "public";/d' -e '/OWNER TO "supabase_admin";/d' "$dir/app-schema.sql"
  { counts old_pg public supabase_migrations; counts old_n8n agent_n8n; } > "$dir/old-counts.txt"
  echo "$dir" > "$WORK_DIR/LATEST"
  echo "Dumped to $dir ($(wc -l < "$dir/old-counts.txt") tables counted)"
}

cmd_prepare_new() { # once, on the fresh project: role, grants, schema
  local dir; dir=$(latest_dir)
  local tables
  tables=$(new_pg "${PSQL[@]}" -At -c "select count(*) from pg_tables where schemaname = 'public'")
  if [ "$tables" != "0" ]; then
    echo "New project already has $tables public tables; prepare-new runs once, on a fresh project." >&2
    exit 1
  fi
  new_pg "${PSQL[@]}" --single-transaction \
    -f "$HERE/sql/before-schema.sql" -f "$dir/app-schema.sql" -f "$dir/n8n-schema.sql" \
    -f "$HERE/sql/after-restore.sql"
  echo "Schema restored on $NEW_REF"
}

cmd_load_data() { # empty the copy, then load the latest dump (dry run and cutover)
  local dir; dir=$(latest_dir)
  new_pg "${PSQL[@]}" --single-transaction \
    -f "$HERE/sql/before-data.sql" -f "$dir/app-data.sql" -f "$dir/n8n-data.sql" \
    -f "$HERE/sql/after-restore.sql"
  echo "Data loaded from $dir"
}

cmd_verify() {
  local dir; dir=$(latest_dir)
  { counts new_pg public supabase_migrations; counts new_n8n agent_n8n; } > "$dir/new-counts.txt"
  if diff -u "$dir/old-counts.txt" "$dir/new-counts.txt"; then
    echo "OK: $(wc -l < "$dir/new-counts.txt") tables, every row count matches"
  else
    echo "MISMATCH: see the diff above" >&2
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
