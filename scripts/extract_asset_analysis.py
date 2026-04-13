#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
从募集说明书第五节提取资产分析相关内容
使用 camelot-py 提取表格，使用 PyMuPDF 提取文字
"""

import fitz
import os
import re
from datetime import datetime
from pathlib import Path

# 尝试导入camelot用于表格提取
try:
    import camelot
    import pandas as pd
    CAMELOT_AVAILABLE = True
except ImportError:
    CAMELOT_AVAILABLE = False
    print("警告: camelot-py 未安装，表格提取功能将受限")


class AssetAnalysisExtractor:
    """资产分析内容提取器 - 使用 camelot 提取表格，PyMuPDF 提取文字"""

    def __init__(self, pdf_path: str):
        self.pdf_path = pdf_path
        self.pdf_name = os.path.basename(pdf_path)
        self.doc = None
        self.issuer_name = self._parse_issuer_name()

    def _parse_issuer_name(self) -> str:
        """从文件名提取发行人名称"""
        name = self.pdf_name.replace(".pdf", "")
        match = re.match(r'(.*?)(20\d{2}年)', name)
        if match:
            return match.group(1).strip()
        return name

    def open_pdf(self):
        """打开 PDF 文件"""
        self.doc = fitz.open(self.pdf_path)

    def close_pdf(self):
        """关闭 PDF 文件"""
        if self.doc:
            self.doc.close()

    def find_section_five_range(self) -> tuple:
        """查找第五节的页码范围"""
        if not self.doc:
            self.open_pdf()

        start_page = None
        end_page = len(self.doc)

        # 收集所有可能的第五节开始页
        possible_starts = []

        for i, page in enumerate(self.doc):
            text = page.get_text()
            # 匹配"第五节"和"财务"或"会计"关键词
            if '第五节' in text and ('财务' in text or '会计' in text):
                # 检查是否是正文页（点号数量少）
                dot_count = text.count('.')
                if dot_count < 100:
                    possible_starts.append((i, dot_count))

        # 如果找到多个候选，选择页码最大的（正文通常在目录之后）
        if possible_starts:
            possible_starts.sort(key=lambda x: x[0])
            start_page = possible_starts[-1][0]

        if start_page is None:
            # 尝试其他匹配方式
            for i, page in enumerate(self.doc):
                text = page.get_text()
                if '财务会计信息' in text and text.count('.') < 100:
                    if '第五节' in text[:500]:
                        possible_starts.append(i)

            if possible_starts:
                start_page = max(possible_starts)

        # 查找第六节作为结束页
        if start_page is not None:
            for i in range(start_page + 1, len(self.doc)):
                text = self.doc[i].get_text()
                if '第六节' in text and ('信用状况' in text or '发行人信用' in text):
                    end_page = i
                    break

        return (start_page, end_page)

    def extract_tables_with_camelot(self, start_page: int, end_page: int) -> list:
        """使用 camelot 提取指定页码范围的表格"""
        if not CAMELOT_AVAILABLE:
            return []

        tables = []
        try:
            # camelot 页码从 1 开始
            page_range = f"{start_page + 1}-{end_page}"

            # 先尝试 lattice 模式（适合有边框的表格）
            camelot_tables = camelot.read_pdf(
                self.pdf_path,
                pages=page_range,
                flavor='lattice',
                line_scale=40
            )

            # 如果没有找到表格，尝试 stream 模式（适合无框线表格）
            if len(camelot_tables) == 0:
                camelot_tables = camelot.read_pdf(
                    self.pdf_path,
                    pages=page_range,
                    flavor='stream'
                )

            for table in camelot_tables:
                tables.append({
                    'page': table.page,
                    'data': table.df,
                    'accuracy': table.accuracy
                })

        except Exception as e:
            print(f"    camelot 提取表格警告: {e}")

        return tables

    def table_to_markdown(self, df) -> str:
        """将 pandas DataFrame 转换为 Markdown 表格"""
        if df is None or df.empty:
            return ""

        # 清理数据
        df = df.copy()
        df = df.replace(r'^\s*$', '', regex=True)
        df = df.fillna('')

        # 生成 Markdown
        lines = []

        # 表头
        headers = df.iloc[0].tolist() if len(df) > 0 else []
        if not any(headers):
            headers = [f"列{i+1}" for i in range(len(df.columns))]

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

    def extract_text_content(self, start_page: int, end_page: int) -> dict:
        """
        使用 PyMuPDF 提取文本内容
        返回包含主要财务指标和资产结构分析的字典
        """
        financial_content = []
        asset_structure_content = []

        collecting_financial = False
        collecting_asset = False

        financial_end_patterns = ['三、发行人财务状况分析', '三、发行人财务', '财务状况分析', '四、发行人财务']
        asset_end_patterns = ['（二）负债结构分析', '（二）负债分析', '负债结构分析', '（二）现金流量分析', '四、盈利能力分析']

        # 首先查找资产结构表的位置
        asset_table_page = None
        for i in range(start_page, min(end_page, len(self.doc))):
            text = self.doc[i].get_text()
            if ('流动资产合计' in text and '非流动资产合计' in text) or \
               ('货币资金' in text and '流动资产' in text[:500]):
                asset_table_page = i
                break

        for i in range(start_page, min(end_page, len(self.doc))):
            text = self.doc[i].get_text()

            # 提取主要财务指标部分
            if not collecting_financial and not collecting_asset:
                markers = [
                    '（二）财务数据', '（二）主要财务指标', '（二）财务数据和财务指标',
                    '财务数据和财务指标情况', '主要财务指标情况', '主要财务数据和财务指标',
                    '三、发行人最近两年及一期主要财务指标', '三、发行人主要财务指标',
                    '发行人主要财务指标'
                ]
                for marker in markers:
                    if marker in text:
                        collecting_financial = True
                        start_idx = text.find(marker)
                        financial_content.append(f"\n来源：第 {i+1} 页\n")
                        financial_content.append(text[start_idx:])
                        break

            elif collecting_financial and not collecting_asset:
                # 检查是否到达财务指标结束位置
                for pattern in financial_end_patterns:
                    if pattern in text:
                        end_idx = text.find(pattern)
                        if end_idx >= 0:
                            financial_content.append(text[:end_idx])
                        collecting_financial = False
                        break
                else:
                    financial_content.append(text)

            # 提取资产结构分析部分
            if not collecting_asset:
                if '（一）资产结构分析' in text:
                    collecting_asset = True
                    start_idx = text.find('（一）资产结构分析')
                    asset_structure_content.append(f"\n来源：第 {i+1} 页\n")
                    asset_structure_content.append(text[start_idx:])
                elif '资产结构分析' in text:
                    if ('三、发行人财务状况' in text[:800] or '三、发行人财务' in text[:800] or
                        '四、发行人财务状况' in text[:800] or '四、发行人财务' in text[:800] or
                        '发行人资产结构' in text):
                        collecting_asset = True
                        start_idx = text.find('（一）资产结构分析')
                        if start_idx < 0:
                            start_idx = text.find('资产结构分析')
                        asset_structure_content.append(f"\n来源：第 {i+1} 页\n")
                        asset_structure_content.append(text[start_idx:])
                elif asset_table_page is not None and i >= asset_table_page:
                    if ('（1）货币资金' in text or '1、货币资金' in text or
                        '（2）应收账款' in text or '2、非流动资产' in text or
                        '1、流动资产分析' in text):
                        collecting_asset = True
                        if '（1）货币资金' in text or '1、货币资金' in text:
                            start_idx = text.find('（1）货币资金') if '（1）货币资金' in text else text.find('1、货币资金')
                        else:
                            start_idx = 0
                        asset_structure_content.append(f"\n来源：第 {i+1} 页\n")
                        asset_structure_content.append(text[start_idx:])
            else:
                # 检查是否到达资产分析结束位置
                for pattern in asset_end_patterns:
                    if pattern in text:
                        end_idx = text.find(pattern)
                        if end_idx >= 0:
                            asset_structure_content.append(text[:end_idx])
                        collecting_asset = False
                        break
                else:
                    asset_structure_content.append(text)

        return {
            'financial': '\n'.join(financial_content) if financial_content else "未找到主要财务指标内容",
            'asset_structure': '\n'.join(asset_structure_content) if asset_structure_content else "未找到资产结构分析内容"
        }

    def clean_text_content(self, content: str) -> str:
        """清理文本内容，移除页眉页脚和纯文本表格"""
        if not content:
            return ""

        lines = content.split('\n')
        cleaned_lines = []
        skip_table_mode = False
        table_indicator_count = 0

        i = 0
        while i < len(lines):
            line = lines[i].strip()

            # 跳过页眉页脚
            if re.match(r'^\s*募集说明书\s*$', line):
                i += 1
                continue
            if re.match(r'^\s*\d+\s*$', line):  # 页码
                i += 1
                continue
            if self.issuer_name in line and len(line.strip()) < len(self.issuer_name) + 5:
                i += 1
                continue

            # 检测纯文本表格的开始（连续的财务指标行）
            # 如果一行是财务指标名称，下一行是数值，则可能是表格
            if not skip_table_mode:
                if self._is_table_start_line(lines, i):
                    skip_table_mode = True
                    table_indicator_count = 0
                    i += 1
                    continue

            if skip_table_mode:
                # 检查是否结束表格模式
                if not line or self._is_narrative_text(line):
                    table_indicator_count += 1
                    if table_indicator_count > 2:  # 连续2行非表格内容，结束跳过模式
                        skip_table_mode = False
                        table_indicator_count = 0
                else:
                    table_indicator_count = 0
                i += 1
                continue

            cleaned_lines.append(lines[i])
            i += 1

        content = '\n'.join(cleaned_lines)

        # 清理多余空行
        content = re.sub(r'\n{3,}', '\n\n', content)

        return content.strip()

    def _is_table_start_line(self, lines: list, idx: int) -> bool:
        """检查当前行是否是纯文本表格的开始"""
        if idx >= len(lines):
            return False

        line = lines[idx].strip()

        # 表格开始的标志："项目" 单独一行，且后面跟着财务指标或日期
        if line == '项目' or line == '项目 ':
            # 检查后续行
            has_date = False
            has_indicator = False
            for j in range(idx + 1, min(idx + 10, len(lines))):
                next_line = lines[j].strip()
                if re.match(r'^20\d{2}.*(年|末|月)', next_line):
                    has_date = True
                if self._is_financial_indicator_name(next_line):
                    has_indicator = True
                if has_date and has_indicator:
                    return True
            return False

        # 检查是否是日期表头行（连续的日期行）
        if re.match(r'^20\d{2}.*(年|末|月)', line):
            # 检查前后行是否也是日期或项目
            prev_line = lines[idx - 1].strip() if idx > 0 else ""
            next_line = lines[idx + 1].strip() if idx + 1 < len(lines) else ""
            if prev_line == '项目' or re.match(r'^20\d{2}', next_line):
                return True

        return False

    def _is_financial_indicator_name(self, line: str) -> bool:
        """检查是否是财务指标名称"""
        indicators = [
            '总资产', '总负债', '全部债务', '所有者权益', '净资产',
            '营业收入', '营业总收入', '利润总额', '净利润', '归属于',
            '经营活动', '投资活动', '筹资活动',
            '流动比率', '速动比率', '资产负债率', '债务资本比率',
            '营业毛利率', '总资产回报率', '净资产收益率', 'EBITDA',
            '应收账款周转率', '存货周转率',
            '货币资金', '应收账款', '预付款项', '其他应收款', '存货',
            '流动资产', '非流动资产', '资产总计',
            '固定资产', '在建工程', '无形资产', '投资性房地产',
        ]
        return any(ind in line for ind in indicators)

    def _is_narrative_text(self, line: str) -> bool:
        """检查是否是叙述性文本（不是表格数据）"""
        line = line.strip()
        if not line:
            return True

        # 如果行很长，可能是段落文本
        if len(line) > 100:
            return True

        # 如果以这些词开头，可能是叙述文本
        narrative_starts = ['报告期', '最近', '截至', '主要系', '发行人', '公司', '注：', '注1', '注2',
                           '（1）', '（2）', '（3）', '1、', '2、', '3、', '（一）', '（二）']
        for start in narrative_starts:
            if line.startswith(start):
                return True

        # 如果包含这些词，可能是说明文字
        narrative_keywords = ['万元', '亿元', '占比', '合计', '比例', '主要', '系', '所致']
        for kw in narrative_keywords:
            if kw in line and len(line) > 30:
                return True

        return False

    def generate_asset_status_note(self, output_dir: str) -> str:
        """生成资产状况笔记 - 使用 camelot 提取表格，PyMuPDF 提取文字"""
        # 获取第五节页码范围
        start_page, end_page = self.find_section_five_range()
        if start_page is None:
            return "未找到第五节内容"

        print(f"    第五节范围: 第{start_page+1}-{end_page}页")

        # 1. 使用 camelot 提取表格
        tables_md = ""
        if CAMELOT_AVAILABLE:
            print(f"    使用 camelot 提取表格...")
            tables = self.extract_tables_with_camelot(start_page, end_page)
            if tables:
                print(f"    找到 {len(tables)} 个表格")
                for i, table in enumerate(tables):
                    tables_md += f"\n### 表格 {i+1} (第{table['page']}页)\n\n"
                    tables_md += self.table_to_markdown(table['data'])
                    tables_md += "\n\n"
            else:
                print(f"    未找到表格")

        # 2. 使用 PyMuPDF 提取文字内容
        print(f"    使用 PyMuPDF 提取文字内容...")
        text_content = self.extract_text_content(start_page, end_page)

        financial_text = self.clean_text_content(text_content['financial'])
        asset_text = self.clean_text_content(text_content['asset_structure'])

        template = f"""---
created: {datetime.now().strftime('%Y-%m-%d')}
type: asset_analysis
tags: [财务/资产分析]
---

# {self.issuer_name} - 资产状况

## 一、主要财务指标

{financial_text}

### 财务数据表格

{tables_md}

---

## 二、资产结构分析

{asset_text}

---

**来源**: {self.pdf_name}
**提取日期**: {datetime.now().strftime('%Y-%m-%d')}
"""

        # 保存文件
        output_path = Path(output_dir) / "05-资产状况" / f"{self.issuer_name}-资产状况.md"
        output_path.parent.mkdir(parents=True, exist_ok=True)

        with open(output_path, 'w', encoding='utf-8') as f:
            f.write(template)

        return str(output_path)


def process_pdf(pdf_path: str, knowledge_base_dir: str = "knowledge") -> dict:
    """处理单个PDF"""
    print(f"\n处理: {os.path.basename(pdf_path)}")

    extractor = AssetAnalysisExtractor(pdf_path)
    extractor.open_pdf()

    result = {
        'issuer': extractor.issuer_name,
        'output_file': None,
        'success': False
    }

    try:
        output_file = extractor.generate_asset_status_note(knowledge_base_dir)
        result['output_file'] = output_file
        result['success'] = True
        print(f"  ✓ 已生成: {output_file}")
    except Exception as e:
        print(f"  ✗ 错误: {e}")
        result['error'] = str(e)
    finally:
        extractor.close_pdf()

    return result


def main():
    """批量处理 raw 目录下的 PDF"""
    raw_dir = Path("raw")
    knowledge_dir = "knowledge"

    if not raw_dir.exists():
        print(f"错误: {raw_dir} 目录不存在")
        return

    pdf_files = list(raw_dir.glob("*.pdf"))

    if not pdf_files:
        print(f"在 {raw_dir} 中未找到 PDF 文件")
        return

    print(f"找到 {len(pdf_files)} 个 PDF 文件")
    print(f"开始提取资产分析内容...")
    print(f"使用: PyMuPDF 提取文字 + camelot-py 提取表格")

    results = []
    for pdf_path in pdf_files:
        result = process_pdf(str(pdf_path), knowledge_dir)
        results.append(result)

    # 输出汇总
    print(f"\n{'='*60}")
    print("提取完成汇总")
    print(f"{'='*60}")
    success_count = sum(1 for r in results if r['success'])
    print(f"成功: {success_count}/{len(results)}")

    for r in results:
        status = "✓" if r['success'] else "✗"
        print(f"  {status} {r['issuer']}")
        if r['success']:
            print(f"     输出: {r['output_file']}")
        else:
            print(f"     错误: {r.get('error', '未知错误')}")


if __name__ == "__main__":
    main()
