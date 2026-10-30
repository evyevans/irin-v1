import copy
import unittest

from atlas.committee import evaluate

AS_OF = "2026-10-24T22:00:00Z"


def source(grade="A", day="2026-10-21"):
    return dict(
        source="https://example.invalid/filing",
        grade=grade,
        observed_at=day + "T20:00:00Z",
        available_at=day + "T21:00:00Z",
    )


def fixture():
    config = dict(
        schema_version=1,
        members=[
            dict(id="quality", roles=["score"], weight=60),
            dict(id="downside", roles=["score", "veto"], weight=40),
            dict(id="capacity", roles=["sizing"], sizing_floor=0.5),
            dict(id="entry", roles=["timing"]),
        ],
        veto_rules=[
            dict(
                id="funding",
                holder="downside",
                scope="funding shortfall",
                trigger_condition="Documented obligations exceed committed funding",
                minimum_grade="A",
                expiry_days=30,
                cure_condition="Committed financing covers the documented shortfall",
            )
        ],
    )
    votes = dict(members=[], vetoes=[], previously_listed=False)
    for key, fields in (
        ("quality", dict(score=90)),
        ("downside", dict(score=80)),
        ("capacity", dict(sizing_factor=0.8)),
        ("entry", dict(timing="pass")),
    ):
        votes["members"].append(
            dict(
                id=key,
                confidence=4,
                observed_at="2026-10-22T20:00:00Z",
                available_at="2026-10-22T21:00:00Z",
                sources=[source()],
                **fields
            )
        )
    return config, votes


def veto():
    return dict(
        id="funding-review",
        rule_id="funding",
        member_id="downside",
        trigger_condition_met=True,
        triggered_at="2026-10-22T22:00:00Z",
        expires_at="2026-11-20T22:00:00Z",
        evidence=[source()],
    )


class Committee(unittest.TestCase):
    def test_weighted_score_and_sizing_without_mutation_or_execution(self):
        config, votes = fixture()
        originals = copy.deepcopy((config, votes))
        result = evaluate(config, votes, as_of=AS_OF)
        self.assertEqual(result["action"], "OPEN_PAPER_POSITION")
        self.assertEqual(result["score"], 86)
        self.assertEqual(result["risk_multiplier"], 0.8)
        self.assertFalse(result["execution_enabled"])
        self.assertEqual((config, votes), originals)
        self.assertEqual(result, evaluate(config, votes, as_of=AS_OF))

    def test_missing_required_weight_is_never_renormalized(self):
        config, votes = fixture()
        votes["members"] = [v for v in votes["members"] if v["id"] != "downside"]
        result = evaluate(config, votes, as_of=AS_OF)
        self.assertEqual(result["score"], 54)
        self.assertEqual(result["active_score_weight"], 60)
        self.assertEqual(result["action"], "KEEP_WATCHLIST")
        self.assertEqual(result["risk_multiplier"], 0)
        self.assertIn("vote_review_required:downside", result["blockers"])

    def test_dissent_cuts_sizing_and_broad_dissent_blocks(self):
        config, votes = fixture()
        config["members"][0]["weight"] = 90
        config["members"][1]["weight"] = 10
        votes["members"][0]["score"] = 100
        votes["members"][1]["score"] = 20
        result = evaluate(config, votes, as_of=AS_OF)
        self.assertEqual(result["score"], 92)
        self.assertEqual(result["strong_dissents"], 1)
        self.assertEqual(result["risk_multiplier"], 0.6)
        config["policy"] = dict(dissent_block_at=1)
        result = evaluate(config, votes, as_of=AS_OF)
        self.assertEqual(result["action"], "KEEP_WATCHLIST")
        self.assertIn("broad_dissent", result["blockers"])

    def test_only_authorized_qualified_veto_rejects(self):
        config, votes = fixture()
        votes["vetoes"] = [veto()]
        self.assertEqual(evaluate(config, votes, as_of=AS_OF)["action"], "REJECT")
        votes["previously_listed"] = True
        self.assertEqual(
            evaluate(config, votes, as_of=AS_OF)["action"], "REDUCE_REMOVE"
        )
        votes["vetoes"][0]["evidence"] = [source("B")]
        result = evaluate(config, votes, as_of=AS_OF)
        self.assertEqual(result["action"], "KEEP_WATCHLIST")
        self.assertEqual(result["vetoes"][0]["status"], "REVIEW_REQUIRED")
        votes["vetoes"][0]["member_id"] = "quality"
        with self.assertRaises(ValueError):
            evaluate(config, votes, as_of=AS_OF)

    def test_expired_unresolved_veto_survives_until_evidenced_cure(self):
        config, votes = fixture()
        votes["vetoes"] = [veto()]
        votes["vetoes"][0]["expires_at"] = "2026-10-23T22:00:00Z"
        result = evaluate(config, votes, as_of=AS_OF)
        self.assertEqual(result["action"], "KEEP_WATCHLIST")
        self.assertEqual(result["vetoes"][0]["status"], "EXPIRED_REVIEW_REQUIRED")
        votes["vetoes"][0]["cure"] = dict(
            condition_met=True,
            observed_at="2026-10-24T20:00:00Z",
            available_at="2026-10-24T21:00:00Z",
            evidence=[source(day="2026-10-24")],
        )
        result = evaluate(config, votes, as_of=AS_OF)
        self.assertEqual(result["action"], "OPEN_PAPER_POSITION")
        self.assertEqual(result["vetoes"][0]["status"], "CURED")
        votes["vetoes"][0]["cure"]["evidence"] = [source("B", "2026-10-24")]
        self.assertEqual(
            evaluate(config, votes, as_of=AS_OF)["action"], "KEEP_WATCHLIST"
        )
        # Reusing the original adverse evidence is not later cure evidence.
        votes["vetoes"][0]["cure"]["evidence"] = [source("A", "2026-10-21")]
        self.assertEqual(
            evaluate(config, votes, as_of=AS_OF)["action"], "KEEP_WATCHLIST"
        )

    def test_future_evidence_cannot_trigger_or_cure_past_veto(self):
        config, votes = fixture()
        votes["vetoes"] = [veto()]
        votes["vetoes"][0]["evidence"] = [source(day="2026-10-23")]
        result = evaluate(config, votes, as_of=AS_OF)
        self.assertEqual(result["vetoes"][0]["status"], "REVIEW_REQUIRED")
        votes["vetoes"][0] = veto()
        votes["vetoes"][0]["cure"] = dict(
            condition_met=True,
            observed_at="2026-10-25T20:00:00Z",
            available_at="2026-10-25T21:00:00Z",
            evidence=[source(day="2026-10-25")],
        )
        self.assertEqual(
            evaluate(config, votes, as_of=AS_OF)["vetoes"][0]["status"], "ACTIVE"
        )

    def test_timing_wait_external_and_structural_gates(self):
        config, votes = fixture()
        votes["members"][-1]["timing"] = "wait"
        self.assertIn("timing_wait", evaluate(config, votes, as_of=AS_OF)["blockers"])
        votes["members"][-1]["timing"] = "pass"
        votes["blockers"] = ["Missing source review"]
        self.assertEqual(
            evaluate(config, votes, as_of=AS_OF)["action"], "KEEP_WATCHLIST"
        )
        votes["structural_reject"] = "Instrument outside research mandate"
        self.assertEqual(evaluate(config, votes, as_of=AS_OF)["action"], "REJECT")

    def test_required_vote_grade_age_expiry_and_source_availability_fail_closed(self):
        config, votes = fixture()
        for change in (
            dict(sources=[source("C")]),
            dict(observed_at="2026-09-01T20:00:00Z"),
            dict(expires_at="2026-10-23T20:00:00Z"),
            dict(sources=[source(day="2026-10-25")]),
        ):
            changed = copy.deepcopy(votes)
            changed["members"][0].update(change)
            result = evaluate(config, changed, as_of=AS_OF)
            self.assertEqual(result["action"], "KEEP_WATCHLIST")
            self.assertEqual(result["score"], 32)

    def test_invalid_confidence_weights_and_role_authority_are_rejected(self):
        config, votes = fixture()
        for confidence in (True, 0, 6, 2.5, "NaN", "Infinity"):
            changed = copy.deepcopy(votes)
            changed["members"][0]["confidence"] = confidence
            with self.assertRaises(ValueError):
                evaluate(config, changed, as_of=AS_OF)
        config["members"][0]["weight"] = 59
        with self.assertRaises(ValueError):
            evaluate(config, votes, as_of=AS_OF)
        config, votes = fixture()
        votes["members"][-1]["sizing_factor"] = 1
        with self.assertRaises(ValueError):
            evaluate(config, votes, as_of=AS_OF)
        votes["members"][-1].pop("sizing_factor")
        votes["vetoes"] = [veto()]
        votes["vetoes"][0]["expires_at"] = "2027-01-01T22:00:00Z"
        with self.assertRaises(ValueError):
            evaluate(config, votes, as_of=AS_OF)

    def test_configurable_downside_tie_break_and_negative_score(self):
        config, votes = fixture()
        config["policy"] = dict(tie_downside_members=["downside"])
        votes["members"][0]["score"] = 85
        votes["members"][1]["score"] = 50
        result = evaluate(config, votes, as_of=AS_OF)
        self.assertEqual(result["score"], 71)
        self.assertIn("tie_downside_not_satisfied", result["blockers"])
        votes["members"][0]["score"] = 0
        votes["members"][1]["score"] = 0
        self.assertEqual(evaluate(config, votes, as_of=AS_OF)["action"], "REJECT")


if __name__ == "__main__":
    unittest.main()
