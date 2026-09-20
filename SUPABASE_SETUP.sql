-- Bethuel Sang Portfolio - reliable persistent storage setup

create table if not exists public.portfolio_store (
    key text primary key,
    value jsonb not null,
    updated_at timestamptz not null default now()
);

create or replace function public.set_portfolio_updated_at()
returns trigger
language plpgsql
as $$
begin
    new.updated_at = now();
    return new;
end;
$$;

drop trigger if exists portfolio_store_updated_at on public.portfolio_store;

create trigger portfolio_store_updated_at
before update on public.portfolio_store
for each row
execute function public.set_portfolio_updated_at();

-- Secret keys run as service_role. Give that role explicit table access.
grant usage on schema public to service_role;
grant select, insert, update, delete on table public.portfolio_store to service_role;

-- Keep RLS enabled. Secret/service_role server keys bypass RLS.
alter table public.portfolio_store enable row level security;

-- Persistent public portfolio assets.
insert into storage.buckets (id, name, public)
values ('portfolio-assets', 'portfolio-assets', true)
on conflict (id) do update set public = true;

drop policy if exists "Public portfolio asset reads" on storage.objects;

create policy "Public portfolio asset reads"
on storage.objects
for select
using (bucket_id = 'portfolio-assets');
