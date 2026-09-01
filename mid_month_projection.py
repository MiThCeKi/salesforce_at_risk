"""
mid_month_projection.py

15th of every month: a standalone "who's projected to go over" report,
separate from check_alerts.py's ongoing high/low usage alerts.

Projects each account's real calendar-month-to-date usage (summed straight
from the daily Usage_data__c records via check_alerts.fetch_month_to_date_pages
- NOT Pages_Last_30__c, which is a continuously rolling trailing-30-day total
with no monthly reset, verified live 2026-09-01) forward to a full-month
total by scaling by (days_in_month / days_elapsed_so_far), then flags anyone
projected to land over 100% of their prorated monthly cap.

Deliberately run on the 15th only, not the 1st: by the 15th, roughly half
the month's real usage pace is in, so the projection is a meaningful
"reasonable pace toward the true total". On the 1st there's only ~1 day of
real data to scale by ~30, which is too little to extrapolate from - a
single unusually heavy or light upload day would dominate the projection.

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
from check_alerts import fetch_accounts, fetch_month_to_date_pages, get_access_token

OVERAGE_THRESHOLD = 100.0
OUTPUT_PATH = "overage_projection.json"


def project_full_month_pct(account, pages_so_far, today):
    """Scales real calendar-month-to-date pages up to a full-month total,
    against the same prorated monthly cap generate.compute_rows uses.
    Returns None if a usage % can't be computed at all (missing contract
    dates or a zero cap) - mirrors generate.compute_rows's "Unknown" case."""
    prorated_cap = generate.prorated_monthly_cap(account)
    if not prorated_cap:
        return None

    days_elapsed = max(today.day, 1)
    days_in_month = calendar.monthrange(today.year, today.month)[1]
    projected_pages = pages_so_far / days_elapsed * days_in_month
    return (projected_pages / prorated_cap) * 100


def main():
    # See check_alerts.py: SF_MY_DOMAIN disappeared from this environment's
    # config on 2026-09-01 - falling back to the known org domain.
    my_domain = os.environ.get("SF_MY_DOMAIN", "https://siftmed.my.salesforce.com").rstrip("/")
    consumer_key = os.environ["SF_CONSUMER_KEY"]
    consumer_secret = os.environ["SF_CONSUMER_SECRET"]
    today = datetime.date.today()

    token = get_access_token(my_domain, consumer_key, consumer_secret)
    accounts = fetch_accounts(my_domain, token)
    mtd_pages = fetch_month_to_date_pages(my_domain, token, today)

    over = []
    for a in accounts:
        pages_so_far = mtd_pages.get(a["Id"], 0)
        pct = project_full_month_pct(a, pages_so_far, today)
        if pct is not None and pct > OVERAGE_THRESHOLD:
            over.append({
                "id": a["Id"], "name": a["Name"], "owner": a["Owner"],
                "projectedPct": round(pct, 1), "pagesSoFar": pages_so_far, "acv": a["ACV"],
            })
    over.sort(key=lambda x: -x["projectedPct"])

    with open(OUTPUT_PATH, "w") as fh:
        json.dump({"asOf": today.isoformat(), "dayOfMonth": today.day, "accounts": over}, fh, indent=2)

    print(f"{len(over)} account(s) projected over {OVERAGE_THRESHOLD}% by month end")
    for o in over:
        print(" -", o)


if __name__ == "__main__":
    main()
