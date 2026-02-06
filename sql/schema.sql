create table if not exists vault_items (
  id bigserial primary key,

  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),

  -- where this came from (melt, manual, import, etc)
  source text not null default 'manual',

  -- classify the virtual object to render
  item_type text not null,   -- e.g. 'junk_silver', 'bullion_bar', 'ring', 'necklace', 'bracelet', 'coin'

  -- value/size drivers
  est_value_usd numeric not null default 0,
  quantity numeric not null default 1,

  -- metal context (optional but helpful)
  metal text null,           -- 'gold','silver','platinum'
  purity numeric null,       -- e.g. 0.925
  weight_grams numeric null,

  -- exact inputs payload from Melt calc (store it whole)
  melt_inputs jsonb not null default '{}'::jsonb,

  -- per-item toggle (melt vs market) and premium pct
  premium_pct numeric not null default 0,
  view_mode text not null default 'melt' -- 'melt' or 'market'
);

create index if not exists vault_items_created_at_idx on vault_items (created_at desc);
create index if not exists vault_items_source_idx on vault_items (source);
create index if not exists vault_items_type_idx on vault_items (item_type);
