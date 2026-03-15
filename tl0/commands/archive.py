"""Archive the task tracking directory — zip contents and reset to empty."""

import argparse
import shutil
import sys
import zipfile
from datetime import date
from pathlib import Path

from tl0.common import TASKS_DIR, git_commit


def main(argv: list[str] | None = None):
    parser = argparse.ArgumentParser(description="Archive tasks and reset the tracking directory")
    parser.add_argument("--force", action="store_true", help="Skip confirmation")
    args = parser.parse_args(argv)

    # Check there's something to archive
    contents = [p for p in TASKS_DIR.iterdir() if p.name not in (".git", ".cache")]
    has_files = any(p.is_file() or any(p.iterdir()) for p in contents if p.exists())
    if not has_files:
        print("Nothing to archive — task tracking directory is already empty.")
        return

    if not args.force:
        print(
            "This will archive and then empty the task tracking directory.\n"
            f"  Tasks dir: {TASKS_DIR}\n"
            "Pass --force to confirm.",
            file=sys.stderr,
        )
        sys.exit(1)

    # Build archive path
    dir_name = TASKS_DIR.name
    today = date.today().isoformat()
    archive_dir = TASKS_DIR.parent / "task-archives"
    archive_dir.mkdir(parents=True, exist_ok=True)
    archive_path = archive_dir / f"{dir_name}-{today}.zip"

    # Avoid overwriting an existing archive
    if archive_path.exists():
        stem = f"{dir_name}-{today}"
        counter = 2
        while archive_path.exists():
            archive_path = archive_dir / f"{stem}-{counter}.zip"
            counter += 1

    # Zip contents (skip .git and .cache)
    with zipfile.ZipFile(archive_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for path in sorted(TASKS_DIR.rglob("*")):
            rel = path.relative_to(TASKS_DIR)
            # Skip .git and .cache directories
            if rel.parts[0] in (".git", ".cache"):
                continue
            if path.is_file():
                zf.write(path, rel)

    print(f"Archived to {archive_path}")

    # Clear contents (preserve .git)
    for item in TASKS_DIR.iterdir():
        if item.name == ".git":
            continue
        if item.is_dir():
            shutil.rmtree(item)
        else:
            item.unlink()

    # Re-create empty structure
    (TASKS_DIR / "tasks").mkdir()
    (TASKS_DIR / "transcripts").mkdir()

    git_commit(f"archive: archived and reset task tracking directory")
    print("Task tracking directory has been reset to empty.")
