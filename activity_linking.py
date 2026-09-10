"""
activity_linking.py

The Contact-join Task/Event logic that resolves each account's MainContact,
LastEmail/LastEmailBy, LastLogin, and Next Meeting (Salesforce-Event half
only - see NOTE below) from Salesforce activity records.

This is a straight port of logic that, until 2026-09-10, lived only as
natural-language SOQL instructions duplicated across two live automation
Routines' prompts (the daily artifact refresh and the daily Salesforce
Static Resource push) - kept in sync by hand on every change. That was
fragile: a step ("STEP 1D") was once found silently missing from one
Routine's prompt for days. Porting it to tested Python means both live
pages and any future consumer share one implementation.

IMPORTANT, inherited from the original hand-written instructions (see
generate.py's own docstring for the incident history): reps mostly log
activity against the Contact (WhoId), not the Account (WhatId) - 1,221
Events and 185 Email-type Tasks in this org have no WhatId at all. Every
function here joins via Contact.AccountId, never WhatId.

NOTE - what this module deliberately does NOT do: Next Meeting has a
second source beyond Salesforce Events - recurring Google Calendar/Zoom
invites sent via Gmail that are never logged back into Salesforce, plus a
title-pattern match for internal-only prep syncs (see generate.py's
docstring, "NextMeeting has a second/third gap"). That cross-check needs
live Google Calendar/Gmail access, which this headless script has no
credentials for in this environment - only the interactive agent running
a Routine has those tools. compute_sf_event_next_meetings() below computes
ONLY the Salesforce-Event candidate; the calling Routine must still do the
Calendar cross-check itself and take the earlier of the two (or the
title-pattern internal-only match), exactly as documented in generate.py.
"""
import datetime
import json
import urllib.parse

import check_alerts


def fetch_contact_account_map(my_domain, token, account_ids):
    """Contact Id -> Account Id for every Contact belonging to one of
    account_ids. account_ids should be chunked by the caller if it ever
    grows large enough to risk an HTTP 431 (this org's ~74 tracked
    accounts and ~880 contacts have always fit in one query - see
    check_alerts.py's own history of this exact limit)."""
    if not account_ids:
        return {}
    ids_list = "','".join(account_ids)
    records = check_alerts.soql(
        my_domain, token,
        f"SELECT Id, AccountId FROM Contact WHERE AccountId IN ('{ids_list}')",
    )
    return {r["Id"]: r["AccountId"] for r in records}


def _account_contact_ids(account_id, contact_account_map):
    return [cid for cid, aid in contact_account_map.items() if aid == account_id]


def reduce_main_contact_counts(task_counts, event_counts):
    """Pure: given {WhoId: count} from a Task GROUP BY and an Event GROUP
    BY for ONE account's contacts, sums them and returns the winning
    WhoId (highest combined count; ties broken by WhoId string for
    determinism), or None if there were no counts at all."""
    combined = dict(task_counts)
    for who_id, count in event_counts.items():
        combined[who_id] = combined.get(who_id, 0) + count
    if not combined:
        return None
    return max(combined.items(), key=lambda kv: (kv[1], kv[0]))[0]


def compute_main_contacts(my_domain, token, account_ids, contact_account_map):
    """{account_id: contact_name_or_None}. One account at a time (small,
    safe result sets) - established 2026-09-02 after an org-wide GROUP BY
    across every tracked account's contacts at once was found to silently
    truncate and produce stale/wrong main contacts undetected for days."""
    winning_who_ids = {}
    for account_id in account_ids:
        contact_ids = _account_contact_ids(account_id, contact_account_map)
        if not contact_ids:
            winning_who_ids[account_id] = None
            continue
        ids_list = "','".join(contact_ids)
        task_rows = check_alerts.soql(
            my_domain, token,
            f"SELECT WhoId, COUNT(Id) cnt FROM Task WHERE WhoId IN ('{ids_list}') AND WhoId != null GROUP BY WhoId",
        )
        event_rows = check_alerts.soql(
            my_domain, token,
            f"SELECT WhoId, COUNT(Id) cnt FROM Event WHERE WhoId IN ('{ids_list}') AND WhoId != null GROUP BY WhoId",
        )
        task_counts = {r["WhoId"]: r["cnt"] for r in task_rows}
        event_counts = {r["WhoId"]: r["cnt"] for r in event_rows}
        winning_who_ids[account_id] = reduce_main_contact_counts(task_counts, event_counts)

    unresolved = {who_id for who_id in winning_who_ids.values() if who_id}
    names = {}
    if unresolved:
        ids_list = "','".join(unresolved)
        for r in check_alerts.soql(my_domain, token, f"SELECT Id, Name FROM Contact WHERE Id IN ('{ids_list}')"):
            names[r["Id"]] = r["Name"]

    return {aid: (names.get(who_id) if who_id else None) for aid, who_id in winning_who_ids.items()}


def reduce_last_email_top_n(task_rows, contact_account_map, account_ids):
    """Pure: task_rows is a list of {WhoId, ActivityDate, Owner} dicts
    already ORDER BY ActivityDate DESC (the caller's top-2000 query) -
    returns {account_id: (date, owner_name)} for every account whose
    first (= most recent) matching row appears in this slice. Accounts
    not present in the return value need the individual-query fallback
    (they may have older activity not captured in the slice, or none at
    all - either way this function can't tell the difference, which is
    why the fallback always re-queries rather than assuming "absent"
    means "no email on file")."""
    wanted = set(account_ids)
    found = {}
    for row in task_rows:
        account_id = contact_account_map.get(row["WhoId"])
        if account_id is None or account_id not in wanted or account_id in found:
            continue
        owner = row.get("Owner") or {}
        found[account_id] = (row["ActivityDate"], owner.get("Name"))
    return found


def compute_last_email(my_domain, token, account_ids, contact_account_map):
    """{account_id: (last_email_date_or_None, last_email_by_or_None)}.
    Matches generate.py's documented LastEmail/LastEmailBy methodology:
    a top-2000-globally-sorted pass first (SOQL has no MAX() on
    Task.ActivityDate), then an individual per-account re-query for any
    account this slice didn't resolve."""
    if not account_ids:
        return {}
    result = {}
    if contact_account_map:
        # Subquery form, not an inline list of every contact id - this org
        # has ~880 contacts, and inlining that many ids directly triggers
        # HTTP 431 (Request Header Fields Too Large), a bug this codebase
        # already hit and fixed once in check_alerts.py's own history.
        acct_ids_list = "','".join(account_ids)
        top_rows = check_alerts.soql(
            my_domain, token,
            "SELECT WhoId, ActivityDate, Owner.Name FROM Task WHERE TaskSubtype = 'Email' "
            f"AND WhoId IN (SELECT Id FROM Contact WHERE AccountId IN ('{acct_ids_list}')) "
            "ORDER BY ActivityDate DESC NULLS LAST LIMIT 2000",
        )
        result = reduce_last_email_top_n(top_rows, contact_account_map, account_ids)

    for account_id in account_ids:
        if account_id in result:
            continue
        contact_ids = _account_contact_ids(account_id, contact_account_map)
        if not contact_ids:
            result[account_id] = (None, None)
            continue
        ids_list = "','".join(contact_ids)
        rows = check_alerts.soql(
            my_domain, token,
            "SELECT ActivityDate, Owner.Name FROM Task WHERE TaskSubtype = 'Email' "
            f"AND WhoId IN ('{ids_list}') ORDER BY ActivityDate DESC, CreatedDate DESC LIMIT 1",
        )
        if rows:
            owner = rows[0].get("Owner") or {}
            result[account_id] = (rows[0]["ActivityDate"], owner.get("Name"))
        else:
            result[account_id] = (None, None)

    return result


def compute_last_login(my_domain, token, account_ids, contact_account_map, today):
    """{account_id: date_or_None}. Never trusts Account.LastActivityDate
    (a Salesforce rollup that includes future-dated rows - see
    generate.py's docstring for the "Last Login in the future" incident).
    One account at a time, filtered to ActivityDate <= today."""
    today_iso = today.isoformat()
    result = {}
    for account_id in account_ids:
        contact_ids = _account_contact_ids(account_id, contact_account_map)
        if not contact_ids:
            result[account_id] = None
            continue
        ids_list = "','".join(contact_ids)
        candidates = []
        for obj in ("Event", "Task"):
            rows = check_alerts.soql(
                my_domain, token,
                f"SELECT ActivityDate FROM {obj} WHERE WhoId IN ('{ids_list}') "
                f"AND ActivityDate <= {today_iso} AND ActivityDate != null "
                "ORDER BY ActivityDate DESC LIMIT 1",
            )
            if rows:
                candidates.append(rows[0]["ActivityDate"])
        result[account_id] = max(candidates) if candidates else None
    return result


def reduce_next_meeting_candidates(event_min_rows, contact_account_map, account_ids):
    """Pure: event_min_rows is [{WhoId, mindate}] from a MIN(StartDateTime)
    GROUP BY WhoId aggregate query (future events only, filtered by the
    caller) - returns {account_id: earliest_mindate} by taking the min
    across each account's contacts. Accounts with no future event at all
    are simply absent from the result."""
    wanted = set(account_ids)
    best = {}
    for row in event_min_rows:
        account_id = contact_account_map.get(row["WhoId"])
        if account_id is None or account_id not in wanted:
            continue
        mindate = row["mindate"]
        if account_id not in best or mindate < best[account_id]:
            best[account_id] = mindate
    return best


def compute_sf_event_next_meetings(my_domain, token, account_ids, contact_account_map, now_iso):
    """{account_id: {"date": ISO datetime, "title": str, "with": str_or_None}}
    for every account with a future Salesforce Event logged against one of
    its Contacts - the Salesforce-Event half of Next Meeting only (see this
    module's docstring). `with` is a comma-joined list of SiftMed User
    names on the winning Event (EventRelation Users, plus the Event's own
    Owner if not already present - EventRelation alone often omits the
    organizer)."""
    if not account_ids:
        return {}
    if not contact_account_map:
        return {}
    # Subquery form, not an inline list of every contact id - see
    # compute_last_email's own note on why (HTTP 431 at this org's contact
    # count when inlined directly).
    acct_ids_list = "','".join(account_ids)
    min_rows = check_alerts.soql(
        my_domain, token,
        "SELECT WhoId, MIN(StartDateTime) mindate FROM Event "
        f"WHERE WhoId IN (SELECT Id FROM Contact WHERE AccountId IN ('{acct_ids_list}')) "
        f"AND StartDateTime > {now_iso} GROUP BY WhoId",
    )
    candidates = reduce_next_meeting_candidates(min_rows, contact_account_map, account_ids)
    if not candidates:
        return {}

    result = {}
    all_user_ids = set()
    pending = {}
    for account_id, mindate in candidates.items():
        contact_ids = _account_contact_ids(account_id, contact_account_map)
        ids_list = "','".join(contact_ids)
        rows = check_alerts.soql(
            my_domain, token,
            f"SELECT Id, Subject, OwnerId FROM Event WHERE WhoId IN ('{ids_list}') "
            f"AND StartDateTime = {mindate} LIMIT 1",
        )
        if not rows:
            continue
        event = rows[0]
        relation_rows = check_alerts.soql(
            my_domain, token,
            f"SELECT RelationId FROM EventRelation WHERE EventId = '{event['Id']}'",
        )
        user_ids = {r["RelationId"] for r in relation_rows if r["RelationId"].startswith("005")}
        if event.get("OwnerId"):
            user_ids.add(event["OwnerId"])
        all_user_ids |= user_ids
        pending[account_id] = {"date": mindate, "title": event.get("Subject"), "user_ids": user_ids}

    user_names = {}
    if all_user_ids:
        ids_list = "','".join(all_user_ids)
        for r in check_alerts.soql(my_domain, token, f"SELECT Id, Name FROM User WHERE Id IN ('{ids_list}')"):
            user_names[r["Id"]] = r["Name"]

    for account_id, info in pending.items():
        names = sorted(user_names[uid] for uid in info["user_ids"] if uid in user_names)
        result[account_id] = {
            "date": info["date"],
            "title": info["title"],
            "with": ", ".join(names) if names else None,
        }
    return result
