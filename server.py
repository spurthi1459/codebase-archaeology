from mcp.server.fastmcp import FastMCP

from git_tools import (
    get_blame,
    get_file_history,
    search_commit_messages,
    get_commit_diff,
    get_commit_diff_for_file,
)

mcp = FastMCP("codebase-archaeology")


@mcp.tool()
def blame_line(file_path: str, line_number: int) -> str:
    """Find who wrote a specific line, which commit changed it, and why based on the commit message."""

    result = get_blame(file_path, line_number)

    return str(result)


@mcp.tool()
def file_history(file_path: str) -> str:
    """Get the chronological commit history for a specific file (most recent
    10 commits).If the result includes a note that history was truncated,
    report the count as 'at least N', not as the total — do not state an
    exact total unless the tool confirms it saw the complete history. """

    result = get_file_history(file_path)

    return str(result)


@mcp.tool()
def search_commits(keyword: str) -> str:
    """Search commit messages across the entire repository for a keyword such as
    'fix', 'retry', or 'bug'.
    Use this for repo-wide topic or concept searches.
    DO NOT use this for finding changes to a specific known file; use file_history instead."""

    result = search_commit_messages(keyword)

    if not result:
        return (
            f"No commit messages mention '{keyword}'. Do not keep retrying similar "
            "keywords. If you know the file, use file_history; otherwise answer "
            "with what you have already found."
        )

    return str(result)


@mcp.tool()
def file_diff(commit_hash: str, file_path: str) -> str:
    """Get the diff for ONE specific file within a commit.
    PREFER this over commit_diff whenever you already know which file you care about
    (for example after calling file_history). It avoids unrelated changes from other
    files in the same commit. Summarize the key changes and intent in your answer;
    do not quote the raw diff back verbatim."""

    return get_commit_diff_for_file(commit_hash, file_path)


@mcp.tool()
def commit_diff(commit_hash: str) -> str:
    """Get the full diff of an entire commit, across ALL files.
    Use this only when you need the whole commit's context. If you know which file
    you care about, use file_diff instead. The diff may be large: summarize the key
    changes and intent in your answer, never quote the raw diff back verbatim."""

    return get_commit_diff(commit_hash)


if __name__ == "__main__":
    mcp.run(transport="stdio")