# At-Risk Accounts Salesforce refresh pipeline

`generate.py` fills `template.html` with a computed at-risk-accounts snapshot and
writes the ready-to-deploy `AtRiskAccountsSnapshot_new.html`, which gets uploaded
to Salesforce as a Static Resource.

Methodology: flags real, paying customers (`Account.Stage__c = "Customer"`,
`Annual_Contract_Value__c > 0`) whose trailing 30-day usage (`Pages_Last_30__c`)
is under 25% of their contracted page cap (`PageCountCap__c`), prorated to each
account's actual contract length (`Active_Contract_Start_Date__c` to
`Subscription_End_Date__c`) instead of a flat 12-month assumption.

## Network access

`salesforce-network-access-setup.md` (in this repo) documents a
cloud-session network block against `siftmed.my.salesforce.com` that was hit by
an earlier session attempting the OAuth client-credentials flow needed to push
the Static Resource update via Salesforce's REST API.

As of this session (2026-08-31), that block is not present: a direct `curl` to
`https://siftmed.my.salesforce.com/services/oauth2/token` returns a real
Salesforce response (`invalid_client_id`, HTTP 400) rather than a connection-level
403 from the egress gateway, and the pre-connected read-only Salesforce MCP
(`Salesforce_Read_MCP_Test`) successfully authenticates and runs SOQL queries
against this org. So the environment's network allowlist already covers this
domain for this environment/session.

## What's still missing for the write path

Updating the Static Resource itself needs a client-credentials OAuth token
exchange against the org's Connected App (Consumer Key/Secret), which is a
**write** capability. The only Salesforce access wired into this session is the
read-only `Salesforce_Read_MCP_Test` MCP tool — there's no Consumer Key/Secret
(`credentials.rtf`) or the `claude/at-risk-accounts-connected-app-handoff.md`
handoff doc referenced by the setup guide anywhere in this repo or in the
connected Google Drive. Whoever has those needs to supply them (or run the
final REST `PATCH`/`POST` to the Static Resource themselves) to complete the
deploy step.

## Regenerating

```bash
python3 -c "
import generate
html, summary = generate.fill_template(open('template.html').read(), generate.accounts, generate.TODAY)
open('AtRiskAccountsSnapshot_new.html', 'w').write(html)
print(summary)
"
```

The `accounts` list in `generate.py` is a point-in-time pull from a live SOQL
query; refresh it before regenerating if the source data has moved.
