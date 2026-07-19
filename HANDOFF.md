# 交接文档：CS 论文复现评测集数据收集

## 项目目的

本项目用于构建一个“论文复现类评测集”的基础数据池，当前限定计算机科学领域，年份范围为 2020-2026。核心目标是按顶级会议/期刊与年份收集论文元数据，并尽量优先筛选有开源代码、项目页或关键复现资源的论文。

当前主表是 CSV，字段为：

- `领域`
- `年份`
- `会议或期刊名`
- `文章名`
- `链接`
- `代码仓库`
- `数据集或基准链接`
- `本地的下载路径`
- `文章类别`
- `备注`

目前优先级已经调整为：先把“带代码/项目链接的文章”收集多一点；PDF 和仓库下载可以后续再补。

## 当前进展

截至本交接文档编写时：

- 候选论文池：`data/papers_candidates.csv`
  - 共 6079 篇候选论文
  - 覆盖 249 个 `会议或期刊名 × 年份` 单元
  - 52 个单元已经扩展到 95 篇以上候选
- 带代码/项目链接论文表：`data/papers_with_code.csv`
  - 共 215 篇
  - 覆盖 59 个 `会议或期刊名 × 年份` 单元
  - 36 个单元已经达到至少 5 篇带代码/项目链接论文
- 覆盖统计表：`data/code_backed_coverage.csv`
  - 由 `scripts/report_coverage.py` 生成
  - 统计每个单元的带代码论文数、本地 PDF 数、本地 repo 数

注意：`data/code_backed_coverage.csv` 中的“本地PDF数”和“本地仓库数”只是当前工作站本地下载状态；迁移到服务器后，`downloads/` 不会随 Git 上传，需要按表中链接重新下载或 clone。

## 目录与文件说明

### 数据文件

- `data/papers.csv`
  - 初始主表，较早阶段收集的论文元数据。
- `data/papers_candidates.csv`
  - 扩展候选池，主要来自 DBLP/OpenAlex/arXiv 等来源。
  - 后续继续扩展候选时优先改这个表。
- `data/papers_with_code.csv`
  - 当前最重要的表：筛选出带代码仓库、项目页、Hugging Face 资源或其他明确代码/复现链接的论文。
- `data/code_backed_coverage.csv`
  - 覆盖统计输出，可随时重新生成。
- `configs/venues.csv`
  - 会议/期刊配置表，记录 venue 名称、领域和数据源配置。

### 脚本

- `scripts/collect_papers.py`
  - 早期通用采集脚本，包含 CSV 字段定义、标题归一化、基础采集逻辑等。
  - 其他脚本会复用其中的 `COLUMNS` 和 `row_key`。
- `scripts/expand_candidates_dblp.py`
  - 用 DBLP 扩大候选池。
  - 当前已把一部分 AI/ML/CV/NLP/SE 会议扩到接近 100 篇/年。
  - 后半段遇到较多 DBLP SSL 错误，尤其 FSE/ASE/ISSTA/SIGCOMM/NSDI/MobiCom/SIGMOD 等方向，需要在服务器上重新尝试或换源。
- `scripts/build_code_backed_subset.py`
  - 从候选池生成/增量更新 `papers_with_code.csv`。
  - 当前逻辑：
    - 先保留旧表中已有代码链接的行，防止增量运行导致倒退。
    - 使用候选行中已有的 `代码仓库`。
    - 查询 arXiv 标题匹配结果，并从摘要中抽取代码/项目 URL。
    - 查询 Hugging Face Papers API，并从 summary 中抽取代码/项目 URL。
    - 可选使用 GitHub Search API 做保守匹配。
  - 已加入临时文件原子替换，降低 Windows 写 CSV 失败概率。
- `scripts/download_assets.py`
  - 根据表中链接下载 PDF、arXiv source tar，并可选 clone repo。
  - 已支持 arXiv、PMLR、ACL Anthology、OpenReview、CVF openaccess 等 PDF 推断。
  - 已加入浏览器 UA 和 `curl` fallback。
- `scripts/clone_repos.py`
  - 根据 `papers_with_code.csv` clone GitHub/GitLab 仓库到 `downloads/.../repo`。
  - 会跳过普通项目页；GitHub `blob/...` 链接会归一化到仓库根地址。
  - Windows 下少数仓库可能因文件名含 `:` 等非法字符 checkout 失败，服务器 Linux 环境通常更适合。
- `scripts/report_coverage.py`
  - 重新生成 `data/code_backed_coverage.csv`。
- `scripts/backfill_missing.py`
  - 早期补缺辅助脚本，目前不是主流程。

## 推荐服务器续跑命令

如果服务器仍需使用代理：

```powershell
$env:HTTP_PROXY='http://127.0.0.1:7897'
$env:HTTPS_PROXY='http://127.0.0.1:7897'
```

Linux shell 对应：

```bash
export HTTP_PROXY=http://127.0.0.1:7897
export HTTPS_PROXY=http://127.0.0.1:7897
```

继续扩大 DBLP 候选池：

```bash
python scripts/expand_candidates_dblp.py \
  --input data/papers.csv \
  --output data/papers_candidates.csv \
  --years 2020-2026 \
  --per-cell 100 \
  --sleep 0.1
```

优先补带代码论文到每单元 5 篇：

```bash
export GITHUB_TOKEN=<your_github_token>
python scripts/build_code_backed_subset.py \
  --input data/papers_candidates.csv \
  --output data/papers_with_code.csv \
  --per-cell 5 \
  --max-queries 300 \
  --arxiv-sleep 0.05 \
  --hf-sleep 0.05 \
  --sleep 2.2 \
  --min-score 0.55
unset GITHUB_TOKEN
```

只使用 arXiv/Hugging Face Papers/已有链接，不使用 GitHub Search：

```bash
python scripts/build_code_backed_subset.py \
  --input data/papers_candidates.csv \
  --output data/papers_with_code.csv \
  --per-cell 5 \
  --max-queries -1 \
  --arxiv-sleep 0.05 \
  --hf-sleep 0.05
```

重新生成覆盖统计：

```bash
python scripts/report_coverage.py
```

后续需要下载 PDF：

```bash
python scripts/download_assets.py --csv data/papers_with_code.csv --max-items 100 --sleep 0.2
```

后续需要 clone 仓库：

```bash
python scripts/clone_repos.py --csv data/papers_with_code.csv --timeout 120 --max-items 100
```

## 重要注意事项

- 不要提交 GitHub token、代理配置或 `.cache/`。
- `downloads/` 很大，包含 PDF、arXiv source 和 cloned repos，已在 `.gitignore` 中，不应上传 GitHub。
- `.cache/` 包含 GitHub/arXiv/HF 查询缓存，也已忽略；迁移服务器后可重新生成。
- 当前 GitHub Search 的保守匹配过滤了 `awesome`、`survey`、`papers`、`tutorial` 等泛化仓库，但仍需要人工抽查一部分结果。
- 有些 `代码仓库` 实际是项目页、Hugging Face 页面、Colab、论文主页等，并不一定能直接 `git clone`。这类仍可作为复现资源链接保留。
- DBLP 在当前代理节点下前半段效果很好，后半段出现 `SSL: DECRYPTION_FAILED_OR_BAD_RECORD_MAC`。服务器上建议换网络环境或分 venue 重试。
- 2026 年很多会议 DBLP/官网记录尚不完整，缺口不一定是脚本问题。
- GitHub Search API 认证后也有搜索限额，建议 `--sleep 2.2` 或更高。

## 当前优先缺口

下一步建议先补这些方向的“带代码论文数”：

- ACL/EMNLP 早期年份：可考虑 ACL Anthology + GitHub Search。
- 软件工程：ICSE 已开始补，ASE/FSE/ISSTA 需要更多候选或 artifact/source mining。
- 系统/网络/安全/数据库：EuroSys/ASPLOS/NSDI/SIGCOMM/CCS/ICDE/SIGMOD/VLDB 等目前候选池或代码链接命中不足，建议先修 DBLP 扩展，再跑 GitHub Search。
- IJCAI/NeurIPS：候选池已扩得较大，但显式摘要链接命中较少，需要 GitHub Search 或 OpenReview/Papers 页面增强。

## Git 与大文件情况

- 远程仓库：`origin git@github.com:ignorancex/cspaper-dataset.git`
- 当前被 Git 跟踪的最大文件约 1 MB，是 `data/papers_candidates.csv`。
- 超过 100 MB 的文件存在于 `downloads/` 下，但该目录已忽略，不会被正常 `git add` 上传。
- push 前建议检查：

```bash
git status --short
git ls-files | xargs -I{} du -h "{}" | sort -hr | head
```

Windows PowerShell 可用：

```powershell
git ls-files | ForEach-Object {
  if (Test-Path -LiteralPath $_) {
    [PSCustomObject]@{ Size=(Get-Item -LiteralPath $_).Length; Path=$_ }
  }
} | Sort-Object Size -Descending | Select-Object -First 20
```
