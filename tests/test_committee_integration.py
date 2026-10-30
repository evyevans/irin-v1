import copy, unittest
from atlas.paper import initialize, advance
from atlas.accounting_demo import steps


def envelope(score):
    return dict(
        config=dict(
            schema_version=1, members=[dict(id="quality", roles=["score"], weight=100)]
        ),
        votes=dict(
            members=[
                dict(
                    id="quality",
                    score=score,
                    confidence=5,
                    observed_at="2026-10-23T20:00:00Z",
                    available_at="2026-10-23T21:00:00Z",
                    sources=[
                        dict(
                            source="https://example.invalid/review",
                            grade="A",
                            observed_at="2026-10-23T19:00:00Z",
                            available_at="2026-10-23T20:00:00Z",
                        )
                    ],
                )
            ]
        ),
    )


class CommitteeIntegration(unittest.TestCase):
    def test_negative_review_blocks_entries_and_later_exit_waits_next_session(self):
        rows = list(steps())
        state = initialize("25000", synthetic=True)
        state["enabled"] = True
        first, b = rows[0]
        b = copy.deepcopy(b)
        b["committees"] = {"DEMO-GRID": envelope(90)}
        state = advance(state, [first], as_of="2026-10-23T22:00:00Z", bookkeeping=b)
        second, b = rows[1]
        blocked = copy.deepcopy(b)
        blocked["committees"] = {"DEMO-GRID": envelope(20)}
        noentry = advance(
            state, [second], as_of="2026-10-26T22:00:00Z", bookkeeping=blocked
        )
        self.assertFalse(noentry["positions"])
        held = advance(state, [second], as_of="2026-10-26T22:00:00Z", bookkeeping=b)
        self.assertTrue(held["positions"])
        third, b = rows[2]
        b = copy.deepcopy(b)
        b["committees"] = {"DEMO-GRID": envelope(20)}
        reviewed = advance(held, [third], as_of="2026-10-27T22:00:00Z", bookkeeping=b)
        self.assertIn("DEMO-GRID", reviewed["positions"])
        self.assertIn(
            "Committee negative", reviewed["positions"]["DEMO-GRID"]["queued_exit"]
        )

    def test_committed_veto_cannot_be_omitted_on_later_review(self):
        rows = list(steps())
        state = initialize("25000", synthetic=True)
        state["enabled"] = True
        review = envelope(90)
        review["config"]["members"][0]["roles"].append("veto")
        review["config"]["veto_rules"] = [
            dict(
                id="solvency-rule",
                holder="quality",
                scope="solvency",
                minimum_grade="A",
                expiry_days=30,
                trigger_condition="Sourced inability to meet obligations",
                cure_condition="Sourced resolution",
            )
        ]
        review["votes"]["vetoes"] = [
            dict(
                id="solvency-event",
                rule_id="solvency-rule",
                member_id="quality",
                trigger_condition_met=True,
                triggered_at="2026-10-23T20:00:00Z",
                expires_at="2026-11-20T20:00:00Z",
                evidence=review["votes"]["members"][0]["sources"],
            )
        ]
        first, b = rows[0]
        b = copy.deepcopy(b)
        b["committees"] = {"DEMO-GRID": review}
        state = advance(state, [first], as_of="2026-10-23T22:00:00Z", bookkeeping=b)
        second, b = rows[1]
        b = copy.deepcopy(b)
        revised = copy.deepcopy(review)
        revised["votes"]["vetoes"] = []
        b["committees"] = {"DEMO-GRID": revised}
        with self.assertRaisesRegex(ValueError, "veto cannot"):
            advance(state, [second], as_of="2026-10-26T22:00:00Z", bookkeeping=b)

    def test_later_review_cannot_create_an_earlier_replay_decision(self):
        first, b = next(steps())
        state = initialize("25000", synthetic=True)
        b = copy.deepcopy(b)
        b["committees"] = {"DEMO-GRID": envelope(20)}
        vote = b["committees"]["DEMO-GRID"]["votes"]["members"][0]
        vote.update(
            observed_at="2026-10-26T20:00:00Z", available_at="2026-10-26T21:00:00Z"
        )
        with self.assertRaisesRegex(ValueError, "valued session UTC date"):
            advance(state, [first], as_of="2026-10-26T22:00:00Z", bookkeeping=b)
