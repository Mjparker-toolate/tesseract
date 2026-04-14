#!/usr/bin/env python3
"""
Leaked Information Checker

A defensive security tool that checks whether personal information (email
addresses, passwords, API keys) has been exposed in known data breaches or
is at risk of leaking from local files.

Features:
  - Email breach check: queries Have I Been Pwned for known breaches/pastes
  - Password breach check: uses HIBP Pwned Passwords with k-anonymity
    (only the first 5 chars of the SHA-1 hash leave your machine)
  - API key scanner: scans local files/repos for accidentally committed
    secrets (API keys, tokens, credentials) that could be leaked

Usage:
    python leaked_info_checker.py --email user@example.com
    python leaked_info_checker.py --password
    python leaked_info_checker.py --scan-keys .
    python leaked_info_checker.py --scan-keys /path/to/project --exclude node_modules,.git
    python leaked_info_checker.py --email user@example.com --password --scan-keys .
"""

import argparse
import hashlib
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request
from getpass import getpass

HIBP_API_BASE = "https://haveibeenpwned.com/api/v3"
HIBP_PASSWORD_API = "https://api.pwnedpasswords.com/range"
USER_AGENT = "LeakedInfoChecker-DefensiveTool"
REQUEST_DELAY_SECONDS = 1.6  # HIBP rate limit: ~1 request per 1.5s

# ---------------------------------------------------------------------------
# API key / secret patterns
# Each entry: (name, compiled regex, description)
# These detect common secret formats that should never be committed to repos.
# ---------------------------------------------------------------------------
API_KEY_PATTERNS = [
    (
        "AWS Access Key ID",
        re.compile(r"(?<![A-Z0-9])(AKIA[0-9A-Z]{16})(?![A-Z0-9])"),
        "AWS IAM access key — rotate immediately if exposed",
    ),
    (
        "AWS Secret Access Key",
        re.compile(r"""(?:aws_secret_access_key|secret_key)\s*[=:]\s*['"]?([A-Za-z0-9/+=]{40})['"]?""", re.IGNORECASE),
        "AWS secret key — rotate immediately if exposed",
    ),
    (
        "GitHub Token (classic)",
        re.compile(r"(ghp_[A-Za-z0-9_]{36,})"),
        "GitHub personal access token — revoke at github.com/settings/tokens",
    ),
    (
        "GitHub Token (fine-grained / OAuth / app)",
        re.compile(r"(gh[ous]_[A-Za-z0-9_]{36,})"),
        "GitHub token — revoke at github.com/settings/tokens",
    ),
    (
        "GitLab Token",
        re.compile(r"(glpat-[A-Za-z0-9\-_]{20,})"),
        "GitLab personal access token",
    ),
    (
        "Slack Bot / User Token",
        re.compile(r"(xox[bporas]-[0-9]{10,13}-[0-9]{10,13}[a-zA-Z0-9-]*)"),
        "Slack API token — regenerate in Slack app settings",
    ),
    (
        "Slack Webhook URL",
        re.compile(r"(https://hooks\.slack\.com/services/T[A-Z0-9]+/B[A-Z0-9]+/[A-Za-z0-9]+)"),
        "Slack incoming webhook URL",
    ),
    (
        "Google API Key",
        re.compile(r"(AIza[0-9A-Za-z\-_]{35})"),
        "Google API key — restrict or delete in Google Cloud Console",
    ),
    (
        "Google OAuth Client Secret",
        re.compile(r"""client_secret["']?\s*[=:]\s*["']([A-Za-z0-9_\-]{24,})["']"""),
        "Google OAuth client secret",
    ),
    (
        "Heroku API Key",
        re.compile(r"""(?:heroku.*api[_-]?key|HEROKU_API_KEY)\s*[=:]\s*['"]?([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})['"]?""", re.IGNORECASE),
        "Heroku API key",
    ),
    (
        "Stripe Secret Key",
        re.compile(r"(sk_live_[0-9a-zA-Z]{24,})"),
        "Stripe live secret key — roll in Stripe dashboard immediately",
    ),
    (
        "Stripe Publishable Key (live)",
        re.compile(r"(pk_live_[0-9a-zA-Z]{24,})"),
        "Stripe live publishable key (lower risk but review usage)",
    ),
    (
        "Twilio API Key / Auth Token",
        re.compile(r"""(?:twilio.*(?:token|key|sid))\s*[=:]\s*['"]?([a-f0-9]{32})['"]?""", re.IGNORECASE),
        "Twilio credential",
    ),
    (
        "SendGrid API Key",
        re.compile(r"(SG\.[A-Za-z0-9_\-]{22}\.[A-Za-z0-9_\-]{43})"),
        "SendGrid API key",
    ),
    (
        "Mailgun API Key",
        re.compile(r"(key-[0-9a-zA-Z]{32})"),
        "Mailgun API key",
    ),
    (
        "OpenAI API Key",
        re.compile(r"(sk-[A-Za-z0-9]{20}T3BlbkFJ[A-Za-z0-9]{20})"),
        "OpenAI API key — revoke at platform.openai.com/api-keys",
    ),
    (
        "OpenAI API Key (project-scoped)",
        re.compile(r"(sk-proj-[A-Za-z0-9_\-]{40,})"),
        "OpenAI project-scoped API key",
    ),
    (
        "Anthropic API Key",
        re.compile(r"(sk-ant-[A-Za-z0-9_\-]{40,})"),
        "Anthropic API key — revoke at console.anthropic.com",
    ),
    (
        "Generic Private Key Block",
        re.compile(r"(-----BEGIN (?:RSA |EC |DSA |OPENSSH )?PRIVATE KEY-----)"),
        "Private key file — never commit private keys to version control",
    ),
    (
        "Generic Secret/Token Assignment",
        re.compile(
            r"""(?:api[_-]?key|api[_-]?secret|access[_-]?token|auth[_-]?token|secret[_-]?key|private[_-]?key|password|passwd|credential)"""
            r"""\s*[=:]\s*['"]([A-Za-z0-9/+=_\-]{20,})['"]""",
            re.IGNORECASE,
        ),
        "Possible hardcoded secret — move to environment variables or a secrets manager",
    ),
    (
        "Database Connection String with Password",
        re.compile(
            r"""((?:mysql|postgres|postgresql|mongodb|redis|amqp)://[^:]+:[^@\s]+@[^\s'"]+)""",
            re.IGNORECASE,
        ),
        "Database URI with embedded credentials — use env vars instead",
    ),
    (
        "JWT Token",
        re.compile(r"(eyJ[A-Za-z0-9_-]{10,}\.eyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_\-]+)"),
        "JSON Web Token — may contain sensitive claims",
    ),
]

# File extensions to scan (text-based files likely to contain code/config)
SCANNABLE_EXTENSIONS = {
    ".py", ".js", ".ts", ".jsx", ".tsx", ".rb", ".go", ".java", ".rs",
    ".php", ".cs", ".swift", ".kt", ".scala", ".sh", ".bash", ".zsh",
    ".yml", ".yaml", ".json", ".toml", ".ini", ".cfg", ".conf", ".config",
    ".env", ".env.local", ".env.development", ".env.production",
    ".properties", ".xml", ".tf", ".hcl", ".dockerfile",
    ".md", ".txt", ".csv", ".sql", ".r", ".R", ".ipynb",
}

# Filenames that are always worth scanning regardless of extension
SCANNABLE_FILENAMES = {
    ".env", ".env.local", ".env.development", ".env.production", ".env.test",
    "Dockerfile", "docker-compose.yml", "docker-compose.yaml",
    "Makefile", "Vagrantfile", ".bashrc", ".bash_profile", ".zshrc",
    ".npmrc", ".pypirc", "credentials", "config",
}

# Default directories to skip
DEFAULT_EXCLUDE_DIRS = {
    ".git", "node_modules", "__pycache__", ".tox", ".venv", "venv",
    ".mypy_cache", ".pytest_cache", "dist", "build", ".next", ".nuxt",
    "vendor", "target", "bin", "obj", ".gradle", ".idea", ".vs",
}

# Maximum file size to scan (skip large binaries / data files)
MAX_FILE_SIZE_BYTES = 1_000_000  # 1 MB


# ---------------------------------------------------------------------------
# HIBP functions
# ---------------------------------------------------------------------------

def _make_request(url, api_key=None, _retries_left=5):
    """Make an HTTP GET request with appropriate headers."""
    req = urllib.request.Request(url)
    req.add_header("User-Agent", USER_AGENT)
    req.add_header("Accept", "application/json")
    if api_key:
        req.add_header("hibp-api-key", api_key)
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return resp.read().decode("utf-8"), resp.status
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return None, 404
        if e.code == 429 and _retries_left > 0:
            print(f"  [!] Rate limited. Waiting before retry ({_retries_left} retries left)...")
            time.sleep(3)
            return _make_request(url, api_key=api_key, _retries_left=_retries_left - 1)
        raise


def check_email_breaches(email, api_key=None):
    """Check if an email appears in known data breaches via HIBP."""
    url = f"{HIBP_API_BASE}/breachedaccount/{urllib.request.quote(email)}?truncateResponse=false"
    data, status = _make_request(url, api_key=api_key)
    if status == 404 or data is None:
        return []
    return json.loads(data)


def check_email_pastes(email, api_key=None):
    """Check if an email appears in known paste dumps via HIBP."""
    url = f"{HIBP_API_BASE}/pasteaccount/{urllib.request.quote(email)}"
    data, status = _make_request(url, api_key=api_key)
    if status == 404 or data is None:
        return []
    return json.loads(data)


def check_password(password):
    """
    Check if a password has been seen in known breaches using the HIBP
    Pwned Passwords API with k-anonymity.

    Only the first 5 characters of the SHA-1 hash are sent to the API.
    The full hash never leaves this machine.
    """
    sha1 = hashlib.sha1(password.encode("utf-8")).hexdigest().upper()
    prefix = sha1[:5]
    suffix = sha1[5:]

    url = f"{HIBP_PASSWORD_API}/{prefix}"
    req = urllib.request.Request(url)
    req.add_header("User-Agent", USER_AGENT)
    with urllib.request.urlopen(req, timeout=30) as resp:
        body = resp.read().decode("utf-8")

    for line in body.splitlines():
        hash_suffix, count = line.strip().split(":")
        if hash_suffix.upper() == suffix:
            return int(count)
    return 0


# ---------------------------------------------------------------------------
# Reporting helpers
# ---------------------------------------------------------------------------

def format_breach_report(breaches):
    """Format breach data into a readable report."""
    lines = []
    for b in breaches:
        name = b.get("Name", "Unknown")
        date = b.get("BreachDate", "Unknown")
        count = b.get("PwnCount", "Unknown")
        data_classes = ", ".join(b.get("DataClasses", []))
        description = b.get("Description", "")
        description = re.sub(r"<[^>]+>", "", description)

        lines.append(f"  Breach: {name}")
        lines.append(f"    Date:         {date}")
        lines.append(f"    Records:      {count:,}" if isinstance(count, int) else f"    Records:      {count}")
        lines.append(f"    Exposed data: {data_classes}")
        if description:
            if len(description) > 200:
                description = description[:200] + "..."
            lines.append(f"    Details:      {description}")
        lines.append("")
    return "\n".join(lines)


def format_paste_report(pastes):
    """Format paste data into a readable report."""
    lines = []
    for p in pastes:
        source = p.get("Source", "Unknown")
        paste_id = p.get("Id", "Unknown")
        title = p.get("Title") or "(untitled)"
        date = p.get("Date") or "Unknown"
        email_count = p.get("EmailCount", "Unknown")

        lines.append(f"  Paste: {title}")
        lines.append(f"    Source: {source} (ID: {paste_id})")
        lines.append(f"    Date:   {date}")
        lines.append(f"    Emails in paste: {email_count}")
        lines.append("")
    return "\n".join(lines)


def _redact(value, visible_chars=6):
    """Partially redact a secret value for safe display."""
    if len(value) <= visible_chars:
        return "*" * len(value)
    return value[:visible_chars] + "*" * (len(value) - visible_chars)


# ---------------------------------------------------------------------------
# Email check
# ---------------------------------------------------------------------------

def check_single_email(email, api_key=None, check_pastes=False):
    """Run all checks for a single email and print results."""
    print(f"\n{'='*60}")
    print(f"Checking: {email}")
    print(f"{'='*60}")

    print("\n[*] Checking known data breaches...")
    try:
        breaches = check_email_breaches(email, api_key=api_key)
    except Exception as e:
        print(f"  [!] Error querying breach database: {e}")
        breaches = []

    if breaches:
        print(f"  [!] FOUND in {len(breaches)} breach(es):\n")
        print(format_breach_report(breaches))
    else:
        print("  [OK] Not found in any known breaches.")

    time.sleep(REQUEST_DELAY_SECONDS)

    if check_pastes:
        print("[*] Checking known paste dumps...")
        try:
            pastes = check_email_pastes(email, api_key=api_key)
        except Exception as e:
            print(f"  [!] Error querying paste database: {e}")
            pastes = []

        if pastes:
            print(f"  [!] FOUND in {len(pastes)} paste(s):\n")
            print(format_paste_report(pastes))
        else:
            print("  [OK] Not found in any known pastes.")

        time.sleep(REQUEST_DELAY_SECONDS)

    return len(breaches) if breaches else 0


# ---------------------------------------------------------------------------
# API key / secret scanner
# ---------------------------------------------------------------------------

def _should_scan_file(filepath, exclude_dirs):
    """Decide whether a file should be scanned for secrets."""
    parts = filepath.split(os.sep)
    for part in parts:
        if part in exclude_dirs:
            return False

    basename = os.path.basename(filepath)
    if basename in SCANNABLE_FILENAMES:
        return True

    _, ext = os.path.splitext(basename)
    if ext.lower() in SCANNABLE_EXTENSIONS:
        return True

    return False


def scan_file_for_keys(filepath):
    """Scan a single file for API key / secret patterns. Returns list of findings."""
    findings = []
    try:
        size = os.path.getsize(filepath)
        if size > MAX_FILE_SIZE_BYTES or size == 0:
            return findings
        with open(filepath, "r", errors="ignore") as f:
            content = f.read()
    except (OSError, PermissionError):
        return findings

    for line_num, line in enumerate(content.splitlines(), start=1):
        # Skip comment-only lines that are documenting patterns (e.g. regex defs)
        stripped = line.strip()
        if stripped.startswith("#") or stripped.startswith("//"):
            # Still check .env style lines like KEY=value
            if "=" not in stripped:
                continue

        for name, pattern, description in API_KEY_PATTERNS:
            for match in pattern.finditer(line):
                value = match.group(1) if match.lastindex else match.group(0)
                findings.append({
                    "file": filepath,
                    "line": line_num,
                    "type": name,
                    "value": value,
                    "description": description,
                })
    return findings


def scan_directory_for_keys(root_path, exclude_dirs=None):
    """Walk a directory tree and scan all eligible files for leaked secrets."""
    if exclude_dirs is None:
        exclude_dirs = DEFAULT_EXCLUDE_DIRS
    else:
        exclude_dirs = DEFAULT_EXCLUDE_DIRS | set(exclude_dirs)

    all_findings = []
    files_scanned = 0

    for dirpath, dirnames, filenames in os.walk(root_path):
        # Prune excluded directories in-place so os.walk skips them
        dirnames[:] = [d for d in dirnames if d not in exclude_dirs]

        for filename in filenames:
            filepath = os.path.join(dirpath, filename)
            if _should_scan_file(filepath, exclude_dirs):
                files_scanned += 1
                findings = scan_file_for_keys(filepath)
                all_findings.extend(findings)

    return all_findings, files_scanned


def format_key_scan_report(findings):
    """Format API key scan results into a readable report."""
    lines = []
    # Group by file
    by_file = {}
    for f in findings:
        by_file.setdefault(f["file"], []).append(f)

    for filepath, file_findings in sorted(by_file.items()):
        lines.append(f"  File: {filepath}")
        for finding in file_findings:
            redacted = _redact(finding["value"])
            lines.append(f"    Line {finding['line']}: [{finding['type']}]")
            lines.append(f"      Value (redacted): {redacted}")
            lines.append(f"      Action: {finding['description']}")
        lines.append("")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Check if personal information or secrets have been exposed.",
        epilog=(
            "Examples:\n"
            "  %(prog)s --email user@example.com\n"
            "  %(prog)s --password\n"
            "  %(prog)s --scan-keys /path/to/project\n"
            "  %(prog)s --scan-keys . --exclude node_modules,.git,dist\n"
            "  %(prog)s --email user@example.com --password --scan-keys .\n"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--email", "-e",
        help="Email address to check against breach databases.",
    )
    parser.add_argument(
        "--emails-file", "-f",
        help="Path to a file with one email address per line.",
    )
    parser.add_argument(
        "--password", "-p",
        action="store_true",
        help="Check a password against the Pwned Passwords database. "
             "You will be prompted to enter it securely (not echoed).",
    )
    parser.add_argument(
        "--pastes",
        action="store_true",
        help="Also check for appearances in paste dumps (requires HIBP API key).",
    )
    parser.add_argument(
        "--api-key", "-k",
        default=os.environ.get("HIBP_API_KEY"),
        help="HIBP API key (required for breach/paste lookups; "
             "password checks do not require a key). "
             "Can also be set via the HIBP_API_KEY environment variable.",
    )
    parser.add_argument(
        "--scan-keys", "-s",
        metavar="PATH",
        help="Scan a directory (recursively) for leaked API keys, tokens, "
             "and hardcoded secrets.",
    )
    parser.add_argument(
        "--exclude",
        help="Comma-separated list of directory names to skip during "
             "--scan-keys (added to the default exclusion list).",
    )

    args = parser.parse_args()

    if not args.email and not args.emails_file and not args.password and not args.scan_keys:
        parser.print_help()
        print("\nError: Provide at least one of --email, --emails-file, --password, or --scan-keys.")
        sys.exit(1)

    print("=" * 60)
    print("  Leaked Information Checker")
    print("  Breach data via Have I Been Pwned (haveibeenpwned.com)")
    print("=" * 60)

    total_breaches = 0
    total_secrets = 0

    # ------------------------------------------------------------------
    # Email checks
    # ------------------------------------------------------------------
    api_key = args.api_key

    if args.email:
        total_breaches += check_single_email(args.email, api_key=api_key, check_pastes=args.pastes)

    if args.emails_file:
        try:
            with open(args.emails_file, "r") as f:
                emails = [line.strip() for line in f if line.strip() and not line.startswith("#")]
        except FileNotFoundError:
            print(f"\nError: File not found: {args.emails_file}")
            sys.exit(1)

        print(f"\nLoaded {len(emails)} email(s) from {args.emails_file}")
        for email in emails:
            total_breaches += check_single_email(email, api_key=api_key, check_pastes=args.pastes)

    # ------------------------------------------------------------------
    # Password check
    # ------------------------------------------------------------------
    if args.password:
        print(f"\n{'='*60}")
        print("Password Check (k-anonymity model)")
        print(f"{'='*60}")
        print("[*] Your password will NOT be sent over the network.")
        print("    Only the first 5 characters of its SHA-1 hash are transmitted.\n")

        password = getpass("Enter password to check: ")
        if not password:
            print("  [!] No password entered.")
        else:
            try:
                count = check_password(password)
                if count > 0:
                    print(f"\n  [!] WARNING: This password has been seen {count:,} time(s) in data breaches.")
                    print("      You should change it immediately wherever it is used.")
                else:
                    print("\n  [OK] This password has NOT been found in any known breaches.")
                    print("       (This does not guarantee it is secure — use a strong, unique password.)")
            except Exception as e:
                print(f"\n  [!] Error checking password: {e}")

    # ------------------------------------------------------------------
    # API key / secret scan
    # ------------------------------------------------------------------
    if args.scan_keys:
        scan_path = os.path.abspath(args.scan_keys)
        if not os.path.isdir(scan_path):
            print(f"\nError: Not a directory: {scan_path}")
            sys.exit(1)

        extra_excludes = []
        if args.exclude:
            extra_excludes = [d.strip() for d in args.exclude.split(",") if d.strip()]

        print(f"\n{'='*60}")
        print("API Key & Secret Scanner")
        print(f"{'='*60}")
        print(f"[*] Scanning: {scan_path}")
        if extra_excludes:
            print(f"    Extra exclusions: {', '.join(extra_excludes)}")
        print(f"    Default exclusions: {', '.join(sorted(DEFAULT_EXCLUDE_DIRS))}")
        print()

        findings, files_scanned = scan_directory_for_keys(scan_path, extra_excludes)
        total_secrets = len(findings)

        print(f"  Files scanned: {files_scanned}")
        print(f"  Potential secrets found: {total_secrets}")

        if findings:
            print(f"\n  [!] LEAKED SECRETS DETECTED:\n")
            print(format_key_scan_report(findings))
        else:
            print("\n  [OK] No leaked secrets detected.")

    # ------------------------------------------------------------------
    # Summary
    # ------------------------------------------------------------------
    print(f"\n{'='*60}")
    print("Summary")
    print(f"{'='*60}")

    if args.email or args.emails_file:
        if total_breaches > 0:
            print(f"  Breach exposures found: {total_breaches}")
            print("\n  Recommended actions:")
            print("    1. Change passwords for affected accounts")
            print("    2. Enable two-factor authentication (2FA)")
            print("    3. Use a unique password for each service")
            print("    4. Consider using a password manager")
        else:
            print("  No breaches found for the checked email(s).")

    if args.password:
        print("  Password check complete.")

    if args.scan_keys:
        if total_secrets > 0:
            print(f"  Potential leaked secrets: {total_secrets}")
            print("\n  Recommended actions:")
            print("    1. Rotate/revoke any confirmed leaked keys immediately")
            print("    2. Move secrets to environment variables or a secrets manager")
            print("    3. Add sensitive files to .gitignore")
            print("    4. Consider using git-secrets or pre-commit hooks to prevent future leaks")
            print("    5. If keys were committed to git history, use BFG Repo-Cleaner or")
            print("       git filter-branch to purge them (the key is compromised either way)")
        else:
            print("  No leaked secrets found in scanned files.")

    print()


if __name__ == "__main__":
    main()
