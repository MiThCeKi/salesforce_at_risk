"""
check_alerts.py

Mon/Wed/Fri usage-threshold alert check + mid-cycle projected-usage snapshot
for the At-Risk Accounts pipeline.

What it does, each run:
  1. Pulls live account data from Salesforce (same fields/methodology as
     generate.py) via the OAuth client-credentials flow (env vars
     SF_MY_DOMAIN, SF_CONSUMER_KEY, SF_CONSUMER_SECRET).
  2. Computes each account's usage % the same way generate.compute_rows does,
     for the high/low alert check below - this is Pages_Last_30__c (a true
     rolling trailing-30-day total, verified live against the raw
     Usage_data__c records) against the prorated monthly cap. It needs no
     calendar-cycle awareness and is never noisy early in a month.
     Separately, for the Projected Usage table only, sums real page counts
     from the 1st of the current calendar month via fetch_month_to_date_pages
     (querying Usage_data__c directly, since Pages_Last_30__c itself never
     resets) and extrapolates to a full-month total using
     generate.cycle_position's day count.
  3. Compares against alert_state.json (persisted in this repo, committed
     after each run) using the hysteresis rules below, and writes
     pending_alerts.json describing exactly which emails need sending this
     run. This script does NOT send email itself — sending requires the
     Gmail OAuth session, which only the calling agent has. The agent
     should: run this script, read pending_alerts.json, send exactly those
     emails, then commit alert_state.json + projected_snapshot.json (and
     delete pending_alerts.json, or leave it - it's overwritten next run).
  4. Writes projected_snapshot.json, the mid-cycle projection table's data,
     which generate.py's daily regeneration reads and carries forward
     unchanged on the days this script doesn't run.
  5. Pushes that same Projected Usage data straight to the LIVE Static
     Resource itself (push_projected_section_live) - the daily push routine
     never clones this repo, so it can't pick up projected_snapshot.json;
     this script is the only thing that keeps the live page's Projected
     section current. It edits only that section (regex-replaces PROJ_ROWS
     and the projAsof date), leaving the main all-accounts table and
     everything else on the live page untouched.

Alert rules (agreed 2026-09-01, methodology corrected 2026-09-01):
  - "High" = usage % > 115. "Low" = usage % < 25. This is the rolling
    30-day Pages_Last_30__c-based UsagePct from generate.compute_rows - the
    same number shown in the dashboard's main table - not the calendar
    month-to-date projection used for the separate Projected Usage table
    below. It's deliberately the stable rolling figure so an alert can fire
    on any day of the month without the early-month noise a month-to-date
    extrapolation would have (confirmed live: projecting from 1 day of
    calendar-month data amplified one account to over 50,000%).
  - First time an account enters High: send an alert, mark state "high".
  - While state stays "high" (pct still > 115), no further emails until
    either (a) pct drops to <= 115 (state resets to "normal", clearing the
    reminder clock), or (b) 14+ days have passed since the last alert for
    this account, in which case send one reminder and reset the clock.
  - First time an account enters Low (pct < 25): send an alert, mark state
    "low". State stays "low" (even once back above 25%) until pct climbs
    above 30 - only then does it reset to "normal". While still "low", the
    same 14-day reminder rule as High applies.
  - Accounts with no computable pct (Unknown severity - missing contract
    dates or a zero cap) are skipped for alerting, but still appear in the
    projected snapshot with pct: null.

Usage: python3 check_alerts.py
Reads:  alert_state.json (if present; treated as empty otherwise)
Writes: alert_state.json, pending_alerts.json, projected_snapshot.json,
        and PATCHes the live Salesforce Static Resource's Projected section.
"""
import datetime
import json
import os
import urllib.error
import urllib.parse
import urllib.request

import generate

API_VERSION = "v62.0"
HIGH_THRESHOLD = 115.0
LOW_ALERT_THRESHOLD = 25.0
LOW_RESET_THRESHOLD = 30.0
REMINDER_DAYS = 14

STATE_PATH = "alert_state.json"
PENDING_PATH = "pending_alerts.json"
PROJECTED_PATH = "projected_snapshot.json"
STATIC_RESOURCE_ID = "081OL000000FhsfYAC"


def get_access_token(my_domain, consumer_key, consumer_secret):
    url = f"{my_domain}/services/oauth2/token"
    data = urllib.parse.urlencode({
        "grant_type": "client_credentials",
        "client_id": consumer_key,
        "client_secret": consumer_secret,
    }).encode("ascii")
    with urllib.request.urlopen(urllib.request.Request(url, data=data, method="POST")) as resp:
        return json.load(resp)["access_token"]


def soql(my_domain, token, query):
    records = []
    url = f"{my_domain}/services/data/{API_VERSION}/query?" + urllib.parse.urlencode({"q": query})
    while url:
        req = urllib.request.Request(url, headers={"Authorization": f"Bearer {token}"})
        with urllib.request.urlopen(req) as resp:
            result = json.load(resp)
        records.extend(result["records"])
        url = (my_domain + result["nextRecordsUrl"]) if not result["done"] else None
    return records


def fetch_month_to_date_pages(my_domain, token, today):
    """Real calendar-month-to-date page counts per account, summed straight
    from the raw daily Usage_data__c records (the ground truth Pages_Last_30__c
    itself is rolled up from) from the 1st of the current month through
    whatever's most recently landed. Verified live 2026-09-01: this is 0 on
    the 1st (no data posted yet for the new month) while the LAST_N_DAYS:30
    sum exactly matches Pages_Last_30__c - confirming Pages_Last_30__c is a
    continuously rolling window with no monthly reset, and this is the only
    correct source for a "how's this calendar month going" figure."""
    first_of_month = today.replace(day=1).isoformat()
    query = (
        "SELECT Related_Account__c, SUM(Number_of_Pages_Uploaded__c) total "
        f"FROM Usage_data__c WHERE Date__c >= {first_of_month} "
        "AND Related_Account__c != null GROUP BY Related_Account__c"
    )
    records = soql(my_domain, token, query)
    return {r["Related_Account__c"]: (r["total"] or 0) for r in records}


def fetch_accounts(my_domain, token):
    query = (
        "SELECT Id, Name, Owner.Name, Account_Tier__c, Annual_Contract_Value__c, "
        "PageCountCap__c, Active_Contract_Start_Date__c, Subscription_End_Date__c, "
        "Pages_Last_30__c, Hours_Last_30__c, Active_Users_Last_30__c "
        "FROM Account WHERE Stage__c = 'Customer' AND Annual_Contract_Value__c > 0 ORDER BY Name"
    )
    records = soql(my_domain, token, query)
    accounts = []
    for r in records:
        owner = r.get("Owner") or {}
        accounts.append({
            "Name": r["Name"],
            "Id": r["Id"],
            "Owner": owner.get("Name", ""),
            "Tier": r.get("Account_Tier__c"),
            "ACV": r.get("Annual_Contract_Value__c") or 0,
            "Cap": r.get("PageCountCap__c") or 0,
            "Start": r.get("Active_Contract_Start_Date__c"),
            "End": r.get("Subscription_End_Date__c"),
            "Pages": r.get("Pages_Last_30__c") or 0,
            "Hours": r.get("Hours_Last_30__c") or 0,
            "Users": r.get("Active_Users_Last_30__c") or 0,
        })
    return accounts


def load_json(path, default):
    if os.path.exists(path):
        with open(path) as fh:
            return json.load(fh)
    return default


def get_static_resource_body(my_domain, token, resource_id):
    url = f"{my_domain}/services/data/{API_VERSION}/sobjects/StaticResource/{resource_id}/Body"
    req = urllib.request.Request(url, headers={"Authorization": f"Bearer {token}"})
    with urllib.request.urlopen(req) as resp:
        return resp.read().decode("utf-8")


def patch_static_resource_body(my_domain, token, resource_id, html_text):
    import base64
    url = f"{my_domain}/services/data/{API_VERSION}/sobjects/StaticResource/{resource_id}"
    payload = json.dumps({"Body": base64.b64encode(html_text.encode("utf-8")).decode("ascii")}).encode("utf-8")
    req = urllib.request.Request(
        url, data=payload, method="PATCH",
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req) as resp:
        return resp.status


def push_projected_section_live(my_domain, token, asof, rows):
    """Surgically replaces ONLY the PROJ_ROWS array and the projAsof date on
    the CURRENT live Static Resource, leaving every other byte (including
    the main all-accounts table's data) untouched - the same "live page as
    its own template" approach the daily push routine uses, so this can run
    independently of it without either one clobbering the other's section."""
    import re as _re
    current = get_static_resource_body(my_domain, token, STATIC_RESOURCE_ID)

    rows_js = generate.render_projected_js(rows)
    new_block = "var PROJ_ROWS = [\n" + rows_js + "\n  ];"
    updated, n_rows = _re.subn(
        r"var PROJ_ROWS = \[.*?\];", new_block, current, count=1, flags=_re.DOTALL
    )
    if n_rows != 1:
        raise RuntimeError("Could not find PROJ_ROWS block on the live page - aborting live patch.")

    updated, n_date = _re.subn(
        r'(<span id="projAsof">)[^<]*(</span>)', rf"\g<1>{asof}\g<2>", updated, count=1
    )
    if n_date != 1:
        raise RuntimeError("Could not find projAsof span on the live page - aborting live patch.")

    return patch_static_resource_body(my_domain, token, STATIC_RESOURCE_ID, updated)


def main():
    # SF_MY_DOMAIN disappeared from this environment's config on 2026-09-01
    # (SF_CONSUMER_KEY/SECRET were still present) - falling back to the known
    # org domain so the Mon/Wed/Fri and 15th-of-month routines don't silently
    # fail. Not a secret (it's just the org's login domain), but the env var
    # should still be restored at the environment level for robustness.
    my_domain = os.environ.get("SF_MY_DOMAIN", "https://siftmed.my.salesforce.com").rstrip("/")
    consumer_key = os.environ["SF_CONSUMER_KEY"]
    consumer_secret = os.environ["SF_CONSUMER_SECRET"]
    today = datetime.date.today()

    token = get_access_token(my_domain, consumer_key, consumer_secret)
    accounts = fetch_accounts(my_domain, token)
    accounts_by_id = {a["Id"]: a for a in accounts}
    rows = generate.compute_rows(accounts, today)
    mtd_pages = fetch_month_to_date_pages(my_domain, token, today)
    days_into, days_remaining, cycle_len = generate.cycle_position(today)

    state = load_json(STATE_PATH, {})
    pending = []
    projected = []

    for r in rows:
        acct_id = r["Id"]
        pct = r["UsagePct"]

        prorated_cap = generate.prorated_monthly_cap(accounts_by_id[acct_id])
        pages_so_far = mtd_pages.get(acct_id, 0)
        if prorated_cap and days_into > 0:
            projected_pct = round((pages_so_far / days_into * cycle_len) / prorated_cap * 100, 1)
        else:
            projected_pct = None
        projected.append({
            "name": r["Name"], "id": acct_id, "tier": r["Tier"],
            "pct": projected_pct, "acv": r["ACV"],
            "daysIntoCycle": days_into, "daysRemaining": days_remaining, "cycleLen": cycle_len,
        })

        if pct is None:
            continue

        entry = state.get(acct_id, {"state": "normal", "since": None, "last_alert": None})
        cur_state = entry["state"]
        new_state = cur_state
        send = None

        if cur_state == "high":
            if pct <= HIGH_THRESHOLD:
                new_state = "normal"
            elif entry["last_alert"] is None or (today - generate.parse(entry["last_alert"])).days >= REMINDER_DAYS:
                send = "high_reminder"
        elif cur_state == "low":
            if pct > LOW_RESET_THRESHOLD:
                new_state = "normal"
            elif entry["last_alert"] is None or (today - generate.parse(entry["last_alert"])).days >= REMINDER_DAYS:
                send = "low_reminder"
        else:  # normal
            if pct > HIGH_THRESHOLD:
                new_state = "high"
                send = "high_new"
            elif pct < LOW_ALERT_THRESHOLD:
                new_state = "low"
                send = "low_new"

        if send:
            pending.append({
                "accountId": acct_id, "accountName": r["Name"], "owner": r["Owner"],
                "pct": pct, "type": send,
            })
            since = entry["since"] if new_state == cur_state else today.isoformat()
            entry = {"state": new_state, "since": since, "last_alert": today.isoformat()}
        elif new_state != cur_state:
            # Full reset back to normal - clear the reminder clock too, so a
            # future re-crossing starts a fresh "first time" alert.
            entry = {"state": "normal", "since": None, "last_alert": None}
        else:
            entry = {"state": cur_state, "since": entry["since"], "last_alert": entry["last_alert"]}

        state[acct_id] = entry

    with open(STATE_PATH, "w") as fh:
        json.dump(state, fh, indent=2, sort_keys=True)
    with open(PENDING_PATH, "w") as fh:
        json.dump(pending, fh, indent=2)
    projected_asof = today.strftime("%b %d, %Y").upper()
    with open(PROJECTED_PATH, "w") as fh:
        json.dump({"asOf": projected_asof, "rows": projected}, fh, indent=2)

    status = push_projected_section_live(my_domain, token, projected_asof, projected)
    print(f"Pushed Projected Usage section live: HTTP {status}")

    print(f"{len(pending)} alert(s) pending, {len(projected)} accounts in projected snapshot")
    for p in pending:
        print(" -", p)


if __name__ == "__main__":
    main()
