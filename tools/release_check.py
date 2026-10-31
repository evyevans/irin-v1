"""Limited, local release scan. Never prints a matching value or file content.

Use --deny-file with an external JSON array of private terms for a one-off
release audit. Keep that deny file outside the public release tree.
"""

import argparse
import hashlib
import json
from pathlib import Path
import re
import sys

SKIP = {".git", "__pycache__", "demo-output", ".venv"}
# Explicitly reviewed public artwork. Other binary formats remain rejected.
REVIEWED_PUBLIC_IMAGES = {"assets/irin-banner.jpg"}
PATTERNS = [
    (
        "credential-like token",
        r"\b(?:gh[pousr]_[A-Za-z0-9]{30,}|github_pat_[A-Za-z0-9_]{30,}|AKIA[0-9A-Z]{16}|xox[baprs]-[A-Za-z0-9-]{20,}|sk-[A-Za-z0-9_-]{24,}|sb_secret_[A-Za-z0-9_-]{20,})\b",
    ),
    ("private key", r"-----BEGIN (?:[A-Z ]+ )?PRIVATE KEY-----"),
    (
        "JWT-like token",
        r"\beyJ[A-Za-z0-9_-]{20,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\b",
    ),
    ("database connection", r"postgres(?:ql)?://[^\s]+|\b[a-z0-9]{20}\.supabase\.co\b"),
    ("local user path", r"/(?:Users|home)/[^\s/]+/"),
]


def main():
    parser = argparse.ArgumentParser(
        description="Limited local privacy and release integrity check"
    )
    parser.add_argument(
        "--root", type=Path, default=Path(__file__).resolve().parents[1]
    )
    parser.add_argument("--deny-file", type=Path)
    args = parser.parse_args()
    root = args.root.resolve()
    try:
        terms = (
            json.loads(args.deny_file.read_text(encoding="utf-8"))
            if args.deny_file
            else []
        )
        if not isinstance(terms, list) or any(
            not isinstance(term, str) or not term for term in terms
        ):
            raise ValueError
        manifest_path = root / "RELEASE_FILES.json"
        manifest = (
            json.loads(manifest_path.read_text(encoding="utf-8"))
            if manifest_path.exists()
            else None
        )
        failures, checked, actual = set(), 0, set()
        for path in sorted(root.rglob("*")):
            rel = path.relative_to(root)
            if any(part in SKIP for part in rel.parts) or path == args.deny_file:
                continue
            if path.is_symlink():
                failures.add("symlinks are not allowed in the release")
                continue
            if not path.is_file():
                continue
            actual.add(rel.as_posix())
            checked += 1
            if path.stat().st_size > 2_000_000:
                failures.add("file exceeds the 2 MB release limit")
                continue
            try:
                raw = path.read_bytes()
                text = raw.decode("utf-8")
            except UnicodeDecodeError:
                if rel.as_posix() in REVIEWED_PUBLIC_IMAGES:
                    if not raw.startswith(b"\xff\xd8\xff"):
                        failures.add("reviewed image has an invalid JPEG signature")
                    if manifest is not None and manifest.get(
                        rel.as_posix()
                    ) != hashlib.sha256(raw).hexdigest():
                        failures.add("reviewed image manifest missing or mismatched")
                    continue
                failures.add("non-text file requires explicit manual review")
                continue
            if any(
                term.casefold() in (rel.as_posix() + "\n" + text).casefold()
                for term in terms
            ):
                failures.add("private term match")
            if (
                any(
                    part
                    in {".remember", "private", "local-data", "node_modules", "exports"}
                    for part in rel.parts
                )
                or (path.name.startswith(".env") and path.name != ".env.example")
                or (
                    path.suffix
                    in {".pem", ".key", ".p12", ".pdf", ".png", ".jpg", ".gif"}
                    and rel.as_posix() not in REVIEWED_PUBLIC_IMAGES
                )
            ):
                failures.add("private, runtime, credential or unreviewed binary path")
            for label, pattern in PATTERNS:
                if re.search(pattern, text):
                    failures.add(label)
            if path.name == ".env.example" and any(
                line.strip()
                and not line.lstrip().startswith("#")
                and ("=" not in line or line.partition("=")[2].strip())
                for line in text.splitlines()
            ):
                failures.add("non-empty or malformed environment template")
            addresses = re.findall(
                r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}", text
            )
            if any(
                not address.lower().endswith(
                    ("@example.com", "@example.org", "@example.net", ".invalid")
                )
                for address in addresses
            ):
                failures.add("non-example email address")
            if manifest is not None and rel.as_posix() != "RELEASE_FILES.json":
                if manifest.get(rel.as_posix()) != hashlib.sha256(raw).hexdigest():
                    failures.add("release manifest missing or mismatched file")
        if manifest is not None and set(manifest) != actual - {"RELEASE_FILES.json"}:
            failures.add("release manifest file inventory mismatch")
        if failures:
            for label in sorted(failures):
                print(f"FAIL: {label}")
            print(f"Checked {checked} files. Matching values are redacted.")
            return 1
        print(
            f"PASS: {checked} release files; no configured pattern matches"
            + ("; manifest verified." if manifest is not None else ".")
        )
        print(
            "Limited scan only. Dedicated secret scanning and manual review are still required before publication."
        )
        return 0
    except (OSError, ValueError, TypeError):
        print(
            "FAIL: scanner input or manifest could not be read safely.", file=sys.stderr
        )
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
