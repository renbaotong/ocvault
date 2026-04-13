# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Repository Overview

这是一个固定收益投行业务的公司债募集说明书结构化知识库，使用 Obsidian 进行知识管理。系统通过 Python 脚本从 PDF 募集说明书中提取结构化数据，生成 Markdown 格式的笔记文件。

## Architecture

### Directory Structure

```
ocvault/
├── raw/                    # 原始 PDF 募集说明书
├── knowledge/              # Obsidian 知识库（按募集说明书章节组织）
│   ├── 00-Meta/           # 索引文件（发行人索引、债券索引）
│   ├── 01-发行条款/       # 第二节：债券发行条款
│   ├── 02-募集资金运用/   # 第三节：资金用途
│   ├── 03-发行人基本情况/ # 第四节：发行人概况
│   ├── 04-主营业务分析/   # 主营业务（新增）
│   ├── 05-资产状况/       # 第五节：财务分析 + camelot提取的表格数据
│   ├── 06-区域分析/       # 地方财政、区域经济（Tushare宏观数据）
│   └── 07-模板参考/       # Obsidian 笔记模板
└── scripts/               # Python 处理脚本
```

**命名约定**: 知识库中的文件按 `{发行人全称}-{内容类型}.md` 命名，如 `樟树市创业投资发展有限公司-发行条款.md`。

### Core Components

1. **PDF Extractor (`scripts/extract_prospectus.py`)**
   - 使用 PyMuPDF (fitz) 提取文本
   - `ProspectusExtractor` 类按章节提取信息
   - 生成 01-04 目录下的结构化笔记

2. **Table Extractor (`scripts/extract_tables_camelot.py`)**
   - 使用 camelot-py 提取 PDF 中的表格
   - 识别财务数据表（基于关键词：资产、负债、利润等）
   - 识别募集资金用途表（基于关键词：募集资金、投向、项目总投资等）
   - 输出追加到 `05-资产状况/{发行人}-财务分析.md`

3. **Tushare Sync (`scripts/tushare_data_sync.py`)**
   - 需要 `TUSHARE_TOKEN` 环境变量
   - 同步宏观经济数据（CPI、PPI、PMI、GDP、M2等）
   - 同步债券市场数据（Shibor、LPR、国债收益率等）
   - 输出到 `06-区域分析/`

4. **Data Model**
   - 每个发行人在各目录下有独立 Markdown 文件
   - Frontmatter 包含 `type` 和 `tags` 用于 Obsidian Dataview 查询
   - 标签体系：`#债券类型`（公司债/乡村振兴债/革命老区债）、`#增信方式`、`#行政层级`

## Multi-Agent Knowledge Base Creation

When processing new prospectuses, use Claude Code's Agent tool to coordinate a three-agent workflow for high-quality knowledge extraction:

### Agent Roles

```python
# Workflow: Extract → Critique → Synthesize

# 1. Extract Agent
Agent({
    "description": "Extract bond prospectus content",
    "prompt": """Extract the following from the prospectus PDF:
    - 发行条款: 注册规模、本期发行规模、债券期限、票面利率、增信措施、主体评级
    - 募集资金运用: 资金用途、偿债计划、项目建设明细
    - 发行人基本情况: 注册资本、法定代表人、股权结构、主营业务
    - 财务状况: 资产总计、负债总计、营业收入、净利润、资产负债率
    
    Output structured data in the format specified in CLAUDE.md.
    Be precise with numbers and cite page numbers for verification."""
})

# 2. Critic Agent  
Agent({
    "description": "Critique extraction quality",
    "prompt": """Review the extracted content for:
    - Logical consistency (e.g., 本期发行规模 ≤ 注册规模)
    - Data completeness (are all required fields present?)
    - Numerical accuracy (check units: 万元 vs 亿元)
    - Cross-section consistency (e.g., 发行人名称一致 across sections)
    
    Flag any issues with severity (ERROR/WARNING/INFO) and suggest corrections.
    If no issues found, explicitly state "APPROVED"."""
})

# 3. Synthesize Agent
Agent({
    "description": "Coordinate and finalize output",
    "prompt": """Given the extraction results and critique feedback:
    - Resolve conflicts between extract and critique (max 2 iterations)
    - Produce final structured output for knowledge base
    - Ensure all numerical data has proper units
    - Format as valid Markdown with correct Obsidian frontmatter
    
    If critique found ERRORs: fix them and output corrected version
    If critique found WARNINGs: note them in comments but proceed
    If critique APPROVED: output the final version directly
    
    Prevent infinite loops by limiting to 1 critique cycle."""
})
```

### Execution Flow

1. **Initial Extraction**: Extract Agent processes PDF and produces structured data
2. **Quality Review**: Critic Agent evaluates extraction for accuracy and consistency
3. **Resolution**: 
   - If approved → Synthesize Agent formats final output
   - If issues found → Extract Agent revises (one iteration max) → Synthesize Agent finalizes

### Conflict Resolution Rules

- **Numerical conflicts**: Prefer data from official tables over narrative text
- **Missing data**: Mark as "未披露" rather than leaving blank
- **Unit confusion**: Convert all to consistent units (亿元 for amounts, % for ratios)
- **Logical errors**: Reject impossible values (e.g., negative asset totals) and flag for manual review

### When to Use Multi-Agent vs Script Processing

| Scenario | Approach |
|----------|----------|
| Standard format PDFs with clear tables | Use `scripts/extract_prospectus.py` (faster) |
| Complex/unusual format, multiple revisions needed | Use Multi-Agent workflow (higher quality) |
| First-time processing new issuer type | Use Multi-Agent to establish extraction pattern |
| Bulk processing (>10 similar PDFs) | Use scripts with manual spot-checking |

## Common Commands

### 处理新募集说明书

```bash
# 1. 将 PDF 放入 raw/ 目录
cp new_prospectus.pdf raw/

# 2. 运行主提取脚本（生成 01-04 目录笔记）
python3 scripts/extract_prospectus.py

# 3. 提取表格数据（追加到 05-资产状况/）
python3 scripts/extract_tables_camelot.py

# 4. 在 Obsidian 中打开知识库复查
open -a Obsidian knowledge/
```

### 同步外部数据

```bash
# 设置 Tushare Token（如未设置）
export TUSHARE_TOKEN=your_token

# 同步宏观经济和债券数据
python3 scripts/tushare_data_sync.py
```

### 批量处理

```bash
# 处理 raw/ 目录下所有 PDF
python3 scripts/extract_prospectus.py

# 查看生成的笔记数量
find knowledge -name "*.md" | wc -l

# 查看特定发行人文件
ls knowledge/*/樟树市创业投资发展有限公司*.md
```

## Key File Patterns

### 生成的笔记类型

- `01-发行条款/{发行人}-发行条款.md` - 债券基本信息、发行规模、期限、增信措施
- `02-募集资金运用/{发行人}-募集资金运用.md` - 资金用途、偿债计划、项目建设
- `03-发行人基本情况/{发行人}-概况.md` - 发行人概况、股权结构、历史沿革
- `04-主营业务分析/{发行人}-主营业务.md` - 主营业务收入、毛利率分析
- `05-资产状况/{发行人}-财务分析.md` - 财务数据、偿债指标、原始表格

### 模板文件

- `knowledge/07-模板参考/债券发行条款模板.md` - 发行条款笔记模板
- `knowledge/07-模板参考/宏观经济数据模板.md` - 宏观经济数据模板

## Environment Setup

### Required Python Packages

```bash
pip install PyMuPDF camelot-py pandas tushare
```

### Obsidian 插件配置

推荐安装以下插件（配置已保存在 `.obsidian/`）：
- **Dataview** - 结构化数据查询和表格生成
- **Templater** - 笔记模板自动化

### Environment Variables

```bash
# Tushare API Token（必需用于宏观数据同步）
export TUSHARE_TOKEN=your_token
```

## Data Extraction Logic

### 章节识别

`extract_prospectus.py` 通过查找 "第{X}节" 字样识别章节边界：
- 第二节 → 01-发行条款
- 第三节 → 02-募集资金运用
- 第四节 → 03-发行人基本情况
- 第五节 → 05-资产状况（财务分析部分）

### 表格识别

`extract_tables_camelot.py` 使用两种模式：
1. **lattice** - 适合有明确边框的表格（默认）
2. **stream** - 适合无框线表格（回退模式）

表格分类基于关键词匹配（至少3个关键词匹配）：
- 财务数据表：资产、负债、利润、现金流量等
- 募集资金用途表：募集资金、投向、项目总投资等

## Important Notes

1. **PDF 格式要求**: 必须是文本可选格式（非扫描图片），否则提取会失败
2. **数据校验**: 提取的财务数字需要人工校验，特别是小数点和单位
3. **增量更新**: 新 PDF 放入 raw/ 后重新运行脚本即可，已有文件会被覆盖
4. **Git 管理**: 知识库文件已纳入 git 管理，定期 commit 备份
5. **目录顺序**: 05-资产状况现在包含合并后的内容（原05+08），每个发行人只有一个文件

## Troubleshooting

### 表格提取失败
- 检查 camelot-py 安装：`python3 -c "import camelot; print(camelot.__version__)"`
- 尝试安装 ghostscript（表格提取依赖）：`brew install ghostscript`

### Tushare 同步失败
- 检查 Token 是否设置：`echo $TUSHARE_TOKEN`
- 检查积分是否足够（部分接口需要 >5000 积分）
- 查看 `docs/external_data.md` 获取接口可用性列表

### Obsidian 无法识别 Dataview 查询
- 确认 Dataview 插件已启用
- 检查笔记 frontmatter 格式是否正确（YAML格式）
