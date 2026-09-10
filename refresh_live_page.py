"""
refresh_live_page.py

Orchestrates the daily refresh of both live "At-Risk Accounts" pages (the
claude.ai artifact and the Salesforce Static Resource) from live
Salesforce data. Added 2026-09-10, user request: replaces what used to be
~150 lines of duplicated, hand-maintained natural-language SOQL
instructions in each Routine's own prompt with tested Python. See
activity_linking.py's docstring for why the Calendar/Gmail cross-check
specifically can't be folded in here too - it needs the interactive
agent's own tool access, which a bash subprocess doesn't have in this
environment.

Two phases, because of that split:

  fetch    - pulls everything computable from Salesforce REST alone
             (account fetch incl. generate.MANUAL_INCLUDE_IDS, MainContact,
             LastEmail/LastEmailBy, LastLogin, and the Salesforce-Event-only
             Next Meeting candidate) and writes live_data.json. NextMeeting/
             NextMeetingTitle/NextMeetingWith default to that SF-Event
             candidate (so a run that skips the Calendar cross-check still
             gets a sane main Next Meeting rather than losing it);
             NextInternalMeeting/NextInternalMeetingTitle default to null
             since Calendar is the ONLY source for those.

  finalize - reads live_data.json (+ an optional calendar_overrides.json
             the calling Routine writes after doing its own Calendar/Gmail
             cross-check - a dict of {accountId: {field: value, ...}},
             only for accounts where the cross-check changed something),
             computes final rows/stats via generate.py, and writes
             live_page_fragment.json (asof + the stat-tile values + the
             exact ROWS JS text) for the Routine to graft into whichever
             live page it's refreshing. Pass --push-sf to also PATCH the
             Salesforce Static Resource directly (eyebrow date, stat
             tiles, and the ROWS block only - the Routine still owns any
             free-text wording change, e.g. naming a newly-excluded
             multi-year example account in the tooltip prose).

Usage:
  python3 refresh_live_page.py fetch
  python3 refresh_live_page.py finalize [--overrides calendar_overrides.json] [--push-sf]
"""
import argparse
import datetime
import json
import os
import re

import activity_linking
import check_alerts
import generate

LIVE_DATA_PATH = "live_data.json"
FRAGMENT_PATH = "live_page_fragment.json"

OVERRIDE_FIELDS = (
    "NextMeeting", "NextMeetingTitle", "NextMeetingWith",
    "NextInternalMeeting", "NextInternalMeetingTitle",
)


def _sf_credentials():
    my_domain = os.environ.get("SF_MY_DOMAIN", "https://siftmed.my.salesforce.com").rstrip("/")
    consumer_key = os.environ["SF_CONSUMER_KEY"]
    consumer_secret = os.environ["SF_CONSUMER_SECRET"]
    return my_domain, consumer_key, consumer_secret


def build_account_records(accounts, contact_account_map, main_contacts, last_emails, last_logins, sf_meetings):
    """Pure: merges the activity_linking outputs onto the fetched accounts
    list, producing the full generate.py-schema account dicts (Next
    Meeting fields defaulted to the Salesforce-Event candidate - see
    module docstring). Separated from fetch() so this merge step is
    unit-testable without mocking Salesforce."""
    records = []
    for a in accounts:
        aid = a["Id"]
        record = dict(a)
        record["LastLogin"] = last_logins.get(aid)
        record["MainContact"] = main_contacts.get(aid)
        last_email_date, last_email_by = last_emails.get(aid, (None, None))
        record["LastEmail"] = last_email_date
        record["LastEmailBy"] = last_email_by

        meeting = sf_meetings.get(aid)
        sf_date = meeting["date"][:10] if meeting else None
        record["SFEventNextMeeting"] = meeting["date"] if meeting else None
        record["NextMeeting"] = sf_date
        record["NextMeetingTitle"] = meeting["title"] if meeting else None
        record["NextMeetingWith"] = meeting["with"] if meeting else None
        record["NextInternalMeeting"] = None
        record["NextInternalMeetingTitle"] = None
        records.append(record)
    return records


def fetch(today=None):
    today = today or datetime.date.today()
    my_domain, consumer_key, consumer_secret = _sf_credentials()
    token = check_alerts.get_access_token(my_domain, consumer_key, consumer_secret)

    accounts = check_alerts.fetch_accounts(my_domain, token)
    account_ids = [a["Id"] for a in accounts]
    contact_account_map = activity_linking.fetch_contact_account_map(my_domain, token, account_ids)

    main_contacts = activity_linking.compute_main_contacts(my_domain, token, account_ids, contact_account_map)
    last_emails = activity_linking.compute_last_email(my_domain, token, account_ids, contact_account_map)
    last_logins = activity_linking.compute_last_login(my_domain, token, account_ids, contact_account_map, today)
    now_iso = datetime.datetime.utcnow().isoformat(timespec="milliseconds") + "Z"
    sf_meetings = activity_linking.compute_sf_event_next_meetings(
        my_domain, token, account_ids, contact_account_map, now_iso
    )

    records = build_account_records(accounts, contact_account_map, main_contacts, last_emails, last_logins, sf_meetings)

    with open(LIVE_DATA_PATH, "w") as fh:
        json.dump({"asOf": today.isoformat(), "accounts": records}, fh, indent=2)
    print(f"Wrote {LIVE_DATA_PATH}: {len(records)} accounts")


def apply_overrides(accounts, overrides):
    """Pure: overrides is {accountId: {field: value}} - only OVERRIDE_FIELDS
    are ever applied, so a malformed or over-broad overrides file can't
    silently corrupt an unrelated field."""
    for a in accounts:
        o = overrides.get(a["Id"])
        if not o:
            continue
        for field in OVERRIDE_FIELDS:
            if field in o:
                a[field] = o[field]
    return accounts


def _regex_replace_one(text, pattern, build_replacement, label, flags=0):
    """Replaces exactly one match of `pattern`, via a CALLABLE replacement
    (never a plain string - a plain replacement string lets re interpret
    backslashes as backreferences like \\1/\\g<...>, and
    generate.js_escape's output legitimately contains literal backslashes
    from escaped quotes that would otherwise corrupt the push).

    Deliberately counts matches with a separate finditer pass rather than
    relying on re.subn(count=1)'s return count: subn with count=1 stops
    after the first hit, so it can only ever report 0 or 1 - it can't
    distinguish "exactly one match" from "two matches, silently replaced
    only the first." This is pushing to a live production page, so that
    distinction is worth the trivial extra scan on a ~70KB string.
    Raises if the true match count isn't exactly 1, aborting the push
    cleanly rather than risking a partial or wrong live write."""
    count = len(re.findall(pattern, text, flags))
    if count != 1:
        raise RuntimeError(f"Could not find {label} on the live page ({count} matches) - aborting live push.")
    return re.sub(pattern, lambda m: build_replacement(m), text, count=1, flags=flags)


def push_main_table_live(rows_js, stats):
    """PATCHes the live Salesforce Static Resource's eyebrow date, stat
    tiles, and main ROWS block - never the Projected Usage section
    (check_alerts.push_projected_section_live owns that) and never the
    free-text tooltip prose beyond its leading 'N of SiftMed's M tracked
    accounts' numbers."""
    my_domain, consumer_key, consumer_secret = _sf_credentials()
    token = check_alerts.get_access_token(my_domain, consumer_key, consumer_secret)
    current = check_alerts.get_static_resource_body(my_domain, token, check_alerts.STATIC_RESOURCE_ID)

    updated = current
    updated = _regex_replace_one(
        updated, r'(<span id="asof">)[^<]*(</span>)',
        lambda m: m.group(1) + stats["asof"] + m.group(2), "asof span",
    )
    updated = _regex_replace_one(
        updated, r'(id="statFlagged">)[^<]*(</div>)',
        lambda m: m.group(1) + str(stats["flagged_n"]) + m.group(2), "statFlagged tile",
    )
    updated = _regex_replace_one(
        updated, r'(id="statTotal">)[^<]*(</span>)',
        lambda m: m.group(1) + str(stats["total_n"]) + m.group(2), "statTotal",
    )
    updated = _regex_replace_one(
        updated, r'(id="statACV">)[^<]*(</div>)',
        lambda m: m.group(1) + stats["acv_k"] + m.group(2), "statACV tile",
    )
    updated = _regex_replace_one(
        updated, r'(id="statRenew">)[^<]*(</div>)',
        lambda m: m.group(1) + str(stats["renew_n"]) + m.group(2), "statRenew tile",
    )
    updated = _regex_replace_one(
        updated, r'(id="statRenewSub">)[^<]*(</div>)',
        lambda m: m.group(1) + stats["renew_sub"] + m.group(2), "statRenewSub",
    )
    updated = _regex_replace_one(
        updated, r'(id="statEnt">)[^<]*(</div>)',
        lambda m: m.group(1) + str(stats["ent_n"]) + m.group(2), "statEnt tile",
    )
    updated = _regex_replace_one(
        updated, r'(id="statEntSub">)[^<]*(</div>)',
        lambda m: m.group(1) + stats["ent_sub"] + m.group(2), "statEntSub",
    )
    updated = _regex_replace_one(
        updated, r"data-tip=\"\d+ of SiftMed's \d+ tracked accounts",
        lambda m: f"data-tip=\"{stats['flagged_n']} of SiftMed's {stats['total_n']} tracked accounts",
        "flagged-accounts tooltip lead numbers",
    )
    new_rows_block = "var ROWS = [\n" + rows_js + "\n  ];"
    updated = _regex_replace_one(
        updated, r"var ROWS = \[.*?\];",
        lambda m: new_rows_block, "ROWS block", flags=re.DOTALL,
    )

    return check_alerts.patch_static_resource_body(my_domain, token, check_alerts.STATIC_RESOURCE_ID, updated)


def finalize(overrides_path=None, push_sf=False):
    with open(LIVE_DATA_PATH) as fh:
        data = json.load(fh)
    accounts = data["accounts"]
    today = generate.parse(data["asOf"])

    overrides = {}
    if overrides_path and os.path.exists(overrides_path):
        with open(overrides_path) as fh:
            overrides = json.load(fh)
    accounts = apply_overrides(accounts, overrides)

    rows = generate.compute_rows(accounts, today)
    stats = generate.compute_summary_stats(rows, today)
    rows_js = generate.render_rows_js(rows)

    fragment = {"asof": stats["asof"], "stats": stats, "rowsJs": rows_js}
    with open(FRAGMENT_PATH, "w") as fh:
        json.dump(fragment, fh, indent=2)
    print(f"Wrote {FRAGMENT_PATH}: {stats['flagged_n']} of {stats['total_n']} flagged")

    if push_sf:
        status = push_main_table_live(rows_js, stats)
        print(f"Pushed main table live: HTTP {status}")


def main():
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("fetch")
    finalize_parser = sub.add_parser("finalize")
    finalize_parser.add_argument("--overrides", default=None)
    finalize_parser.add_argument("--push-sf", action="store_true")
    args = parser.parse_args()

    if args.command == "fetch":
        fetch()
    elif args.command == "finalize":
        finalize(overrides_path=args.overrides, push_sf=args.push_sf)


if __name__ == "__main__":
    main()
