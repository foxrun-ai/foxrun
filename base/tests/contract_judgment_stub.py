#!/usr/bin/env python3
"""Stand-in for the Jev runner in tests. It calls no model.

Same call shape as the runner: --progress <answers file> <request file>.
It answers yes to a question when the section holds the marker for that question:
STUB-CONTRADICTION, STUB-FILLER, or STUB-INVENTED-TERM. A section with STUB-NO-ANSWER gets a failed line.
"""

from __future__ import annotations

import json
import sys

MARKERS = {"contradiction": "STUB-CONTRADICTION", "filler": "STUB-FILLER", "invented_term": "STUB-INVENTED-TERM"}


def main(argv: list[str]) -> int:
    if len(argv) != 3 or argv[0] != "--progress":
        print("usage: contract_judgment_stub.py --progress ANSWERS REQUEST", file=sys.stderr)
        return 2
    request = json.load(open(argv[2], encoding="utf-8"))
    failed = 0
    with open(argv[1], "a", encoding="utf-8") as stream:
        for item in request["requests"]:
            section = item["state"]["section"]
            if "STUB-NO-ANSWER" in section:
                failed += 1
                line = {"request_id": item["request_id"], "ok": False, "attempts": 1, "rate_limited": 0, "error": {"code": "provider_failed"}}
            else:
                answers = {name: {"type": "boolean", "probability": 0.9 if marker in section else 0.1} for name, marker in MARKERS.items()}
                line = {"request_id": item["request_id"], "ok": True, "attempts": 1, "rate_limited": 0, "result": {"request_id": item["request_id"], "answers": answers}}
            stream.write(json.dumps(line) + "\n")
    print(json.dumps({"ok": failed == 0, "action": "batch"}))
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
