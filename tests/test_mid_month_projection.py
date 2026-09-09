"""Unit tests for mid_month_projection.py's pure projection math."""
import datetime
import unittest

import mid_month_projection as mmp


def make_account(**over):
    base = {
        "Name": "Acme Inc", "Id": "001x", "Owner": "Jane Rep",
        "Start": "2026-01-01", "End": "2027-01-01", "Cap": 120000.0,
        "ACV": 12000.0,
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


class TestSelectOverage(unittest.TestCase):
    """Covers the user's own worked example (2026-09-09): a 100-page
    contract with 50 pages uploaded in the first week is a 200% pace and
    must be flagged - and the threshold is "more than 150%", not
    "at least 150%"."""
    TODAY = datetime.date(2026, 9, 8)  # day 8 of a 30-day month

    def test_users_worked_example_is_flagged(self):
        # 100-page/month contract, 50 pages in the first week (day 8):
        # (50 / 8 * 30) / 100 * 100 = 187.5% projected - over 150%.
        account = make_account(Id="acc1", Cap=100.0, Start="2026-01-01", End="2026-02-01")
        over = mmp.select_overage([account], {"acc1": 50}, self.TODAY)
        self.assertEqual(len(over), 1)
        self.assertEqual(over[0]["id"], "acc1")
        self.assertGreater(over[0]["projectedPct"], 150.0)

    def test_exactly_at_threshold_is_not_flagged(self):
        account = make_account(Id="acc1")
        # Pick pages_so_far that lands exactly on 150.0% projected.
        prorated_cap = 120000.0 / (365 / 30.44)
        days_in_month = 30
        pages_for_exactly_150 = 150.0 / 100 * prorated_cap * self.TODAY.day / days_in_month
        over = mmp.select_overage([account], {"acc1": pages_for_exactly_150}, self.TODAY, threshold=150.0)
        self.assertEqual(over, [])

    def test_under_threshold_not_flagged(self):
        account = make_account(Id="acc1")
        over = mmp.select_overage([account], {"acc1": 10}, self.TODAY)
        self.assertEqual(over, [])

    def test_uncomputable_pct_skipped(self):
        account = make_account(Id="acc1", Cap=0)
        over = mmp.select_overage([account], {"acc1": 999999}, self.TODAY)
        self.assertEqual(over, [])

    def test_sorted_highest_projected_first(self):
        accounts = [
            make_account(Id="low", Cap=1000.0),
            make_account(Id="high", Cap=100.0),
        ]
        over = mmp.select_overage(accounts, {"low": 1000, "high": 1000}, self.TODAY)
        self.assertEqual([o["id"] for o in over], ["high", "low"])

    def test_missing_mtd_entry_defaults_to_zero_and_is_not_flagged(self):
        account = make_account(Id="acc1")
        over = mmp.select_overage([account], {}, self.TODAY)
        self.assertEqual(over, [])


if __name__ == "__main__":
    unittest.main()
