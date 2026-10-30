import json, sqlite3, tempfile, unittest
from contextlib import closing
from pathlib import Path
from atlas.paper import initialize
from atlas.storage import LocalStore


class AuditChain(unittest.TestCase):
    def test_state_tampering_and_missing_revision_detected(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = LocalStore(Path(tmp) / "ledger.db")
            s = initialize("10000", synthetic=True)
            store.commit(0, "one", s)
            s["enabled"] = True
            store.commit(1, "two", s)
            checked = store.verify_audit()
            self.assertTrue(checked["valid"])
            with closing(sqlite3.connect(store.path)) as c, c:
                c.execute("update audit set payload='{}' where revision=1")
            self.assertFalse(store.verify_audit()["valid"])

    def test_trusted_head_and_legacy_checkpoint(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "ledger.db"
            store = LocalStore(path)
            store.commit(0, "one", initialize("10000", synthetic=True))
            self.assertFalse(store.verify_audit(expected_head="0" * 64)["valid"])
            with closing(sqlite3.connect(path)) as c, c:
                c.execute("drop table audit")
            upgraded = LocalStore(path)
            result = upgraded.verify_audit()
            self.assertTrue(result["valid"])
            self.assertTrue(result["legacy_prefix_unverifiable"])

    def test_surplus_dedupe_record_is_not_an_audited_commit(self):
        from atlas.storage import encoded
        import hashlib

        with tempfile.TemporaryDirectory() as tmp:
            store = LocalStore(Path(tmp) / "ledger.db")
            state = initialize("10000", synthetic=True)
            store.commit(0, "one", state)
            head = store.verify_audit()["head"]
            state["enabled"] = True
            with closing(sqlite3.connect(store.path)) as c, c:
                c.execute(
                    "insert into commits values(?,?,?)",
                    ("phantom", hashlib.sha256(encoded(state).encode()).hexdigest(), 2),
                )
            self.assertFalse(store.verify_audit(expected_head=head)["valid"])
