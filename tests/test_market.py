import copy, unittest
from atlas.market import parse_yahoo, parse_nasdaq, compare


class Market(unittest.TestCase):
    def test_parses_provider_currency_history_and_split_flags(self):
        raw = {
            "chart": {
                "result": [
                    {
                        "meta": {"currency": "USD"},
                        "timestamp": [1792785600],
                        "indicators": {
                            "quote": [
                                {
                                    "open": [10],
                                    "high": [11],
                                    "low": [9],
                                    "close": [10],
                                    "volume": [100],
                                }
                            ],
                            "adjclose": [{"adjclose": [10]}],
                        },
                        "events": {},
                    }
                ]
            }
        }
        currency, rows, splits = parse_yahoo(raw)
        self.assertEqual(currency, "USD")
        self.assertEqual(rows[0]["c"], 10)
        self.assertFalse(splits)

    def test_cross_check_needs_ten_agreeing_latest_observations(self):
        rows = [dict(d=f"2026-10-{d:02}", c=10) for d in range(10, 20)]
        secondary = {r["d"]: 10 for r in rows}
        self.assertTrue(compare(rows, secondary)["eligible"])
        secondary[rows[-1]["d"]] = 12
        self.assertFalse(compare(rows, secondary)["eligible"])
        self.assertFalse(
            compare(rows[-2:], {r["d"]: 10 for r in rows[-2:]})["eligible"]
        )

    def test_nasdaq_numeric_normalization(self):
        data = {
            "data": {
                "tradesTable": {"rows": [{"date": "10/23/2026", "close": "$1,234.50"}]}
            }
        }
        self.assertEqual(parse_nasdaq(data)["2026-10-23"], 1234.5)
