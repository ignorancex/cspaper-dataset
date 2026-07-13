#!/usr/bin/env python
"""Build a GitHub-backed paper subset from data/papers.csv.

The script keeps rows that already have a GitHub URL and uses the GitHub
repository search API as a conservative best-effort fallback for missing repos.
It writes the same CSV schema as the main table.
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import re
import time
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any

from collect_papers import COLUMNS


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_INPUT = ROOT / "data" / "papers.csv"
DEFAULT_OUTPUT = ROOT / "data" / "papers_with_code.csv"
CACHE_PATH = ROOT / ".cache" / "github_repo_search.json"
ARXIV_CACHE_PATH = ROOT / ".cache" / "arxiv_title_search.json"
USER_AGENT = "cspaper-dataset/0.1"
ARXIV_NS = {"atom": "http://www.w3.org/2005/Atom"}

STOPWORDS = {
    "with",
    "from",
    "into",
    "using",
    "towards",
    "toward",
    "based",
    "learning",
    "model",
    "models",
    "network",
    "networks",
    "deep",
    "data",
    "paper",
    "method",
    "approach",
    "analysis",
    "system",
}

BAD_REPO_TERMS = {
    "awesome",
    "survey",
    "paper-list",
    "papers",
    "paper-reading",
    "reading-list",
    "literature",
    "collection",
    "benchmark-list",
    "review",
    "tutorial",
}


def log(message: str) -> None:
    print(message, flush=True)


def load_cache() -> dict[str, Any]:
    if CACHE_PATH.exists():
        return json.loads(CACHE_PATH.read_text(encoding="utf-8"))
    return {}


def load_json(path: Path) -> dict[str, Any]:
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8"))
    return {}


def save_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, sort_keys=True), encoding="utf-8")


def save_cache(cache: dict[str, Any]) -> None:
    CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
    CACHE_PATH.write_text(json.dumps(cache, indent=2, sort_keys=True), encoding="utf-8")


def normalize_title(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", value.lower())


def arxiv_repo_for_title(title: str, cache: dict[str, Any]) -> tuple[str, str]:
    cache_key = title.lower()
    if cache_key in cache:
        item = cache[cache_key]
        return item.get("repo", ""), item.get("note", "")
    params = urllib.parse.urlencode(
        {
            "search_query": f'ti:"{title}"',
            "start": "0",
            "max_results": "1",
            "sortBy": "relevance",
            "sortOrder": "descending",
        }
    )
    url = "https://export.arxiv.org/api/query?" + params
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    repo = ""
    note = ""
    try:
        with urllib.request.urlopen(req, timeout=30) as response:
            root = ET.fromstring(response.read())
    except Exception:
        cache[cache_key] = {"repo": "", "note": ""}
        save_json(ARXIV_CACHE_PATH, cache)
        return "", ""
    entry = root.find("atom:entry", ARXIV_NS)
    if entry is not None:
        entry_title = entry.findtext("atom:title", default="", namespaces=ARXIV_NS)
        summary = entry.findtext("atom:summary", default="", namespaces=ARXIV_NS)
        entry_id = entry.findtext("atom:id", default="", namespaces=ARXIV_NS)
        if normalize_title(entry_title) == normalize_title(title):
            match = re.search(r"https?://github\.com/[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", summary)
            if match:
                repo = match.group(0).rstrip(".,;)")
                arxiv_id = entry_id.rstrip("/").rsplit("/", 1)[-1] if entry_id else ""
                note = f"arXiv abstract repo match; arXiv:{arxiv_id}"
    cache[cache_key] = {"repo": repo, "note": note}
    save_json(ARXIV_CACHE_PATH, cache)
    return repo, note


def read_rows(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def write_rows(path: Path, rows: list[dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=COLUMNS)
        writer.writeheader()
        writer.writerows(rows)


def title_tokens(title: str) -> set[str]:
    tokens = set()
    for token in re.findall(r"[A-Za-z0-9]+", title.lower()):
        if len(token) < 4 or token in STOPWORDS:
            continue
        tokens.add(token)
    return tokens


def repo_text(repo: dict[str, Any]) -> str:
    parts = [
        repo.get("name") or "",
        repo.get("full_name") or "",
        repo.get("description") or "",
    ]
    return " ".join(parts).lower()


def repo_name_text(repo: dict[str, Any]) -> str:
    return " ".join([repo.get("name") or "", repo.get("full_name") or ""]).lower()


def score_repo(title: str, repo: dict[str, Any]) -> float:
    tokens = title_tokens(title)
    if not tokens:
        return 0.0
    text = repo_text(repo)
    name_text = repo_name_text(repo)
    if any(term in text for term in BAD_REPO_TERMS):
        return 0.0
    name_overlap = sum(1 for token in tokens if token in name_text)
    if name_overlap == 0:
        return 0.0
    overlap = sum(1 for token in tokens if token in text)
    ratio = overlap / max(len(tokens), 1)
    name_ratio = name_overlap / max(len(tokens), 1)
    stars = min(float(repo.get("stargazers_count") or 0), 1000.0) / 1000.0
    exactish = 0.5 if re.sub(r"[^a-z0-9]+", "", title.lower())[:18] in re.sub(r"[^a-z0-9]+", "", text) else 0.0
    return 0.6 * ratio + 0.8 * name_ratio + 0.2 * stars + exactish


def github_search(title: str, token: str, cache: dict[str, Any]) -> tuple[list[dict[str, Any]], bool]:
    cache_key = title.lower()
    if cache_key in cache:
        return cache[cache_key], True
    query = f"{title} in:name,description,readme"
    params = urllib.parse.urlencode(
        {
            "q": query,
            "sort": "stars",
            "order": "desc",
            "per_page": "5",
        }
    )
    url = "https://api.github.com/search/repositories?" + params
    headers = {
        "User-Agent": USER_AGENT,
        "Accept": "application/vnd.github+json",
    }
    if token:
        headers["Authorization"] = f"Bearer {token}"
    req = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=30) as response:
            data = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        if exc.code in {403, 429}:
            reset = exc.headers.get("x-ratelimit-reset")
            raise RuntimeError(f"GitHub rate limited; reset={reset}") from exc
        raise
    items = data.get("items", [])
    cache[cache_key] = items
    save_cache(cache)
    return items, False


def best_repo_for_title(title: str, token: str, cache: dict[str, Any], min_score: float) -> tuple[str, str, bool]:
    repos, cached = github_search(title, token, cache)
    scored = sorted(((score_repo(title, repo), repo) for repo in repos), key=lambda item: item[0], reverse=True)
    if not scored or scored[0][0] < min_score:
        return "", "", cached
    repo = scored[0][1]
    note = f"GitHub search candidate; stars={repo.get('stargazers_count', 0)}; score={scored[0][0]:.2f}"
    return repo.get("html_url", ""), note, cached


def append_note(row: dict[str, str], note: str) -> None:
    if not note:
        return
    row["备注"] = f"{row.get('备注', '')}; {note}".strip("; ")


def build(args: argparse.Namespace) -> list[dict[str, str]]:
    rows = read_rows(Path(args.input))
    cache = load_cache()
    arxiv_cache = load_json(ARXIV_CACHE_PATH)
    token = os.environ.get("GITHUB_TOKEN", "")
    grouped: dict[tuple[str, str], list[dict[str, str]]] = {}
    for row in rows:
        grouped.setdefault((row["会议或期刊名"], row["年份"]), []).append(row)

    output: list[dict[str, str]] = []
    queries = 0
    for key in sorted(grouped):
        selected: list[dict[str, str]] = []
        candidates = grouped[key]
        for row in candidates:
            if row.get("代码仓库"):
                selected.append(dict(row))
                if len(selected) >= args.per_cell:
                    break
        for row in candidates:
            if len(selected) >= args.per_cell:
                break
            if row.get("代码仓库"):
                continue
            repo_url, note = arxiv_repo_for_title(row["文章名"], arxiv_cache)
            if repo_url:
                new_row = dict(row)
                new_row["代码仓库"] = repo_url
                append_note(new_row, note)
                selected.append(new_row)
                log(f"[arxiv-repo] {key[0]} {key[1]}: {new_row['文章名']} -> {repo_url}")
                time.sleep(args.arxiv_sleep)
                continue
            time.sleep(args.arxiv_sleep)
            if args.max_queries and queries >= args.max_queries:
                continue
            try:
                repo_url, note, cached = best_repo_for_title(row["文章名"], token, cache, args.min_score)
                if not cached:
                    queries += 1
            except RuntimeError as exc:
                log(f"[stop] {exc}")
                return output
            except Exception as exc:
                log(f"[warn] search failed: {row['文章名']} ({exc})")
                queries += 1
                continue
            if not cached:
                time.sleep(args.sleep)
            if not repo_url:
                continue
            new_row = dict(row)
            new_row["代码仓库"] = repo_url
            append_note(new_row, note)
            selected.append(new_row)
            log(f"[repo] {key[0]} {key[1]}: {new_row['文章名']} -> {repo_url}")
        output.extend(selected[: args.per_cell])
        if selected:
            log(f"[cell] {key[0]} {key[1]}: {len(selected[:args.per_cell])}")
        write_rows(Path(args.output), output)
    log(f"[done] wrote {len(output)} rows to {args.output}; queries={queries}")
    return output


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", default=str(DEFAULT_INPUT))
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT))
    parser.add_argument("--per-cell", type=int, default=5)
    parser.add_argument("--max-queries", type=int, default=80)
    parser.add_argument("--min-score", type=float, default=0.45)
    parser.add_argument("--sleep", type=float, default=6.5)
    parser.add_argument("--arxiv-sleep", type=float, default=3.0)
    args = parser.parse_args()
    build(args)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
