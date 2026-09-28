import json
import sys
from collections import Counter

path = sys.argv[1] if len(sys.argv) > 1 else "eval_results.json"

with open(path) as f:
    rows = [r for r in json.load(f) if r["error"] is None]

counts = Counter(t for r in rows for t in r["tools_called"])
ALL_TOOLS = ["blame_line", "file_history", "search_commits", "file_diff", "commit_diff"]

print(f"Completed runs analyzed: {len(rows)}")
print("Tool usage across completed runs:")
for t in ALL_TOOLS:
    print(f"  {counts.get(t, 0):3}  {t}")

never = [t for t in ALL_TOOLS if counts.get(t, 0) == 0]
if never:
    print("\nNever exercised:", ", ".join(never))
else:
    print("\nAll tools exercised at least once.")