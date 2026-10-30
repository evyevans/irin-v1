\set ON_ERROR_STOP on
create role anon nologin;
create role authenticated nologin;
create role service_role nologin bypassrls;
\ir ../database/001_cloud_store.sql
\ir ../database/002_audit_chain.sql
do $$ begin
 if has_function_privilege('anon','public.atlas_store_read()','execute') then raise exception 'anonymous read exposed'; end if;
 if has_function_privilege('authenticated','public.atlas_store_commit(bigint,text,jsonb)','execute') then raise exception 'authenticated write exposed'; end if;
 if has_schema_privilege('anon','atlas_private','usage') then raise exception 'private schema exposed'; end if;
end $$;
set role anon;
do $$ begin
 begin perform public.atlas_store_read();raise exception 'anon RPC allowed';exception when insufficient_privilege then null;end;
 begin perform state from atlas_private.ledger;raise exception 'anon table allowed';exception when insufficient_privilege then null;end;
end $$;
reset role;
set role authenticated;
do $$ begin
 begin perform public.atlas_store_commit(0,'unauthorized','{"version":1,"cash":"100"}');raise exception 'authenticated RPC allowed';exception when insufficient_privilege then null;end;
end $$;
reset role;
set role service_role;
select public.atlas_store_commit(0,'initial','{"version":1,"cash":"10000"}');
select public.atlas_store_commit(0,'initial','{"version":1,"cash":"10000"}');
do $$ begin
 if (public.atlas_store_read()->>'revision')::int<>1 then raise exception 'duplicate commit'; end if;
 begin perform public.atlas_store_commit(0,'stale','{"version":1,"cash":"10000"}');raise exception 'stale write accepted';exception when serialization_failure then null; end;
 begin perform public.atlas_store_commit(1,'initial','{"version":1,"cash":"9999"}');raise exception 'key mismatch accepted';exception when serialization_failure then null; end;
 begin perform public.atlas_store_commit(1,'negative','{"version":1,"cash":"-1"}');raise exception 'negative cash accepted';exception when check_violation then null; end;
 begin perform public.atlas_store_commit(1,'empty','{}');raise exception 'missing required fields accepted';exception when check_violation then null; end;
 begin perform public.atlas_store_commit(1,'nan','{"version":1,"cash":"NaN"}');raise exception 'NaN accepted';exception when check_violation then null; end;
 if has_table_privilege('service_role','atlas_private.commits','delete') then raise exception 'audit delete granted'; end if;
end $$;
reset role;
select 'PASS: fresh migration, role boundaries, idempotency, revision conflict, cash constraint and audit privileges';

set role service_role;
do $$ begin
 if (public.atlas_store_audit_verify()->>'valid')::boolean is not true then raise exception 'audit verification failed'; end if;
 if has_function_privilege('anon','public.atlas_store_audit_verify()','execute') then raise exception 'anonymous audit exposed'; end if;
end $$;
reset role;
-- A database owner can tamper: verification must detect the change.
update atlas_private.commits set state='{"version":1,"cash":"9999"}' where revision=1;
set role service_role;
do $$ begin
 if (public.atlas_store_audit_verify()->>'valid')::boolean is not false then raise exception 'tampering undetected'; end if;
end $$;
reset role;
update atlas_private.commits set state='{"version":1,"cash":"10000"}' where revision=1;
