import ast
from datetime import date, datetime, timedelta, timezone
import io
import json
from pathlib import Path
import threading
import tempfile
import unittest
from unittest.mock import Mock, patch
import zipfile

import pandas as pd
import market_store as store

CSV = b"Date,Open,High,Low,Close\n2026-09-08,310,315,300,307\n2026-09-09,307,311,299,306\n"
SHA = "a" * 40


class StoreTests(unittest.TestCase):
    def test_csv_validation(self):
        self.assertEqual(len(store.parse_prices(CSV)), 2)
        with self.assertRaises(ValueError):
            store.parse_prices(b"Date,Open,High,Low,Close\n2026-09-08,310,315,0,307\n")

    def test_data_paths_cannot_escape(self):
        with self.assertRaises(ValueError):
            store.raw_url(SHA, "../secrets")
        with self.assertRaises(ValueError):
            store.raw_url("main", "manifest.json")

    def test_failed_refresh_retains_previous_snapshot(self):
        previous = store._last_snapshot
        try:
            store._last_snapshot = (SHA, {"schema": 1, "prices": {"7201.T": {}}})
            with patch.object(store, "read_url", side_effect=OSError("offline")):
                self.assertEqual(store.get_snapshot()[0], SHA)
        finally:
            store._last_snapshot = previous

    def test_initial_failure_does_not_invent_prices(self):
        previous = store._last_snapshot
        try:
            store._last_snapshot = None
            with patch.object(store, "read_url", side_effect=OSError("offline")):
                with self.assertRaises(RuntimeError):
                    store.get_snapshot()
        finally:
            store._last_snapshot = previous

    def test_local_mode_prefers_updated_local_snapshot(self):
        previous_dir = store.LOCAL_SNAPSHOT_DIR
        previous_snapshot = store._last_snapshot
        try:
            with tempfile.TemporaryDirectory() as directory:
                folder = Path(directory)
                manifest = {
                    "schema": 1,
                    "prices": {"7201.T": {"path": "prices/7201.T.csv"}},
                    "ranking": {"path": "nikkei225.zip", "tickers": ["7201.T"], "as_of": "2026-09-11"},
                }
                (folder / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
                (folder / "prices").mkdir()
                (folder / "prices" / "7201.T.csv").write_bytes(CSV)
                with zipfile.ZipFile(folder / "nikkei225.zip", "w") as archive:
                    archive.writestr("7201.T.csv", CSV)
                store.LOCAL_SNAPSHOT_DIR = folder
                store._last_snapshot = None
                revision, loaded = store.get_snapshot()
                self.assertEqual(len(revision), 64)
                self.assertEqual(loaded["ranking"]["as_of"], "2026-09-11")
                with patch.object(store, "read_url", side_effect=AssertionError("remote read")):
                    self.assertEqual(len(store.read_prices(revision, "7201.T", loaded)), 2)
                    self.assertEqual(len(store.read_nikkei(revision, loaded)), 2)
        finally:
            store.LOCAL_SNAPSHOT_DIR = previous_dir
            store._last_snapshot = previous_snapshot

    def test_incomplete_ranking_bundle_is_rejected(self):
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as archive:
            archive.writestr("7201.T.csv", CSV)
        with patch.object(store, "read_url", return_value=buf.getvalue()):
            with self.assertRaises(RuntimeError):
                store.read_nikkei(SHA, {"ranking": {"path": "nikkei225.zip", "tickers": ["7201.T", "7203.T"]}})

    def test_ranking_cache_reuses_same_snapshot_and_keeps_actual_data_date(self):
        tree = ast.parse(Path("app.py").read_text(encoding="utf-8-sig"))
        function = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "get_light_pickling_ranking")
        state = {"lock": threading.Lock(), "entries": {}}
        frame = pd.DataFrame({"銘柄": ["test"]})
        calculate = Mock(return_value=(frame, frame))
        save = Mock()
        scope = dict(pd=pd, date=date, datetime=datetime, JAPAN_TIMEZONE=timezone(timedelta(hours=9)),
                     saved_snapshot=lambda: (SHA, {"ranking": {"as_of": "2026-09-08"}}),
                     ranking_cache_state=lambda: state, load_ranking_cache=lambda: {},
                     save_ranking_cache=save, calculate_light_pickling_rankings=calculate)
        exec(compile(ast.Module(body=[function], type_ignores=[]), "test_cache", "exec"), scope)
        get = scope["get_light_pickling_ranking"]
        self.assertEqual(get(date(2015, 1, 1), date(2026, 9, 10))[2], date(2026, 9, 8))
        self.assertFalse(get(date(2015, 1, 1), date(2026, 9, 10))[3])
        calculate.assert_called_once()
        save.assert_called_once()


if __name__ == "__main__":
    unittest.main()
