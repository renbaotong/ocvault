# 公司债募集说明书知识库

固定收益投行业务的公司债募集说明书结构化知识库，使用 Obsidian 进行管理。

## 项目现状

- **已处理发行人**: 26 家
- **知识库文件**: 147 个 Markdown 笔记
- **债券类型**: 公司债、乡村振兴债、革命老区债、低碳转型债、科技创新债、可续期债、绿色债

## 目录结构

```
ocvault/
├── raw/                    # 原始 PDF/DOCX 文件（本地保留，不提交 Git）
├── knowledge/              # 知识库文件
│   ├── 00-Meta/           # 索引（发行人索引、债券索引）
│   ├── 01-发行条款/       # 债券发行条款
│   ├── 02-募集资金运用/   # 资金用途
│   ├── 03-发行人基本情况/ # 发行人概况
│   ├── 04-主营业务分析/   # 主营业务
│   └── 05-资产结构分析/   # 资产结构（流动资产/非流动资产/资产总计）
└── scripts/               # Python 脚本
    ├── extractors/        # 共享提取器包
    └── run_all.py         # 批量运行入口
```

## 使用说明

### 处理新募集说明书

```bash
# 1. 将 PDF/DOCX 放入 raw/ 目录（DOCX 需先转 PDF）
#    Word COM 转换（Windows）:
#    python -c "import win32com.client; w=win32com.client.Dispatch('Word.Application'); w.Visible=False; d=w.Documents.Open('raw/xxx.docx'); d.SaveAs('raw/xxx.pdf', FileFormat=17); d.Close(); w.Quit()"

# 2. 批量运行所有提取脚本（01-05 目录 + 索引）
python scripts/run_all.py

# 3. 或单独运行某个脚本
python scripts/extract_bond_terms.py        # 01-发行条款
python scripts/extract_fund_usage.py        # 02-募集资金运用
python scripts/extract_issuer_profile.py    # 03-发行人基本情况
python scripts/extract_business_analysis.py # 04-主营业务分析
python scripts/extract_financial_analysis.py # 05-资产结构分析
python scripts/generate_meta_index.py       # 更新索引
```

### 核心脚本

| 脚本 | 输出目录 | 功能 |
|------|----------|------|
| `extract_bond_terms.py` | 01-发行条款 | 注册规模、发行规模、期限、利率、增信、评级 |
| `extract_fund_usage.py` | 02-募集资金运用 | 募集资金总额、用途明细（偿债/补流/项目投资） |
| `extract_issuer_profile.py` | 03-发行人基本情况 | 注册名称、资本、实缴资本、设立日期、经营范围、股权结构 |
| `extract_business_analysis.py` | 04-主营业务分析 | 营业收入、营业成本、毛利率分板块表格 |
| `extract_financial_analysis.py` | 05-资产结构分析 | 资产构成（流动资产/非流动资产/资产总计） |
| `generate_meta_index.py` | 00-Meta/ | 生成发行人索引和债券索引笔记 |
| `run_all.py` | — | 批量运行以上脚本 + 生成索引 |

## 环境配置

### Python 依赖

```bash
pip install PyMuPDF pdfplumber
```

### Obsidian 插件

- **Dataview** - 结构化数据查询（索引页面使用）
- **Templater** - 笔记模板

## 标签体系

- `#债券类型`: `#公司债` `#乡村振兴债` `#革命老区债` `#低碳转型债` `#科技创新债` `#绿色债`
- `#增信方式`: `#保证担保` `#抵押担保` `#质押担保` `#信用`

## 注意事项

1. **PDF 格式**: 必须是文本可选格式（非扫描图片），DOCX 需先转换为 PDF
2. **数据校验**: 提取的财务数字需人工校验
3. **增量更新**: 新 PDF 放入 raw/ 后重新运行 `run_all.py`
4. **禁止使用** `extract_prospectus.py`（已废弃，改用模块化脚本）
5. **raw/ 目录**: 已在 `.gitignore` 中，不提交到远程仓库
