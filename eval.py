# eval.py
import asyncio
import json
import os
import re

from agent import run_agent, MODEL

RUNS_PER_QUESTION = 3
PAUSE_SECONDS = 15
RESULTS_FILE = f"eval_results_{MODEL}.json"

HASH_RE = re.compile(r"\b[0-9a-f]{7,40}\b")

TEST_CASES = [
    # ---- development set (10) ----
    {
        "question": "Find the commit that introduced a significant change to setup.py and show what changed.",
        "expected_tools_any": ["file_diff", "commit_diff"],
        "answer_contains_any": ["6d6d986f", "pyproject"],
    },
    {
        "question": "Who changed setup.py to require Werkzeug 2.2.2, and when?",
        "expected_tools_any": ["file_history", "search_commits"],
        "answer_contains_any": ["de16718b", "2022-08-08", "august 8, 2022", "8 august 2022"],
    },
    {
        "question": "Which commit switched the CLI from pkg_resources to importlib.metadata?",
        "expected_tools_any": ["search_commits", "file_history"],
        "answer_contains_any": ["751d85f3"],
    },
    {
        "question": "Check the file history for a file called totally_fake_file.py",
        "expected_tools_any": ["file_history"],
        "negative": True,
    },
    {
        "question": "Show me the diff for commit 0000000",
        "expected_tools_any": ["commit_diff", "file_diff"],
        "negative": True,
        "allowed_hashes": ("0000000",),
    },
    {
        "question": "Which commit removed setup.cfg, and what replaced it?",
        "expected_tools_any": ["commit_diff", "file_history", "file_diff", "search_commits"],
        "answer_contains_all": ["6d6d986f", "pyproject"],
    },
    {
        "question": "Who authored the commit that switched the CLI to importlib.metadata?",
        "expected_tools_any": ["search_commits", "file_history", "commit_diff"],
        "answer_contains_any": ["k900"],
    },
    {
        "question": "When was setup.py deleted from the repository?",
        "expected_tools_any": ["file_history", "file_diff", "commit_diff"],
        "answer_contains_any": ["2023-01-18", "january 18, 2023", "18 january 2023", "jan 18, 2023"],
    },
    {
        "question": "Is it safe to change setup.py?",
        "expected_tools_any": ["file_history"],
        "answer_contains_any": ["deleted", "removed", "no longer exist", "does not exist", "doesn't exist"],
    },
    {
        "question": "In one sentence, what does git blame do?",
        "expect_no_tools": True,
    },
    # ---- held-out set (5) — written and answer-keyed against git independently ----
    {
        "question": "Who last changed line 1 of pyproject.toml, and in which commit?",
        "expected_tools_any": ["blame_line"],
        "answer_contains_any": ["6d6d986f"],
    },
    {
        "question": "Who made the most recent change to src/flask/cli.py, and what kind of change was it?",
        "expected_tools_any": ["file_history"],
        "answer_contains_any": ["6a2f545b", "david lord"],
    },
    {
        "question": "How many commits have touched src/flask/json/__init__.py?",
        "expected_tools_any": ["file_history"],
        "answer_contains_any": ["at least 10", "at least ten", "more than 10", "over 10", "10 or more", "10+"],
    },
    {
    "question": "Get the commit diff for the hash '6d6d', treating it as a commit reference, not a file path.",
    "expected_tools_any": ["commit_diff", "file_diff"],
    "answer_contains_any": ["6d6d986f"],
    },
    {
        "question": "Why was the merge commit 6a2f545b made to src/flask/cli.py — what does the commit message say?",
        "expected_tools_any": ["file_history", "commit_diff"],
        "answer_contains_any": ["merge", "stable"],
    },
]


def looks_like_hash(s: str) -> bool:
    """Real hashes mix digits and letters; this skips words like 'defaced'."""
    return any(c.isdigit() for c in s) and any(c.isalpha() for c in s)


def invented_hash(answer: str, allowed: tuple = ()) -> bool:
    """True if the answer contains a commit-looking hash we did not expect."""
    return any(
        looks_like_hash(h) and h not in allowed
        for h in HASH_RE.findall(answer.lower())
    )


def ungrounded_hashes(answer: str, tool_results: list) -> list:
    """Hash-like strings in the answer that never appeared in any tool output."""
    haystack = " ".join(tool_results).lower()
    return [
        h for h in HASH_RE.findall(answer.lower())
        if looks_like_hash(h) and h not in haystack
    ]


def score(case: dict, result: dict) -> tuple[bool, bool, list]:
    called = [c["tool"] for c in result["tools_called"]]
    answer = result["answer"].lower()
    ungrounded = ungrounded_hashes(answer, result.get("tool_results", []))

    if case.get("expect_no_tools"):
        # a question the agent should answer directly, without investigating
        tools_ok = len(called) == 0
        answer_ok = tools_ok and bool(answer.strip())
    else:
        tools_ok = any(t in called for t in case["expected_tools_any"])
        if case.get("negative"):
            # correct behaviour: call the tool and don't fabricate a commit
            allowed = tuple(case.get("allowed_hashes", ()))
            answer_ok = tools_ok and not invented_hash(answer, allowed)
        elif "answer_contains_all" in case:
            answer_ok = all(s.lower() in answer for s in case["answer_contains_all"])
        else:
            answer_ok = any(s.lower() in answer for s in case["answer_contains_any"])

    # an answer containing a hash that no tool returned is never correct
    answer_ok = answer_ok and not ungrounded
    return tools_ok, answer_ok, ungrounded


def root_causes(e: BaseException) -> list:
    """Unwrap ExceptionGroups (what anyio/MCP wraps errors in) to the real errors."""
    if hasattr(e, "exceptions"):
        found = []
        for sub in e.exceptions:
            found.extend(root_causes(sub))
        return found
    return [e]


def load_clean_rows() -> list:
    """Keep only runs from earlier attempts that completed without error."""
    if not os.path.exists(RESULTS_FILE):
        return []
    with open(RESULTS_FILE) as f:
        return [r for r in json.load(f) if r["error"] is None]


def save_rows(rows: list) -> None:
    with open(RESULTS_FILE, "w") as f:
        json.dump(rows, f, indent=2)


async def main():
    print(f"Model: {MODEL}")
    rows = load_clean_rows()
    done = {(r["question"], r["run"]) for r in rows}
    if done:
        print(f"Resuming: {len(done)} completed runs already saved in {RESULTS_FILE}")

    quota_errors_in_a_row = 0
    stopped_early = False

    for case in TEST_CASES:
        if stopped_early:
            break
        for run in range(1, RUNS_PER_QUESTION + 1):
            if (case["question"], run) in done:
                continue

            error = None
            try:
                result = await run_agent(case["question"], verbose=False)
                tools_ok, answer_ok, ungrounded = score(case, result)
            except Exception as e:
                result = {"tools_called": [], "answer": ""}
                tools_ok, answer_ok, ungrounded = False, False, []
                error = "; ".join(f"{type(x).__name__}: {x}" for x in root_causes(e))

            rows.append({
                "model": MODEL,
                "question": case["question"],
                "run": run,
                "tools_called": [c["tool"] for c in result["tools_called"]],
                "tools_ok": tools_ok,
                "answer_ok": answer_ok,
                "ungrounded_hashes": ungrounded,
                "error": error,
                "answer": result["answer"],
                "steps": result.get("steps"),
                "hit_step_cap": result.get("hit_step_cap"),
            })
            save_rows(rows)   # save after EVERY run so nothing is lost on interrupt

            status = "CRASH" if error else f"tools={tools_ok} answer={answer_ok}"
            print(f"{case['question'][:50]}... run {run}: {status}")

            if error and ("429" in error or "RESOURCE_EXHAUSTED" in error):
                quota_errors_in_a_row += 1
            else:
                quota_errors_in_a_row = 0

            if quota_errors_in_a_row >= 2:
                print("\nStopping early: two quota errors in a row. "
                      "Fix quota, then rerun; finished runs are kept.")
                stopped_early = True
                break

            await asyncio.sleep(PAUSE_SECONDS)

    clean = [r for r in rows if r["error"] is None]
    print(f"\nModel: {MODEL}")
    print(f"Completed runs:              {len(clean)}")

    if clean:
        n = len(clean)
        print(f"Tool selection correct:      {sum(r['tools_ok'] for r in clean)}/{n}")
        print(f"Answer correct:              {sum(r['answer_ok'] for r in clean)}/{n}")
        print(f"Runs with ungrounded hashes: {sum(1 for r in clean if r.get('ungrounded_hashes'))}/{n}")

        capped = sum(1 for r in clean if r.get("hit_step_cap"))
        steps = [r["steps"] for r in clean if r.get("steps")]
        print(f"Hit step cap:                {capped}/{n}")
        if steps:
            print(f"Avg steps per run:           {sum(steps) / len(steps):.1f}")

        print("\nPer question (answer correct / completed):")
        for case in TEST_CASES:
            qrows = [r for r in clean if r["question"] == case["question"]]
            if qrows:
                ok = sum(r["answer_ok"] for r in qrows)
                print(f"  {ok}/{len(qrows)}  {case['question'][:60]}")


if __name__ == "__main__":
    asyncio.run(main())