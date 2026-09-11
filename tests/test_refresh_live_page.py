"""Unit tests for refresh_live_page.py.

build_account_records/apply_overrides/_regex_replace_one are pure and
tested directly. push_main_table_live is tested with check_alerts'
Salesforce calls mocked out - the regex patterns themselves were
separately validated by hand against a real fetched live page (see
2026-09-10 session notes) before this pipeline was ever wired into the
live Routines, since a wrong regex here pushes straight to production.
"""
import os
import re
import unittest
from unittest import mock

import refresh_live_page as rlp

FAKE_SF_ENV = {"SF_CONSUMER_KEY": "fake_key", "SF_CONSUMER_SECRET": "fake_secret"}


class TestBuildAccountRecords(unittest.TestCase):
    def test_merges_activity_fields_and_defaults_next_meeting_to_sf_candidate(self):
        accounts = [{"Id": "001x", "Name": "Acme"}]
        records = rlp.build_account_records(
            accounts,
            contact_account_map={},
            main_contacts={"001x": "Jane Contact"},
            last_emails={"001x": ("2026-09-01", "Rep One")},
            last_logins={"001x": "2026-09-05"},
            sf_meetings={"001x": {"date": "2026-09-20T10:00:00.000+0000", "title": "Sync", "with": "Rep One"}},
        )
        r = records[0]
        self.assertEqual(r["MainContact"], "Jane Contact")
        self.assertEqual(r["LastEmail"], "2026-09-01")
        self.assertEqual(r["LastEmailBy"], "Rep One")
        self.assertEqual(r["LastLogin"], "2026-09-05")
        self.assertEqual(r["NextMeeting"], "2026-09-20")
        self.assertEqual(r["NextMeetingTitle"], "Sync")
        self.assertEqual(r["NextMeetingWith"], "Rep One")
        self.assertEqual(r["SFEventNextMeeting"], "2026-09-20T10:00:00.000+0000")
        self.assertIsNone(r["NextInternalMeeting"])
        self.assertIsNone(r["NextInternalMeetingTitle"])

    def test_missing_account_gets_all_nulls(self):
        accounts = [{"Id": "001z", "Name": "Nobody Home"}]
        records = rlp.build_account_records(accounts, {}, {}, {}, {}, {})
        r = records[0]
        self.assertIsNone(r["MainContact"])
        self.assertIsNone(r["LastEmail"])
        self.assertIsNone(r["LastEmailBy"])
        self.assertIsNone(r["LastLogin"])
        self.assertIsNone(r["NextMeeting"])

    def test_does_not_mutate_input_account_dict(self):
        original = {"Id": "001x", "Name": "Acme"}
        accounts = [original]
        rlp.build_account_records(accounts, {}, {}, {}, {}, {})
        self.assertEqual(original, {"Id": "001x", "Name": "Acme"})

    def test_health_score_from_the_account_fetch_passes_through_untouched(self):
        # HealthScore comes straight from check_alerts.fetch_accounts (part
        # of the base account dict), not from any activity_linking
        # compute_* output - this only confirms the dict(a) copy in
        # build_account_records doesn't drop it.
        accounts = [{"Id": "001x", "Name": "Acme", "HealthScore": 0}]
        records = rlp.build_account_records(accounts, {}, {}, {}, {}, {})
        self.assertEqual(records[0]["HealthScore"], 0)


class TestApplyOverrides(unittest.TestCase):
    def test_override_replaces_next_meeting_fields(self):
        accounts = [{"Id": "001x", "NextMeeting": "2026-09-20", "NextMeetingTitle": "SF Sync", "NextMeetingWith": "A"}]
        overrides = {"001x": {"NextMeeting": "2026-09-15", "NextMeetingTitle": "Calendar Sync", "NextMeetingWith": "B, C"}}
        result = rlp.apply_overrides(accounts, overrides)
        self.assertEqual(result[0]["NextMeeting"], "2026-09-15")
        self.assertEqual(result[0]["NextMeetingTitle"], "Calendar Sync")
        self.assertEqual(result[0]["NextMeetingWith"], "B, C")

    def test_can_set_internal_meeting_fields(self):
        accounts = [{"Id": "001x", "NextInternalMeeting": None, "NextInternalMeetingTitle": None}]
        overrides = {"001x": {"NextInternalMeeting": "2026-09-18", "NextInternalMeetingTitle": "SiftMed x MVP Sync"}}
        result = rlp.apply_overrides(accounts, overrides)
        self.assertEqual(result[0]["NextInternalMeeting"], "2026-09-18")
        self.assertEqual(result[0]["NextInternalMeetingTitle"], "SiftMed x MVP Sync")

    def test_override_cannot_touch_unlisted_fields(self):
        accounts = [{"Id": "001x", "ACV": 12000.0, "NextMeeting": "2026-09-20"}]
        overrides = {"001x": {"ACV": 999999.0, "NextMeeting": "2026-09-15"}}
        result = rlp.apply_overrides(accounts, overrides)
        self.assertEqual(result[0]["ACV"], 12000.0)  # untouched - not in OVERRIDE_FIELDS
        self.assertEqual(result[0]["NextMeeting"], "2026-09-15")

    def test_account_with_no_override_entry_is_untouched(self):
        accounts = [{"Id": "001x", "NextMeeting": "2026-09-20"}]
        result = rlp.apply_overrides(accounts, {})
        self.assertEqual(result[0]["NextMeeting"], "2026-09-20")


class TestRegexReplaceOne(unittest.TestCase):
    def test_replaces_single_match(self):
        text = '<span id="asof">OLD</span>'
        result = rlp._regex_replace_one(
            text, r'(<span id="asof">)[^<]*(</span>)',
            lambda m: m.group(1) + "NEW" + m.group(2), "asof span",
        )
        self.assertEqual(result, '<span id="asof">NEW</span>')

    def test_raises_on_zero_matches(self):
        with self.assertRaises(RuntimeError):
            rlp._regex_replace_one("no match here", r'id="nope"', lambda m: "x", "nope")

    def test_raises_on_multiple_matches(self):
        text = '<div id="x">A</div><div id="x">B</div>'
        with self.assertRaises(RuntimeError):
            rlp._regex_replace_one(text, r'(id="x">)[^<]*(</div>)', lambda m: m.group(0), "dup")

    def test_replacement_with_literal_backslash_is_not_misinterpreted(self):
        # The whole reason this uses a callable, not a plain string: a
        # plain re.sub replacement string treats \g and \1 specially.
        # js_escape output can contain a literal backslash (escaped
        # quotes) - confirm it comes through completely unmangled.
        text = '<span id="x">OLD</span>'
        replacement_with_backslash = 'name:"Rep \\"Nickname\\" Person"'
        result = rlp._regex_replace_one(
            text, r'(<span id="x">)[^<]*(</span>)',
            lambda m: m.group(1) + replacement_with_backslash + m.group(2), "x",
        )
        self.assertIn(replacement_with_backslash, result)


class TestPushMainTableLive(unittest.TestCase):
    LIVE_HTML = (
        '<span id="asof">OLD DATE</span>'
        '<div class="value" id="statFlagged">1</div>'
        '<span id="statTotal">1</span>'
        '<div class="value" id="statRenew">0</div>'
        '<div class="sub" id="statRenewSub">None in the next 60 days</div>'
        '<div class="value plain" id="statEnt">0</div>'
        '<div class="sub" id="statEntSub">None</div>'
        'data-tip="1 of SiftMed\'s 1 tracked accounts blah blah"'
        '<script>var ROWS = [\n    {name:"Old"},\n  ];</script>'
    )

    @mock.patch.dict(os.environ, FAKE_SF_ENV)
    @mock.patch("refresh_live_page.check_alerts.patch_static_resource_body")
    @mock.patch("refresh_live_page.check_alerts.get_static_resource_body")
    @mock.patch("refresh_live_page.check_alerts.get_access_token")
    def test_replaces_all_sections_leaves_rest_untouched(self, mock_token, mock_get, mock_patch):
        mock_token.return_value = "tok"
        mock_get.return_value = self.LIVE_HTML
        mock_patch.return_value = 204
        stats = {
            "asof": "SEP 10, 2026", "flagged_n": 2, "total_n": 3, "acv_k": "$2K",
            "renew_n": 1, "renew_sub": "Acme &mdash; 5 days, 1.0% usage",
            "ent_n": 1, "ent_sub": "BigCo",
        }
        status = rlp.push_main_table_live("    {name:\"New\"},", stats)
        self.assertEqual(status, 204)
        pushed = mock_patch.call_args[0][3]
        self.assertIn('id="asof">SEP 10, 2026<', pushed)
        self.assertIn('id="statFlagged">2<', pushed)
        self.assertIn('id="statTotal">3<', pushed)
        self.assertIn('id="statRenew">1<', pushed)
        self.assertIn('id="statRenewSub">Acme &mdash; 5 days, 1.0% usage<', pushed)
        self.assertIn('id="statEnt">1<', pushed)
        self.assertIn('id="statEntSub">BigCo<', pushed)
        self.assertIn("2 of SiftMed's 3 tracked accounts", pushed)
        self.assertIn('name:"New"', pushed)
        self.assertNotIn('name:"Old"', pushed)

    @mock.patch.dict(os.environ, FAKE_SF_ENV)
    @mock.patch("refresh_live_page.check_alerts.get_access_token")
    @mock.patch("refresh_live_page.check_alerts.get_static_resource_body")
    def test_raises_if_a_section_is_missing(self, mock_get, mock_token):
        mock_token.return_value = "tok"
        mock_get.return_value = "<html>nothing matches here</html>"
        stats = {"asof": "X", "flagged_n": 1, "total_n": 1, "acv_k": "$1K", "renew_n": 0,
                  "renew_sub": "None", "ent_n": 0, "ent_sub": "None"}
        with self.assertRaises(RuntimeError):
            rlp.push_main_table_live("{}", stats)


if __name__ == "__main__":
    unittest.main()
