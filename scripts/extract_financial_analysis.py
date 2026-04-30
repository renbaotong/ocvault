#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
财务分析提取器
从 PDF 中提取资产结构分析表格数据
"""

import os
import re
import html
from datetime import datetime
from typing import Dict, List, Optional, Tuple

from extractors import BaseExtractor, clean_text


class FinancialAnalysisExtractor(BaseExtractor):
    """财务分析提取器"""

    NOTE_TYPE = "financial_analysis"
    OUTPUT_DIR = "05-资产结构分析"
    TAGS = ["财务/分析"]

    # 资产结构分析表格标题关键词
    ASSET_TABLE_PATTERNS = [
        # 标准"表：XXX"格式
        r"表[：:]?发行人最近两年及一期末资产构成情况",
        r"表[：:]?报告期各期末发行人资产结构情况",
        r"表[：:]?发行人资产结构分析",
        r"表[：:]?发行人最近两年及一期末资产构成明细情况",
        r"表[：:]?发行人最近两年及一期末资产整体构成情况",
        r"表[：:]?近两年及一期末发行人资产构成情况",
        r"表[：:]?近两年及一期末发行人资产构成明细情况",
        r"表[：:]?近两年及一期末资产结构分析",
        r"表[：:]?发行人主要资产结构分析表",
        r"表[：:]?资产构成情况表",
        r"表[：:]?发行人近两年及一期末资产结构表",
        r"表[：:]?发行人最近两年及一期末资产构成表",
        r"表[：:]?报告期各期末资产结构情况",
        r"表[：:]?近两年及一期末资产结构详细表",
        r"表[：:]?近两年及一期末发行人资产结构情况",
        # 章节+表格标题格式
        r"一[、.\s]*资产结构分析",
        r"[（(]一[）)]\s*资产结构分析",
        # "XXX如下"格式
        r"资产结构分析如下",
        r"资产构成情况如下",
        r"发行人.*资产结构表",
        r"最近两年及一期末[，,]?发行人资产结构情况如下",
        r"报告期各期末[，,]?发行人资产情况如下",
        r"近两年及一期末[，,]?发行人资产情况如下",
        r"公司近两年及一期末资产的总体构成情况如下表",
        r"发行人.*资产.*构成情况",
        r"报告期各期期末[，,]?发行人资产结构情况如下",
        # 直接标题格式
        r"近两年及一期末资产结构分析",
        r"最近两年及一期末资产结构情况",
        r"发行人最近两年及一期末资产构成情况",
        r"近两年及一期末发行人资产结构情况",
        r"近两年及一期末资产结构情况",
        r"近两年及一期末公司主要资产结构表",
        r"发行人近两年及一期末资产结构详细",
        # 其他格式
        r"主要资产结构分析",
        r"资产结构详细表",
        r"资产负债结构分析",
        r"资产构成分析",
    ]

    # 流动资产项目
    FLOW_ITEMS = [
        "货币资金", "应收账款", "预付款项", "其他应收款", "应收票据",
        "存货", "合同资产", "一年内到期的非流动资产", "其他流动资产",
        "交易性金融资产", "应收款项融资"
    ]
    # 非流动资产项目
    NON_FLOW_ITEMS = [
        "其他权益工具投资", "长期股权投资", "投资性房地产",
        "固定资产", "在建工程", "工程物资", "使用权资产",
        "无形资产", "开发支出", "商誉", "长期待摊费用",
        "递延所得税资产", "其他非流动资产"
    ]
    # 所有资产项目
    ALL_ASSET_ITEMS = FLOW_ITEMS + NON_FLOW_ITEMS + [
        "流动资产合计", "非流动资产合计", "资产总计", "资产合计"
    ]

    def __init__(self, pdf_path: str):
        super().__init__(pdf_path)

    def _get_section_5_text(self) -> str:
        self.extract_text()
        section_5_patterns = [
            r"第五节\s+发行人主要财务情况",
            r"第五节发行人主要财务情况",
            r"五[、.\s]*发行人主要财务情况",
            r"第五节\s+财务会计信息",
            r"第五节财务会计信息",
            r"五[、.\s]*财务会计信息",
            r"第五节\s+发行人主要财务状况",
            r"第五节发行人主要财务状况",
            r"五[、.\s]*发行人主要财务状况",
        ]
        section_5_start = -1
        for pattern in section_5_patterns:
            match = re.search(pattern, self.full_text)
            if match:
                section_5_start = match.start()
                break
        if section_5_start < 0:
            return ""
        section_end_patterns = [
            r"第六节\s+发行人", r"第六节发行人",
            r"六[、.\s]*发行人信用状况", r"第六节\s+发行人信用状况",
            r"第六节\s+募集资金运用", r"第六节\s+增信情况",
        ]
        section_5_end = len(self.full_text)
        for pattern in section_end_patterns:
            match = re.search(pattern, self.full_text[section_5_start:])
            if match:
                end_pos = section_5_start + match.start()
                if end_pos > section_5_start + 5000:
                    section_5_end = end_pos
                    break
        return self.full_text[section_5_start:section_5_end]

    def _find_asset_table_start(self, text: str) -> int:
        for pattern in self.ASSET_TABLE_PATTERNS:
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                return match.start()
        return -1

    def _extract_table_from_pages(self) -> Dict:
        """
        从PDF页面中直接提取资产结构表格
        """
        result = {
            "years": [],
            "flow_assets": [],
            "non_flow_assets": [],
            "total": {}
        }

        # 第一步：尝试查找资产结构分析内容页面
        asset_structure_pages = []
        page_texts = []

        for page_num, page in enumerate(self.doc):
            html_text = page.get_text('html')
            text = html.unescape(html_text)
            text = html.unescape(text)
            page_texts.append(text)

            has_asset_table = False
            for pattern in self.ASSET_TABLE_PATTERNS:
                if re.search(pattern, text, re.IGNORECASE):
                    has_asset_table = True
                    break

            if not has_asset_table:
                # HTML模式可能丢失中文，回退使用纯文本检测
                plain_text = page.get_text()
                detect_text = text if any(kw in text for kw in ["货币", "资产"]) else plain_text

                flow_keywords = ["货币资金", "应收账款", "预付款项", "其他应收款", "存货"]
                non_flow_keywords = ["固定资产", "在建工程", "无形资产", "长期股权投资"]
                has_flow = any(kw in detect_text for kw in flow_keywords)
                has_non_flow = any(kw in detect_text for kw in non_flow_keywords)
                if has_flow and has_non_flow:
                    has_asset_table = True

            if has_asset_table:
                asset_structure_pages.append(page_num)

        if asset_structure_pages:
            print(f"  找到资产结构分析相关内容第 {[p+1 for p in asset_structure_pages]} 页")

            # 策略1：优先扫描所有页面查找"项目"+年份的表格头结构（最可靠）
            # 关键：只找包含"金额"+"占比"列头的页面，排除资产负债表（只有金额列）
            target_pages = []
            best_header_page = -1
            best_header_score = 0
            for page_num in range(min(30, len(self.doc)), len(self.doc)):
                page = self.doc[page_num]
                plain_text = page.get_text()
                # 查找"项目"后紧跟年份日期的模式
                lines = [l.strip() for l in plain_text.split('\n') if l.strip()]
                for i, line in enumerate(lines):
                    if line in ["项目", "项目名称"] and i + 1 < len(lines):
                        next_lines = ' '.join(lines[i+1:i+8])
                        # 必须有至少3个年份日期（资产结构表是3期对比）
                        # 或者至少2个（部分PDF只有2期）
                        year_matches = re.findall(r'202\d', next_lines)
                        if len(set(year_matches)) < 2:
                            break
                        if not re.search(r'202\d.*[年月]', next_lines):
                            break

                        # 检查表格开头的项目是否为资产结构项目（而非明细子项或合计行）
                        table_items = []
                        for j in range(i+1, min(i+60, len(lines))):
                            l = lines[j]
                            # 遇到叙述性文本则停止（超过30字符的中文行）
                            if len(l) > 30 and re.search(r'[一-鿿]', l) and l not in self.ALL_ASSET_ITEMS:
                                break
                            for item in self.ALL_ASSET_ITEMS:
                                if l == item or l.startswith(item + " "):
                                    table_items.append(item)
                                    break

                        # 只接受包含至少2个非合计资产项目的表格
                        unique_items = set(table_items) - {"流动资产合计", "非流动资产合计", "资产总计", "资产合计"}
                        if len(unique_items) < 2:
                            break

                        has_numbers = bool(re.search(r'\d+,\d+\.\d+', plain_text))
                        if not has_numbers:
                            break

                        # 关键检查：必须有"金额"+"占比"列头（资产结构表特有，资产负债表没有）
                        # 在"项目"行之后搜索列头
                        has_amount_ratio_header = False
                        for j in range(i+1, min(i+12, len(lines))):
                            l = lines[j]
                            if l in ["金额", "占比"]:
                                has_amount_ratio_header = True
                                break
                        # 也检查"项目"和年份之间是否有占比
                        if not has_amount_ratio_header:
                            header_section = ' '.join(lines[i:i+10])
                            if '占比' in header_section:
                                has_amount_ratio_header = True

                        if not has_amount_ratio_header:
                            break  # 这是资产负债表，跳过

                        # 评分
                        score = len(unique_items) * 3
                        if has_amount_ratio_header:
                            score += 30  # 资产结构表的关键特征
                        if "资产总计" in plain_text:
                            score += 10
                        if "流动资产合计" in plain_text and "非流动资产合计" in plain_text:
                            score += 5
                        # 分数相同时优先选前面的页面
                        if score > best_header_score or (score == best_header_score and best_header_page < 0):
                            best_header_score = score
                            best_header_page = page_num
                        break

            if best_header_page > 0:
                target_pages.append(best_header_page)
                print(f"  通过表格头找到最佳资产表格，页面 {best_header_page+1} (得分={best_header_score})")

            # 策略2：如果表格头扫描未找到，尝试标题+内容匹配
            if not target_pages:
                for page_num in asset_structure_pages:
                    if page_num < 20:
                        continue
                    page = self.doc[page_num]
                    html_text = page.get_text('html')
                    text = html.unescape(html_text)
                    text = html.unescape(text)

                    has_table_title = any(kw in text for kw in [
                        '（一）资产结构分析', '一、资产结构分析',
                        '表：近两年及一期末发行人资产构成明细情况',
                        '表：发行人最近两年及一期末资产构成情况',
                        '资产构成情况表', '发行人近两年及一期末资产结构表',
                        '公司近两年及一期末资产的总体构成情况如下表',
                    ])
                    has_table_content = any(kw in text for kw in self.ALL_ASSET_ITEMS[:5]) and \
                                        bool(re.search(r'\d+,\d+\.\d+', text))

                    if has_table_title and has_table_content:
                        target_pages.append(page_num)
                    elif has_table_title:
                        for offset in range(1, 3):
                            if page_num + offset >= len(self.doc):
                                break
                            next_page = self.doc[page_num + offset]
                            next_html = next_page.get_text('html')
                            next_text = html.unescape(next_html)
                            next_text = html.unescape(next_text)
                            next_has_content = any(kw in next_text for kw in self.ALL_ASSET_ITEMS[:5]) and \
                                              bool(re.search(r'\d+,\d+\.\d+', next_text))
                            if next_has_content:
                                target_pages.append(page_num)
                                break

            # 策略3：回退使用asset_structure_pages
            if not target_pages:
                target_pages = [p for p in asset_structure_pages if p >= 10]
            if not target_pages:
                target_pages = asset_structure_pages

            # 选择连续的页面（优先选择包含最多资产项目的连续页面组）
            selected_pages = self._select_contiguous_pages(target_pages)

            combined_lines = []
            for page_num in selected_pages:
                page = self.doc[page_num]
                # 优先使用纯文本（HTML模式在某些PDF中会丢失或碎片化中文）
                plain_text = page.get_text()
                html_text = page.get_text('html')
                text = html.unescape(html_text)
                text = html.unescape(text)
                # 如果纯文本包含更多中文关键词，使用纯文本
                plain_kw_count = sum(1 for kw in self.ALL_ASSET_ITEMS if kw in plain_text)
                html_kw_count = sum(1 for kw in self.ALL_ASSET_ITEMS if kw in text)
                if plain_kw_count >= html_kw_count:
                    text = plain_text
                clean = re.sub(r'<[^>]+>', '\n', text)
                lines = [l.strip() for l in clean.split('\n') if l.strip()]
                combined_lines.extend(lines)

            # 找到表格开始位置
            table_started = False
            table_start_idx = 0

            for i, line in enumerate(combined_lines):
                for pattern in self.ASSET_TABLE_PATTERNS:
                    if re.search(pattern, line, re.IGNORECASE):
                        table_started = True
                        table_start_idx = i
                        print(f"  表格标题匹配: {line[:50]}")
                        break
                if table_started:
                    break

            if not table_started:
                for i, line in enumerate(combined_lines):
                    if line.strip() in ["项目", "项目名称"]:
                        if i + 1 < len(combined_lines):
                            next_line = combined_lines[i + 1]
                            if re.search(r'\d{4}.*年', next_line):
                                table_started = True
                                table_start_idx = i
                                print(f"  通过表头找到表格: {line}")
                                break

            if not table_started:
                for i, line in enumerate(combined_lines):
                    if line.strip() in ["流动资产：", "流动资产"] and i > 0:
                        table_started = True
                        table_start_idx = max(0, i - 20)
                        print(f"  通过'流动资产'找到表格区域")
                        break

            if table_started:
                table_lines = combined_lines[table_start_idx:]
                result = self._parse_table_lines(table_lines, result)
                if result.get("total") or result.get("flow_assets"):
                    return result

        # 回退：从资产负债表提取
        print(f"  未找到详细资产结构，尝试从资产负债表提取...")
        result = self._extract_from_balance_sheet(result)
        if result.get("total") or result.get("years"):
            return result

        print(f"  资产负债表提取失败，使用简化的总计提取")
        return self._extract_simple_totals(result)

    def _select_contiguous_pages(self, target_pages: List[int]) -> List[int]:
        """选择连续的页面组，优先选择包含最多资产项目的组"""
        if not target_pages:
            return []

        # 找出所有连续页面组
        groups = []
        current_group = [target_pages[0]]
        for i in range(1, len(target_pages)):
            if target_pages[i] - target_pages[i-1] <= 2:
                current_group.append(target_pages[i])
            else:
                if len(current_group) > 1:
                    groups.append(list(current_group))
                current_group = [target_pages[i]]
        if len(current_group) > 1:
            groups.append(list(current_group))

        # 如果有连续组，选择第一个组并扩展
        if groups:
            selected = groups[0]
        else:
            # 没有连续页面，选择第一个页面
            selected = [target_pages[0]]

        # 向后扩展以包含跨页表格
        expanded = list(selected)
        last_page = selected[-1]
        for offset in range(1, 12):
            next_p = last_page + offset
            if next_p < len(self.doc) and next_p not in expanded:
                expanded.append(next_p)

        # 向前扩展1页（资产结构表可能从前一页开始）
        first_page = selected[0]
        if first_page > 0 and (first_page - 1) not in expanded:
            expanded.insert(0, first_page - 1)

        selected = sorted(set(expanded))[:10]

        print(f"  选择页面: {[p+1 for p in selected]} 进行表格提取")
        return selected

    def _parse_table_lines(self, lines: List[str], result: Dict) -> Dict:
        """解析表格行"""
        # 预处理：合并单字符行
        merged_lines = self._merge_single_char_lines(lines)

        # 提取年份
        years = self._extract_years(merged_lines)
        if years:
            result["years"] = years
            print(f"  提取到年份: {result['years']}")

        num_years = len(result.get("years", [])) or 3
        required_numbers = num_years * 2

        i = 0
        current_section = None

        while i < len(merged_lines):
            line = merged_lines[i].strip()
            if not line:
                i += 1
                continue

            if line in ["流动资产：", "流动资产", "一、流动资产"]:
                current_section = "flow"
                i += 1
                continue
            if line in ["非流动资产：", "非流动资产", "二、非流动资产"]:
                current_section = "non_flow"
                i += 1
                continue

            if re.match(r"单位[：:]", line) or ("万元" in line and "%" in line):
                i += 1
                continue
            if line in ["项目", "项目名称"]:
                i += 1
                continue
            if re.match(r"^\d{4}\s*年", line) or re.match(r"^\d{4}\s*年度", line):
                i += 1
                continue
            if line in ["金额", "占比", "金额（万元）", "占比（%）", "金额(万元)", "占比(%)"]:
                i += 1
                continue

            if re.search(r"表[：:]?近两年及一期末流动资产结构分析", line):
                break
            if re.search(r"表[：:]?近两年及一期末货币资金明细", line):
                break
            if re.search(r"表[：:]?发行人.*负债.*构成", line):
                break
            if "负债结构分析" in line and "表" in line:
                break
            if result.get("total") and re.search(r'总体来看|综上所述|总体而言', line):
                break

            item_name = self._match_asset_item(line, merged_lines, i)
            if item_name:
                all_numbers = self._extract_numbers_for_item(merged_lines, i, item_name, required_numbers)
                if len(all_numbers) >= num_years:
                    values = self._parse_values(all_numbers, num_years)
                    if len(values) >= num_years:
                        self._add_asset_item(result, item_name, values, current_section)
                    i = i + 1 + min(len(all_numbers), 15)
                else:
                    i += 1
            else:
                i += 1

        return result

    def _merge_single_char_lines(self, lines: List[str]) -> List[str]:
        """合并单字符行为完整文本，但不合并数字行"""
        merged = []
        i = 0
        known_words = set(self.ALL_ASSET_ITEMS) | {
            "流动资产", "非流动资产", "流动资产合计", "非流动资产合计",
            "资产总计", "项目", "金额", "占比", "万元", "年末", "月末",
            "占比（%）", "金额（万元）", "占比(%)", "金额(万元)",
            "资产结构分析", "资产构成分析",
        }

        while i < len(lines):
            line = lines[i].strip()
            if not line:
                merged.append("")
                i += 1
                continue

            # 数字行（包括带%的百分比）保持独立
            if re.match(r'^-?[\d,]+\.?\d*%?$', line):
                merged.append(line)
                i += 1
                continue

            # 已知词保持独立
            if line in known_words:
                merged.append(line)
                i += 1
                continue

            # 合并连续的非数字短字符串
            combined = line
            j = i + 1
            while j < len(lines):
                next_line = lines[j].strip()
                if not next_line:
                    break
                if re.match(r'^-?[\d,]+\.?\d*%?$', next_line):
                    break
                if next_line in known_words:
                    break
                if len(next_line) > 10:
                    break
                combined += next_line
                j += 1

            merged.append(combined)
            i = j

        return merged

    def _match_asset_item(self, line: str, lines: List[str], index: int) -> Optional[str]:
        for item in self.ALL_ASSET_ITEMS:
            if line == item or line.startswith(item + " ") or line.endswith(item):
                return item
            if item in line and len(line) < len(item) + 15:
                return item
        return None

    def _extract_numbers_for_item(self, lines: List[str], idx: int, item_name: str, required_numbers: int) -> List[str]:
        all_numbers = []
        current_line = lines[idx].strip()
        if item_name in current_line:
            item_pos = current_line.find(item_name)
            if item_pos >= 0:
                after_item = current_line[item_pos + len(item_name):]
                nums = re.findall(r'[\d,]+\.?\d*', after_item)
                for num in nums:
                    all_numbers.append(num.replace(',', ''))

        if len(all_numbers) >= required_numbers:
            return all_numbers[:required_numbers]

        consecutive_numbers = []
        max_look_ahead = min(25, len(lines) - idx - 1)

        for k in range(max_look_ahead):
            num_line = lines[idx + 1 + k].strip()
            if num_line in ["金额", "占比", "金额（万元）", "占比（%）", "金额(万元)", "占比(%)"]:
                continue

            is_new_item = False
            if num_line:
                for item in self.ALL_ASSET_ITEMS:
                    if num_line == item or (num_line.startswith(item) and len(num_line) < len(item) + 5):
                        is_new_item = True
                        break
                if num_line in ["流动资产：", "非流动资产：", "流动资产", "非流动资产"]:
                    is_new_item = True
                if len(num_line) > 4 and re.search(r'[一-鿿]', num_line):
                    for item in self.ALL_ASSET_ITEMS:
                        if item in num_line:
                            is_new_item = True
                            break

            if is_new_item:
                break

            nums = re.findall(r'[\d,]+\.?\d*', num_line)
            if nums:
                for num in nums:
                    clean_num = num.replace(',', '')
                    if clean_num:
                        consecutive_numbers.append(clean_num)

        if len(consecutive_numbers) >= required_numbers:
            return consecutive_numbers[:required_numbers]

        return all_numbers + consecutive_numbers

    def _add_asset_item(self, result: Dict, item_name: str, values: List[Dict], current_section: str):
        if "合计" in item_name or "总计" in item_name:
            if "流动资产合计" in item_name and not result.get("flow_total"):
                result["flow_total"] = values
            elif "非流动资产合计" in item_name and not result.get("non_flow_total"):
                result["non_flow_total"] = values
            elif item_name in ["资产总计", "资产合计"] and not result.get("total"):
                result["total"] = values
        else:
            existing_names = [x["name"] for x in result.get("flow_assets", [])] + \
                            [x["name"] for x in result.get("non_flow_assets", [])]
            if item_name not in existing_names:
                item_data = {"name": item_name, "values": values}
                if item_name in self.FLOW_ITEMS:
                    result.setdefault("flow_assets", []).append(item_data)
                elif item_name in self.NON_FLOW_ITEMS:
                    result.setdefault("non_flow_assets", []).append(item_data)
                elif current_section == "flow":
                    result.setdefault("flow_assets", []).append(item_data)
                elif current_section == "non_flow":
                    result.setdefault("non_flow_assets", []).append(item_data)

    def _extract_years(self, lines: List[str]) -> List[str]:
        years = []
        combined_text = ' '.join(lines[:100])
        # 支持多种日期格式：2024年12月31日、2024年末、2024/12/31、2024年9月末
        for pattern in [r"(\d{4})\s*年\s*(\d{1,2})\s*月\s*(\d{1,2})\s*日",
                        r"(\d{4})\s*年\s*(\d{1,2})\s*月末",
                        r"(\d{4})\s*年末",
                        r"(\d{4})/(\d{1,2})/(\d{1,2})"]:
            matches = re.findall(pattern, combined_text)
            if matches:
                for m in matches:
                    year_str = m[0] if isinstance(m, tuple) else str(m)
                    if year_str and re.match(r'\d{4}', year_str) and year_str not in years:
                        years.append(year_str)

        if len(years) < 2:
            for i in range(min(50, len(lines) - 3)):
                line = lines[i].strip()
                if re.match(r'^\d{4}$', line):
                    for j in range(i+1, min(i+3, len(lines))):
                        if '年' in lines[j] or '末' in lines[j] or '月' in lines[j]:
                            if line not in years:
                                years.append(line)
                            break

        if years:
            seen = set()
            unique = []
            for y in years:
                if y not in seen:
                    seen.add(y)
                    unique.append(y)
            if len(unique) >= 2 and int(unique[0]) < int(unique[-1]):
                unique = list(reversed(unique))
            return unique[:3]
        return []

    def _parse_values(self, all_numbers: List[str], num_years: int) -> List[Dict[str, str]]:
        values = []
        required_numbers = num_years * 2

        # If we have exactly the right number of values, use alternating (amount, ratio) pairs
        if len(all_numbers) == required_numbers:
            for i in range(0, required_numbers, 2):
                values.append({"amount": all_numbers[i], "ratio": all_numbers[i + 1]})
            return values[:num_years]

        # If we have more than required, try to detect column vs alternating layout
        if len(all_numbers) > required_numbers:
            try:
                first_six = [float(all_numbers[i]) for i in range(min(6, len(all_numbers)))]
                if len(first_six) == 6:
                    is_column = (
                        all(x > 10 for x in first_six[:3]) and
                        all(x <= 100 for x in first_six[3:6])
                    )
                    is_alternate = (
                        all(first_six[i] > 10 for i in [0, 2, 4]) and
                        all(first_six[i] <= 100 for i in [1, 3, 5])
                    )
                    if is_column:
                        for i in range(num_years):
                            values.append({"amount": all_numbers[i], "ratio": all_numbers[i + num_years]})
                        return values[:num_years]
                    elif is_alternate:
                        for i in range(0, required_numbers, 2):
                            values.append({"amount": all_numbers[i], "ratio": all_numbers[i + 1]})
                        return values[:num_years]
            except ValueError:
                pass

        # Fallback: pair alternately from available numbers
        for i in range(0, min(required_numbers, len(all_numbers)), 2):
            if i + 1 < len(all_numbers):
                values.append({"amount": all_numbers[i], "ratio": all_numbers[i + 1]})
            else:
                values.append({"amount": all_numbers[i], "ratio": "0"})
        return values[:num_years]

    def _extract_from_balance_sheet(self, result: Dict) -> Dict:
        if not result:
            result = {"years": [], "flow_assets": [], "non_flow_assets": [], "total": {}}

        for page_num, page in enumerate(self.doc):
            html_text = page.get_text('html')
            text = html.unescape(html_text)
            text = html.unescape(text)
            if "合并资产负债表" in text or "资产负债表" in text:
                print(f"  找到资产负债表在第 {page_num + 1} 页")
                clean = re.sub(r'<[^>]+>', '\n', text)
                lines = [l.strip() for l in clean.split('\n') if l.strip()]

                years = []
                for line in lines[:50]:
                    matches = re.findall(r'(\d{4})\s*年\s*(\d{1,2})\s*月', line)
                    if matches:
                        for m in matches:
                            if m[0] not in years:
                                years.append(m[0])
                    if re.match(r'^\d{4}$', line.strip()) and line.strip() not in years:
                        years.append(line.strip())

                if years:
                    result["years"] = sorted(years, reverse=True)[:3]
                    print(f"  提取到资产负债表年份: {result['years']}")

                flow_kw = ["货币资金", "应收账款", "预付款项", "其他应收款", "存货"]
                non_flow_kw = ["固定资产", "在建工程", "无形资产", "长期股权投资"]
                current_section = None
                i = 0
                while i < len(lines):
                    line = lines[i].strip()
                    if line in ["流动资产：", "流动资产"]:
                        current_section = "flow"
                    elif line in ["非流动资产：", "非流动资产"]:
                        current_section = "non_flow"

                    if line in self.ALL_ASSET_ITEMS:
                        j = i + 1
                        numbers = []
                        while j < min(i + 6, len(lines)) and len(numbers) < 3:
                            nums = re.findall(r'[\d,]+\.?\d*', lines[j].strip())
                            if nums:
                                numbers.append({"amount": nums[0].replace(',', ''), "ratio": "0.00"})
                            j += 1
                        if numbers:
                            item_data = {"name": line, "values": numbers[:3]}
                            if line in flow_kw or current_section == "flow":
                                if line not in [x["name"] for x in result["flow_assets"]]:
                                    result["flow_assets"].append(item_data)
                            elif line in non_flow_kw or current_section == "non_flow":
                                if line not in [x["name"] for x in result["non_flow_assets"]]:
                                    result["non_flow_assets"].append(item_data)
                        i = j
                        continue

                    if line in ["资产总计", "流动资产合计", "非流动资产合计"]:
                        j = i + 1
                        numbers = []
                        while j < min(i + 6, len(lines)) and len(numbers) < 3:
                            nums = re.findall(r'[\d,]+\.?\d*', lines[j].strip())
                            if nums:
                                numbers.append({"amount": nums[0].replace(',', ''), "ratio": "100.00" if line == "资产总计" else "0.00"})
                            j += 1
                        if numbers:
                            if line == "资产总计" and not result.get("total"):
                                result["total"] = numbers[:3]
                            elif line == "流动资产合计" and not result.get("flow_total"):
                                result["flow_total"] = numbers[:3]
                            elif line == "非流动资产合计" and not result.get("non_flow_total"):
                                result["non_flow_total"] = numbers[:3]
                        i = j
                        continue
                    i += 1
                return result
        return result

    def _extract_simple_totals(self, result: Dict = None) -> Dict:
        if not result:
            result = {"years": [], "total": {}}
        for page in self.doc:
            html_text = page.get_text('html')
            text = html.unescape(html_text)
            text = html.unescape(text)
            if "资产总计" in text:
                clean = re.sub(r'<[^>]+>', '\n', text)
                lines = [l.strip() for l in clean.split('\n') if l.strip()]
                for i, line in enumerate(lines):
                    if "资产总计" in line:
                        nums = []
                        j = i + 1
                        while j < len(lines) and len(nums) < 3:
                            matches = re.findall(r'[\d,]+\.?\d+', lines[j])
                            if matches:
                                nums.extend([m.replace(',', '') for m in matches])
                            j += 1
                        if len(nums) >= 3:
                            result["total"] = [{"amount": nums[k], "ratio": "100.00"} for k in range(3)]
                            result["years"] = ["2025年6月/末", "2024年末", "2023年末"]
                            return result
        return result

    def extract_financial_data(self) -> Dict:
        return self._extract_table_from_pages()

    def generate_note(self, output_base: str) -> str:
        info = {
            "issuer": self._issuer_name,
            "bond_type": self._bond_info.bond_type.value if self._bond_info else "公司债"
        }
        financial_data = self.extract_financial_data()
        table_content = self._build_asset_table(financial_data)

        frontmatter = self.get_frontmatter(
            note_type=self.NOTE_TYPE,
            tags=self.TAGS + [f"#{info['bond_type']}"]
        )

        template = f"""{frontmatter}
# {info['issuer']} - 财务分析

## 发行人最近两年及一期末资产构成情况

{table_content}

---
**来源**: {self.pdf_name}
**提取日期**: {datetime.now().strftime('%Y-%m-%d')}
"""
        output_path = os.path.join(
            output_base, self.OUTPUT_DIR,
            f"{info['issuer']}- 资产结构分析.md"
        )
        self.write_note(output_path, template)
        return output_path

    def _build_asset_table(self, data: Dict) -> str:
        years = data.get("years", [])
        if not years:
            years = ["2025年6月", "2024年末", "2023年末"]
        elif len(years) == 2:
            years = [f"{y}年" for y in years]

        num_periods = len(years[:3])
        has_flow = len(data.get("flow_assets", [])) > 0
        has_total = len(data.get("total", [])) > 0
        if not has_flow and not has_total:
            return "详见募集说明书原文"

        header = "| 项目"
        for year in years[:3]:
            header += f" | {year}金额（万元） | {year}占比"
        header += " |"
        separator = "|" + "|".join(["---"] * (1 + num_periods * 2)) + "|"

        empty_cells = " |" + " |" * num_periods * 2
        rows = [f"| **流动资产**{empty_cells}"]
        for item in data.get("flow_assets", []):
            row = f"| {item['name']}"
            for v in item['values'][:num_periods]:
                row += f" | {v['amount']} | {v['ratio']}%"
            row += " |"
            rows.append(row)

        flow_total = data.get("flow_total", [])
        if flow_total:
            row = "| **流动资产合计**"
            for v in flow_total[:num_periods]:
                row += f" | **{v['amount']}** | **{v['ratio']}%**"
            row += " |"
            rows.append(row)

        rows.append(f"| **非流动资产**{empty_cells}")
        for item in data.get("non_flow_assets", []):
            row = f"| {item['name']}"
            for v in item['values'][:num_periods]:
                row += f" | {v['amount']} | {v['ratio']}%"
            row += " |"
            rows.append(row)

        non_flow_total = data.get("non_flow_total", [])
        if non_flow_total:
            row = "| **非流动资产合计**"
            for v in non_flow_total[:num_periods]:
                row += f" | **{v['amount']}** | **{v['ratio']}%**"
            row += " |"
            rows.append(row)

        total = data.get("total", {})
        if total:
            row = "| **资产总计**"
            for v in total[:num_periods]:
                row += f" | **{v['amount']}** | **{v['ratio']}%**"
            row += " |"
            rows.append(row)

        if len(rows) <= 2:
            return self._build_simple_table(data)
        return "\n".join([header, separator] + rows)

    def _build_simple_table(self, data: Dict) -> str:
        years = ["2025年6月/末", "2024年末", "2023年末"]
        total_assets = data.get("total_assets", [])
        if not total_assets:
            return "详见募集说明书原文"
        table = "| 项目"
        for year in years[:len(total_assets)]:
            table += f" | {year}"
        table += " |\n" + "|" + "|".join(["---"] * (1 + len(total_assets))) + "|\n"
        table += "| 资产总计"
        for v in total_assets:
            table += f" | {v}万元"
        table += " |\n"
        return table


def main():
    raw_dir = "raw"
    knowledge_dir = "knowledge"
    pdf_files = [f for f in os.listdir(raw_dir) if f.endswith(".pdf")]
    print(f"发现 {len(pdf_files)} 份 PDF 文件\n")
    for pdf_file in pdf_files:
        pdf_path = os.path.join(raw_dir, pdf_file)
        print(f"处理：{pdf_file}")
        try:
            with FinancialAnalysisExtractor(pdf_path) as extractor:
                extractor.parse_issuer_name()
                extractor.parse_bond_info()
                output_file = extractor.generate_note(knowledge_dir)
                print(f"  生成：{output_file}")
        except Exception as e:
            print(f"  错误：{e}")
        print("-" * 50)
    print("\n处理完成！")


if __name__ == "__main__":
    main()
