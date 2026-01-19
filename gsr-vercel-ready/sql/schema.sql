-- Run this once in your Postgres database (e.g., Neon)
create table if not exists gsr_daily (
  d date primary key,
  gold_usd numeric not null,
  silver_usd numeric not null,
  gsr numeric not null,
  fetched_at_utc timestamptz not null default now(),
  source text not null default 'gold-api.com'
);

create index if not exists gsr_daily_fetched_at_idx on gsr_daily (fetched_at_utc desc);
