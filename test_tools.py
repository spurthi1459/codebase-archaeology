# test_tools.py  (no Gemini calls, uses no quota)
import sys

from git_tools import (
    get_blame,
    get_file_history,
    search_commit_messages,
    get_commit_diff,
    get_commit_diff_for_file,
)

results = []


def check(name, condition):
    results.append(bool(condition))
    print(("PASS" if condition else "FAIL"), "-", name)


# --- file_history ---
history = get_file_history("setup.py")
check("file_history: newest commit for setup.py is 6d6d986f",
      history and history[0].get("commit") == "6d6d986f")
check("file_history: includes the Werkzeug commit de16718b",
      any(h.get("commit") == "de16718b" for h in history))

fake = get_file_history("totally_fake_file.py")
check("file_history: fake file returns an error entry, no crash",
      fake and "error" in fake[0])

# --- file_diff (scoped to one file) ---
diff = get_commit_diff_for_file("6d6d986f", "setup.py")
check("file_diff: shows setup.py was deleted", "deleted file mode" in diff)
check("file_diff: excludes unrelated files (.flake8)", ".flake8" not in diff)
check("file_diff: file not in commit gives a clear message",
      "No changes" in get_commit_diff_for_file("6d6d986f", "README.md")
      or "Error" in get_commit_diff_for_file("6d6d986f", "README.md"))

# --- commit_diff (whole commit) ---
full = get_commit_diff("6d6d986f")
check("commit_diff: whole commit mentions pyproject.toml", "pyproject.toml" in full)
check("commit_diff: output is capped", len(full) <= 1600)

# --- invalid input handling ---
check("commit_diff: invalid hash returns clean error",
      get_commit_diff("0000000").startswith("Error"))
check("file_diff: invalid hash returns clean error",
      get_commit_diff_for_file("0000000", "setup.py").startswith("Error"))

# --- search (this is the 500-commit cap check) ---
found = search_commit_messages("importlib", max_results=50)
check("search: reaches old commit 751d85f3 (Jan 2022)",
      any(r.get("commit") == "751d85f3" for r in found))
check("search: no-match keyword returns an empty list",
      search_commit_messages("zzzznotarealkeywordzzzz") == [])

# --- blame ---
blame = get_blame("pyproject.toml", 1)
check("blame: returns a commit for line 1 of pyproject.toml", "commit" in blame)
check("blame: nonexistent file returns an error dict",
      "error" in get_blame("totally_fake_file.py", 1))

# --- summary ---
print(f"\n{sum(results)}/{len(results)} passed")
sys.exit(0 if all(results) else 1)