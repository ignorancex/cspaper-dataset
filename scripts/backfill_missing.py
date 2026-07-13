#!/usr/bin/env python
"""Backfill underfilled venue/year cells in data/papers.csv using DBLP."""

from __future__ import annotations

import argparse
import csv
import shutil
import time
from pathlib import Path

from collect_papers import COLUMNS, DEFAULT_OUTPUT, DEFAULT_VENUES, query_dblp_toc, read_venues, row_key


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
    parser.add_argument("--csv", default=str(DEFAULT_OUTPUT))
    parser.add_argument("--venues", default=str(DEFAULT_VENUES))
    parser.add_argument("--years", default="2020-2026")
    parser.add_argument("--per-year", type=int, default=5)
    parser.add_argument("--sleep", type=float, default=1.5)
    parser.add_argument("--max-cells", type=int, default=0, help="0 means no limit")
    parser.add_argument("--start-venue", default="", help="skip venues before this venue name")
    args = parser.parse_args()

    csv_path = Path(args.csv).resolve()
    rows = read_rows(csv_path)
    seen = {row_key(row) for row in rows}
    venues = read_venues(Path(args.venues))
    years = parse_years(args.years)
    touched = 0

    started = not args.start_venue
    for venue in venues:
        if not started:
            started = venue.venue == args.start_venue
        if not started:
            continue
        for year in years:
            current = sum(
                1
                for row in rows
                if row["会议或期刊名"] == venue.venue and row["年份"] == str(year)
            )
            if current >= args.per_year:
                continue
            if args.max_cells and touched >= args.max_cells:
                write_rows(csv_path, rows)
                print(f"[done] max cells reached; rows={len(rows)}")
                return 0
            needed = args.per_year - current
            additions = []
            for row in query_dblp_toc(venue, year, needed):
                key = row_key(row)
                if key in seen:
                    continue
                seen.add(key)
                additions.append(row)
            if additions:
                rows.extend(additions)
                touched += 1
                print(f"[backfill] {venue.venue} {year}: +{len(additions)}")
                write_rows(csv_path, rows)
            else:
                print(f"[miss] {venue.venue} {year}: still {current}/{args.per_year}")
            time.sleep(args.sleep)

    write_rows(csv_path, rows)
    print(f"[done] rows={len(rows)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
