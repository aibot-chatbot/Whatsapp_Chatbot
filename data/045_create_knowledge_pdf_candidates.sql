-- Temporary preflight records for supporting PDF validation.
-- These rows are not normal knowledge sources and must not be shown with
-- knowledge_files until a candidate is explicitly confirmed and ingested.

create table if not exists public.knowledge_pdf_candidates (
    id uuid primary key default gen_random_uuid(),
    company_id bigint not null,
    chatbot_id bigint not null,
    original_file_name text not null,
    safe_file_name text not null,
    temp_file_path text not null,
    file_size bigint not null default 0,
    file_sha256 text not null,
    content_sha256 text,
    primary_content_sha256 text,
    primary_file_id bigint,
    relevance_score numeric(6, 5),
    threshold numeric(6, 5),
    validation_status text not null default 'pending',
    passed boolean not null default false,
    duplicate_status text not null default 'none',
    result_metadata jsonb not null default '{}'::jsonb,
    error_code text,
    error_message text,
    created_by_user_id bigint,
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now(),
    expires_at timestamptz not null,
    confirmed_at timestamptz,
    ingested_knowledge_file_id bigint,
    constraint knowledge_pdf_candidates_validation_status_check check (
        validation_status in (
            'pending',
            'validating',
            'validated_passed',
            'validated_failed',
            'confirming',
            'ingested_supporting',
            'ingest_failed',
            'cancelled',
            'expired'
        )
    ),
    constraint knowledge_pdf_candidates_duplicate_status_check check (
        duplicate_status in (
            'none',
            'exact_content_duplicate',
            'possible_near_duplicate'
        )
    ),
    constraint knowledge_pdf_candidates_score_check check (
        relevance_score is null or (relevance_score >= 0 and relevance_score <= 1)
    ),
    constraint knowledge_pdf_candidates_threshold_check check (
        threshold is null or (threshold >= 0 and threshold <= 1)
    )
);

alter table public.knowledge_pdf_candidates
    add constraint knowledge_pdf_candidates_company_fk
    foreign key (company_id)
    references public.companies(id)
    on delete cascade;

alter table public.knowledge_pdf_candidates
    add constraint knowledge_pdf_candidates_chatbot_fk
    foreign key (chatbot_id)
    references public.chatbots(id)
    on delete cascade;

alter table public.knowledge_pdf_candidates
    add constraint knowledge_pdf_candidates_primary_file_fk
    foreign key (primary_file_id)
    references public.knowledge_files(id)
    on delete set null;

alter table public.knowledge_pdf_candidates
    add constraint knowledge_pdf_candidates_ingested_file_fk
    foreign key (ingested_knowledge_file_id)
    references public.knowledge_files(id)
    on delete set null;

alter table public.knowledge_pdf_candidates
    add constraint knowledge_pdf_candidates_created_by_user_fk
    foreign key (created_by_user_id)
    references public.users(id)
    on delete set null;

alter table public.knowledge_files
    add column if not exists source_pdf_candidate_id uuid;

alter table public.knowledge_files
    add column if not exists original_file_name text;

alter table public.knowledge_files
    add constraint knowledge_files_source_pdf_candidate_fk
    foreign key (source_pdf_candidate_id)
    references public.knowledge_pdf_candidates(id)
    on delete set null;

create unique index if not exists knowledge_files_source_pdf_candidate_unique_idx
    on public.knowledge_files (source_pdf_candidate_id)
    where source_pdf_candidate_id is not null;

create index if not exists knowledge_pdf_candidates_company_chatbot_idx
    on public.knowledge_pdf_candidates (company_id, chatbot_id, created_at desc);

create index if not exists knowledge_pdf_candidates_status_expiry_idx
    on public.knowledge_pdf_candidates (validation_status, expires_at);

create index if not exists knowledge_pdf_candidates_file_hash_idx
    on public.knowledge_pdf_candidates (chatbot_id, file_sha256);

create index if not exists knowledge_pdf_candidates_content_hash_idx
    on public.knowledge_pdf_candidates (chatbot_id, content_sha256);

alter table public.knowledge_pdf_candidates enable row level security;

revoke all privileges on table public.knowledge_pdf_candidates
    from public, anon, authenticated;

grant select, insert, update, delete on table public.knowledge_pdf_candidates
    to service_role;

comment on table public.knowledge_pdf_candidates is
    'Temporary service-role managed supporting PDF preflight candidates. Rows are not normal knowledge sources until confirmed and ingested.';

comment on column public.knowledge_pdf_candidates.temp_file_path is
    'Internal server-side temporary storage path. Never expose directly to browser clients.';
