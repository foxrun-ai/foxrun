---
name: setup-browser-cookies
description: "Import browser cookies from a real Chromium browser into the headless browse session, so browse can test a logged-in site. Use when the person says import browser cookies, log in to the test site, or set up an authenticated session. Runs on the gstack browse engine, an Add-on."
kind: driving
---

# setup-browser-cookies

Copy logged-in sessions from the person's real Chromium browser into the headless browse session.
The `browse` skill then reaches pages behind a login without a password typed by the agent.

**Add-on:** the gstack browse engine, the same one as `browse`. Foxrun ships this skill, not the engine.
The person installs the engine from the tool guide page `tools/cli/gstack-browse.md`.
**Mac-only:** no. The engine reads cookies on macOS (Keychain) and Linux (libsecret).

## Trigger phrases

`import browser cookies` · `log in to the test site` · `set up an authenticated session`

## Steps

1. Find the engine with step 1 of the `browse` skill.
   Done when you have `READY: <path>` in `$B`.
   On `NO_ENGINE`, stop. Tell the person the gstack engine is an Add-on and give the install page.

2. Check if browse already uses the real browser.

   ```sh
   $B status 2>/dev/null | grep -q "Mode: cdp" && echo "CDP_MODE=true" || echo "CDP_MODE=false"
   ```

   With `CDP_MODE=true`, the real browser's sessions are already there. Say so and stop.
   Done when you know the mode.

3. Pick the domains.
   If the person named a domain, import it directly:

   ```sh
   $B cookie-import-browser <browser> --domain <domain>
   ```

   With no domain, open the picker: `$B cookie-import-browser`.
   The picker opens in the person's browser. They choose the domains, then tell you they are done.
   Done when the import command exits 0, or the person says the picker is done.

4. Verify.

   ```sh
   $B cookies
   ```

   Report the domains and the cookie count for each. Never print a cookie value.
   Done when each requested domain shows one or more cookies.

## Gotchas

- On macOS, the first import from a browser shows a Keychain prompt. The person clicks Allow. The agent never clicks it.
- Import only the domains the person named. Cookies are logins; more domains means more risk.
- The picker shows domain names and counts only. Keep it that way in the report.
- The headless session keeps cookies only while the engine runs, unless the person opts in to `BROWSE_PERSIST_STATE=1`.

## Stop

Close only the picker tab you opened.
Never import a domain the person did not name or pick.
