# Fixing the Salesforce network block in Claude Code

## What's going on

This work needs a cloud session to reach `siftmed.my.salesforce.com` so it can complete an OAuth (Open Authorization, the standard for letting an app get a token to call an API without your password) token exchange against Salesforce and then update a Static Resource through Salesforce's REST API (Application Programming Interface, the interface Salesforce exposes for programs to read and write data).

Every cloud session runs inside a "cloud environment" with its own outbound network allowlist. By default, that allowlist only covers package registries (npm, pip, and so on) and a few other common domains, not `siftmed.my.salesforce.com`. Every attempt so far has been rejected at that network layer (HTTP 403, meaning "forbidden", from the egress gateway) before it ever reached Salesforce.

The fix has to be made on the environment itself, from Claude Code on the web, not from inside a running session.

## Step-by-step: add the domain

1. Go to [claude.ai/code](https://claude.ai/code).
2. In the row above the message box, click the cloud icon that shows the current environment's name.
3. Hover over the environment you use for this work (likely named "Default" unless you created another one), and click the gear/settings icon that appears.
4. In the dialog that opens, find the **Network access** field. It's currently set to **Trusted** (the default: package registries and a short list of common domains only).
5. Change it to **Custom**.
6. In the **Allowed domains** box that appears, add:

   ```
   siftmed.my.salesforce.com
   ```

7. Check the box labeled **Also include default list of common package managers**, so you don't lose access to npm, pip, GitHub, and the other Trusted-level domains you're probably still relying on for everything else Claude Code does.
8. If any part of this project relies on Claude Code artifacts (the previewable HTML/Markdown/etc. pages Claude can publish), also add:

   ```
   *.frame.claudeusercontent.com
   ```

   Claude Code fetches artifact content from that domain, and leaves it out and artifacts stop loading in sessions that use this environment.
9. Save the dialog.

## The part that trips people up

Per Claude Code's own documentation, changing an environment's network access only takes effect for sessions that start after the change. Resuming an existing session, or continuing in a session that was already running, never re-reads the new setting. So after saving:

- Don't try to keep working in the same session that hit the block.
- Start a brand new session in Claude Code (in this same environment) to pick up the change.

Also worth double-checking: this environment setting lives on the specific environment shown in that cloud icon selector. If you (or your team) have more than one environment set up, make sure you're editing the same one the session doing this work is actually using, not a different one with a similar name.

## How to confirm it worked

In the new session, run this first, before anything else (it's also the first step in the handoff doc, `claude/at-risk-accounts-connected-app-handoff.md`, in the Salesforce project):

```bash
curl -s -w "\nHTTP_STATUS:%{http_code}\n" -X POST "https://siftmed.my.salesforce.com/services/oauth2/token" \
  -d "grant_type=client_credentials" \
  --data-urlencode "client_id=<Consumer Key from credentials.rtf>" \
  --data-urlencode "client_secret=<Consumer Secret from credentials.rtf>"
```

- If you still get a connection-level error (not a response from Salesforce at all), the environment change either didn't save or the new session isn't using the environment you edited. Check both.
- If Salesforce responds, even with an OAuth error in the body, the network layer is fixed. Any remaining issue at that point is in the Connected App's own configuration (scope, Run As user, IP relaxation), which is already documented as configured once in the handoff doc.
