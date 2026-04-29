# CLAUDE.md

## 项目概述

公司债募集说明书结构化知识库，用于固定收益投行业务。使用 Obsidian 管理，通过 Python 脚本从 PDF 提取结构化数据。

## 目录结构

```
ocvault/
├── raw/                    # 原始 PDF
├── knowledge/              # Obsidian 知识库
│   ├── 00-Meta/           # 索引（发行人索引、债券索引）
│   ├── 01-发行条款/       # 债券发行条款
│   ├── 02-募集资金运用/   # 资金用途
│   ├── 03-发行人基本情况/ # 发行人概况
│   ├── 04-主营业务分析/   # 主营业务分析
│   └── 05-资产结构分析/   # 资产结构分析
└── scripts/               # Python 脚本
    ├── extractors/        # 共享提取器包
    │   ├── __init__.py    # 导出常量、基类、工具函数
    │   ├── base.py        # BaseExtractor 基类
    │   ├── config.py      # 正则模式配置
    │   ├── utils.py       # 工具函数
    │   └── equity_paddle_ocr.py  # 股权架构图 OCR
    └── run_all.py         # 批量运行入口
```

**命名约定**: `{发行人全称}-{内容类型}.md`

## 核心脚本

| 脚本 | 输出目录 | 功能 |
|------|----------|------|
| `extract_bond_terms.py` | 01-发行条款 | 注册规模、发行规模、期限、利率、增信、评级 |
| `extract_fund_usage.py` | 02-募集资金运用 | 募集资金总额、用途明细（偿债/补流/项目投资） |
| `extract_issuer_profile.py` | 03-发行人基本情况 | 注册名称、资本、实缴资本、设立日期、经营范围、股权结构 |
| `extract_business_analysis.py` | 04-主营业务分析 | 营业收入、营业成本、毛利率分板块表格 |
| `extract_financial_analysis.py` | 05-资产结构分析 | 资产构成（流动资产/非流动资产/资产总计） |
| `run_all.py` | — | 批量运行以上 5 个脚本 + 生成索引 |
| `generate_meta_index.py` | 00-Meta/ | 生成发行人索引和债券索引笔记 |

## 使用方法

```bash
# 处理新募集说明书
cp new_prospectus.pdf raw/

# 方式一：批量运行所有提取脚本
python scripts/run_all.py

# 方式二：单独运行某个脚本
python scripts/extract_bond_terms.py
python scripts/extract_fund_usage.py
python scripts/extract_issuer_profile.py
python scripts/extract_business_analysis.py
python scripts/extract_financial_analysis.py
```

## 环境配置

```bash
# Python 依赖
pip install PyMuPDF pdfplumber

# 可选：股权架构图 OCR（需要 PaddleOCR）
pip install paddlepaddle paddleocr

# Obsidian 插件：Dataview, Templater
```

## 笔记类型

| 目录 | 文件 | 内容 |
|------|------|------|
| 01-发行条款 | `{发行人}-发行条款.md` | 规模、期限、利率、增信、评级 |
| 02-募集资金运用 | `{发行人}-募集资金运用.md` | 资金用途、偿债计划、使用明细 |
| 03-发行人基本情况 | `{发行人}-概况.md` | 注册资本、法人、股权架构 |
| 04-主营业务分析 | `{发行人}-主营业务.md` | 营业收入、成本、毛利率分板块表 |
| 05-资产结构分析 | `{发行人}- 资产结构分析.md` | 流动资产/非流动资产/资产总计 |

## 注意事项

1. PDF 必须是文本可选格式（非扫描图片）
2. 财务数字需人工校验
3. 增量更新：新 PDF 放入 raw/ 后重新运行 `run_all.py`
4. **禁止使用** `extract_prospectus.py`（已废弃，改用模块化脚本）
