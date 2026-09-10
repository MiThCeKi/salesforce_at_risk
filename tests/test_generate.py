"""Unit tests for generate.py's pure computation/rendering functions.

Deliberately does not touch generate.accounts (the module-level live
snapshot) - these tests build their own small fixture accounts so they
stay stable regardless of when the snapshot was last refreshed. See
generate.py's own docstring ("accounts array is a SNAPSHOT, not a live
source") for why that distinction matters.
"""
import datetime
import re
import unittest

import generate


def make_account(**over):
    base = {
        "Name": "Acme Inc", "Id": "001000000000001AAA", "Owner": "Jane Rep",
        "Stage": "Customer", "Tier": "SMB", "ACV": 12000.0,
        "Start": "2026-01-01", "End": "2027-01-01", "Cap": 120000.0,
        "Pages": 5000.0, "Hours": 3.0, "Users": 4.0,
        "MainContact": "Bob Contact", "LastEmail": "2026-09-01", "LastEmailBy": "Jane Rep",
        "LastLogin": "2026-09-01", "HealthScore": 6,
        "NextMeeting": None, "NextMeetingTitle": None, "NextMeetingWith": None,
        "NextInternalMeeting": None, "NextInternalMeetingTitle": None,
    }
    base.update(over)
    return base


class TestParse(unittest.TestCase):
    def test_parses_iso_date(self):
        self.assertEqual(generate.parse("2026-09-18"), datetime.date(2026, 9, 18))


class TestProratedMonthlyCap(unittest.TestCase):
    def test_normal_contract(self):
        a = make_account(Start="2026-01-01", End="2027-01-01", Cap=365 * 30.44)
        cap = generate.prorated_monthly_cap(a)
        self.assertAlmostEqual(cap, 365 * 30.44 / (365 / 30.44), places=2)

    def test_missing_start_returns_none(self):
        self.assertIsNone(generate.prorated_monthly_cap(make_account(Start=None)))

    def test_missing_end_returns_none(self):
        self.assertIsNone(generate.prorated_monthly_cap(make_account(End=None)))

    def test_missing_cap_returns_none(self):
        self.assertIsNone(generate.prorated_monthly_cap(make_account(Cap=None)))

    def test_zero_cap_returns_none(self):
        self.assertIsNone(generate.prorated_monthly_cap(make_account(Cap=0)))

    def test_end_before_start_returns_none(self):
        a = make_account(Start="2027-01-01", End="2026-01-01")
        self.assertIsNone(generate.prorated_monthly_cap(a))

    def test_zero_length_contract_returns_none(self):
        a = make_account(Start="2026-01-01", End="2026-01-01")
        self.assertIsNone(generate.prorated_monthly_cap(a))


class TestComputeRows(unittest.TestCase):
    TODAY = datetime.date(2026, 9, 9)

    def row_for(self, pages, cap=120000.0):
        accounts = [make_account(Pages=pages, Cap=cap)]
        return generate.compute_rows(accounts, self.TODAY)[0]

    def test_severity_critical_below_5pct(self):
        # prorated cap for a 1-year, 120000-cap contract ~= 9986/mo
        row = self.row_for(pages=100)
        self.assertLess(row["UsagePct"], 5)
        self.assertEqual(row["Severity"], "Critical")

    def test_severity_high_5_to_15pct(self):
        row = self.row_for(pages=1000)
        self.assertTrue(5 <= row["UsagePct"] < 15)
        self.assertEqual(row["Severity"], "High")

    def test_severity_watch_15_to_25pct(self):
        row = self.row_for(pages=2000)
        self.assertTrue(15 <= row["UsagePct"] < 25)
        self.assertEqual(row["Severity"], "Watch")

    def test_severity_healthy_at_or_above_25pct(self):
        row = self.row_for(pages=5000)
        self.assertGreaterEqual(row["UsagePct"], 25)
        self.assertEqual(row["Severity"], "Healthy")

    def test_severity_unknown_when_pct_uncomputable(self):
        row = self.row_for(pages=5000, cap=0)
        self.assertIsNone(row["UsagePct"])
        self.assertEqual(row["Severity"], "Unknown")

    def test_stage_label_includes_tier_only_for_customer(self):
        accounts = [
            make_account(Stage="Customer", Tier="Enterprise"),
            make_account(Stage="Prospect", Tier="Enterprise"),
            make_account(Stage="Customer", Tier=None),
        ]
        rows = generate.compute_rows(accounts, self.TODAY)
        by_stage = {(r["Stage"], r["Tier"]): r["StageLabel"] for r in rows}
        self.assertEqual(by_stage[("Customer", "Enterprise")], "Customer (Enterprise)")
        self.assertEqual(by_stage[("Prospect", "Enterprise")], "Prospect")
        self.assertEqual(by_stage[("Customer", None)], "Customer")

    def test_days_to_renewal_and_since_login(self):
        a = make_account(End="2026-10-09", LastLogin="2026-09-02")
        row = generate.compute_rows([a], self.TODAY)[0]
        self.assertEqual(row["Days"], 30)
        self.assertEqual(row["DaysSinceLogin"], 7)

    def test_missing_end_and_last_login_are_none(self):
        a = make_account(End=None, LastLogin=None)
        row = generate.compute_rows([a], self.TODAY)[0]
        self.assertIsNone(row["Days"])
        self.assertIsNone(row["DaysSinceLogin"])

    def test_health_score_passed_through(self):
        row = self.row_for(pages=5000)
        self.assertEqual(row["HealthScore"], 6)  # make_account's default

    def test_health_score_none_when_missing(self):
        a = make_account(HealthScore=None)
        row = generate.compute_rows([a], self.TODAY)[0]
        self.assertIsNone(row["HealthScore"])

    def test_rows_sorted_by_usage_pct_ascending_nones_last(self):
        accounts = [
            make_account(Id="a1", Pages=5000, Cap=120000.0),   # ~25%+, Healthy
            make_account(Id="a2", Pages=100, Cap=120000.0),    # low pct
            make_account(Id="a3", Pages=5000, Cap=0),          # None -> Unknown
        ]
        rows = generate.compute_rows(accounts, self.TODAY)
        ids_in_order = [r["Id"] for r in rows]
        self.assertEqual(ids_in_order, ["a2", "a1", "a3"])


class TestComputeFlagged(unittest.TestCase):
    def test_only_critical_high_watch_are_flagged(self):
        rows = [
            {"Severity": "Critical"}, {"Severity": "High"}, {"Severity": "Watch"},
            {"Severity": "Healthy"}, {"Severity": "Unknown"},
        ]
        flagged = generate.compute_flagged(rows)
        self.assertEqual(len(flagged), 3)
        self.assertTrue(all(r["Severity"] in ("Critical", "High", "Watch") for r in flagged))


class TestJsEscape(unittest.TestCase):
    def test_escapes_backslash_before_quote(self):
        # Backslashes must be escaped first, or a trailing backslash would
        # eat the closing quote's escape.
        self.assertEqual(generate.js_escape('a\\b"c'), 'a\\\\b\\"c')

    def test_plain_string_unchanged(self):
        self.assertEqual(generate.js_escape("Regular Name"), "Regular Name")


class TestRenderRowsJs(unittest.TestCase):
    TODAY = datetime.date(2026, 9, 9)

    def rendered_for(self, **over):
        accounts = [make_account(**over)]
        rows = generate.compute_rows(accounts, self.TODAY)
        return generate.render_rows_js(rows)

    def test_none_tier_renders_as_js_null_not_string(self):
        # Regression test: render_rows_js used to hardcode tier:"{tier}",
        # which stringified a None Tier into the literal JS "None" rather
        # than null (found 2026-09-09 auditing Dr. Yaacov Markus's row).
        js = self.rendered_for(Tier=None)
        self.assertIn("tier:null", js)
        self.assertNotIn('tier:"None"', js)
        self.assertNotIn("tier:None", js)  # would be a JS ReferenceError

    def test_string_tier_renders_quoted_and_escaped(self):
        js = self.rendered_for(Tier='Ent"erprise')
        self.assertIn('tier:"Ent\\"erprise"', js)

    def test_optional_fields_null_when_missing(self):
        js = self.rendered_for(
            MainContact=None, LastEmail=None, LastEmailBy=None, NextMeeting=None,
            NextMeetingTitle=None, NextMeetingWith=None,
            NextInternalMeeting=None, NextInternalMeetingTitle=None, HealthScore=None,
        )
        for field in (
            "mainContact", "lastEmail", "lastEmailBy", "nextMeeting", "nextMeetingTitle",
            "nextMeetingWith", "nextInternalMeeting", "nextInternalMeetingTitle", "healthScore",
        ):
            self.assertIn(f"{field}:null", js)

    def test_health_score_renders_as_int_when_present(self):
        js = self.rendered_for(HealthScore=7)
        self.assertIn("healthScore:7,", js)
        self.assertNotIn("healthScore:7.0", js)

    def test_health_score_zero_is_not_treated_as_missing(self):
        # 0 is a real, valid Health_Score__c value (verified live 2026-09-10)
        # - must render as healthScore:0, not fall through to null.
        js = self.rendered_for(HealthScore=0)
        self.assertIn("healthScore:0,", js)

    def test_last_email_by_null_when_last_email_present_but_sender_unknown(self):
        # LastEmailBy can legitimately be null even when LastEmail isn't - a
        # defensive case, not one the live pipeline should produce (its own
        # docstring says never guess a sender), but the renderer must still
        # degrade to null rather than crash or emit an unquoted bareword.
        js = self.rendered_for(LastEmail="2026-09-01", LastEmailBy=None)
        self.assertIn("lastEmailBy:null", js)
        self.assertIn('lastEmail:"2026-09-01"', js)

    def test_present_next_meeting_fields_populated(self):
        js = self.rendered_for(
            NextMeeting="2026-09-18", NextMeetingTitle="Sync",
            NextMeetingWith="A, B",
        )
        self.assertIn('nextMeeting:"2026-09-18"', js)
        self.assertIn('nextMeetingTitle:"Sync"', js)
        self.assertIn('nextMeetingWith:"A, B"', js)

    def test_last_email_by_present_and_escaped(self):
        js = self.rendered_for(LastEmail="2026-09-01", LastEmailBy='Sylvia "Syl" Bermudez')
        self.assertIn('lastEmailBy:"Sylvia \\"Syl\\" Bermudez"', js)

    def test_acv_renders_as_int_when_whole_number(self):
        js = self.rendered_for(ACV=12000.0)
        self.assertIn("acv:12000,", js)
        self.assertNotIn("acv:12000.0", js)

    def test_acv_renders_as_float_when_fractional(self):
        js = self.rendered_for(ACV=12000.5)
        self.assertIn("acv:12000.5", js)

    def test_output_is_syntactically_plausible_js_object_list(self):
        js = self.rendered_for()
        # Every emitted line should be one balanced-brace object literal
        # ending in a comma - a cheap structural smoke check that catches
        # unbalanced quoting/escaping bugs like the tier one above without
        # requiring a JS engine.
        for line in js.splitlines():
            line = line.strip()
            self.assertTrue(line.startswith("{") and line.endswith("},"), line)
            self.assertEqual(line.count("{"), line.count("}"))
            # An even number of unescaped double quotes means every string
            # literal opened is properly closed.
            unescaped_quotes = re.sub(r'\\.', '', line).count('"')
            self.assertEqual(unescaped_quotes % 2, 0, line)


class TestCyclePosition(unittest.TestCase):
    def test_first_of_month(self):
        days_into, days_remaining, cycle_len = generate.cycle_position(datetime.date(2026, 9, 1))
        self.assertEqual((days_into, days_remaining, cycle_len), (1, 29, 30))

    def test_last_of_month(self):
        days_into, days_remaining, cycle_len = generate.cycle_position(datetime.date(2026, 9, 30))
        self.assertEqual((days_into, days_remaining, cycle_len), (30, 0, 30))

    def test_leap_february(self):
        _, _, cycle_len = generate.cycle_position(datetime.date(2028, 2, 15))
        self.assertEqual(cycle_len, 29)

    def test_non_leap_february(self):
        _, _, cycle_len = generate.cycle_position(datetime.date(2026, 2, 15))
        self.assertEqual(cycle_len, 28)


class TestRenderProjectedJs(unittest.TestCase):
    def test_none_tier_renders_as_js_null(self):
        rows = [{
            "name": "Acme", "id": "001x", "tier": None, "stage": "Customer",
            "stageLabel": "Customer", "pct": 42.0, "acv": 12000.0,
            "daysIntoCycle": 9, "daysRemaining": 21, "cycleLen": 30,
        }]
        js = generate.render_projected_js(rows)
        self.assertIn("tier:null", js)
        self.assertNotIn('tier:"None"', js)

    def test_none_pct_renders_as_js_null(self):
        rows = [{
            "name": "Acme", "id": "001x", "tier": "SMB", "stage": "Customer",
            "stageLabel": "Customer", "pct": None, "acv": 12000.0,
            "daysIntoCycle": 9, "daysRemaining": 21, "cycleLen": 30,
        }]
        js = generate.render_projected_js(rows)
        self.assertIn("pct:null", js)

    def test_falls_back_to_tier_when_stage_missing(self):
        rows = [{
            "name": "Acme", "id": "001x", "tier": "SMB", "stage": None,
            "stageLabel": None, "pct": 10.0, "acv": 100.0,
            "daysIntoCycle": 1, "daysRemaining": 29, "cycleLen": 30,
        }]
        js = generate.render_projected_js(rows)
        self.assertIn('stage:"SMB"', js)
        self.assertIn('stageLabel:"SMB"', js)


class TestFillTemplate(unittest.TestCase):
    TODAY = datetime.date(2026, 9, 9)
    FAKE_TEMPLATE = (
        "asof=__ASOF__ flagged=__FLAGGED_N__ total=__TOTAL_N__ acv=__ACV_K__ "
        "renewN=__RENEW_N__ renewSub=__RENEW_SUB__ entN=__ENT_N__ entSub=__ENT_SUB__\n"
        "var ROWS = [\n__ROWS_JS__\n];\n"
        "projAsof=__PROJECTED_ASOF__\n"
        "var PROJ_ROWS = [\n__PROJECTED_ROWS_JS__\n];\n"
    )

    def test_all_placeholders_replaced(self):
        accounts = [make_account()]
        html, summary = generate.fill_template(self.FAKE_TEMPLATE, accounts, self.TODAY)
        self.assertNotRegex(html, r"__[A-Z_]+__")
        self.assertEqual(summary["total_n"], 1)

    def test_raises_on_unfilled_placeholder(self):
        bad_template = self.FAKE_TEMPLATE + "__NOT_A_REAL_FIELD__"
        with self.assertRaises(AssertionError):
            generate.fill_template(bad_template, [make_account()], self.TODAY)

    def test_renewal_summary_picks_soonest_within_60_days(self):
        accounts = [
            make_account(Id="a1", Pages=100, End="2026-11-08"),   # 60 days out
            make_account(Id="a2", Pages=100, End="2026-09-19"),   # 10 days out, soonest
            make_account(Id="a3", Pages=100, End="2027-09-09"),   # far out, excluded
        ]
        _, summary = generate.fill_template(self.FAKE_TEMPLATE, accounts, self.TODAY)
        self.assertEqual(summary["renew_n"], 2)
        self.assertTrue(summary["renew_sub"].startswith("Acme Inc"))
        self.assertIn("10 days", summary["renew_sub"])

    def test_renewal_summary_none_in_next_60_days(self):
        accounts = [make_account(Pages=100, End="2027-09-09")]
        _, summary = generate.fill_template(self.FAKE_TEMPLATE, accounts, self.TODAY)
        self.assertEqual(summary["renew_n"], 0)
        self.assertEqual(summary["renew_sub"], "None in the next 60 days")

    def test_enterprise_summary_lists_flagged_enterprise_accounts(self):
        accounts = [
            make_account(Id="a1", Pages=100, Tier="Enterprise", Name="BigCo"),
            make_account(Id="a2", Pages=5000, Tier="Enterprise", Name="HealthyCo"),
        ]
        _, summary = generate.fill_template(self.FAKE_TEMPLATE, accounts, self.TODAY)
        self.assertEqual(summary["ent_n"], 1)
        self.assertEqual(summary["ent_sub"], "BigCo")


if __name__ == "__main__":
    unittest.main()
