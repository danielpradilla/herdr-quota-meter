import unittest

from reset_tab import render_resets, reset_time


class ResetTabTests(unittest.TestCase):
    def test_accounts_stay_separate_and_unknown_resets_are_explicit(self):
        data = {"providers": [
            {"provider": "claude", "name": "claude1", "windows": [
                {"label": "5h", "resetsAt": "2000-01-01T00:00:00Z"},
                {"label": "7d", "resetsAt": None},
            ]},
            {"provider": "claude", "name": "claude2", "windows": [],
             "state": {"status": "auth_required"}},
            {"provider": "other", "windows": []},
        ]}
        first, second = render_resets(data, None, ["claude"]).splitlines()
        self.assertIn("claude1: 5h: in 0h 0m (", first)
        self.assertIn(" | 7d: reset unknown", first)
        self.assertEqual(second, "claude2: reset unavailable (auth_required)")
        self.assertEqual(reset_time("invalid"), "reset unknown")
        self.assertEqual(reset_time("2030-01-01T00:00:00"), "reset unknown")
        self.assertEqual(render_resets(None, "vendor offline", ["claude"]), "quota: vendor offline")


if __name__ == "__main__":
    unittest.main()
