begin;
-- One owner-controlled paper installation per project. No tenant-facing public data API.
create schema atlas_private;
revoke all on schema atlas_private from public;
create table atlas_private.ledger (
 id integer primary key check(id=1), revision bigint not null check(revision>0),
 state jsonb not null check((jsonb_typeof(state)='object' and state ? 'version' and state ? 'cash' and state->>'version'='1' and jsonb_typeof(state->'cash')='string' and (state->>'cash') ~ '^[0-9]+([.][0-9]+)?$' and (state->>'cash')::numeric between 0 and 1e18) is true)
);
create table atlas_private.commits (
 request_id text primary key check(length(request_id) between 1 and 160),
 revision bigint unique not null, state jsonb not null, committed_at timestamptz not null default clock_timestamp()
);
alter table atlas_private.ledger enable row level security;
alter table atlas_private.commits enable row level security;
create function public.atlas_store_read() returns jsonb language sql security invoker set search_path='' as $$
 select coalesce((select jsonb_build_object('revision',revision,'state',state) from atlas_private.ledger where id=1),'{"revision":0,"state":null}'::jsonb)
$$;
create function public.atlas_store_commit(expected_revision bigint,request_id text,new_state jsonb) returns bigint
 language plpgsql security invoker set search_path='' as $$
declare prior atlas_private.commits%rowtype; current_revision bigint;
begin
 -- Serializes empty-store creation as well as subsequent transitions for this installation.
 perform pg_catalog.pg_advisory_xact_lock(712094132);
 select * into prior from atlas_private.commits c where c.request_id=atlas_store_commit.request_id;
 if found then
  if prior.state<>new_state then raise exception 'idempotency conflict' using errcode='40001'; end if;
  return prior.revision;
 end if;
 select revision into current_revision from atlas_private.ledger where id=1;
 if coalesce(current_revision,0)<>expected_revision then raise exception 'revision conflict' using errcode='40001'; end if;
 insert into atlas_private.ledger values(1,expected_revision+1,new_state)
 on conflict(id) do update set revision=excluded.revision,state=excluded.state;
 insert into atlas_private.commits values(request_id,expected_revision+1,new_state,clock_timestamp());
 return expected_revision+1;
end $$;
revoke all on function public.atlas_store_read() from public,anon,authenticated;
revoke all on function public.atlas_store_commit(bigint,text,jsonb) from public,anon,authenticated;
grant usage on schema atlas_private to service_role;
grant select,insert,update on atlas_private.ledger to service_role;
grant select,insert on atlas_private.commits to service_role;
grant execute on function public.atlas_store_read() to service_role;
grant execute on function public.atlas_store_commit(bigint,text,jsonb) to service_role;
commit;
