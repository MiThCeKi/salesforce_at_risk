"""Integration/smoke tests over the repo's actual committed artifacts:
template.html, generate.py's live accounts snapshot, and the JSON state
files check_alerts.py reads and writes.

These catch a different class of bug than the unit tests: template drift
(a placeholder renamed in one file but not the other), rendered-JS syntax
errors that only show up with real data/escaping, and malformed persisted
state - the kind of thing that only bites in production, not in a
hand-built fixture.
"""
import datetime
import json
import os
import shutil
import subprocess
import unittest

import generate

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
NODE = shutil.which("node") or "/opt/node22/bin/node"


def _read(name):
    with open(os.path.join(REPO_ROOT, name)) as fh:
        return fh.read()


class TestTemplatePlaceholdersMatchFillTemplate(unittest.TestCase):
    def test_every_template_placeholder_gets_filled(self):
        template_text = _read("template.html")
        html, summary = generate.fill_template(template_text, generate.accounts, generate.TODAY)
        import re
        remaining = re.findall(r"__[A-Z_]+__", html)
        self.assertEqual(remaining, [], f"Unfilled placeholders in real template: {remaining}")

    def test_output_is_larger_than_template_and_nonempty(self):
        template_text = _read("template.html")
        html, _ = generate.fill_template(template_text, generate.accounts, generate.TODAY)
        self.assertGreater(len(html), len(template_text))


class TestRenderedJsIsValidJavascript(unittest.TestCase):
    """Renders the real accounts snapshot's JS and hands it to node to
    parse - the check that would have caught the tier:"None" bug and any
    future escaping mistake, since it exercises actual production data
    rather than a hand-picked fixture."""

    def _assert_valid_js_array(self, rows_js):
        if not shutil.which(NODE) and not os.path.exists(NODE):
            self.skipTest("node not available in this environment")
        script = "var ROWS = [\n" + rows_js + "\n];\nJSON.stringify(ROWS.length);"
        proc = subprocess.run([NODE, "-e", script], capture_output=True, text=True, timeout=30)
        self.assertEqual(
            proc.returncode, 0,
            f"Rendered JS failed to parse:\n{proc.stderr}\n---\nFirst 500 chars:\n{rows_js[:500]}",
        )

    def test_main_table_rows_are_valid_js(self):
        rows = generate.compute_rows(generate.accounts, generate.TODAY)
        self._assert_valid_js_array(generate.render_rows_js(rows))

    def test_projected_snapshot_rows_are_valid_js(self):
        path = os.path.join(REPO_ROOT, "projected_snapshot.json")
        if not os.path.exists(path):
            self.skipTest("projected_snapshot.json not present")
        with open(path) as fh:
            data = json.load(fh)
        self._assert_valid_js_array(generate.render_projected_js(data["rows"]))


class TestProjectedSnapshotSchema(unittest.TestCase):
    def test_shape_and_types(self):
        path = os.path.join(REPO_ROOT, "projected_snapshot.json")
        if not os.path.exists(path):
            self.skipTest("projected_snapshot.json not present")
        with open(path) as fh:
            data = json.load(fh)
        self.assertIn("asOf", data)
        self.assertIn("rows", data)
        self.assertIsInstance(data["rows"], list)
        required_keys = {
            "name", "id", "tier", "stage", "stageLabel", "pct", "acv",
            "daysIntoCycle", "daysRemaining", "cycleLen",
        }
        for row in data["rows"]:
            self.assertEqual(set(row.keys()), required_keys, row.get("id"))
            self.assertIsInstance(row["daysIntoCycle"], int)
            self.assertIsInstance(row["daysRemaining"], int)
            self.assertIsInstance(row["cycleLen"], int)


class TestOverageProjectionSchema(unittest.TestCase):
    """Schema check for mid_month_projection.py's output - the sole source
    of the (now monthly, mid-month) overage email, replacing the old
    pending_alerts.json/alert_state.json pair this file used to check."""

    def test_shape_and_types(self):
        path = os.path.join(REPO_ROOT, "overage_projection.json")
        if not os.path.exists(path):
            self.skipTest("overage_projection.json not present (gitignored / no run yet)")
        with open(path) as fh:
            data = json.load(fh)
        self.assertIn("asOf", data)
        self.assertIn("dayOfMonth", data)
        self.assertIn("accounts", data)
        self.assertIsInstance(data["accounts"], list)
        required_keys = {"id", "name", "owner", "projectedPct", "pagesSoFar", "acv"}
        for entry in data["accounts"]:
            self.assertEqual(set(entry.keys()), required_keys, entry)
            self.assertIsInstance(entry["projectedPct"], (int, float))
            self.assertGreater(entry["projectedPct"], 150.0, entry)


class TestAccountsSnapshotShape(unittest.TestCase):
    """Structural checks on generate.py's accounts array - deliberately NOT
    a "no stale dates" check, since that array is a point-in-time snapshot
    by design (see generate.py's own docstring) and would fail every day
    on schedule rather than on an actual bug."""

    REQUIRED_KEYS = {
        "Name", "Id", "Owner", "Stage", "Tier", "ACV", "Start", "End", "Cap",
        "Pages", "Hours", "Users", "MainContact", "LastEmail", "LastEmailBy", "LastLogin",
        "NextMeeting", "NextMeetingTitle", "NextMeetingWith",
        "NextInternalMeeting", "NextInternalMeetingTitle",
    }

    def test_no_duplicate_account_ids(self):
        ids = [a["Id"] for a in generate.accounts]
        dupes = {i for i in ids if ids.count(i) > 1}
        self.assertEqual(dupes, set())

    def test_every_account_has_required_keys(self):
        for a in generate.accounts:
            self.assertEqual(set(a.keys()), self.REQUIRED_KEYS, a.get("Name"))

    def test_meeting_fields_consistent_null_pairing(self):
        # A meeting date with no title (or vice versa) usually indicates a
        # partial/corrupted refresh - flag it rather than silently render it.
        for a in generate.accounts:
            has_date = a.get("NextMeeting") is not None
            has_title = a.get("NextMeetingTitle") is not None
            self.assertEqual(
                has_date, has_title,
                f"{a['Name']}: NextMeeting={a.get('NextMeeting')!r} but "
                f"NextMeetingTitle={a.get('NextMeetingTitle')!r}",
            )

    def test_contract_dates_parse_and_are_ordered(self):
        for a in generate.accounts:
            if a.get("Start") and a.get("End"):
                self.assertLess(
                    generate.parse(a["Start"]), generate.parse(a["End"]),
                    f"{a['Name']}: Start {a['Start']} not before End {a['End']}",
                )


if __name__ == "__main__":
    unittest.main()
