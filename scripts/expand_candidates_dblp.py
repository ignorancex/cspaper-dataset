#!/usr/bin/env python
"""Expand paper candidates using DBLP TOC XML/API fallback."""

from __future__ import annotations

import argparse
import csv
import shutil
import time
from pathlib import Path

from collect_papers import COLUMNS, DEFAULT_VENUES, query_dblp_toc, read_venues, row_key


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_INPUT = ROOT / "data" / "papers.csv"
DEFAULT_OUTPUT = ROOT / "data" / "papers_candidates.csv"


def read_rows(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def write_rows(path: Path, rows: list[dict[str, str]]) -> None:
    path = path.resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
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


def parse_years(value: str) -> list[int]:
    if "-" in value:
        start, end = value.split("-", 1)
        return list(range(int(start), int(end) + 1))
    return [int(part.strip()) for part in value.split(",") if part.strip()]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", default=str(DEFAULT_INPUT))
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT))
    parser.add_argument("--venues", default=str(DEFAULT_VENUES))
    parser.add_argument("--years", default="2020-2026")
    parser.add_argument("--per-cell", type=int, default=50)
    parser.add_argument("--sleep", type=float, default=0.5)
    parser.add_argument("--start-venue", default="")
    args = parser.parse_args()

    rows = read_rows(Path(args.input))
    seen = {row_key(row) for row in rows}
    venues = read_venues(Path(args.venues))
    years = parse_years(args.years)
    started = not args.start_venue

    for venue in venues:
        if not started:
            started = venue.venue == args.start_venue
        if not started:
            continue
        for year in years:
            current = [
                row
                for row in rows
                if row["会议或期刊名"] == venue.venue and row["年份"] == str(year)
            ]
            if len(current) >= args.per_cell:
                continue
            needed = args.per_cell - len(current)
            additions: list[dict[str, str]] = []
            for row in query_dblp_toc(venue, year, needed):
                key = row_key(row)
                if key in seen:
                    continue
                seen.add(key)
                additions.append(row)
            if additions:
                rows.extend(additions)
                write_rows(Path(args.output), rows)
                print(f"[expand] {venue.venue} {year}: +{len(additions)} -> {len(current) + len(additions)}", flush=True)
            else:
                print(f"[miss] {venue.venue} {year}: {len(current)}/{args.per_cell}", flush=True)
            time.sleep(args.sleep)

    write_rows(Path(args.output), rows)
    print(f"[done] rows={len(rows)}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
