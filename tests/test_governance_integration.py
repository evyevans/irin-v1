import copy, unittest
from atlas.paper import initialize, advance
from atlas.accounting_demo import steps
from atlas.governance import configure


class GovernanceIntegration(unittest.TestCase):
    def test_unready_blocks_entries_and_preserves_protective_exits(self):
        inputs = list(steps())
        s = initialize("25000", synthetic=True)
        s["enabled"] = True
        first, b = inputs[0]
        s = advance(s, [first], as_of="2026-10-23T22:00:00Z", bookkeeping=b)
        second, b = inputs[1]
        held = advance(s, [second], as_of="2026-10-26T22:00:00Z", bookkeeping=b)
        self.assertTrue(held["positions"])
        blocked = configure(s, {"required_checks": ["source-health"]})
        blocked = advance(
            blocked, [second], as_of="2026-10-26T22:00:00Z", bookkeeping=b
        )
        self.assertFalse(blocked["positions"])
        self.assertEqual(blocked["operational"]["mode"], "HOLD")
        held = configure(held, {"required_checks": ["source-health"]})
        third = copy.deepcopy(second)
        row = copy.deepcopy(third["history"][-1])
        row.update(d="2026-10-27", o=80, h=82, l=78, c=81, ac=81)
        third["history"].append(row)
        for source in third["sources"]:
            source.update(
                observed_at="2026-10-27T20:00:00Z", available_at="2026-10-27T21:00:00Z"
            )
        out = advance(held, [third], as_of="2026-10-27T22:00:00Z")
        self.assertFalse(out["positions"])
        self.assertTrue(any(e["kind"] == "exit" for e in out["events"]))
