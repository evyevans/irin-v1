import copy, json, unittest
from pathlib import Path
from atlas.leaderboard import news_score
from atlas.batch import evaluate_batch


class Leaderboard(unittest.TestCase):
    def test_news_excludes_future_and_old(self):
        items = [
            dict(
                title="Company wins contract",
                url="https://example.invalid/a",
                published_at="2026-10-22T10:00:00Z",
                available_at="2026-10-22T11:00:00Z",
            ),
            dict(
                title="Company growth strong",
                url="https://example.invalid/b",
                published_at="2026-10-23T10:00:00Z",
                available_at="2026-10-23T11:00:00Z",
            ),
            dict(
                title="Company fraud loss",
                url="https://example.invalid/c",
                published_at="2026-10-24T10:00:00Z",
                available_at="2026-10-24T11:00:00Z",
            ),
        ]
        r = news_score(items, as_of="2026-10-23T22:00:00Z")
        self.assertEqual(r["count"], 2)
        self.assertGreater(r["score"], 5)
        self.assertEqual(r["negative"], 0)

    def test_batch_ranking_has_previous_movement_and_cannot_trade(self):
        s = json.loads(
            (
                Path(__file__).resolve().parents[1] / "examples/synthetic.json"
            ).read_text()
        )
        r = evaluate_batch(
            [s], held=[], as_of="2026-10-23T22:00:00Z", previous={"DEMO-GRID": 2}
        )
        self.assertEqual(r["leaderboard"]["rows"][0]["move"], 1)
        self.assertFalse(r["execution_enabled"])
        self.assertEqual(
            r["leaderboard"]["rows"][0]["news"]["status"], "insufficient_news_neutral"
        )
