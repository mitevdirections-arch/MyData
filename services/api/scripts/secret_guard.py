from __future__ import annotations

import argparse
from dataclasses import dataclass
import re
import subprocess
import sys
from pathlib import Path


SAFE_SECRET_MARKERS = {
    "change-me",
    "example",
    "dummy",
    "placeholder",
    "sample",
    "local",
    "localhost",
    "<",
    ">",
}

OFFICIAL_PUBLIC_SERVICE_URL_PREFIXES = (
    "https://ec.europa.eu/taxation_customs/vies/",
)

SECRET_ASSIGNMENT_RE = re.compile(
    r"(?i)\b(jwt_secret|storage_grant_secret|guard_bot_signing_master_secret|storage_secret_key|s3_secret_key)\b\s*[:=]\s*[\"']([^\"'\n]{8,})[\"']"
)
ENV_SECRET_RE = re.compile(
    r"\b([A-Z0-9_]*(?:SECRET|SECRET_KEY|PASSWORD|API_KEY|PRIVATE_KEY|ACCESS_KEY)[A-Z0-9_]*)\b\s*=\s*([^\s#]+)"
)
INLINE_DSN_WITH_CREDS_RE = re.compile(
    r"(?i)\b(cockroachdb\+psycopg|cockroachdb|postgresql|postgres|mysql|mariadb)://[^/\s:\"']+:[^@\s\"']+@"
)
PUBLIC_SERVICE_URL_ASSIGNMENT_RE = re.compile(
    r"(?i)\b(entity_verification_vies_wsdl_url|entity_verification_vies_service_url)\b[^=]*=\s*[\"']([^\"']+)[\"']"
)
PRIVATE_KEY_RE = re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----")

ALLOWLIST_EXACT_FILES = {
    "services/api/tests/test_prod_gate.py",
}


@dataclass(frozen=True)
class Finding:
    path: str
    line: int
    code: str
    detail: str


def _run_git(repo_root: Path, args: list[str]) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git", *args],
        cwd=repo_root,
        text=True,
        capture_output=True,
        check=False,
    )


def _run_git_bytes(repo_root: Path, args: list[str]) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git", *args],
        cwd=repo_root,
        text=False,
        capture_output=True,
        check=False,
    )


def _repo_root_from_script() -> Path:
    return Path(__file__).resolve().parents[3]


def _normalize_rel(path: str) -> str:
    return str(path).replace("\\", "/").strip("/")


def _is_safe_value(raw_value: str) -> bool:
    value = str(raw_value or "").strip().strip("'\"")
    if not value:
        return True
    if value.isdigit():
        return True
    if len(value) < 8:
        return True
    low = value.lower()
    if low in {"true", "false", "0", "1"}:
        return True
    if value.startswith("$") or value.startswith("${"):
        return True
    if any(marker in low for marker in SAFE_SECRET_MARKERS):
        return True
    return False


def _is_allowlisted_public_service_url(url: str) -> bool:
    raw = str(url or "").strip().lower()
    return any(raw.startswith(prefix) for prefix in OFFICIAL_PUBLIC_SERVICE_URL_PREFIXES)


def _is_dotenv_like(path: str) -> bool:
    p = _normalize_rel(path).lower().split("/")[-1]
    return p.startswith(".env")


def _is_forbidden_env_file(path: str) -> bool:
    p = _normalize_rel(path).lower().split("/")[-1]
    return p.startswith(".env") and p != ".env.example"


def _scan_text(path: str, text: str) -> list[Finding]:
    findings: list[Finding] = []
    rel = _normalize_rel(path)
    is_env = _is_dotenv_like(rel)

    for ln, line in enumerate(text.splitlines(), start=1):
        stripped = line.strip()
        if stripped.startswith("#"):
            continue

        if INLINE_DSN_WITH_CREDS_RE.search(line):
            findings.append(Finding(rel, ln, "hardcoded_dsn_credentials", "DSN contains inline credentials"))

        if PRIVATE_KEY_RE.search(line):
            findings.append(Finding(rel, ln, "private_key_material", "Private key material marker detected"))

        for match in SECRET_ASSIGNMENT_RE.finditer(line):
            value = match.group(2) or ""
            if not _is_safe_value(value):
                findings.append(Finding(rel, ln, "hardcoded_secret_assignment", match.group(1)))

        if is_env:
            for match in ENV_SECRET_RE.finditer(line):
                env_key = match.group(1) or ""
                value = match.group(2) or ""
                if not _is_safe_value(value):
                    findings.append(Finding(rel, ln, "dotenv_secret_value", env_key))

        m_public = PUBLIC_SERVICE_URL_ASSIGNMENT_RE.search(line)
        if m_public:
            assigned_url = m_public.group(2) or ""
            if not _is_allowlisted_public_service_url(assigned_url):
                findings.append(Finding(rel, ln, "non_official_public_service_url_assignment", assigned_url))

    return findings


def _get_staged_paths(repo_root: Path) -> list[str]:
    cp = _run_git(repo_root, ["diff", "--cached", "--name-only", "--diff-filter=ACMR"])
    if cp.returncode != 0:
        raise RuntimeError(f"git_diff_failed: {cp.stderr.strip()}")
    out = [x.strip() for x in cp.stdout.splitlines() if x.strip()]
    return [_normalize_rel(x) for x in out]


def _get_all_tracked_paths(repo_root: Path) -> list[str]:
    cp = _run_git(repo_root, ["ls-files"])
    if cp.returncode != 0:
        raise RuntimeError(f"git_ls_files_failed: {cp.stderr.strip()}")
    out = [x.strip() for x in cp.stdout.splitlines() if x.strip()]
    return [_normalize_rel(x) for x in out]


def _get_staged_content(repo_root: Path, rel_path: str) -> bytes:
    cp = _run_git_bytes(repo_root, ["show", f":{rel_path}"])
    if cp.returncode != 0:
        raise RuntimeError(f"git_show_failed:{rel_path}:{cp.stderr.decode(errors='ignore').strip()}")
    return bytes(cp.stdout or b"")


def _get_worktree_content(repo_root: Path, rel_path: str) -> bytes:
    target = repo_root / rel_path
    if not target.exists() or not target.is_file():
        return b""
    return target.read_bytes()


def _scan_paths(repo_root: Path, paths: list[str], *, staged: bool) -> list[Finding]:
    findings: list[Finding] = []

    for rel in paths:
        if _normalize_rel(rel) in ALLOWLIST_EXACT_FILES:
            continue

        if _is_forbidden_env_file(rel):
            findings.append(Finding(_normalize_rel(rel), 1, "forbidden_env_file", ".env file must not be committed"))
            continue

        raw = _get_staged_content(repo_root, rel) if staged else _get_worktree_content(repo_root, rel)
        if not raw:
            continue

        if b"\x00" in raw:
            continue
        text = raw.decode("utf-8", errors="ignore")
        findings.extend(_scan_text(rel, text))

    return findings


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Fail-closed secret gate for local pre-commit and CI.")
    parser.add_argument("--staged", action="store_true", help="Scan staged content only.")
    parser.add_argument("--all", action="store_true", help="Scan all tracked files in the repository.")
    args = parser.parse_args(argv)

    if args.staged and args.all:
        print("secret_guard_error:choose_one_scope", file=sys.stderr)
        return 2

    repo_root = _repo_root_from_script()
    if args.all:
        paths = _get_all_tracked_paths(repo_root)
        findings = _scan_paths(repo_root, paths, staged=False)
    else:
        paths = _get_staged_paths(repo_root)
        if not paths:
            print("secret_guard_ok:no_staged_changes")
            return 0
        findings = _scan_paths(repo_root, paths, staged=True)

    if not findings:
        print("secret_guard_ok")
        return 0

    print("secret_guard_failed")
    for f in findings[:200]:
        print(f"- {f.code}:{f.path}:{f.line}:{f.detail}")
    if len(findings) > 200:
        print(f"- findings_truncated:{len(findings)}")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
ALLOWLIST_EXACT_FILES = {
    "services/api/tests/test_prod_gate.py",
}
