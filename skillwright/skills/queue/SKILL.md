---
type: note
workspace: system
timestamp: 2026-10-26T14:30:00-04:00
name: queue
description: "Queue worker results for review and report the count in a line: hold each finished result, and list them on request. Results are tasks in review and run folders with a result.md. Use for /queue, /queue list, or when someone asks what came back or what waits for review."
kind: knowledge
argument-hint: "[count | list] [workspace]"
---

# queue

Workers finish at different times. The queue holds their results so the person is not pulled out of the topic at hand.
Hold worker news until the topic is closed. Then report the count in one line.
The queue is a read. It never accepts, closes, or merges anything.

## Steps

1. **Count the results.** Set `<tracker>` as the `task` skill does. Run:
   `sqlite3 -readonly <tracker> "SELECT id,title,claimed_by FROM tasks WHERE status='in-review' ORDER BY id"`.
   Then list today's run results: `ls ~/.foxrun/runs/$(date +%Y-%m-%d)/*/result.md`.
   Done when you have both lists, or know each one is empty.
2. **Report the count.** One line: `Queue: <n> tasks in review, <m> run results today.` Done when the person has the line.
3. **List on request.** For `/queue list`, give one line per result: the id with its title, or the run folder with the first line of its `result.md`. Done when each result has one line.
4. **Hand on.** A result in review closes only through `task accept`, by a signer who did not do the work. Name who should review each one. Done when each result has a named next owner.

## Gotchas

- A worker's `result.md` is a claim until someone checks it. Do not repeat it as done.
- Do not interrupt the current topic to report a result, unless it changes that topic.
