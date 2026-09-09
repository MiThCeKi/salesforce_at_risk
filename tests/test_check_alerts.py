"""Unit tests for check_alerts.py.

decide_alert() is pure state-machine logic (see check_alerts.py's own
docstring for the agreed rules) and is tested directly with no mocking.
The Salesforce/HTTP functions are tested with urllib.request.urlopen
mocked out - no network access, no live org needed.
"""
import datetime
import json
import unittest
from unittest import mock

import check_alerts


def entry(state="normal", since=None, last_alert=None):
    return {"state": state, "since": since, "last_alert": last_alert}


class TestDecideAlertNormalState(unittest.TestCase):
    TODAY = datetime.date(2026, 9, 9)

    def test_crossing_above_high_threshold_sends_high_new(self):
        send, new = check_alerts.decide_alert(entry(), 120.0, self.TODAY)
        self.assertEqual(send, "high_new")
        self.assertEqual(new, {"state": "high", "since": "2026-09-09", "last_alert": "2026-09-09"})

    def test_exactly_at_high_threshold_does_not_trigger(self):
        send, new = check_alerts.decide_alert(entry(), 115.0, self.TODAY)
        self.assertIsNone(send)
        self.assertEqual(new["state"], "normal")

    def test_crossing_below_low_threshold_sends_low_new(self):
        send, new = check_alerts.decide_alert(entry(), 10.0, self.TODAY)
        self.assertEqual(send, "low_new")
        self.assertEqual(new, {"state": "low", "since": "2026-09-09", "last_alert": "2026-09-09"})

    def test_exactly_at_low_threshold_does_not_trigger(self):
        send, new = check_alerts.decide_alert(entry(), 25.0, self.TODAY)
        self.assertIsNone(send)
        self.assertEqual(new["state"], "normal")

    def test_healthy_middle_range_stays_normal_silently(self):
        send, new = check_alerts.decide_alert(entry(), 60.0, self.TODAY)
        self.assertIsNone(send)
        self.assertEqual(new, entry())


class TestDecideAlertHighState(unittest.TestCase):
    TODAY = datetime.date(2026, 9, 9)

    def test_still_high_within_reminder_window_stays_silent(self):
        cur = entry("high", since="2026-08-01", last_alert="2026-09-05")
        send, new = check_alerts.decide_alert(cur, 130.0, self.TODAY)
        self.assertIsNone(send)
        self.assertEqual(new, cur)

    def test_still_high_at_exactly_14_days_sends_reminder(self):
        cur = entry("high", since="2026-08-01", last_alert="2026-08-26")
        send, new = check_alerts.decide_alert(cur, 130.0, self.TODAY)
        self.assertEqual(send, "high_reminder")
        self.assertEqual(new["last_alert"], "2026-09-09")
        self.assertEqual(new["since"], "2026-08-01")  # since is preserved, not reset
        self.assertEqual(new["state"], "high")

    def test_still_high_just_under_14_days_stays_silent(self):
        cur = entry("high", since="2026-08-01", last_alert="2026-08-27")
        send, new = check_alerts.decide_alert(cur, 130.0, self.TODAY)
        self.assertIsNone(send)

    def test_last_alert_none_sends_reminder_immediately(self):
        # Defensive case: a hand-edited or corrupted state file with
        # state=high but no recorded last_alert should not get stuck mute.
        cur = entry("high", since="2026-08-01", last_alert=None)
        send, new = check_alerts.decide_alert(cur, 130.0, self.TODAY)
        self.assertEqual(send, "high_reminder")

    def test_dropping_to_exactly_threshold_resets_to_normal_silently(self):
        cur = entry("high", since="2026-08-01", last_alert="2026-08-01")
        send, new = check_alerts.decide_alert(cur, 115.0, self.TODAY)
        self.assertIsNone(send)
        self.assertEqual(new, {"state": "normal", "since": None, "last_alert": None})

    def test_dropping_below_threshold_resets_to_normal_silently(self):
        cur = entry("high", since="2026-08-01", last_alert="2026-08-01")
        send, new = check_alerts.decide_alert(cur, 50.0, self.TODAY)
        self.assertIsNone(send)
        self.assertEqual(new["state"], "normal")


class TestDecideAlertLowState(unittest.TestCase):
    TODAY = datetime.date(2026, 9, 9)

    def test_still_low_within_reminder_window_stays_silent(self):
        cur = entry("low", since="2026-08-01", last_alert="2026-09-05")
        send, new = check_alerts.decide_alert(cur, 5.0, self.TODAY)
        self.assertIsNone(send)

    def test_still_low_at_14_days_sends_reminder(self):
        cur = entry("low", since="2026-08-01", last_alert="2026-08-26")
        send, new = check_alerts.decide_alert(cur, 5.0, self.TODAY)
        self.assertEqual(send, "low_reminder")

    def test_staying_low_state_between_25_and_30_does_not_reset(self):
        # Between the alert threshold (25) and the reset threshold (30) is
        # the hysteresis band: still counted as "low" state, so a reminder
        # can still fire, but it does NOT bounce back to normal.
        cur = entry("low", since="2026-08-01", last_alert="2026-08-26")
        send, new = check_alerts.decide_alert(cur, 28.0, self.TODAY)
        self.assertEqual(send, "low_reminder")
        self.assertEqual(new["state"], "low")

    def test_climbing_above_reset_threshold_resets_to_normal(self):
        cur = entry("low", since="2026-08-01", last_alert="2026-08-01")
        send, new = check_alerts.decide_alert(cur, 30.1, self.TODAY)
        self.assertIsNone(send)
        self.assertEqual(new, {"state": "normal", "since": None, "last_alert": None})

    def test_exactly_at_reset_threshold_does_not_reset(self):
        cur = entry("low", since="2026-08-01", last_alert="2026-09-05")
        send, new = check_alerts.decide_alert(cur, 30.0, self.TODAY)
        # 30.0 is not > 30.0, so still "low"; last_alert is recent, so no
        # reminder fires either - net effect is a silent no-op, not a reset.
        self.assertIsNone(send)
        self.assertEqual(new["state"], "low")


class TestFetchAccounts(unittest.TestCase):
    def _mock_response(self, payload):
        cm = mock.MagicMock()
        cm.__enter__.return_value = cm
        cm.read.return_value = json.dumps(payload).encode("utf-8")
        return cm

    @mock.patch("check_alerts.urllib.request.urlopen")
    def test_maps_fields_and_defaults_missing_owner(self, mock_urlopen):
        mock_urlopen.return_value = self._mock_response({
            "done": True, "nextRecordsUrl": None,
            "records": [{
                "Id": "001x", "Name": "Acme", "Owner": None, "Stage__c": "Customer",
                "Account_Tier__c": "SMB", "Annual_Contract_Value__c": 1000.0,
                "PageCountCap__c": 10000.0, "Active_Contract_Start_Date__c": "2026-01-01",
                "Subscription_End_Date__c": "2027-01-01", "Pages_Last_30__c": None,
                "Hours_Last_30__c": None, "Active_Users_Last_30__c": None,
            }],
        })
        accounts = check_alerts.fetch_accounts("https://example.my.salesforce.com", "tok")
        self.assertEqual(len(accounts), 1)
        a = accounts[0]
        self.assertEqual(a["Owner"], "")  # missing Owner.Name defaults to ""
        self.assertEqual(a["Pages"], 0)   # None Pages_Last_30__c defaults to 0
        self.assertEqual(a["Hours"], 0)
        self.assertEqual(a["Users"], 0)

    @mock.patch("check_alerts.urllib.request.urlopen")
    def test_soql_follows_pagination(self, mock_urlopen):
        page1 = {"done": False, "nextRecordsUrl": "/next", "records": [{"Id": "1"}]}
        page2 = {"done": True, "nextRecordsUrl": None, "records": [{"Id": "2"}]}
        mock_urlopen.side_effect = [self._mock_response(page1), self._mock_response(page2)]
        records = check_alerts.soql("https://example.my.salesforce.com", "tok", "SELECT Id FROM Account")
        self.assertEqual([r["Id"] for r in records], ["1", "2"])
        self.assertEqual(mock_urlopen.call_count, 2)


class TestFetchMonthToDatePages(unittest.TestCase):
    @mock.patch("check_alerts.soql")
    def test_maps_account_id_to_total_defaulting_none_to_zero(self, mock_soql):
        mock_soql.return_value = [
            {"Related_Account__c": "001a", "total": 500},
            {"Related_Account__c": "001b", "total": None},
        ]
        result = check_alerts.fetch_month_to_date_pages(
            "https://example.my.salesforce.com", "tok", datetime.date(2026, 9, 9)
        )
        self.assertEqual(result, {"001a": 500, "001b": 0})

    @mock.patch("check_alerts.soql")
    def test_query_filters_from_first_of_month(self, mock_soql):
        mock_soql.return_value = []
        check_alerts.fetch_month_to_date_pages(
            "https://example.my.salesforce.com", "tok", datetime.date(2026, 9, 17)
        )
        query = mock_soql.call_args[0][2]
        self.assertIn("2026-09-01", query)
        self.assertNotIn("2026-09-17", query)


class TestPushProjectedSectionLive(unittest.TestCase):
    LIVE_HTML = (
        "<html><span id=\"projAsof\">OLD DATE</span>"
        "<script>var PROJ_ROWS = [\n  {name:\"Old\"},\n  ];</script></html>"
    )

    @mock.patch("check_alerts.patch_static_resource_body")
    @mock.patch("check_alerts.get_static_resource_body")
    def test_replaces_rows_and_date_leaves_rest_untouched(self, mock_get, mock_patch):
        mock_get.return_value = self.LIVE_HTML
        mock_patch.return_value = 204
        rows = [{
            "name": "Acme", "id": "001x", "tier": "SMB", "stage": "Customer",
            "stageLabel": "Customer", "pct": 10.0, "acv": 100.0,
            "daysIntoCycle": 9, "daysRemaining": 21, "cycleLen": 30,
        }]
        status = check_alerts.push_projected_section_live(
            "https://example.my.salesforce.com", "tok", "SEP 09, 2026", rows
        )
        self.assertEqual(status, 204)
        pushed_html = mock_patch.call_args[0][3]
        self.assertIn('<span id="projAsof">SEP 09, 2026</span>', pushed_html)
        self.assertIn('name:"Acme"', pushed_html)
        self.assertNotIn("Old", pushed_html)
        self.assertTrue(pushed_html.startswith("<html>"))
        self.assertTrue(pushed_html.endswith("</html>"))

    @mock.patch("check_alerts.get_static_resource_body")
    def test_raises_if_proj_rows_block_missing(self, mock_get):
        mock_get.return_value = "<html><span id=\"projAsof\">OLD</span></html>"
        with self.assertRaises(RuntimeError):
            check_alerts.push_projected_section_live(
                "https://example.my.salesforce.com", "tok", "SEP 09, 2026", []
            )

    @mock.patch("check_alerts.get_static_resource_body")
    def test_raises_if_projasof_span_missing(self, mock_get):
        mock_get.return_value = "<html><script>var PROJ_ROWS = [\n  ];</script></html>"
        with self.assertRaises(RuntimeError):
            check_alerts.push_projected_section_live(
                "https://example.my.salesforce.com", "tok", "SEP 09, 2026", []
            )


class TestPatchStaticResourceBody(unittest.TestCase):
    @mock.patch("check_alerts.urllib.request.urlopen")
    def test_base64_encodes_body_and_uses_patch_method(self, mock_urlopen):
        import base64
        cm = mock.MagicMock()
        cm.__enter__.return_value = cm
        cm.status = 204
        mock_urlopen.return_value = cm

        status = check_alerts.patch_static_resource_body(
            "https://example.my.salesforce.com", "tok", "081xyz", "<html>hi</html>"
        )
        self.assertEqual(status, 204)
        sent_request = mock_urlopen.call_args[0][0]
        self.assertEqual(sent_request.get_method(), "PATCH")
        body = json.loads(sent_request.data)
        self.assertEqual(base64.b64decode(body["Body"]).decode("utf-8"), "<html>hi</html>")


if __name__ == "__main__":
    unittest.main()
