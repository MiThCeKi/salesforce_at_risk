"""
Fills /home/claude/sf-refresh/template.html with freshly computed at-risk data
and writes out the final, ready-to-deploy HTML.

This is the "recompute from Salesforce directly" pipeline step. Today it runs
against the hardcoded `accounts` snapshot (same data compute.py validated
against the live SOQL query on 2026-08-28). In the real scheduled job, the
`accounts` list below gets replaced by a live SOQL query result and TODAY
becomes datetime.date.today() (already the case here).

Usage: python3 generate.py
Output: /home/claude/sf-refresh/AtRiskAccountsSnapshot_new.html
"""
import datetime
import json
import re

TODAY = datetime.date.today()

accounts = [
{"Name":"Canadian Health Solutions Inc","Owner":"Carla Chaytor","Tier":"SMB","ACV":20000,"Start":"2026-04-11","End":"2027-04-10","Cap":200000,"Pages":21396,"Hours":9.1696,"Users":26},
{"Name":"AssessMed Inc.","Owner":"Travis Bailey","Tier":"Enterprise","ACV":124000,"Start":"2026-06-01","End":"2027-06-30","Cap":3100000,"Pages":248875,"Hours":405.1371,"Users":27},
{"Name":"Viewpoint Medical Assessments","Owner":"Travis Bailey","Tier":"SMB","ACV":126000,"Start":"2025-09-01","End":"2026-08-31","Cap":3500000,"Pages":4905,"Hours":14.3344,"Users":12},
{"Name":"Zurich North America","Owner":"Travis Bailey","Tier":"Enterprise","ACV":88200,"Start":"2026-04-01","End":"2028-03-31","Cap":900000,"Pages":14884,"Hours":17.0439,"Users":47},
{"Name":"Peel Mutual Insurance Company","Owner":"Carla Chaytor","Tier":"SMB","ACV":5760,"Start":"2025-08-25","End":"2026-08-24","Cap":38400,"Pages":5456,"Hours":7.8601,"Users":10},
{"Name":"Roebothan McKay Marshall (RMM)","Owner":"Carla Chaytor","Tier":"SMB","ACV":36000,"Start":"2026-06-06","End":"2027-06-06","Cap":480000,"Pages":19451,"Hours":65.3917,"Users":37},
{"Name":"Physiohealth Inc.","Owner":"Carla Chaytor","Tier":"Micro","ACV":1500,"Start":"2026-05-15","End":"2027-05-15","Cap":120000,"Pages":18004,"Hours":15.1318,"Users":1},
{"Name":"Girones Lawyers","Owner":"Carla Chaytor","Tier":"SMB","ACV":11188,"Start":"2026-05-12","End":"2027-05-12","Cap":100000,"Pages":0,"Hours":0,"Users":5},
{"Name":"Hooper Law","Owner":"Carla Chaytor","Tier":"SMB","ACV":6000,"Start":"2023-08-01","End":"2026-07-31","Cap":50000,"Pages":5856,"Hours":6.3538,"Users":10},
{"Name":"Breedon Mor LLP","Owner":"Carla Chaytor","Tier":"SMB","ACV":15000,"Start":"2026-02-12","End":"2027-02-12","Cap":150000,"Pages":11097,"Hours":19.8335,"Users":6},
{"Name":"Crannie Law","Owner":"Carla Chaytor","Tier":"SMB","ACV":11896,"Start":"2026-05-11","End":"2027-05-11","Cap":125000,"Pages":4021,"Hours":54.8696,"Users":4},
{"Name":"Priddle Law Group","Owner":"Matt Baldwin","Tier":"SMB","ACV":600,"Start":"2025-12-01","End":"2026-12-01","Cap":5000,"Pages":0,"Hours":0,"Users":0},
{"Name":"Tri-Star Health Management Group Inc.","Owner":"Travis Bailey","Tier":"SMB","ACV":19250,"Start":"2026-01-20","End":"2027-01-20","Cap":275000,"Pages":14413,"Hours":123.013,"Users":15},
{"Name":"Integral Consulting Services Inc.","Owner":"Travis Bailey","Tier":"SMB","ACV":121500,"Start":"2026-06-30","End":"2027-06-30","Cap":2000000,"Pages":92699,"Hours":96.0318,"Users":3},
{"Name":"JS Held - BioMechanics Group","Owner":"Carla Chaytor","Tier":"SMB","ACV":23061.75,"Start":"2026-01-08","End":"2027-01-08","Cap":125000,"Pages":2674,"Hours":29.2987,"Users":7},
{"Name":"Boucher Medical Professional Corp.","Owner":"Carla Chaytor","Tier":"Micro","ACV":11746,"Start":"2025-03-21","End":"2026-08-31","Cap":275000,"Pages":20627,"Hours":118.7051,"Users":3},
{"Name":"Chris Small Professional Medical Corporation","Owner":"Carla Chaytor","Tier":"Micro","ACV":4800,"Start":"2026-03-21","End":"2027-03-21","Cap":20000,"Pages":24,"Hours":0.8222,"Users":1},
{"Name":"Medical Vocational Planning","Owner":"Travis Bailey","Tier":"SMB","ACV":115200,"Start":"2025-11-01","End":"2027-12-01","Cap":1440000,"Pages":8632,"Hours":52.2319,"Users":6},
{"Name":"Integrity Medical Evaluations","Owner":"Travis Bailey","Tier":"Enterprise","ACV":158400,"Start":"2026-06-25","End":"2027-08-31","Cap":1440000,"Pages":7391,"Hours":5.3222,"Users":1},
{"Name":"Orvosi Medical Management","Owner":"Travis Bailey","Tier":"SMB","ACV":96000,"Start":"2026-01-09","End":"2027-01-08","Cap":1600000,"Pages":7398,"Hours":8.7989,"Users":7},
{"Name":"Curtis Hlushak","Owner":"Carla Chaytor","Tier":"Micro","ACV":4500,"Start":"2026-02-23","End":"2027-02-23","Cap":30000,"Pages":5003,"Hours":6.4159,"Users":1},
{"Name":"Alex Luczack MD","Owner":"Carla Chaytor","Tier":"Micro","ACV":4000,"Start":"2026-07-01","End":"2027-07-01","Cap":55000,"Pages":2686,"Hours":21.1402,"Users":1},
{"Name":"ArthroBiologix Inc.","Owner":"Carla Chaytor","Tier":"Micro","ACV":10800,"Start":"2026-04-01","End":"2027-03-31","Cap":15000,"Pages":22218,"Hours":14.193,"Users":2},
{"Name":"Janet Patterson MD","Owner":"Carla Chaytor","Tier":"Micro","ACV":27700,"Start":"2026-06-30","End":"2027-06-30","Cap":400000,"Pages":30946,"Hours":46.147,"Users":6},
{"Name":"Jamie Irvine MD","Owner":"Carla Chaytor","Tier":"Micro","ACV":9576,"Start":"2026-02-18","End":"2027-02-18","Cap":60000,"Pages":0,"Hours":0.31,"Users":1},
{"Name":"Kevin Smith MD","Owner":"Carla Chaytor","Tier":"Micro","ACV":9000,"Start":"2026-06-30","End":"2027-06-30","Cap":150000,"Pages":8429,"Hours":18.7851,"Users":5},
{"Name":"Mohamed Khaled MD","Owner":"Carla Chaytor","Tier":"Micro","ACV":19349,"Start":"2025-09-03","End":"2026-09-02","Cap":192000,"Pages":149,"Hours":0.1033,"Users":1},
{"Name":"IMED Services","Owner":"Carla Chaytor","Tier":"SMB","ACV":12000,"Start":"2026-05-21","End":"2027-05-20","Cap":60000,"Pages":5361,"Hours":68.7151,"Users":5},
{"Name":"Physician Life Care Planning (PLCP)","Owner":"Travis Bailey","Tier":"SMB","ACV":845000,"Start":"2025-11-07","End":"2027-11-07","Cap":6500000,"Pages":149266,"Hours":2488.3171,"Users":100},
{"Name":"Rehab First Inc.","Owner":"Carla Chaytor","Tier":"SMB","ACV":18000,"Start":"2025-11-03","End":"2026-11-02","Cap":180000,"Pages":8235,"Hours":6.9144,"Users":6},
{"Name":"iMPROve Health","Owner":"Travis Bailey","Tier":"SMB","ACV":36960,"Start":"2025-09-15","End":"2026-09-30","Cap":336000,"Pages":685,"Hours":28.1272,"Users":7},
{"Name":"Life Care Planning Solutions LLC","Owner":"Travis Bailey","Tier":"SMB","ACV":8000,"Start":"2026-06-23","End":"2027-06-23","Cap":300000,"Pages":3745,"Hours":34.0364,"Users":8},
{"Name":"Kenney Shelton Liptak Nowak - KSLN law","Owner":"Carla Chaytor","Tier":"SMB","ACV":41000,"Start":"2026-06-23","End":"2027-06-23","Cap":300000,"Pages":20627,"Hours":51.1357,"Users":21},
{"Name":"Trillium Mutual Insurance Company","Owner":"Carla Chaytor","Tier":"SMB","ACV":7000,"Start":"2026-01-01","End":"2027-01-01","Cap":50000,"Pages":2423,"Hours":3.7124,"Users":2},
{"Name":"North Toronto Surgical","Owner":"Carla Chaytor","Tier":"Micro","ACV":1920,"Start":"2026-06-03","End":"2027-06-03","Cap":24000,"Pages":0,"Hours":0,"Users":1},
{"Name":"Portage Mutual Insurance","Owner":"Travis Bailey","Tier":"SMB","ACV":10200,"Start":"2026-01-07","End":"2027-01-07","Cap":60000,"Pages":4530,"Hours":11.6995,"Users":11},
{"Name":"JHU Consulting","Owner":"Carla Chaytor","Tier":"Micro","ACV":6600,"Start":"2025-07-21","End":"2026-07-26","Cap":17500,"Pages":2324,"Hours":11.5241,"Users":2},
{"Name":"Daugherty & Associates, LLC","Owner":"Carla Chaytor","Tier":"Micro","ACV":8400,"Start":"2025-07-30","End":"2026-07-30","Cap":60000,"Pages":1569,"Hours":89.1256,"Users":1},
{"Name":"Northeast Life Care Planning","Owner":"Carla Chaytor","Tier":"Micro","ACV":8400,"Start":"2025-07-09","End":"2026-07-08","Cap":60000,"Pages":1326,"Hours":7.4339,"Users":1},
{"Name":"Halbrecht Orthopedics","Owner":"Peter Moyse","Tier":"Micro","ACV":650,"Start":"2025-11-23","End":"2026-11-23","Cap":5000,"Pages":0,"Hours":0,"Users":1},
{"Name":"SEA & Associates Medical Legal Consulting Inc","Owner":"Carla Chaytor","Tier":"SMB","ACV":24000,"Start":"2025-09-26","End":"2026-09-25","Cap":420000,"Pages":718,"Hours":0.2831,"Users":2},
{"Name":"TrueLine Medical Legal Consulting","Owner":"Peter Moyse","Tier":"SMB","ACV":12000,"Start":"2026-06-01","End":"2027-05-31","Cap":120000,"Pages":0,"Hours":0,"Users":1},
{"Name":"Integrity Legal Nurse Consulting","Owner":"Travis Bailey","Tier":"SMB","ACV":9000,"Start":"2025-09-22","End":"2026-09-21","Cap":60000,"Pages":0,"Hours":0,"Users":16},
{"Name":"NuHaven Health","Owner":"Carla Chaytor","Tier":"SMB","ACV":8100,"Start":"2025-09-22","End":"2026-09-21","Cap":90000,"Pages":2362,"Hours":6.878,"Users":1},
{"Name":"Cayuga Mutual","Owner":"Travis Bailey","Tier":"SMB","ACV":600,"Start":"2025-10-20","End":"2026-10-19","Cap":5000,"Pages":0,"Hours":0,"Users":0},
{"Name":"KLE Nurse Consultants","Owner":"Carla Chaytor","Tier":"Micro","ACV":9000,"Start":"2025-09-15","End":"2026-09-14","Cap":60000,"Pages":2934,"Hours":0.8554,"Users":3},
{"Name":"Vocational Alternatives","Owner":"Carla Chaytor","Tier":"SMB","ACV":9900,"Start":"2026-03-10","End":"2027-03-09","Cap":90000,"Pages":1194,"Hours":0.9789,"Users":3},
{"Name":"Hands-On Orthopedics","Owner":"Carla Chaytor","Tier":"Micro","ACV":14700,"Start":"2025-12-06","End":"2026-12-05","Cap":70000,"Pages":3335,"Hours":8.8245,"Users":4},
{"Name":"Medivest","Owner":"Travis Bailey","Tier":"SMB","ACV":100000,"Start":"2026-04-01","End":"2027-03-31","Cap":1000000,"Pages":136544,"Hours":96.0233,"Users":12},
{"Name":"The Ivera Group","Owner":"Carla Chaytor","Tier":"SMB","ACV":80000,"Start":"2026-03-23","End":"2027-03-22","Cap":800000,"Pages":7748,"Hours":7.055,"Users":3},
{"Name":"LCP Pro","Owner":"Travis Bailey","Tier":"SMB","ACV":100000,"Start":"2026-05-22","End":"2027-05-21","Cap":950000,"Pages":185998,"Hours":395.5839,"Users":46},
{"Name":"Walnut Orchard Psychology Services","Owner":"Carla Chaytor","Tier":"SMB","ACV":12500,"Start":"2026-04-09","End":"2027-04-08","Cap":120000,"Pages":10490,"Hours":18.5215,"Users":2},
{"Name":"Aua Consulting LLC","Owner":"Travis Bailey","Tier":"Micro","ACV":14000,"Start":"2026-06-08","End":"2027-06-14","Cap":80000,"Pages":22158,"Hours":6.1175,"Users":1},
]

SEVERITY_CODE = {"Critical": 0, "High": 1, "Watch": 2}


def parse(d):
    return datetime.date(*[int(x) for x in d.split("-")])


def compute_flagged(accounts, today):
    flagged = []
    for a in accounts:
        start = parse(a["Start"])
        end = parse(a["End"])
        months = (end - start).days / 30.44
        if months <= 0 or a["Cap"] <= 0:
            continue
        prorated_cap = a["Cap"] / months
        usage_pct = (a["Pages"] / prorated_cap) * 100 if prorated_cap > 0 else 0
        if usage_pct < 25:
            if usage_pct < 5:
                sev = "Critical"
            elif usage_pct < 15:
                sev = "High"
            else:
                sev = "Watch"
            days_to_renewal = (end - today).days
            flagged.append({
                "Name": a["Name"], "Owner": a["Owner"], "Tier": a["Tier"], "Severity": sev,
                "UsagePct": round(usage_pct, 1), "Pages": a["Pages"], "Hours": round(a["Hours"], 1),
                "Users": a["Users"], "ACV": a["ACV"], "Renewal": a["End"], "Days": days_to_renewal,
            })
    flagged.sort(key=lambda x: x["UsagePct"])
    return flagged


def js_escape(s):
    return s.replace("\\", "\\\\").replace('"', '\\"')


def render_rows_js(flagged):
    lines = []
    for f in flagged:
        lines.append(
            '    {{name:"{name}", owner:"{owner}", tier:"{tier}", severity:{sev}, '
            'pct:{pct}, pages:{pages}, hours:{hours}, users:{users}, acv:{acv}, '
            'renewal:"{renewal}", days:{days}}},'.format(
                name=js_escape(f["Name"]),
                owner=js_escape(f["Owner"]),
                tier=f["Tier"],
                sev=SEVERITY_CODE[f["Severity"]],
                pct=f["UsagePct"],
                pages=f["Pages"],
                hours=f["Hours"],
                users=f["Users"],
                acv=(int(f["ACV"]) if float(f["ACV"]).is_integer() else f["ACV"]),
                renewal=f["Renewal"],
                days=f["Days"],
            )
        )
    return "\n".join(lines)


def fill_template(template_text, accounts, today):
    flagged = compute_flagged(accounts, today)
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

    rows_js = render_rows_js(flagged)

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

    remaining = re.findall(r"__[A-Z_]+__", out)
    if remaining:
        raise AssertionError(f"Unfilled placeholders remain: {set(remaining)}")

    return out, {
        "flagged_n": flagged_n, "total_n": total_n, "acv_k": acv_k,
        "renew_n": renew_n, "renew_sub": renew_sub, "ent_n": ent_n, "ent_sub": ent_sub,
        "asof": asof,
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
