#!/usr/bin/env bash
# ocr-textbooks.sh
# Batch-OCR every textbook PDF in OCR_SRC and replace markdown stubs with the
# OCR'd PDFs. Originals (and any matching .md) are moved to OCR_SRC/_replaced/
# for safe rollback. Idempotent: re-running skips already-upgraded files.

set -euo pipefail

OCR_SRC="${OCR_SRC:-$HOME/Desktop/Misc/Claude Project Files}"
LOG_DIR="$HOME/scripts"
LOG="$LOG_DIR/ocr-textbooks.log"
DRY_RUN=0

for arg in "$@"; do
    case "$arg" in
        --dry-run|-n) DRY_RUN=1 ;;
        -h|--help)
            cat <<EOF
Usage: $0 [--dry-run]

Environment:
  OCR_SRC   Source folder (default: ~/Desktop/Misc/Claude Project Files)

Runs ocrmypdf on every *.pdf in OCR_SRC, replaces each original with its
OCR'd PDF/A version, and moves stripped *.md files into OCR_SRC/_replaced/.
The original (image-only) PDFs are also moved to _replaced/ so nothing is
permanently deleted.
EOF
            exit 0 ;;
        *) echo "Unknown arg: $arg" >&2; exit 2 ;;
    esac
done

if ! command -v ocrmypdf >/dev/null 2>&1; then
    echo "ERROR: ocrmypdf not found. Install with: brew install ocrmypdf jbig2enc unpaper" >&2
    exit 1
fi

if [[ ! -d "$OCR_SRC" ]]; then
    echo "ERROR: source folder does not exist: $OCR_SRC" >&2
    exit 1
fi

mkdir -p "$LOG_DIR"
REPLACED_DIR="$OCR_SRC/_replaced"

ts()  { date '+%Y-%m-%d %H:%M:%S'; }
log() { echo "[$(ts)] $*" | tee -a "$LOG"; }

do_ocr() {
    local in="$1" out="$2"
    if [[ $DRY_RUN -eq 1 ]]; then
        echo "  [dry-run] ocrmypdf --deskew --clean --optimize 3 --output-type pdfa --jobs 4 --skip-text \"$in\" \"$out\""
        return 0
    fi
    ocrmypdf --deskew --clean --optimize 3 --output-type pdfa --jobs 4 --skip-text \
             "$in" "$out" >>"$LOG" 2>&1
}

do_mv() {
    local from="$1" to="$2"
    if [[ $DRY_RUN -eq 1 ]]; then
        echo "  [dry-run] mv \"$from\" \"$to\""
        return 0
    fi
    mv "$from" "$to"
}

do_mkdir() {
    local d="$1"
    if [[ $DRY_RUN -eq 1 ]]; then
        [[ -d "$d" ]] || echo "  [dry-run] mkdir -p \"$d\""
        return 0
    fi
    mkdir -p "$d"
}

if [[ $DRY_RUN -eq 1 ]]; then
    log "=== DRY RUN — no changes will be made ==="
fi
log "Source folder: $OCR_SRC"

inputs=()
while IFS= read -r -d '' f; do
    inputs+=("$f")
done < <(find "$OCR_SRC" -maxdepth 1 -type f -name '*.pdf' ! -name '*-ocr.pdf' -print0 | sort -z)

total=${#inputs[@]}
if [[ $total -eq 0 ]]; then
    log "No PDFs found in $OCR_SRC."
    exit 0
fi

upgraded=0
skipped=0
failed=0
failures=()
i=0

for input in "${inputs[@]}"; do
    i=$((i + 1))
    name="$(basename "$input" .pdf)"
    ocr_out="$OCR_SRC/${name}-ocr.pdf"
    md_path="$OCR_SRC/${name}.md"
    backup_pdf="$REPLACED_DIR/${name}.pdf"

    log "[$i/$total] $name.pdf"

    if [[ -f "$backup_pdf" ]]; then
        log "  -> already upgraded (backup in _replaced/), skipping"
        skipped=$((skipped + 1))
        continue
    fi

    if [[ -f "$ocr_out" ]]; then
        log "  -> reusing existing ${name}-ocr.pdf from a prior partial run"
    else
        log "  -> running ocrmypdf (this can take a while for large books)"
        if ! do_ocr "$input" "$ocr_out"; then
            log "  !! OCR failed for ${name}.pdf (details in $LOG)"
            failed=$((failed + 1))
            failures+=("${name}.pdf")
            continue
        fi
    fi

    do_mkdir "$REPLACED_DIR"
    do_mv "$input"   "$backup_pdf"
    if [[ -f "$md_path" ]]; then
        do_mv "$md_path" "$REPLACED_DIR/${name}.md"
    fi
    do_mv "$ocr_out" "$input"

    log "  -> upgraded"
    upgraded=$((upgraded + 1))
done

log "Done: $upgraded upgraded, $skipped skipped, $failed failed. Originals in $REPLACED_DIR"
if [[ ${#failures[@]} -gt 0 ]]; then
    log "Failed files:"
    for f in "${failures[@]}"; do log "  - $f"; done
fi

[[ $failed -gt 0 ]] && exit 1
exit 0
