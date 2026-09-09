"""Unit tests for check_alerts.py.

Since 2026-09-09 this script only refreshes the dashboard's Projected
Usage section (the high/low alert email + hysteresis state machine it
used to run was retired in favor of mid_month_projection.py - see
check_alerts.py's own docstring). build_projected_rows() is pure
extrapolation logic and is tested directly with no mocking. The
Salesforce/HTTP functions are tested with urllib.request.urlopen mocked
out - no network access, no live org needed.
"""
import datetime
import json
import unittest
from unittest import mock

import check_alerts


def make_account(**over):
    base = {
        "Name": "Acme Inc", "Id": "001x", "Owner": "Jane Rep",
        "Stage": "Customer", "Tier": "SMB", "ACV": 12000.0,
        "Start": "2026-01-01", "End": "2027-01-01", "Cap": 120000.0,
        "Pages": 5000.0, "Hours": 3.0, "Users": 4.0,
    }
    base.update(over)
    return base


class TestBuildProjectedRows(unittest.TestCase):
    TODAY = datetime.date(2026, 9, 15)

    def test_extrapolates_pages_so_far_to_full_month(self):
        accounts = [make_account()]
        accounts_by_id = {a["Id"]: a for a in accounts}
        rows = [{"Id": "001x", "Name": "Acme Inc", "Tier": "SMB", "ACV": 12000.0}]
        result = check_alerts.build_projected_rows(rows, accounts_by_id, {"001x": 1000}, self.TODAY)
        self.assertEqual(len(result), 1)
        row = result[0]
        prorated_cap = 120000.0 / (365 / 30.44)
        expected = round((1000 / 15 * 30) / prorated_cap * 100, 1)
        self.assertEqual(row["pct"], expected)
        self.assertEqual(row["daysIntoCycle"], 15)
        self.assertEqual(row["cycleLen"], 30)

    def test_missing_mtd_entry_defaults_to_zero_pages(self):
        accounts = [make_account()]
        accounts_by_id = {a["Id"]: a for a in accounts}
        rows = [{"Id": "001x", "Name": "Acme Inc", "Tier": "SMB", "ACV": 12000.0}]
        result = check_alerts.build_projected_rows(rows, accounts_by_id, {}, self.TODAY)
        self.assertEqual(result[0]["pct"], 0)

    def test_missing_prorated_cap_yields_null_pct(self):
        accounts = [make_account(Cap=0)]
        accounts_by_id = {a["Id"]: a for a in accounts}
        rows = [{"Id": "001x", "Name": "Acme Inc", "Tier": "SMB", "ACV": 12000.0}]
        result = check_alerts.build_projected_rows(rows, accounts_by_id, {"001x": 1000}, self.TODAY)
        self.assertIsNone(result[0]["pct"])

    def test_stage_label_includes_tier_only_for_customer(self):
        accounts = [make_account(Stage="Prospect")]
        accounts_by_id = {a["Id"]: a for a in accounts}
        rows = [{"Id": "001x", "Name": "Acme Inc", "Tier": "SMB", "ACV": 12000.0}]
        result = check_alerts.build_projected_rows(rows, accounts_by_id, {"001x": 0}, self.TODAY)
        self.assertEqual(result[0]["stageLabel"], "Prospect")


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
