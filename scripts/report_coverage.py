#!/usr/bin/env python
"""Report code-backed paper coverage by venue/year."""

from __future__ import annotations

import argparse
import csv
from pathlib import Path

from download_assets import ROOT


def read_rows(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def local_dir(row: dict[str, str]) -> Path | None:
    value = row.get("本地的下载路径", "").strip()
    if not value:
        return None
    return ROOT / value


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--csv", default=str(ROOT / "data" / "papers_with_code.csv"))
    parser.add_argument("--output", default=str(ROOT / "data" / "code_backed_coverage.csv"))
    args = parser.parse_args()

    rows = read_rows(Path(args.csv))
    stats: dict[tuple[str, str], dict[str, int]] = {}
    for row in rows:
        key = (row["会议或期刊名"], row["年份"])
        item = stats.setdefault(key, {"code_count": 0, "pdf_count": 0, "repo_count": 0})
        if row.get("代码仓库", "").strip():
            item["code_count"] += 1
        base = local_dir(row)
        if base and (base / "paper.pdf").exists():
            item["pdf_count"] += 1
        if base and (base / "repo").exists():
            item["repo_count"] += 1

    out_path = Path(args.output)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w", encoding="utf-8-sig", newline="") as handle:
        fieldnames = ["会议或期刊名", "年份", "带开源仓库的文章数", "本地PDF数", "本地仓库数"]
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for (venue, year), item in sorted(stats.items()):
            writer.writerow(
                {
                    "会议或期刊名": venue,
                    "年份": year,
                    "带开源仓库的文章数": item["code_count"],
                    "本地PDF数": item["pdf_count"],
                    "本地仓库数": item["repo_count"],
                }
            )

    total_code = sum(item["code_count"] for item in stats.values())
    total_pdf = sum(item["pdf_count"] for item in stats.values())
    total_repo = sum(item["repo_count"] for item in stats.values())
    print(f"[done] cells={len(stats)} code={total_code} pdf={total_pdf} repo={total_repo}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
