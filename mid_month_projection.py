"""
mid_month_projection.py

15th of every month: a standalone "who's projected to go over" report,
separate from check_alerts.py's ongoing high/low usage alerts.

Usage resets on a shared monthly cycle rather than being a rolling
trailing-30-day window (corrected 2026-09-01), so partway through a cycle
the raw current tally understates what a full month's pace would be. This
report corrects for that: it scales each account's usage-so-far by
(days_in_month / days_elapsed_so_far) to project a full-month total, then
flags anyone projected to land over 100% of their prorated monthly cap.

Deliberately run on the 15th only, not the 1st: by the 15th, roughly half
the month's real usage pace is in, so the projection is a meaningful
"reasonable pace toward the true total". On the 1st there's only ~1 day of
data to scale by ~30, which amplifies a single unusually heavy or light
upload day into nonsense (confirmed live: 39/51 accounts flagged, one over
50,000% projected) - not worth reporting, so that run was dropped rather
than patched.

Unlike check_alerts.py, this report carries no hysteresis/reminder state -
it's a fresh status snapshot every run, not a "new crossing" alert system,
so every account currently projected over 100% is listed every time this
runs, even if it was also listed last time.

Usage: python3 mid_month_projection.py
Reads: nothing persisted
Writes: overage_projection.json (the caller/agent reads it to compose and
        send the report email)
"""
import calendar
import datetime
import json
import os

import generate
from check_alerts import fetch_accounts, get_access_token

OVERAGE_THRESHOLD = 100.0
OUTPUT_PATH = "overage_projection.json"


def project_full_month_pct(account, today):
    """Scales usage-so-far this calendar cycle up to a full-month total,
    against the same prorated monthly cap generate.compute_rows uses.
    Returns None if a usage % can't be computed at all (missing contract
    dates or a zero cap) - mirrors generate.compute_rows's "Unknown" case."""
    start = generate.parse(account["Start"])
    end = generate.parse(account["End"])
    months = (end - start).days / 30.44
    if months <= 0 or account["Cap"] <= 0:
        return None
    prorated_cap = account["Cap"] / months
    if prorated_cap <= 0:
        return None

    days_elapsed = max(today.day, 1)
    days_in_month = calendar.monthrange(today.year, today.month)[1]
    projected_pages = account["Pages"] / days_elapsed * days_in_month
    return (projected_pages / prorated_cap) * 100


def main():
    my_domain = os.environ["SF_MY_DOMAIN"].rstrip("/")
    consumer_key = os.environ["SF_CONSUMER_KEY"]
    consumer_secret = os.environ["SF_CONSUMER_SECRET"]
    today = datetime.date.today()

    token = get_access_token(my_domain, consumer_key, consumer_secret)
    accounts = fetch_accounts(my_domain, token)

    over = []
    for a in accounts:
        pct = project_full_month_pct(a, today)
        if pct is not None and pct > OVERAGE_THRESHOLD:
            over.append({
                "id": a["Id"], "name": a["Name"], "owner": a["Owner"],
                "projectedPct": round(pct, 1), "pagesSoFar": a["Pages"], "acv": a["ACV"],
            })
    over.sort(key=lambda x: -x["projectedPct"])

    with open(OUTPUT_PATH, "w") as fh:
        json.dump({"asOf": today.isoformat(), "dayOfMonth": today.day, "accounts": over}, fh, indent=2)

    print(f"{len(over)} account(s) projected over {OVERAGE_THRESHOLD}% by month end")
    for o in over:
        print(" -", o)


if __name__ == "__main__":
    main()
