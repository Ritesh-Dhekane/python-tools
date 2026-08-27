import json
import os
import subprocess
import sys
import tempfile
from datetime import datetime, timezone

DEFAULT_CONFIG = "config.json"


def load_config(path):
    with open(path) as f:
        return json.load(f)


def find_git_repos(root, exclude):
    repos = []
    for name in sorted(os.listdir(root)):
        if name in exclude:
            continue
        full = os.path.join(root, name)
        if os.path.isdir(full) and os.path.isdir(os.path.join(full, ".git")):
            repos.append((name, full))
    return repos


def get_commits(repo_path, author, since_hours):
    cmd = [
        "git", "-C", repo_path, "log",
        "--no-merges",
        f"--author={author}",
        f"--since={since_hours} hours ago",
        "--format=%H|||%s",
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    commits = []
    for line in result.stdout.strip().splitlines():
        if "|||" not in line:
            continue
        sha, msg = line.split("|||", 1)
        files = get_changed_files(repo_path, sha)
        commits.append({"sha": sha[:10], "message": msg.strip(), "files": files})
    return commits


def get_changed_files(repo_path, sha):
    cmd = ["git", "-C", repo_path, "diff-tree", "--no-commit-id", "-r", "--name-only", sha]
    result = subprocess.run(cmd, capture_output=True, text=True)
    return [f.strip() for f in result.stdout.strip().splitlines() if f.strip()]


def ticket_from_message(msg):
    import re
    match = re.match(r"(MTGS-\d+)", msg, re.IGNORECASE)
    return match.group(1).upper() if match else "NO-TICKET"


def group_by_ticket(commits):
    grouped = {}
    for c in commits:
        ticket = ticket_from_message(c["message"])
        grouped.setdefault(ticket, []).append(c)
    return grouped


def main():
    config_path = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_CONFIG
    if not os.path.exists(config_path):
        print(f"Config not found: {config_path}")
        sys.exit(1)

    config = load_config(config_path)
    root = os.path.expanduser(config["root"])
    exclude = set(config.get("exclude_repos", []))
    author = config.get("git_username", "")
    hours = config.get("hours", 24)

    if not author:
        print("git_username is required in config")
        sys.exit(1)

    repos = find_git_repos(root, exclude)
    print(f"Scanning {len(repos)} repo(s) for commits by '{author}' in the last {hours}h...\n")

    output = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "author": author,
        "hours": hours,
        "repos": []
    }

    for repo_name, repo_path in repos:
        commits = get_commits(repo_path, author, hours)
        if not commits:
            continue
        by_ticket = group_by_ticket(commits)
        output["repos"].append({
            "repo": repo_name,
            "commit_count": len(commits),
            "by_ticket": by_ticket
        })
        tickets = ", ".join(by_ticket.keys())
        print(f"  {repo_name}: {len(commits)} commit(s) — {tickets}")

    if not output["repos"]:
        print("No commits found.")
        sys.exit(0)

    script_dir = os.path.dirname(os.path.abspath(__file__))
    temp_dir = os.path.join(script_dir, "temp")
    os.makedirs(temp_dir, exist_ok=True)

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_path = os.path.join(temp_dir, f"commit_log_{timestamp}.json")
    with open(out_path, "w") as f:
        json.dump(output, f, indent=2)

    print(f"\nSaved to: {out_path}")
    print("Paste the contents of that file to Claude to generate your worklog.")


if __name__ == "__main__":
    main()
