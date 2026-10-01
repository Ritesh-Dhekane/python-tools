import json
import os
import subprocess
import sys
from datetime import datetime, timezone

DEFAULT_CONFIG = "config.json"
DEFAULT_DAYS = 14


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


def get_commits(repo_path, since_days):
    cmd = [
        "git", "-C", repo_path, "log",
        "--no-merges",
        f"--since={since_days} days ago",
        "--format=%H|||%ae|||%s",
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    commits = []
    for line in result.stdout.strip().splitlines():
        if "|||" not in line:
            continue
        parts = line.split("|||", 2)
        if len(parts) < 3:
            continue
        sha, author, msg = parts
        files = get_changed_files(repo_path, sha.strip())
        commits.append({
            "sha": sha.strip()[:10],
            "author": author.strip(),
            "message": msg.strip(),
            "files": files,
        })
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
    days = int(sys.argv[2]) if len(sys.argv) > 2 else DEFAULT_DAYS

    if not os.path.exists(config_path):
        print(f"Config not found: {config_path}")
        sys.exit(1)

    config = load_config(config_path)
    root = os.path.expanduser(config["root"])
    exclude = set(config.get("exclude_repos", []))

    repos = find_git_repos(root, exclude)
    print(f"Scanning {len(repos)} repo(s) — last {days} days, all authors...\n")

    output = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "days": days,
        "repos": [],
    }

    for repo_name, repo_path in repos:
        commits = get_commits(repo_path, days)
        if not commits:
            continue
        by_ticket = group_by_ticket(commits)
        output["repos"].append({
            "repo": repo_name,
            "commit_count": len(commits),
            "by_ticket": by_ticket,
        })
        tickets = ", ".join(by_ticket.keys())
        print(f"  {repo_name}: {len(commits)} commit(s) — {tickets}")

    if not output["repos"]:
        print("No commits found in the last {} days.".format(days))
        sys.exit(0)

    script_dir = os.path.dirname(os.path.abspath(__file__))
    temp_dir = os.path.join(script_dir, "temp")
    os.makedirs(temp_dir, exist_ok=True)

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_path = os.path.join(temp_dir, f"demo_log_{timestamp}.json")
    with open(out_path, "w") as f:
        json.dump(output, f, indent=2)

    print(f"\nSaved to: {out_path}")
    return out_path


if __name__ == "__main__":
    main()
