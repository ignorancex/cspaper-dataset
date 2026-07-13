#!/usr/bin/env python
"""Collect CS venue/year paper metadata for a reproduction benchmark.

The script uses OpenAlex for broad metadata and arXiv for best-effort PDF/source
enrichment. It intentionally avoids aggressive scraping and keeps repository
discovery conservative.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import re
import ssl
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_VENUES = ROOT / "configs" / "venues.csv"
DEFAULT_OUTPUT = ROOT / "data" / "papers.csv"
CACHE_DIR = ROOT / ".cache"
OPENALEX_CACHE = CACHE_DIR / "openalex_sources.json"

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
ARXIV_NS = {"atom": "http://www.w3.org/2005/Atom"}
DBLP_SSL_CONTEXT = ssl._create_unverified_context()

DBLP_TOC_PATTERNS = {
    "AAAI": ["conf/aaai/aaai{year}"],
    "IJCAI": ["conf/ijcai/ijcai{year}"],
    "ICML": ["conf/icml/icml{year}"],
    "ICLR": ["conf/iclr/iclr{year}"],
    "NeurIPS": ["conf/nips/neurips{year}"],
    "CVPR": ["conf/cvpr/cvpr{year}"],
    "ICCV": ["conf/iccv/iccv{year}"],
    "ECCV": ["conf/eccv/eccv{year}"],
    "ACL": ["conf/acl/acl{year}"],
    "EMNLP": ["conf/emnlp/emnlp{year}"],
    "NAACL": ["conf/naacl/naacl{year}"],
    "ICSE": ["conf/icse/icse{year}"],
    "FSE": ["conf/sigsoft/fse{year}", "conf/sigsoft/esecfse{year}"],
    "ASE": ["conf/kbse/ase{year}"],
    "ISSTA": ["conf/issta/issta{year}"],
    "SIGCOMM": ["conf/sigcomm/sigcomm{year}"],
    "NSDI": ["conf/nsdi/nsdi{year}"],
    "MobiCom": ["conf/mobicom/mobicom{year}"],
    "SIGMOD": ["conf/sigmod/sigmod{year}"],
    "ICDE": ["conf/icde/icde{year}"],
    "OSDI": ["conf/osdi/osdi{year}"],
    "SOSP": ["conf/sosp/sosp{year}"],
    "USENIX ATC": ["conf/usenix/usenix{year}"],
    "EuroSys": ["conf/eurosys/eurosys{year}"],
    "USENIX Security": ["conf/uss/uss{year}"],
    "IEEE S&P": ["conf/sp/sp{year}"],
    "CCS": ["conf/ccs/ccs{year}"],
    "NDSS": ["conf/ndss/ndss{year}"],
    "ISCA": ["conf/isca/isca{year}"],
    "MICRO": ["conf/micro/micro{year}"],
    "ASPLOS": ["conf/asplos/asplos{year}"],
    "HPCA": ["conf/hpca/hpca{year}"],
    "CHI": ["conf/chi/chi{year}"],
    "UIST": ["conf/uist/uist{year}"],
    "CSCW": ["conf/cscw/cscw{year}"],
    "STOC": ["conf/stoc/stoc{year}"],
    "FOCS": ["conf/focs/focs{year}"],
    "SODA": ["conf/soda/soda{year}"],
}


@dataclass(frozen=True)
class Venue:
    area: str
    venue: str
    kind: str
    source_name: str
    aliases: tuple[str, ...]


def log(message: str) -> None:
    print(message, file=sys.stderr, flush=True)


def request_json(
    url: str,
    timeout: int = 30,
    retries: int = 3,
    context: ssl.SSLContext | None = None,
) -> dict[str, Any]:
    last_error: Exception | None = None
    for attempt in range(retries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
            with urllib.request.urlopen(req, timeout=timeout, context=context) as response:
                return json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            last_error = exc
            if exc.code == 429:
                time.sleep(2.5 * (attempt + 1))
                continue
            raise
        except (TimeoutError, urllib.error.URLError) as exc:
            last_error = exc
            time.sleep(1.5 * (attempt + 1))
    raise RuntimeError(f"request failed after retries: {url}") from last_error


def request_text(url: str, timeout: int = 30, retries: int = 2) -> str:
    last_error: Exception | None = None
    for attempt in range(retries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
            with urllib.request.urlopen(req, timeout=timeout) as response:
                return response.read().decode("utf-8", errors="replace")
        except (TimeoutError, urllib.error.URLError, urllib.error.HTTPError) as exc:
            last_error = exc
            time.sleep(1.5 * (attempt + 1))
    raise RuntimeError(f"text request failed after retries: {url}") from last_error


def request_bytes(
    url: str,
    timeout: int = 45,
    retries: int = 3,
    context: ssl.SSLContext | None = None,
) -> bytes:
    last_error: Exception | None = None
    for attempt in range(retries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
            with urllib.request.urlopen(req, timeout=timeout, context=context) as response:
                return response.read()
        except (TimeoutError, urllib.error.URLError, urllib.error.HTTPError) as exc:
            last_error = exc
            time.sleep(2.0 * (attempt + 1))
    raise RuntimeError(f"bytes request failed after retries: {url}") from last_error


def read_venues(path: Path) -> list[Venue]:
    venues: list[Venue] = []
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        for row in csv.DictReader(handle):
            aliases = tuple(
                item.strip()
                for item in (row.get("aliases") or row["venue"]).split(";")
                if item.strip()
            )
            venues.append(
                Venue(
                    area=row["area"].strip(),
                    venue=row["venue"].strip(),
                    kind=row["kind"].strip(),
                    source_name=row["openalex_source_name"].strip(),
                    aliases=aliases,
                )
            )
    return venues


def load_source_cache() -> dict[str, str]:
    if not OPENALEX_CACHE.exists():
        return {}
    return json.loads(OPENALEX_CACHE.read_text(encoding="utf-8"))


def save_source_cache(cache: dict[str, str]) -> None:
    OPENALEX_CACHE.parent.mkdir(parents=True, exist_ok=True)
    OPENALEX_CACHE.write_text(json.dumps(cache, indent=2, sort_keys=True), encoding="utf-8")


def resolve_openalex_source(venue: Venue, cache: dict[str, str]) -> str | None:
    if venue.venue in cache:
        return cache[venue.venue]

    filters = []
    if venue.kind in {"conference", "journal"}:
        filters.append(f"type:{venue.kind}")
    params = {
        "search": venue.source_name,
        "per-page": "10",
    }
    if filters:
        params["filter"] = ",".join(filters)
    url = "https://api.openalex.org/sources?" + urllib.parse.urlencode(params)
    data = request_json(url)
    candidates = data.get("results", [])
    if not candidates:
        log(f"[warn] no OpenAlex source for {venue.venue}")
        return None

    source = candidates[0]
    source_id = source["id"].rsplit("/", 1)[-1]
    cache[venue.venue] = source_id
    log(f"[source] {venue.venue}: {source.get('display_name')} ({source_id})")
    time.sleep(0.15)
    return source_id


def reconstruct_abstract(work: dict[str, Any]) -> str:
    inverted = work.get("abstract_inverted_index") or {}
    if not inverted:
        return ""
    pairs: list[tuple[int, str]] = []
    for word, positions in inverted.items():
        for pos in positions:
            pairs.append((int(pos), word))
    return " ".join(word for _, word in sorted(pairs))


def get_work_link(work: dict[str, Any]) -> str:
    locations = [
        work.get("best_oa_location") or {},
        work.get("primary_location") or {},
    ]
    for location in locations:
        for key in ("pdf_url", "landing_page_url"):
            value = location.get(key)
            if value:
                return value
    ids = work.get("ids") or {}
    return ids.get("doi") or ids.get("openalex") or work.get("id") or ""


def infer_category(title: str, abstract: str) -> str:
    text = f"{title} {abstract}".lower()
    if any(token in text for token in ("benchmark", "dataset", "corpus", "leaderboard", "evaluation suite")):
        return "bench/dataset型"
    if any(token in text for token in ("system", "platform", "framework", "runtime", "compiler", "operating system")):
        return "系统型"
    if any(token in text for token in ("survey", "review", "taxonomy")):
        return "综述型"
    if any(token in text for token in ("method", "approach", "algorithm", "model", "architecture", "training")):
        return "方法型"
    return ""


def extract_resource_link(abstract: str) -> str:
    for pattern in (
        r"https?://huggingface\.co/[^\s)>\]]+",
        r"https?://www\.kaggle\.com/[^\s)>\]]+",
        r"https?://zenodo\.org/[^\s)>\]]+",
        r"https?://doi\.org/10\.\d{4,9}/[^\s)>\]]+",
    ):
        match = re.search(pattern, abstract)
        if match:
            return match.group(0).rstrip(".,;")
    return ""


def extract_github_link(abstract: str) -> str:
    match = re.search(r"https?://github\.com/[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", abstract)
    return match.group(0).rstrip(".,;") if match else ""


def arxiv_search_by_title(title: str) -> dict[str, str]:
    query = f'ti:"{title}"'
    params = urllib.parse.urlencode(
        {
            "search_query": query,
            "start": "0",
            "max_results": "1",
            "sortBy": "relevance",
            "sortOrder": "descending",
        }
    )
    url = "https://export.arxiv.org/api/query?" + params
    try:
        xml_text = request_text(url, timeout=20, retries=1)
    except Exception:
        return {}
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError:
        return {}
    entry = root.find("atom:entry", ARXIV_NS)
    if entry is None:
        return {}
    entry_title = "".join(entry.findtext("atom:title", default="", namespaces=ARXIV_NS).split())
    target_title = "".join(title.split())
    if not entry_title or entry_title.lower() != target_title.lower():
        return {}
    entry_id = entry.findtext("atom:id", default="", namespaces=ARXIV_NS)
    arxiv_id = entry_id.rstrip("/").rsplit("/", 1)[-1] if entry_id else ""
    primary = entry.find("arxiv:primary_category", {"arxiv": "http://arxiv.org/schemas/atom"})
    category = primary.attrib.get("term", "") if primary is not None else ""
    return {
        "arxiv_id": arxiv_id,
        "arxiv_url": f"https://arxiv.org/abs/{arxiv_id}" if arxiv_id else "",
        "pdf_url": f"https://arxiv.org/pdf/{arxiv_id}.pdf" if arxiv_id else "",
        "source_url": f"https://arxiv.org/e-print/{arxiv_id}" if arxiv_id else "",
        "category": category,
    }


def query_openalex_works(source_id: str, year: int, per_year: int) -> list[dict[str, Any]]:
    params = {
        "filter": f"primary_location.source.id:{source_id},publication_year:{year}",
        "per-page": str(max(per_year * 3, 20)),
        "sort": "cited_by_count:desc",
    }
    url = "https://api.openalex.org/works?" + urllib.parse.urlencode(params)
    data = request_json(url)
    return data.get("results", [])


def normalize_hits(raw_hits: Any) -> list[dict[str, Any]]:
    if not raw_hits:
        return []
    if isinstance(raw_hits, dict):
        return [raw_hits]
    return list(raw_hits)


def dblp_xml_rows(venue: Venue, year: int, toc: str, limit: int) -> list[dict[str, str]]:
    url = f"https://dblp.org/{toc.removesuffix('.bht')}.xml"
    data = request_bytes(url, timeout=60, retries=3, context=DBLP_SSL_CONTEXT)
    root = ET.fromstring(data)
    rows: list[dict[str, str]] = []
    for pub in root.iter():
        if pub.tag not in {"inproceedings", "article"}:
            continue
        title = (pub.findtext("title") or "").rstrip(".").strip()
        if not title:
            continue
        rows.append(
            {
                "领域": venue.area,
                "年份": str(year),
                "会议或期刊名": venue.venue,
                "文章名": title,
                "链接": pub.findtext("ee") or pub.findtext("url") or "",
                "代码仓库": "",
                "数据集或基准链接": "",
                "本地的下载路径": "",
                "文章类别": infer_category(title, ""),
                "备注": "DBLP XML fallback",
            }
        )
        if len(rows) >= limit:
            break
    return rows


def query_dblp_toc(venue: Venue, year: int, limit: int) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    patterns = DBLP_TOC_PATTERNS.get(venue.venue, [])
    for pattern in patterns:
        toc = f"db/{pattern.format(year=year)}.bht"
        try:
            rows = dblp_xml_rows(venue, year, toc, limit)
        except Exception as exc:
            log(f"[warn] DBLP XML fallback failed for {venue.venue} {year} via {toc}: {exc}")
        if rows:
            break

        params = {
            "q": f"toc:{toc}:",
            "format": "json",
            "h": str(limit),
        }
        url = "https://dblp.org/search/publ/api?" + urllib.parse.urlencode(params)
        try:
            data = request_json(url, timeout=25, retries=3, context=DBLP_SSL_CONTEXT)
        except Exception as exc:
            log(f"[warn] DBLP fallback failed for {venue.venue} {year} via {toc}: {exc}")
            continue
        hits = normalize_hits((data.get("result", {}).get("hits", {}) or {}).get("hit"))
        for hit in hits:
            info = hit.get("info", {})
            title = (info.get("title") or "").rstrip(".").strip()
            if not title:
                continue
            rows.append(
                {
                    "领域": venue.area,
                    "年份": str(year),
                    "会议或期刊名": venue.venue,
                    "文章名": title,
                    "链接": info.get("ee") or info.get("url") or "",
                    "代码仓库": "",
                    "数据集或基准链接": "",
                    "本地的下载路径": "",
                    "文章类别": infer_category(title, ""),
                    "备注": "DBLP fallback",
                }
            )
        if rows:
            break
    return rows[:limit]


def make_row(venue: Venue, year: int, work: dict[str, Any], enrich_arxiv: bool) -> dict[str, str]:
    title = (work.get("title") or "").strip()
    abstract = reconstruct_abstract(work)
    link = get_work_link(work)
    note_parts = []

    arxiv = arxiv_search_by_title(title) if enrich_arxiv and title else {}
    if arxiv.get("arxiv_url"):
        link = arxiv["arxiv_url"]
        note_parts.append(f"arXiv:{arxiv['arxiv_id']}")

    if work.get("cited_by_count") is not None:
        note_parts.append(f"OpenAlex cited_by_count={work['cited_by_count']}")

    area = arxiv.get("category") or venue.area
    return {
        "领域": area,
        "年份": str(year),
        "会议或期刊名": venue.venue,
        "文章名": title,
        "链接": link,
        "代码仓库": extract_github_link(abstract),
        "数据集或基准链接": extract_resource_link(abstract),
        "本地的下载路径": "",
        "文章类别": infer_category(title, abstract),
        "备注": "; ".join(note_parts),
    }


def row_key(row: dict[str, str]) -> str:
    raw = f"{row['年份']}|{row['会议或期刊名']}|{row['文章名']}".lower()
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()


def collect(args: argparse.Namespace) -> list[dict[str, str]]:
    venues = read_venues(Path(args.venues))
    years = parse_years(args.years)
    cache = load_source_cache()
    rows: list[dict[str, str]] = []
    seen: set[str] = set()

    for venue in venues:
        source_id = resolve_openalex_source(venue, cache)
        save_source_cache(cache)
        for year in years:
            works: list[dict[str, Any]] = []
            if source_id:
                try:
                    works = query_openalex_works(source_id, year, args.per_year)
                except Exception as exc:
                    log(f"[warn] {venue.venue} {year}: {exc}")
            accepted = 0
            for work in works:
                if not work.get("title"):
                    continue
                row = make_row(venue, year, work, args.enrich_arxiv)
                key = row_key(row)
                if key in seen:
                    continue
                rows.append(row)
                seen.add(key)
                accepted += 1
                if accepted >= args.per_year:
                    break
            if accepted < args.per_year:
                fallback_rows = query_dblp_toc(venue, year, args.per_year - accepted)
                for row in fallback_rows:
                    key = row_key(row)
                    if key in seen:
                        continue
                    rows.append(row)
                    seen.add(key)
                    accepted += 1
                    if accepted >= args.per_year:
                        break
            log(f"[collect] {venue.venue} {year}: {accepted}")
            time.sleep(args.sleep)
    return rows


def parse_years(value: str) -> list[int]:
    if "-" in value:
        start, end = value.split("-", 1)
        return list(range(int(start), int(end) + 1))
    return [int(part.strip()) for part in value.split(",") if part.strip()]


def write_csv(rows: list[dict[str, str]], output: Path) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=COLUMNS)
        writer.writeheader()
        writer.writerows(rows)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--venues", default=str(DEFAULT_VENUES))
    parser.add_argument("--years", default="2020-2026")
    parser.add_argument("--per-year", type=int, default=5)
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT))
    parser.add_argument("--sleep", type=float, default=0.2)
    parser.add_argument(
        "--no-arxiv",
        action="store_false",
        dest="enrich_arxiv",
        help="skip arXiv title lookup",
    )
    parser.set_defaults(enrich_arxiv=True)
    args = parser.parse_args()

    rows = collect(args)
    write_csv(rows, Path(args.output))
    log(f"[done] wrote {len(rows)} rows to {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
