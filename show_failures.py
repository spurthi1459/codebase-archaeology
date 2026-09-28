# show_failures.py
import json
import sys

path = sys.argv[1] if len(sys.argv) > 1 else "eval_results.json"

with open(path) as f:
    rows = json.load(f)

bad = [r for r in rows if r["error"] or not (r["tools_ok"] and r["answer_ok"])]

if not bad:
    print("No failures.")

for r in bad:
    print("-" * 70)
    print("Q:", r["question"][:70])
    print("run:", r["run"], "| steps:", r.get("steps"), "| hit_step_cap:", r.get("hit_step_cap"))
    print("error:", r["error"])
    print("tools_called:", r["tools_called"])
    print("answer:", (r["answer"] or "")[:400])