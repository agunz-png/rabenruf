create table if not exists public.herold_update_requests (
  id uuid primary key default gen_random_uuid(),
  event_id text not null check (event_id ~ '^[A-Za-z0-9_-]{1,120}$'),
  old_event jsonb not null,
  proposed_event jsonb not null,
  status text not null default 'pending'
    check (status = any (array['pending'::text, 'approved'::text, 'rejected'::text])),
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create unique index if not exists herold_update_requests_one_pending_per_event
  on public.herold_update_requests (event_id)
  where status = 'pending';

create index if not exists herold_update_requests_pending_created_at
  on public.herold_update_requests (created_at desc)
  where status = 'pending';

alter table public.herold_update_requests enable row level security;
revoke all on table public.herold_update_requests from anon, authenticated;
grant all on table public.herold_update_requests to service_role;
