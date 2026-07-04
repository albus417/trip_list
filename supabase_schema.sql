-- TripList final schema: login + shared groups + cloud JSON data
-- Run this in Supabase SQL Editor.

create extension if not exists pgcrypto;

drop table if exists trip_group_data cascade;
drop table if exists trip_group_members cascade;
drop table if exists trip_groups cascade;

create table trip_groups (
  id uuid primary key default gen_random_uuid(),
  name text not null default '旅行グループ',
  invite_code text not null unique,
  passcode_hash text not null,
  created_by uuid not null references auth.users(id) on delete cascade,
  created_at timestamptz not null default now()
);

create table trip_group_members (
  group_id uuid not null references trip_groups(id) on delete cascade,
  user_id uuid not null references auth.users(id) on delete cascade,
  role text not null default 'member' check (role in ('admin','member')),
  joined_at timestamptz not null default now(),
  primary key (group_id, user_id)
);

create table trip_group_data (
  group_id uuid primary key references trip_groups(id) on delete cascade,
  trips jsonb not null default '[]'::jsonb,
  settings jsonb not null default '{}'::jsonb,
  updated_at timestamptz not null default now()
);

alter table trip_groups enable row level security;
alter table trip_group_members enable row level security;
alter table trip_group_data enable row level security;

create policy "logged in users can create groups"
on trip_groups for insert
to authenticated
with check (auth.uid() = created_by);

create policy "logged in users can lookup groups by invite"
on trip_groups for select
to authenticated
using (true);

create policy "admins can update groups"
on trip_groups for update
to authenticated
using (
  exists (
    select 1 from trip_group_members m
    where m.group_id = id and m.user_id = auth.uid() and m.role = 'admin'
  )
)
with check (
  exists (
    select 1 from trip_group_members m
    where m.group_id = id and m.user_id = auth.uid() and m.role = 'admin'
  )
);

create policy "users can view their memberships"
on trip_group_members for select
to authenticated
using (
  user_id = auth.uid()
  or exists (
    select 1 from trip_group_members mine
    where mine.group_id = trip_group_members.group_id and mine.user_id = auth.uid()
  )
);

create policy "users can join groups as themselves"
on trip_group_members for insert
to authenticated
with check (user_id = auth.uid());

create policy "members can read group data"
on trip_group_data for select
to authenticated
using (
  exists (
    select 1 from trip_group_members m
    where m.group_id = trip_group_data.group_id and m.user_id = auth.uid()
  )
);

create policy "members can insert group data"
on trip_group_data for insert
to authenticated
with check (
  exists (
    select 1 from trip_group_members m
    where m.group_id = trip_group_data.group_id and m.user_id = auth.uid()
  )
);

create policy "members can update group data"
on trip_group_data for update
to authenticated
using (
  exists (
    select 1 from trip_group_members m
    where m.group_id = trip_group_data.group_id and m.user_id = auth.uid()
  )
)
with check (
  exists (
    select 1 from trip_group_members m
    where m.group_id = trip_group_data.group_id and m.user_id = auth.uid()
  )
);
