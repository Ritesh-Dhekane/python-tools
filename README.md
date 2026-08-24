# python-tools

## sync_repos.py

Keeps every git repo under a root folder checked out to a target branch
(e.g. `release/dev`) and pulled up to date, without you having to `cd` into
each one by hand.

For each immediate subfolder of the root that is a git repo, it:

- fetches from its remote
- if the working tree is clean and has no unpushed commits, checks out the
  target branch (creating a local tracking branch if needed) and pulls it
- if the repo is dirty (uncommitted changes and/or unpushed commits), leaves
  it alone during the automatic pass, then offers an interactive menu once
  the automatic pass is done: stash & sync, stash & sync & pop, show
  diff/status, skip, or apply one choice to every remaining dirty repo

### Requirements

- Python 3.8+
- `git` on your `PATH`

### Setup

1. Copy the example config and edit it for your machine:
   ```
   cp config.example.json config.json
   ```
2. Edit `config.json`:
   - `root` — absolute path to the folder containing your repos (one repo per
     immediate subfolder)
   - `target_branch` — the branch every repo should be synced to
   - `exclude_repos` — folder names to skip entirely (e.g. repos with no
     `target_branch`, or folders that aren't actually git repos)

   `config.json` is gitignored — it's personal to your machine and never
   gets committed or pushed.

### Usage

With `config.json` in place, just run:
```
python3 python-tools/sync_repos.py
```

Preview what it would do first, with no changes made:
```
python3 python-tools/sync_repos.py --dry-run
```

Override the config for a one-off run (CLI args always win over `config.json`):
```
python3 python-tools/sync_repos.py --root /path/to/other/folder --branch main
```

### Output

- Clean repos report either `already up to date` or `pulled new commits`.
- Dirty repos prompt you interactively, then report what was done (synced,
  skipped, or left stashed with a reminder to `git stash pop` manually).
- A final summary table lists the outcome for every repo scanned.
