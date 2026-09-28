import git

REPO_PATH = r"D:\Projects\codebase-archaeology\test_repo"
SCAN_LIMIT = 20000   # how many commits search scans (was 500, which missed old commits)


def get_blame(file_path: str, line_number: int) -> dict:
    """Who last touched this specific line, and in which commit."""

    try:
        repo = git.Repo(REPO_PATH)

        blame_result = repo.blame("HEAD", file_path)

        current_line = 0

        for commit, lines in blame_result:
            for line in lines:
                current_line += 1

                if current_line == line_number:
                    return {
                        "commit": commit.hexsha[:8],
                        "author": commit.author.name,
                        "date": commit.committed_datetime.strftime(
                            "%Y-%m-%d"
                        ),
                        "message": commit.message.strip(),
                        "line_content": line,
                    }

        return {
            "error": f"Line {line_number} not found in '{file_path}'."
        }

    except git.exc.GitCommandError as e:
        return {
            "error": f"Git error: {str(e)}"
        }

    except Exception as e:
        return {
            "error": f"Unexpected error: {str(e)}"
        }


def get_file_history(
    file_path: str,
    max_commits: int = 10
) -> list[dict]:
    """Chronological list of commits that touched this file."""

    try:
        repo = git.Repo(REPO_PATH)

        # fetch one extra to detect whether there are more commits beyond the cap
        commits = list(
            repo.iter_commits(
                paths=file_path,
                max_count=max_commits + 1
            )
        )

        if not commits:
            return [
                {
                    "error": (
                        f"No commit history found for '{file_path}'. "
                        "Check the path is correct."
                    )
                }
            ]

        truncated = len(commits) > max_commits
        commits = commits[:max_commits]

        history = [
            {
                "commit": c.hexsha[:8],
                "author": c.author.name,
                "date": c.committed_datetime.strftime("%Y-%m-%d"),
                "message": c.message.strip().split("\n")[0],
            }
            for c in commits
        ]

        if truncated:
            history.append({
                "note": (
                    f"Showing only the {max_commits} most recent commits. "
                    f"This file has MORE than {max_commits} commits in total — "
                    "do not state this as the complete count."
                )
            })

        return history

    except git.exc.GitCommandError as e:
        return [{"error": f"Git error: {str(e)}"}]

    except Exception as e:
        return [{"error": f"Unexpected error: {str(e)}"}]


def search_commit_messages(
    keyword: str,
    max_results: int = 10
) -> list[dict]:
    """Find commits across the whole repo whose message mentions a keyword."""

    try:
        repo = git.Repo(REPO_PATH)

        matches = []

        for c in repo.iter_commits(max_count=SCAN_LIMIT):

            if keyword.lower() in c.message.lower():

                matches.append({
                    "commit": c.hexsha[:8],
                    "author": c.author.name,
                    "date": c.committed_datetime.strftime("%Y-%m-%d"),
                    "message": c.message.strip().split("\n")[0],
                })

                if len(matches) >= max_results:
                    break

        return matches

    except git.exc.GitCommandError as e:
        return [
            {
                "error": f"Git error: {str(e)}"
            }
        ]

    except Exception as e:
        return [
            {
                "error": f"Unexpected error: {str(e)}"
            }
        ]


def get_commit_diff(commit_hash: str) -> str:
    """Full diff introduced by a specific commit (all files)."""

    try:
        repo = git.Repo(REPO_PATH)

        repo.commit(commit_hash)

        diff = repo.git.show(
            commit_hash,
            "--stat",
            "-p"
        )

        if len(diff) > 1500:
            return diff[:1500] + "\n... (diff truncated)"

        return diff

    except git.exc.BadName:
        return (
            f"Error: Invalid commit hash '{commit_hash}'."
        )

    except git.exc.GitCommandError as e:
        return f"Git error: {str(e)}"

    except Exception as e:
        return f"Unexpected error: {str(e)}"


def get_commit_diff_for_file(commit_hash: str, file_path: str) -> str:
    """Diff for ONE file within a commit, not the whole commit."""

    try:
        repo = git.Repo(REPO_PATH)

        repo.commit(commit_hash)

        diff = repo.git.show(
            commit_hash,
            "--",
            file_path
        )

        if not diff.strip():
            return (
                f"No changes to '{file_path}' in commit {commit_hash}."
            )

        if len(diff) > 1500:
            return diff[:1500] + "\n... (diff truncated)"

        return diff

    except git.exc.BadName:
        return (
            f"Error: Invalid commit hash '{commit_hash}'."
        )

    except git.exc.GitCommandError as e:
        return f"Git error: {str(e)}"

    except Exception as e:
        return f"Unexpected error: {str(e)}"