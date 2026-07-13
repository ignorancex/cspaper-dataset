#!/usr/bin/env python
"""Clone GitHub repositories listed in a paper CSV."""

from __future__ import annotations

import argparse
import csv
import os
from pathlib import Path

from collect_papers import COLUMNS
from download_assets import DOWNLOAD_ROOT, ROOT, clone_repo, slugify


def read_rows(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def write_rows(path: Path, rows: list[dict[str, str]]) -> None:
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=COLUMNS)
        writer.writeheader()
        writer.writerows(rows)


def append_note(row: dict[str, str], note: str) -> None:
    existing = row.get("备注", "")
    if note in existing:
        return
    row["备注"] = f"{existing}; {note}".strip("; ")


def local_dir_for(row: dict[str, str]) -> Path:
    if row.get("本地的下载路径"):
        return ROOT / row["本地的下载路径"]
    venue = slugify(row["会议或期刊名"])
    title = slugify(row["文章名"])
    return DOWNLOAD_ROOT / venue / row["年份"] / title


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--csv", default=str(ROOT / "data" / "papers_with_code.csv"))
    parser.add_argument("--max-items", type=int, default=0, help="0 means all")
    parser.add_argument("--timeout", type=int, default=180)
    args = parser.parse_args()

    csv_path = Path(args.csv)
    rows = read_rows(csv_path)
    cloned = 0
    attempted = 0
    for row in rows:
        repo_url = row.get("代码仓库", "")
        if not repo_url:
            continue
        local_dir = local_dir_for(row)
        repo_dir = local_dir / "repo"
        if repo_dir.exists():
            row["本地的下载路径"] = str(local_dir.relative_to(ROOT)).replace(os.sep, "/")
            cloned += 1
            continue
        if args.max_items and attempted >= args.max_items:
            break
        attempted += 1
        ok = clone_repo(repo_url, repo_dir, timeout=args.timeout)
        if ok:
            row["本地的下载路径"] = str(local_dir.relative_to(ROOT)).replace(os.sep, "/")
            if not (local_dir / "paper.pdf").exists():
                append_note(row, "repo cloned; PDF pending")
            cloned += 1
            print(f"[clone] {cloned}: {row['会议或期刊名']} {row['年份']} {repo_url}", flush=True)
            write_rows(csv_path, rows)
    write_rows(csv_path, rows)
    print(f"[done] cloned_or_existing={cloned}; attempted={attempted}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

