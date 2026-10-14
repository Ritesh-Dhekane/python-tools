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

## doc_text.py

Turns a PDF, DOCX or PPTX into compact text that is cheap to read (for people and for AI agents):
drops headers/footers repeated on most pages, page numbers, blank lines, extra spaces and duplicate
pages; marks pages as `## p<N>`; writes `<file>.txt` and prints a size report (chars, ~tokens).
Reports scanned PDFs (no text layer) instead of returning nothing.

```
pip install pypdf python-docx python-pptx
python doc_text.py paper.pdf                    # write paper.txt + size report
python doc_text.py paper.pdf --outline          # headings / question lines only
python doc_text.py paper.pdf --pages 3-5        # some pages (slides for .pptx)
python doc_text.py paper.pdf --grep Maslow -C 1 # matching lines with context
python doc_text.py paper.pdf --print            # full cleaned text
```
