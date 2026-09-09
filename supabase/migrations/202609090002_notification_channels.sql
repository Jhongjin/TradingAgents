-- Member notification channels (Telegram first). One row per member and
-- channel. The server links a chat by a short one-time code the member sends
-- to the bot; members can read their own row, only the server writes.

create table if not exists public.notification_channels (
    id uuid primary key default gen_random_uuid(),
    user_id uuid not null references auth.users (id) on delete cascade,
    channel varchar(24) not null default 'telegram',
    external_id varchar(120),
    display_name varchar(120),
    link_code varchar(32),
    link_code_expires_at timestamptz,
    linked_at timestamptz,
    enabled boolean not null default true,
    metadata_json jsonb not null default '{}'::jsonb,
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now(),
    unique (user_id, channel)
);

create index if not exists idx_notification_channels_link_code
    on public.notification_channels (link_code);

create index if not exists idx_notification_channels_external
    on public.notification_channels (channel, external_id);

alter table public.notification_channels enable row level security;

drop policy if exists "members read own notification channels" on public.notification_channels;
create policy "members read own notification channels"
on public.notification_channels
for select
using (auth.uid() = user_id);
