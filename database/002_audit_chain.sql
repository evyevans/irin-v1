begin;
-- Separate chain retains the original migration/store protocol and covers old retained commits.
create table atlas_private.audit_chain (
 revision bigint primary key, parent_hash text not null, record_hash text not null
);
alter table atlas_private.audit_chain enable row level security;
create function atlas_private.chain_commit() returns trigger
language plpgsql security invoker set search_path='' as $$
declare parent text;
begin
 select record_hash into parent from atlas_private.audit_chain order by revision desc limit 1;
 parent:=coalesce(parent,repeat('0',64));
 insert into atlas_private.audit_chain values(new.revision,parent,
  encode(sha256(convert_to(jsonb_build_array(new.revision,new.request_id,new.state,parent)::text,'UTF8')),'hex'));
 return new;
end $$;
do $$ declare r record; parent text:=repeat('0',64); head text;
begin
 for r in select * from atlas_private.commits order by revision loop
  head:=encode(sha256(convert_to(jsonb_build_array(r.revision,r.request_id,r.state,parent)::text,'UTF8')),'hex');
  insert into atlas_private.audit_chain values(r.revision,parent,head); parent:=head;
 end loop;
end $$;
create trigger atlas_chain_commit after insert on atlas_private.commits
for each row execute function atlas_private.chain_commit();
create function public.atlas_store_audit_verify() returns jsonb
language plpgsql security invoker set search_path='' as $$
declare r record; n bigint:=0; parent text:=repeat('0',64); head text; ok boolean:=true; live atlas_private.ledger%rowtype; last_state jsonb;
begin
 perform pg_catalog.pg_advisory_xact_lock(712094132);
 for r in select c.*,a.parent_hash,a.record_hash from atlas_private.commits c
 left join atlas_private.audit_chain a using(revision) order by c.revision loop
  n:=n+1;
  head:=encode(sha256(convert_to(jsonb_build_array(r.revision,r.request_id,r.state,parent)::text,'UTF8')),'hex');
  ok:=ok and coalesce(r.revision=n and r.parent_hash=parent and r.record_hash=head,false);
  parent:=head; last_state:=r.state;
 end loop;
 select * into live from atlas_private.ledger where id=1;
 ok:=ok and (select count(*)=n from atlas_private.audit_chain)
  and case when n=0 then live.id is null else coalesce(live.revision=n and live.state=last_state,false) end;
 return jsonb_build_object('valid',ok,'revision',n,'head',parent,'coverage_from_revision',case when n>0 then 1 else null end,'legacy_prefix_unverifiable',false);
end $$;
revoke all on function atlas_private.chain_commit() from public,anon,authenticated;
revoke all on function public.atlas_store_audit_verify() from public,anon,authenticated;
grant select,insert on atlas_private.audit_chain to service_role;
grant execute on function atlas_private.chain_commit() to service_role;
grant execute on function public.atlas_store_audit_verify() to service_role;
commit;
