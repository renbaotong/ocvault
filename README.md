# 公司债募集说明书知识库

固定收益投行业务的公司债募集说明书结构化知识库，使用 Obsidian 进行管理。

## 项目现状

- **已处理发行人**: 6 家
- **知识库文件**: 20 个 Markdown 笔记（01-03 目录）
- **债券类型**: 公司债、乡村振兴债、革命老区债

## 目录结构

```
ocvault/
├── raw/                    # 原始 PDF 文件（6 份募集说明书）
├── knowledge/              # 知识库文件
│   ├── 00-Meta/           # 索引（发行人索引、债券索引）
│   ├── 01-发行条款/       # 债券发行条款
│   ├── 02-募集资金运用/   # 资金用途
│   ├── 03-发行人基本情况/ # 发行人概况
│   └── 05-资产状况/       # 财务分析（由 extract_tables_camelot.py 生成）
└── scripts/               # Python 处理脚本（3 个）
```

## 使用说明

### 处理新募集说明书

```bash
# 1. 将 PDF 放入 raw/ 目录
cp new_prospectus.pdf raw/

# 2. 提取文本生成笔记 (01-03 目录)
python3 scripts/extract_prospectus.py

# 3. 提取表格数据 (05-资产状况)
python3 scripts/extract_tables_camelot.py
```

### 同步外部数据

```bash
export TUSHARE_TOKEN=your_token
python3 scripts/tushare_data_sync.py
```

## 核心脚本

| 脚本 | 功能 |
|------|------|
| `extract_prospectus.py` | 从 PDF 提取文本，生成 01-03 目录笔记 |
| `extract_tables_camelot.py` | 提取 PDF 表格，生成 05-资产状况 |
| `tushare_data_sync.py` | 同步宏观经济和债券市场数据 |

## 环境配置

### Python 依赖

```bash
pip install PyMuPDF camelot-py pandas tushare
```

### Obsidian 插件

- **Dataview** - 结构化数据查询（索引页面使用）
- **Templater** - 笔记模板

## 标签体系

- `#债券类型`: `#公司债` `#乡村振兴债` `#革命老区债`
- `#增信方式`: `#保证担保` `#抵押担保` `#质押担保` `#信用`
- `#行政层级`: `#省级` `#地市级` `#区县级`

## 注意事项

1. **PDF 格式**: 必须是文本可选格式（非扫描图片）
2. **数据校验**: 提取的财务数字需人工校验
