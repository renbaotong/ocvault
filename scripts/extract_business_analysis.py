#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
主营业务分析提取器 v3.0 - 优化版
改进点：
1. 改进章节定位逻辑，支持更多章节格式
2. 修复表格格式问题（处理换行符）
3. 改进表格识别算法
4. 增加表格标题识别
5. 修复表头处理
"""

import os
import re
from datetime import datetime
from typing import Dict, List, Optional, Tuple, Any

import pdfplumber
import fitz

from extractors import (
    BaseExtractor,
    BUSINESS_ANALYSIS_PATTERNS,
    clean_text,
    find_section,
    validate_extraction,
)


class BusinessAnalysisExtractorV3(BaseExtractor):
    """主营业务分析提取器 v3.0"""

    NOTE_TYPE = "business_analysis"
    OUTPUT_DIR = "04-主营业务分析"
    TAGS = ["业务/主营"]

    def __init__(self, pdf_path: str):
        super().__init__(pdf_path)

    def extract_revenue_table(self) -> Dict[str, str]:
        """
        提取营业收入、成本、毛利率表格 v3.0
        Returns:
            包含营业收入表、营业成本表、毛利率表的字典
        """
        return self._extract_tables_v3()

    def _extract_tables_v3(self) -> Dict[str, str]:
        """
        使用改进的表格提取算法 v3.0
        """
        result = {
            "revenue": "",
            "cost": "",
            "margin": ""
        }

        try:
            # 第一步：找到主营业务章节的位置
            business_section_pages = self._find_business_section_pages_v3()
            if not business_section_pages:
                print("  未找到主营业务章节")
                return result

            print(f"  主营业务章节页面: {[p+1 for p in business_section_pages]}")

            # 第二步：在主营业务章节页面及其相邻页面中提取表格
            # 扩展页面范围：每个找到的页面前后各加3页，确保不遗漏相邻的成本/毛利率表格
            expanded_pages = set()
            for p in business_section_pages:
                for offset in range(-2, 4):  # 前2页到后3页
                    np = p + offset
                    if 0 <= np < 200:  # 限制最大页面范围
                        expanded_pages.add(np)
            expanded_pages = sorted(expanded_pages)

            page_data = []  # [(page_num, table_idx, table, page_text, section_type), ...]

            # 使用 PyMuPDF find_tables() 作为主要提取方法，
            # pdfplumber 作为备用（对某些 PDF 格式更好）
            doc = fitz.open(self.pdf_path)

            for page_num in expanded_pages:
                if page_num >= len(doc):
                    continue
                page = doc[page_num]
                page_text = page.get_text() or ""

                # 方法1：PyMuPDF find_tables()
                pymupdf_tables = []
                try:
                    tabs = page.find_tables()
                    for tab in tabs.tables:
                        data = tab.extract()
                        if data and len(data) >= 2:
                            pymupdf_tables.append(data)
                except:
                    pass

                # 方法2：如果 PyMuPDF 没有找到表格，尝试 pdfplumber
                if not pymupdf_tables:
                    try:
                        import pdfplumber
                        with pdfplumber.open(self.pdf_path) as pdf:
                            if page_num < len(pdf.pages):
                                pp_page = pdf.pages[page_num]
                                pp_tables = pp_page.extract_tables()
                                for t in pp_tables:
                                    if t and len(t) >= 2:
                                        pymupdf_tables.append(t)
                    except:
                        pass

                if pymupdf_tables:
                    # 分析页面文本，找出章节类型
                    section_info = self._analyze_page_section_v3(page_text)
                    for idx, table in enumerate(pymupdf_tables):
                        if table and len(table) >= 2:
                            # 清理表格数据
                            cleaned_table = self._clean_table_data(table)
                            if cleaned_table and len(cleaned_table) >= 2:
                                page_data.append((page_num, idx, cleaned_table, page_text, section_info))

            doc.close()

            # 第三步：识别并分配表格类型
            result = self._assign_table_types_v3(page_data, result)

        except Exception as e:
            print(f"  提取表格失败: {e}")
            import traceback
            traceback.print_exc()

        return result

    def _find_business_section_pages_v3(self) -> List[int]:
        """
        找到主营业务章节所在的页面范围 v3.0
        支持多种章节编号格式
        """
        pages = []

        try:
            doc = fitz.open(self.pdf_path)

            # 扩展章节标题匹配模式
            section_patterns = [
                # 标准第四节
                (r'第[四4]节\s*发行人基本情况', '第四节'),
                # （二）发行人主营业务情况
                (r'[（(][二2][)）]\s*发行人.*主营业务', '主营业务(二)'),
                # 七、发行人主营业务情况
                (r'[七7][、.\s]+发行人.*主营业务', '七、主营业务'),
                # 发行人主营业务情况
                (r'发行人.*主营业务.*情况', '主营业务'),
                # 营业收入、营业成本、毛利率情况
                (r'营业收入.*营业成本.*毛利率', '收入成本毛利'),
            ]

            section_pages = []
            for page_num in range(len(doc)):
                page = doc[page_num]
                text = page.get_text()

                for pattern, name in section_patterns:
                    if re.search(pattern, text):
                        section_pages.append((page_num, name, text))
                        print(f"    找到{name}: 第{page_num + 1}页")
                        break

            # 第二步：找到包含营业收入表格的页面
            table_pages = []
            for page_num in range(len(doc)):
                page = doc[page_num]
                text = page.get_text()

                # 查找包含营业收入表格特征的页面
                if self._is_relevant_page(text):
                    if page_num not in [p for p, _, _ in table_pages]:
                        table_pages.append((page_num, text, self._is_relevant_page(text)))

            # 第三步：确定搜索范围
            if section_pages and table_pages:
                # 找到最接近章节标题的表格页面
                for section_page, section_name, section_text in section_pages:
                    # 查找该章节后续的相关表格页面（最多100页，确保覆盖财务数据章节的表格）
                    for p in range(section_page, min(section_page + 100, len(doc))):
                        if p not in pages:
                            page_text = doc[p].get_text()
                            if self._is_relevant_page(page_text):
                                pages.append(p)

            # 如果没有找到，尝试直接查找包含表格特征的页面
            # 扩大搜索范围至前100页
            if not pages:
                for page_num in range(min(100, len(doc))):
                    page = doc[page_num]
                    text = page.get_text()

                    if self._is_relevant_page(text):
                        if page_num not in pages:
                            pages.append(page_num)

                    # 检查是否到达下一节
                    if re.search(r'第[五5]节|^\s*[八8][、.]', text):
                        if pages and page_num > max(pages):
                            break

            doc.close()

            # 确保页面按顺序排列
            pages.sort()

        except Exception as e:
            print(f"  查找章节失败: {e}")

        return pages

    def _is_relevant_page(self, text: str) -> bool:
        """检查页面是否包含相关表格"""
        # 必须包含报告期年份（2022-2025）
        has_year = bool(re.search(r'202[2345]', text))
        if not has_year:
            return False

        # 核心判断：页面必须包含标准的主营业务收入/成本/毛利率章节标题或变体
        standard_section_patterns = [
            r'发行人报告期内营业收入.*毛利润.*毛利率',
            r'发行人报告期内营业收入.*营业成本.*毛利率',
            r'营业收入、营业成本、毛利率',
            r'营业收入.*营业成本.*毛利率情况',
            r'营业收入构成情况',
            r'营业收入情况表',
            r'分板块营业收入',
            r'主营业务收入构成',
            r'主营业务板块收入',
            r'营业收入结构',
            r'报告期内.*营业收入.*情况',
            r'报告期内.*营业收入构成',
            r'近两年.*营业收入.*情况',
            r'报告期.*营业收入.*如下',
            r'发行人.*主营业务.*收入情况',
            # 营业成本专属
            r'营业成本.*构成',
            r'营业成本.*情况',
            r'营业成本.*如下',
            r'主营业务成本.*构成',
            r'主营业务成本.*情况',
            r'主营业务成本.*如下',
            r'成本构成情况',
            r'营业成本构成情况表',
            r'主营业务成本情况表',
            # 毛利润/毛利率专属
            r'毛利润.*构成',
            r'毛利润.*情况',
            r'毛利润.*如下',
            r'毛利率.*构成',
            r'毛利率.*情况',
            r'毛利率.*如下',
            r'各业务板块.*毛利润',
            r'各业务板块.*毛利率',
            r'营业毛利率构成',
            r'营业毛利润构成',
            r'各业务板块.*毛利润及毛利率',
        ]

        for pattern in standard_section_patterns:
            if re.search(pattern, text):
                return True

        # 扩展匹配：包含"营业收入"或"营业成本"或"毛利率"且同时包含"金额"+"占比"
        has_financial_table = ('金额' in text and '占比' in text) or \
                              bool(re.search(r'(万元|亿元).*占比', text))
        if has_financial_table and ('营业收入' in text or '营业成本' in text or '毛利率' in text or '毛利润' in text):
            return True

        return False

    def _analyze_page_section_v3(self, page_text: str) -> Dict[str, any]:
        """
        分析页面包含的章节类型 v4.0
        改进：更精确的章节位置检测
        """
        text_lower = page_text

        # 查找各章节的标题位置
        revenue_patterns = ['营业收入构成', '营业收入情况', '营业收入如下', '分板块营业收入', '主营业务收入构成', '主营业务板块收入', '营业收入结构', '营业收入构成情况']
        cost_patterns = ['营业成本构成', '营业成本情况', '营业成本如下', '主营业务成本构成', '主营业务成本情况', '主营业务成本如下', '营业成本构成情况', '成本构成情况']
        margin_patterns = ['毛利率构成', '毛利率情况', '毛利率如下', '毛利润构成', '毛利润情况', '毛利润如下', '营业毛利率构成', '营业毛利润构成', '各业务板块毛利润', '各业务板块毛利率']

        def find_first_position(patterns, text):
            min_pos = len(text)
            for pattern in patterns:
                pos = text.find(pattern)
                if pos >= 0 and pos < min_pos:
                    min_pos = pos
            return min_pos if min_pos < len(text) else -1

        revenue_idx = find_first_position(revenue_patterns, text_lower)
        cost_idx = find_first_position(cost_patterns, text_lower)
        margin_idx = find_first_position(margin_patterns, text_lower)

        # 确定哪个章节在前
        sections = []
        if revenue_idx >= 0:
            sections.append(('revenue', revenue_idx))
        if cost_idx >= 0:
            sections.append(('cost', cost_idx))
        if margin_idx >= 0:
            sections.append(('margin', margin_idx))

        sections.sort(key=lambda x: x[1])

        # 记录页面中各关键词的最后出现位置（用于判断表格归属）
        revenue_last = text_lower.rfind('营业收入')
        cost_last = text_lower.rfind('营业成本')
        margin_last = text_lower.rfind('毛利率')
        profit_last = text_lower.rfind('毛利润')

        return {
            'has_revenue': revenue_idx >= 0,
            'has_cost': cost_idx >= 0,
            'has_margin': margin_idx >= 0,
            'revenue_idx': revenue_idx,
            'cost_idx': cost_idx,
            'margin_idx': margin_idx,
            'section_order': [s[0] for s in sections],
            'revenue_last': revenue_last,
            'cost_last': cost_last,
            'margin_last': margin_last,
            'profit_last': profit_last,
        }

    def _clean_table_data(self, table: List[List[Optional[str]]]) -> List[List[str]]:
        """
        清理表格数据：
        1. 将None替换为空字符串
        2. 处理单元格内的换行符
        3. 去除多余空格
        4. 确保每行长度一致
        """
        if not table:
            return []

        # 找到最大列数
        max_cols = max(len(row) for row in table if row)

        cleaned = []
        for row in table:
            if not row:
                continue

            cleaned_row = []
            for cell in row:
                if cell is None:
                    cell_str = ""
                else:
                    cell_str = str(cell)
                    # 处理换行符 - 替换为空格
                    cell_str = cell_str.replace('\n', ' ').replace('\r', ' ')
                    # 去除多余空格（但保留中文字符之间的单个空格）
                    cell_str = ' '.join(cell_str.split())
                    # 修复中文之间的异常空格断裂（如"供水制水业 务" -> "供水制水业务"）
                    cell_str = re.sub(r'([一-鿿])\s+([一-鿿])', r'\1\2', cell_str)
                cleaned_row.append(cell_str)

            # 补齐列数
            while len(cleaned_row) < max_cols:
                cleaned_row.append("")

            # 只保留非空行
            if any(cleaned_row):
                cleaned.append(cleaned_row)

        return cleaned

    def _detect_table_continuation(self, prev_table, curr_table, prev_page_text="", curr_page_text="") -> bool:
        """检测当前表格是否为上一页表格的延续（跨页表格）"""
        if not prev_table or not curr_table:
            return False

        prev_cols = len(prev_table[0]) if prev_table else 0
        curr_cols = len(curr_table[0]) if curr_table else 0

        # 列数必须一致
        if prev_cols != curr_cols or prev_cols < 2:
            return False

        # 新增：检查当前页第一行是否为完全不同的表头类型
        # 如果第一行包含明显的独立表格关键词（如景区名称、许可证编号等），不合并
        curr_first_row = curr_table[0] if curr_table else []
        curr_first_row_text = ' '.join([c or '' for c in curr_first_row])
        independent_table_markers = [
            '景区名称', '景区等级', '主要景点', '收费标准', '门票收费',
            '许可证编号', '开采河流', '采砂区', '有效期限',
            '供应商一', '供应商二', '供应商三', '采购产品',
            '项目名称', '是否为关联方',
            '元/吨', '原水费',
        ]
        if any(kw in curr_first_row_text for kw in independent_table_markers):
            return False

        # 新增：检查上一页最后一行是否为"综合毛利率"等终结性行（类似合计但不是"合计"）
        prev_last_row = prev_table[-1] if prev_table else []
        prev_last_row_text = ' '.join([c or '' for c in prev_last_row])
        terminal_markers = ['综合毛利率', '综合毛利', '合计毛利率', '小计', '合计', '总计']
        if any(kw in prev_last_row_text for kw in terminal_markers):
            return False

        # 检查当前页第一行是否为表头行（重复表头的跨页情况）
        curr_first_row_text = ' '.join([c or '' for c in curr_table[0]])
        # 同时检查前两行的 header 指标（有些表头跨两行）
        curr_second_row_text = ' '.join([c or '' for c in curr_table[1]]) if len(curr_table) > 1 else ''
        curr_combined_text = curr_first_row_text + ' ' + curr_second_row_text
        header_indicators = ['业务板块', '业务板块名称', '业务名称', '金额', '占比',
                           '业务种类', '业务类型']
        header_count = sum(1 for kw in header_indicators if kw in curr_combined_text)
        # 单独检查第一行的关键指标
        first_row_key_count = sum(1 for kw in ['业务板块', '业务板块名称', '业务名称', '业务种类', '业务类型'] if kw in curr_first_row_text)

        # 检查上一页最后一行是否为"合计"行
        is_prev_total = False
        if prev_table:
            last_row = prev_table[-1]
            last_row_text = ' '.join([c or '' for c in last_row])
            is_prev_total = '合计' in last_row_text or '小计' in last_row_text

        if is_prev_total:
            return False

        # 跨页重复表头处理：如果下一页第一行是重复表头（包含业务板块等关键词），
        # 且上一页最后一行不是合计行，则判定为跨页延续
        if first_row_key_count >= 1:
            # 验证上一页第一行也包含相同的业务板块关键词
            prev_first_row = ' '.join([c or '' for c in prev_table[0]])
            prev_key_count = sum(1 for kw in ['业务板块', '业务板块名称', '业务名称', '业务种类', '业务类型'] if kw in prev_first_row)
            if prev_key_count >= 1 and prev_cols == curr_cols:
                return True
            return False

        # 检查上一页第一行是否为纯表头（没有数据），如果是，则下一页几乎一定是延续
        prev_has_data = False
        if len(prev_table) >= 3:
            for row in prev_table[2:]:
                row_vals = [c for c in row if c and c.strip()]
                if any(re.search(r'\d', v) for v in row_vals):
                    prev_has_data = True
                    break
        # 上一页没有数据行（只有表头），下一页必然是延续
        if not prev_has_data:
            return True

        # 检查上一页最后一行是否包含数字（数据行特征）
        prev_last_vals = [c for c in prev_table[-1] if c and c.strip()] if prev_table else []
        prev_last_has_num = any(re.search(r'\d', v) for v in prev_last_vals) if prev_last_vals else False
        if prev_last_has_num and header_count <= 1:
            return True

        return False

    def _merge_cross_page_tables(self, page_data: List[Tuple]) -> List[Tuple]:
        """
        合并跨页表格。
        page_data: [(page_num, table_idx, table, page_text, section_info), ...]
        返回合并后的 page_data
        """
        if not page_data:
            return page_data

        # 按页面顺序排序
        page_data.sort(key=lambda x: (x[0], x[1]))

        merged = []
        i = 0
        while i < len(page_data):
            current = list(page_data[i])
            current_table = current[2]

            # 检查下一页是否有延续表格
            while i + 1 < len(page_data):
                next_item = page_data[i + 1]
                next_page_num = next_item[0]
                next_table = next_item[2]
                next_page_text = next_item[3]
                current_page_text = current[3]

                # 只在相邻页面之间尝试合并
                if next_page_num != current[0] + 1:
                    break

                if self._detect_table_continuation(current_table, next_table, current_page_text, next_page_text):
                    # 判断是否为跨页重复表头的情况
                    next_first_row = ' '.join([c or '' for c in next_table[0]])
                    prev_first_row = ' '.join([c or '' for c in current_table[0]])
                    header_indicators = ['业务板块', '业务板块名称', '业务名称', '金额', '占比',
                                       '业务种类', '业务类型']
                    next_first_key = sum(1 for kw in ['业务板块', '业务板块名称', '业务名称', '业务种类', '业务类型'] if kw in next_first_row)
                    prev_first_key = sum(1 for kw in ['业务板块', '业务板块名称', '业务名称', '业务种类', '业务类型'] if kw in prev_first_row)

                    if next_first_key >= 1 and prev_first_key >= 1:
                        # 下一页是重复表头，需要跳过多行表头
                        # 检测表头行数：检查前两行是否包含"金额"/"占比"/"年度"等
                        header_rows = 1
                        if len(next_table) > 1:
                            hr_row = ' '.join([c or '' for c in next_table[1]])
                            if sum(1 for kw in ['金额', '占比'] if kw in hr_row) >= 1:
                                header_rows = 2
                        current_table = current_table + next_table[header_rows:]
                    elif next_first_key >= 1 or prev_first_key >= 1:
                        # 一方有业务关键词，另一方可能使用了通用的'项目'作为表头
                        # 检查下一页第一行是否和上一页第一行结构相同
                        prev_first = ' '.join([c or '' for c in current_table[0]])
                        next_first = ' '.join([c or '' for c in next_table[0]])
                        if prev_first.strip() == next_first.strip():
                            # 完全相同的表头行，跳过下一页的表头
                            header_rows = 1
                            if len(next_table) > 1:
                                hr_row = ' '.join([c or '' for c in next_table[1]])
                                if sum(1 for kw in ['金额', '占比'] if kw in hr_row) >= 1:
                                    header_rows = 2
                            current_table = current_table + next_table[header_rows:]
                        else:
                            # 表头不同，可能是数据延续
                            current_table = current_table + next_table
                    else:
                        # 常规跨页合并
                        # 检查是否有重复的表头行
                        prev_first = ' '.join([c or '' for c in current_table[0]])
                        next_first = ' '.join([c or '' for c in next_table[0]])
                        if prev_first.strip() == next_first.strip():
                            # 相同表头，跳过下一页的表头行
                            header_rows = 1
                            if len(next_table) > 1:
                                hr_row2 = ' '.join([c or '' for c in next_table[1]])
                                prev_second = ' '.join([c or '' for c in current_table[1]]) if len(current_table) > 1 else ''
                                if hr_row2.strip() == prev_second.strip():
                                    header_rows = 2
                            current_table = current_table + next_table[header_rows:]
                        else:
                            # 不同表头，检查上一页是否有合计行
                            prev_has_data = len(current_table) >= 3
                            if prev_has_data:
                                for row in current_table[2:]:
                                    row_vals = [c for c in row if c and c.strip()]
                                    if any(re.search(r'\d', v) for v in row_vals):
                                        break
                                else:
                                    prev_has_data = False

                            if not prev_has_data:
                                current_table = current_table + next_table
                            else:
                                if current_table and '合计' in ' '.join([c or '' for c in current_table[-1]]):
                                    current_table = current_table[:-1]
                                current_table = current_table + next_table

                    current[2] = current_table
                    # 合并页面文本但保留原始 section_info（不重新分析，
                    # 因为表格类型应由起始页决定）
                    current[3] = current_page_text + '\n' + next_page_text
                    i += 1
                else:
                    break

            merged.append(tuple(current))
            i += 1

        return merged

    def _is_gross_profit_amount_table(self, table: List[List[str]]) -> bool:
        """
        判断表格是否为毛利润绝对值表（万元）而非毛利率百分比表。
        核心区别：毛利润金额表包含大量 > 1000 的数值（万元量级）
        毛利率表的数值几乎全部 < 200（百分比量级）

        注意：此方法只应在表格可能为利润相关表时使用（页面上下文包含"毛利润"/"毛利率"）
        """
        if not table or len(table) < 3:
            return False

        data_rows = table[2:] if len(table) > 2 else []
        very_large_count = 0  # > 1000
        small_count = 0       # < 200

        for row in data_rows[:10]:
            for cell in row[1:]:  # 跳过第一列（业务名称）
                if not cell or cell.strip() in ('-', '', '%'):
                    continue
                try:
                    val = float(cell.replace(',', '').replace('%', '').strip())
                    if abs(val) > 1000:
                        very_large_count += 1
                    elif abs(val) < 200:
                        small_count += 1
                except (ValueError, IndexError):
                    pass

        # 毛利润金额表：有显著的 > 1000 的数值
        # 毛利率表：几乎不会有 > 1000 的数值（百分比最大 100 或略超）
        return very_large_count >= 5

    def _split_combined_table(self, table: List[List[str]], page_text: str) -> Dict[str, List[List[str]]]:
        """
        拆分包含收入/成本/毛利润/毛利率的大表格。
        检测表格内部的分隔行（如"营业成本"、"营业毛利润"等作为子表标题）。
        返回 {"revenue": [...], "cost": [...], "margin": [...]} 的子表格字典
        """
        result = {"revenue": [], "cost": [], "margin": []}
        if not table or len(table) < 2:
            return result

        # 查找分隔行：整行第一个单元格包含"营业成本"或"营业毛利润"或"营业毛利率"
        # 且该行其他单元格基本为空
        split_points = []  # [(row_idx, section_type), ...]

        for idx, row in enumerate(table):
            if not row:
                continue
            first_cell = (row[0] or '').strip()
            rest_empty = all(not (c or '').strip() for c in row[1:])

            if rest_empty and len(first_cell) < 15:
                if '营业成本' in first_cell and '收入' not in first_cell:
                    split_points.append((idx, 'cost'))
                elif '营业毛利率' in first_cell or '营业毛利润' in first_cell or first_cell.strip() in ('毛利率', '毛利润'):
                    split_points.append((idx, 'margin'))

        if not split_points:
            return result

        # 第一个分隔点之前是营业收入表
        first_split_idx = split_points[0][0]
        if first_split_idx >= 2:
            result['revenue'] = table[:first_split_idx]

        # 各个分隔点之间是成本表和毛利率表
        for sp_idx in range(len(split_points)):
            section_type = split_points[sp_idx][1]
            start_idx = split_points[sp_idx][0]

            # 跳过标题行（分隔行本身），从下一行开始
            if sp_idx + 1 < len(split_points):
                end_idx = split_points[sp_idx + 1][0]
            else:
                end_idx = len(table)

            # 如果分隔行的下一行看起来像表头（包含"金额"、"占比"等），保留它作为子表表头
            sub_table = table[start_idx:end_idx]
            if sub_table and len(sub_table) >= 2:
                # 检查第一行是否为分隔标题行（第一个单元格为标题，其余为空）
                if len(sub_table) > 0:
                    first_row = sub_table[0]
                    first_cell = (first_row[0] or '').strip()
                    rest_empty = all(not (c or '').strip() for c in first_row[1:])
                    if rest_empty and len(first_cell) < 15:
                        # 去掉分隔标题行，但如果下一行是表头则保留
                        if len(sub_table) > 1:
                            second_row = sub_table[1]
                            second_has_header = any(kw in ' '.join([c or '' for c in second_row]) for kw in ['金额', '占比', '毛利润', '毛利率'])
                            if second_has_header:
                                sub_table = sub_table[1:]  # 去掉分隔行，保留新表头
                            else:
                                sub_table = sub_table[1:]  # 去掉分隔行

                result[section_type] = sub_table

        return result

    def _assign_table_types_v3(self, page_data: List[Tuple], result: Dict[str, str]) -> Dict[str, str]:
        """
        识别表格类型并分配到相应类别 v4.0
        新增：跨页表格合并 + 大表格拆分
        """
        if not page_data:
            return result

        # 按页面顺序排序
        page_data.sort(key=lambda x: (x[0], x[1]))

        # 步骤1：合并跨页表格
        page_data = self._merge_cross_page_tables(page_data)

        # 步骤1.5：同一页面有多个表格时，优先保留数据行数更多的表格
        # 当两个表格都被识别为同一类型时，选择行数更多的那个
        filtered_page_data = []
        skip_indices = set()
        for i, item in enumerate(page_data):
            if i in skip_indices:
                continue
            page_num = item[0]
            table = item[2]
            # 检查同一页面是否有其他表格
            same_page_tables = [(j, p) for j, p in enumerate(page_data) if p[0] == page_num and j != i and j not in skip_indices]
            # 如果当前表格行数很少（<=4行），而同一页面有更大的表格（>=10行），
            # 优先检查大表格是否满足需求
            if len(table) <= 4:
                for j, other_item in same_page_tables:
                    other_table = other_item[2]
                    if len(other_table) >= 10:
                        # 当前是小表格，先不处理，等大表格
                        skip_indices.add(i)
                        break
            if i not in skip_indices:
                filtered_page_data.append(item)
        page_data = filtered_page_data

        # 步骤2：分析每个页面的表格
        tables_by_page = {}
        for page_num, table_idx, table, page_text, section_info in page_data:
            if page_num not in tables_by_page:
                tables_by_page[page_num] = []
            tables_by_page[page_num].append({
                'table_idx': table_idx,
                'table': table,
                'page_text': page_text,
                'section_info': section_info,
            })

        # 步骤2.5：同一页面多个表格时，使用段落位置分析确定各表格的归属
        # 核心思路：页面上每个表格上方的最近段落标题决定了该表格的类型
        # 例如：表格上方最近是"营业收入情况如下" → 该表格为 revenue
        table_type_hints = {}  # {(page_num, table_idx): 'revenue'/'cost'/'margin'/None}

        for page_num, page_tables in tables_by_page.items():
            if len(page_tables) < 2:
                continue
            page_text = page_tables[0]['page_text']

            # 定义各类型的段落标题关键词
            # 注意："毛利润"（金额表）和"毛利率"（百分比表）需要区分
            section_keywords = {
                'revenue': ['营业收入情况', '营业收入如下', '营业收入构成', '营业收入情况如下',
                           '营业收入结构', '分板块营业收入', '主营业务收入构成',
                           '主营业务收入如下', '主营业务收入情况', '发行人营业收入',
                           '营业收入情况表', '营业收入构成情况', '收入情况', '收入如下'],
                'cost': ['营业成本情况', '营业成本如下', '营业成本构成', '营业成本情况如下',
                        '主营业务成本构成', '主营业务成本情况', '主营业务成本如下',
                        '成本构成情况', '营业成本构成情况'],
                'margin_pct': ['毛利率情况', '毛利率如下', '毛利率构成', '毛利率情况如下',
                              '营业毛利率构成', '各业务板块毛利率'],
                'gross_profit': ['毛利润情况', '毛利润如下', '毛利润构成', '毛利润情况如下',
                                '营业毛利润构成', '各业务板块毛利润', '毛利润及毛利率'],
            }

            # 获取各表格在页面文本中的位置范围
            table_positions = []  # [(start_pos, end_pos), ...]
            for tinfo in page_tables:
                table = tinfo['table']
                first_name = ''
                last_name = ''
                for row in table[2:]:
                    if row and row[0] and row[0].strip():
                        if not first_name:
                            first_name = row[0].strip()
                        last_name = row[0].strip()

                start_pos = page_text.find(first_name) if first_name else -1
                end_pos = page_text.rfind(last_name) if last_name else -1
                if start_pos < 0:
                    start_pos = 0
                if end_pos < 0:
                    end_pos = len(page_text)
                table_positions.append((start_pos, end_pos))

            # 为每个表格查找最近的关键词
            for ti, (start_pos, end_pos) in enumerate(table_positions):
                # 方法1：查找表格起始位置之前的关键词
                best_type_before = None
                best_pos_before = -1
                for section_type, kws in section_keywords.items():
                    for kw in kws:
                        kw_pos = page_text.rfind(kw, 0, start_pos)
                        if kw_pos > best_pos_before:
                            best_pos_before = kw_pos
                            best_type_before = section_type

                # 方法2：查找表格结束位置到页面文本末尾之间的关键词
                # （处理PDF中文本顺序异常：表格数据在前，标题在后的情况）
                best_type_after = None
                best_pos_after = len(page_text)
                for section_type, kws in section_keywords.items():
                    for kw in kws:
                        kw_pos = page_text.find(kw, end_pos)
                        if kw_pos >= 0 and kw_pos < best_pos_after:
                            best_pos_after = kw_pos
                            best_type_after = section_type

                # 优先使用方法1的结果（标题在表格前是正常情况）
                # 方法2仅在方法1完全找不到关键词时使用
                use_method2 = False
                if best_pos_before < 0:
                    use_method2 = True
                elif best_pos_after < len(page_text):
                    # 方法1找到了关键词，仅在距离极远（>500字符）时才考虑方法2
                    dist_before = start_pos - best_pos_before if best_pos_before >= 0 else 9999
                    dist_after = best_pos_after - end_pos
                    if dist_after < dist_before and dist_before > 500:
                        use_method2 = True

                # 初始推断类型
                final_type = None
                if use_method2 and best_type_after:
                    final_type = best_type_after
                elif best_type_before and best_pos_before >= 0:
                    final_type = best_type_before

                # 后处理：当页面有"营业收入"且同一页面有多个大数值表格时，
                # 按数值大小排序：最大=revenue，次大=gross_profit，最小=margin
                if '营业收入' in page_text:
                    all_large_tables = []
                    for other_ti, other_tinfo in enumerate(page_tables):
                        other_table = other_tinfo['table']
                        total = 0.0
                        for row in other_table[2:3]:
                            for cell in row[1:]:
                                if cell and cell.strip():
                                    try:
                                        total += abs(float(cell.replace(',', '').replace('%', '').strip()))
                                    except:
                                        pass
                        if total > 1000:
                            all_large_tables.append((other_ti, total))

                    if len(all_large_tables) >= 2:
                        all_large_tables.sort(key=lambda x: x[1], reverse=True)
                        if ti == all_large_tables[0][0]:
                            final_type = 'revenue'
                        elif ti == all_large_tables[1][0]:
                            final_type = 'gross_profit'

                if final_type:
                    table_type_hints[(page_num, ti)] = final_type

            # 如果部分表格没有找到位置线索，但有明显的"毛利润"+"毛利率"共存
            # 且表格都有大数值特征，则按表格顺序推断
            if len(page_tables) >= 2:
                hinted_count = sum(1 for ti in range(len(page_tables)) if (page_num, ti) in table_type_hints)
                if hinted_count < len(page_tables):
                    # 检查是否有"营业收入"和"毛利润"关键词共存
                    page_lower = page_text.lower()
                    has_rev_kw = '营业收入' in page_lower
                    has_profit_kw = '毛利润' in page_lower
                    has_cost_kw = '营业成本' in page_lower

                    if has_rev_kw and has_profit_kw:
                        # 按顺序：第一个大数值表 = revenue，第二个大数值表 = 毛利润
                        large_table_indices = []
                        for ti, tinfo in enumerate(page_tables):
                            if self._is_gross_profit_amount_table(tinfo['table']):
                                large_table_indices.append(ti)

                        if len(large_table_indices) >= 2:
                            # 第一个大数值表归为 revenue
                            if (page_num, large_table_indices[0]) not in table_type_hints:
                                table_type_hints[(page_num, large_table_indices[0])] = 'revenue'
                            # 第二个大数值表归为毛利润（不作为 margin，留待后续处理）
                            if (page_num, large_table_indices[1]) not in table_type_hints:
                                table_type_hints[(page_num, large_table_indices[1])] = 'gross_profit'
                        elif len(large_table_indices) == 1:
                            # 只有一个大数值表，且页面有"营业收入" → revenue
                            idx = large_table_indices[0]
                            if (page_num, idx) not in table_type_hints:
                                table_type_hints[(page_num, idx)] = 'revenue'

                    elif has_profit_kw and not has_rev_kw:
                        # 只有"毛利润"没有"营业收入" → 大数值表归为毛利润
                        for ti, tinfo in enumerate(page_tables):
                            if self._is_gross_profit_amount_table(tinfo['table']):
                                if (page_num, ti) not in table_type_hints:
                                    table_type_hints[(page_num, ti)] = 'gross_profit'

                    # 新增：页面没有明确章节关键词，但多个表格顺序排列
                    # 按常见的 收入→成本→毛利率 顺序推断
                    if hinted_count == 0 and len(page_tables) >= 2:
                        # 检查各表格的数值特征
                        table_features = []
                        for ti, tinfo in enumerate(page_tables):
                            table = tinfo['table']
                            data_rows_check = table[2:] if len(table) > 2 else []
                            header_check = ' '.join([' '.join(row) for row in table[:2]]).lower()
                            all_check = ' '.join([' '.join(row) for row in table]).lower()

                            is_cost_header = '成本' in header_check and '收入' not in header_check
                            is_margin_header = '毛利率' in header_check or '毛利润' in header_check
                            is_amount_pct = ('金额' in header_check and '占比' in header_check) or \
                                            ('收入' in header_check and '占比' in header_check and '成本' not in header_check and '毛利率' not in header_check)

                            # 计算数值总量
                            total_val = 0.0
                            for row in data_rows_check[:5]:
                                for cell in row[1:]:
                                    if cell and cell.strip():
                                        try:
                                            total_val += abs(float(cell.replace(',', '').replace('%', '').strip()))
                                        except:
                                            pass

                            table_features.append({
                                'ti': ti,
                                'is_cost_header': is_cost_header,
                                'is_margin_header': is_margin_header,
                                'is_amount_pct': is_amount_pct,
                                'total_val': total_val,
                                'has_percentage': bool(re.search(r'\d+\.\d{2}', ' '.join([' '.join(row) for row in data_rows_check[:3]])))
                            })

                        # 按表格顺序分配：第一个大表=revenue，第二个可能=cost/margin
                        for fi, feat in enumerate(table_features):
                            key = (page_num, feat['ti'])
                            if key in table_type_hints:
                                continue
                            if feat['is_cost_header']:
                                table_type_hints[key] = 'cost'
                            elif feat['is_margin_header']:
                                table_type_hints[key] = 'margin'
                            elif feat['is_amount_pct']:
                                # 金额/占比表，且不是成本/毛利率表头 → revenue
                                table_type_hints[key] = 'revenue'

            # 数据校正：当位置推断将毛利率百分比表误分类为 gross_profit 时，
            # 通过数值特征纠正：gross_profit 表应包含大数值（万元），
            # 毛利率表包含百分比值（< 200）
            for ti, tinfo in enumerate(page_tables):
                hint = table_type_hints.get((page_num, ti))
                if hint == 'gross_profit':
                    if not self._is_gross_profit_amount_table(tinfo['table']):
                        # 不是毛利润金额表 → 可能是毛利率百分比表
                        table_type_hints[(page_num, ti)] = 'margin_pct'

            # 新增：同一类型有多个候选表格时，选择数据更完整的
            # 例如：南通的营业成本表在 page 44 是部分的（只有2行+合计），
            # 在 page 45 是完整的（6行+合计）
            type_candidates = {}  # {type: [(page_num, ti, row_count), ...]}
            for key, hint_type in table_type_hints.items():
                if hint_type in ('revenue', 'cost', 'margin'):
                    if hint_type not in type_candidates:
                        type_candidates[hint_type] = []
                    pn, ti_idx = key
                    # 找到对应的表格
                    for tinfo in page_tables:
                        if tinfo['table_idx'] == ti_idx:
                            type_candidates[hint_type].append((pn, ti_idx, len(tinfo['table'])))
                            break

            # 如果有多个页面有同一类型的表格，保留行数最多的
            for hint_type, candidates in type_candidates.items():
                if len(candidates) > 1:
                    candidates.sort(key=lambda x: x[2], reverse=True)
                    # 只保留行数最多的，其他的标记为 skip
                    best = candidates[0]
                    for c in candidates[1:]:
                        if c[2] < best[2]:  # 只有行数更少时才跳过
                            table_type_hints[c[:2]] = 'skip_incomplete'

        # 基于 type hints，设置 margin_skip 和 force_type
        margin_skip_indices = set()
        force_types = {}  # {(page_num, table_idx): forced_type}

        for key, hint_type in table_type_hints.items():
            if hint_type == 'gross_profit':
                # 毛利润表：不用于 margin 分类，也不用于 cost 分类
                margin_skip_indices.add(key)
                force_types[key] = 'gross_profit'  # 跳过该表格
            elif hint_type == 'margin_pct':
                force_types[key] = 'margin'
            elif hint_type == 'revenue':
                force_types[key] = 'revenue'
            elif hint_type == 'cost':
                force_types[key] = 'cost'
            elif hint_type == 'skip_incomplete':
                force_types[key] = 'skip'  # 跳过不完整的表格

        # 新增：校正位置推断错误 - 当表格表头明确表明是营业收入表时，覆盖位置推断的 cost 结果
        for page_num, page_tables in tables_by_page.items():
            for tinfo in page_tables:
                table = tinfo['table']
                orig_idx = tinfo['table_idx']
                header_text_check = ' '.join([' '.join(row) for row in table[:2]]).lower()
                # "收入/占比"且不含"成本"→ 应该是 revenue 而非 cost
                if ('收入' in header_text_check and '占比' in header_text_check and
                    '成本' not in header_text_check and '毛利率' not in header_text_check and
                    '毛利润' not in header_text_check):
                    key = (page_num, orig_idx)
                    if force_types.get(key) == 'cost':
                        force_types[key] = 'revenue'

        # 步骤2.6：同一页面多个结构相似表格的差异化处理
        # 当同一页面有多个表格使用相同业务名称和列结构时，通常是收入/成本/毛利率分表
        # 检测这种情况并依次分配给 revenue -> cost -> margin
        # 注意：此逻辑仅在页面没有明确的收入/成本/毛利率章节上下文时才使用
        for page_num, page_tables in tables_by_page.items():
            if len(page_tables) < 2:
                continue
            page_text = page_tables[0]['page_text']

            # 只有当页面没有明确的章节上下文，或者页面只包含单一类型的表格且该类型已填充时才应用
            # 这避免在有明确 margin 上下文的页面上误用此逻辑
            section_info = page_tables[0]['section_info']
            page_lower = page_text.lower()

            # 如果页面已有明确的毛利率上下文且有2个以上表格，且页面和表格都不包含营业收入关键词，跳过
            has_rev_kw = '营业收入' in page_lower
            has_cost_kw = '营业成本' in page_lower
            has_margin_kw = '毛利率' in page_lower or '毛利润' in page_lower
            # 移除 kw_types >= 2 的限制：当表格共享业务名称时，无论页面关键词如何，
            # 都应该应用多表格顺序分配逻辑（适用于樟树市等场景：页面同时有"营业收入"和"毛利率"关键词）
            has_rev_in_page = '营业收入' in page_lower
            has_rev_in_tables = any('营业收入' in ' '.join([' '.join(row) for row in tinfo['table']]).lower() for tinfo in page_tables)
            if has_margin_kw and not has_rev_in_page and not has_rev_in_tables:
                continue

            # 提取各表格的业务名称列表
            table_business_names = []
            for tinfo in page_tables:
                table = tinfo['table']
                names = set()
                for row in table[2:]:  # 跳过表头
                    if row and row[0] and row[0].strip():
                        cell = row[0].strip()
                        # 排除纯序号（数字）和"合计"/"小计"
                        if not re.match(r'^\d+$', cell) and cell not in ('合计', '小计', '总计'):
                            names.add(cell)
                table_business_names.append(names)

            # 检查是否有两个表格共享大量相同业务名称
            has_multi_section = False
            for i in range(len(table_business_names)):
                for j in range(i+1, len(table_business_names)):
                    overlap = len(table_business_names[i] & table_business_names[j])
                    if overlap >= 3:  # 至少3个相同业务名称
                        has_multi_section = True
                        break
                if has_multi_section:
                    break

            if has_multi_section:
                # 进一步验证：各表格的数值特征应该不同（收入有大数值，成本有大数值，毛利率有小数值）
                # 如果所有表格都是大数值或都是小数值，说明不是收入/成本/毛利率分表
                table_types_by_data = []
                table_data_signatures = []  # 存储各表格的数据签名（合计行数值）
                for tinfo in page_tables:
                    table = tinfo['table']
                    data_rows = table[2:] if len(table) > 2 else []
                    has_large = False
                    has_small = False
                    total_sum = 0.0  # 合计行数值总和
                    for row in data_rows[:5]:
                        for cell in row[1:]:
                            if not cell or cell.strip() in ('-', '', '%'):
                                continue
                            try:
                                val = float(cell.replace(',', '').replace('%', '').strip())
                                total_sum += abs(val)
                                if abs(val) > 1000:
                                    has_large = True
                                elif abs(val) < 200:
                                    has_small = True
                            except:
                                pass
                    if has_large:
                        table_types_by_data.append('large')
                    elif has_small:
                        table_types_by_data.append('small')
                    else:
                        table_types_by_data.append('unknown')
                    table_data_signatures.append(total_sum)

                # 新增：检查表格数据是否高度相似（如收入和成本使用相同的业务名称但数据不同）
                # 如果两个表格的合计行数值非常接近（误差<5%），可能是同一张表
                has_similar_tables = False
                for i in range(len(table_data_signatures)):
                    for j in range(i+1, len(table_data_signatures)):
                        if table_data_signatures[i] > 0 and table_data_signatures[j] > 0:
                            ratio = min(table_data_signatures[i], table_data_signatures[j]) / \
                                    max(table_data_signatures[i], table_data_signatures[j])
                            if ratio > 0.95:  # 数值高度相似
                                has_similar_tables = True
                                break
                    if has_similar_tables:
                        break

                # 只有当表格数据特征有混合（既有large又有small）且数据不高度相似时才应用此逻辑
                if 'large' in table_types_by_data and 'small' in table_types_by_data and not has_similar_tables:
                    # 按表格顺序依次分配给 revenue -> cost -> margin
                    assigned_types = ['revenue', 'cost', 'margin']
                    for ti, tinfo in enumerate(page_tables):
                        table = tinfo['table']
                        page_text = tinfo['page_text']
                        section_info = tinfo['section_info']

                        # 先尝试拆分
                        split_tables = self._split_combined_table(table, page_text)
                        has_split = any(v for v in split_tables.values())
                        if has_split:
                            for section_type, sub_table in split_tables.items():
                                if sub_table and len(sub_table) >= 2 and not result[section_type]:
                                    result[section_type] = self._format_table_to_markdown_v3(sub_table)
                                    print(f"  识别到 {section_type} 表格 (拆分大表格, 第{page_num + 1}页)")
                            continue

                        if ti < len(assigned_types):
                            target_type = assigned_types[ti]
                            # 安全检查：第一个表格必须有收入相关表头，才能分配为 revenue
                            # 避免将成本表误判为收入表（安吉县场景：成本表在收入表前面）
                            if target_type == 'revenue':
                                t_header = ' '.join([' '.join(row) for row in table[:2]]).lower()
                                if '收入' not in t_header:
                                    # 第一个表格不是收入表，跳过 revenue 分配
                                    continue
                            # 对于 cost 分配，需要页面有"营业成本"上下文
                            # 避免将毛利润表误判为成本表
                            page_lower = tinfo['page_text'].lower()
                            has_cost_context = '营业成本' in page_lower or '成本构成' in page_lower or '成本情况' in page_lower
                            if target_type == 'cost' and not has_cost_context:
                                # 页面没有成本上下文，跳过 cost 分配
                                continue
                            if not result[target_type]:
                                result[target_type] = self._format_table_to_markdown_v3(table)
                                print(f"  识别到 {target_type} 表格 (同页多表顺序, 第{page_num + 1}页)")
                        # 标记这些表格已处理，跳过后续常规分类
                        page_tables[ti]['_pre_assigned'] = True

        for page_num in sorted(tables_by_page.keys()):
            page_tables = tables_by_page[page_num]
            section_info = page_tables[0]['section_info']

            for ti, table_info in enumerate(page_tables):
                # 跳过已预分配的表格
                if table_info.get('_pre_assigned'):
                    continue

                table = table_info['table']
                page_text = table_info['page_text']
                orig_idx = table_info['table_idx']

                # 先尝试拆分大表格
                split_tables = self._split_combined_table(table, page_text)
                has_split = any(v for v in split_tables.values())

                if has_split:
                    for section_type, sub_table in split_tables.items():
                        if sub_table and len(sub_table) >= 2 and not result[section_type]:
                            result[section_type] = self._format_table_to_markdown_v3(sub_table)
                            print(f"  识别到 {section_type} 表格 (拆分大表格, 第{page_num + 1}页)")
                else:
                    # 预过滤：检查是否为期间费用表（销售费用、管理费用、财务费用等）
                    # 这类表格绝不应被误判为 revenue 表（即使包含"营业收入"字样）
                    all_table_text = ' '.join([' '.join(row) for row in table]).lower()
                    is_period_expense = any(kw in all_table_text for kw in [
                        '销售费用', '管理费用', '研发费用', '财务费用'
                    ]) or ('期间费用' in all_table_text and '占营业收入' in all_table_text)
                    if is_period_expense:
                        # 期间费用表，跳过（不作为 revenue/cost/margin）
                        continue
                    # 预过滤：排除供应商采购表（即使页面有"营业成本/成本构成"关键词）
                    is_supplier_table = any(kw in all_table_text for kw in [
                        '供应商一', '供应商二', '供应商三', '供应商四', '供应商五',
                        '主要采购产品', '采购金额'
                    ])
                    if is_supplier_table:
                        continue
                    # 预过滤：排除单位成本分析表（元/吨、原水费等明细）
                    is_unit_cost_table = ('元/吨' in all_table_text or '元/m³' in all_table_text or '元/立方米' in all_table_text) and \
                                         '其中：' in all_table_text
                    if is_unit_cost_table:
                        continue

                    # 检查是否有强制类型提示（使用原始 table_idx）
                    forced = force_types.get((page_num, orig_idx))
                    if forced == 'skip':
                        # 跳过不完整的表格
                        continue
                    elif forced == 'revenue' and not result.get('revenue'):
                        result['revenue'] = self._format_table_to_markdown_v3(table)
                        print(f"  识别到 revenue 表格 (位置推断, 第{page_num + 1}页)")
                        continue
                    elif forced == 'cost' and not result.get('cost'):
                        result['cost'] = self._format_table_to_markdown_v3(table)
                        print(f"  识别到 cost 表格 (位置推断, 第{page_num + 1}页)")
                        continue
                    elif forced == 'margin' and not result.get('margin'):
                        result['margin'] = self._format_table_to_markdown_v3(table)
                        print(f"  识别到 margin 表格 (位置推断, 第{page_num + 1}页)")
                        continue
                    elif forced == 'gross_profit':
                        # 毛利润表：不用于 margin，跳过
                        continue

                    # 如果是毛利润金额表且同一页面有毛利率百分比表，优先将其归类为 cost
                    is_profit_amount = self._is_gross_profit_amount_table(table)
                    is_margin_skip = (page_num, orig_idx) in margin_skip_indices

                    # force_cost 仅在毛利润金额表和毛利率百分比表明确共存时启用
                    force_cost = is_profit_amount and is_margin_skip

                    table_type = self._identify_table_type_v3(table, section_info, result, page_text, force_cost=force_cost)
                    if table_type and not result[table_type]:
                        result[table_type] = self._format_table_to_markdown_v3(table)
                        print(f"  识别到 {table_type} 表格 (第{page_num + 1}页)")

        # 后处理：当同一页面有多个结构相同但类型重复的表格时，尝试重新分配
        # 注意：此逻辑仅用于处理同一类型被重复识别的情况，不用于填充空位
        # 毛利润金额表不应用于填充 cost 空位
        for page_num, page_tables in tables_by_page.items():
            if len(page_tables) < 2:
                continue
            # 收集已分配的表格
            assigned_on_page = []
            for tinfo in page_tables:
                if tinfo.get('_pre_assigned'):
                    continue
                table = tinfo['table']
                page_text = tinfo['page_text']
                all_text = ' '.join([' '.join(row) for row in table]).lower()
                # 提取业务名称
                names = set()
                for row in table[2:]:
                    if row and row[0] and row[0].strip():
                        names.add(row[0].strip())
                assigned_on_page.append({
                    'table': table, 'page_text': page_text,
                    'names': names, 'all_text': all_text,
                    'is_gross_profit': self._is_gross_profit_amount_table(table)
                })

            # 检查是否有重复类型的表格（两个都被分类为同一类型）
            # 仅当 revenue/cost/margin 中某个类型被重复填充时才需要重新分配
            # 这里我们检查：如果页面上有多个表格共享业务名称，且第一个表格已经填充了 revenue，
            # 第二个表格也是大数值但未被分类，且不是毛利润表，则可能是 cost
            if result.get('revenue') and not result.get('cost'):
                for i in range(len(assigned_on_page)):
                    for j in range(i+1, len(assigned_on_page)):
                        overlap = len(assigned_on_page[i]['names'] & assigned_on_page[j]['names'])
                        if overlap >= 3:
                            # 第一个表格应该是 revenue，第二个可能是 cost
                            t2 = assigned_on_page[j]
                            # 排除毛利润表
                            if t2['is_gross_profit']:
                                continue
                            # 排除毛利率表（小数值）
                            data_rows = t2['table'][2:] if len(t2['table']) > 2 else []
                            has_large_values = False
                            for row in data_rows[:5]:
                                for cell in row[1:]:
                                    if not cell or cell.strip() in ('-', '', '%'):
                                        continue
                                    try:
                                        val = float(cell.replace(',', '').replace('%', '').strip())
                                        if abs(val) > 1000:
                                            has_large_values = True
                                            break
                                    except:
                                        pass
                                if has_large_values:
                                    break
                            if not has_large_values:
                                continue
                            # 检查页面是否包含"营业成本"上下文
                            if '营业成本' in t2['page_text'].lower():
                                result['cost'] = self._format_table_to_markdown_v3(t2['table'])
                                print(f"  识别到 cost 表格 (同页重分类, 第{page_num + 1}页)")
                                break
                    if result.get('cost'):
                        break

        # ===== 兜底：当任何结果字段为空时，重新扫描所有表格进行直接分类 =====
        if not result.get('revenue') or not result.get('cost') or not result.get('margin'):
            # 构建已填充的类型集合
            filled_types = {k for k, v in result.items() if v}
            needed_types = {'revenue', 'cost', 'margin'} - filled_types

            if needed_types:
                # 重新遍历所有页面数据，用更直接的表头匹配
                for page_num, table_idx, table, page_text, section_info in page_data:
                    if not needed_types:
                        break
                    # 检查该表格是否已经被使用
                    if result.get('revenue') and result.get('cost') and result.get('margin'):
                        break

                    header_text_scan = ' '.join([' '.join(row) for row in table[:2]]).lower()
                    all_text_scan = ' '.join([' '.join(row) for row in table]).lower()
                    data_rows_scan = table[2:] if len(table) > 2 else []

                    # 排除明显不相关的表格
                    if re.search(r'202[6789]|203\d', header_text_scan):
                        continue
                    if any(kw in all_text_scan for kw in ['现金流量', '筹资活动', '投资活动', '资产负债', '货币资金', '应收账款', '净利润', '借款', '子公司', '关联方', '政府补助']):
                        continue
                    # 排除期间费用表（销售费用、管理费用、研发费用、财务费用等）
                    if any(kw in all_text_scan for kw in ['销售费用', '管理费用', '研发费用', '财务费用', '期间费用合计']):
                        continue
                    # 排除物业明细表
                    if any(kw in all_text_scan for kw in ['可出租面积', '出租价格', '开工时间', '总投资额', '已投资额', '预计可租面积', '预计租金']):
                        continue
                    # 排除成本结构拆解表（直接材料、直接人工、制造费用明细）
                    if all(kw in all_text_scan for kw in ['直接材料', '直接人工', '制造费用']):
                        continue
                    # 排除供应商采购表
                    if any(kw in all_text_scan for kw in ['供应商一', '供应商二', '供应商三', '主要采购产品', '采购金额']):
                        continue
                    # 排除许可证/采砂表
                    if any(kw in all_text_scan for kw in ['许可证编号', '开采河流', '采砂区名称', '年度采砂']):
                        continue
                    # 排除景区信息表
                    if any(kw in all_text_scan for kw in ['景区名称', '景区等级', '主要景点', '门票收费']) and not re.search(r'业务板块|毛利润|毛利率', all_text_scan):
                        continue

                    # 计算数值特征
                    has_large = False
                    has_small = False
                    comma_count_scan = 0
                    for row in data_rows_scan[:10]:
                        for cell in row[1:]:
                            if not cell or cell.strip() in ('-', '', '%'):
                                continue
                            if ',' in cell and re.search(r'\d{1,3},\d{3}', cell):
                                comma_count_scan += 1
                            try:
                                val = float(cell.replace(',', '').replace('%', '').strip())
                                if abs(val) > 1000:
                                    has_large = True
                                elif abs(val) < 200:
                                    has_small = True
                            except:
                                pass

                    # 直接表头匹配
                    has_revenue_header_scan = ('营业收入' in header_text_scan) or \
                                              ('收入' in header_text_scan and '占比' in header_text_scan and '成本' not in header_text_scan)
                    has_cost_header_scan = '成本' in header_text_scan and '收入' not in header_text_scan and '毛利率' not in header_text_scan
                    has_margin_header_scan = '毛利率' in header_text_scan

                    if has_margin_header_scan and 'margin' in needed_types:
                        result['margin'] = self._format_table_to_markdown_v3(table)
                        needed_types.discard('margin')
                        print(f"  [兜底] 识别到 margin 表格 (第{page_num + 1}页)")
                        continue

                    # 当页面包含"毛利润"/"毛利率"且 cost 仍为空位时，
                    # 说明该页面可能同时包含收入表和成本表，
                    # 带有"金额/占比"结构的表格应优先归为 cost
                    # 但前提是：
                    # 1. 页面同时存在至少两个"金额/占比"表格（收入+成本）
                    # 2. revenue 已经填充（说明第一个表已被识别为收入）
                    # 3. 页面有"营业成本"关键词（说明确实有成本表上下文）
                    has_multiple_amount_tables = False
                    if page_num in tables_by_page:
                        amount_table_count = 0
                        for tinfo in tables_by_page[page_num]:
                            t = tinfo['table']
                            t_header = ' '.join([' '.join(row) for row in t[:2]]).lower()
                            if '金额' in t_header and '占比' in t_header and len(t) >= 4:
                                amount_table_count += 1
                        has_multiple_amount_tables = amount_table_count >= 2

                    is_cost_preferred = ('营业成本' in page_text) and 'cost' in needed_types and \
                                        has_multiple_amount_tables and result.get('revenue')
                    has_revenue_only_header = ('收入' in header_text_scan and '成本' not in header_text_scan and
                                               '毛利率' not in header_text_scan and '毛利润' not in header_text_scan)

                    if has_revenue_header_scan and comma_count_scan >= 2:
                        # 表头有"收入"且无"成本" → 无论页面上下文如何，都归为 revenue
                        if has_revenue_only_header and 'revenue' in needed_types:
                            result['revenue'] = self._format_table_to_markdown_v3(table)
                            needed_types.discard('revenue')
                            print(f"  [兜底] 识别到 revenue 表格 (收入表头, 第{page_num + 1}页)")
                            continue
                        elif is_cost_preferred and not result.get('revenue') and not result.get('cost'):
                            # 页面有毛利润上下文且 revenue/cost 都空缺 → 归为 cost
                            result['cost'] = self._format_table_to_markdown_v3(table)
                            needed_types.discard('cost')
                            print(f"  [兜底] 识别到 cost 表格 (第{page_num + 1}页)")
                            continue
                        elif not is_cost_preferred and 'revenue' in needed_types:
                            result['revenue'] = self._format_table_to_markdown_v3(table)
                            needed_types.discard('revenue')
                            print(f"  [兜底] 识别到 revenue 表格 (第{page_num + 1}页)")
                            continue
                        elif 'revenue' in needed_types:
                            result['revenue'] = self._format_table_to_markdown_v3(table)
                            needed_types.discard('revenue')
                            print(f"  [兜底] 识别到 revenue 表格 (第{page_num + 1}页)")
                            continue

                    if has_cost_header_scan and comma_count_scan >= 2 and 'cost' in needed_types:
                        result['cost'] = self._format_table_to_markdown_v3(table)
                        needed_types.discard('cost')
                        print(f"  [兜底] 识别到 cost 表格 (第{page_num + 1}页)")
                        continue

                    # 新增：当 revenue 已填充但 cost 仍空缺，且页面有"营业成本"上下文，
                    # 表格有"金额/占比"结构且有大数值 → 这是成本表
                    # 适用于南通江海等场景：收入表和成本表使用相同的"金额/占比"列结构
                    # 关键约束：页面必须有至少2个"金额/占比"表格（收入+成本分表），
                    # 否则会将唯一的收入表误判为成本
                    has_amount_pct_generic = '金额' in header_text_scan and '占比' in header_text_scan
                    has_cost_context = '营业成本' in page_text  # 必须明确有"营业成本"关键词
                    # 检查同一页面是否有多个"金额/占比"表格
                    _multi_amount_on_page = False
                    if page_num in tables_by_page:
                        _cnt = 0
                        for _tinfo in tables_by_page[page_num]:
                            _t = _tinfo['table']
                            _h = ' '.join([' '.join(row) for row in _t[:2]]).lower()
                            if '金额' in _h and '占比' in _h and len(_t) >= 4:
                                _cnt += 1
                        _multi_amount_on_page = _cnt >= 2
                    if (has_amount_pct_generic and has_cost_context and _multi_amount_on_page and
                        comma_count_scan >= 3 and 'cost' in needed_types and result.get('revenue')):
                        result['cost'] = self._format_table_to_markdown_v3(table)
                        needed_types.discard('cost')
                        print(f"  [兜底] 识别到 cost 表格 (金额/占比+营业成本上下文, 第{page_num + 1}页)")
                        continue

        return result

    def _identify_table_type_v3(self, table: List[List[str]], section_info: Dict, result: Dict[str, str], page_text: str = "", force_cost: bool = False) -> Optional[str]:
        """
        识别表格类型 v4.0 - 增强排除规则，避免误识别
        """
        if not table or len(table) < 2:
            return None

        # 合并表头文本
        header_text = ' '.join([' '.join(row) for row in table[:2]]).lower()
        all_text = ' '.join([' '.join(row) for row in table]).lower()

        # 获取数据区域
        data_rows = table[2:] if len(table) > 2 else []

        # ===== 第一步：排除明确不相关的表格 =====

        # 排除1：未来年份预测表（包含2026+年份）
        # 如果表头同时包含未来年份和报告期年份，也排除（这是预测表）
        has_future_years = re.search(r'202[6789]|203\d', header_text) is not None
        has_reporting_years = re.search(r'202[2345]', header_text) is not None
        if has_future_years:
            return None  # 任何包含2026+年份的表头都是预测表，排除

        # 排除2：现金流量表
        has_cashflow = any(kw in all_text for kw in ['现金流量', '筹资活动', '投资活动', '经营活动产生的现金流量'])
        if has_cashflow:
            return None

        # 排除3：利润表/损益表（同时包含利润总额、净利润、营业利润）
        has_profit_statement = all(kw in all_text for kw in ['利润总额', '净利润', '营业利润'])
        if has_profit_statement:
            return None

        # 排除4：资产负债表项目
        has_balance_sheet = any(kw in all_text for kw in [
            '总资产', '总负债', '所有者权益', '资产负债率',
            '货币资金', '应收账款', '交易性金融资产', '存货', '固定资产',
            '流动负债', '非流动负债', '短期借款', '长期借款',
            '应付账款', '预收账款', '其他应收款'
        ])
        if has_balance_sheet:
            return None

        # 排除5：期间费用表（表头包含销售费用/管理费用/财务费用等且不含"营业"）
        has_period_expense = any(kw in header_text for kw in ['销售费用', '管理费用', '财务费用', '研发费用'])
        if has_period_expense and '营业' not in header_text:
            return None
        # 更全面的期间费用表：即使含"营业"，如果没有"业务板块"列
        has_full_period_expense = all(kw in all_text for kw in ['销售费用', '管理费用', '财务费用'])
        if has_full_period_expense:
            has_business_column = any(kw in all_text for kw in ['业务板块', '业务板块名称', '业务种类', '业务类型'])
            if not has_business_column:
                return None

        # 排除6：会计差错更正/追溯重述表
        has_accounting_error = any(kw in all_text for kw in ['追溯', '重述', '差错更正', '前期差错', '调整期初'])
        if has_accounting_error:
            return None

        # 排除7：关联方交易表
        has_related_party = any(kw in all_text for kw in ['关联方', '关联关系', '关联', '合营企业', '联营企业'])
        if has_related_party:
            return None

        # 排除8：成本结构拆解表（包含直接材料、直接人工、制造费用等明细）
        has_cost_breakdown = all(kw in all_text for kw in ['直接材料', '直接人工', '制造费用'])
        if has_cost_breakdown:
            return None

        # 排除9：净利润/营业净利率表
        has_net_profit_items = any(kw in all_text for kw in [
            '净利润', '营业净利率', '平均净资产收益率', '利润总额', '所得税'
        ]) and not re.search(r'业务板块|业务名称|项目.*业务', all_text)
        if has_net_profit_items:
            has_business_column = any(kw in all_text for kw in ['业务板块', '业务板块名称', '业务种类', '业务类型'])
            if not has_business_column:
                return None

        # 排除10：借款/贷款表
        has_loan = any(kw in all_text for kw in [
            '借款类别', '质押借款', '保证借款', '组合担保借款', '信用借款',
            '抵押借款', '委托借款', '借款方式'
        ])
        if has_loan:
            return None

        # 排除11：银行授信/融资情况表
        has_financing = any(kw in all_text for kw in [
            '授信额度', '银行授信', '融资余额', '贷款银行', '借款余额',
            '提款金额', '放款金额', '提款'
        ]) and not re.search(r'业务板块|业务名称|营业收入|营业成本', all_text)
        if has_financing:
            return None

        # 排除12：政府补助表
        has_government_subsidy = any(kw in all_text for kw in ['政府补助', '财政补助', '专项资金', '补贴'])
        if has_government_subsidy:
            return None

        # 排除13：前五大客户/供应商表
        has_customer_supplier = any(kw in all_text for kw in [
            '前五大客户', '前五大供应商', '客户名称', '供应商名称',
            '主要客户', '主要供应商', '采购金额', '销售金额'
        ])
        if has_customer_supplier:
            return None

        # 排除14：子公司信息表（包含子公司名称、注册资本、持股比例、取得方式等）
        has_subsidiary = all(kw in all_text for kw in ['子公司', '注册资本']) or \
                         all(kw in all_text for kw in ['子公司', '持股比例']) or \
                         ('子公司名称' in all_text and '注册资本' in all_text)
        if has_subsidiary:
            return None

        # 排除15：资产账面价值表（包含账面价值且无业务板块关键词）
        has_book_value = '账面价值' in all_text and '业务板块' not in all_text
        if has_book_value:
            return None

        # 排除16：银行承兑汇票/担保表
        has_bank_guarantee = any(kw in all_text for kw in [
            '银行承兑汇票', '担保方式', '担保金额', '反担保',
            '保证方式', '抵押物', '质押物'
        ])
        if has_bank_guarantee:
            return None

        # 排除17：物业/资产明细表（包含面积、价格、开工时间等非财务指标）
        has_property_detail = any(kw in all_text for kw in [
            '可出租面积', '出租价格', '出租率', '出租方式',
            '开工时间', '总投资额', '已投资额', '预计可租面积',
            '预计租金', '取得方式', '受让面积', '使用年限',
            '项目名称', '房屋名称', '序号',
        ]) and not re.search(r'业务板块|业务名称|金额.*占比', all_text)
        if has_property_detail:
            return None

        # 排除18：其他收益/营业外收入明细表（政府补助明细等）
        has_other_income = any(kw in all_text for kw in [
            '其他业务', '其他收益', '营业外收入', '政府补助',
            '产业基金', '农业博览会', '项目补助', '科创中心',
        ]) and not re.search(r'业务板块|业务名称|营业收入|营业成本|毛利润|毛利率', all_text)
        # 进一步验证：如果表格行数很少（<=8行）且第一项就是补助类项目，排除
        if has_other_income and len(data_rows) <= 8:
            first_row_first_cell = data_rows[0][0] if data_rows else ''
            if any(kw in first_row_first_cell for kw in ['补助', '补贴', '奖励', '扶持', '专项']):
                return None

        # 排除19：期间费用表（包含销售费用、管理费用、研发费用、财务费用等明细）
        has_period_expense_items = any(kw in all_text for kw in [
            '销售费用', '管理费用', '研发费用', '财务费用', '期间费用'
        ]) and not re.search(r'业务板块|业务名称|营业收入|营业成本|毛利润|毛利率', all_text)
        if has_period_expense_items:
            return None

        # 排除20：供应商采购表（包含供应商、采购产品、采购金额等）
        has_supplier = any(kw in all_text for kw in [
            '供应商一', '供应商二', '供应商三', '供应商四', '供应商五',
            '主要采购产品', '采购金额', '占.*采购总额比例'
        ])
        if has_supplier:
            return None

        # 排除21：许可证/采砂表（包含许可证编号、开采河流、采砂区等）
        has_permit = any(kw in all_text for kw in [
            '许可证编号', '开采河流', '采砂区名称', '年度采砂', '有效期限',
            '采砂控制', '可采区'
        ])
        if has_permit:
            return None

        # 排除22：单位成本分析表（元/吨、百分比构成等明细拆解）
        has_unit_cost = ('元/吨' in all_text or '其中：' in all_text) and \
                        not re.search(r'业务板块|业务名称|营业收入|营业成本|毛利润|毛利率|项目.*202', all_text)
        if has_unit_cost:
            return None

        # 排除23：景区/景点信息表（包含景区名称、景区等级、主要景点、收费标准等）
        has_scenic = any(kw in all_text for kw in [
            '景区名称', '景区等级', '主要景点', '收费标准', '门票收费',
            'AAA', '人次'
        ]) and not re.search(r'业务板块|业务名称|营业收入|营业成本|毛利润|毛利率', all_text)
        if has_scenic:
            return None

        # ===== 第二步：提取表格数据特征 =====

        # 统计数字类型 - 改进：同时检测千分位格式和普通小数格式
        has_comma_numbers = False
        has_small_decimals = False
        has_percentages = False
        has_numeric_values = False  # 新增：任何数字值（含无千分位）
        comma_count = 0
        decimal_count = 0
        percent_count = 0
        numeric_count = 0

        for row in data_rows[:10]:
            for cell in row:
                if cell:
                    cell_str = str(cell)
                    if ',' in cell_str and re.search(r'\d{1,3},\d{3}', cell_str):
                        has_comma_numbers = True
                        comma_count += 1
                    if '%' in cell_str:
                        has_percentages = True
                        percent_count += 1
                    try:
                        val = float(cell_str.replace(',', '').replace('%', '').replace('-', '0').strip())
                        if abs(val) > 0.01:  # 非零有效值
                            has_numeric_values = True
                            numeric_count += 1
                        if 0 < val < 100 and '.' in cell_str:
                            has_small_decimals = True
                            decimal_count += 1
                    except:
                        pass

        # 检查业务分类列
        # 注意：'项目' 过于宽泛，资产负债表等也用"项目"，所以只在有明确业务分类关键词时才匹配
        has_business_column = any(kw in all_text for kw in [
            '业务板块', '业务板块名称', '业务名称', '业务类型', '业务种类'
        ])

        # 检查关键词
        has_revenue = '营业收入' in all_text
        has_cost = '营业成本' in all_text
        has_margin = '毛利率' in all_text
        has_profit = '毛利润' in all_text

        # 同时检查页面上下文（关键词可能在表格上方但不在表格内）
        page_lower = page_text.lower() if page_text else ''
        has_margin_in_page = '毛利率' in page_lower or '毛利润' in page_lower
        has_cost_in_page = '营业成本' in page_lower
        has_revenue_in_page = '营业收入' in page_lower

        # 表头关键词
        # 注意：只匹配"营业收入"完整词，不匹配单独的"收入"（可能是"收入确认方式"等）
        has_revenue_header = ('营业收入' in header_text) and '成本' not in header_text and '毛利率' not in header_text
        has_cost_header = '营业成本' in header_text and '收入' not in header_text and '毛利率' not in header_text
        has_margin_header = '毛利率' in header_text

        num_cols = len(table[0]) if table else 0

        # ===== 第三步：分类判断 =====

        # force_cost: 当毛利润金额表和毛利率百分比表共存时，毛利润表强制归为 cost
        if force_cost:
            if (comma_count + numeric_count) >= 3:
                if not result.get('cost'):
                    return "cost"
            return None

        # 优先检测：毛利润金额表（大数值特征）- 应归为 cost 而非 margin
        # 注意：只在页面没有"营业收入"相关上下文中才检查，避免将收入表误判
        has_revenue_context = has_revenue_in_page or '营业收入' in page_text.lower()
        if ('毛利润' in all_text) and not has_revenue and not has_cost and not has_revenue_context:
            if self._is_gross_profit_amount_table(table):
                return "cost" if not result.get('cost') else None

        # 毛利率表：必须包含"毛利率"关键词（表格内或表头）
        if has_margin_header or has_margin:
            return "margin"

        # 辅助判断：页面包含"毛利率"且表格特征符合（少列、小数值、无千分位）
        if has_margin_in_page and num_cols <= 5 and not has_comma_numbers and has_small_decimals:
            if data_rows:
                first_cell = data_rows[0][0] if data_rows[0] else ''
                if not re.match(r'^20\d{2}', first_cell.strip()):
                    return "margin"

        # 营业收入表：表头含"营业收入"，有金额数据，有业务分类
        if has_revenue_header and (has_comma_numbers or has_numeric_values) and (comma_count + numeric_count) >= 3:
            return "revenue"

        # 新增：通用"金额/占比"或"收入/占比"表头 + 业务板块数据 → 当页面没有明确"营业收入"但有此类列结构时，
        # 如果表格包含多个业务板块行且有报告期年份，归类为 revenue
        has_amount_pct_structure = ('金额' in header_text and '占比' in header_text) or \
                                   ('收入' in header_text and '占比' in header_text and '营业成本' not in header_text and '毛利率' not in header_text)
        has_business_segments = False
        if data_rows:
            segment_count = 0
            for row in data_rows[:10]:
                if row and row[0] and row[0].strip() and row[0].strip() not in ('合计', '小计', '总计'):
                    # 检查是否为业务板块名称（非年份、非纯数字）
                    cell = row[0].strip()
                    if not re.match(r'^20\d{2}', cell) and not re.match(r'^\d+$', cell):
                        segment_count += 1
            has_business_segments = segment_count >= 2

        if has_amount_pct_structure and has_business_segments and (comma_count + numeric_count) >= 3:
            # 检查是否有报告期年份（表头或数据行）
            has_reporting_year_in_data = bool(re.search(r'202[2345]', header_text))
            if not has_reporting_year_in_data:
                for row in data_rows[:3]:
                    for cell in row:
                        if cell and re.search(r'202[2345]', cell):
                            has_reporting_year_in_data = True
                            break
            # 通用金额表 + 业务板块 + 报告期年份 → 营业收入表
            # 注意：has_cost/has_profit/has_margin 仅检查表格自身内容，
            # 不检查页面上下文（同一页面可能有多个不同类型的表格）
            table_has_cost_kw = '营业成本' in all_text or '成本' in header_text
            table_has_profit_kw = '毛利润' in all_text
            table_has_margin_kw = '毛利率' in all_text or '毛利率' in header_text
            if has_reporting_year_in_data and not table_has_cost_kw and not table_has_profit_kw and not table_has_margin_kw:
                return "revenue"

        # 营业成本表：表头含"营业成本"，有金额数据
        if has_cost_header and (has_comma_numbers or has_numeric_values) and (comma_count + numeric_count) >= 3:
            return "cost"

        # 辅助判断：页面包含"营业成本"且表格有金额数据（成本表格标题在页面文本中）
        # 但表格自身表头有"收入/占比"且无"成本"时，不应被归类为 cost
        if has_cost_in_page and (comma_count + numeric_count) >= 3:
            if not result.get('cost') and not has_revenue and not has_revenue_in_page:
                # 如果表头有"收入"且无"成本"，这应该是收入表而非成本表
                has_revenue_like_header = ('收入' in header_text and '成本' not in header_text and '毛利率' not in header_text)
                if not has_revenue_like_header:
                    return "cost"

        # 综合表：同时包含营业收入和营业成本
        is_combined = has_revenue and has_cost and (comma_count + numeric_count) >= 6
        if is_combined:
            if not result.get('revenue'):
                return "revenue"
            elif not result.get('cost'):
                return "cost"

        # 毛利润金额表 - 大数值（万元量级）的毛利润表应归为 cost 而非 margin
        if has_profit and (comma_count + numeric_count) >= 3:
            is_amount_table = self._is_gross_profit_amount_table(table)
            if is_amount_table:
                if num_cols > 4:
                    return "revenue"
                else:
                    return "cost"
            else:
                return "margin"

        # 基于页面上下文的毛利率检测：页面包含"毛利率构成"/"毛利率情况"
        # 且表格为少列、小数值（百分比特征）
        if has_margin_in_page and '毛利率' in page_text.lower():
            is_pct_table = num_cols <= 5 and not has_comma_numbers
            if is_pct_table:
                all_small = True
                for row in data_rows[:10]:
                    for cell in row[1:]:
                        if not cell or cell.strip() in ('-', '', '%'):
                            continue
                        try:
                            val = float(cell.replace(',', '').replace('%', '').strip())
                            if abs(val) > 200:
                                all_small = False
                                break
                        except:
                            pass
                if all_small and numeric_count >= 2:
                    return "margin"

        # 基于数据特征的毛利率判断 - 必须包含"毛利率"或"毛利润"关键词
        if has_margin or has_profit:
            if num_cols <= 4 and has_small_decimals and not has_comma_numbers:
                return "margin"
            if num_cols <= 5 and percent_count >= 3 and not has_comma_numbers:
                return "margin"
            if '毛利率' in header_text or '毛利润' in header_text:
                return "margin"

        # 兜底：有业务分类和金额数据的表格
        if (comma_count + numeric_count) >= 3 and has_business_column:
            # 如果页面上下文包含"毛利润"，检查是否为毛利润金额表（应归为 cost 而非 margin）
            if '毛利润' in page_text.lower() and not has_revenue and not has_cost and not has_revenue_in_page:
                if self._is_gross_profit_amount_table(table):
                    return "cost" if not result.get('cost') else None

            # 当页面同时包含营业收入和营业成本上下文时，用表格内关键词区分
            if has_revenue_in_page and has_cost_in_page:
                if has_revenue or has_revenue_header:
                    if not result.get('revenue'):
                        return "revenue"
                elif has_cost or has_cost_header:
                    if not result.get('cost'):
                        return "cost"
                if section_info.get('section_order'):
                    for section in section_info['section_order']:
                        if section == 'revenue' and not result.get('revenue'):
                            return "revenue"
                        elif section == 'cost' and not result.get('cost'):
                            return "cost"
                        elif section == 'margin':
                            if not result.get('margin'):
                                is_margin_like = num_cols <= 5 and not has_comma_numbers
                                if is_margin_like:
                                    return "margin"

            # 页面只有成本或只有收入上下文时
            if has_cost and not has_revenue:
                if not result.get('cost'):
                    return "cost"
            if has_revenue and not has_cost:
                if not result.get('revenue'):
                    return "revenue"
            # 兜底返回 revenue 前，检查页面是否有任何收入/成本/毛利率上下文
            if (has_revenue_in_page or has_cost_in_page or has_margin_in_page or
                has_revenue_header or has_cost_header):
                if not result.get('revenue'):
                    return "revenue"

        # 兜底2：页面上下文明确表明是收入/成本/毛利率表格
        if has_revenue_in_page and has_numeric_values and numeric_count >= 2 and not has_cost and not has_margin:
            if not result.get('revenue'):
                return "revenue"
        if has_cost_in_page and has_numeric_values and numeric_count >= 2 and not has_revenue:
            if not result.get('cost'):
                return "cost"
        if has_margin_in_page and has_numeric_values and numeric_count >= 2 and not has_revenue and not has_cost:
            # 确保不是毛利润金额表
            if not self._is_gross_profit_amount_table(table):
                if not result.get('margin'):
                    return "margin"

        return None

    def _format_table_to_markdown_v3(self, table: List[List[str]]) -> str:
        """
        将表格转换为 Markdown 格式 v4.0
        改进：正确处理跨行表头、修复单元格内异常空格
        """
        if not table or len(table) < 2:
            return ""

        lines = []

        # 确定表头行数（检查前几行是否有空单元格或包含年份）
        header_rows = 1
        for i in range(1, min(3, len(table))):
            row_text = ' '.join(table[i])
            # 如果包含年份标记，可能是表头的一部分
            if any(year in row_text for year in ['202', '金额', '占比', '收入', '成本']):
                header_rows = i + 1

        # 合并表头
        if header_rows > 1:
            merged_header = []
            num_cols = len(table[0])
            for col_idx in range(num_cols):
                header_parts = []
                for row_idx in range(header_rows):
                    if col_idx < len(table[row_idx]):
                        cell = table[row_idx][col_idx].strip()
                        if cell:
                            header_parts.append(cell)
                merged_header.append(' '.join(header_parts) if header_parts else "")
            lines.append("| " + " | ".join(merged_header) + " |")
            lines.append("| " + " | ".join(["---"] * num_cols) + " |")
            data_start = header_rows
        else:
            # 单行表头
            header = table[0]
            lines.append("| " + " | ".join(header) + " |")
            lines.append("| " + " | ".join(["---"] * len(header)) + " |")
            data_start = 1

        # 数据行
        num_cols = len(table[0]) if table else 0
        for row in table[data_start:]:
            # 跳过空行
            if not any(cell.strip() for cell in row):
                continue
            # 修复单元格内异常空格（中文之间的多余空格）
            cleaned_row = []
            for cell in row:
                cell = cell.strip()
                # 移除中文字符之间的多余空格
                cell = re.sub(r'([一-鿿])\s+([一-鿿])', r'\1\2', cell)
                cleaned_row.append(cell)
            # 确保列数一致
            while len(cleaned_row) < num_cols:
                cleaned_row.append("")
            lines.append("| " + " | ".join(cleaned_row) + " |")

        return "\n".join(lines)

    def generate_note(self, output_base: str) -> str:
        """生成主营业务分析笔记"""
        info = {
            "issuer": self._issuer_name,
            "bond_type": self._bond_info.bond_type.value if self._bond_info else "公司债"
        }

        # 提取营业收入、成本、毛利率表格
        tables = self.extract_revenue_table()

        frontmatter = self.get_frontmatter(
            note_type=self.NOTE_TYPE,
            tags=self.TAGS + [f"#{info['bond_type']}"]
        )

        # 格式化表格内容
        revenue_section = self._format_table_section(tables.get("revenue"), "营业收入")
        cost_section = self._format_table_section(tables.get("cost"), "营业成本")
        margin_section = self._format_table_section(tables.get("margin"), "毛利率")

        template = f"""{frontmatter}
# {info['issuer']} - 主营业务

## （二）发行人报告期内营业收入、毛利润及毛利率情况

### 1、营业收入

{revenue_section}

### 2、营业成本

{cost_section}

### 3、毛利率

{margin_section}

---
**来源**: {self.pdf_name}
**提取日期**: {datetime.now().strftime('%Y-%m-%d')}
"""

        output_path = os.path.join(
            output_base, self.OUTPUT_DIR,
            f"{info['issuer']}-主营业务.md"
        )
        self.write_note(output_path, template)
        return output_path

    def _format_table_section(self, table_md: str, table_name: str) -> str:
        """格式化表格部分"""
        if not table_md:
            return "详见募集说明书原文"
        return table_md


def main():
    """主函数"""
    raw_dir = "raw"
    knowledge_dir = "knowledge"

    pdf_files = [f for f in os.listdir(raw_dir) if f.endswith(".pdf")]
    print(f"发现 {len(pdf_files)} 份 PDF 文件\n")

    for pdf_file in pdf_files:
        pdf_path = os.path.join(raw_dir, pdf_file)
        print(f"处理：{pdf_file}")

        try:
            with BusinessAnalysisExtractorV3(pdf_path) as extractor:
                extractor.parse_issuer_name()
                extractor.parse_bond_info()
                output_file = extractor.generate_note(knowledge_dir)
                print(f"  生成：{output_file}")
        except Exception as e:
            print(f"  处理失败：{e}")
            import traceback
            traceback.print_exc()

        print("-" * 50)

    print("\n处理完成！")


if __name__ == "__main__":
    main()
