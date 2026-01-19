# Gold-to-Silver Ratio (GSR) — Vercel + Python + Daily History

This project stores a **daily** Gold-to-Silver Ratio snapshot in Postgres using:

- **Vercel Cron Jobs** → hits `/api/cron_gsr` once per day
- **Vercel Python Functions** → fetches spot prices + writes to DB
- A Postgres database (recommended: **Neon**) via `DATABASE_URL`

## 1) Create a Postgres database

1. Create a Postgres DB (Neon is a good choice).
2. Copy the connection string as `DATABASE_URL`.
3. Run the schema once (in your DB SQL console):

```sql
-- from sql/schema.sql
create table if not exists gsr_daily (
  d date primary key,
  gold_usd numeric not null,
  silver_usd numeric not null,
  gsr numeric not null,
  fetched_at_utc timestamptz not null default now(),
  source text not null default 'gold-api.com'
);

create index if not exists gsr_daily_fetched_at_idx on gsr_daily (fetched_at_utc desc);
```

## 2) Create a GitHub repo and push

```bash
git init
git add -A
git commit -m "Initial GSR app"
# create repo on GitHub, then:
git remote add origin <YOUR_REPO_URL>
git push -u origin main
```

## 3) Import into Vercel

1. Vercel Dashboard → **Add New → Project** → Import your GitHub repo.
2. Set Environment Variables (Project → Settings → Environment Variables):

- `DATABASE_URL` = your Postgres connection string
- `CRON_SECRET` = a long random string

Add env vars for **Production** (and optionally Preview).

## 4) Deploy to Production (important)

Vercel cron jobs are invoked only for **Production** deployments.

After your first production deploy, run the cron endpoint once manually to seed data:

- Visit:
  - `https://<your-domain>/api/cron_gsr?secret=<CRON_SECRET>`

If successful, `GET /api/latest` and the homepage will show values.

## 5) Change the daily schedule

Edit `vercel.json`:

```json
{
  "crons": [
    { "path": "/api/cron_gsr", "schedule": "5 0 * * *" }
  ]
}
```

Cron schedules are in **UTC**.

## Local development

You can run the static UI locally, but Python serverless functions + cron are Vercel features.

```bash
python3 -m http.server 5173
# open http://localhost:5173
```

## Endpoints

- `GET /api/latest` → latest snapshot + full history
- `GET /api/cron_gsr` → protected; called by Vercel Cron. Requires `CRON_SECRET`.

## Notes

- This uses `pg8000` (pure Python) for Postgres.
- Spot prices are fetched from `https://api.gold-api.com/price/XAU` and `/price/XAG`.
