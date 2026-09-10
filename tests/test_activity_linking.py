"""Unit tests for activity_linking.py.

The reduce_* functions are pure and tested directly. The compute_*
orchestration functions are tested with check_alerts.soql mocked out -
no live org needed.
"""
import unittest
from unittest import mock

import activity_linking


class TestFetchContactAccountMap(unittest.TestCase):
    @mock.patch("activity_linking.check_alerts.soql")
    def test_maps_contact_to_account(self, mock_soql):
        mock_soql.return_value = [
            {"Id": "003a", "AccountId": "001x"},
            {"Id": "003b", "AccountId": "001x"},
            {"Id": "003c", "AccountId": "001y"},
        ]
        result = activity_linking.fetch_contact_account_map("https://x", "tok", ["001x", "001y"])
        self.assertEqual(result, {"003a": "001x", "003b": "001x", "003c": "001y"})

    def test_empty_account_ids_short_circuits(self):
        result = activity_linking.fetch_contact_account_map("https://x", "tok", [])
        self.assertEqual(result, {})


class TestReduceMainContactCounts(unittest.TestCase):
    def test_picks_highest_combined_count(self):
        winner = activity_linking.reduce_main_contact_counts(
            task_counts={"003a": 2, "003b": 5}, event_counts={"003a": 1, "003b": 1}
        )
        self.assertEqual(winner, "003b")  # 3 vs 6

    def test_sums_task_and_event_for_same_contact(self):
        winner = activity_linking.reduce_main_contact_counts(
            task_counts={"003a": 3}, event_counts={"003a": 4, "003b": 6}
        )
        self.assertEqual(winner, "003a")  # 003a: 3+4=7, 003b: 0+6=6 -> 003a wins

    def test_no_counts_returns_none(self):
        self.assertIsNone(activity_linking.reduce_main_contact_counts({}, {}))

    def test_ties_broken_deterministically_by_contact_id(self):
        winner = activity_linking.reduce_main_contact_counts(
            task_counts={"003b": 5}, event_counts={"003a": 5}
        )
        self.assertEqual(winner, "003b")  # higher string wins the tie


class TestComputeMainContacts(unittest.TestCase):
    @mock.patch("activity_linking.check_alerts.soql")
    def test_resolves_winning_contact_name(self, mock_soql):
        contact_account_map = {"003a": "001x", "003b": "001x"}

        def fake_soql(domain, token, query):
            if "COUNT(Id) cnt FROM Task" in query:
                return [{"WhoId": "003a", "cnt": 1}]
            if "COUNT(Id) cnt FROM Event" in query:
                return [{"WhoId": "003b", "cnt": 5}]
            if "SELECT Id, Name FROM Contact" in query:
                return [{"Id": "003b", "Name": "Jane Contact"}]
            raise AssertionError(f"unexpected query: {query}")

        mock_soql.side_effect = fake_soql
        result = activity_linking.compute_main_contacts("https://x", "tok", ["001x"], contact_account_map)
        self.assertEqual(result, {"001x": "Jane Contact"})

    @mock.patch("activity_linking.check_alerts.soql")
    def test_account_with_no_contacts_is_none(self, mock_soql):
        result = activity_linking.compute_main_contacts("https://x", "tok", ["001z"], {})
        self.assertEqual(result, {"001z": None})
        mock_soql.assert_not_called()


class TestReduceLastEmailTopN(unittest.TestCase):
    def test_first_occurrence_per_account_wins(self):
        contact_account_map = {"003a": "001x", "003b": "001x", "003c": "001y"}
        rows = [
            {"WhoId": "003a", "ActivityDate": "2026-09-09", "Owner": {"Name": "Rep One"}},
            {"WhoId": "003b", "ActivityDate": "2026-09-01", "Owner": {"Name": "Rep Two"}},
            {"WhoId": "003c", "ActivityDate": "2026-09-05", "Owner": {"Name": "Rep Three"}},
        ]
        result = activity_linking.reduce_last_email_top_n(rows, contact_account_map, ["001x", "001y"])
        self.assertEqual(result["001x"], ("2026-09-09", "Rep One"))
        self.assertEqual(result["001y"], ("2026-09-05", "Rep Three"))

    def test_account_absent_from_slice_is_absent_from_result(self):
        result = activity_linking.reduce_last_email_top_n([], {}, ["001x"])
        self.assertEqual(result, {})

    def test_missing_owner_is_none(self):
        contact_account_map = {"003a": "001x"}
        rows = [{"WhoId": "003a", "ActivityDate": "2026-09-09", "Owner": None}]
        result = activity_linking.reduce_last_email_top_n(rows, contact_account_map, ["001x"])
        self.assertEqual(result["001x"], ("2026-09-09", None))


class TestComputeLastEmail(unittest.TestCase):
    @mock.patch("activity_linking.check_alerts.soql")
    def test_falls_back_to_individual_query_for_missing_account(self, mock_soql):
        contact_account_map = {"003a": "001x"}

        def fake_soql(domain, token, query):
            if "LIMIT 2000" in query:
                return []  # account not in the top-2000 slice
            if "LIMIT 1" in query:
                return [{"ActivityDate": "2026-08-01", "Owner": {"Name": "Rep One"}}]
            raise AssertionError(f"unexpected query: {query}")

        mock_soql.side_effect = fake_soql
        result = activity_linking.compute_last_email("https://x", "tok", ["001x"], contact_account_map)
        self.assertEqual(result, {"001x": ("2026-08-01", "Rep One")})

    @mock.patch("activity_linking.check_alerts.soql")
    def test_no_email_at_all_is_none_none(self, mock_soql):
        contact_account_map = {"003a": "001x"}
        mock_soql.return_value = []
        result = activity_linking.compute_last_email("https://x", "tok", ["001x"], contact_account_map)
        self.assertEqual(result, {"001x": (None, None)})

    def test_no_contacts_at_all_short_circuits(self):
        result = activity_linking.compute_last_email("https://x", "tok", ["001x"], {})
        self.assertEqual(result, {"001x": (None, None)})


class TestComputeLastLogin(unittest.TestCase):
    @mock.patch("activity_linking.check_alerts.soql")
    def test_takes_max_across_event_and_task(self, mock_soql):
        import datetime
        contact_account_map = {"003a": "001x"}

        def fake_soql(domain, token, query):
            if "FROM Event" in query:
                return [{"ActivityDate": "2026-09-01"}]
            if "FROM Task" in query:
                return [{"ActivityDate": "2026-09-05"}]
            raise AssertionError(query)

        mock_soql.side_effect = fake_soql
        result = activity_linking.compute_last_login(
            "https://x", "tok", ["001x"], contact_account_map, datetime.date(2026, 9, 9)
        )
        self.assertEqual(result, {"001x": "2026-09-05"})

    @mock.patch("activity_linking.check_alerts.soql")
    def test_neither_object_has_a_row_is_none(self, mock_soql):
        import datetime
        contact_account_map = {"003a": "001x"}
        mock_soql.return_value = []
        result = activity_linking.compute_last_login(
            "https://x", "tok", ["001x"], contact_account_map, datetime.date(2026, 9, 9)
        )
        self.assertEqual(result, {"001x": None})


class TestReduceNextMeetingCandidates(unittest.TestCase):
    def test_takes_earliest_across_account_contacts(self):
        contact_account_map = {"003a": "001x", "003b": "001x"}
        rows = [
            {"WhoId": "003a", "mindate": "2026-09-20T10:00:00.000+0000"},
            {"WhoId": "003b", "mindate": "2026-09-15T10:00:00.000+0000"},
        ]
        result = activity_linking.reduce_next_meeting_candidates(rows, contact_account_map, ["001x"])
        self.assertEqual(result["001x"], "2026-09-15T10:00:00.000+0000")

    def test_account_with_no_future_event_is_absent(self):
        result = activity_linking.reduce_next_meeting_candidates([], {}, ["001x"])
        self.assertEqual(result, {})


class TestComputeSfEventNextMeetings(unittest.TestCase):
    @mock.patch("activity_linking.check_alerts.soql")
    def test_resolves_title_and_attendees(self, mock_soql):
        contact_account_map = {"003a": "001x"}

        def fake_soql(domain, token, query):
            if "MIN(StartDateTime)" in query:
                return [{"WhoId": "003a", "mindate": "2026-09-20T10:00:00.000+0000"}]
            if "SELECT Id, Subject, OwnerId FROM Event" in query:
                return [{"Id": "00Uevt", "Subject": "SiftMed x Acme Sync", "OwnerId": "005owner"}]
            if "FROM EventRelation" in query:
                return [{"RelationId": "005attendee"}, {"RelationId": "003contact"}]
            if "SELECT Id, Name FROM User" in query:
                return [{"Id": "005owner", "Name": "Owner Rep"}, {"Id": "005attendee", "Name": "Attendee Rep"}]
            raise AssertionError(query)

        mock_soql.side_effect = fake_soql
        result = activity_linking.compute_sf_event_next_meetings(
            "https://x", "tok", ["001x"], contact_account_map, "2026-09-09T00:00:00.000+0000"
        )
        self.assertEqual(result["001x"]["date"], "2026-09-20T10:00:00.000+0000")
        self.assertEqual(result["001x"]["title"], "SiftMed x Acme Sync")
        self.assertEqual(result["001x"]["with"], "Attendee Rep, Owner Rep")

    @mock.patch("activity_linking.check_alerts.soql")
    def test_no_future_event_absent_from_result(self, mock_soql):
        mock_soql.return_value = []
        result = activity_linking.compute_sf_event_next_meetings(
            "https://x", "tok", ["001x"], {"003a": "001x"}, "2026-09-09T00:00:00.000+0000"
        )
        self.assertEqual(result, {})

    @mock.patch("activity_linking.check_alerts.soql")
    def test_event_relation_without_extra_users_uses_owner_only(self, mock_soql):
        contact_account_map = {"003a": "001x"}

        def fake_soql(domain, token, query):
            if "MIN(StartDateTime)" in query:
                return [{"WhoId": "003a", "mindate": "2026-09-20T10:00:00.000+0000"}]
            if "SELECT Id, Subject, OwnerId FROM Event" in query:
                return [{"Id": "00Uevt", "Subject": "Solo Meeting", "OwnerId": "005owner"}]
            if "FROM EventRelation" in query:
                return []
            if "SELECT Id, Name FROM User" in query:
                return [{"Id": "005owner", "Name": "Owner Rep"}]
            raise AssertionError(query)

        mock_soql.side_effect = fake_soql
        result = activity_linking.compute_sf_event_next_meetings(
            "https://x", "tok", ["001x"], contact_account_map, "2026-09-09T00:00:00.000+0000"
        )
        self.assertEqual(result["001x"]["with"], "Owner Rep")


if __name__ == "__main__":
    unittest.main()
