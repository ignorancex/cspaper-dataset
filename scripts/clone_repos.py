#!/usr/bin/env python
"""Clone GitHub repositories listed in a paper CSV."""

from __future__ import annotations

import argparse
import csv
import os
import re
import shutil
import time
from pathlib import Path

from collect_papers import COLUMNS
from download_assets import DOWNLOAD_ROOT, ROOT, clone_repo, slugify


def read_rows(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def write_rows(path: Path, rows: list[dict[str, str]]) -> None:
    path = path.resolve()
    tmp_path = path.with_suffix(path.suffix + ".tmp")
    with tmp_path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=COLUMNS)
        writer.writeheader()
        writer.writerows(rows)
    for attempt in range(5):
        try:
            tmp_path.replace(path)
            return
        except PermissionError:
            time.sleep(0.5 * (attempt + 1))
    shutil.copyfile(tmp_path, path)


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


def rewrite_clone_url(repo_url: str) -> str:
    prefix = os.environ.get("GITHUB_CLONE_PREFIX", "").strip()
    if not prefix:
        return repo_url
    if "{url}" in prefix:
        return prefix.format(url=repo_url)
    if repo_url.startswith("https://github.com/") and prefix.rstrip("/").endswith("github.com"):
        return prefix.rstrip("/") + repo_url.removeprefix("https://github.com")
    return prefix.rstrip("/") + "/" + repo_url


def cloneable_repo_url(repo_url: str) -> str:
    github_match = re.match(r"https?://github\.com/([^/\s]+)/([^/\s#?]+)", repo_url)
    if github_match:
        owner, repo = github_match.groups()
        repo = repo.removesuffix(".git")
        return f"https://github.com/{owner}/{repo}"
    gitlab_match = re.match(r"https?://gitlab\.com/([^/\s]+/[^/\s#?]+)", repo_url)
    if gitlab_match:
        return f"https://gitlab.com/{gitlab_match.group(1).removesuffix('.git')}"
    if repo_url.endswith(".git"):
        return repo_url
    return ""


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--csv", default=str(ROOT / "data" / "papers_with_code.csv"))
    parser.add_argument("--max-items", type=int, default=0, help="0 means all")
    parser.add_argument("--timeout", type=int, default=180)
    parser.add_argument("--skip-url", action="append", default=[])
    args = parser.parse_args()

    csv_path = Path(args.csv)
    rows = read_rows(csv_path)
    cloned = 0
    attempted = 0
    for row in rows:
        repo_url = row.get("代码仓库", "")
        if not repo_url:
            continue
        if repo_url in set(args.skip_url):
            append_note(row, "repo clone skipped")
            continue
        local_dir = local_dir_for(row)
        repo_dir = local_dir / "repo"
        if repo_dir.exists():
            row["本地的下载路径"] = str(local_dir.relative_to(ROOT)).replace(os.sep, "/")
            cloned += 1
            continue
        if args.max_items and attempted >= args.max_items:
            break
        repo_url = cloneable_repo_url(repo_url)
        if not repo_url:
            append_note(row, "code link is a project page; repo clone pending")
            continue
        attempted += 1
        clone_url = rewrite_clone_url(repo_url)
        ok = clone_repo(clone_url, repo_dir, timeout=args.timeout)
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
