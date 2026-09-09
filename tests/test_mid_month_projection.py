"""Unit tests for mid_month_projection.py's pure projection math."""
import datetime
import unittest

import mid_month_projection as mmp


def make_account(**over):
    base = {
        "Name": "Acme Inc", "Id": "001x", "Owner": "Jane Rep",
        "Start": "2026-01-01", "End": "2027-01-01", "Cap": 120000.0,
    }
    base.update(over)
    return base


class TestProjectFullMonthPct(unittest.TestCase):
    def test_scales_pages_so_far_to_full_month(self):
        # 15 days in, 1000 pages so far, 30-day month -> full month ~= 2000
        today = datetime.date(2026, 9, 15)
        pct = mmp.project_full_month_pct(make_account(), 1000, today)
        prorated_cap = 120000.0 / (365 / 30.44)
        expected = (1000 / 15 * 30) / prorated_cap * 100
        self.assertAlmostEqual(pct, expected, places=6)

    def test_missing_cap_returns_none(self):
        today = datetime.date(2026, 9, 15)
        pct = mmp.project_full_month_pct(make_account(Cap=0), 1000, today)
        self.assertIsNone(pct)

    def test_day_one_does_not_divide_by_zero(self):
        # max(today.day, 1) guards this - day 1 should scale by the full
        # month length exactly as if 1 day had elapsed, not raise.
        today = datetime.date(2026, 9, 1)
        pct = mmp.project_full_month_pct(make_account(), 100, today)
        self.assertIsNotNone(pct)
        self.assertGreater(pct, 0)

    def test_zero_pages_so_far_projects_zero_pct(self):
        today = datetime.date(2026, 9, 15)
        pct = mmp.project_full_month_pct(make_account(), 0, today)
        self.assertEqual(pct, 0)


if __name__ == "__main__":
    unittest.main()
