#!/usr/bin/env python3
"""sync_from_factory.py — pull alive memories from factory into this repo.

One-way: factory -> memories. Runs on a 30-min systemd timer (planned) or
manually.

For each alive (dave, mira, art-director):
  1. Copy <FACTORY>/employees/<slug>/brain/MEMORY.md -> <REPO>/<slug>/brain/MEMORY.md
  2. Copy <FACTORY>/employees/<slug>/state.json -> <REPO>/<slug>/state.json
  3. Copy <FACTORY>/employees/<slug>/i_am_alive.md -> <REPO>/<slug>/i_am_alive.md
  4. Copy any world-journal/*.md entries -> <REPO>/<slug>/world-journal/
  5. Append current state.json as a line to <REPO>/<slug>/state-history.jsonl
     (with a `sync_ts` field added)
  6. If git status shows changes: commit with a timestamp + push

Safe re-entry: all ops are idempotent. No-op if nothing changed.

Run:
  python tools/sync_from_factory.py
  python tools/sync_from_factory.py --dry-run    # report changes, no writes
  python tools/sync_from_factory.py --no-push    # commit but don't push
"""
from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

FACTORY_EMPLOYEES = Path("/mnt/d/Ai-Employee Factory/factory/employees")
# Under WSL-compatible path; under Windows path (for standalone runs):
WIN_FACTORY_EMPLOYEES = Path("D:/Ai-Employee Factory/factory/employees")

# This repo root — derived from script location
REPO_ROOT = Path(__file__).resolve().parent.parent

ALIVES = ["dave", "mira", "art-director"]

# File categories — what we copy from the factory
SIMPLE_FILES = [
    "brain/MEMORY.md",
    "state.json",
    "i_am_alive.md",
]
# Directories — we mirror contents (.md files only)
MIRROR_DIRS = [
    "world-journal",
]


def _factory_root() -> Path:
    """Return the factory employees dir in whichever path style works."""
    if FACTORY_EMPLOYEES.exists():
        return FACTORY_EMPLOYEES
    if WIN_FACTORY_EMPLOYEES.exists():
        return WIN_FACTORY_EMPLOYEES
    sys.exit(f"Factory not found at {FACTORY_EMPLOYEES} or {WIN_FACTORY_EMPLOYEES}")


def _copy_if_changed(src: Path, dst: Path, dry_run: bool = False) -> bool:
    """Copy src -> dst if contents differ. Returns True if changed."""
    if not src.exists():
        return False
    dst.parent.mkdir(parents=True, exist_ok=True)
    if dst.exists():
        try:
            if src.read_bytes() == dst.read_bytes():
                return False
        except Exception:
            pass  # fall through to copy
    if dry_run:
        print(f"[dry-run] would copy: {src} -> {dst}")
        return True
    shutil.copy2(src, dst)
    print(f"  copied: {src.name} -> {dst.relative_to(REPO_ROOT)}")
    return True


def _append_state_history(slug: str, dry_run: bool = False) -> bool:
    """Append the current state.json (with sync_ts) to state-history.jsonl.

    Returns True if a line was appended.
    """
    src = _factory_root() / slug / "state.json"
    if not src.exists():
        return False
    try:
        state = json.loads(src.read_text(encoding="utf-8"))
    except Exception as e:
        print(f"  warn: couldn't parse {src}: {e}")
        return False
    state["sync_ts"] = datetime.now(timezone.utc).isoformat()
    line = json.dumps(state, separators=(",", ":"))

    history = REPO_ROOT / slug / "state-history.jsonl"
    # Dedupe: if last line's tick timestamp matches the new one, skip append
    # (state hasn't progressed since last sync)
    if history.exists():
        try:
            tail = history.read_text(encoding="utf-8").rstrip("\n").splitlines()[-1:]
            if tail:
                last = json.loads(tail[0])
                if last.get("last_tick_ts") == state.get("last_tick_ts"):
                    return False
        except Exception:
            pass

    if dry_run:
        print(f"[dry-run] would append state to: {history.relative_to(REPO_ROOT)}")
        return True
    history.parent.mkdir(parents=True, exist_ok=True)
    with history.open("a", encoding="utf-8") as f:
        f.write(line + "\n")
    print(f"  appended state -> {history.relative_to(REPO_ROOT)}")
    return True


def sync_alive(slug: str, dry_run: bool = False) -> bool:
    """Sync one alive. Returns True if any changes were made."""
    factory_dir = _factory_root() / slug
    if not factory_dir.exists():
        print(f"  skip {slug}: factory dir missing")
        return False
    repo_dir = REPO_ROOT / slug
    any_changed = False

    print(f"-- {slug} --")
    for rel in SIMPLE_FILES:
        src = factory_dir / rel
        dst = repo_dir / rel
        if _copy_if_changed(src, dst, dry_run):
            any_changed = True

    for rel_dir in MIRROR_DIRS:
        src_dir = factory_dir / rel_dir
        dst_dir = repo_dir / rel_dir
        if not src_dir.exists():
            continue
        for entry in sorted(src_dir.glob("*.md")):
            dst = dst_dir / entry.name
            if _copy_if_changed(entry, dst, dry_run):
                any_changed = True

    if _append_state_history(slug, dry_run):
        any_changed = True

    return any_changed


def git_commit_and_push(dry_run: bool = False, no_push: bool = False) -> None:
    """If the repo has changes, commit + push."""
    result = subprocess.run(
        ["git", "-C", str(REPO_ROOT), "status", "--porcelain"],
        capture_output=True, text=True,
    )
    if not result.stdout.strip():
        print("no changes to commit")
        return

    if dry_run:
        print(f"[dry-run] would commit: {result.stdout.count(chr(10))} files changed")
        return

    ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    subprocess.run(["git", "-C", str(REPO_ROOT), "add", "-A"], check=True)
    subprocess.run(
        ["git", "-C", str(REPO_ROOT), "commit", "-m", f"sync {ts}"],
        check=True,
    )
    print(f"committed: sync {ts}")
    if no_push:
        print("--no-push set; skipping push")
        return
    push = subprocess.run(
        ["git", "-C", str(REPO_ROOT), "push"],
        capture_output=True, text=True,
    )
    if push.returncode != 0:
        print(f"push failed: {push.stderr}")
    else:
        print("pushed")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true", help="report changes, make no writes")
    ap.add_argument("--no-push", action="store_true", help="commit but don't push")
    args = ap.parse_args()

    print(f"sync_from_factory: {datetime.now(timezone.utc).isoformat()}")
    print(f"  factory: {_factory_root()}")
    print(f"  repo:    {REPO_ROOT}")

    changed = False
    for alive in ALIVES:
        if sync_alive(alive, args.dry_run):
            changed = True

    if not args.dry_run and changed:
        git_commit_and_push(args.dry_run, args.no_push)
    elif not changed:
        print("no changes this run")


if __name__ == "__main__":
    main()
