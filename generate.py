"""
Fills /home/claude/sf-refresh/template.html with freshly computed at-risk data
and writes out the final, ready-to-deploy HTML.

This is the "recompute from Salesforce directly" pipeline step. The `accounts`
list below was pulled live via SOQL against Salesforce on 2026-09-02:
Account.Stage__c IN ('Customer', 'SQL', 'Prospect') AND Annual_Contract_Value__c > 0,
selecting Name, Owner.Name, Stage__c, Account_Tier__c, Annual_Contract_Value__c,
Active_Contract_Start_Date__c, Subscription_End_Date__c, PageCountCap__c,
Pages_Last_30__c, Hours_Last_30__c, Active_Users_Last_30__c, LastActivityDate
(the "Last Login" column, despite its name). Widened from Stage__c = "Customer"
only on 2026-09-02 so SQL/Prospect deals already carrying usage and page-cap
data (e.g. Litco Law LSO) show up too, not just signed customers. MainContact
is derived per-account from summed Task+Event counts grouped by WhoId (via
each activity's WhatId = the Account itself); LastEmail is the most recent
ActivityDate among that account's TaskSubtype = 'Email' Tasks; NextMeeting is
the earliest future StartDateTime among that account's Events (both WhatId =
the Account) - null when there's no such record. In the scheduled job, this
list gets replaced by that same live SOQL/activity pull each run, and TODAY
becomes datetime.date.today() (already the case here).

Usage: python3 generate.py
Output: /home/claude/sf-refresh/AtRiskAccountsSnapshot_new.html
"""
import datetime
import json
import re

TODAY = datetime.date.today()

accounts = [
{"Name":"Alex Luczack MD", "Id":"001OL00000C5CzSYAV", "LastLogin":"2026-08-18", "Owner":"Carla Chaytor", "Stage":"Customer", "Tier":"Micro", "ACV":4000, "Start":"2026-07-01", "End":"2027-07-01", "Cap":55000, "Pages":2686, "Hours":21.1402, "Users":1, "MainContact":"Alex Luczack", "LastEmail":"2026-02-18", "NextMeeting":None},
{"Name":"ArthroBiologix Inc.", "Id":"001OL00000Ckjw6YAB", "LastLogin":"2026-08-19", "Owner":"Carla Chaytor", "Stage":"Customer", "Tier":"Micro", "ACV":10800, "Start":"2026-04-01", "End":"2027-03-31", "Cap":15000, "Pages":22218, "Hours":14.193, "Users":2, "MainContact":"Alex Rabinovich", "LastEmail":"2026-05-11", "NextMeeting":None},
{"Name":"AssessMed Inc.", "Id":"0015f00000IQRGHAA5", "LastLogin":"2026-09-01", "Owner":"Travis Bailey", "Stage":"Customer", "Tier":"Enterprise", "ACV":124000, "Start":"2026-06-01", "End":"2027-06-30", "Cap":3100000, "Pages":259832, "Hours":373.2954, "Users":27, "MainContact":"Kelly Costa", "LastEmail":"2026-05-01", "NextMeeting":None},
{"Name":"Assessnet", "Id":"001OL00000Xtpi4YAB", "LastLogin":"2026-08-11", "Owner":"Carla Chaytor", "Stage":"SQL", "Tier":"SMB", "ACV":18000, "Start":"2025-10-16", "End":"2026-10-15", "Cap":150000, "Pages":0, "Hours":0, "Users":0, "MainContact":"Joanne Dowd", "LastEmail":"2026-04-27", "NextMeeting":None},
{"Name":"Aua Consulting LLC", "Id":"001OL00000kV72oYAC", "LastLogin":"2026-07-17", "Owner":"Travis Bailey", "Stage":"Customer", "Tier":"Micro", "ACV":14000, "Start":"2026-06-08", "End":"2027-06-14", "Cap":80000, "Pages":12377, "Hours":4.9829, "Users":1, "MainContact":"Michael Schaufele", "LastEmail":"2026-05-06", "NextMeeting":None},
{"Name":"Boucher Medical Professional Corp.", "Id":"001OL0000087uk3YAA", "LastLogin":"2026-08-31", "Owner":"Carla Chaytor", "Stage":"Customer", "Tier":"Micro", "ACV":11746, "Start":"2025-03-21", "End":"2026-08-31", "Cap":275000, "Pages":20627, "Hours":102.1781, "Users":3, "MainContact":"Michael Boucher", "LastEmail":"2026-03-23", "NextMeeting":None},
{"Name":"Breedon Mor LLP", "Id":"001I9000005T4bZIAS", "LastLogin":"2026-08-11", "Owner":"Carla Chaytor", "Stage":"Customer", "Tier":"SMB", "ACV":15000, "Start":"2026-02-12", "End":"2027-02-12", "Cap":150000, "Pages":6336, "Hours":21.2149, "Users":6, "MainContact":"Jessica Mor", "LastEmail":"2026-02-09", "NextMeeting":None},
{"Name":"Buckeye Medical Legal Consulting", "Id":"001OL00000SHtnxYAD", "LastLogin":"2026-08-20", "Owner":"Carla Chaytor", "Stage":"SQL", "Tier":"Micro", "ACV":13200, "Start":"2025-11-07", "End":"2026-10-31", "Cap":120000, "Pages":1150, "Hours":3.3724, "Users":1, "MainContact":"Dan Bravard", "LastEmail":"2026-06-04", "NextMeeting":None},
{"Name":"Canadian Health Solutions Inc", "Id":"0015f00000IPHxuAAH", "LastLogin":"2026-09-08", "Owner":"Carla Chaytor", "Stage":"Customer", "Tier":"SMB", "ACV":20000, "Start":"2026-04-11", "End":"2027-04-10", "Cap":200000, "Pages":26758, "Hours":7.4509, "Users":26, "MainContact":"Allison Smith", "LastEmail":"2026-05-08", "NextMeeting":None},
{"Name":"Cayuga Mutual", "Id":"001OL00000VTlWPYA1", "LastLogin":"2026-08-06", "Owner":"Travis Bailey", "Stage":"Customer", "Tier":"SMB", "ACV":600, "Start":"2025-10-20", "End":"2026-10-19", "Cap":5000, "Pages":0, "Hours":0, "Users":0, "MainContact":"Paul Tiller", "LastEmail":"2026-04-23", "NextMeeting":None},
{"Name":"Chris Small Professional Medical Corporation", "Id":"001OL000008ibX8YAI", "LastLogin":"2026-08-11", "Owner":"Carla Chaytor", "Stage":"Customer", "Tier":"Micro", "ACV":4800, "Start":"2026-03-21", "End":"2027-03-21", "Cap":20000, "Pages":24, "Hours":0.8222, "Users":1, "MainContact":"Christopher Small", "LastEmail":"2026-03-05", "NextMeeting":None},
{"Name":"Crannie Law", "Id":"001I9000005T4dLIAS", "LastLogin":"2026-08-11", "Owner":"Carla Chaytor", "Stage":"Customer", "Tier":"SMB", "ACV":11896, "Start":"2026-05-11", "End":"2027-05-11", "Cap":125000, "Pages":3113, "Hours":51.2205, "Users":4, "MainContact":"Ruth Johnson", "LastEmail":"2026-08-11", "NextMeeting":None},
{"Name":"Curtis Hlushak", "Id":"001OL00000C4p0PYAR", "LastLogin":"2026-08-11", "Owner":"Carla Chaytor", "Stage":"Customer", "Tier":"Micro", "ACV":4500, "Start":"2026-02-23", "End":"2027-02-23", "Cap":30000, "Pages":2860, "Hours":7.2453, "Users":1, "MainContact":"Curtis Hlushak", "LastEmail":"2026-04-07", "NextMeeting":None},
{"Name":"Daugherty & Associates, LLC", "Id":"001OL00000SYxvHYAT", "LastLogin":"2026-08-18", "Owner":"Carla Chaytor", "Stage":"Customer", "Tier":"Micro", "ACV":8400, "Start":"2026-07-30", "End":"2027-07-29", "Cap":60000, "Pages":34, "Hours":66.1956, "Users":1, "MainContact":"Shirley Daugherty", "LastEmail":"2026-03-16", "NextMeeting":None},
{"Name":"Dr. Rick Hu", "Id":"001OL00000YiPK6YAN", "LastLogin":"2026-09-02", "Owner":"Carla Chaytor", "Stage":"SQL", "Tier":"Micro", "ACV":9600, "Start":"2025-10-09", "End":"2026-09-24", "Cap":120000, "Pages":3501, "Hours":25.2662, "Users":1, "MainContact":"Rick Hu", "LastEmail":"2026-05-04", "NextMeeting":None},
{"Name":"Dr. Yaacov Markus", "Id":"001OL00000p3vHKYAY", "LastLogin":"2026-08-24", "Owner":"Carla Chaytor", "Stage":"Prospect", "Tier":None, "ACV":13800, "Start":"2026-06-09", "End":"2027-06-30", "Cap":60000, "Pages":0, "Hours":0, "Users":0, "MainContact":"Yaacov Markus", "LastEmail":"2026-08-24", "NextMeeting":None},
{"Name":"E4 Life Care Planning, LLC", "Id":"001OL00000RHvTmYAL", "LastLogin":"2026-08-13", "Owner":"Travis Bailey", "Stage":"Prospect", "Tier":"Micro", "ACV":9618, "Start":"2026-07-28", "End":"2027-07-27", "Cap":60000, "Pages":148, "Hours":1.1007, "Users":1, "MainContact":"Alison Wohlhuter", "LastEmail":"2026-06-23", "NextMeeting":None},
{"Name":"Gateway Health Solutions Inc.", "Id":"001OL00000jFWbzYAG", "LastLogin":"2026-06-25", "Owner":"Peter Moyse", "Stage":"Prospect", "Tier":"Micro", "ACV":5998, "Start":None, "End":None, "Cap":None, "Pages":0, "Hours":0, "Users":1, "MainContact":"David Sheps", "LastEmail":"2026-03-24", "NextMeeting":None},
{"Name":"Girones Lawyers", "Id":"001I9000005T4a9IAC", "LastLogin":"2026-08-11", "Owner":"Carla Chaytor", "Stage":"Customer", "Tier":"SMB", "ACV":11188, "Start":"2026-05-12", "End":"2027-05-12", "Cap":100000, "Pages":0, "Hours":0, "Users":5, "MainContact":"Andrea Girones", "LastEmail":"2026-05-14", "NextMeeting":None},
{"Name":"Hands-On Orthopedics", "Id":"001OL00000dg8ynYAA", "LastLogin":"2026-06-30", "Owner":"Carla Chaytor", "Stage":"Customer", "Tier":"Micro", "ACV":14700, "Start":"2025-12-06", "End":"2026-12-05", "Cap":70000, "Pages":3335, "Hours":9.6283, "Users":4, "MainContact":"Ronald Williams", "LastEmail":"2026-02-19", "NextMeeting":None},
{"Name":"Hooper Law", "Id":"001I9000005T4bNIAS", "LastLogin":"2026-08-11", "Owner":"Carla Chaytor", "Stage":"Customer", "Tier":"SMB", "ACV":6000, "Start":"2026-08-01", "End":"2027-07-31", "Cap":50000, "Pages":9018, "Hours":8.3668, "Users":10, "MainContact":"Paige Thompson", "LastEmail":"2026-02-24", "NextMeeting":None},
{"Name":"IMED Services", "Id":"001OL00000Io5WoYAJ", "LastLogin":"2026-09-02", "Owner":"Carla Chaytor", "Stage":"Customer", "Tier":"SMB", "ACV":12000, "Start":"2026-05-21", "End":"2027-05-20", "Cap":60000, "Pages":4532, "Hours":67.2805, "Users":5, "MainContact":"John Byrne", "LastEmail":"2026-05-11", "NextMeeting":None},
{"Name":"Integral Consulting Services Inc.", "Id":"001I9000007cllGIAQ", "LastLogin":"2026-08-31", "Owner":"Travis Bailey", "Stage":"Customer", "Tier":"SMB", "ACV":121500, "Start":"2026-06-30", "End":"2027-06-30", "Cap":2000000, "Pages":92768, "Hours":94.6953, "Users":3, "MainContact":"Renee Madonna", "LastEmail":"2026-01-19", "NextMeeting":None},
{"Name":"Integrity Legal Nurse Consulting", "Id":"001OL00000UmhEIYAZ", "LastLogin":"2026-09-15", "Owner":"Travis Bailey", "Stage":"Customer", "Tier":"SMB", "ACV":9000, "Start":"2025-09-22", "End":"2026-09-21", "Cap":60000, "Pages":0, "Hours":0, "Users":16, "MainContact":"Wendy Votroubek", "LastEmail":"2026-04-17", "NextMeeting":None},
{"Name":"Integrity Medical Evaluations", "Id":"001OL00000AU6wgYAD", "LastLogin":"2026-09-02", "Owner":"Michael King", "Stage":"Customer", "Tier":"Enterprise", "ACV":158400, "Start":"2026-06-25", "End":"2027-08-31", "Cap":1440000, "Pages":2496, "Hours":3.707, "Users":1, "MainContact":"Tiffany Sparks", "LastEmail":"2026-08-07", "NextMeeting":None},
{"Name":"JHU Consulting", "Id":"001OL00000SYhk0YAD", "LastLogin":"2026-08-11", "Owner":"Carla Chaytor", "Stage":"Customer", "Tier":"Micro", "ACV":6600, "Start":"2026-01-30", "End":"2027-01-30", "Cap":30000, "Pages":2324, "Hours":3.1922, "Users":2, "MainContact":"Jessica Urie", "LastEmail":"2025-10-21", "NextMeeting":None},
{"Name":"JS Held - BioMechanics Group", "Id":"001OL000006SaZlYAK", "LastLogin":"2026-08-11", "Owner":"Carla Chaytor", "Stage":"Customer", "Tier":"SMB", "ACV":23061.75, "Start":"2026-01-08", "End":"2027-01-08", "Cap":125000, "Pages":2233, "Hours":18.2296, "Users":7, "MainContact":"Karla Cassidy", "LastEmail":None, "NextMeeting":None},
{"Name":"Jamie Irvine MD", "Id":"001OL00000D0AqjYAF", "LastLogin":"2026-08-11", "Owner":"Carla Chaytor", "Stage":"Customer", "Tier":"Micro", "ACV":9576, "Start":"2026-02-18", "End":"2027-02-18", "Cap":60000, "Pages":0, "Hours":0.31, "Users":1, "MainContact":"James Irvine", "LastEmail":None, "NextMeeting":None},
{"Name":"Janet Patterson MD", "Id":"001OL00000Czp9PYAR", "LastLogin":"2026-08-11", "Owner":"Carla Chaytor", "Stage":"Customer", "Tier":"Micro", "ACV":27700, "Start":"2026-06-30", "End":"2027-06-30", "Cap":400000, "Pages":34835, "Hours":47.3734, "Users":6, "MainContact":"Raquel Bean", "LastEmail":"2026-05-15", "NextMeeting":None},
{"Name":"KLE Nurse Consultants", "Id":"001OL00000XOkQ8YAL", "LastLogin":"2026-08-11", "Owner":"Carla Chaytor", "Stage":"Customer", "Tier":"Micro", "ACV":9000, "Start":"2025-09-15", "End":"2026-09-14", "Cap":60000, "Pages":2934, "Hours":2.8743, "Users":3, "MainContact":"Kelly Ehrhardt", "LastEmail":"2026-03-10", "NextMeeting":None},
{"Name":"Kenney Shelton Liptak Nowak - KSLN law", "Id":"001OL00000Q4KAsYAN", "LastLogin":"2027-04-01", "Owner":"Carla Chaytor", "Stage":"Customer", "Tier":"SMB", "ACV":41000, "Start":"2026-06-23", "End":"2027-06-23", "Cap":300000, "Pages":17106, "Hours":42.9013, "Users":21, "MainContact":"Janine Smith", "LastEmail":"2026-08-28", "NextMeeting":None},
{"Name":"Kevin Smith MD", "Id":"001OL00000D0B7IYAV", "LastLogin":"2026-08-11", "Owner":"Carla Chaytor", "Stage":"Customer", "Tier":"Micro", "ACV":9000, "Start":"2026-06-30", "End":"2027-06-30", "Cap":150000, "Pages":8429, "Hours":17.9728, "Users":5, "MainContact":"Kevin Smith", "LastEmail":"2026-02-26", "NextMeeting":None},
{"Name":"LCP Pro", "Id":"001OL00000i2nBOYAY", "LastLogin":"2026-09-02", "Owner":"Travis Bailey", "Stage":"Customer", "Tier":"SMB", "ACV":100000, "Start":"2026-05-22", "End":"2027-05-21", "Cap":950000, "Pages":156132, "Hours":344.0166, "Users":46, "MainContact":"Shelene Giles", "LastEmail":"2026-09-02", "NextMeeting":None},
{"Name":"Laxton Consulting, LLC", "Id":"001OL00000YdWpQYAV", "LastLogin":"2026-07-21", "Owner":"Carla Chaytor", "Stage":"Prospect", "Tier":"Micro", "ACV":9000, "Start":"2025-10-17", "End":"2026-10-17", "Cap":60000, "Pages":7215, "Hours":7.1035, "Users":1, "MainContact":"Theresa Laxton", "LastEmail":"2026-01-19", "NextMeeting":None},
{"Name":"Life Care Planning Solutions LLC", "Id":"001OL00000NseOJYAZ", "LastLogin":"2026-08-11", "Owner":"Travis Bailey", "Stage":"Customer", "Tier":"SMB", "ACV":8000, "Start":"2026-06-23", "End":"2027-06-23", "Cap":300000, "Pages":2266, "Hours":30.3813, "Users":8, "MainContact":"Jennifer Post", "LastEmail":"2026-05-04", "NextMeeting":None},
{"Name":"Litco Law LSO", "Id":"001I9000006SKfQIAW", "LastLogin":"2026-09-03", "Owner":"Travis Bailey", "Stage":"SQL", "Tier":"Enterprise", "ACV":62500, "Start":"2026-07-15", "End":"2027-07-14", "Cap":600000, "Pages":197, "Hours":7.8855, "Users":3, "MainContact":"Liz Detmold", "LastEmail":"2026-05-11", "NextMeeting":None},
{"Name":"Medical Vocational Planning (MVP)", "Id":"001OL00000A5GPoYAN", "LastLogin":"2026-10-28", "Owner":"Michael King", "Stage":"Customer", "Tier":"SMB", "ACV":115200, "Start":"2025-11-01", "End":"2027-12-01", "Cap":1440000, "Pages":15993, "Hours":50.0289, "Users":6, "MainContact":"Eva Sarkinen", "LastEmail":"2025-11-05", "NextMeeting":None},
{"Name":"Medivest", "Id":"001OL00000eL401YAC", "LastLogin":"2026-09-04", "Owner":"Travis Bailey", "Stage":"Customer", "Tier":"SMB", "ACV":100000, "Start":"2026-04-01", "End":"2027-03-31", "Cap":1000000, "Pages":140422, "Hours":104.8003, "Users":12, "MainContact":"Anna Childers", "LastEmail":"2026-08-06", "NextMeeting":None},
{"Name":"Mohamed Khaled MD", "Id":"001OL00000D0B7XYAV", "LastLogin":"2026-08-11", "Owner":"Carla Chaytor", "Stage":"Customer", "Tier":"Micro", "ACV":19349, "Start":"2025-09-03", "End":"2026-09-02", "Cap":192000, "Pages":149, "Hours":0.1033, "Users":1, "MainContact":"Mohamed Khaled", "LastEmail":"2025-10-14", "NextMeeting":None},
{"Name":"National Medical Reviews (NMR)", "Id":"001I9000007bWXNIA2", "LastLogin":"2026-08-25", "Owner":"Travis Bailey", "Stage":"Prospect", "Tier":"Enterprise", "ACV":350000, "Start":"2026-07-01", "End":"2027-06-30", "Cap":3500000, "Pages":6371, "Hours":11.2638, "Users":8, "MainContact":"Nicole Borror", "LastEmail":"2026-05-06", "NextMeeting":None},
{"Name":"North Toronto Surgical", "Id":"001OL00000SE68iYAD", "LastLogin":"2026-08-11", "Owner":"Carla Chaytor", "Stage":"Customer", "Tier":"Micro", "ACV":1920, "Start":"2026-06-03", "End":"2027-06-03", "Cap":24000, "Pages":0, "Hours":0, "Users":1, "MainContact":"Luis Figueroa", "LastEmail":"2026-03-10", "NextMeeting":None},
{"Name":"Northeast Life Care Planning", "Id":"001OL00000TANqiYAH", "LastLogin":"2026-08-18", "Owner":"Carla Chaytor", "Stage":"Customer", "Tier":"Micro", "ACV":9250, "Start":"2026-07-09", "End":"2027-07-08", "Cap":60000, "Pages":1326, "Hours":7.5536, "Users":1, "MainContact":"Barbara Bate", "LastEmail":"2026-02-19", "NextMeeting":None},
{"Name":"NuHaven Health", "Id":"001OL00000VI1ofYAD", "LastLogin":"2026-08-17", "Owner":"Carla Chaytor", "Stage":"Customer", "Tier":"SMB", "ACV":8100, "Start":"2025-09-22", "End":"2026-09-21", "Cap":90000, "Pages":2421, "Hours":10.0283, "Users":1, "MainContact":"Brad King", "LastEmail":"2026-01-20", "NextMeeting":None},
{"Name":"Orvosi Medical Management", "Id":"001OL00000BbZGdYAN", "LastLogin":"2026-08-31", "Owner":"Zackary Chaulk", "Stage":"Customer", "Tier":"SMB", "ACV":96000, "Start":"2026-01-09", "End":"2027-01-08", "Cap":1600000, "Pages":7847, "Hours":12.6401, "Users":7, "MainContact":"Rachel Stanga", "LastEmail":"2026-05-20", "NextMeeting":None},
{"Name":"Peel Mutual Insurance Company", "Id":"001I900000362wRIAQ", "LastLogin":"2026-09-28", "Owner":"Carla Chaytor", "Stage":"Customer", "Tier":"SMB", "ACV":5760, "Start":"2025-08-25", "End":"2026-08-24", "Cap":38400, "Pages":5525, "Hours":9.1041, "Users":10, "MainContact":"Daniel Heap", "LastEmail":"2026-03-06", "NextMeeting":None},
{"Name":"Physician Life Care Planning (PLCP)", "Id":"001OL00000KcO97YAF", "LastLogin":"2026-09-02", "Owner":"Nitla Cooke", "Stage":"Customer", "Tier":"SMB", "ACV":845000, "Start":"2025-11-07", "End":"2027-11-07", "Cap":6500000, "Pages":147958, "Hours":2410.6839, "Users":100, "MainContact":"Andres Martinez", "LastEmail":"2026-05-08", "NextMeeting":None},
{"Name":"Physiohealth Inc.", "Id":"001I9000004mawoIAA", "LastLogin":"2026-08-11", "Owner":"Carla Chaytor", "Stage":"Customer", "Tier":"Micro", "ACV":1500, "Start":"2026-05-15", "End":"2027-05-15", "Cap":120000, "Pages":15993, "Hours":12.1965, "Users":1, "MainContact":"Dennis Polygenis", "LastEmail":None, "NextMeeting":None},
{"Name":"Portage Mutual Insurance", "Id":"001OL00000SGW3tYAH", "LastLogin":"2026-08-11", "Owner":"Travis Bailey", "Stage":"Customer", "Tier":"SMB", "ACV":10200, "Start":"2026-01-07", "End":"2027-01-07", "Cap":60000, "Pages":2738, "Hours":8.7267, "Users":11, "MainContact":"Chaussie Lawson", "LastEmail":"2026-05-26", "NextMeeting":None},
{"Name":"PsycIME", "Id":"0015f00000WHoQUAA1", "LastLogin":"2026-09-01", "Owner":"Michael King", "Stage":"SQL", "Tier":"Enterprise", "ACV":105000, "Start":"2025-09-30", "End":"2027-09-30", "Cap":1500000, "Pages":51066, "Hours":119.8926, "Users":5, "MainContact":"Jacqueline Buck", "LastEmail":"2026-09-01", "NextMeeting":None},
{"Name":"Rehab First Inc.", "Id":"001OL00000Kf2yUYAR", "LastLogin":"2026-10-08", "Owner":"Carla Chaytor", "Stage":"Customer", "Tier":"SMB", "ACV":18000, "Start":"2025-11-03", "End":"2026-11-02", "Cap":180000, "Pages":15275, "Hours":9.6713, "Users":6, "MainContact":"Andrew Ferguson", "LastEmail":"2026-02-19", "NextMeeting":None},
{"Name":"Roebothan McKay Marshall (RMM)", "Id":"001I9000003c6huIAA", "LastLogin":"2026-08-27", "Owner":"Carla Chaytor", "Stage":"Customer", "Tier":"SMB", "ACV":36000, "Start":"2026-06-06", "End":"2027-06-06", "Cap":480000, "Pages":11890, "Hours":52.7138, "Users":37, "MainContact":"Ashley Francis", "LastEmail":"2026-06-15", "NextMeeting":None},
{"Name":"Sutton Special Risk", "Id":"001OL00000r94PIYAY", "LastLogin":"2026-09-01", "Owner":"Carla Chaytor", "Stage":"Prospect", "Tier":"SMB", "ACV":5000, "Start":"2026-08-10", "End":"2027-08-09", "Cap":30000, "Pages":747, "Hours":3.8094, "Users":3, "MainContact":None, "LastEmail":None, "NextMeeting":None},
{"Name":"The Ivera Group", "Id":"001OL00000gAMVJYA4", "LastLogin":"2026-09-02", "Owner":"Carla Chaytor", "Stage":"Customer", "Tier":"SMB", "ACV":80000, "Start":"2026-03-23", "End":"2027-03-22", "Cap":800000, "Pages":4820, "Hours":5.4733, "Users":3, "MainContact":"Kristen Gruhler", "LastEmail":"2026-03-13", "NextMeeting":None},
{"Name":"Tri-Star Health Management Group Inc.", "Id":"001I9000007CYHEIA4", "LastLogin":"2026-09-02", "Owner":"Travis Bailey", "Stage":"Customer", "Tier":"SMB", "ACV":19250, "Start":"2026-01-20", "End":"2027-01-20", "Cap":275000, "Pages":12195, "Hours":120.7742, "Users":15, "MainContact":"Nicole Galeotalanza", "LastEmail":"2026-05-25", "NextMeeting":None},
{"Name":"Trillium Mutual Insurance Company", "Id":"001OL00000Q4fgjYAB", "LastLogin":"2026-09-18", "Owner":"Carla Chaytor", "Stage":"Customer", "Tier":"SMB", "ACV":7000, "Start":"2026-01-01", "End":"2027-01-01", "Cap":50000, "Pages":2423, "Hours":3.3544, "Users":2, "MainContact":"Christine Fizell", "LastEmail":"2025-12-10", "NextMeeting":None},
{"Name":"TrueLine Medical Legal Consulting", "Id":"001OL00000UBUYBYA5", "LastLogin":"2026-07-27", "Owner":"Peter Moyse", "Stage":"Customer", "Tier":"SMB", "ACV":12000, "Start":"2026-06-01", "End":"2027-05-31", "Cap":120000, "Pages":0, "Hours":0, "Users":1, "MainContact":"Khaleela Umheni", "LastEmail":"2026-07-27", "NextMeeting":None},
{"Name":"Vocational Alternatives", "Id":"001OL00000byRmQYAU", "LastLogin":"2026-07-15", "Owner":"Carla Chaytor", "Stage":"Customer", "Tier":"SMB", "ACV":9900, "Start":"2026-03-10", "End":"2027-03-09", "Cap":90000, "Pages":1194, "Hours":0.9789, "Users":3, "MainContact":"Jeff Cohen", "LastEmail":"2026-05-25", "NextMeeting":None},
{"Name":"Walnut Orchard Psychology Services", "Id":"001OL00000izh1xYAA", "LastLogin":"2026-06-23", "Owner":"Carla Chaytor", "Stage":"Customer", "Tier":"SMB", "ACV":12500, "Start":"2026-04-09", "End":"2027-04-08", "Cap":120000, "Pages":7185, "Hours":16.8766, "Users":2, "MainContact":"Shayna Nussbaum", "LastEmail":"2026-06-23", "NextMeeting":None},
{"Name":"Zurich North America", "Id":"001I9000002tqUTIAY", "LastLogin":"2026-08-31", "Owner":"Travis Bailey", "Stage":"Customer", "Tier":"Enterprise", "ACV":88200, "Start":"2026-04-01", "End":"2028-03-31", "Cap":900000, "Pages":12175, "Hours":21.6125, "Users":48, "MainContact":"Ryan Gussak", "LastEmail":"2026-09-01", "NextMeeting":None},
{"Name":"iMPROve Health", "Id":"001OL00000Ncj26YAB", "LastLogin":"2026-09-17", "Owner":"Travis Bailey", "Stage":"Customer", "Tier":"SMB", "ACV":36960, "Start":"2025-09-15", "End":"2026-09-30", "Cap":336000, "Pages":581, "Hours":29.8478, "Users":9, "MainContact":"Leslie Howard", "LastEmail":"2026-05-07", "NextMeeting":None}
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
        lines.append(
            '    {{name:"{name}", id:"{id}", owner:"{owner}", tier:"{tier}", stage:"{stage}", '
            'stageLabel:"{stage_label}", severity:{sev}, '
            'pct:{pct}, pages:{pages}, hours:{hours}, users:{users}, acv:{acv}, '
            'renewal:{renewal}, days:{days}, lastLogin:{last_login}, daysSinceLogin:{days_since_login}, '
            'mainContact:{main_contact}, lastEmail:{last_email}, nextMeeting:{next_meeting}}},'.format(
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
