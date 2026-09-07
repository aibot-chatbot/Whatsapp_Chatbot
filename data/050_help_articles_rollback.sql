-- Reverses 050_help_articles.sql. Feedback first: it holds the foreign key.
begin;
drop table if exists public.help_article_feedback;
drop table if exists public.help_articles;
commit;
