"""
Fills /home/claude/sf-refresh/template.html with freshly computed at-risk data
and writes out the final, ready-to-deploy HTML.

This is the "recompute from Salesforce directly" pipeline step. The `accounts`
list below was pulled live via SOQL against Salesforce on 2026-09-02:
Annual_Contract_Value__c > 0 AND PageCountCap__c > 0 AND
Active_Contract_Start_Date__c != null AND Subscription_End_Date__c != null,
selecting Name, Owner.Name, Stage__c, Account_Tier__c, Annual_Contract_Value__c,
Active_Contract_Start_Date__c, Subscription_End_Date__c, PageCountCap__c,
Pages_Last_30__c, Hours_Last_30__c, Active_Users_Last_30__c, LastActivityDate
(the "Last Login" column, despite its name). Deliberately has NO Stage__c
filter as of 2026-09-02 - the criterion for inclusion is "does this account
have the data to compute a usage %", not which sales/lifecycle stage it
currently carries. (It went Stage__c = "Customer" only -> IN ('Customer',
'SQL','Prospect') -> no stage filter at all, in two widenings both made
2026-09-02, each time because a real account with usage data on file -
Litco Law LSO, then Tamming Law - was missing from the list.) This pulls in
Previous Customer (already-churned) and other non-Customer-pipeline stages
too, which is intentional: 72 accounts as of 2026-09-02, up from 60. Do not
reintroduce a Stage__c filter without being asked.

IMPORTANT - activity linking (MainContact/LastEmail/NextMeeting): an earlier
version of this pipeline (through 2026-09-02) joined Task/Event to the
Account via WhatId ("Related To"). That undercounts badly - verified live
2026-09-02 that reps mostly log activity against the Contact (WhoId) and
leave WhatId blank: 1,221 of this org's Events and 185 Email-type Tasks tied
to these accounts' contacts have no WhatId at all. That bug produced 57 of
72 accounts showing a wrong LastEmail (some as "Never" when real emails
existed) and every single account showing NextMeeting=null when 12 real
future meetings existed. The correct join is via Contact: for each account,
first resolve its Contacts (Contact.AccountId), then look up Task/Event by
WhoId IN (those Contact Ids) - never by WhatId. MainContact is derived from
summed Task+Event counts grouped by WhoId (joined via Contact.AccountId);
LastEmail is the most recent ActivityDate among that account's contacts'
TaskSubtype = 'Email' Tasks; NextMeeting is the earliest future
StartDateTime among that account's contacts' Events. Both null when there's
no such record - but confirm null via the Contact-join query before treating
it as "none", since the WhatId-only version produced false nulls. In the
scheduled job, this list gets replaced by that same live SOQL/activity pull
each run, and TODAY becomes datetime.date.today() (already the case here).

Re-verified live 2026-09-02 (later same day): LastEmail/NextMeeting were
re-checked account-by-account (72 direct per-account queries, not the
top-2000-globally-sorted shortcut used in the first pass) and matched
exactly except for two accounts whose data had simply moved forward in
time since the first pass (a new email logged, a same-day meeting that
had since passed) - so that fix was solid. MainContact, however, had NOT
actually been recomputed in the first pass (skipped then due to a query
that returned too many inline rows to parse) and was still carrying stale
values from the old WhatId-based method for 4 accounts: Assessnet (was
"Joanne Dowd", corrected to "Dr. Adriano Persi"), Medical and Life Care
Consulting (was "April Pettengill", corrected to "Cynthia Bourbeau"), and
Priddle Law Group and Sutton Special Risk (both were null/"no main
contact", corrected to "Jasmine Kooner" and "Ahad Imrit" respectively -
both had real logged activity once joined via Contact.AccountId instead
of WhatId). Fixed by running the per-account WhoId GROUP BY query directly
(one account at a time keeps the result set small enough to parse) instead
of one org-wide query across all 72 accounts' contacts at once.

IMPORTANT - NextMeeting has a second, more serious gap (found 2026-09-02,
same day, after the user reported it looked wrong): Salesforce Event
records are NOT the only place real customer meetings live. This rep books
recurring weekly Zoom syncs with several accounts (Zurich North America,
Integrity Medical Evaluations, PsycIME, Medivest, Physician Life Care
Planning (PLCP), NuHaven Health) via Google Calendar/Zoom invites sent
straight from Gmail - and those meetings are NEVER logged back into
Salesforce as an Event on the contact. So the Contact-join-on-Event query
above is necessary but not sufficient: it was still showing
NextMeeting=null for 5 real, weekly-recurring, currently-scheduled
customer meetings (Zurich, Integrity, PsycIME, NuHaven, PLCP), confirmed
by cross-referencing the rep's Google Calendar (external-domain attendees
matched to Contact.Email, e.g. ryan.gussak@zurich.com -> Zurich's main
contact) AND Gmail invite threads ("Invitation: Siftmed x Zurich Weekly
Sync @ Weekly ... on Tuesday", etc. - both sources agreed exactly).
PLCP's real contact showed up as a guest on a meeting titled "Medivest
Weekly Sync" (rpese@physicianlcp.com), not a PLCP-titled meeting, because
Medivest and PLCP share reps who take joint calls - so don't assume a
literal name match between meeting title and account name is required,
only that a matched attendee's email belongs to that account's Contacts.
Correct NextMeeting per account = the EARLIER of (a) the Contact-join
Event query above and (b) the nearest future Google Calendar event with
an external (non-@siftmed.ca) attendee whose email matches one of that
account's Contacts - Medivest is the proof this matters both ways: its
Salesforce Event ("Medivest Index Review", 2026-09-04) is genuinely
earlier than its recurring Google Calendar sync (2026-09-08), so it was
already correct and should NOT be overwritten by the calendar date - take
the minimum of both sources, never one or the other unconditionally. This
data source (Google Calendar + Gmail) is NOT reachable via the plain
Salesforce REST API this script otherwise uses - it requires a Google
Calendar/Gmail-connected session (the interactive session that made this
fix had both).

Follow-up 2026-09-03: tried to close this by attaching an explicit
Calendar/Gmail connector grant to the two scheduled Routines via
create_trigger's `connectors` param - rejected outright: "the connectors
parameter is not available for this organization." That's an org-wide
platform restriction, not something fixable from this repo/script. It's
less of a problem than it sounds, though: the "At-Risk Accounts daily
refresh" Routine's 2026-09-03 run (connectors: null the whole time) still
had working Calendar/Gmail access on its own and independently found/
fixed Integrity Medical Evaluations' next meeting - so this environment
appears to hand every session Gmail/Calendar tools ambiently, and the
(disabled) connector-grant mechanism was never actually the thing gating
access here. Net effect: the STEP 2D/1D Calendar cross-check documented
above should keep working in the scheduled jobs same as it does
interactively; there's no known lever to make that more certain than "it
worked yesterday and today," since the org-level connectors setting can't
be turned on to force-guarantee it.

IMPORTANT - NextMeeting has a THIRD gap (found 2026-09-03, caught by the
user re-checking minutes after a manual refresh): the Calendar cross-check
above only matches events that have an external (non-@siftmed.ca) attendee
whose email is one of the account's Contacts. That misses a real pattern
this team uses: an internal-only prep/sync meeting named after the
customer, with NO external attendee on it at all - verified live with
"SiftMed x MVP Sync" (2026-09-18, attendees travisbailey@siftmed.ca and
michaelking@siftmed.ca only, zack@siftmed.ca declined), created minutes
before the user asked "there should be one now for MVP on another day."
Fix: ALSO match calendar events whose title follows this team's
consistent naming convention - "SiftMed x <X>", "SiftMed <> <X>", "<X> x
SiftMed", or "<X> <> SiftMed" (case-insensitive) - where <X> is the
account's Name or the parenthetical abbreviation at the end of it (e.g.
"MVP" from "Medical Vocational Planning (MVP)"), REQUIRING at least one
@siftmed.ca attendee but NOT requiring an external one. This is a narrow,
validated pattern match, not the freeform Subject-text fuzzy-matching
that's explicitly forbidden elsewhere in this file (which risks false
positives like "NC Ironman" or "BOIL UP WEEK") - checking it against all
72 accounts on 2026-09-03 found matches only for Medivest and PsycIME
(both already correctly captured via the external-attendee path, so no
change) plus this one genuinely new MVP catch. Do not go further than
this specific naming convention (do not match on the account name or
abbreviation appearing anywhere in the Subject) - that would reintroduce
the false-positive risk this pattern was built to avoid.

Usage: python3 generate.py
Output: /home/claude/sf-refresh/AtRiskAccountsSnapshot_new.html
"""
import datetime
import json
import re

TODAY = datetime.date.today()

accounts = [
{"Name":"Alex Luczack MD", "Id":"001OL00000C5CzSYAV", "LastLogin":"2026-08-18", "Owner":"Carla Chaytor", "Stage":"Customer", "Tier":"Micro", "ACV":4000.0, "Start":"2026-07-01", "End":"2027-07-01", "Cap":55000.0, "Pages":2686.0, "Hours":21.1402, "Users":1.0, "MainContact":"Alex Luczack", "LastEmail":"2026-08-18", "NextMeeting":None, "NextMeetingTitle":None, "NextMeetingWith":None},
{"Name":"ArthroBiologix Inc.", "Id":"001OL00000Ckjw6YAB", "LastLogin":"2026-08-19", "Owner":"Carla Chaytor", "Stage":"Customer", "Tier":"Micro", "ACV":10800.0, "Start":"2026-04-01", "End":"2027-03-31", "Cap":15000.0, "Pages":22218.0, "Hours":14.193, "Users":2.0, "MainContact":"Alex Rabinovich", "LastEmail":"2026-08-19", "NextMeeting":None, "NextMeetingTitle":None, "NextMeetingWith":None},
{"Name":"AssessMed Inc.", "Id":"0015f00000IQRGHAA5", "LastLogin":"2026-09-03", "Owner":"Travis Bailey", "Stage":"Customer", "Tier":"Enterprise", "ACV":124000.0, "Start":"2026-06-01", "End":"2027-06-30", "Cap":3100000.0, "Pages":278872.0, "Hours":393.6182, "Users":27.0, "MainContact":"Kelly Costa", "LastEmail":"2026-09-03", "NextMeeting":None, "NextMeetingTitle":None, "NextMeetingWith":None},
{"Name":"Assessnet", "Id":"001OL00000Xtpi4YAB", "LastLogin":"2026-08-11", "Owner":"Carla Chaytor", "Stage":"SQL", "Tier":"SMB", "ACV":18000.0, "Start":"2025-10-16", "End":"2026-10-15", "Cap":150000.0, "Pages":0, "Hours":0, "Users":0, "MainContact":"Dr. Adriano Persi", "LastEmail":"2026-04-27", "NextMeeting":None, "NextMeetingTitle":None, "NextMeetingWith":None},
{"Name":"Aua Consulting LLC", "Id":"001OL00000kV72oYAC", "LastLogin":"2026-07-17", "Owner":"Travis Bailey", "Stage":"Customer", "Tier":"Micro", "ACV":14000.0, "Start":"2026-06-08", "End":"2027-06-14", "Cap":80000.0, "Pages":12377.0, "Hours":4.9829, "Users":1.0, "MainContact":"Michael Schaufele", "LastEmail":"2026-07-17", "NextMeeting":None, "NextMeetingTitle":None, "NextMeetingWith":None},
{"Name":"Bobbie Ross MD", "Id":"001OL00000D0ArZYAV", "LastLogin":"2026-03-19", "Owner":"Carla Chaytor", "Stage":"Previous Customer", "Tier":"Micro", "ACV":3000.0, "Start":"2025-09-17", "End":"2026-03-16", "Cap":30000.0, "Pages":0, "Hours":0, "Users":0, "MainContact":"Bobbie Ross", "LastEmail":"2026-03-06", "NextMeeting":None, "NextMeetingTitle":None, "NextMeetingWith":None},
{"Name":"Boucher Medical Professional Corp.", "Id":"001OL0000087uk3YAA", "LastLogin":"2026-09-03", "Owner":"Carla Chaytor", "Stage":"Customer", "Tier":"Micro", "ACV":13500.0, "Start":"2026-08-31", "End":"2027-08-31", "Cap":275000.0, "Pages":20627.0, "Hours":96.949, "Users":3.0, "MainContact":"Michael Boucher", "LastEmail":"2026-09-03", "NextMeeting":None, "NextMeetingTitle":None, "NextMeetingWith":None},
{"Name":"Breedon Mor LLP", "Id":"001I9000005T4bZIAS", "LastLogin":"2026-08-11", "Owner":"Carla Chaytor", "Stage":"Customer", "Tier":"SMB", "ACV":15000.0, "Start":"2026-02-12", "End":"2027-02-12", "Cap":150000.0, "Pages":6336.0, "Hours":21.8121, "Users":6.0, "MainContact":"Jessica Mor", "LastEmail":"2026-08-17", "NextMeeting":None, "NextMeetingTitle":None, "NextMeetingWith":None},
{"Name":"Buckeye Medical Legal Consulting", "Id":"001OL00000SHtnxYAD", "LastLogin":"2026-08-20", "Owner":"Carla Chaytor", "Stage":"SQL", "Tier":"Micro", "ACV":13200.0, "Start":"2025-11-07", "End":"2026-10-31", "Cap":120000.0, "Pages":1150.0, "Hours":3.3724, "Users":1.0, "MainContact":"Dan Bravard", "LastEmail":"2026-08-20", "NextMeeting":None, "NextMeetingTitle":None, "NextMeetingWith":None},
{"Name":"Canadian Health Solutions Inc", "Id":"0015f00000IPHxuAAH", "LastLogin":"2026-09-08", "Owner":"Carla Chaytor", "Stage":"Customer", "Tier":"SMB", "ACV":20000.0, "Start":"2026-04-11", "End":"2027-04-10", "Cap":200000.0, "Pages":26758.0, "Hours":7.0917, "Users":26.0, "MainContact":"Allison Smith", "LastEmail":"2026-08-26", "NextMeeting":"2026-09-08", "NextMeetingTitle":"SiftMed - CHS: Chat about next steps", "NextMeetingWith":"Mike Mensink, Peter Moyse"},
{"Name":"Carol Bierbrier & Associates - CBA", "Id":"001I9000007Bwg5IAC", "LastLogin":"2026-05-01", "Owner":"Carla Chaytor", "Stage":"Previous Customer", "Tier":"Micro", "ACV":6840.0, "Start":"2026-02-12", "End":"2026-05-01", "Cap":36000.0, "Pages":0, "Hours":0, "Users":0, "MainContact":"Alyssa Bierbrier", "LastEmail":"2026-05-01", "NextMeeting":None, "NextMeetingTitle":None, "NextMeetingWith":None},
{"Name":"Cayuga Mutual", "Id":"001OL00000VTlWPYA1", "LastLogin":"2026-08-06", "Owner":"Travis Bailey", "Stage":"Customer", "Tier":"SMB", "ACV":600.0, "Start":"2025-10-20", "End":"2026-10-19", "Cap":5000.0, "Pages":0, "Hours":0, "Users":0, "MainContact":"Paul Tiller", "LastEmail":"2026-08-06", "NextMeeting":None, "NextMeetingTitle":None, "NextMeetingWith":None},
{"Name":"Chris Small Professional Medical Corporation", "Id":"001OL000008ibX8YAI", "LastLogin":"2026-08-11", "Owner":"Carla Chaytor", "Stage":"Customer", "Tier":"Micro", "ACV":4800.0, "Start":"2026-03-21", "End":"2027-03-21", "Cap":20000.0, "Pages":490.0, "Hours":0.9278, "Users":1.0, "MainContact":"Christopher Small", "LastEmail":"2026-06-25", "NextMeeting":None, "NextMeetingTitle":None, "NextMeetingWith":None},
{"Name":"Crannie Law", "Id":"001I9000005T4dLIAS", "LastLogin":"2026-08-11", "Owner":"Carla Chaytor", "Stage":"Customer", "Tier":"SMB", "ACV":11896.0, "Start":"2026-05-11", "End":"2027-05-11", "Cap":125000.0, "Pages":3113.0, "Hours":56.6013, "Users":4.0, "MainContact":"Ruth Johnson", "LastEmail":"2026-08-11", "NextMeeting":None, "NextMeetingTitle":None, "NextMeetingWith":None},
{"Name":"Curtis Hlushak", "Id":"001OL00000C4p0PYAR", "LastLogin":"2026-08-11", "Owner":"Carla Chaytor", "Stage":"Customer", "Tier":"Micro", "ACV":4500.0, "Start":"2026-02-23", "End":"2027-02-23", "Cap":30000.0, "Pages":3275.0, "Hours":7.4064, "Users":1.0, "MainContact":"Curtis Hlushak", "LastEmail":"2026-07-01", "NextMeeting":None, "NextMeetingTitle":None, "NextMeetingWith":None},
{"Name":"Daugherty & Associates, LLC", "Id":"001OL00000SYxvHYAT", "LastLogin":"2026-08-18", "Owner":"Carla Chaytor", "Stage":"Customer", "Tier":"Micro", "ACV":8400.0, "Start":"2026-07-30", "End":"2027-07-29", "Cap":60000.0, "Pages":34.0, "Hours":63.007, "Users":1.0, "MainContact":"Shirley Daugherty", "LastEmail":"2026-07-20", "NextMeeting":None, "NextMeetingTitle":None, "NextMeetingWith":None},
{"Name":"Dr. Jordi Cisa Medical Corporation", "Id":"001OL00000BxtGiYAJ", "LastLogin":"2026-08-13", "Owner":"Carla Chaytor", "Stage":"Kick Back", "Tier":"Micro", "ACV":4590.0, "Start":"2025-10-09", "End":"2026-10-08", "Cap":36000.0, "Pages":1072.0, "Hours":3.6097, "Users":2.0, "MainContact":"Anne Lagace", "LastEmail":"2026-07-14", "NextMeeting":None, "NextMeetingTitle":None, "NextMeetingWith":None},
{"Name":"Dr. Rick Hu", "Id":"001OL00000YiPK6YAN", "LastLogin":"2026-09-02", "Owner":"Carla Chaytor", "Stage":"SQL", "Tier":"Micro", "ACV":9600.0, "Start":"2025-10-09", "End":"2026-09-24", "Cap":120000.0, "Pages":3501.0, "Hours":24.2298, "Users":1.0, "MainContact":"Rick Hu", "LastEmail":"2026-08-19", "NextMeeting":None, "NextMeetingTitle":None, "NextMeetingWith":None},
{"Name":"Dr. Yaacov Markus", "Id":"001OL00000p3vHKYAY", "LastLogin":"2026-09-02", "Owner":"Carla Chaytor", "Stage":"Prospect", "Tier":None, "ACV":13800.0, "Start":"2026-06-09", "End":"2027-06-30", "Cap":60000.0, "Pages":0, "Hours":0, "Users":0, "MainContact":"Yaacov Markus", "LastEmail":"2026-09-02", "NextMeeting":None, "NextMeetingTitle":None, "NextMeetingWith":None},
{"Name":"Drass and Associates Behavioral Healthcare and Legal Nurse Consulting", "Id":"001OL00000UZty1YAD", "LastLogin":"2026-08-11", "Owner":"Peter Moyse", "Stage":"Previous Customer", "Tier":"Micro", "ACV":600.0, "Start":"2025-08-28", "End":"2026-08-28", "Cap":5000.0, "Pages":0, "Hours":0, "Users":3.0, "MainContact":"Theresa Drass", "LastEmail":"2026-05-26", "NextMeeting":None, "NextMeetingTitle":None, "NextMeetingWith":None},
{"Name":"E4 Life Care Planning, LLC", "Id":"001OL00000RHvTmYAL", "LastLogin":"2026-08-13", "Owner":"Carla Chaytor", "Stage":"Prospect", "Tier":"Micro", "ACV":9618.0, "Start":"2026-07-28", "End":"2027-07-27", "Cap":60000.0, "Pages":148.0, "Hours":1.0229, "Users":1.0, "MainContact":"Alison Wohlhuter", "LastEmail":"2026-07-26", "NextMeeting":None, "NextMeetingTitle":None, "NextMeetingWith":None},
{"Name":"Girones Lawyers", "Id":"001I9000005T4a9IAC", "LastLogin":"2026-08-11", "Owner":"Carla Chaytor", "Stage":"Customer", "Tier":"SMB", "ACV":11188.0, "Start":"2026-05-12", "End":"2027-05-12", "Cap":100000.0, "Pages":0, "Hours":0, "Users":5.0, "MainContact":"Andrea Girones", "LastEmail":"2026-06-22", "NextMeeting":None, "NextMeetingTitle":None, "NextMeetingWith":None},
{"Name":"Halbrecht Orthopedics", "Id":"001OL00000TX14jYAD", "LastLogin":"2026-05-11", "Owner":"Peter Moyse", "Stage":"Previous Customer", "Tier":"Micro", "ACV":650.0, "Start":"2025-11-23", "End":"2026-11-23", "Cap":5000.0, "Pages":0, "Hours":0, "Users":1.0, "MainContact":"Joanne Halbrecht", "LastEmail":"2026-05-11", "NextMeeting":None, "NextMeetingTitle":None, "NextMeetingWith":None},
{"Name":"Hands-On Orthopedics", "Id":"001OL00000dg8ynYAA", "LastLogin":"2026-06-30", "Owner":"Carla Chaytor", "Stage":"Customer", "Tier":"Micro", "ACV":14700.0, "Start":"2025-12-06", "End":"2026-12-05", "Cap":70000.0, "Pages":3436.0, "Hours":11.1752, "Users":4.0, "MainContact":"Ronald Williams", "LastEmail":"2026-06-30", "NextMeeting":None, "NextMeetingTitle":None, "NextMeetingWith":None},
{"Name":"Hooper Law", "Id":"001I9000005T4bNIAS", "LastLogin":"2026-08-11", "Owner":"Carla Chaytor", "Stage":"Customer", "Tier":"SMB", "ACV":6000.0, "Start":"2026-08-01", "End":"2027-07-31", "Cap":50000.0, "Pages":9018.0, "Hours":8.3668, "Users":10.0, "MainContact":"Paige Thompson", "LastEmail":"2026-07-23", "NextMeeting":None, "NextMeetingTitle":None, "NextMeetingWith":None},
{"Name":"IMED Services", "Id":"001OL00000Io5WoYAJ", "LastLogin":"2026-09-02", "Owner":"Carla Chaytor", "Stage":"Customer", "Tier":"SMB", "ACV":12000.0, "Start":"2026-05-21", "End":"2027-05-20", "Cap":60000.0, "Pages":4532.0, "Hours":67.2805, "Users":5.0, "MainContact":"John Byrne", "LastEmail":"2026-09-02", "NextMeeting":None, "NextMeetingTitle":None, "NextMeetingWith":None},
{"Name":"Integral Consulting Services Inc.", "Id":"001I9000007cllGIAQ", "LastLogin":"2026-08-31", "Owner":"Travis Bailey", "Stage":"Customer", "Tier":"SMB", "ACV":121500.0, "Start":"2026-06-30", "End":"2027-06-30", "Cap":2000000.0, "Pages":95445.0, "Hours":96.5147, "Users":3.0, "MainContact":"Renee Madonna", "LastEmail":"2026-08-31", "NextMeeting":None, "NextMeetingTitle":None, "NextMeetingWith":None},
{"Name":"Integrated Insurance Resources", "Id":"001OL00000i3vA5YAI", "LastLogin":"2026-08-12", "Owner":"Carla Chaytor", "Stage":"Unqualifed", "Tier":"SMB", "ACV":9000.0, "Start":"2026-04-01", "End":"2027-03-31", "Cap":60000.0, "Pages":1640.0, "Hours":4.0302, "Users":5.0, "MainContact":"Jacqueline Caceres", "LastEmail":"2026-08-12", "NextMeeting":None, "NextMeetingTitle":None, "NextMeetingWith":None},
{"Name":"Integrity Legal Nurse Consulting", "Id":"001OL00000UmhEIYAZ", "LastLogin":"2026-09-15", "Owner":"Travis Bailey", "Stage":"Customer", "Tier":"SMB", "ACV":9000.0, "Start":"2025-09-22", "End":"2026-09-21", "Cap":60000.0, "Pages":0, "Hours":0, "Users":16.0, "MainContact":"Wendy Votroubek", "LastEmail":"2026-06-18", "NextMeeting":"2026-09-15", "NextMeetingTitle":"SiftMed <> Integrity: Quarterly Review #4", "NextMeetingWith":"Travis Bailey"},
{"Name":"Integrity Medical Evaluations", "Id":"001OL00000AU6wgYAD", "LastLogin":"2026-09-03", "Owner":"Michael King", "Stage":"Customer", "Tier":"Enterprise", "ACV":158400.0, "Start":"2026-06-25", "End":"2027-08-31", "Cap":1440000.0, "Pages":2496.0, "Hours":3.707, "Users":1.0, "MainContact":"Tiffany Sparks", "LastEmail":"2026-09-03", "NextMeeting":"2026-09-08", "NextMeetingTitle":"SiftMed x Integrity Weekly Sync", "NextMeetingWith":"John Byrne, Michael King, Travis Bailey, Zackary Chaulk"},
{"Name":"JHU Consulting", "Id":"001OL00000SYhk0YAD", "LastLogin":"2026-08-11", "Owner":"Carla Chaytor", "Stage":"Customer", "Tier":"Micro", "ACV":6600.0, "Start":"2026-01-30", "End":"2027-01-30", "Cap":30000.0, "Pages":2324.0, "Hours":3.1922, "Users":2.0, "MainContact":"Jessica Urie", "LastEmail":"2026-07-15", "NextMeeting":None, "NextMeetingTitle":None, "NextMeetingWith":None},
{"Name":"JS Held - BioMechanics Group", "Id":"001OL000006SaZlYAK", "LastLogin":"2026-09-03", "Owner":"Carla Chaytor", "Stage":"Customer", "Tier":"SMB", "ACV":23061.75, "Start":"2026-01-08", "End":"2027-01-08", "Cap":125000.0, "Pages":2233.0, "Hours":19.3327, "Users":7.0, "MainContact":"Karla Cassidy", "LastEmail":"2026-09-03", "NextMeeting":None, "NextMeetingTitle":None, "NextMeetingWith":None},
{"Name":"Jamie Irvine MD", "Id":"001OL00000D0AqjYAF", "LastLogin":"2026-08-11", "Owner":"Carla Chaytor", "Stage":"Customer", "Tier":"Micro", "ACV":9576.0, "Start":"2026-02-18", "End":"2027-02-18", "Cap":60000.0, "Pages":0, "Hours":0.31, "Users":1.0, "MainContact":"James Irvine", "LastEmail":"2026-06-15", "NextMeeting":None, "NextMeetingTitle":None, "NextMeetingWith":None},
{"Name":"Janet Patterson MD", "Id":"001OL00000Czp9PYAR", "LastLogin":"2026-08-11", "Owner":"Carla Chaytor", "Stage":"Customer", "Tier":"Micro", "ACV":27700.0, "Start":"2026-06-30", "End":"2027-06-30", "Cap":400000.0, "Pages":34835.0, "Hours":51.1812, "Users":6.0, "MainContact":"Raquel Bean", "LastEmail":"2026-06-25", "NextMeeting":None, "NextMeetingTitle":None, "NextMeetingWith":None},
{"Name":"KLE Nurse Consultants", "Id":"001OL00000XOkQ8YAL", "LastLogin":"2026-08-11", "Owner":"Carla Chaytor", "Stage":"Customer", "Tier":"Micro", "ACV":9000.0, "Start":"2025-09-15", "End":"2026-09-14", "Cap":60000.0, "Pages":2934.0, "Hours":2.8743, "Users":3.0, "MainContact":"Kelly Ehrhardt", "LastEmail":"2026-07-16", "NextMeeting":None, "NextMeetingTitle":None, "NextMeetingWith":None},
{"Name":"Kenney Shelton Liptak Nowak - KSLN law", "Id":"001OL00000Q4KAsYAN", "LastLogin":"2027-04-01", "Owner":"Carla Chaytor", "Stage":"Customer", "Tier":"SMB", "ACV":41000.0, "Start":"2026-06-23", "End":"2027-06-23", "Cap":300000.0, "Pages":17106.0, "Hours":42.9013, "Users":21.0, "MainContact":"Janine Smith", "LastEmail":"2026-08-28", "NextMeeting":"2026-10-01", "NextMeetingTitle":"SiftMed <> KSLN QBR", "NextMeetingWith":"Carla Chaytor"},
{"Name":"Kevin Smith MD", "Id":"001OL00000D0B7IYAV", "LastLogin":"2026-08-11", "Owner":"Carla Chaytor", "Stage":"Customer", "Tier":"Micro", "ACV":9000.0, "Start":"2026-06-30", "End":"2027-06-30", "Cap":150000.0, "Pages":8688.0, "Hours":13.9108, "Users":5.0, "MainContact":"Kevin Smith", "LastEmail":"2026-08-06", "NextMeeting":None, "NextMeetingTitle":None, "NextMeetingWith":None},
{"Name":"LCP Pro", "Id":"001OL00000i2nBOYAY", "LastLogin":"2026-09-03", "Owner":"Travis Bailey", "Stage":"Customer", "Tier":"SMB", "ACV":100000.0, "Start":"2026-05-22", "End":"2027-05-21", "Cap":950000.0, "Pages":156132.0, "Hours":335.0812, "Users":46.0, "MainContact":"Shelene Giles", "LastEmail":"2026-09-03", "NextMeeting":None, "NextMeetingTitle":None, "NextMeetingWith":None},
{"Name":"Laxton Consulting, LLC", "Id":"001OL00000YdWpQYAV", "LastLogin":"2026-07-21", "Owner":"Carla Chaytor", "Stage":"Prospect", "Tier":"Micro", "ACV":9000.0, "Start":"2025-10-17", "End":"2026-10-17", "Cap":60000.0, "Pages":7215.0, "Hours":9.1257, "Users":1.0, "MainContact":"Theresa Laxton", "LastEmail":"2026-06-30", "NextMeeting":None, "NextMeetingTitle":None, "NextMeetingWith":None},
{"Name":"Life Care Planning Solutions LLC", "Id":"001OL00000NseOJYAZ", "LastLogin":"2026-08-11", "Owner":"Travis Bailey", "Stage":"Customer", "Tier":"SMB", "ACV":8000.0, "Start":"2026-06-23", "End":"2027-06-23", "Cap":300000.0, "Pages":4162.0, "Hours":32.7357, "Users":8.0, "MainContact":"Jennifer Post", "LastEmail":"2026-07-16", "NextMeeting":None, "NextMeetingTitle":None, "NextMeetingWith":None},
{"Name":"Litco Law LSO", "Id":"001I9000006SKfQIAW", "LastLogin":"2026-09-11", "Owner":"Travis Bailey", "Stage":"SQL", "Tier":"Enterprise", "ACV":62500.0, "Start":"2026-07-15", "End":"2027-07-14", "Cap":600000.0, "Pages":197.0, "Hours":7.8855, "Users":3.0, "MainContact":"Liz Detmold", "LastEmail":"2026-08-04", "NextMeeting":"2026-09-11", "NextMeetingTitle":"SiftMed x Valent Template Review", "NextMeetingWith":"Travis Bailey, Zackary Chaulk"},
{"Name":"Medical Vocational Planning (MVP)", "Id":"001OL00000A5GPoYAN", "LastLogin":"2026-10-28", "Owner":"Michael King", "Stage":"Customer", "Tier":"SMB", "ACV":115200.0, "Start":"2025-11-01", "End":"2027-12-01", "Cap":1440000.0, "Pages":17901.0, "Hours":54.5506, "Users":6.0, "MainContact":"Eva Sarkinen", "LastEmail":"2026-09-02", "NextMeeting":"2026-09-18", "NextMeetingTitle":"SiftMed x MVP Sync", "NextMeetingWith":"Travis Bailey, Michael King"},
{"Name":"Medical and Life Care Consulting", "Id":"001OL00000SL1U6YAL", "LastLogin":"2026-09-24", "Owner":"Carla Chaytor", "Stage":"Unqualifed", "Tier":"Micro", "ACV":16800.0, "Start":"2025-11-03", "End":"2026-11-03", "Cap":120000.0, "Pages":2064.0, "Hours":2.092, "Users":4.0, "MainContact":"Cynthia Bourbeau", "LastEmail":"2026-08-04", "NextMeeting":"2026-09-24", "NextMeetingTitle":"SiftMed <> MLCC Quarterly Business Review", "NextMeetingWith":"Mike Mensink"},
{"Name":"Medivest", "Id":"001OL00000eL401YAC", "LastLogin":"2026-09-04", "Owner":"Travis Bailey", "Stage":"Customer", "Tier":"SMB", "ACV":100000.0, "Start":"2026-04-01", "End":"2027-03-31", "Cap":1000000.0, "Pages":140422.0, "Hours":104.8003, "Users":12.0, "MainContact":"Anna Childers", "LastEmail":"2026-09-03", "NextMeeting":"2026-09-04", "NextMeetingTitle":"Medivest Index Review", "NextMeetingWith":"John Byrne, Travis Bailey"},
{"Name":"Mohamed Khaled MD", "Id":"001OL00000D0B7XYAV", "LastLogin":"2026-08-11", "Owner":"Carla Chaytor", "Stage":"Customer", "Tier":"Micro", "ACV":19349.0, "Start":"2025-09-03", "End":"2026-09-02", "Cap":192000.0, "Pages":149.0, "Hours":0.1033, "Users":1.0, "MainContact":"Mohamed Khaled", "LastEmail":"2026-06-24", "NextMeeting":None, "NextMeetingTitle":None, "NextMeetingWith":None},
{"Name":"National Medical Reviews (NMR)", "Id":"001I9000007bWXNIA2", "LastLogin":"2026-08-25", "Owner":"Travis Bailey", "Stage":"Prospect", "Tier":"Enterprise", "ACV":350000.0, "Start":"2026-07-01", "End":"2027-06-30", "Cap":3500000.0, "Pages":6371.0, "Hours":11.2638, "Users":8.0, "MainContact":"Nicole Borror", "LastEmail":"2026-09-03", "NextMeeting":None, "NextMeetingTitle":None, "NextMeetingWith":None},
{"Name":"North Toronto Surgical", "Id":"001OL00000SE68iYAD", "LastLogin":"2026-08-11", "Owner":"Carla Chaytor", "Stage":"Customer", "Tier":"Micro", "ACV":1920.0, "Start":"2026-06-03", "End":"2027-06-03", "Cap":24000.0, "Pages":0, "Hours":0, "Users":1.0, "MainContact":"Luis Figueroa", "LastEmail":"2026-06-10", "NextMeeting":None, "NextMeetingTitle":None, "NextMeetingWith":None},
{"Name":"Northeast Life Care Planning", "Id":"001OL00000TANqiYAH", "LastLogin":"2026-08-18", "Owner":"Carla Chaytor", "Stage":"Customer", "Tier":"Micro", "ACV":9250.0, "Start":"2026-07-09", "End":"2027-07-08", "Cap":60000.0, "Pages":4511.0, "Hours":8.2344, "Users":1.0, "MainContact":"Barbara Bate", "LastEmail":"2026-06-30", "NextMeeting":None, "NextMeetingTitle":None, "NextMeetingWith":None},
{"Name":"NuHaven Health", "Id":"001OL00000VI1ofYAD", "LastLogin":"2026-08-17", "Owner":"Carla Chaytor", "Stage":"Customer", "Tier":"SMB", "ACV":8100.0, "Start":"2025-09-22", "End":"2026-09-21", "Cap":90000.0, "Pages":2421.0, "Hours":10.0283, "Users":1.0, "MainContact":"Brad King", "LastEmail":"2026-08-11", "NextMeeting":"2026-09-09", "NextMeetingTitle":"SiftMed <> NuHaven", "NextMeetingWith":"Carla Chaytor, Michael King, Zackary Chaulk"},
{"Name":"Orvosi Medical Management", "Id":"001OL00000BbZGdYAN", "LastLogin":"2026-08-31", "Owner":"Zackary Chaulk", "Stage":"Customer", "Tier":"SMB", "ACV":96000.0, "Start":"2026-01-09", "End":"2027-01-08", "Cap":1600000.0, "Pages":7847.0, "Hours":13.9434, "Users":7.0, "MainContact":"Rachel Stanga", "LastEmail":"2026-09-01", "NextMeeting":None, "NextMeetingTitle":None, "NextMeetingWith":None},
{"Name":"Paul Zalzal MD", "Id":"001OL00000Co9OYYAZ", "LastLogin":"2026-08-11", "Owner":"John Byrne", "Stage":"Previous Customer", "Tier":"Micro", "ACV":4752.0, "Start":"2024-08-30", "End":"2026-08-30", "Cap":48000.0, "Pages":0, "Hours":0, "Users":1.0, "MainContact":"Paul Zalzal", "LastEmail":"2026-03-30", "NextMeeting":None, "NextMeetingTitle":None, "NextMeetingWith":None},
{"Name":"Peel Mutual Insurance Company", "Id":"001I900000362wRIAQ", "LastLogin":"2026-09-28", "Owner":"Carla Chaytor", "Stage":"Customer", "Tier":"SMB", "ACV":5760.0, "Start":"2025-09-08", "End":"2026-09-08", "Cap":38400.0, "Pages":5643.0, "Hours":10.5074, "Users":10.0, "MainContact":"Daniel Heap", "LastEmail":"2026-07-31", "NextMeeting":"2026-09-08", "NextMeetingTitle":"SiftMed <> Peel", "NextMeetingWith":"Nitla Cooke"},
{"Name":"Physician Life Care Planning (PLCP)", "Id":"001OL00000KcO97YAF", "LastLogin":"2026-09-03", "Owner":"Nitla Cooke", "Stage":"Customer", "Tier":"SMB", "ACV":845000.0, "Start":"2025-11-07", "End":"2027-11-07", "Cap":6500000.0, "Pages":151777.0, "Hours":2505.3035, "Users":100.0, "MainContact":"Andres Martinez", "LastEmail":"2026-09-03", "NextMeeting":"2026-09-08", "NextMeetingTitle":"SiftMed x Medivest Weekly Sync", "NextMeetingWith":"Holly Hill, John Byrne, Michael King, Travis Bailey, Zackary Chaulk"},
{"Name":"Physiohealth Inc.", "Id":"001I9000004mawoIAA", "LastLogin":"2026-08-11", "Owner":"Carla Chaytor", "Stage":"Customer", "Tier":"Micro", "ACV":1500.0, "Start":"2026-05-15", "End":"2027-05-15", "Cap":120000.0, "Pages":15993.0, "Hours":12.0885, "Users":1.0, "MainContact":"Dennis Polygenis", "LastEmail":"2026-07-17", "NextMeeting":None, "NextMeetingTitle":None, "NextMeetingWith":None},
{"Name":"Portage Mutual Insurance", "Id":"001OL00000SGW3tYAH", "LastLogin":"2026-08-11", "Owner":"Travis Bailey", "Stage":"Customer", "Tier":"SMB", "ACV":10200.0, "Start":"2026-01-07", "End":"2027-01-07", "Cap":60000.0, "Pages":2738.0, "Hours":8.7267, "Users":11.0, "MainContact":"Chaussie Lawson", "LastEmail":"2026-08-11", "NextMeeting":None, "NextMeetingTitle":None, "NextMeetingWith":None},
{"Name":"Priddle Law Group", "Id":"001I9000005T4fNIAS", "LastLogin":"2026-06-10", "Owner":"Matt Baldwin", "Stage":"Previous Customer", "Tier":"SMB", "ACV":600.0, "Start":"2025-12-01", "End":"2026-12-02", "Cap":5000.0, "Pages":0, "Hours":0, "Users":0, "MainContact":"Jasmine Kooner", "LastEmail":"2026-03-13", "NextMeeting":None, "NextMeetingTitle":None, "NextMeetingWith":None},
{"Name":"PsycIME", "Id":"0015f00000WHoQUAA1", "LastLogin":"2026-09-01", "Owner":"Michael King", "Stage":"SQL", "Tier":"Enterprise", "ACV":105000.0, "Start":"2025-09-30", "End":"2027-09-30", "Cap":1500000.0, "Pages":58623.0, "Hours":121.6512, "Users":5.0, "MainContact":"Jacqueline Buck", "LastEmail":"2026-09-01", "NextMeeting":"2026-09-10", "NextMeetingTitle":"SiftMed x PsycIME Weekly Sync", "NextMeetingWith":"Laura Fry, Michael King, Nitla Cooke, Travis Bailey, Zackary Chaulk"},
{"Name":"Rachel Yeboah MD", "Id":"001OL00000Czp7tYAB", "LastLogin":"2026-05-04", "Owner":"Matt Baldwin", "Stage":"Previous Customer", "Tier":"Micro", "ACV":5400.0, "Start":"2025-10-23", "End":"2026-10-22", "Cap":36000.0, "Pages":0, "Hours":0, "Users":1.0, "MainContact":"Rachel Yeboah", "LastEmail":"2026-05-04", "NextMeeting":None, "NextMeetingTitle":None, "NextMeetingWith":None},
{"Name":"Rehab First Inc.", "Id":"001OL00000Kf2yUYAR", "LastLogin":"2026-10-08", "Owner":"Carla Chaytor", "Stage":"Customer", "Tier":"SMB", "ACV":18000.0, "Start":"2025-11-03", "End":"2026-11-02", "Cap":180000.0, "Pages":15275.0, "Hours":10.7382, "Users":6.0, "MainContact":"Andrew Ferguson", "LastEmail":"2026-09-02", "NextMeeting":"2026-09-09", "NextMeetingTitle":"Andrew Ferguson and Laura Fry", "NextMeetingWith":"Nitla Cooke"},
{"Name":"Roebothan McKay Marshall (RMM)", "Id":"001I9000003c6huIAA", "LastLogin":"2026-08-27", "Owner":"Carla Chaytor", "Stage":"Customer", "Tier":"SMB", "ACV":36000.0, "Start":"2026-06-06", "End":"2027-06-06", "Cap":480000.0, "Pages":12937.0, "Hours":56.0074, "Users":37.0, "MainContact":"Ashley Francis", "LastEmail":"2026-08-27", "NextMeeting":None, "NextMeetingTitle":None, "NextMeetingWith":None},
{"Name":"SEA & Associates Medical Legal Consulting Inc", "Id":"001OL00000TtYQBYA3", "LastLogin":"2026-08-25", "Owner":"Carla Chaytor", "Stage":"Previous Customer", "Tier":"SMB", "ACV":24000.0, "Start":"2025-09-26", "End":"2026-09-25", "Cap":420000.0, "Pages":718.0, "Hours":0.2831, "Users":2.0, "MainContact":"Suzanne Arragg", "LastEmail":"2026-08-26", "NextMeeting":None, "NextMeetingTitle":None, "NextMeetingWith":None},
{"Name":"Sutton Special Risk", "Id":"001OL00000r94PIYAY", "LastLogin":"2026-09-01", "Owner":"Carla Chaytor", "Stage":"Prospect", "Tier":"SMB", "ACV":5000.0, "Start":"2026-08-10", "End":"2027-08-09", "Cap":30000.0, "Pages":747.0, "Hours":3.8094, "Users":3.0, "MainContact":"Ahad Imrit", "LastEmail":"2026-08-31", "NextMeeting":None, "NextMeetingTitle":None, "NextMeetingWith":None},
{"Name":"Tamming Law", "Id":"001I9000005T4eYIAS", "LastLogin":"2026-07-25", "Owner":"Carla Chaytor", "Stage":"Unqualifed", "Tier":"SMB", "ACV":9600.0, "Start":"2025-09-11", "End":"2026-09-10", "Cap":60000.0, "Pages":1777.0, "Hours":0.525, "Users":3.0, "MainContact":"Jessica Macinnes", "LastEmail":"2026-07-25", "NextMeeting":None, "NextMeetingTitle":None, "NextMeetingWith":None},
{"Name":"The Ivera Group", "Id":"001OL00000gAMVJYA4", "LastLogin":"2026-09-03", "Owner":"Carla Chaytor", "Stage":"Customer", "Tier":"SMB", "ACV":80000.0, "Start":"2026-03-23", "End":"2027-03-22", "Cap":800000.0, "Pages":4820.0, "Hours":4.4363, "Users":3.0, "MainContact":"Kristen Gruhler", "LastEmail":"2026-09-02", "NextMeeting":None, "NextMeetingTitle":None, "NextMeetingWith":None},
{"Name":"Tri-Star Health Management Group Inc.", "Id":"001I9000007CYHEIA4", "LastLogin":"2026-09-03", "Owner":"Travis Bailey", "Stage":"Customer", "Tier":"SMB", "ACV":19250.0, "Start":"2026-01-20", "End":"2027-01-20", "Cap":275000.0, "Pages":15268.0, "Hours":125.7069, "Users":15.0, "MainContact":"Nicole Galeotalanza", "LastEmail":"2026-09-03", "NextMeeting":None, "NextMeetingTitle":None, "NextMeetingWith":None},
{"Name":"Trillium Mutual Insurance Company", "Id":"001OL00000Q4fgjYAB", "LastLogin":"2026-09-18", "Owner":"Carla Chaytor", "Stage":"Customer", "Tier":"SMB", "ACV":7000.0, "Start":"2026-01-01", "End":"2027-01-01", "Cap":50000.0, "Pages":2423.0, "Hours":3.3544, "Users":2.0, "MainContact":"Christine Fizell", "LastEmail":"2026-08-13", "NextMeeting":"2026-09-18", "NextMeetingTitle":"SiftMed <> Trillium", "NextMeetingWith":"Nitla Cooke"},
{"Name":"TrueLine Medical Legal Consulting", "Id":"001OL00000UBUYBYA5", "LastLogin":"2026-07-27", "Owner":"Peter Moyse", "Stage":"Customer", "Tier":"SMB", "ACV":12000.0, "Start":"2026-06-01", "End":"2027-05-31", "Cap":120000.0, "Pages":0, "Hours":0, "Users":1.0, "MainContact":"Khaleela Umheni", "LastEmail":"2026-07-27", "NextMeeting":None, "NextMeetingTitle":None, "NextMeetingWith":None},
{"Name":"Viewpoint Medical Assessments", "Id":"0015f00000L4E4IAAV", "LastLogin":"2026-08-11", "Owner":"Travis Bailey", "Stage":"Previous Customer", "Tier":"SMB", "ACV":126000.0, "Start":"2025-09-01", "End":"2026-08-31", "Cap":3500000.0, "Pages":2537.0, "Hours":5.5825, "Users":12.0, "MainContact":"Melinda Popa", "LastEmail":"2026-08-11", "NextMeeting":None, "NextMeetingTitle":None, "NextMeetingWith":None},
{"Name":"Vocational Alternatives", "Id":"001OL00000byRmQYAU", "LastLogin":"2026-09-03", "Owner":"Carla Chaytor", "Stage":"Customer", "Tier":"SMB", "ACV":9900.0, "Start":"2026-03-10", "End":"2027-03-09", "Cap":90000.0, "Pages":1194.0, "Hours":2.2331, "Users":3.0, "MainContact":"Jeff Cohen", "LastEmail":"2026-07-15", "NextMeeting":None, "NextMeetingTitle":None, "NextMeetingWith":None},
{"Name":"Walnut Orchard Psychology Services", "Id":"001OL00000izh1xYAA", "LastLogin":"2026-06-23", "Owner":"Carla Chaytor", "Stage":"Customer", "Tier":"SMB", "ACV":12500.0, "Start":"2026-04-09", "End":"2027-04-08", "Cap":120000.0, "Pages":7185.0, "Hours":15.0877, "Users":2.0, "MainContact":"Shayna Nussbaum", "LastEmail":"2026-06-23", "NextMeeting":None, "NextMeetingTitle":None, "NextMeetingWith":None},
{"Name":"Zurich North America", "Id":"001I9000002tqUTIAY", "LastLogin":"2026-09-17", "Owner":"Travis Bailey", "Stage":"Customer", "Tier":"Enterprise", "ACV":88200.0, "Start":"2026-04-01", "End":"2028-03-31", "Cap":900000.0, "Pages":15055.0, "Hours":24.3754, "Users":48.0, "MainContact":"Ryan Gussak", "LastEmail":"2026-09-03", "NextMeeting":"2026-09-08", "NextMeetingTitle":"Siftmed x Zurich Weekly Sync", "NextMeetingWith":"Holly Hill, John Byrne, Michael King, Travis Bailey"},
{"Name":"iMPROve Health", "Id":"001OL00000Ncj26YAB", "LastLogin":"2026-09-17", "Owner":"Travis Bailey", "Stage":"Customer", "Tier":"SMB", "ACV":36960.0, "Start":"2025-09-15", "End":"2026-09-30", "Cap":336000.0, "Pages":581.0, "Hours":33.6665, "Users":9.0, "MainContact":"Leslie Howard", "LastEmail":"2026-09-02", "NextMeeting":"2026-09-17", "NextMeetingTitle":"iMPROve <> SiftMed: Quarterly Check-in", "NextMeetingWith":"Travis Bailey"}
]

SEVERITY_CODE = {"Critical": 0, "High": 1, "Watch": 2, "Healthy": 3, "Unknown": 4}


def parse(d):
    return datetime.date(*[int(x) for x in d.split("-")])


def prorated_monthly_cap(a):
    """The account's page cap divided by its contract term in months - an
    average monthly allowance, independent of calendar position. Returns
    None if it can't be computed (missing contract dates or a zero cap)."""
    if not a.get("Start") or not a.get("End") or not a.get("Cap"):
        return None
    start = parse(a["Start"])
    end = parse(a["End"])
    months = (end - start).days / 30.44
    if months <= 0 or a["Cap"] <= 0:
        return None
    cap = a["Cap"] / months
    return cap if cap > 0 else None


def compute_rows(accounts, today):
    """Computes a row for every account, not just ones under the 25% at-risk
    threshold. Severity is "Healthy" at/above 25% usage, or "Unknown" when a
    usage % can't be computed at all (missing contract dates or a zero cap).

    UsagePct here is Pages (Pages_Last_30__c, a true trailing 30-day rolling
    total - verified live against the raw Usage_data__c records) against the
    prorated monthly cap. This is a stable, always-current "how's usage been
    lately" read that needs no calendar-cycle awareness, which is why it's
    used for this main table and isn't the same figure as the mid-cycle
    Projected Usage table (see check_alerts.py), which deliberately tracks
    the real calendar month instead."""
    rows = []
    for a in accounts:
        prorated_cap = prorated_monthly_cap(a)
        usage_pct = (a["Pages"] / prorated_cap) * 100 if prorated_cap else None

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

        end = a.get("End")
        days_to_renewal = (parse(end) - today).days if end else None
        last_login = a.get("LastLogin")
        days_since_login = (today - parse(last_login)).days if last_login else None
        stage = a.get("Stage")
        stage_label = "{} ({})".format(stage, a["Tier"]) if stage == "Customer" and a.get("Tier") else stage
        rows.append({
            "Name": a["Name"], "Id": a["Id"], "Owner": a["Owner"], "Tier": a["Tier"], "Severity": sev,
            "Stage": stage, "StageLabel": stage_label,
            "UsagePct": (round(usage_pct, 1) if usage_pct is not None else None),
            "Pages": a["Pages"], "Hours": round(a["Hours"], 1),
            "Users": a["Users"], "ACV": a["ACV"], "Renewal": end, "Days": days_to_renewal,
            "LastLogin": last_login, "DaysSinceLogin": days_since_login,
            "MainContact": a.get("MainContact"),
            "LastEmail": a.get("LastEmail"), "NextMeeting": a.get("NextMeeting"),
            "NextMeetingTitle": a.get("NextMeetingTitle"), "NextMeetingWith": a.get("NextMeetingWith"),
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
        renewal_js = 'null' if f["Renewal"] is None else '"{}"'.format(f["Renewal"])
        days_js = 'null' if f["Days"] is None else f["Days"]
        main_contact = f.get("MainContact")
        main_contact_js = 'null' if not main_contact else '"{}"'.format(js_escape(main_contact))
        last_email = f.get("LastEmail")
        last_email_js = 'null' if not last_email else '"{}"'.format(last_email)
        next_meeting = f.get("NextMeeting")
        next_meeting_js = 'null' if not next_meeting else '"{}"'.format(next_meeting)
        next_meeting_title = f.get("NextMeetingTitle")
        next_meeting_title_js = 'null' if not next_meeting_title else '"{}"'.format(js_escape(next_meeting_title))
        next_meeting_with = f.get("NextMeetingWith")
        next_meeting_with_js = 'null' if not next_meeting_with else '"{}"'.format(js_escape(next_meeting_with))
        lines.append(
            '    {{name:"{name}", id:"{id}", owner:"{owner}", tier:"{tier}", stage:"{stage}", '
            'stageLabel:"{stage_label}", severity:{sev}, '
            'pct:{pct}, pages:{pages}, hours:{hours}, users:{users}, acv:{acv}, '
            'renewal:{renewal}, days:{days}, lastLogin:{last_login}, daysSinceLogin:{days_since_login}, '
            'mainContact:{main_contact}, lastEmail:{last_email}, nextMeeting:{next_meeting}, '
            'nextMeetingTitle:{next_meeting_title}, nextMeetingWith:{next_meeting_with}}},'.format(
                name=js_escape(f["Name"]),
                id=f["Id"],
                owner=js_escape(f["Owner"]),
                tier=f["Tier"],
                stage=js_escape(f["Stage"]),
                stage_label=js_escape(f["StageLabel"]),
                sev=SEVERITY_CODE[f["Severity"]],
                pct=pct_js,
                pages=f["Pages"],
                hours=f["Hours"],
                users=f["Users"],
                acv=(int(f["ACV"]) if float(f["ACV"]).is_integer() else f["ACV"]),
                renewal=renewal_js,
                days=days_js,
                last_login=last_login_js,
                days_since_login=days_since_login_js,
                main_contact=main_contact_js,
                last_email=last_email_js,
                next_meeting=next_meeting_js,
                next_meeting_title=next_meeting_title_js,
                next_meeting_with=next_meeting_with_js,
            )
        )
    return "\n".join(lines)


def cycle_position(today):
    """Returns (days_into_cycle, days_remaining, cycle_length_days) for the
    current calendar month. This is a real reset point for the month-to-date
    figures check_alerts.py sums straight from Usage_data__c (verified live
    2026-09-01: THIS_MONTH sums to 0 on the 1st) - it is NOT what Pages/
    Pages_Last_30__c track, which is a continuously rolling trailing-30-day
    total with no reset at all (verified live: LAST_N_DAYS:30 exactly
    matches the field). Only use this alongside month-to-date sums, not
    alongside UsagePct/Pages."""
    import calendar
    cycle_len = calendar.monthrange(today.year, today.month)[1]
    days_into = today.day
    return days_into, cycle_len - days_into, cycle_len


def render_projected_js(rows):
    lines = []
    for r in rows:
        pct_js = 'null' if r["pct"] is None else r["pct"]
        stage = r.get("stage") or r.get("tier")
        stage_label = r.get("stageLabel") or stage
        lines.append(
            '    {{name:"{name}", id:"{id}", tier:"{tier}", stage:"{stage}", stageLabel:"{stage_label}", '
            'pct:{pct}, acv:{acv}, '
            'daysIntoCycle:{days_into}, daysRemaining:{days_remaining}, cycleLen:{cycle_len}}},'.format(
                name=js_escape(r["name"]),
                id=r["id"],
                tier=r["tier"],
                stage=js_escape(stage),
                stage_label=js_escape(stage_label),
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

    renewing = [f for f in flagged if f["Days"] is not None and 0 <= f["Days"] <= 60]
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
