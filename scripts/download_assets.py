#!/usr/bin/env python
"""Download selected PDFs, arXiv sources, and optional GitHub repositories."""

from __future__ import annotations

import argparse
import csv
import os
import re
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from urllib.parse import urlparse


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CSV = ROOT / "data" / "papers.csv"
DOWNLOAD_ROOT = ROOT / "downloads"
COLUMNS = [
    "领域",
    "年份",
    "会议或期刊名",
    "文章名",
    "链接",
    "代码仓库",
    "数据集或基准链接",
    "本地的下载路径",
    "文章类别",
    "备注",
]
USER_AGENT = "cspaper-dataset/0.1 (https://github.com/local/cspaper-dataset)"


def log(message: str) -> None:
    print(message, file=sys.stderr, flush=True)


def slugify(value: str, max_len: int = 80) -> str:
    value = re.sub(r"[^A-Za-z0-9]+", "-", value).strip("-").lower()
    return value[:max_len].strip("-") or "paper"


def infer_pdf_url(link: str) -> str:
    if not link:
        return ""
    if "arxiv.org/abs/" in link:
        arxiv_id = link.rstrip("/").rsplit("/", 1)[-1]
        return f"https://arxiv.org/pdf/{arxiv_id}.pdf"
    if "arxiv.org/pdf/" in link:
        return link if link.endswith(".pdf") else f"{link}.pdf"
    parsed = urlparse(link)
    if parsed.path.lower().endswith(".pdf"):
        return link
    return ""


def infer_arxiv_source_url(link: str) -> str:
    if "arxiv.org/abs/" not in link:
        return ""
    arxiv_id = link.rstrip("/").rsplit("/", 1)[-1]
    return f"https://arxiv.org/e-print/{arxiv_id}"


def download_file(url: str, output: Path, timeout: int = 60) -> bool:
    if not url:
        return False
    if output.exists() and output.stat().st_size > 0:
        return True
    output.parent.mkdir(parents=True, exist_ok=True)
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as response:
            data = response.read()
    except (TimeoutError, urllib.error.URLError, urllib.error.HTTPError) as exc:
        log(f"[warn] download failed: {url} ({exc})")
        return False
    output.write_bytes(data)
    return output.exists() and output.stat().st_size > 0


def clone_repo(repo_url: str, dest: Path) -> bool:
    if not repo_url:
        return False
    if dest.exists():
        return True
    dest.parent.mkdir(parents=True, exist_ok=True)
    result = subprocess.run(
        ["git", "clone", "--depth", "1", repo_url, str(dest)],
        cwd=str(ROOT),
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        check=False,
    )
    if result.returncode != 0:
        log(f"[warn] git clone failed for {repo_url}: {result.stdout.strip()}")
        return False
    return True


def read_rows(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def write_rows(path: Path, rows: list[dict[str, str]]) -> None:
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=COLUMNS)
        writer.writeheader()
        writer.writerows(rows)


def eligible_rows(rows: list[dict[str, str]], prefer_github: bool) -> list[int]:
    indexed = list(range(len(rows)))
    if prefer_github:
        indexed.sort(key=lambda i: (0 if rows[i].get("代码仓库") else 1, i))
    return indexed


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--csv", default=str(DEFAULT_CSV))
    parser.add_argument("--max-items", type=int, default=30)
    parser.add_argument("--clone-repos", action="store_true")
    parser.add_argument("--prefer-github", action="store_true", default=True)
    parser.add_argument("--sleep", type=float, default=0.5)
    args = parser.parse_args()

    csv_path = Path(args.csv)
    rows = read_rows(csv_path)
    downloaded = 0

    for index in eligible_rows(rows, args.prefer_github):
        if downloaded >= args.max_items:
            break
        row = rows[index]
        if row.get("本地的下载路径"):
            continue

        pdf_url = infer_pdf_url(row.get("链接", ""))
        if not pdf_url:
            continue

        venue = slugify(row["会议或期刊名"])
        title = slugify(row["文章名"])
        year = row["年份"]
        local_dir = DOWNLOAD_ROOT / venue / year / title
        pdf_ok = download_file(pdf_url, local_dir / "paper.pdf")
        if not pdf_ok:
            continue

        source_url = infer_arxiv_source_url(row.get("链接", ""))
        if source_url:
            download_file(source_url, local_dir / "source.tar")

        if args.clone_repos and row.get("代码仓库"):
            clone_repo(row["代码仓库"], local_dir / "repo")

        row["本地的下载路径"] = str(local_dir.relative_to(ROOT)).replace(os.sep, "/")
        downloaded += 1
        write_rows(csv_path, rows)
        log(f"[download] {downloaded}/{args.max_items}: {row['会议或期刊名']} {year} {row['文章名']}")
        time.sleep(args.sleep)

    write_rows(csv_path, rows)
    log(f"[done] downloaded {downloaded} items")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
