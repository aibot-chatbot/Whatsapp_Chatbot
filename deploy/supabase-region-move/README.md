# Move the database from Seoul to Singapore

The app runs in Singapore (Fly `sin`) but Supabase project `parjsxypengvubziwwjp`
is in Seoul (`ap-northeast-2`). One AI reply makes ~32 database calls in a row at
~124 ms each, so ~4 s of every reply is distance. A Singapore project
(`ap-southeast-1`) cuts each call to a few ms.

Supabase cannot change a project's region. The documented way is a new project
plus a dump and restore ([Change Project Region](https://supabase.com/docs/guides/troubleshooting/change-project-region-eWJo5Z)).

What moves: schemas `public` and `supabase_migrations` (app), schema `agent_n8n`
and role `agent_n8n` (n8n), and Storage bucket `landing` (46 public images).
What does not need moving: auth users (0), edge functions, cron jobs and realtime
(none used).

## 1. One-time setup

**Owner of the Supabase org "Jackhan":**

1. New project: org **Jackhan**, name `AI Chatbot SG`, region **Southeast Asia (Singapore)**.
   Use *Generate a password* (letters and digits only).
2. Old project > Project Settings > Database > **Reset database password**. Safe: the
   app and worker use API keys and n8n logs in as `agent_n8n`, never `postgres`.
3. Send Vincent privately: the new project ref, both database passwords, and the new
   project's service key (Settings > API Keys > *Legacy* `service_role` if shown,
   otherwise the `secret` key).

**Vincent:** create `%USERPROFILE%\.omnexa-secrets\supabase-sg.env` (never commit it):

```
OLD_DB_PASSWORD=
NEW_PROJECT_REF=
NEW_DB_PASSWORD=
NEW_SERVICE_ROLE_KEY=
```

## 2. Dry run (no downtime)

From Git Bash in this folder. Dumps go to `~/.omnexa-secrets/supabase-move/`.

```bash
./move.sh preflight     # both databases reachable
./move.sh dump          # read-only on the old project
./move.sh prepare-new   # once: role, grants, schema on the fresh project
./move.sh load-data     # empties the copy, then loads the dump
./move.sh verify        # every table's row count matches, n8n's TLS CA works
./move.sh storage       # copies buckets, checks served headers match
```

Then, before the cutover:

- Prove the new key works with the app's client (one read through `supabase-py`).
- Point the image URLs in `frontend/*.html` at the new ref and commit. This is
  safe as soon as `storage` has run: both projects then serve the same files.

## 3. Cutover (~15-20 min without AI replies)

Run late at night. Telegram and Meta redeliver missed webhooks; WaSender may not.

1. Stop every writer, so the final dump is complete:
   ```bash
   for app in aibot-chatbot-my aibot-agent-worker-my aibot-agent-n8n-my; do
     for id in $(fly machines list -q -a $app); do fly machine stop $id -a $app; done
   done
   ```
2. Final copy: `./move.sh dump && ./move.sh load-data && ./move.sh verify && ./move.sh storage`
3. Stage the new settings (`fly secrets import --stage -a <app>`, values on stdin,
   never on the command line):
   - `aibot-chatbot-my` and `aibot-agent-worker-my`: `SUPABASE_URL`, `SUPABASE_SERVICE_ROLE_KEY`
   - `aibot-agent-n8n-my`: `DB_POSTGRESDB_HOST=db.<new-ref>.supabase.co`
4. Release: `fly deploy --ha=false -a aibot-chatbot-my` from the release worktree
   (it must contain the live commit, see the release-ancestry check), then
   `fly secrets deploy` for the worker and n8n, and `fly machine start` anything
   still stopped.
5. Smoke test: `/` returns 200, a Telegram message gets an AI reply, the login and
   landing images load, n8n's editor opens, the worker logs no database errors.
6. Update your local `.env` and tell teammates to update theirs.

## 4. Rollback

Restore the old `SUPABASE_URL`, `SUPABASE_SERVICE_ROLE_KEY` and n8n host, then
redeploy the previous release image (`fly releases --image -a aibot-chatbot-my`).
Anything written in Singapore after the switch is not in Seoul.

## Afterwards

Leave the Seoul project untouched for at least a week as the fallback. Pausing or
deleting it is the org owner's decision. Delete `~/.omnexa-secrets/supabase-move/`
once the move is confirmed: the dumps contain customer data.
