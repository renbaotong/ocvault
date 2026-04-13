#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
使用 camelot-py 提取 PDF 中的表格数据
专门用于提取财务数据表、募集资金用途表等结构化数据
"""

import camelot
import os
import re
import pandas as pd
from pathlib import Path
from typing import List, Dict, Optional
import json


class CamelotTableExtractor:
    """基于 camelot-py 的表格提取器"""

    def __init__(self, pdf_path: str):
        self.pdf_path = pdf_path
        self.pdf_name = os.path.basename(pdf_path)
        self.issuer_name = self._parse_issuer_name()

    def _parse_issuer_name(self) -> str:
        """从文件名提取发行人名称"""
        name = self.pdf_name.replace(".pdf", "")
        match = re.match(r'(.*?)(20\d{2}年)', name)
        if match:
            return match.group(1).strip()
        return name

    def extract_all_tables(self, pages: str = 'all') -> List[camelot.core.Table]:
        """
        提取 PDF 中的所有表格

        Args:
            pages: 页码范围，如 '1-10' 或 'all'

        Returns:
            表格列表
        """
        try:
            tables = camelot.read_pdf(
                self.pdf_path,
                pages=pages,
                flavor='lattice',  # 使用 lattice 模式，适合有明确边框的表格
                line_scale=40,
                shift_text=['l', 't']
            )
            print(f"  找到 {len(tables)} 个表格 (lattice 模式)")

            # 如果没有找到表格，尝试 stream 模式
            if len(tables) == 0:
                tables = camelot.read_pdf(
                    self.pdf_path,
                    pages=pages,
                    flavor='stream'  # 适合没有明确边框的表格
                )
                print(f"  找到 {len(tables)} 个表格 (stream 模式)")

            return tables
        except Exception as e:
            print(f"  提取表格时出错: {e}")
            return []

    def extract_financial_tables(self) -> List[Dict]:
        """
        提取财务报表相关表格
        通常在第五节"财务状况"
        """
        # 先提取所有表格
        tables = self.extract_all_tables('all')

        financial_tables = []
        for i, table in enumerate(tables):
            df = table.df

            # 检查是否是财务数据表（通过表头关键词）
            is_financial = self._is_financial_table(df)

            if is_financial:
                financial_tables.append({
                    'page': table.page,
                    'data': df,
                    'accuracy': table.accuracy,
                    'whitespace': table.whitespace
                })

        return financial_tables

    def _is_financial_table(self, df: pd.DataFrame) -> bool:
        """判断表格是否为财务数据表"""
        if df.empty:
            return False

        # 转换为字符串检查关键词
        text = ' '.join(df.astype(str).values.flatten())

        financial_keywords = [
            '资产', '负债', '资产负债', '利润', '现金流量',
            '营业收入', '净利润', '总资产', '净资产',
            '流动资产', '非流动资产', '流动负债', '非流动负债',
            '货币资金', '应收账款', '存货', '固定资产',
            '短期借款', '长期借款', '应付债券'
        ]

        keyword_count = sum(1 for kw in financial_keywords if kw in text)
        return keyword_count >= 3  # 至少匹配3个关键词

    def extract_fund_usage_tables(self) -> List[Dict]:
        """
        提取募集资金用途表
        通常在第三节"募集资金运用"
        """
        tables = self.extract_all_tables('all')

        fund_tables = []
        for i, table in enumerate(tables):
            df = table.df

            is_fund = self._is_fund_usage_table(df)

            if is_fund:
                fund_tables.append({
                    'page': table.page,
                    'data': df,
                    'accuracy': table.accuracy
                })

        return fund_tables

    def _is_fund_usage_table(self, df: pd.DataFrame) -> bool:
        """判断表格是否为募集资金用途表"""
        if df.empty:
            return False

        text = ' '.join(df.astype(str).values.flatten())

        fund_keywords = [
            '募集资金', '用途', '投向', '项目名称',
            '投资额', '拟使用', '募集资金', '建设期',
            '项目', '总投资', '资本金'
        ]

        keyword_count = sum(1 for kw in fund_keywords if kw in text)
        return keyword_count >= 3

    def table_to_markdown(self, table_data: pd.DataFrame) -> str:
        """将表格转换为 Markdown 格式"""
        if table_data.empty:
            return ""

        # 清理数据
        df = table_data.copy()
        df = df.replace(r'^\s*$', '', regex=True)  # 空单元格
        df = df.fillna('')

        # 生成 Markdown
        lines = []

        # 表头
        headers = df.iloc[0].tolist() if len(df) > 0 else []
        header_line = '| ' + ' | '.join(str(h).strip() for h in headers) + ' |'
        lines.append(header_line)

        # 分隔符
        separator = '|' + '|'.join(['---'] * len(headers)) + '|'
        lines.append(separator)

        # 数据行
        for _, row in df.iloc[1:].iterrows():
            row_line = '| ' + ' | '.join(str(cell).strip() for cell in row) + ' |'
            lines.append(row_line)

        return '\n'.join(lines)

    def extract_key_metrics(self) -> Dict:
        """从表格中提取关键财务指标"""
        tables = self.extract_financial_tables()

        metrics = {
            'total_assets': '',
            'total_liabilities': '',
            'net_assets': '',
            'revenue': '',
            'net_profit': '',
            'current_ratio': '',
            'quick_ratio': '',
            'debt_ratio': ''
        }

        for table in tables:
            df = table['data']
            text = df.astype(str).to_string()

            # 查找总资产
            if not metrics['total_assets']:
                match = re.search(r'总资产.*?([\d,]+\.?\d*)', text)
                if match:
                    metrics['total_assets'] = match.group(1)

            # 查找总负债
            if not metrics['total_liabilities']:
                match = re.search(r'总负债.*?([\d,]+\.?\d*)', text)
                if match:
                    metrics['total_liabilities'] = match.group(1)

            # 查找营业收入
            if not metrics['revenue']:
                match = re.search(r'营业收入.*?([\d,]+\.?\d*)', text)
                if match:
                    metrics['revenue'] = match.group(1)

            # 查找净利润
            if not metrics['net_profit']:
                match = re.search(r'净利润.*?([\d,]+\.?\d*)', text)
                if match:
                    metrics['net_profit'] = match.group(1)

        return metrics


def process_pdf_with_camelot(pdf_path: str, knowledge_base_dir: str = "knowledge") -> Dict:
    """
    使用 camelot 处理单个 PDF，提取表格数据

    Args:
        pdf_path: PDF 文件路径
        knowledge_base_dir: 知识库根目录

    Returns:
        提取结果摘要
    """
    print(f"\n{'='*60}")
    print(f"处理: {os.path.basename(pdf_path)}")
    print(f"{'='*60}")

    extractor = CamelotTableExtractor(pdf_path)
    issuer_name = extractor.issuer_name

    result = {
        'issuer': issuer_name,
        'financial_tables': [],
        'fund_usage_tables': [],
        'key_metrics': {}
    }

    # 提取财务表格
    print("\n1. 提取财务数据表...")
    financial_tables = extractor.extract_financial_tables()
    print(f"   找到 {len(financial_tables)} 个财务相关表格")

    # 提取募集资金用途表
    print("\n2. 提取募集资金用途表...")
    fund_tables = extractor.extract_fund_usage_tables()
    print(f"   找到 {len(fund_tables)} 个募集资金用途相关表格")

    # 提取关键指标
    print("\n3. 提取关键财务指标...")
    key_metrics = extractor.extract_key_metrics()
    print(f"   总资产: {key_metrics.get('total_assets', 'N/A')}")
    print(f"   营业收入: {key_metrics.get('revenue', 'N/A')}")

    result['financial_tables'] = financial_tables
    result['fund_usage_tables'] = fund_tables
    result['key_metrics'] = key_metrics

    # 生成 Obsidian 笔记片段
    print("\n4. 生成 Obsidian 表格数据...")
    generate_obsidian_table_notes(extractor, issuer_name, knowledge_base_dir)

    return result


def generate_obsidian_table_notes(extractor: CamelotTableExtractor, issuer_name: str, knowledge_base_dir: str):
    """生成 Obsidian 表格数据笔记 - 追加到现有财务分析文件"""

    # 财务状况目录
    tables_dir = Path(knowledge_base_dir) / "05-资产状况"
    tables_dir.mkdir(parents=True, exist_ok=True)

    safe_name = re.sub(r'[\\/*?:"<>|]', "", issuer_name)
    analysis_file = tables_dir / f"{safe_name}-财务分析.md"

    # 读取现有文件内容（如果存在）
    existing_content = ""
    if analysis_file.exists():
        with open(analysis_file, 'r', encoding='utf-8') as f:
            existing_content = f.read()

    # 财务表格
    financial_tables = extractor.extract_financial_tables()
    if financial_tables:
        financial_md = f"""
## 原始财务数据表

以下表格通过 camelot-py 从募集说明书第五节提取。

"""
        for i, table in enumerate(financial_tables):
            financial_md += f"\n### 财务表 {i+1} (第 {table['page']} 页)\n\n"
            financial_md += extractor.table_to_markdown(table['data'])
            financial_md += "\n\n"

        # 追加到现有文件或创建新文件
        if analysis_file.exists():
            with open(analysis_file, 'a', encoding='utf-8') as f:
                f.write(financial_md)
            print(f"   追加到: {analysis_file}")
        else:
            # 创建新文件（带 frontmatter）
            full_content = f"""---
created: {pd.Timestamp.now().strftime('%Y-%m-%d')}
type: financial_analysis
tags: [财务/分析]
---

# {issuer_name} - 财务分析

## 主要财务数据

| 项目 | 2024 年 | 2023 年 | 2022 年 |
|------|---------|---------|---------|
| 资产总计 | | | |
| 负债总计 | | | |
| 所有者权益 | | | |
| 营业收入 | | | |
| 净利润 | | | |
| 经营活动现金流净额 | | | |

## 偿债能力指标

| 指标 | 2024 年 | 2023 年 | 2022 年 |
|------|---------|---------|---------|
| 资产负债率 | | | |
| 流动比率 | | | |
| 速动比率 | | | |
| EBITDA 利息保障倍数 | | | |

## 资产结构分析

### 经营性资产

| 项目 | 金额 | 占比 | 说明 |
|------|------|------|------|
| | | | |

### 非经营性资产

| 项目 | 金额 | 占比 | 说明 |
|------|------|------|------|
| | | | |

### 政府性资产识别

| 资产类型 | 金额 | 收益特征 | 交易对手 |
|---------|------|---------|---------|
| | | □无收益 □低收益 | □政府 □政府部门 □其他 |

---
**来源**: {extractor.pdf_name}
**提取日期**: {pd.Timestamp.now().strftime('%Y-%m-%d')}
{financial_md}"""
            with open(analysis_file, 'w', encoding='utf-8') as f:
                f.write(full_content)
            print(f"   创建: {analysis_file}")

    # 募集资金用途表
    fund_tables = extractor.extract_fund_usage_tables()
    if fund_tables:
        fund_md = f"""
## 募集资金用途表

以下表格通过 camelot-py 从募集说明书第三节提取。

"""
        for i, table in enumerate(fund_tables):
            fund_md += f"\n### 用途表 {i+1} (第 {table['page']} 页)\n\n"
            fund_md += extractor.table_to_markdown(table['data'])
            fund_md += "\n\n"

        # 追加到现有文件
        if analysis_file.exists():
            with open(analysis_file, 'a', encoding='utf-8') as f:
                f.write(fund_md)
            print(f"   追加到: {analysis_file}")
        else:
            # 创建新文件（带 frontmatter）
            full_content = f"""---
created: {pd.Timestamp.now().strftime('%Y-%m-%d')}
type: financial_analysis
tags: [财务/分析]
---

# {issuer_name} - 财务分析

## 主要财务数据

| 项目 | 2024 年 | 2023 年 | 2022 年 |
|------|---------|---------|---------|
| 资产总计 | | | |
| 负债总计 | | | |
| 所有者权益 | | | |
| 营业收入 | | | |
| 净利润 | | | |
| 经营活动现金流净额 | | | |

## 偿债能力指标

| 指标 | 2024 年 | 2023 年 | 2022 年 |
|------|---------|---------|---------|
| 资产负债率 | | | |
| 流动比率 | | | |
| 速动比率 | | | |
| EBITDA 利息保障倍数 | | | |

## 资产结构分析

### 经营性资产

| 项目 | 金额 | 占比 | 说明 |
|------|------|------|------|
| | | | |

### 非经营性资产

| 项目 | 金额 | 占比 | 说明 |
|------|------|------|------|
| | | | |

### 政府性资产识别

| 资产类型 | 金额 | 收益特征 | 交易对手 |
|---------|------|---------|---------|
| | | □无收益 □低收益 | □政府 □政府部门 □其他 |

---
**来源**: {extractor.pdf_name}
**提取日期**: {pd.Timestamp.now().strftime('%Y-%m-%d')}
{fund_md}"""
            with open(analysis_file, 'w', encoding='utf-8') as f:
                f.write(full_content)
            print(f"   创建: {analysis_file}")


def main():
    """主函数：处理 raw/ 目录下的所有 PDF"""
    raw_dir = Path("raw")
    knowledge_dir = "knowledge"

    if not raw_dir.exists():
        print(f"错误: {raw_dir} 目录不存在")
        return

    # 查找所有 PDF 文件
    pdf_files = list(raw_dir.glob("*.pdf"))

    if not pdf_files:
        print(f"在 {raw_dir} 中未找到 PDF 文件")
        return

    print(f"找到 {len(pdf_files)} 个 PDF 文件")
    print(f"开始提取表格数据...")

    results = []
    for pdf_path in pdf_files:
        try:
            result = process_pdf_with_camelot(str(pdf_path), knowledge_dir)
            results.append(result)
        except Exception as e:
            print(f"处理 {pdf_path.name} 时出错: {e}")
            continue

    # 输出汇总
    print(f"\n{'='*60}")
    print("提取完成汇总")
    print(f"{'='*60}")
    for r in results:
        print(f"\n{r['issuer']}:")
        print(f"  - 财务表格: {len(r['financial_tables'])} 个")
        print(f"  - 募资用途表: {len(r['fund_usage_tables'])} 个")

    print(f"\n表格数据已保存到 {knowledge_dir}/05-资产状况/")


if __name__ == "__main__":
    main()
