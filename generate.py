"""
Fills /home/claude/sf-refresh/template.html with freshly computed at-risk data
and writes out the final, ready-to-deploy HTML.

This is the "recompute from Salesforce directly" pipeline step. The `accounts`
list below was pulled live via SOQL against Salesforce on 2026-08-31 (the same
query compute.py/generate.py's methodology has always used:
Account.Stage__c = "Customer" AND Annual_Contract_Value__c > 0, selecting
Name, Owner.Name, Account_Tier__c, Annual_Contract_Value__c,
Active_Contract_Start_Date__c, Subscription_End_Date__c, PageCountCap__c,
Pages_Last_30__c, Hours_Last_30__c, Active_Users_Last_30__c). In the
scheduled job, this list gets replaced by that same live SOQL query result
each run, and TODAY becomes datetime.date.today() (already the case here).

Usage: python3 generate.py
Output: /home/claude/sf-refresh/AtRiskAccountsSnapshot_new.html
"""
import datetime
import json
import re

TODAY = datetime.date.today()

accounts = [
{"Name":"Alex Luczack MD","Id":"001OL00000C5CzSYAV","LastLogin":"2026-08-27","Owner":"Carla Chaytor","Tier":"Micro","ACV":4000,"Start":"2026-07-01","End":"2027-07-01","Cap":55000,"Pages":2686,"Hours":21.1402,"Users":1},
{"Name":"ArthroBiologix Inc.","Id":"001OL00000Ckjw6YAB","LastLogin":"2026-08-19","Owner":"Carla Chaytor","Tier":"Micro","ACV":10800,"Start":"2026-04-01","End":"2027-03-31","Cap":15000,"Pages":22218,"Hours":14.193,"Users":2},
{"Name":"AssessMed Inc.","Id":"0015f00000IQRGHAA5","LastLogin":"2026-08-31","Owner":"Travis Bailey","Tier":"Enterprise","ACV":124000,"Start":"2026-06-01","End":"2027-06-30","Cap":3100000,"Pages":230030,"Hours":354.5592,"Users":27},
{"Name":"Aua Consulting LLC","Id":"001OL00000kV72oYAC","LastLogin":"2026-08-20","Owner":"Travis Bailey","Tier":"Micro","ACV":14000,"Start":"2026-06-08","End":"2027-06-14","Cap":80000,"Pages":12377,"Hours":5.6395,"Users":1},
{"Name":"Boucher Medical Professional Corp.","Id":"001OL0000087uk3YAA","LastLogin":"2026-08-31","Owner":"Carla Chaytor","Tier":"Micro","ACV":11746,"Start":"2025-03-21","End":"2026-08-31","Cap":275000,"Pages":20627,"Hours":95.3605,"Users":3},
{"Name":"Breedon Mor LLP","Id":"001I9000005T4bZIAS","LastLogin":"2026-08-31","Owner":"Carla Chaytor","Tier":"SMB","ACV":15000,"Start":"2026-02-12","End":"2027-02-12","Cap":150000,"Pages":6154,"Hours":19.4049,"Users":6},
{"Name":"Canadian Health Solutions Inc","Id":"0015f00000IPHxuAAH","LastLogin":"2026-08-31","Owner":"Carla Chaytor","Tier":"SMB","ACV":20000,"Start":"2026-04-11","End":"2027-04-10","Cap":200000,"Pages":23530,"Hours":9.081,"Users":26},
{"Name":"Cayuga Mutual","Id":"001OL00000VTlWPYA1","LastLogin":"2025-11-19","Owner":"Travis Bailey","Tier":"SMB","ACV":600,"Start":"2025-10-20","End":"2026-10-19","Cap":5000,"Pages":0,"Hours":0,"Users":0},
{"Name":"Chris Small Professional Medical Corporation","Id":"001OL000008ibX8YAI","LastLogin":"2026-08-15","Owner":"Carla Chaytor","Tier":"Micro","ACV":4800,"Start":"2026-03-21","End":"2027-03-21","Cap":20000,"Pages":24,"Hours":0.8222,"Users":1},
{"Name":"Crannie Law","Id":"001I9000005T4dLIAS","LastLogin":"2026-08-31","Owner":"Carla Chaytor","Tier":"SMB","ACV":11896,"Start":"2026-05-11","End":"2027-05-11","Cap":125000,"Pages":2996,"Hours":48.3565,"Users":4},
{"Name":"Curtis Hlushak","Id":"001OL00000C4p0PYAR","LastLogin":"2026-08-29","Owner":"Carla Chaytor","Tier":"Micro","ACV":4500,"Start":"2026-02-23","End":"2027-02-23","Cap":30000,"Pages":2860,"Hours":6.34,"Users":1},
{"Name":"Daugherty & Associates, LLC","Id":"001OL00000SYxvHYAT","LastLogin":"2026-08-13","Owner":"Carla Chaytor","Tier":"Micro","ACV":8400,"Start":"2026-07-30","End":"2027-07-29","Cap":60000,"Pages":1165,"Hours":70.1106,"Users":1},
{"Name":"Girones Lawyers","Id":"001I9000005T4a9IAC","LastLogin":"2026-06-15","Owner":"Carla Chaytor","Tier":"SMB","ACV":11188,"Start":"2026-05-12","End":"2027-05-12","Cap":100000,"Pages":0,"Hours":0,"Users":5},
{"Name":"Halbrecht Orthopedics","Id":"001OL00000TX14jYAD","LastLogin":"2026-01-21","Owner":"Peter Moyse","Tier":"Micro","ACV":650,"Start":"2025-11-23","End":"2026-11-23","Cap":5000,"Pages":0,"Hours":0,"Users":1},
{"Name":"Hands-On Orthopedics","Id":"001OL00000dg8ynYAA","LastLogin":"2026-08-31","Owner":"Carla Chaytor","Tier":"Micro","ACV":14700,"Start":"2025-12-06","End":"2026-12-05","Cap":70000,"Pages":3335,"Hours":7.2089,"Users":4},
{"Name":"Hooper Law","Id":"001I9000005T4bNIAS","LastLogin":"2026-08-31","Owner":"Carla Chaytor","Tier":"SMB","ACV":6000,"Start":"2026-08-01","End":"2027-07-31","Cap":50000,"Pages":9018,"Hours":8.0293,"Users":10},
{"Name":"IMED Services","Id":"001OL00000Io5WoYAJ","LastLogin":"2026-08-31","Owner":"Carla Chaytor","Tier":"SMB","ACV":12000,"Start":"2026-05-21","End":"2027-05-20","Cap":60000,"Pages":4350,"Hours":64.6663,"Users":5},
{"Name":"iMPROve Health","Id":"001OL00000Ncj26YAB","LastLogin":"2026-08-31","Owner":"Travis Bailey","Tier":"SMB","ACV":36960,"Start":"2025-09-15","End":"2026-09-30","Cap":336000,"Pages":591,"Hours":26.4569,"Users":7},
{"Name":"Integral Consulting Services Inc.","Id":"001I9000007cllGIAQ","LastLogin":"2026-08-31","Owner":"Travis Bailey","Tier":"SMB","ACV":121500,"Start":"2026-06-30","End":"2027-06-30","Cap":2000000,"Pages":90091,"Hours":87.4752,"Users":3},
{"Name":"Integrity Legal Nurse Consulting","Id":"001OL00000UmhEIYAZ","LastLogin":"2026-05-01","Owner":"Travis Bailey","Tier":"SMB","ACV":9000,"Start":"2025-09-22","End":"2026-09-21","Cap":60000,"Pages":0,"Hours":0,"Users":16},
{"Name":"Integrity Medical Evaluations","Id":"001OL00000AU6wgYAD","LastLogin":"2026-08-28","Owner":"Travis Bailey","Tier":"Enterprise","ACV":158400,"Start":"2026-06-25","End":"2027-08-31","Cap":1440000,"Pages":7684,"Hours":5.1092,"Users":1},
{"Name":"Jamie Irvine MD","Id":"001OL00000D0AqjYAF","LastLogin":"2026-08-12","Owner":"Carla Chaytor","Tier":"Micro","ACV":9576,"Start":"2026-02-18","End":"2027-02-18","Cap":60000,"Pages":0,"Hours":0.31,"Users":1},
{"Name":"Janet Patterson MD","Id":"001OL00000Czp9PYAR","LastLogin":"2026-08-31","Owner":"Carla Chaytor","Tier":"Micro","ACV":27700,"Start":"2026-06-30","End":"2027-06-30","Cap":400000,"Pages":28416,"Hours":44.669,"Users":6},
{"Name":"JHU Consulting","Id":"001OL00000SYhk0YAD","LastLogin":"2026-08-26","Owner":"Carla Chaytor","Tier":"Micro","ACV":6600,"Start":"2026-01-30","End":"2027-01-30","Cap":30000,"Pages":2324,"Hours":5.7275,"Users":2},
{"Name":"JS Held - BioMechanics Group","Id":"001OL000006SaZlYAK","LastLogin":"2026-08-31","Owner":"Carla Chaytor","Tier":"SMB","ACV":23061.75,"Start":"2026-01-08","End":"2027-01-08","Cap":125000,"Pages":2233,"Hours":15.5071,"Users":7},
{"Name":"Kenney Shelton Liptak Nowak - KSLN law","Id":"001OL00000Q4KAsYAN","LastLogin":"2026-08-31","Owner":"Carla Chaytor","Tier":"SMB","ACV":41000,"Start":"2026-06-23","End":"2027-06-23","Cap":300000,"Pages":17204,"Hours":43.5486,"Users":21},
{"Name":"Kevin Smith MD","Id":"001OL00000D0B7IYAV","LastLogin":"2026-08-31","Owner":"Carla Chaytor","Tier":"Micro","ACV":9000,"Start":"2026-06-30","End":"2027-06-30","Cap":150000,"Pages":8429,"Hours":21.6467,"Users":5},
{"Name":"KLE Nurse Consultants","Id":"001OL00000XOkQ8YAL","LastLogin":"2026-08-29","Owner":"Carla Chaytor","Tier":"Micro","ACV":9000,"Start":"2025-09-15","End":"2026-09-14","Cap":60000,"Pages":2934,"Hours":2.0496,"Users":3},
{"Name":"LCP Pro","Id":"001OL00000i2nBOYAY","LastLogin":"2026-08-31","Owner":"Travis Bailey","Tier":"SMB","ACV":100000,"Start":"2026-05-22","End":"2027-05-21","Cap":950000,"Pages":166138,"Hours":360.3928,"Users":46},
{"Name":"Life Care Planning Solutions LLC","Id":"001OL00000NseOJYAZ","LastLogin":"2026-08-31","Owner":"Travis Bailey","Tier":"SMB","ACV":8000,"Start":"2026-06-23","End":"2027-06-23","Cap":300000,"Pages":2194,"Hours":28.628,"Users":8},
{"Name":"Medical Vocational Planning (MVP)","Id":"001OL00000A5GPoYAN","LastLogin":"2026-08-31","Owner":"Travis Bailey","Tier":"SMB","ACV":115200,"Start":"2025-11-01","End":"2027-12-01","Cap":1440000,"Pages":12301,"Hours":47.3866,"Users":6},
{"Name":"Medivest","Id":"001OL00000eL401YAC","LastLogin":"2026-08-31","Owner":"Travis Bailey","Tier":"SMB","ACV":100000,"Start":"2026-04-01","End":"2027-03-31","Cap":1000000,"Pages":140422,"Hours":100.2814,"Users":12},
{"Name":"Mohamed Khaled MD","Id":"001OL00000D0B7XYAV","LastLogin":"2026-08-27","Owner":"Carla Chaytor","Tier":"Micro","ACV":19349,"Start":"2025-09-03","End":"2026-09-02","Cap":192000,"Pages":149,"Hours":0.1033,"Users":1},
{"Name":"North Toronto Surgical","Id":"001OL00000SE68iYAD","LastLogin":"2026-07-07","Owner":"Carla Chaytor","Tier":"Micro","ACV":1920,"Start":"2026-06-03","End":"2027-06-03","Cap":24000,"Pages":0,"Hours":0,"Users":1},
{"Name":"Northeast Life Care Planning","Id":"001OL00000TANqiYAH","LastLogin":"2026-08-27","Owner":"Carla Chaytor","Tier":"Micro","ACV":9250,"Start":"2026-07-09","End":"2027-07-08","Cap":60000,"Pages":1326,"Hours":7.4339,"Users":1},
{"Name":"NuHaven Health","Id":"001OL00000VI1ofYAD","LastLogin":"2026-08-28","Owner":"Carla Chaytor","Tier":"SMB","ACV":8100,"Start":"2025-09-22","End":"2026-09-21","Cap":90000,"Pages":2362,"Hours":10.0169,"Users":1},
{"Name":"Orvosi Medical Management","Id":"001OL00000BbZGdYAN","LastLogin":"2026-08-31","Owner":"Travis Bailey","Tier":"SMB","ACV":96000,"Start":"2026-01-09","End":"2027-01-08","Cap":1600000,"Pages":7398,"Hours":10.1603,"Users":7},
{"Name":"Peel Mutual Insurance Company","Id":"001I900000362wRIAQ","LastLogin":"2026-08-31","Owner":"Carla Chaytor","Tier":"SMB","ACV":5760,"Start":"2025-08-25","End":"2026-08-24","Cap":38400,"Pages":5469,"Hours":8.0887,"Users":10},
{"Name":"Physician Life Care Planning (PLCP)","Id":"001OL00000KcO97YAF","LastLogin":"2026-08-31","Owner":"Travis Bailey","Tier":"SMB","ACV":845000,"Start":"2025-11-07","End":"2027-11-07","Cap":6500000,"Pages":149309,"Hours":2246.9853,"Users":100},
{"Name":"Physiohealth Inc.","Id":"001I9000004mawoIAA","LastLogin":"2026-08-31","Owner":"Carla Chaytor","Tier":"Micro","ACV":1500,"Start":"2026-05-15","End":"2027-05-15","Cap":120000,"Pages":16346,"Hours":14.7165,"Users":1},
{"Name":"Portage Mutual Insurance","Id":"001OL00000SGW3tYAH","LastLogin":"2026-08-27","Owner":"Travis Bailey","Tier":"SMB","ACV":10200,"Start":"2026-01-07","End":"2027-01-07","Cap":60000,"Pages":3137,"Hours":9.6559,"Users":11},
{"Name":"Priddle Law Group","Id":"001I9000005T4fNIAS","LastLogin":"2026-03-06","Owner":"Matt Baldwin","Tier":"SMB","ACV":600,"Start":"2025-12-01","End":"2026-12-01","Cap":5000,"Pages":0,"Hours":0,"Users":0},
{"Name":"Rehab First Inc.","Id":"001OL00000Kf2yUYAR","LastLogin":"2026-08-31","Owner":"Carla Chaytor","Tier":"SMB","ACV":18000,"Start":"2025-11-03","End":"2026-11-02","Cap":180000,"Pages":9620,"Hours":6.4782,"Users":6},
{"Name":"Roebothan McKay Marshall (RMM)","Id":"001I9000003c6huIAA","LastLogin":"2026-08-31","Owner":"Carla Chaytor","Tier":"SMB","ACV":36000,"Start":"2026-06-06","End":"2027-06-06","Cap":480000,"Pages":9619,"Hours":53.8765,"Users":37},
{"Name":"The Ivera Group","Id":"001OL00000gAMVJYA4","LastLogin":"2026-08-31","Owner":"Carla Chaytor","Tier":"SMB","ACV":80000,"Start":"2026-03-23","End":"2027-03-22","Cap":800000,"Pages":5606,"Hours":4.9683,"Users":3},
{"Name":"Tri-Star Health Management Group Inc.","Id":"001I9000007CYHEIA4","LastLogin":"2026-08-31","Owner":"Travis Bailey","Tier":"SMB","ACV":19250,"Start":"2026-01-20","End":"2027-01-20","Cap":275000,"Pages":12059,"Hours":113.9459,"Users":15},
{"Name":"Trillium Mutual Insurance Company","Id":"001OL00000Q4fgjYAB","LastLogin":"2026-08-26","Owner":"Carla Chaytor","Tier":"SMB","ACV":7000,"Start":"2026-01-01","End":"2027-01-01","Cap":50000,"Pages":2423,"Hours":2.6652,"Users":2},
{"Name":"TrueLine Medical Legal Consulting","Id":"001OL00000UBUYBYA5","LastLogin":"2026-06-12","Owner":"Peter Moyse","Tier":"SMB","ACV":12000,"Start":"2026-06-01","End":"2027-05-31","Cap":120000,"Pages":0,"Hours":0,"Users":1},
{"Name":"Vocational Alternatives","Id":"001OL00000byRmQYAU","LastLogin":"2026-08-18","Owner":"Carla Chaytor","Tier":"SMB","ACV":9900,"Start":"2026-03-10","End":"2027-03-09","Cap":90000,"Pages":1194,"Hours":0.9789,"Users":3},
{"Name":"Walnut Orchard Psychology Services","Id":"001OL00000izh1xYAA","LastLogin":"2026-08-31","Owner":"Carla Chaytor","Tier":"SMB","ACV":12500,"Start":"2026-04-09","End":"2027-04-08","Cap":120000,"Pages":7185,"Hours":16.9796,"Users":2},
{"Name":"Zurich North America","Id":"001I9000002tqUTIAY","LastLogin":"2026-08-31","Owner":"Travis Bailey","Tier":"Enterprise","ACV":88200,"Start":"2026-04-01","End":"2028-03-31","Cap":900000,"Pages":13673,"Hours":16.2238,"Users":47},
]

SEVERITY_CODE = {"Critical": 0, "High": 1, "Watch": 2, "Healthy": 3, "Unknown": 4}


def parse(d):
    return datetime.date(*[int(x) for x in d.split("-")])


def compute_rows(accounts, today):
    """Computes a row for every account, not just ones under the 25% at-risk
    threshold. Severity is "Healthy" at/above 25% usage, or "Unknown" when a
    usage % can't be computed at all (missing contract dates or a zero cap)."""
    rows = []
    for a in accounts:
        start = parse(a["Start"])
        end = parse(a["End"])
        months = (end - start).days / 30.44
        if months <= 0 or a["Cap"] <= 0:
            usage_pct = None
        else:
            prorated_cap = a["Cap"] / months
            usage_pct = (a["Pages"] / prorated_cap) * 100 if prorated_cap > 0 else None

        if usage_pct is None:
            sev = "Unknown"
        elif usage_pct < 5:
            sev = "Critical"
        elif usage_pct < 15:
            sev = "High"
        elif usage_pct < 25:
            sev = "Watch"
        else:
            sev = "Healthy"

        days_to_renewal = (end - today).days
        last_login = a.get("LastLogin")
        days_since_login = (today - parse(last_login)).days if last_login else None
        rows.append({
            "Name": a["Name"], "Id": a["Id"], "Owner": a["Owner"], "Tier": a["Tier"], "Severity": sev,
            "UsagePct": (round(usage_pct, 1) if usage_pct is not None else None),
            "Pages": a["Pages"], "Hours": round(a["Hours"], 1),
            "Users": a["Users"], "ACV": a["ACV"], "Renewal": a["End"], "Days": days_to_renewal,
            "LastLogin": last_login, "DaysSinceLogin": days_since_login,
        })
    rows.sort(key=lambda x: (x["UsagePct"] is None, x["UsagePct"] if x["UsagePct"] is not None else 0))
    return rows


def compute_flagged(rows):
    """The at-risk subset (usage % under 25) of an already-computed row list,
    used only for the summary stat tiles."""
    return [r for r in rows if r["Severity"] in ("Critical", "High", "Watch")]


def js_escape(s):
    return s.replace("\\", "\\\\").replace('"', '\\"')


def render_rows_js(rows):
    lines = []
    for f in rows:
        last_login_js = 'null' if f["LastLogin"] is None else '"{}"'.format(f["LastLogin"])
        days_since_login_js = 'null' if f["DaysSinceLogin"] is None else f["DaysSinceLogin"]
        pct_js = 'null' if f["UsagePct"] is None else f["UsagePct"]
        lines.append(
            '    {{name:"{name}", id:"{id}", owner:"{owner}", tier:"{tier}", severity:{sev}, '
            'pct:{pct}, pages:{pages}, hours:{hours}, users:{users}, acv:{acv}, '
            'renewal:"{renewal}", days:{days}, lastLogin:{last_login}, daysSinceLogin:{days_since_login}}},'.format(
                name=js_escape(f["Name"]),
                id=f["Id"],
                owner=js_escape(f["Owner"]),
                tier=f["Tier"],
                sev=SEVERITY_CODE[f["Severity"]],
                pct=pct_js,
                pages=f["Pages"],
                hours=f["Hours"],
                users=f["Users"],
                acv=(int(f["ACV"]) if float(f["ACV"]).is_integer() else f["ACV"]),
                renewal=f["Renewal"],
                days=f["Days"],
                last_login=last_login_js,
                days_since_login=days_since_login_js,
            )
        )
    return "\n".join(lines)


def cycle_position(start_date_str, today):
    """Returns (days_into_cycle, days_remaining, cycle_length_days) for the
    account's current monthly billing cycle, anchored to the day-of-month of
    its contract start date. Approximate: a shorter month clamps to its own
    last day rather than precisely modeling calendar rollovers."""
    import calendar
    start = parse(start_date_str)
    anchor_day = start.day

    def month_add(d, months):
        m = d.month - 1 + months
        y = d.year + m // 12
        m = m % 12 + 1
        day = min(anchor_day, calendar.monthrange(y, m)[1])
        return datetime.date(y, m, day)

    cycle_start = datetime.date(today.year, today.month, min(anchor_day, calendar.monthrange(today.year, today.month)[1]))
    if cycle_start > today:
        cycle_start = month_add(cycle_start, -1)
    cycle_end = month_add(cycle_start, 1)
    days_into = (today - cycle_start).days
    cycle_len = (cycle_end - cycle_start).days
    return days_into, cycle_len - days_into, cycle_len


def render_projected_js(rows):
    lines = []
    for r in rows:
        pct_js = 'null' if r["pct"] is None else r["pct"]
        lines.append(
            '    {{name:"{name}", id:"{id}", tier:"{tier}", pct:{pct}, acv:{acv}, '
            'daysIntoCycle:{days_into}, daysRemaining:{days_remaining}, cycleLen:{cycle_len}}},'.format(
                name=js_escape(r["name"]),
                id=r["id"],
                tier=r["tier"],
                pct=pct_js,
                acv=(int(r["acv"]) if float(r["acv"]).is_integer() else r["acv"]),
                days_into=r["daysIntoCycle"],
                days_remaining=r["daysRemaining"],
                cycle_len=r["cycleLen"],
            )
        )
    return "\n".join(lines)


def load_projected_snapshot(path="projected_snapshot.json"):
    """Reads the mid-cycle projection snapshot written by check_alerts.py
    (which runs Mon/Wed/Fri). Returns (asof_str, rows_js). If the file is
    missing (e.g. before check_alerts.py has ever run), returns a
    "not yet computed" placeholder rather than failing."""
    import os
    if not os.path.exists(path):
        return "Not yet computed", ""
    with open(path) as fh:
        data = json.load(fh)
    return data["asOf"], render_projected_js(data["rows"])


def fill_template(template_text, accounts, today, projected_path="projected_snapshot.json"):
    all_rows = compute_rows(accounts, today)
    flagged = compute_flagged(all_rows)
    total_n = len(accounts)
    flagged_n = len(flagged)
    total_acv = sum(f["ACV"] for f in flagged)
    acv_k = f"${total_acv/1000:.1f}K"

    renewing = [f for f in flagged if f["Days"] <= 60]
    renewing_sorted = sorted(renewing, key=lambda f: f["Days"])
    renew_n = len(renewing)
    if renewing_sorted:
        top = renewing_sorted[0]
        renew_sub = f"{top['Name']} &mdash; {top['Days']} days, {top['UsagePct']}% usage"
    else:
        renew_sub = "None in the next 60 days"

    enterprise = [f for f in flagged if f["Tier"] == "Enterprise"]
    ent_n = len(enterprise)
    ent_sub = ", ".join(f["Name"] for f in enterprise) if enterprise else "None"

    asof = today.strftime("%b %d, %Y").upper()

    rows_js = render_rows_js(all_rows)
    projected_asof, projected_rows_js = load_projected_snapshot(projected_path)

    out = template_text
    out = out.replace("__ASOF__", asof)
    out = out.replace("__FLAGGED_N__", str(flagged_n))
    out = out.replace("__TOTAL_N__", str(total_n))
    out = out.replace("__ACV_K__", acv_k)
    out = out.replace("__RENEW_N__", str(renew_n))
    out = out.replace("__RENEW_SUB__", renew_sub)
    out = out.replace("__ENT_N__", str(ent_n))
    out = out.replace("__ENT_SUB__", ent_sub)
    out = out.replace("__ROWS_JS__", rows_js)
    out = out.replace("__PROJECTED_ASOF__", projected_asof)
    out = out.replace("__PROJECTED_ROWS_JS__", projected_rows_js)

    remaining = re.findall(r"__[A-Z_]+__", out)
    if remaining:
        raise AssertionError(f"Unfilled placeholders remain: {set(remaining)}")

    return out, {
        "flagged_n": flagged_n, "total_n": total_n, "acv_k": acv_k,
        "renew_n": renew_n, "renew_sub": renew_sub, "ent_n": ent_n, "ent_sub": ent_sub,
        "asof": asof, "projected_asof": projected_asof,
    }


if __name__ == "__main__":
    with open("/home/claude/sf-refresh/template.html") as fh:
        template_text = fh.read()

    html, summary = fill_template(template_text, accounts, TODAY)

    out_path = "/home/claude/sf-refresh/AtRiskAccountsSnapshot_new.html"
    with open(out_path, "w") as fh:
        fh.write(html)

    print(json.dumps(summary, indent=2))
    print(f"Wrote {out_path} ({len(html)} bytes)")
