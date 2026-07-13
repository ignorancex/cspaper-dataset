# CS Paper Reproduction Dataset

This workspace collects metadata and selected local assets for a computer science paper reproduction benchmark.

## Files

- `configs/venues.csv`: curated CS conference and journal list for the first collection pass.
- `scripts/collect_papers.py`: collects venue/year paper metadata from OpenAlex and optionally enriches arXiv links.
- `scripts/download_assets.py`: downloads PDFs, arXiv LaTeX sources when available, and optionally clones GitHub repositories already listed in the CSV.
- `data/papers.csv`: generated metadata table.
- `downloads/`: local PDFs, sources, and repositories. This folder is intentionally ignored by Git.

## CSV Columns

The generated CSV uses the requested Chinese columns:

`领域, 年份, 会议或期刊名, 文章名, 链接, 代码仓库, 数据集或基准链接, 本地的下载路径, 文章类别, 备注`

## Typical Commands

Collect five papers per configured venue per year:

```powershell
python scripts/collect_papers.py --years 2020-2026 --per-year 5 --output data/papers.csv
```

Download a small review subset:

```powershell
python scripts/download_assets.py --csv data/papers.csv --max-items 30
```

If a row has a GitHub URL in `代码仓库`, clone it too:

```powershell
python scripts/download_assets.py --csv data/papers.csv --max-items 30 --clone-repos
```

## Notes

- OpenAlex is used for broad venue/year metadata.
- arXiv is used as a best-effort enrichment source for PDF and LaTeX source downloads.
- External datasets and benchmarks are recorded as links only for now; the downloader does not fetch them.
- Code repository discovery is intentionally conservative. The downloader clones only URLs already present in the CSV.

