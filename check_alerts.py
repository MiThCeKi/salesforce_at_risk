"""
check_alerts.py

Mon/Wed/Fri refresh of the "Projected End of Month Usage" section on the
live At-Risk Accounts dashboard.

RETIRED 2026-09-09 (user request): this script used to ALSO run a
high/low rolling-usage email alert with hysteresis/reminder state
(alert_state.json, pending_alerts.json, decide_alert()). That email has
been fully replaced by mid_month_projection.py's mid-month (15th of the
month) overage report, which the user specifically wanted instead: a
single monthly check using the first half of the month's real pace to
project the second half, flagging only accounts projected over 150% of
their cap. See mid_month_projection.py's own docstring for that logic.
This script no longer sends any email or persists any alert state - it
only keeps the dashboard's Projected Usage tab current, which is a
separate, still-wanted concern from the email and was kept on its
existing Mon/Wed/Fri cadence so that tab doesn't go stale for three
weeks out of four.

What it does, each run:
  1. Pulls live account data from Salesforce (same fields/methodology as
     generate.py) via the OAuth client-credentials flow (env vars
     SF_MY_DOMAIN, SF_CONSUMER_KEY, SF_CONSUMER_SECRET).
  2. Sums real page counts from the 1st of the current calendar month via
     fetch_month_to_date_pages (querying Usage_data__c directly, since
     Pages_Last_30__c is a continuously rolling trailing-30-day total with
     no monthly reset - verified live 2026-09-01) and extrapolates each
     account to a full-month total using generate.cycle_position's day
     count, against its prorated monthly cap.
  3. Writes projected_snapshot.json, the mid-cycle projection table's data,
     which generate.py's daily regeneration reads and carries forward
     unchanged on the days this script doesn't run.
  4. Pushes that same Projected Usage data straight to the LIVE Static
     Resource itself (push_projected_section_live) - the daily push routine
     never clones this repo, so it can't pick up projected_snapshot.json;
     this script is the only thing that keeps the live page's Projected
     section current. It edits only that section (regex-replaces PROJ_ROWS
     and the projAsof date), leaving the main all-accounts table and
     everything else on the live page untouched.

Usage: python3 check_alerts.py
Reads:  nothing persisted
Writes: projected_snapshot.json, and PATCHes the live Salesforce Static
        Resource's Projected section.
"""
import datetime
import json
import os
import urllib.error
import urllib.parse
import urllib.request

import generate

API_VERSION = "v62.0"

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


def fetch_last_30d_case_hours(my_domain, token, account_ids):
    """{account_id: (hours_sum, cases_sum)} - the source for Avg Time/Case
    (added 2026-09-11, user request). Account has no Cases_Last_30__c
    rollup the way it does for Pages/Hours, so this sums Usage_data__c's
    own Total_Time_spent_in_App_hr__c and Number_of_Cases_Created__c
    directly over the trailing 30 days (Date__c = LAST_N_DAYS:30) - the
    only place a per-account case count exists at all. Both sums come
    from the same query/window so their ratio is always internally
    consistent, even though checked live 2026-09-11 that this LAST_N_DAYS:30
    sum does NOT exactly reproduce Account.Hours_Last_30__c or
    Pages_Last_30__c (consistently a few percent lower across sampled
    accounts - AssessMed: 377.89 summed vs 394.09 on the Account rollup;
    those rollups evidently aggregate over a slightly different
    window/source than a literal SOQL LAST_N_DAYS:30 sum of this object).
    That's not a correctness problem for this ratio, which only needs its
    own numerator and denominator to agree with each other, not to match
    a different field's rollup. account_ids inlined directly - safe at
    this org's ~74 tracked-account count (unlike Contact ids elsewhere in
    this codebase, which hit HTTP 431 at ~880 - see activity_linking.py).

    Excludes Usage_data__c rows with zero Total_Time_spent_in_App_hr__c
    (added 2026-09-11, user request: a case created but never worked on
    shouldn't count toward the average - it isn't real "time per case",
    it's a case sitting untouched). Usage_data__c is a daily per-contact
    row, not per-case, so there's no way to see whether a SPECIFIC case
    got zero time; the closest available proxy is the day it was
    created - if that whole day logged zero app time, whatever cases it
    lists as created are dropped from the case count entirely (not just
    zeroed out) rather than dragging the average down for work that
    provably didn't happen. This also means those excluded rows can never
    contribute to hours_sum either (a zero-hours row adds nothing to a
    sum regardless), so the filter only ever changes cases_sum, never
    hours_sum."""
    if not account_ids:
        return {}
    ids_list = "','".join(account_ids)
    query = (
        "SELECT Related_Account__c, SUM(Total_Time_spent_in_App_hr__c) hrsum, "
        "SUM(Number_of_Cases_Created__c) casesum FROM Usage_data__c "
        f"WHERE Date__c = LAST_N_DAYS:30 AND Related_Account__c IN ('{ids_list}') "
        "AND Total_Time_spent_in_App_hr__c > 0 "
        "GROUP BY Related_Account__c"
    )
    records = soql(my_domain, token, query)
    return {r["Related_Account__c"]: (r["hrsum"] or 0, r["casesum"] or 0) for r in records}


def avg_hours_per_case(hours_sum, cases_sum):
    """Pure: None when there's no case to divide by - either no usage data
    at all in the window, or real hours logged with zero NEW cases created
    that period (checked live 2026-09-11: several tracked accounts have
    hours > 0 but 0 cases created) - both are real "can't compute this"
    states, not a bug to paper over with a 0."""
    if not cases_sum:
        return None
    return hours_sum / cases_sum


def fetch_accounts(my_domain, token):
    """Same account universe as generate.py's accounts list: no Stage__c
    filter (deliberately dropped 2026-09-02 - see generate.py's module
    docstring) - a non-zero ACV, a non-zero page cap, both contract dates
    on file, AND a non-null Account_Tier__c (added 2026-09-10, user
    request: an account with no Tier segment assigned shouldn't be tracked
    as though it were - live-checked 2026-09-10 that exactly one currently-
    tracked account, Dr. Yaacov Markus, has a null Tier and is the one this
    drops) - OR its Id is in generate.MANUAL_INCLUDE_IDS (also added
    2026-09-10, user request: a standing per-account override the user
    grows by naming an account to always include, regardless of whether it
    meets the criteria above - see generate.py's own docstring for the
    full rationale and the rule to keep this in sync with both live
    Routines' prompts). Kept identical to generate.py's criteria on
    purpose so the Projected End of Month Usage table tracks the exact
    same accounts as the main Expected Monthly table; do not reintroduce a
    Stage__c filter here without also changing generate.py."""
    criteria = (
        "(Annual_Contract_Value__c > 0 AND PageCountCap__c > 0 "
        "AND Active_Contract_Start_Date__c != null AND Subscription_End_Date__c != null "
        "AND Account_Tier__c != null)"
    )
    if generate.MANUAL_INCLUDE_IDS:
        manual_ids = "','".join(generate.MANUAL_INCLUDE_IDS)
        criteria += f" OR Id IN ('{manual_ids}')"
    query = (
        "SELECT Id, Name, Owner.Name, Stage__c, Account_Tier__c, Annual_Contract_Value__c, "
        "PageCountCap__c, Active_Contract_Start_Date__c, Subscription_End_Date__c, "
        "Pages_Last_30__c, Hours_Last_30__c, Active_Users_Last_30__c, Health_Score__c "
        f"FROM Account WHERE {criteria} "
        "ORDER BY Name"
    )
    records = soql(my_domain, token, query)
    case_hours = fetch_last_30d_case_hours(my_domain, token, [r["Id"] for r in records])
    accounts = []
    for r in records:
        owner = r.get("Owner") or {}
        hours_sum, cases_sum = case_hours.get(r["Id"], (0, 0))
        accounts.append({
            "Name": r["Name"],
            "Id": r["Id"],
            "Owner": owner.get("Name", ""),
            "Stage": r.get("Stage__c"),
            "Tier": r.get("Account_Tier__c"),
            "ACV": r.get("Annual_Contract_Value__c") or 0,
            "Cap": r.get("PageCountCap__c") or 0,
            "Start": r.get("Active_Contract_Start_Date__c"),
            "End": r.get("Subscription_End_Date__c"),
            "Pages": r.get("Pages_Last_30__c") or 0,
            "Hours": r.get("Hours_Last_30__c") or 0,
            "Users": r.get("Active_Users_Last_30__c") or 0,
            "HealthScore": r.get("Health_Score__c"),
            "AvgHoursPerCase": avg_hours_per_case(hours_sum, cases_sum),
        })
    return accounts


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


def build_projected_rows(rows, accounts_by_id, mtd_pages, today):
    """Pure computation of the Projected Usage table's rows: for every
    account row (as produced by generate.compute_rows), extrapolates its
    calendar-month-to-date pages to a full-month total against its prorated
    cap. Pulled out of main() so this can be unit tested without mocking
    Salesforce - the extrapolation math itself is exactly
    mid_month_projection.project_full_month_pct, just computed for every
    account on every run rather than only on the 15th."""
    days_into, days_remaining, cycle_len = generate.cycle_position(today)
    projected = []
    for r in rows:
        acct_id = r["Id"]
        prorated_cap = generate.prorated_monthly_cap(accounts_by_id[acct_id])
        pages_so_far = mtd_pages.get(acct_id, 0)
        if prorated_cap and days_into > 0:
            projected_pct = round((pages_so_far / days_into * cycle_len) / prorated_cap * 100, 1)
        else:
            projected_pct = None
        stage = accounts_by_id[acct_id].get("Stage")
        stage_label = "{} ({})".format(stage, r["Tier"]) if stage == "Customer" and r["Tier"] else stage
        projected.append({
            "name": r["Name"], "id": acct_id, "tier": r["Tier"],
            "stage": stage, "stageLabel": stage_label,
            "pct": projected_pct, "acv": r["ACV"],
            "daysIntoCycle": days_into, "daysRemaining": days_remaining, "cycleLen": cycle_len,
        })
    return projected


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

    projected = build_projected_rows(rows, accounts_by_id, mtd_pages, today)

    projected_asof = today.strftime("%b %d, %Y").upper()
    with open(PROJECTED_PATH, "w") as fh:
        json.dump({"asOf": projected_asof, "rows": projected}, fh, indent=2)

    status = push_projected_section_live(my_domain, token, projected_asof, projected)
    print(f"Pushed Projected Usage section live: HTTP {status}")
    print(f"{len(projected)} accounts in projected snapshot")


if __name__ == "__main__":
    main()
