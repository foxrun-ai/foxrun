---
name: reminders
description: "Read and write Apple Reminders with the remindctl command: show today or overdue, search, add, edit, and complete reminders. Use when the person says what's on my reminders, remind me to, add a reminder, or mark that reminder done. Mac-only. remindctl is an Add-on."
kind: knowledge
---

# reminders

Show, add, change, and finish the person's Apple Reminders from the terminal.

**Add-on:** `remindctl`. Foxrun ships this skill, not the command.
The person installs it from the tool guide page `tools/cli/remindctl.md`.
**Mac-only:** yes. Reminders and `remindctl` exist only on macOS.

## Trigger phrases

`what's on my reminders` · `remind me to` · `add a reminder` · `mark that reminder done`

## Steps

1. Check the command and access.

   ```sh
   command -v remindctl && remindctl status
   ```

   Done when `status` shows Reminders access is granted.
   If the command is missing, tell the person it is an Add-on and give the tool page. Stop.
   If access is not granted, ask the person to run `remindctl authorize` and allow it. Stop until they do.

2. Read.

   | To | Run |
   |---|---|
   | Show today | `remindctl show today --json --no-input` |
   | Show overdue | `remindctl show overdue --json --no-input` |
   | Show one list | `remindctl show --list "<list>" --json --no-input` |
   | List the lists | `remindctl list --json --no-input` |
   | Search | `remindctl search "<words>" --json --no-input` |

   Done when the JSON parses. Report titles, due dates, and lists. Keep IDs for step 3.

3. Write only what the person asked for.

   | To | Run |
   |---|---|
   | Add | `remindctl add "<title>" --list "<list>" --due "<date>" --json --no-input` |
   | Edit | `remindctl edit <id> --due "<date>" --json --no-input` |
   | Complete | `remindctl complete <id> --dry-run`, then the same without `--dry-run` |

   Use the ID prefix from the read in step 2, not a list index. An index shifts when the list changes.
   Done when the command exits 0 and a read of the same reminder shows the change.

4. Report in one line: what changed, and the reminder's title and due date.
   Done when the person has the line.

## Gotchas

- A delete needs the person's yes to the exact reminder. Run `remindctl delete <id> --dry-run` first, show the result, then delete. Never add `--force` on your own.
- `--alarm` sets a notification. It does not turn on the Urgent flag; only the Reminders app can.
- With no list given, `add` uses the default list. Name the list when the person did.
- A due date the person gave in words, such as "Friday", goes in as a date string. Read it back in the report.
- For every flag, run `remindctl <command> --help`.
