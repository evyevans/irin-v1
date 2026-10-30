"""Atomic revisioned local store; the cloud gateway exposes the same contract."""

import hashlib, json, sqlite3
from contextlib import closing


class Conflict(RuntimeError):
    pass


def encoded(state):
    return json.dumps(state, sort_keys=True, allow_nan=False, separators=(",", ":"))


def chain_hash(revision, key, payload, parent):
    return hashlib.sha256(
        encoded([revision, key, payload, parent]).encode()
    ).hexdigest()


class LocalStore:
    def __init__(self, path):
        self.path = str(path)
        with closing(sqlite3.connect(self.path)) as c, c:
            c.execute(
                "create table if not exists current (id integer primary key check(id=1), revision integer, state text)"
            )
            c.execute(
                "create table if not exists commits (key text primary key, digest text not null, revision integer not null)"
            )

            audit_existed = c.execute(
                "select 1 from sqlite_master where type='table' and name='audit'"
            ).fetchone()
            c.execute(
                "create table if not exists audit (revision integer primary key, key text, payload text, parent text, hash text, checkpoint integer)"
            )
            current = c.execute(
                "select revision,state from current where id=1"
            ).fetchone()
            if current and not audit_existed:
                rev, payload = current
                head = chain_hash(rev, "legacy-checkpoint", payload, "0" * 64)
                c.execute(
                    "insert into audit values(?,?,?,?,?,1)",
                    (rev, "legacy-checkpoint", payload, "0" * 64, head),
                )

    def verify_audit(self, expected_head=None):
        with closing(sqlite3.connect(self.path)) as c:
            c.execute("begin")
            rows = c.execute(
                "select revision,key,payload,parent,hash,checkpoint from audit order by revision"
            ).fetchall()
            current = c.execute(
                "select revision,state from current where id=1"
            ).fetchone()
            commits = {
                key: (digest, rev)
                for key, digest, rev in c.execute(
                    "select key,digest,revision from commits"
                )
            }
        parent, valid = "0" * 64, True
        revision = rows[0][0] - 1 if rows and rows[0][5] else 0
        for rev, key, payload, previous, head, checkpoint in rows:
            valid = (
                valid
                and rev == revision + 1
                and previous == parent
                and head == chain_hash(rev, key, payload, parent)
            )
            if not checkpoint:
                valid = valid and commits.get(key) == (
                    hashlib.sha256(payload.encode()).hexdigest(),
                    rev,
                )
            revision, parent = rev, head
        valid = valid and (
            (current == (rows[-1][0], rows[-1][2])) if rows else current is None
        )
        baseline = rows[0][0] if rows and rows[0][5] else 0
        audited_keys = {r[1] for r in rows if not r[5]}
        retained_keys = {key for key, (_, rev) in commits.items() if rev > baseline}
        valid = valid and audited_keys == retained_keys
        if expected_head is not None:
            valid = valid and parent == expected_head
        return dict(
            valid=bool(valid),
            revision=revision,
            head=parent,
            coverage_from_revision=rows[0][0] if rows else None,
            legacy_prefix_unverifiable=bool(rows and rows[0][5]),
        )

    def read(self):
        with closing(sqlite3.connect(self.path)) as c, c:
            r = c.execute("select revision,state from current where id=1").fetchone()
        return (
            dict(revision=r[0], state=json.loads(r[1]))
            if r
            else dict(revision=0, state=None)
        )

    def commit(self, revision, key, state):
        from .paper import validate_state

        validate_state(state)
        text = encoded(state)
        digest = hashlib.sha256(text.encode()).hexdigest()
        with closing(sqlite3.connect(self.path)) as c, c:
            c.execute("begin immediate")
            old = c.execute(
                "select digest,revision from commits where key=?", (key,)
            ).fetchone()
            if old:
                if old[0] != digest:
                    raise Conflict("Idempotency key reused with different state")
                return old[1]
            row = c.execute("select revision from current where id=1").fetchone()
            if (row[0] if row else 0) != revision:
                raise Conflict("Revision changed; reload and recompute")
            c.execute(
                "insert or replace into current values(1,?,?)", (revision + 1, text)
            )
            c.execute("insert into commits values(?,?,?)", (key, digest, revision + 1))
            latest = c.execute(
                "select hash from audit order by revision desc limit 1"
            ).fetchone()
            parent = latest[0] if latest else "0" * 64
            head = chain_hash(revision + 1, key, text, parent)
            c.execute(
                "insert into audit values(?,?,?,?,?,0)",
                (revision + 1, key, text, parent, head),
            )
            return revision + 1
