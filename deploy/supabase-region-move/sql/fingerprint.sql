-- One line per object: "<kind> <name> <fingerprint>". move.sh runs it on both
-- projects and diffs the output. :schemas is a comma-separated list.
-- Extension members are skipped: the new project ships a newer pgvector build.
-- Two equivalent forms are normalised, both produced by any dump and restore:
--   an ACL naming only the owner's full rights equals the implicit default, and
--   Postgres re-parses CHECK/index expressions and moves ::text casts around.
\pset tuples_only on
\pset format unaligned
WITH s AS (SELECT oid, nspname FROM pg_namespace WHERE nspname = ANY (string_to_array(:'schemas', ','))),
ext AS (SELECT objid FROM pg_depend WHERE deptype = 'e')
SELECT line FROM (
  -- every row of every table, order-independent
  SELECT format('data %I.%I %s', s.nspname, c.relname,
    (xpath('/row/h/text()', query_to_xml(format(
      'select count(*) || '' '' || coalesce(md5(string_agg(md5(t::text), '''' order by md5(t::text))), ''-'') as h from %I.%I t',
      s.nspname, c.relname), false, true, '')))[1]::text) AS line
  FROM pg_class c JOIN s ON s.oid = c.relnamespace WHERE c.relkind IN ('r', 'p')
  UNION ALL
  SELECT format('columns %I.%I %s', s.nspname, c.relname, md5(string_agg(
    a.attname || ':' || format_type(a.atttypid, a.atttypmod) || ':' || a.attnotnull || ':' ||
    coalesce(pg_get_expr(d.adbin, d.adrelid), ''), ',' ORDER BY a.attnum)))
  FROM pg_class c JOIN s ON s.oid = c.relnamespace
  JOIN pg_attribute a ON a.attrelid = c.oid AND a.attnum > 0 AND NOT a.attisdropped
  LEFT JOIN pg_attrdef d ON d.adrelid = c.oid AND d.adnum = a.attnum
  WHERE c.relkind IN ('r', 'p', 'v', 'm') GROUP BY s.nspname, c.relname
  UNION ALL
  SELECT format('relation %I.%I kind=%s owner=%s rls=%s/%s acl=%s', s.nspname, c.relname, c.relkind,
    pg_get_userbyid(c.relowner), c.relrowsecurity, c.relforcerowsecurity,
    coalesce(nullif(c.relacl, acldefault((CASE c.relkind WHEN 'S' THEN 's' ELSE 'r' END)::"char", c.relowner))::text, 'default'))
  FROM pg_class c JOIN s ON s.oid = c.relnamespace
  WHERE c.relkind IN ('r', 'p', 'v', 'm', 'S', 'f') AND c.oid NOT IN (SELECT objid FROM ext)
  UNION ALL
  SELECT format('function %I.%s(%s) src=%s secdef=%s config=%s owner=%s acl=%s', s.nspname, p.proname,
    pg_get_function_identity_arguments(p.oid), md5(p.prosrc), p.prosecdef, coalesce(p.proconfig::text, '-'),
    pg_get_userbyid(p.proowner), coalesce(nullif(p.proacl, acldefault('f', p.proowner))::text, 'default'))
  FROM pg_proc p JOIN s ON s.oid = p.pronamespace WHERE p.oid NOT IN (SELECT objid FROM ext)
  UNION ALL
  SELECT format('policy %I.%I.%I %s', schemaname, tablename, policyname,
    md5(cmd || permissive || roles::text || coalesce(qual, '') || coalesce(with_check, '')))
  FROM pg_policies WHERE schemaname IN (SELECT nspname FROM s)
  UNION ALL
  SELECT format('trigger %I.%I %s', c.relname, t.tgname, md5(pg_get_triggerdef(t.oid)))
  FROM pg_trigger t JOIN pg_class c ON c.oid = t.tgrelid JOIN s ON s.oid = c.relnamespace WHERE NOT t.tgisinternal
  UNION ALL
  SELECT format('index %I.%I %s', schemaname, indexname, md5(regexp_replace(indexdef, '::(text|character varying)(\[\])?|[()[:space:]]', '', 'g')))
  FROM pg_indexes WHERE schemaname IN (SELECT nspname FROM s)
  UNION ALL
  SELECT format('constraint %I.%I %s', c.relname, k.conname, md5(regexp_replace(pg_get_constraintdef(k.oid), '::(text|character varying)(\[\])?|[()[:space:]]', '', 'g')))
  FROM pg_constraint k JOIN pg_class c ON c.oid = k.conrelid JOIN s ON s.oid = c.relnamespace
  UNION ALL
  SELECT format('type %I.%I %s', s.nspname, t.typname, t.typtype)
  FROM pg_type t JOIN s ON s.oid = t.typnamespace
  WHERE t.typtype IN ('e', 'd', 'r') AND t.oid NOT IN (SELECT objid FROM ext)
  UNION ALL
  SELECT format('default-acl %s %s %s %s', pg_get_userbyid(d.defaclrole), s.nspname, d.defaclobjtype, d.defaclacl)
  FROM pg_default_acl d JOIN s ON s.oid = d.defaclnamespace
  UNION ALL
  SELECT format('schema %I owner=%s acl=%s', s.nspname, pg_get_userbyid(n.nspowner), coalesce(nullif(n.nspacl, acldefault('n', n.nspowner))::text, 'default'))
  FROM pg_namespace n JOIN s ON s.oid = n.oid
) lines ORDER BY line;
