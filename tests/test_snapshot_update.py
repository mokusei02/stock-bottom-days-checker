import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import pandas as pd
from scripts import update_market_data as updater


CSV = b"Date,Open,High,Low,Close\n2026-09-09,307,311,299,306\n"


class UpdateTests(unittest.TestCase):
    def run_update(self, output, results):
        with patch.object(updater, "ranking_codes", return_value=["7201", "7203"]), \
             patch.object(updater.pd, "read_csv", return_value=pd.DataFrame({"code": []})), \
             patch.object(updater.yf, "set_tz_cache_location"), \
             patch.object(updater, "is_japan_business_day", return_value=True), \
             patch.object(updater, "fetch", side_effect=lambda ticker, end: results[ticker]):
            updater.update(output, only_nikkei=True)

    def test_japanese_holiday_skips_all_downloads(self):
        with tempfile.TemporaryDirectory() as temporary, \
             patch.object(updater, "is_japan_business_day", return_value=False), \
             patch.object(updater, "fetch") as fetch:
            updater.update(Path(temporary), only_nikkei=True)
            fetch.assert_not_called()
            self.assertFalse((Path(temporary) / "manifest.json").exists())

    def test_rate_limit_keeps_all_saved_files_unchanged(self):
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary)
            old = '{"schema":1,"prices":{},"ranking":{"as_of":"2026-09-08"}}'
            (output / "manifest.json").write_text(old)
            (output / "nikkei225.zip").write_bytes(b"previous bundle")
            with self.assertRaisesRegex(RuntimeError, "rate limit"):
                self.run_update(output, {
                    "7201.T": ("7201.T", CSV, "2026-09-09", None),
                    "7203.T": ("7203.T", None, None, "rate_limit"),
                })
            self.assertEqual((output / "manifest.json").read_text(), old)
            self.assertEqual((output / "nikkei225.zip").read_bytes(), b"previous bundle")
            self.assertFalse((output / "prices").exists())

    def test_incomplete_refresh_keeps_old_ranking_and_failed_symbol(self):
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary)
            previous = {"path": "prices/7203.T.csv", "latest_date": "2026-09-08"}
            ranking = {"as_of": "2026-09-08", "path": "nikkei225.zip"}
            (output / "manifest.json").write_text(json.dumps({
                "schema": 1, "prices": {"7203.T": previous}, "ranking": ranking,
            }))
            (output / "nikkei225.zip").write_bytes(b"previous bundle")
            self.run_update(output, {
                "7201.T": ("7201.T", CSV, "2026-09-09", None),
                "7203.T": ("7203.T", None, None, "TimeoutError"),
            })
            result = json.loads((output / "manifest.json").read_text())
            self.assertEqual(result["ranking"], ranking)
            self.assertEqual(result["prices"]["7203.T"], previous)
            self.assertEqual(result["prices"]["7201.T"]["latest_date"], "2026-09-09")
            self.assertEqual((output / "nikkei225.zip").read_bytes(), b"previous bundle")


if __name__ == "__main__":
    unittest.main()
