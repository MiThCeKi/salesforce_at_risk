"""
check_alerts.py

Mon/Wed/Fri usage-threshold alert check + mid-cycle projected-usage snapshot
for the At-Risk Accounts pipeline.

What it does, each run:
  1. Pulls live account data from Salesforce (same fields/methodology as
     generate.py) via the OAuth client-credentials flow (env vars
     SF_MY_DOMAIN, SF_CONSUMER_KEY, SF_CONSUMER_SECRET).
  2. Computes each account's usage % (generate.compute_rows's formula) and
     its own billing-cycle position (day-of-month anchored to
     Active_Contract_Start_Date__c, via generate.cycle_position).
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

Alert rules (agreed 2026-09-01):
  - "High" = projected usage % > 115. "Low" = projected usage % < 25.
    Note: given the accepted data-approximation (see generate.py docstring
    changes), "projected" here is numerically the same trailing-30-day-pace
    usage % already shown elsewhere on the dashboard - there is no finer
    data available to compute a truer per-cycle projection.
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
Writes: alert_state.json, pending_alerts.json, projected_snapshot.json
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


def main():
    my_domain = os.environ["SF_MY_DOMAIN"].rstrip("/")
    consumer_key = os.environ["SF_CONSUMER_KEY"]
    consumer_secret = os.environ["SF_CONSUMER_SECRET"]
    today = datetime.date.today()

    token = get_access_token(my_domain, consumer_key, consumer_secret)
    accounts = fetch_accounts(my_domain, token)
    accounts_by_id = {a["Id"]: a for a in accounts}
    rows = generate.compute_rows(accounts, today)

    state = load_json(STATE_PATH, {})
    pending = []
    projected = []

    for r in rows:
        acct_id = r["Id"]
        pct = r["UsagePct"]

        days_into, days_remaining, cycle_len = generate.cycle_position(
            accounts_by_id[acct_id]["Start"], today
        )
        projected.append({
            "name": r["Name"], "id": acct_id, "tier": r["Tier"],
            "pct": pct, "acv": r["ACV"],
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
    with open(PROJECTED_PATH, "w") as fh:
        json.dump({"asOf": today.strftime("%b %d, %Y").upper(), "rows": projected}, fh, indent=2)

    print(f"{len(pending)} alert(s) pending, {len(projected)} accounts in projected snapshot")
    for p in pending:
        print(" -", p)


if __name__ == "__main__":
    main()
