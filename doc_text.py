#!/usr/bin/env python3
"""Turn a PDF, DOCX or PPTX into compact text for reading with few tokens.

Removes what costs tokens but carries no information: lines repeated on most pages (headers, footers,
page numbers), blank lines, runs of spaces and exact duplicate pages. Writes the result next to the
file (or to --out) and prints a size report, so the text can then be read in part.

    python doc_text.py paper.pdf                    # write paper.txt, print size + outline preview
    python doc_text.py paper.pdf --outline          # only headings / question lines
    python doc_text.py paper.pdf --pages 3-5        # only these pages (slides for .pptx)
    python doc_text.py paper.pdf --grep Maslow -C 1 # matching lines with context
    python doc_text.py paper.pdf --print            # print the full cleaned text
    python doc_text.py notes.docx --out notes.txt

Output marks each page as "## p<N>" so --pages and line references stay meaningful.
"""
import argparse
import re
import sys
from collections import Counter
from pathlib import Path

# A line counts as a heading / question for --outline.
OUTLINE = re.compile(
    r"^(#+\s|Q\.?\s*\d+|Question\s+\d+|\d+[.)]\s+[A-Z]|[a-z][.)]\s+\S|[ivx]+\)\s+\S|Unit\s+\w+|UNIT\s+\w+|Chapter\s+\d+|"
    r"Practice Paper|Section\s+[A-Z]|OR$|[A-Z][A-Z &/\-]{6,}$|\d+\.\d+\.?\s*\S|CO\d|[A-Z][\w ()/&,'-]{2,50}:$|"
    r"Semester\s+\w+$)"
)


def pages_pdf(path):
    from pypdf import PdfReader

    reader = PdfReader(str(path))
    return [(p.extract_text() or "") for p in reader.pages]


def pages_docx(path):
    import docx

    d = docx.Document(str(path))
    lines = []
    for para in d.paragraphs:
        style = (para.style.name or "").lower()
        text = para.text.strip()
        if not text:
            continue
        if style.startswith("heading"):
            level = "".join(ch for ch in style if ch.isdigit()) or "1"
            text = "#" * int(level) + " " + text
        lines.append(text)
    for t in d.tables:
        for row in t.rows:
            lines.append(" | ".join(c.text.strip() for c in row.cells))
    return ["\n".join(lines)]  # Word has no fixed pages: one "page"


def pages_pptx(path):
    from pptx import Presentation

    out = []
    for slide in Presentation(str(path)).slides:
        texts = []
        for shape in slide.shapes:
            if shape.has_text_frame:
                texts += [p.text for p in shape.text_frame.paragraphs if p.text.strip()]
            if getattr(shape, "has_table", False) and shape.has_table:
                for row in shape.table.rows:
                    texts.append(" | ".join(c.text.strip() for c in row.cells))
        if slide.has_notes_slide and slide.notes_slide.notes_text_frame.text.strip():
            texts.append("[notes] " + slide.notes_slide.notes_text_frame.text.strip())
        out.append("\n".join(texts))
    return out


READERS = {".pdf": pages_pdf, ".docx": pages_docx, ".pptx": pages_pptx}


def clean(pages):
    """Normalise whitespace, drop lines that repeat on most pages, and drop duplicate pages."""
    norm = []
    for text in pages:
        lines = [re.sub(r"[ \t ]+", " ", ln).strip() for ln in text.splitlines()]
        norm.append([ln for ln in lines if ln and not re.fullmatch(r"[-_=.·•\s]{3,}", ln)])
    if len(norm) >= 3:
        counts = Counter(ln for lines in norm for ln in set(lines))
        boiler = {ln for ln, n in counts.items() if n >= max(3, len(norm) * 0.5) and len(ln) < 160}
        # Bare page numbers ("3", "Page 3 of 9") are boilerplate even if they differ per page.
        norm = [
            [ln for ln in lines if ln not in boiler and not re.fullmatch(r"(page\s*)?\d+(\s*(of|/)\s*\d+)?", ln, re.I)]
            for lines in norm
        ]
    else:
        boiler = set()
    seen, result = set(), []
    for i, lines in enumerate(norm, 1):
        key = "\n".join(lines)
        if key and key in seen:
            result.append((i, ["(same as an earlier page)"]))
            continue
        seen.add(key)
        result.append((i, lines))
    return result, boiler


def parse_range(spec, total):
    keep = set()
    for part in spec.split(","):
        a, _, b = part.partition("-")
        start = int(a) if a else 1
        end = int(b) if b else (total if _ else start)
        keep.update(range(start, min(end, total) + 1))
    return keep


def main():
    for stream in (sys.stdout, sys.stderr):
        stream.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("file")
    ap.add_argument("--out", help="text file to write (default: next to the input, .txt)")
    ap.add_argument("--pages", help="e.g. 1-3,7 (pages, or slides for .pptx)")
    ap.add_argument("--outline", action="store_true", help="print only headings / question lines")
    ap.add_argument("--grep", help="print lines matching this regex (case-insensitive)")
    ap.add_argument("-C", type=int, default=0, help="context lines for --grep")
    ap.add_argument("--print", action="store_true", help="print the full cleaned text")
    a = ap.parse_args()

    path = Path(a.file)
    reader = READERS.get(path.suffix.lower())
    if not reader:
        sys.exit(f"unsupported file type: {path.suffix} (pdf, docx, pptx)")
    raw = reader(path)
    pages, boiler = clean(raw)
    if a.pages:
        keep = parse_range(a.pages, len(pages))
        pages = [(n, lines) for n, lines in pages if n in keep]

    text = "\n".join(f"## p{n}\n" + "\n".join(lines) for n, lines in pages if lines) + "\n"
    out = Path(a.out) if a.out else path.with_suffix(".txt")
    out.write_text(text, encoding="utf-8")

    raw_chars = sum(len(p) for p in raw)
    empty = sum(1 for p in raw if not p.strip())
    print(
        f"{path.name}: {len(raw)} page(s), {raw_chars:,} → {len(text):,} chars (~{len(text) // 4:,} tokens) → {out}",
        file=sys.stderr,
    )
    if boiler:
        print(f"removed {len(boiler)} repeated line(s), e.g. {sorted(boiler, key=len)[-1][:70]!r}", file=sys.stderr)
    if path.suffix.lower() == ".pdf" and empty == len(raw):
        print("no text layer: this PDF is scanned images (needs OCR)", file=sys.stderr)
    elif empty:
        print(f"{empty} page(s) without text (images or scans)", file=sys.stderr)

    lines = text.splitlines()
    if a.grep:
        rx = re.compile(a.grep, re.I)
        hits = [i for i, ln in enumerate(lines) if rx.search(ln)]
        shown = sorted({j for i in hits for j in range(max(0, i - a.C), min(len(lines), i + a.C + 1))})
        page = ""
        for j in shown:
            for k in range(j, -1, -1):
                if lines[k].startswith("## p"):
                    if lines[k] != page:
                        page = lines[k]
                        print(page)
                    break
            if not lines[j].startswith("## p"):
                print(lines[j])
    elif a.outline:
        for ln in lines:
            if ln.startswith("## p") or OUTLINE.match(ln):
                print(ln[:160])
    elif a.print:
        sys.stdout.write(text)


if __name__ == "__main__":
    main()
