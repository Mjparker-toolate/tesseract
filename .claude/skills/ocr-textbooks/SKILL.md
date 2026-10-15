---
name: ocr-textbooks
description: Batch-OCR textbook PDFs (default folder ~/Desktop/Misc/Claude Project Files/) using ocrmypdf with --deskew --clean --optimize 3 --output-type pdfa --jobs 4. Replaces image-only PDFs and stripped markdown stubs with searchable PDF/A versions; moves originals to _replaced/ for rollback. Use when the user asks to "upgrade", "OCR", "make searchable", or "process" their Claude Project textbooks / scanned books on macOS. Idempotent — safe to re-run.
---

# OCR textbooks for Claude Projects

This skill upgrades scanned/image-only textbook PDFs into searchable PDF/A
files using `ocrmypdf`. It also removes the stripped-markdown versions the
user previously made (those lose the figures). Output filenames preserve the
originals so the user can re-upload to claude.ai Projects directly.

The bundled script `ocr-textbooks.sh` (alongside this SKILL.md) does the work.

## When invoked

Run these steps in order. **Pause and confirm with the user between phases**
(prereq install, dry-run review, real run).

### 1. Confirm the source folder

Default: `~/Desktop/Misc/Claude Project Files/`. Check it exists:

```bash
ls -d ~/Desktop/Misc/Claude\ Project\ Files 2>/dev/null
```

If it's missing, ask the user for the correct path and pass it via `OCR_SRC`
when invoking the script in later steps.

### 2. Verify prerequisites

Check that `ocrmypdf` is on PATH:

```bash
command -v ocrmypdf
```

If missing:

- Check `command -v brew`. If brew is also missing, ask the user before
  running:
  ```bash
  /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
  ```
  After install, source it: `eval "$(/opt/homebrew/bin/brew shellenv)"`
  (Apple Silicon) or `eval "$(/usr/local/bin/brew shellenv)"` (Intel).
- Then install the OCR toolchain (only after user confirms):
  ```bash
  brew install ocrmypdf jbig2enc unpaper
  ```

Never install Homebrew or system packages without explicit confirmation.

### 3. Dry-run

Always dry-run before the real run so the user sees exactly what will move:

```bash
bash ~/.claude/skills/ocr-textbooks/ocr-textbooks.sh --dry-run
```

Show the user the action list. Summarize: how many textbooks will be
upgraded, how many already-upgraded ones will be skipped, whether any
markdown stubs will be moved to `_replaced/`. Ask whether to proceed.

### 4. Real run

The real run is **long** — typically 5–20 minutes per textbook. Run it in
the background and stream progress from the log:

```bash
# Start in background
bash ~/.claude/skills/ocr-textbooks/ocr-textbooks.sh
```

Use the Bash tool's `run_in_background: true`. While it runs, read
`~/scripts/ocr-textbooks.log` periodically (or use Monitor with
`tail -f ~/scripts/ocr-textbooks.log`) to surface per-file progress to the
user. Don't block — the user should see live updates.

### 5. Report

When the script finishes, report:

- Counts: upgraded / skipped / failed (from the script's final summary line).
- Failed filenames (grep `!! OCR failed` in the log) and the relevant
  ocrmypdf error excerpt for each.
- Reminder: the user must re-upload the new PDFs to their claude.ai Project
  via the web UI and delete the old `.md` uploads — there's no public API
  for Project file management.

## Idempotency & rollback

- Re-running the skill is safe. The script skips any textbook whose original
  is already in `_replaced/`.
- To roll back one textbook:
  ```bash
  SRC=~/Desktop/Misc/Claude\ Project\ Files
  mv "$SRC/_replaced/Foo.pdf" "$SRC/Foo.pdf"
  # If a markdown was also replaced:
  mv "$SRC/_replaced/Foo.md" "$SRC/Foo.md"
  ```
- To roll back everything: move every file out of `_replaced/` back into the
  source folder, overwriting the OCR'd versions.

## Variants the user might ask for

- **Different folder:** pass `OCR_SRC=/some/other/path` before the bash
  invocation. The script handles spaces in the path correctly.
- **Skip the markdown deletion:** not currently a flag; if asked, edit the
  script's phase-2 block to comment out the `if [[ -f "$md_path" ]]; then`
  branch. Don't add a flag without explicit user request.
- **Different ocrmypdf flags:** edit `do_ocr()` in the script. The reference
  flags are tuned for textbooks (deskew + clean for scan artifacts,
  optimize 3 + pdfa for archive-quality compression).

## Constraints

- macOS only (Homebrew install path). On Linux, the script itself works but
  the prereq install instructions need adjustment to apt/dnf.
- Requires `jbig2enc` for `--optimize 3`. If it's missing, ocrmypdf will
  warn and fall back; the script does not check for it explicitly.
- Not recursive — only top-level `*.pdf` in the source folder. If the user
  has subfolders, ask whether to add `-maxdepth` adjustments before
  changing behavior.
