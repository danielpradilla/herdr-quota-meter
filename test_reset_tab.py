from datetime import datetime, timezone
import unittest

from reset_tab import dashboard_rows, quota_bar, reset_time


class ResetTabTests(unittest.TestCase):
    def test_countdown_ticks_and_stops_at_zero(self):
        reset = "2030-01-02T00:00:00Z"
        for second, expected in ((58, "00:00:02"), (59, "00:00:01")):
            now = datetime(2030, 1, 1, 23, 59, second, tzinfo=timezone.utc)
            self.assertTrue(reset_time(reset, now).startswith(expected))
        now = datetime(2030, 1, 2, 0, 0, 1, tzinfo=timezone.utc)
        self.assertTrue(reset_time(reset, now).startswith("00:00:00"))
        self.assertTrue(reset_time("2030-01-04T01:02:04Z", now).startswith("2d 01:02:03"))
        for value in (None, "bad", "2030-01-01T00:00:00"):
            self.assertEqual(reset_time(value, now), "reset unknown")

    def test_bar_capacity_and_unknown_are_not_confused(self):
        self.assertEqual(quota_bar(50, 10), ("[█████░░░░░]  50%", 1))
        self.assertEqual(quota_bar(-5, 4), ("[░░░░]   0%", 3))
        self.assertEqual(quota_bar(150, 4), ("[████] 100%", 1))
        self.assertEqual(quota_bar(20, 4)[1], 2)
        self.assertIn("░", quota_bar(96, 10)[0])
        for value in (None, "50", float("nan"), float("inf")):
            self.assertEqual(quota_bar(value, 4), ("[????]   ?%", 0))

    def test_resizing_preserves_account_windows_and_errors_keep_stale_data(self):
        data = {"providers": [
            {"provider": "claude", "name": "claude1", "windows": [
                {"label": "5h", "percentRemaining": 50, "resetsAt": "2030-01-02T00:00:00Z"},
                {"label": "7d", "percentRemaining": 20},
            ]},
            {"provider": "claude", "name": "claude2", "windows": [],
             "state": {"status": "auth_required"}},
            {"provider": "other", "windows": []},
        ]}
        now = datetime(2030, 1, 1, tzinfo=timezone.utc)
        wide = dashboard_rows(data, None, ["claude"], 210, now)
        account_line = next(text for text, _ in wide if text.startswith("claude1"))
        self.assertIn("5h", account_line)
        self.assertIn("7d", account_line)
        narrow = dashboard_rows(data, "offline", ["claude"], 65, now)
        text = "\n".join(row for row, _ in narrow)
        self.assertIn("claude1", text)
        self.assertIn("50%", text)
        self.assertIn("reset unknown", text)
        self.assertIn("auth_required", text)
        self.assertIn("offline", text)
        self.assertNotIn("other", text)
        self.assertTrue(all(len(row) <= 65 for row, _ in narrow))
        bare = dashboard_rows(data, None, ["claude"], 30, now)
        self.assertTrue(all(len(row) <= 30 for row, _ in bare))
        self.assertIn("1d 00:00:00", "\n".join(row for row, _ in bare))


if __name__ == "__main__":
    unittest.main()
