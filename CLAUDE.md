# CLAUDE.md

## 项目概述

公司债募集说明书结构化知识库，用于固定收益投行业务。使用 Obsidian 管理，通过 Python 脚本从 PDF 提取结构化数据。

## 目录结构

```
ocvault/
├── raw/                    # 原始 PDF（6 份募集说明书）
├── knowledge/              # Obsidian 知识库
│   ├── 00-Meta/           # 索引（发行人索引、债券索引）
│   ├── 01-发行条款/       # 债券发行条款
│   ├── 02-募集资金运用/   # 资金用途
│   ├── 03-发行人基本情况/ # 发行人概况
│   ├── 04-主营业务分析/   # 主营业务（6 个发行人模板）
│   └── 05-资产状况/       # 财务分析
└── scripts/               # Python 脚本（3 个）
```

**命名约定**: `{发行人全称}-{内容类型}.md`

## 核心脚本

| 脚本 | 功能 |
|------|------|
| `extract_prospectus.py` | 提取 PDF 文本，生成 01-03 目录笔记 |
| `extract_tables_camelot.py` | 提取 PDF 表格，生成 05-资产状况 |
| `tushare_data_sync.py` | 同步 Tushare 宏观/债券数据 |

## 使用方法

```bash
# 处理新募集说明书
cp new_prospectus.pdf raw/
python3 scripts/extract_prospectus.py
python3 scripts/extract_tables_camelot.py

# 同步外部数据
export TUSHARE_TOKEN=your_token
python3 scripts/tushare_data_sync.py
```

## 环境配置

```bash
# Python 依赖
pip install PyMuPDF camelot-py pandas tushare

# Obsidian 插件：Dataview, Templater
# 环境变量
export TUSHARE_TOKEN=your_token
```

## 笔记类型

| 目录 | 文件 | 内容 |
|------|------|------|
| 01-发行条款 | `{发行人}-发行条款.md` | 规模、期限、利率、增信、评级 |
| 02-募集资金运用 | `{发行人}-募集资金运用.md` | 资金用途、偿债计划 |
| 03-发行人基本情况 | `{发行人}-概况.md` | 注册资本、法人、股权 |
| 04-主营业务分析 | `{发行人}-主营业务.md` | 业务板块、收入构成、毛利率（模板） |
| 05-资产状况 | `{发行人}-财务分析.md` | 财务数据、偿债指标、原始表格 |

## 注意事项

1. PDF 必须是文本可选格式（非扫描图片）
2. 财务数字需人工校验
3. 增量更新：新 PDF 放入 raw/ 后重新运行脚本

## Troubleshooting

```bash
# 表格提取失败 - 检查 camelot
python3 -c "import camelot; print(camelot.__version__)"
brew install ghostscript

# Tushare 失败 - 检查 Token 和积分
echo $TUSHARE_TOKEN
```
