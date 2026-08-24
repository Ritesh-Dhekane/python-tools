#!/usr/bin/env python3
"""
Copyright Ritesh Dhekane, 2026, v3.0

Sync every git repo under a root folder onto a target branch.

For each immediate subfolder of --root that is a git repo:
  - fetch from its remote
  - if the working tree is clean and has no unpushed commits, checkout the
    target branch (creating a tracking branch if needed) and pull it
  - if the repo is dirty (uncommitted changes and/or unpushed commits),
    leave it alone during the automatic pass and offer an interactive
    menu (stash / stash+pull+pop / show diff / skip / apply-to-all) once
    the automatic pass is done.

Reads defaults from config.json next to this script if present (see
config.example.json for the format). CLI args override the config file,
which overrides built-in defaults.

Usage:
    python3 sync_repos.py [--root PATH] [--branch release/dev] [--dry-run]
"""

import argparse
import json
import os
import subprocess
import sys
from dataclasses import dataclass, field
from datetime import datetime

CONFIG_FILENAME = "config.json"


# ---------------------------------------------------------------------------
# small terminal color helpers (no-op if output isn't a tty)
# ---------------------------------------------------------------------------

USE_COLOR = sys.stdout.isatty() and os.environ.get("NO_COLOR") is None


def _c(code, text):
    if not USE_COLOR:
        return text
    return f"\033[{code}m{text}\033[0m"


def green(text):
    return _c("32", text)


def red(text):
    return _c("31", text)


def yellow(text):
    return _c("33", text)


def cyan(text):
    return _c("36", text)


def bold(text):
    return _c("1", text)


# ---------------------------------------------------------------------------
# git helpers
# ---------------------------------------------------------------------------

class GitError(Exception):
    pass


def run_git(repo_path, args, check=True):
    result = subprocess.run(
        ["git", *args],
        cwd=repo_path,
        capture_output=True,
        text=True,
    )
    if check and result.returncode != 0:
        raise GitError(result.stderr.strip() or result.stdout.strip())
    return result


def is_git_repo(path):
    return os.path.exists(os.path.join(path, ".git"))


def get_remote_name(repo_path):
    result = run_git(repo_path, ["remote"], check=False)
    remotes = [line.strip() for line in result.stdout.splitlines() if line.strip()]
    if not remotes:
        return None
    return "origin" if "origin" in remotes else remotes[0]


def get_current_branch(repo_path):
    result = run_git(repo_path, ["symbolic-ref", "--short", "-q", "HEAD"], check=False)
    if result.returncode == 0:
        return result.stdout.strip()
    # detached HEAD
    short_sha = run_git(repo_path, ["rev-parse", "--short", "HEAD"], check=False)
    return f"DETACHED@{short_sha.stdout.strip()}"


def get_working_tree_status(repo_path):
    """Return list of (code, filename) for tracked/staged/untracked changes."""
    result = run_git(repo_path, ["status", "--porcelain"], check=False)
    entries = []
    for line in result.stdout.splitlines():
        if not line:
            continue
        entries.append((line[:2], line[3:]))
    return entries


def get_ahead_count(repo_path):
    """Ahead-of-upstream count for the current branch, or None if no upstream."""
    upstream = run_git(
        repo_path,
        ["rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{u}"],
        check=False,
    )
    if upstream.returncode != 0:
        return None
    counts = run_git(
        repo_path,
        ["rev-list", "--left-right", "--count", "@{u}...HEAD"],
        check=False,
    )
    if counts.returncode != 0:
        return None
    parts = counts.stdout.split()
    if len(parts) != 2:
        return None
    return int(parts[1])  # ahead count


def local_branch_exists(repo_path, branch):
    result = run_git(repo_path, ["show-ref", "--verify", "--quiet", f"refs/heads/{branch}"], check=False)
    return result.returncode == 0


def remote_branch_exists(repo_path, remote, branch):
    if remote is None:
        return False
    result = run_git(
        repo_path,
        ["show-ref", "--verify", "--quiet", f"refs/remotes/{remote}/{branch}"],
        check=False,
    )
    return result.returncode == 0


# ---------------------------------------------------------------------------
# repo status model
# ---------------------------------------------------------------------------

@dataclass
class RepoStatus:
    name: str
    path: str
    remote: str = None
    starting_branch: str = None
    working_tree_changes: list = field(default_factory=list)
    ahead_count: int = None
    branch_exists_locally: bool = False
    branch_exists_remotely: bool = False
    error: str = None
    action: str = None  # what happened / will happen, for the summary
    up_to_date: bool = None  # set after a real (non-dry-run) pull succeeds

    @property
    def has_working_tree_changes(self):
        return len(self.working_tree_changes) > 0

    @property
    def is_ahead(self):
        return bool(self.ahead_count)

    @property
    def is_dirty(self):
        return self.has_working_tree_changes or self.is_ahead

    def dirty_summary(self):
        parts = []
        if self.working_tree_changes:
            parts.append(f"{len(self.working_tree_changes)} changed file(s)")
        if self.is_ahead:
            parts.append(f"{self.ahead_count} commit(s) ahead of upstream")
        return ", ".join(parts) if parts else "clean"


def inspect_repo(repo_path, branch):
    name = os.path.basename(repo_path.rstrip("/"))
    status = RepoStatus(name=name, path=repo_path)
    try:
        status.remote = get_remote_name(repo_path)
        if status.remote:
            run_git(repo_path, ["fetch", status.remote, "--prune"])
        status.starting_branch = get_current_branch(repo_path)
        status.working_tree_changes = get_working_tree_status(repo_path)
        status.ahead_count = get_ahead_count(repo_path)
        status.branch_exists_locally = local_branch_exists(repo_path, branch)
        status.branch_exists_remotely = remote_branch_exists(repo_path, status.remote, branch)
    except GitError as exc:
        status.error = str(exc)
    return status


# ---------------------------------------------------------------------------
# actions
# ---------------------------------------------------------------------------

def checkout_target_branch(repo_path, branch, status, dry_run):
    if status.starting_branch == branch:
        return True
    if status.branch_exists_locally:
        cmd = ["checkout", branch]
    elif status.branch_exists_remotely:
        cmd = ["checkout", "-b", branch, "--track", f"{status.remote}/{branch}"]
    else:
        status.action = red(f"branch '{branch}' not found locally or on remote")
        return False

    if dry_run:
        print(cyan(f"  [dry-run] would run: git {' '.join(cmd)}"))
        return True

    try:
        run_git(repo_path, cmd)
        return True
    except GitError as exc:
        status.action = red(f"checkout failed: {exc}")
        return False


def pull_branch(repo_path, status, dry_run):
    if dry_run:
        print(cyan("  [dry-run] would run: git pull --ff-only"))
        return True
    try:
        before_sha = run_git(repo_path, ["rev-parse", "HEAD"]).stdout.strip()
        result = run_git(repo_path, ["pull", "--ff-only"], check=False)
        if result.returncode != 0:
            status.action = yellow(f"checked out but pull failed (diverged?): {result.stderr.strip()}")
            return False
        after_sha = run_git(repo_path, ["rev-parse", "HEAD"]).stdout.strip()
        status.up_to_date = before_sha == after_sha
        return True
    except GitError as exc:
        status.action = red(f"pull failed: {exc}")
        return False


def sync_note(status, dry_run):
    if dry_run:
        return "dry-run"
    return "already up to date" if status.up_to_date else "pulled new commits"


def sync_clean_repo(repo_path, branch, status, dry_run):
    if not checkout_target_branch(repo_path, branch, status, dry_run):
        return
    if status.remote is None:
        status.action = yellow("no remote configured, checked out only")
        return
    if pull_branch(repo_path, status, dry_run):
        status.action = green(f"synced to '{branch}' ({sync_note(status, dry_run)})")


def stash_changes(repo_path, dry_run):
    message = f"auto-sync before checkout {datetime.now().isoformat(timespec='seconds')}"
    if dry_run:
        print(cyan(f"  [dry-run] would run: git stash push -u -m \"{message}\""))
        return True
    try:
        run_git(repo_path, ["stash", "push", "-u", "-m", message])
        return True
    except GitError as exc:
        print(red(f"  stash failed: {exc}"))
        return False


def stash_pop(repo_path, dry_run):
    if dry_run:
        print(cyan("  [dry-run] would run: git stash pop"))
        return True
    result = run_git(repo_path, ["stash", "pop"], check=False)
    if result.returncode != 0:
        print(red(f"  stash pop failed (left stashed): {result.stderr.strip()}"))
        return False
    return True


# ---------------------------------------------------------------------------
# interactive menu for dirty repos
# ---------------------------------------------------------------------------

def show_diff(repo_path):
    result = run_git(repo_path, ["status", "--short"], check=False)
    print(result.stdout or "  (no working tree changes)")
    result = run_git(repo_path, ["diff", "--stat"], check=False)
    if result.stdout.strip():
        print(result.stdout)


def prompt_menu(status, has_working_tree_changes):
    print(f"\n{bold(status.name)} ({status.path})")
    print(f"  branch: {status.starting_branch}  |  {status.dirty_summary()}")
    options = []
    if has_working_tree_changes:
        options.append(("stash", "Stash changes, then checkout + pull"))
        options.append(("stash-pop", "Stash, checkout + pull, then pop stash back"))
        options.append(("diff", "Show diff / status"))
    else:
        options.append(("proceed", "Proceed anyway (ahead commits stay reachable via branch/reflog)"))
    options.append(("skip", "Skip this repo"))
    options.append(("all", "Apply this choice to all remaining dirty repos"))

    for idx, (_, label) in enumerate(options, start=1):
        print(f"  {idx}. {label}")

    while True:
        try:
            choice = input("  choose an option: ").strip()
        except (EOFError, KeyboardInterrupt):
            print(yellow("\n  no input available, skipping this repo"))
            return "skip"
        if choice.isdigit() and 1 <= int(choice) <= len(options):
            return options[int(choice) - 1][0]
        print("  invalid choice, try again")


def handle_dirty_repo(status, branch, action, dry_run):
    """Execute a resolved action ('stash' | 'stash-pop' | 'proceed' | 'skip') for one repo."""
    repo_path = status.path
    if action == "skip":
        status.action = yellow("skipped (left dirty)")
        return

    if action in ("stash", "stash-pop") and status.has_working_tree_changes:
        if not stash_changes(repo_path, dry_run):
            status.action = red("stash failed, left untouched")
            return

    if not checkout_target_branch(repo_path, branch, status, dry_run):
        return
    if status.remote is None:
        status.action = yellow("no remote configured, checked out only")
        return
    if not pull_branch(repo_path, status, dry_run):
        return

    note = sync_note(status, dry_run)
    if action == "stash-pop" and status.has_working_tree_changes:
        if stash_pop(repo_path, dry_run):
            status.action = green(f"synced ({note}) + stash popped")
        else:
            status.action = yellow(f"synced ({note}), stash left in stash list (pop conflict)")
    elif action == "stash":
        status.action = yellow(f"synced ({note}), changes left in stash list (run `git stash pop` manually)")
    else:
        status.action = green(f"synced to '{branch}' ({note}, ahead commits remain in reflog)")


def run_interactive_pass(dirty_statuses, branch, dry_run):
    if not dirty_statuses:
        return
    print(bold(f"\n{len(dirty_statuses)} repo(s) need attention:"))
    forced_action = None
    for status in dirty_statuses:
        if status.error:
            continue
        has_wt_changes = status.has_working_tree_changes
        if forced_action is not None:
            action = forced_action
            print(f"\n{bold(status.name)}: applying '{action}' (from apply-to-all)")
        else:
            while True:
                action = prompt_menu(status, has_wt_changes)
                if action == "diff":
                    show_diff(status.path)
                    continue
                break
            if action == "all":
                # ask which action to apply, since "all" itself isn't an action
                sub_options = ["stash", "stash-pop"] if has_wt_changes else ["proceed"]
                sub_options.append("skip")
                print("  apply which action to all remaining dirty repos?")
                for idx, opt in enumerate(sub_options, start=1):
                    print(f"  {idx}. {opt}")
                while True:
                    try:
                        choice = input("  choose an option: ").strip()
                    except (EOFError, KeyboardInterrupt):
                        print(yellow("\n  no input available, skipping remaining repos"))
                        forced_action = "skip"
                        break
                    if choice.isdigit() and 1 <= int(choice) <= len(sub_options):
                        forced_action = sub_options[int(choice) - 1]
                        break
                    print("  invalid choice, try again")
                action = forced_action
        handle_dirty_repo(status, branch, action, dry_run)


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------

def discover_repos(root, exclude_repos=()):
    repos = []
    for entry in sorted(os.listdir(root)):
        if entry in exclude_repos:
            continue
        full_path = os.path.join(root, entry)
        if os.path.isdir(full_path) and is_git_repo(full_path):
            repos.append(full_path)
    return repos


def load_config():
    config_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), CONFIG_FILENAME)
    if not os.path.isfile(config_path):
        return {}
    try:
        with open(config_path) as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError) as exc:
        print(yellow(f"warning: could not read {config_path}: {exc}"))
        return {}


def print_summary(statuses):
    print(bold("\n=== Summary ==="))
    width_name = max((len(s.name) for s in statuses), default=10)
    for s in statuses:
        action = s.action or (red(f"error: {s.error}") if s.error else "unknown")
        print(f"  {s.name.ljust(width_name)}  {action}")


def main():
    config = load_config()

    parser = argparse.ArgumentParser(description="Sync git repos under a root folder onto a target branch.")
    parser.add_argument("--root", default=None, help="Root folder containing the repos (default: config.json's 'root', else cwd)")
    parser.add_argument("--branch", default=None, help="Target branch to sync to (default: config.json's 'branch', else release/dev)")
    parser.add_argument("--dry-run", action="store_true", help="Show what would happen without changing anything")
    args = parser.parse_args()

    root = os.path.abspath(args.root or config.get("root") or os.getcwd())
    branch = args.branch or config.get("branch") or "release/dev"
    exclude_repos = set(config.get("exclude_repos", []))

    if not os.path.isdir(root):
        print(red(f"root folder not found: {root}"))
        sys.exit(1)

    repos = discover_repos(root, exclude_repos)
    if not repos:
        print(yellow(f"no git repos found directly under {root}"))
        return

    print(bold(f"Scanning {len(repos)} repo(s) under {root} -> target branch '{branch}'"))
    if args.dry_run:
        print(cyan("(dry-run: no changes will be made)"))

    statuses = []
    dirty_statuses = []
    for repo_path in repos:
        status = inspect_repo(repo_path, branch)
        statuses.append(status)
        if status.error:
            continue
        if status.is_dirty:
            dirty_statuses.append(status)
        else:
            sync_clean_repo(repo_path, branch, status, args.dry_run)

    run_interactive_pass(dirty_statuses, branch, args.dry_run)
    print_summary(statuses)


if __name__ == "__main__":
    main()
