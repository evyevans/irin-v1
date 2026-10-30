import copy
import unittest

from atlas import governance as g

NOW = "2026-10-30T22:00:00Z"
EARLY = "2026-10-30T21:00:00Z"
LATE = "2026-10-30T23:00:00Z"


class Governance(unittest.TestCase):
    def ready(self):
        state = g.configure(
            {"enabled": True, "halted": False},
            {"required_checks": ["health", "recovery"]},
        )
        for name in ("health", "recovery"):
            state = g.record_check(
                state, name, True, observed_at=EARLY, expires_at=LATE
            )
        return state

    def test_legacy_preserves_gates_and_does_not_enable(self):
        original = {"enabled": False, "halted": False}
        result = g.assess(original, as_of=NOW)
        self.assertFalse(result["configured"])
        self.assertTrue(result["ready"])
        self.assertFalse(result["entries_allowed"])
        self.assertEqual(original, {"enabled": False, "halted": False})

    def test_configured_missing_checks_fail_closed(self):
        state = g.configure({"enabled": True}, {"required_checks": ["health"]})
        result = g.assess(state, as_of=NOW)
        self.assertEqual(result["mode"], "HOLD")
        self.assertEqual(result["checks"], {"health": "missing"})
        for invalid in (None, {}, {"config": {"required_checks": []}}):
            self.assertIn(
                "governance_invalid",
                g.assess({"governance": invalid}, as_of=NOW)["reasons"],
            )

    def test_fresh_pass_and_expiry_boundary(self):
        state = self.ready()
        before = copy.deepcopy(state)
        self.assertTrue(g.assess(state, as_of=NOW)["entries_allowed"])
        self.assertEqual(g.assess(state, as_of=LATE)["checks"]["health"], "stale")
        self.assertEqual(state, before)
        state["halted"] = True
        self.assertFalse(g.assess(state, as_of=NOW)["entries_allowed"])

    def test_failed_and_future_checks_require_new_fresh_pass(self):
        state = self.ready()
        state = g.record_check(state, "health", False, observed_at=NOW, expires_at=LATE)
        self.assertEqual(g.assess(state, as_of=NOW)["checks"]["health"], "failed")
        self.assertEqual(g.assess(state, as_of=EARLY)["checks"]["health"], "future")
        state = g.record_check(
            state, "health", True, observed_at="2026-10-30T22:01:00Z", expires_at=LATE
        )
        self.assertTrue(g.assess(state, as_of="2026-10-30T22:02:00Z")["ready"])

    def test_review_deadline_resolution_and_immutable_ids(self):
        state = self.ready()
        state = g.add_review(state, "review-1", due_at=NOW, detail="Check source")
        self.assertEqual(
            state, g.add_review(state, "review-1", due_at=NOW, detail="Check source")
        )
        self.assertTrue(g.assess(state, as_of=EARLY)["ready"])
        self.assertEqual(g.assess(state, as_of=NOW)["overdue_reviews"], ["review-1"])
        with self.assertRaises(ValueError):
            g.add_review(state, "review-1", due_at=LATE, detail="Check source")
        resolved = g.resolve_review(state, "review-1", resolved_at=NOW)
        self.assertTrue(g.assess(resolved, as_of=NOW)["ready"])
        self.assertEqual(
            resolved, g.resolve_review(resolved, "review-1", resolved_at=NOW)
        )
        with self.assertRaises(ValueError):
            g.resolve_review(resolved, "review-1", resolved_at=LATE)

    def test_notice_deadline_reservation_and_receipt(self):
        state = self.ready()
        state = g.queue_notice(
            state, "notice-1", deadline_at=NOW, payload={"topic": "review"}
        )
        self.assertTrue(g.assess(state, as_of=EARLY)["ready"])
        self.assertEqual(g.assess(state, as_of=NOW)["overdue_notices"], ["notice-1"])
        reserved = g.acknowledge_notice(state, "notice-1", status="reserved", at=EARLY)
        self.assertFalse(g.assess(reserved, as_of=NOW)["ready"])
        sent = g.acknowledge_notice(
            reserved, "notice-1", status="sent", at=NOW, evidence="receipt-1"
        )
        self.assertTrue(g.assess(sent, as_of=NOW)["ready"])
        self.assertEqual(
            sent,
            g.acknowledge_notice(
                sent, "notice-1", status="sent", at=NOW, evidence="receipt-1"
            ),
        )
        self.assertEqual(
            sent,
            g.queue_notice(
                sent, "notice-1", deadline_at=NOW, payload={"topic": "review"}
            ),
        )
        with self.assertRaises(ValueError):
            g.queue_notice(sent, "notice-1", deadline_at=LATE)
        with self.assertRaises(ValueError):
            g.acknowledge_notice(sent, "notice-1", status="failed", at=LATE)

    def test_failed_notice_holds_before_deadline_then_recovery(self):
        state = g.queue_notice(self.ready(), "notice", deadline_at=LATE)
        state = g.acknowledge_notice(state, "notice", status="failed", at=EARLY)
        self.assertIn("notice_failed:notice", g.assess(state, as_of=NOW)["reasons"])
        state = g.acknowledge_notice(state, "notice", status="reserved", at=NOW)
        state = g.acknowledge_notice(
            state,
            "notice",
            status="sent",
            at="2026-10-30T22:01:00Z",
            evidence="receipt",
        )
        self.assertTrue(g.assess(state, as_of="2026-10-30T22:02:00Z")["ready"])
        self.assertFalse(g.assess(state, as_of=NOW)["ready"])

    def test_copy_semantics_and_configuration_retains_tasks(self):
        old = self.ready()
        before = copy.deepcopy(old)
        new = g.add_review(old, "review", due_at=NOW)
        self.assertEqual(old, before)
        new = g.configure(new, {"required_checks": ["health", "new_check"]})
        self.assertIn("review", new["governance"]["reviews"])
        self.assertIn("review_overdue:review", g.assess(new, as_of=NOW)["reasons"])
        self.assertEqual(g.assess(new, as_of=NOW)["checks"]["new_check"], "missing")

    def test_invalid_or_conflicting_health_rejected(self):
        state = self.ready()
        for passed in (None, 1, "true"):
            with self.assertRaises(ValueError):
                g.record_check(
                    state, "health", passed, observed_at=NOW, expires_at=LATE
                )
        with self.assertRaises(ValueError):
            g.record_check(state, "health", False, observed_at=EARLY, expires_at=LATE)
        with self.assertRaises(ValueError):
            g.record_check(state, "health", True, observed_at=NOW, expires_at=NOW)
        self.assertEqual(
            state,
            g.record_check(state, "health", True, observed_at=EARLY, expires_at=LATE),
        )

    def test_malformed_future_tasks_cannot_appear_ready(self):
        state = g.add_review(self.ready(), "review", due_at=LATE)
        state["governance"]["reviews"]["review"]["resolved_at"] = "invalid"
        self.assertIn("governance_invalid", g.assess(state, as_of=NOW)["reasons"])
        state = g.queue_notice(self.ready(), "notice", deadline_at=LATE)
        state["governance"]["outbox"]["notice"]["evidence"] = True
        self.assertIn("governance_invalid", g.assess(state, as_of=NOW)["reasons"])


if __name__ == "__main__":
    unittest.main()
