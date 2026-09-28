# Codebase Archaeology — An MCP Agent for Git History Investigation

An agent that investigates a codebase's git history before answering questions about it, instead of only reading the current state of files. Built with the Model Context Protocol (MCP) and Google Gemini, with no agent framework (LangChain/CrewAI, etc.) — the tool-calling loop is hand-implemented to make the mechanics visible and debuggable.

## The problem

AI coding tools typically read only the current state of a file. They have no memory of *why* something was written a certain way, whether a piece of code has a history of bugs, or what a past refactor was trying to fix. This project gives an agent the ability to investigate history — blame, commit search, file history, diffs — and reason across multiple pieces of evidence before answering, rather than guessing from a single snapshot.

Example: asked "is it safe to change `setup.py`?", the agent checks the file's history, finds it was deleted in favor of `pyproject.toml`, and reports that the file doesn't exist anymore — instead of analyzing code that isn't there.

## Architecture

```
User question
      │
      ▼
┌─────────────────┐        JSON-RPC / stdio        ┌──────────────────┐
│  Gemini Agent    │ ─────────────────────────────► │   MCP Server      │
│  (agent.py)      │ ◄───────────────────────────── │   (server.py)      │
│                  │                                 │                    │
│ - decides which  │                                 │ - blame_line       │
│   tool to call   │                                 │ - file_history      │
│ - loops until it │                                 │ - search_commits     │
│   has enough     │                                 │ - file_diff          │
│   evidence       │                                 │ - commit_diff        │
└─────────────────┘                                 └──────────────────┘
                                                              │
                                                              ▼
                                                     ┌──────────────────┐
                                                     │  git_tools.py     │
                                                     │  (GitPython)      │
                                                     └──────────────────┘
```

The MCP server holds **no intelligence** — it's a pure data layer over git. All reasoning (which tool to call, when to stop investigating, how to synthesize an answer) lives in the Gemini agent. This separation is the core MCP idea: the server is a reusable capability; the agent is the decision-maker plugged into it.

## Tech stack

- **Python 3**
- **GitPython** — programmatic git access
- **`mcp` (FastMCP)** — official MCP server SDK
- **`google-genai`** — Gemini SDK (model: `gemini-3.5-flash-lite`)
- **No agent framework** — the MCP-to-Gemini tool-calling bridge and the investigation loop are ~150 lines of hand-written glue code, not hidden behind LangChain/CrewAI. This was a deliberate choice to keep every mechanism visible and explainable.

## The 5 tools

| Tool | Purpose |
|---|---|
| `blame_line` | Who last touched a specific line, and in which commit |
| `file_history` | Chronological commits touching a file (capped at 10, with an explicit truncation note — see Findings) |
| `search_commits` | Repo-wide keyword search across commit messages |
| `file_diff` | Diff for one file within a commit (avoids noise from unrelated files in the same commit) |
| `commit_diff` | Full diff of an entire commit, across all files |

Tool descriptions (docstrings) are the only information Gemini sees when deciding what to call — they were iterated on directly to steer tool selection (e.g. `file_diff`'s docstring tells the model to prefer it over `commit_diff` once a file is already known).

## Agent design

- **System prompt** enforces investigation discipline: use the fewest tool calls needed, don't retry near-synonym searches, always finish with a written answer, never invent commit hashes/authors/dates.
- **Step cap (8)** with tool calls forcibly disabled on the final step — this guarantees the agent always produces an answer instead of silently running out of steps.
- **Retry logic** distinguishes three failure types: daily quota errors (not retried — waiting won't help), transient API errors like 429/500/503 (retried with backoff), and network-level errors (retried separately).

## Evaluation

Tested against a real repository (Flask) with 15 questions, run 3 times each (45 total runs) to account for LLM non-determinism.

**Two separate question sets:**
- **10 development questions** — written while building and debugging the agent.
- **5 held-out questions** — written independently from raw `git log`/`git blame` output, without observing how the agent responds, specifically to avoid the eval being tuned to its own test cases. One of these targets `blame_line`, which no development question happened to exercise.

**Scoring checks three things per run:**
1. Did the agent call an appropriate tool for the question?
2. Does the answer contain the expected fact (commit hash, author, date, etc.)?
3. **Grounding check** — does the answer contain any commit-hash-looking string that never appeared in any tool's actual output? This catches fabrication that keyword matching alone would miss.

### Results

| Metric | Result |
|---|---|
| Tool selection correct | 45/45 |
| Answer correct | 45/45 |
| Runs with a fabricated (ungrounded) hash | 0/45 |
| Runs that hit the step cap without answering | 0/45 |
| Avg. tool calls per question | 2.6 |

## Findings

**1. A real bug, found and fixed through the eval — not assumed:**
`file_history` silently caps at 10 commits per file. On a file with more history than that, the agent reported "10 commits" as if it were the complete count. This is a real risk if the same overclaiming happened on a factual question like a file's total number of authors or its actual commit count. Initial score on the relevant question: **0/3**.

Fix: rather than trying to prompt around it (which is fragile), the tool itself was changed to fetch one commit beyond the cap and inject an explicit truncation note into its returned data when more history exists. This makes the model's response bounded by what it can actually see. After the fix: **3/3**, with the agent correctly saying "at least 10" instead of a bare count.

This is the finding I'd lead with in an interview: **tool-level fixes are more reliable than prompt-level fixes** for grounding problems, because they change what the model can see rather than hoping it behaves.

**2. Documented (not "fixed," because it isn't a bug) — short-hash resolution:**
Git resolves truncated commit hashes (e.g. `6d6d`) to their full form automatically when the prefix is unambiguous in the repository. This means a typo'd or accidentally shortened hash can silently return real data for the *wrong* commit if it happens to collide with a valid prefix, with no warning to the caller. Worth knowing if this pattern were ever extended to a repository where hash collisions are more likely.

## Known limitations

- `file_history` still hard-caps at 10 commits (now signaled explicitly, not silently hidden).
- The model is non-deterministic — repeated runs on identical questions occasionally used different tool sequences before converging on the same answer.
- Evaluated against one repository (Flask). Generalization to other codebases with different commit conventions is untested.
- Keyword-based answer scoring can't catch every kind of factual error — the grounding check only catches fabricated commit hashes specifically, not fabricated authors, dates, or explanations.

## Setup

```bash
git clone https://github.com/<your-username>/codebase-archaeology.git
cd codebase-archaeology

python -m venv venv
source venv/bin/activate  # Windows: venv\Scripts\activate
pip install -r requirements.txt
```

`.env` (create this file yourself — it's gitignored and never committed):
```
GEMINI_API_KEY=your-key-here
GEMINI_MODEL=gemini-3.5-flash-lite
```

This project needs a git repository to investigate. It was built and evaluated against Flask — clone it into `test_repo/`:

```bash
git clone https://github.com/pallets/flask.git test_repo
```

`REPO_PATH` in `git_tools.py` points at `test_repo` by default; change it to point at any other local git repository if you want to try a different codebase.

```bash
python test_tools.py       # unit tests for the git tool layer (no API calls, no quota used)
python agent.py             # run a single question interactively
python eval.py               # run the full 15-question evaluation suite (uses API quota)
python show_failures.py eval_results_gemini-3.5-flash-lite.json   # inspect any failing runs
python tool_usage.py eval_results_gemini-3.5-flash-lite.json      # confirm all 5 tools were exercised
```

## Project structure

```
git_tools.py      # git logic (GitPython), fully unit-tested independently of the LLM
server.py         # MCP server exposing git_tools as agent-callable tools
agent.py          # Gemini agent: tool-calling loop, retry logic, system prompt
eval.py           # evaluation harness: 15 questions × 3 runs, grounding checks
test_tools.py     # unit tests for git_tools.py (no API calls, no quota used)
show_failures.py  # inspect failing eval runs
tool_usage.py      # confirm every MCP tool is exercised by the eval
requirements.txt   # pinned dependencies
.gitignore          # excludes .env, venv/, test_repo/, __pycache__/, eval results
```

Note: `test_repo/`, `venv/`, `.env`, and saved eval result files are all gitignored — they're either regenerable, machine-specific, or secrets, and are not part of this repository.
