#!/usr/bin/env python3
"""Compare intraday vs close scan entry codes; exit 0 if worth notifying."""
from __future__ import annotations

import json
import sys
from pathlib import Path


def _entry_codes(path: Path) -> set[str]:
    data = json.loads(path.read_text())
    return {c["代码"] for c in data.get("candidates", []) if c.get("买点")}


def main() -> None:
    if len(sys.argv) != 3:
        print("usage: prepump_confirm_diff.py <intraday.json> <close.json>", file=sys.stderr)
        sys.exit(2)
    prev = _entry_codes(Path(sys.argv[1]))
    cur = _entry_codes(Path(sys.argv[2]))
    new = sorted(cur - prev)
    gone = sorted(prev - cur)
    if not new and not gone:
        sys.exit(1)
    print(json.dumps({"new": new, "gone": gone}, ensure_ascii=False))
    sys.exit(0)


if __name__ == "__main__":
    main()
