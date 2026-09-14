#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
发行人基本情况提取器
从 PDF 中提取发行人基本信息，生成 knowledge/03-发行人基本情况/目录下的笔记文件
"""

import os
import re
from datetime import datetime
from typing import Dict, Optional
import fitz  # PyMuPDF

from extractors import (
    BaseExtractor,
    ISSUER_PROFILE_PATTERNS,
    clean_text,
    extract_number,
    validate_extraction,
)
from extractors.equity_paddle_ocr import EquityPaddleOCR


class IssuerProfileExtractor(BaseExtractor):
    """发行人基本情况提取器"""

    NOTE_TYPE = "issuer_profile"
    OUTPUT_DIR = "03-发行人基本情况"
    TAGS = ["发行人/概况"]

    # 发行人基本情况章节内的小节配置
    SECTION_PATTERNS = {
        "issuer_overview": {  # 一、发行人基本情况
            "start": ["一、发行人基本情况", "一、发行人概况", "一、发行人基本信息"],
            "end": ["二、发行人的历史沿革情况", "二、发行人的历史沿革", "二、"]
        }
    }

    def __init__(self, pdf_path: str):
        super().__init__(pdf_path)

    @staticmethod
    def _compact_index(text: str):
        """去掉全部空白字符，并记录每个保留字符在原文中的下标，
        用于在"标题被换行/空格拆开"的情况下定位章节（task 66）。"""
        chars, idxs = [], []
        for i, ch in enumerate(text):
            if ch.isspace():
                continue
            chars.append(ch)
            idxs.append(i)
        idxs.append(len(text))
        return ''.join(chars), idxs

    def _locate_section_tolerant(self, after_pattern: str, start_patterns: list, end_patterns: list):
        """在"去空白"文本中定位章节，返回 (start_orig, end_orig)；未找到返回 (-1, -1)。

        原文中标题常被排版拆行（如"一、" + 换行 + "发行人基本情况"），
        字面量查找会失败，导致整节取空（task 66：佛山市高明发展投资建设集团）。
        """
        compact, cmap = self._compact_index(self.full_text)

        base_c = 0
        if after_pattern:
            ap = re.sub(r'\s+', '', after_pattern)
            if ap:
                j = compact.find(ap)
                if j >= 0:
                    base_c = j + len(ap)

        for pattern in start_patterns:
            cp = re.sub(r'\s+', '', pattern)
            if not cp:
                continue
            pos = compact.find(cp, base_c)
            while pos >= 0:
                after_c = compact[pos + len(cp): pos + len(cp) + 200].lstrip(' \t')
                # 跳过目录条目（点号+页码，或引用性后缀）
                if after_c.startswith('....') or after_c[:1] in ['"', '"', "'", "'", '之', ',', '，']:
                    pos = compact.find(cp, pos + 1)
                    continue
                break
            if pos < 0:
                continue

            end_c = len(compact)
            for ep in end_patterns:
                ecp = re.sub(r'\s+', '', ep)
                if not ecp:
                    continue
                j = compact.find(ecp, pos + 10)
                if j > pos:
                    end_c = min(end_c, j)
            end_orig = cmap[end_c] if end_c < len(cmap) else len(self.full_text)
            return cmap[pos], end_orig

        return -1, -1

    def _extract_section_after(self, after_pattern: str, start_patterns: list, end_patterns: list) -> str:
        """在某个模式之后提取章节内容 - 增强版，跳过 TOC 引用"""
        self.extract_text()

        # 策略1：直接在全文中搜索 start_patterns，跳过 TOC 条目
        start_idx = -1
        for pattern in start_patterns:
            idx = -1
            while True:
                idx = self.full_text.find(pattern, idx + 1)
                if idx < 0:
                    break
                # 检查是否是 TOC 条目（后面跟大量点号+页码）
                next_chars = self.full_text[idx:idx + 200]
                next_clean = next_chars.replace('\n', '')
                # TOC 特征：紧跟 pattern 后有 4+ 个点号（含"·""．""…"等目录点）
                after_text = next_clean[len(pattern):]
                has_toc_dots = bool(re.match(r'[.·．…]{4,}', after_text.lstrip(' \t')))
                has_toc_ref = after_text.lstrip(' \t')[:1] in ['"', '\"', "'", "'", '之', ',', '，']
                if has_toc_dots or has_toc_ref:
                    continue
                start_idx = idx
                break
            if start_idx >= 0:
                break

        # 策略2：如果没找到，尝试通过 after_pattern 定位后再搜索
        if start_idx < 0 and after_pattern:
            base_idx = -1
            for variant in [
                after_pattern,
                after_pattern.replace(' ', ''),
                after_pattern.replace(' ', '\n'),
            ]:
                bidx = self.full_text.find(variant)
                if bidx >= 0:
                    base_idx = bidx
                    break

            if base_idx >= 0:
                for pattern in start_patterns:
                    idx = self.full_text.find(pattern, base_idx)
                    if idx >= 0:
                        next_chars = self.full_text[idx:idx + 200]
                        next_clean = next_chars.replace('\n', '')
                        after_text = next_clean[len(pattern):]
                        has_toc_dots = bool(re.match(r'[.·．…]{4,}', after_text.lstrip(' \t')))
                        if has_toc_dots:
                            continue
                        start_idx = idx
                        break

        if start_idx < 0:
            # task 66：标题被换行/空格拆开时（如"一、" + 换行 + "发行人基本情况"），
            # 回到"去空白"文本中定位，避免整节取空
            tol_start, tol_end = self._locate_section_tolerant(after_pattern, start_patterns, end_patterns)
            if tol_start >= 0:
                return self.full_text[tol_start:tol_end]
            return ""

        end_idx = len(self.full_text)
        for pattern in end_patterns:
            idx = self.full_text.find(pattern, start_idx + 10)
            if idx > start_idx:
                end_idx = min(end_idx, idx)

        return self.full_text[start_idx:end_idx]

    def _extract_basic_info_fields(self, text: str) -> Dict[str, str]:
        """从"一、发行人基本情况"文本中提取关键字段 - 增强版"""
        result = {
            "注册名称": "",
            "注册资本": "",
            "实缴资本": "",
            "设立日期": "",
            "经营范围": ""
        }

        if not text:
            return result

        # 预处理文本，处理单字换行格式
        clean = self._preprocess_text(text)
        # 进一步处理：移除多余的HTML标签和页码标记
        clean = re.sub(r'<[^>]+>', '', clean)
        clean = re.sub(r'\.{3,}\s*\d+\s*$', '', clean, flags=re.MULTILINE)
        # 单字换行格式后处理：修复字段名和值之间的连接问题
        clean = self._postprocess_char_format(clean)

        # 额外生成一个"表格模式"的文本：将 | 分隔的表格行转换为 key: value 格式
        table_clean = self._convert_table_format(clean)

        # 合并搜索：在 clean 和 table_clean 中同时搜索
        search_texts = [clean, table_clean]

        # 1. 提取注册名称
        name_patterns = [
            r'(?:注册名称|公司名称|企业名称)\s*[:：|]\s*\n?\s*([\s\S]+?)(?=\n\s*(?:法定代表|注册资本|实缴资本|设立日期|统一社会信用代码|注册地址|所属行业|经营范围|企业类型|股票代码|网址|二、|$))',
            r'(?:注册名称|公司名称|企业名称)\s*[:：|]?\s*\n?\s*([\s\S]+?)(?=\n\s*(?:法定代表|注册资本|实缴资本|设立日期|统一社会信用代码|注册地址|所属行业|经营范围|企业类型|股票代码|网址|二、|$))',
        ]
        for pattern in name_patterns:
            for st in search_texts:
                match = re.search(pattern, st, re.DOTALL)
                if match:
                    result["注册名称"] = self._clean_field_value(match.group(1))
                    break
            if result["注册名称"]:
                break

        if not result["注册名称"] and self._issuer_name:
            result["注册名称"] = self._issuer_name

        # 2. 提取注册资本
        capital_patterns = [
            r'注册资本\s*[:：|]\s*\n?\s*人民币?\s*\n?\s*([\d,\.]+)\s*\n?\s*[:：]?\s*\n?\s*(万[元]?|亿[元]?|元)',
            r'注册资本\s*[:：|]\s*\n?\s*([\d,\.]+)\s*\n?\s*[:：]?\s*\n?\s*(万[元]?|亿[元]?|元)',
            r'注册资本\s*[:：|]\s*\n?\s*(?:为)?\s*\n?\s*人民币?\s*\n?\s*([\d,\.]+)',
            # 表格格式：注册资本 | 人民币X亿元 或 注册资本 | X亿元
            r'注册资本\s*\|?\s*人民币\s*([\d,\.]+)\s*(万|亿)?元?',
            r'注册资本\s*\|?\s*([\d,\.]+)\s*(万|亿)?元?',
        ]
        for pattern in capital_patterns:
            for st in search_texts:
                match = re.search(pattern, st)
                if match:
                    value = self._clean_field_value(match.group(1))
                    if len(match.groups()) > 1 and match.group(2):
                        unit = match.group(2)
                        # Normalize unit: ensure ends with "元" not "万"/"亿" alone
                        if unit in ('万',):
                            unit = '万元'
                        elif unit in ('亿',):
                            unit = '亿元'
                        elif not unit.endswith('元'):
                            unit = unit + '元'
                    else:
                        unit = "万元"
                    result["注册资本"] = value + unit
                    break
            if result["注册资本"]:
                break

        # 3. 提取实缴资本（同时支持"实缴资本"和"实收资本"）
        paid_in_patterns = [
            r'(?:实缴资本|实收资本)\s*[:：|]\s*\n?\s*人民币?\s*\n?\s*([\d,\.]+)\s*\n?\s*[:：]?\s*\n?\s*(万[元]?|亿[元]?|元)',
            r'(?:实缴资本|实收资本)\s*[:：|]\s*\n?\s*([\d,\.]+)\s*\n?\s*[:：]?\s*\n?\s*(万[元]?|亿[元]?|元)',
            r'(?:实缴资本|实收资本)\s*[:：|]\s*\n?\s*(?:为)?\s*\n?\s*人民币?\s*\n?\s*([\d,\.]+)',
            # 表格格式：实收资本 | 人民币X亿元 或 实缴资本 | X亿元
            r'(?:实缴资本|实收资本)\s*\|?\s*人民币\s*([\d,\.]+)\s*(万|亿)?元?',
            r'(?:实缴资本|实收资本)\s*\|?\s*([\d,\.]+)\s*(万|亿)?元?',
        ]
        for pattern in paid_in_patterns:
            for st in search_texts:
                match = re.search(pattern, st)
                if match:
                    value = self._clean_field_value(match.group(1))
                    if len(match.groups()) > 1 and match.group(2):
                        unit = match.group(2)
                        if unit in ('万',):
                            unit = '万元'
                        elif unit in ('亿',):
                            unit = '亿元'
                        elif not unit.endswith('元'):
                            unit = unit + '元'
                    else:
                        unit = "万元"
                    result["实缴资本"] = value + unit
                    break
            if result["实缴资本"]:
                break
        for pattern in paid_in_patterns:
            for st in search_texts:
                match = re.search(pattern, st)
                if match:
                    value = self._clean_field_value(match.group(1))
                    unit = match.group(2) if len(match.groups()) > 1 and match.group(2) else "万元"
                    result["实缴资本"] = value + unit
                    break
            if result["实缴资本"]:
                break

        # 3b) 兜底：基本信息章节未列示实缴资本时，用全文"发行人注册资本X，实缴资本Y"
        #     的表述补齐（限定主语为发行人/本公司，避免误取子公司数据）
        #     task 66：佛山市高明的概况表未列实缴资本，风险章节披露为 1.14 亿元
        if not result["实缴资本"]:
            flat = re.sub(r'\s+', '', self.full_text or '')
            fm = re.search(
                r'(?:发行人|本公司)\s*注册资本\s*[:：]?\s*[\d,\.]+\s*(?:万元|亿元|万|亿|元)'
                r'[，,；;]\s*实缴资本\s*[:：]?\s*([\d,\.]+)\s*(万元|亿元|万|亿|元)', flat)
            if fm:
                result["实缴资本"] = fm.group(1) + fm.group(2)

        # 4. 提取设立日期
        for st in search_texts:
            d = self._extract_establishment_date(st)
            if d:
                result["设立日期"] = d
                break

        # 5. 提取经营范围
        for st in search_texts:
            s = self._extract_business_scope(st)
            if s:
                result["经营范围"] = s
                break

        return result

    def _convert_table_format(self, text: str) -> str:
        """将 | 分隔的表格格式转换为 key: value 格式，便于正则匹配"""
        lines = text.split('\n')
        result_lines = []
        i = 0
        while i < len(lines):
            line = lines[i].strip()
            if '|' in line:
                # 拆分表格行
                parts = [p.strip() for p in line.split('|')]
                # 尝试匹配 key-value 对
                field_keywords = ['注册名称', '公司名称', '法定代表人', '注册资本', '实缴资本',
                                  '实收资本', '设立日期', '成立日期', '统一社会信用代码',
                                  '住所', '注册地址', '所属行业', '经营范围', '企业类型',
                                  '信息披露事务负责人',
                                  '设立（工商注册）日期']
                j = 0
                while j < len(parts) - 1:
                    key = parts[j].strip()
                    val = parts[j + 1].strip()
                    # 如果当前部分是已知字段名，则转换为 key: value 格式
                    if any(kw in key for kw in field_keywords) and val:
                        result_lines.append(f"{key}: {val}")
                        j += 2
                    else:
                        j += 1
                if j >= len(parts):
                    i += 1
                    continue
            else:
                result_lines.append(line)
            i += 1
        return '\n'.join(result_lines)

    def _extract_establishment_date(self, text: str) -> str:
        """
        提取设立日期 - 专门处理逐字换行格式
        例如：设\n立\n日\n期\n2\n0\n0\n0\n年\n3\n月\n2\n7\n日
        """
        # 先尝试提取标准格式
        standard_patterns = [
            r'(?:设立日期|成立日期|设立[（(]工商注册[）)]日期)\s*[:：|]?\s*(\d{4})\s*年\s*(\d{1,2})\s*月\s*(\d{1,2})\s*日',
            r'(?:设立日期|成立日期|设立[（(]工商注册[）)]日期)\s*[:：|]?\s*(\d{4}[年/\-\.]\d{1,2}[月/\-\.]\d{1,2}[日]?)',
        ]

        for pattern in standard_patterns:
            match = re.search(pattern, text)
            if match:
                groups = match.groups()
                if len(groups) == 3:
                    return f"{groups[0]}年{groups[1]}月{groups[2]}日"
                date_str = self._clean_field_value(match.group(1))
                # 处理 ISO 格式 YYYY-MM-DD
                iso_match = re.match(r'(\d{4})[-\.](\d{2})[-\.](\d{2})', date_str)
                if iso_match:
                    return f"{iso_match.group(1)}年{iso_match.group(2)}月{iso_match.group(3)}日"
                # 处理 YYYY/M/D 格式
                slash_match = re.match(r'(\d{4})/(\d{1,2})/(\d{1,2})', date_str)
                if slash_match:
                    return f"{slash_match.group(1)}年{slash_match.group(2)}月{slash_match.group(3)}日"
                iso_match = re.match(r'(\d{4})[-\.](\d{1,2})[-\.](\d{1,2})', date_str)
                if iso_match:
                    return f"{iso_match.group(1)}年{iso_match.group(2)}月{iso_match.group(3)}日"
                return date_str

        # 处理逐字换行格式：查找"设立日期"或"成立日期"后的数字序列
        date_field_patterns = [
            r'(?:设立日期|成立日期|设立[（(]工商注册[）)]日期)\s*[:：]?\s*',
        ]

        for pattern in date_field_patterns:
            match = re.search(pattern, text)
            if match:
                pos = match.end()
                extracted = []
                i = pos
                # 收集最多30个字符，用于组成日期
                while i < len(text) and len(extracted) < 30:
                    char = text[i]
                    if char.isdigit() or char in ['年', '月', '日', '\n']:
                        extracted.append(char)
                    elif char.strip() and char not in ['\n', '\r', '\t']:
                        if len([c for c in extracted if c.isdigit()]) >= 6:
                            break
                    i += 1

                # 清理提取的字符，只保留数字
                date_chars = [c for c in extracted if c.isdigit()]

                # 尝试解析日期：yyyy年mm月dd日 格式需要至少8位数字
                if len(date_chars) >= 8:
                    year = ''.join(date_chars[:4])
                    month = ''.join(date_chars[4:6])
                    day = ''.join(date_chars[6:8])
                    return f"{year}年{month}月{day}日"
                elif len(date_chars) >= 6:
                    year = ''.join(date_chars[:4])
                    month = ''.join(date_chars[4:5]) if len(date_chars) == 5 else ''.join(date_chars[4:6])
                    day = ''.join(date_chars[5:6]) if len(date_chars) == 6 else ''.join(date_chars[6:8]) if len(date_chars) >= 8 else '01'
                    return f"{year}年{month}月{day}日"

        # 备用方案：直接从文本中提取日期模式（yyyy年mm月dd日）
        date_regex = r'(\d{4})\s*年\s*(\d{1,2})\s*月\s*(\d{1,2})\s*日'
        matches = re.findall(date_regex, text)
        if matches:
            for year, month, day in matches:
                idx = text.find(f"{year}年{month}月{day}日")
                context = text[max(0, idx-100):idx+20]
                if any(kw in context for kw in ['设立', '成立', '日期', '注册', '工商']):
                    return f"{year}年{month}月{day}日"
            return f"{matches[0][0]}年{matches[0][1]}月{matches[0][2]}日"

        return ""

    def _extract_business_scope(self, text: str) -> str:
        """
        提取经营范围 - 增强版
        """
        scope_patterns = [
            # 优先匹配"一般项目"开头的经营范围
            r'经营范围\s*[:：|]\s*\n?\s*一般项目[：:]?\s*([^\n]{20,2000}?(?:自主开展经营活动|依法须经批准的项目|经营范围[：；]))',
            # 匹配经营范围后跟关键截止词
            r'经营范围\s*[:：|]?\s*\n?\s*([\s\S]{30,2000}?)\n\s*(?:电话及传真|电话[:：]|传真[:：]|信息披露事务负责人|联系(?:电话|方式)|网址|所属行业|统一社会信用代码)',
            r'经营范围\s*[:：|]\s*\n?\s*([\s\S]{20,1000}?)\n\s*(?:信息披露事务负责人|联系(?:电话|方式)|传真号码|网址|所属行业|二、发行人)',
        ]
        for pattern in scope_patterns:
            match = re.search(pattern, text)
            if match:
                scope = self._clean_field_value(match.group(1))
                scope = re.sub(r'(?:电话及传真|电话[:：]|传真[:：]|信息披露事务负责人|联系(?:电话|方式)|网址|所属行业|二、).*', '', scope)
                if len(scope) > 10:
                    if len(scope) > 1000:
                        scope = scope[:1000] + "..."
                    return scope

        # 备用方案：从文本中查找经营范围关键词后的内容
        scope_start_patterns = [
            r'经营范围\s*[:：|]\s*',
        ]
        for pattern in scope_start_patterns:
            match = re.search(pattern, text)
            if match:
                start_pos = match.end()
                # 提取最多800字符
                end_pos = min(start_pos + 800, len(text))
                # 查找自然结束点（句号、分号、或者下一个字段）
                next_field_match = re.search(r'(?:电话|传真|联系人|信息披露|统一社会信用代码|所属行业)', text[start_pos:end_pos])
                if next_field_match:
                    end_pos = start_pos + next_field_match.start()
                scope = text[start_pos:end_pos].strip()
                scope = re.sub(r'\s+', ' ', scope)
                if len(scope) > 10:
                    return scope

        return ""

    def _convert_field_value_lines(self, text: str) -> str:
        """将"字段名\n字段值"格式转换为"字段名: 字段值"格式"""
        field_keywords = ['注册名称', '公司名称', '法定代表人', '注册资本', '实缴资本',
                          '实收资本', '设立日期', '成立日期', '统一社会信用代码',
                          '住所', '注册地址', '邮政编码', '所属行业', '经营范围',
                          '信息披露事务负责人', '设立（工商注册）日期', '企业类型',
                          '公司注册地址', '联系人', '电话号码', '传真号码', '股票代码']
        lines = text.split('\n')
        result = []
        i = 0
        while i < len(lines):
            line = lines[i].strip()
            matched_field = None
            for kw in field_keywords:
                if kw in line:
                    matched_field = kw
                    break
            if matched_field and i + 1 < len(lines):
                # 标签行本身可能已带值（如"经营范围：对工程项目的投资及管理、…"），
                # 该值必须保留，否则会被下一行的合并结果覆盖丢失（task 66：佛山市高明）
                inline = ''
                mm = re.match(r'^.*?' + re.escape(matched_field) + r'\s*[:：|]\s*(.+)$', line)
                if mm:
                    inline = mm.group(1).strip()
                # 合并从下一行开始的值（可能跨多行直到遇到下一个字段名或截止词）
                value_lines = []
                j = i + 1
                while j < len(lines):
                    next_line = lines[j].strip()
                    if not next_line:
                        break
                    # 检查是否是下一个字段名
                    is_next_field = any(kw in next_line for kw in field_keywords)
                    # 检查是否是常见的截止词
                    is_stop_word = any(kw in next_line for kw in
                        ['二、', '三、', '第四节', '第五节', '电话及传真', '公司电话', '公司传真',
                         '信息披露事务', '联系方'])
                    if is_next_field or is_stop_word:
                        break
                    value_lines.append(next_line)
                    j += 1
                value = ' '.join(([inline] if inline else []) + value_lines)
                if value:
                    result.append(f"{matched_field}: {value}")
                else:
                    result.append(line)
                i = j
            else:
                result.append(line)
                i += 1
        return '\n'.join(result)

    def _preprocess_text(self, text: str) -> str:
        """预处理文本：检测并处理"单字换行"格式"""
        lines = text.split('\n')
        non_empty_lines = [l for l in lines if l.strip()]
        if not non_empty_lines:
            return text

        short_lines = [l for l in non_empty_lines if len(l.strip()) <= 3]
        is_single_char_format = len(short_lines) > len(non_empty_lines) * 0.6

        if not is_single_char_format:
            clean = re.sub(r'\.{3,}\s*\d+\s*$', '', text, flags=re.MULTILINE)
            # Remove standalone page numbers (exactly 3 digits, to avoid removing years like 2016 or content numbers like 60)
            clean = re.sub(r'(?<=\n)\s*([1-9]\d{2})\s*(?=\n)', '', clean)
            clean = re.sub(r'\n{3,}', '\n\n', clean)
            # 处理"字段名\n字段值"格式（无冒号分隔的表格行）
            clean = self._convert_field_value_lines(clean)
            return clean

        result_lines = []
        current_line = ""
        field_names = ['注册名称', '公司名称', '法定代表人', '注册资本', '实缴资本', '实收资本', '设立日期', '成立日期',
                       '统一社会信用代码', '住所', '注册地址', '邮政编码', '所属行业', '经营范围', '信息披露事务负责人']

        for line in lines:
            line = line.strip()
            if not line:
                if current_line:
                    result_lines.append(current_line)
                    current_line = ""
                continue

            if re.match(r'^[\d,\.]+$', line):
                if current_line and any(current_line.endswith(f) for f in field_names):
                    current_line += ": " + line
                else:
                    current_line += line
            elif line in ['万元', '亿元', '元', '年', '月', '日', '）日期', ')日期', '日期']:
                current_line += line
                if line in ['年', '月'] and current_line and re.search(r'\d{4}年\d{1,2}月$', current_line):
                    continue
                result_lines.append(current_line)
                current_line = ""
            elif len(line) <= 3:
                new_field_keywords = ['法定', '统一', '住所', '经营', '信息', '联系', '所属']
                if line == '注册' and current_line and not any(current_line.endswith(f) for f in field_names):
                    current_line += line
                elif line in ['设立', '成立']:
                    if current_line:
                        result_lines.append(current_line)
                    current_line = line
                elif any(line.startswith(k) for k in new_field_keywords) and current_line:
                    result_lines.append(current_line)
                    current_line = line
                else:
                    current_line += line
            else:
                if current_line:
                    # 如果 current_line 是完整的字段名，添加冒号分隔
                    is_field = any(current_line == f or current_line.startswith(f) for f in field_names)
                    if is_field:
                        result_lines.append(current_line + ": " + line)
                    else:
                        result_lines.append(current_line + line)
                    current_line = ""
                else:
                    result_lines.append(line)

        if current_line:
            result_lines.append(current_line)

        return '\n'.join(result_lines)

    def _postprocess_char_format(self, text: str) -> str:
        """后处理单字换行格式结果，修复字段名和值之间的连接问题"""
        field_keywords = ['注册名称', '公司名称', '法定代表人', '注册资本', '实缴资本',
                          '实收资本', '设立日期', '成立日期', '统一社会信用代码',
                          '住所', '注册地址', '邮政编码', '所属行业', '经营范围',
                          '信息披露事务负责人', '设立（工商注册）日期']

        # Step 1: 修复常见 split 字段名
        # "设立（工\n商注册）日期" -> "设立（工商注册）日期"
        text = text.replace('设立（工\n商注册）日期', '设立（工商注册）日期')
        text = text.replace('住\n所', '住所')
        text = text.replace('法\n定\n代表\n人', '法定代表人')
        text = text.replace('法\n定代表\n人', '法定代表人')

        # Step 2: 修复字段名后直接跟值但没有冒号的情况
        for kw in field_keywords:
            escaped = re.escape(kw)
            pattern = escaped + r'(?![：:\n\s])([\u4e00-\u9fa5a-zA-Z0-9])'
            text = re.sub(pattern, kw + ': ' + r'\1', text)

        # Step 3: 修复跨行值
        lines = text.split('\n')
        merged = []
        for line in lines:
            if merged:
                prev = merged[-1]
                for kw in field_keywords:
                    prefix = kw + ': '
                    if prev.endswith(prefix):
                        val_part = prev[len(prefix):]
                        if 0 < len(val_part) < 30:
                            merged[-1] = prev + line.strip()
                            line = None
                            break
            if line:
                merged.append(line)
        return '\n'.join(merged)

    def _merge_char_newlines(self, text: str) -> str:
        """修复逐字换行格式，合并被换行分割的连续文本（如：湖\n州\n南\n浔 -> 湖州南浔）"""
        result = []
        buffer = ""
        for line in text.split('\n'):
            stripped = line.strip()
            if not stripped:
                if buffer:
                    result.append(buffer)
                    buffer = ""
                continue
            is_fragment = (
                len(stripped) <= 3 and
                re.match(r'^[一-龥a-zA-Z0-9\s\.\,\;\:\%\。\!\?\;\:\，\、]+$', stripped) and
                not re.match(r'^(?:公司|集团|局|政府|办公室|财政局|国资委|管委会|有限公司|发行人|截至|报告|期末|股权|结构|股东|控股|实际|控制人|持有|出资|设立|成立|注册|资本|法定代表人|经营范围|主营业务)$', stripped)
            )
            if is_fragment:
                buffer += stripped
            else:
                if buffer:
                    result.append(buffer)
                    buffer = ""
                result.append(stripped)
        if buffer:
            result.append(buffer)
        return '\n'.join(result)

    def _clean_field_value(self, value: str) -> str:
        """清理字段值中的多余字符"""
        if not value:
            return ""
        value = re.sub(r'<[^>]+>', '', value)
        value = re.sub(r'\s+', ' ', value)
        # 清除中文之间的空格（PDF逐字提取导致，如"强 村"→"强村"）
        value = re.sub(r'([一-龥])\s+([一-龥])', r'\1\2', value)
        value = value.strip()
        return value

    def _extract_equity_structure_from_controlling_shareholder(self, section_text: str) -> str:
        """从控股股东/实际控制人部分提取股权信息 - 增强版，支持多层级和文字版架构"""
        lines = []
        issuer_name = self._issuer_name or "发行人"

        if not section_text or len(section_text.strip()) < 20:
            return "（待提取）"

        # 预处理文本：清理多余空白，合并被换行分割的文本
        processed_text = re.sub(r'\n+', '\n', section_text)

        processed_text = self._merge_char_newlines(processed_text)
        # 额外处理：合并被换行分割的公司名称
        # 策略1：X有限公司 split by newline（如"控股集\n团有限公司"）
        # 注意：不能合并两个独立的公司名（如"AA有限公司\nBB有限公司"）
        def merge_company_newline(match):
            before = match.group(1)
            after = match.group(2)
            # 如果 after 以完整公司名开头（如"衢州市国有资本..."），说明是新公司名，不合并
            if re.match(r'^[一-龥]{2,15}(?:有限公司|有限责任公司|股份有限公司|集团有限公司)', after):
                return match.group(0)  # 保持原样
            # 如果 before 本身已是完整公司名（以"有限公司"等结尾），不合并
            if re.search(r'(?:有限公司|有限责任公司|股份有限公司|集团有限公司)$', before):
                return match.group(0)
            return before + after

        processed_text = re.sub(
            r'([一-龥]+)[\n\r]+([一-龥]*(?:有限公司|有限责任公司|股份有限公司|集团有限公司)[一-龥]*)',
            merge_company_newline,
            processed_text
        )
        # 策略2：任意中文字符+换行+中文字符，如果两边合起来像公司名（含"公司""集团"等关键词）
        # 扩大长度限制以适配长公司名被拆分的场景
        processed_text = re.sub(
            r'([一-龥]{3,50}[\n\r]+[一-龥]{1,50})',
            lambda m: m.group(1).replace('\n', '').replace('\r', '')
            if any(kw in m.group(1) for kw in ['公司', '集团', '局', '政府', '办公室', '财政局', '国资委', '管委会', '控股'])
            and not re.search(r'(?:有限公司|有限责任公司|股份有限公司|集团有限公司)[\n\r]+[一-龥]', m.group(1))
            else m.group(1),
            processed_text
        )
        # 合并"持股\n100%\n股权"这种比例中间的换行
        processed_text = re.sub(r'(\d+)\s*[\n\r]\s*(%)', r'\1\2', processed_text)

        processed_text = re.sub(r'\s+', ' ', processed_text)

        # 合并被换行分割的股东名称 - 增强版，处理"XX区\nXX办公室"格式
        processed_text = re.sub(r'([一-龥]{2,6}(?:区|县|市))\s+([^\s]{2,20}?(?:局|办|委|政府|监督管理办公室))',
                                r'\1\2', processed_text)
        processed_text = re.sub(r'(公司|集团|中心|政府|办公室|财政局|国资委|管委会|有限)[\n\r]+([^\n]{1,20}?(?:公司|集团|中心|政府|办公室|财政局|国资委|管委会))',
                                r'\1\2', processed_text)
        processed_text = re.sub(r'([一-龥]{2,6}(?:区|县|市))[\n\r]+([^\n]{2,15}?(?:局|办|委|政府))',
                                r'\1\2', processed_text)

        # 修复被空格分割的中文词语（如"持 有" -> "持有"）
        processed_text = re.sub(r'([一-龥])\s+([一-龥])', r'\1\2', processed_text)

        processed_text = self._merge_char_newlines(processed_text)
        # 再次清理合并后的空格
        processed_text = re.sub(r'\s+', ' ', processed_text)
        # 修复被空格分割的中文词语（如"湖 州 南 浔" -> "湖州南浔"）
        # 这个修复需要运行在 _merge_char_newlines 之后，因为 merge 可能留下空格
        processed_text = re.sub(r'([一-龥])\s+([一-龥])', r'\1\2', processed_text)

        all_holders = []

        # 辅助函数：验证公司名称是否有效
        def is_valid_company_name(name: str) -> bool:
            if not name:
                return False
            if len(name) < 3 or len(name) > 50:
                return False
            # 排除仅包含公司后缀的名称
            if re.match(r'^(?:有限公司|有限责任公司|股份有限公司|集团有限公司|集团)$', name):
                return False
            # 排除常见的非公司名称模式
            exclude_keywords = [
                '及实际控制人', '及控股股东', '及控制人', '及股东',
                '的具体情况', '的详细情况', '详见', '详情',
                '变更为', '基本情况', '详细介绍', '如下所示',
                '如下', '所示', '主要', '简介', '说明',
                '发行人概况', '本公司', '公司债券', '募集说明书',
                '股东名称', '持股比例', '注册资本', '法定代表人',
                '截至报告期末', '报告期', '财务报表', '因此',
                '书签署之日', '根据', '由于', '鉴于', '全部无偿转让给',
                '发行人股权结构图', '股权结构图如下', '股权结构图',
                '股权结构',  # 株洲高科场景：页眉文本合并使"三、发行人的股权结构株洲高科产业投资集团…"被误当公司名
                '为实际控制人', '和实际控制人', '均为', '决定将',
                '的出资人由', '面向专业投资者', '年面向',
                '年面向专业投资者', '公开发行公司', '非公开发行',
            ]
            for kw in exclude_keywords:
                if kw in name:
                    return False
            # 排除纯数字或纯英文
            if re.match(r'^[\d\s\.]+$', name):
                return False
            if re.match(r'^[a-zA-Z\s]+$', name):
                return False
            # 必须以中文字符开头（除非是知名缩写）
            if not re.match(r'^[一-龥]', name):
                # 允许个别知名的英文缩写如IBM等，但一般公司名应该以中文开头
                if len(name) < 4 or not re.search(r'[一-龥]', name):
                    return False
            # 必须包含有效的机构关键词
            valid_keywords = ['公司', '集团', '局', '政府', '办公室', '财政局', '国资委', '管委会', '中心', '委', '公资办', '资产办', '农业农村', '监']
            if not any(kw in name for kw in valid_keywords):
                return False
            return True

        # 辅助函数：清理公司名称
        def clean_company_name(name: str) -> str:
            if not name:
                return ""
            # 移除前后空白
            name = name.strip()
            # 移除前缀如"变更为"、"因此"等
            name = re.sub(r'^(?:变更为|为|是|以及|及|因此|由于|鉴于|根据|书签署之日|截至报告期末|全部无偿转让给|发行人系依法成立的|同意)\s*', '', name)
            # 移除"和实际控制人"、"均为"等前缀
            name = re.sub(r'^(?:和实际控制人|均为|系|发行人|公司|控股股东|实际控制人)[是为均]*\s*', '', name)
            # 移除"股权结构图"前缀
            name = re.sub(r'^股权结构图\s*', '', name)
            # 移除后缀 - 更全面的清理
            name = re.sub(r'(?:的具体情况|的详细情况|详见|如下|所示|主要|简介|说明|以及|及).*$', '', name)
            # 移除"持有的公司"、"持有的股权"等后缀
            name = re.sub(r'持有的(?:公司|股权|股份).*$', '', name)
            name = re.sub(r'持有.*$', '', name)
            # 移除"将名下"、"决定将"等中间文本
            name = re.sub(r'将名下.*$', '', name)
            name = re.sub(r'决定将.*$', '', name)
            # 移除"直接"后缀（如"嘉祥县国有资产事务中心直接"）
            name = re.sub(r'直接$', '', name)
            # 移除PDF文件名相关后缀（年份+债券发行描述）
            name = re.sub(r'\s*20\d{2}\s*年面向.*$', '', name)
            name = re.sub(r'\s*20\d{2}\s*年.*$', '', name)
            # 移除"的出资人由"等文本
            name = re.sub(r'的出资人由.*$', '', name)
            # 移除数字噪声（如"474,016.6785.002"）
            name = re.sub(r'[\d,\.]{5,}', '', name)
            # 移除括号及其内容（包括简称标注）
            # 但保留公司名内的括号（如"（集团）"）
            # 只移除包含"简称"、"以下简称"等标注的括号
            name = re.sub(r'[（(][^）)]*以下简称[^）)]*[）)]', '', name)
            name = re.sub(r'[（(][^）)]*简称[^）)]*[）)]', '', name)
            # 移除未闭合的括号（如"（三"）
            name = re.sub(r'[（(][^）)]*$', '', name)
            # 移除"以下简称"及后续内容
            name = re.sub(r'以下简称.*$', '', name)
            # 移除地理前缀（省/市/区/县开头的长前缀，仅保留紧邻机构名的行政区划）
            # e.g. "广东省肇庆市封开县财政局" -> "封开县财政局"
            # 但不能把"樟树市人民政府"切成"人民政府"
            # 策略：只移除包含"省"或2个以上地级市名的前缀
            if re.search(r'省.*?市.*?市', name) or re.search(r'省.*?市.*?县', name):
                name = re.sub(r'^(?:.*?(?:省|自治区|直辖市))?(?:.*?市)?(?:.*?区)?((?:[一-龥]{1,6}县)?(?:财政局|国资委|国资办|公资办|人民政府|政府|国有资产事务中心|国有资产管理服务中心|国有资本运营有限公司|国有资产监督管理委员会|国有资产监督管理办公室|资产事务中心))$', r'\1', name)
            # 检测两个公司名拼接的情况（包含两个"有限公司"等后缀）
            # e.g. "广东省肇庆市封开县财政局封开县公有资产发展有限公司" -> "封开县财政局"
            double_company = re.search(r'((?:省|市|区|县)?[一-龥]{1,6}(?:财政局|国资委|人民政府|政府|局))([一-龥]+(?:有限公司|有限责任公司|股份有限公司|集团有限公司))$', name)
            if double_company:
                name = double_company.group(1)  # Keep the first (controlling) company
            # 检测发行人自身名称拼接（如"樟树市创业投资发展有限公司樟树市人民政府"）
            # 如果名称以发行人名称开头且后面还有其他内容，移除发行人名称前缀
            if issuer_name and name.startswith(issuer_name) and len(name) > len(issuer_name):
                name = name[len(issuer_name):]
            # 如果名称中包含发行人名称且前面是政府机构，取政府机构部分
            if issuer_name:
                # e.g. "XX樟树市创业投资发展有限公司樟树市人民政府" -> keep the part before issuer name
                idx = name.find(issuer_name)
                if idx > 0:
                    prefix = name[:idx].rstrip()
                    if any(kw in prefix for kw in ['财政局', '国资委', '人民政府', '政府', '局', '管委会']):
                        name = prefix
            # 移除标点符号
            name = re.sub(r'[。，；、：:．・•]', '', name)
            # 移除空格
            name = re.sub(r'\s+', '', name)
            # 移除多余的修饰词
            name = re.sub(r'(的?实际控制人|的?控股股东|的?股东|的?控股公司)$', '', name)
            name = re.sub(r'\s*报告期内.*$', '', name)
            name = re.sub(r'\s*（三）.*$', '', name)
            name = re.sub(r'\s*截至.*$', '', name)
            # 移除"控股股东为"/"控股股东"前缀（pattern 捕获）
            name = re.sub(r'^控股股东为\s*', '', name)
            name = re.sub(r'^控股股东\s*', '', name)
            name = re.sub(r'^的为.*$', '', name)
            # 移除紧跟在公司名后的"（三）"等章节标记（无空格）
            name = re.sub(r'[（(]三[）)].*$', '', name)
            # 移除"的"开头的多余文本
            name = re.sub(r'^的.*$', '', name)
            return name.strip()

        # 1. 首先尝试从"（二）控股股东和实际控制人"小节提取
        controlling_section_patterns = [
            r'(?:（二）|[(]二[)])\s*控股股东和实际控制人\s*[:：]?\s*([\s\S]{50,3000}?)(?=\n\s*(?:（三）|\(三\)|四、|五、|$))',
            r'(?:（二）|[(]二[)])\s*控股股东\s*[:：]?\s*([\s\S]{50,2000}?)(?=\n\s*(?:（三）|\(三\)|四、|五、|$))',
            r'（二）发行人控股股东及实际控制人\s*[:：]?\s*([\s\S]{50,3000}?)(?=\n\s*(?:（三）|\(三\)|四、|五、|$))',
        ]

        controlling_text = ""
        for pattern in controlling_section_patterns:
            match = re.search(pattern, processed_text, re.DOTALL)
            if match:
                controlling_text = match.group(1)
                break

        # 如果没找到（二）小节，使用整个section_text
        if not controlling_text:
            controlling_text = processed_text

        # 2. 首先尝试股权关系链条模式（优先于简单架构图，因为链条模式匹配更精确）
        # 提取股权关系链条（如：A公司 -> B公司 -> 发行人）
        chain_patterns = [
            # 模式0: 发行人控股股东为/及实际控制人为XX公司（精确匹配，优先运行）
            r'发行人控股股东(?:及实际控制人)?为([一-龥（）()]{4,50}(?:股份有限公司|有限责任公司|集团有限公司|有限公司|管委会|国资委|财政局|办公室|政府|集团|局|公司|中心|监督管理委员会|监督管理办公室|国有资产管理服务中心|国有资产事务中心))(?:[^"\'\n]{0,60}?(\d+(?:\.\d+)?)\s*%)?',
            # 模式0b: 发行人全称的控股股东为XX（适配罗湖等用全称替代"发行人"的情况）
            r'[一-龥]+?的控股股东为\s*([一-龥]{4,30}?(?:财政局|国资委|国资办|公资办|人民政府|政府|监督管理委员会))',
            # 模式0c: 控股股东为XX（短名），持股比例...XX%
            r'控股股东为([一-龥（）()]{2,20})[^"\'\n]{0,50}?持股比例[^"\'\n]{0,30}?(\d+(?:\.\d+)?)\s*%',
            # 模式1: XX公司持有XX公司XX%股权（后缀按最长到最短排序）
            r'([^"\'\n]{3,40}?(?:有限公司|有限责任公司|股份有限公司|集团有限公司|管委会|国资委|财政局|办公室|政府|集团|局|公司|中心))\s*持有\s*[^"\'\n]*?(?:公司|集团)?\s*(\d+(?:\.\d+)?)\s*%\s*(?:股权|股份)',
            # 模式2: XX公司XX%控股XX公司（后缀按最长到最短排序）
            r'([^"\'\n]{3,40}?(?:有限公司|有限责任公司|股份有限公司|集团有限公司|管委会|国资委|财政局|办公室|政府|集团|局|公司))\s*(\d+(?:\.\d+)?)\s*%\s*(?:控股|持股)',
            # 模式3: 控股股东为XX公司，持股XX%
            # 使用贪婪匹配捕获完整公司名（包括括号内容），然后匹配比例
            r'(?:控股股东|实际控制人)\s*为\s*([一-龥（）()]{3,50}(?:股份有限公司|有限责任公司|集团有限公司|有限公司|管委会|国资委|财政局|办公室|政府|集团|局|公司))[^"\'\n]{0,60}?(\d+(?:\.\d+)?)\s*%',
            # 模式4: XX公司为控股股东，持有XX%股权（后缀按最长到最短排序）
            r'([一-龥（）()]{3,50}?(?:股份有限公司|有限责任公司|集团有限公司|有限公司|管委会|国资委|财政局|办公室|政府|集团|局|公司))\s*为\s*(?:控股股东|实际控制人)[^"\'\n]{0,50}?(\d+(?:\.\d+)?)\s*%',
            # 模式5: XX公司 XX% 股权（后缀按最长到最短排序）
            r'([一-龥（）()]{3,50}?(?:股份有限公司|有限责任公司|集团有限公司|有限公司|管委会|国资委|财政局|办公室|政府|集团|局|公司))\s+(\d+(?:\.\d+)?)\s*%\s*(?:股权|股份|控股)',
            # 模式6: XX%股权由XX公司持有（后缀按最长到最短排序）
            r'(\d+(?:\.\d+)?)\s*%\s*(?:股权|股份|控股)\s*(?:由|系)?\s*([^"\'\n]{3,35}?(?:有限公司|有限责任公司|股份有限公司|集团有限公司|管委会|国资委|财政局|办公室|政府|集团|局|公司))',
            # 模式7: XX公司...持有发行人...XX%股权（后缀按最长到最短排序）
            r'([^"\'\n]{3,40}?(?:有限公司|有限责任公司|股份有限公司|集团有限公司|管委会|国资委|财政局|办公室|政府|集团|局|公司|中心))[^"\'\n]{0,100}?(?:持有|持股)[^"\'\n]{0,50}?(?:发行人|公司)[^"\'\n]{0,30}?(\d+(?:\.\d+)?)\s*%',
            # 模式7b: XX持有发行人XX%的股权（精确匹配"XX%的股权"格式，适配湖州南浔等）
            r'([一-龥（）()]{4,45}(?:有限公司|有限责任公司|股份有限公司|集团有限公司|管委会|国资委|财政局|办公室|政府|集团|局|公司|中心))[\s]{0,3}持[\s]{0,3}有[\s\S]{0,30}?(?:发行人|公司)[\s\S]{0,20}?(\d+(?:\.\d+)?)\s*%\s*的股权',
            # 模式8: 人民政府/国资委/财政局持有发行人XX%股权
            # 需要确保匹配的是完整的政府机构名，而不是文本中出现的其他提及
            r'(?:^|\s)([^"\'\n]{2,40}?(?:人民政府|国资委|财政局|国资办|公资办))[^"\'\n]{0,100}?(?:持有|持股)[^"\'\n]{0,50}?(?:发行人|公司)?[^"\'\n]{0,30}?(\d+(?:\.\d+)?)\s*%',
            # 模式9: XX公司持有发行人\n100%\n股权（处理换行格式，使用DOTALL模式，后缀按最长到最短排序）
            # 注意：需要排除"基本情况"等前缀，使用更精确的匹配
            r'([一-龥]{4,35}(?:有限公司|有限责任公司|股份有限公司|集团有限公司|管委会|国资委|财政局|办公室|政府|集团|局|公司|中心))[\s\S]{0,80}?(?:持有|持股)[\s\S]{0,80}?(?:发行人|公司)[\s\S]{0,30}?(\d+(?:\.\d+)?)\s*%[\s\S]{0,20}?(?:股权|股份)?',
            # 模式10: XX公司...是发行人的唯一出资人/实际控制人（后缀按最长到最短排序）
            r'([一-龥]{2,40}(?:有限公司|有限责任公司|股份有限公司|集团有限公司|管委会|国资委|财政局|办公室|政府|集团|局|公司|中心|监督管理委员会|监督管理办公室|国有资产管理服务中心|国有资产事务中心)[^"\'\n]{0,10})[\s\S]{0,100}?(?:唯一出资人|实际控制人)[\s\S]{0,20}?[，。]',
            # 模式11: 控股股东为XX公司，实际控制人为XX局（处理两层架构，后缀按最长到最短排序）
            # 需要确保中间不包含"（三）"等章节分隔符
            r'(?:控股股东|控制人)[\s\S]{0,10}?(?:为|是)[\s\S]{0,10}?([一-龥]{2,30}(?:有限公司|有限责任公司|股份有限公司|集团有限公司|管委会|国资委|财政局|办公室|政府|集团|局|公司))[\s\S]{0,50}?(?:实际控制人|控制人)[\s\S]{0,10}?(?:为|是)[\s\S]{0,10}?([一-龥]{2,30}(?:有限公司|有限责任公司|股份有限公司|集团有限公司|管委会|国资委|财政局|办公室|政府|集团|局|公司))',
            # 模式11b: XX持有发行人/公司XX%股权（精确匹配，避免捕获"基本情况"前缀）
            r'([一-龥]{2,30}(?:有限公司|有限责任公司|股份有限公司|集团有限公司|管委会|国资委|财政局|办公室|政府|集团|局|公司|中心))[^"\'\n]{0,50}?(?:持有|持股)[^"\'\n]{0,30}?(?:发行人|公司)[^"\'\n]{0,10}?(\d+(?:\.\d+)?)\s*%',
            # 模式12: 直接从"截至报告期末，发行人股权结构图如下"后提取股东（后缀按最长到最短排序）
            r'(?:股权结构图|股权结构)[\s\S]{0,30}?(?:如下|所示)[:：]?[\s\S]{0,100}?发行人[\s\S]{0,50}?([一-龥]{2,30}(?:有限公司|有限责任公司|股份有限公司|集团有限公司|管委会|国资委|财政局|办公室|政府|集团|局|公司))[\s\S]{0,20}?(\d+(?:\.\d+)?)\s*%',
            # 模式13: 控股股东为XX公司，持有发行人XX%股权（核心模式，适配换行和"持有发行人"表述，后缀按最长到最短排序）
            r'控股股东.{0,5}?为.{0,5}?([一-龥（）()]{2,25}(?:股份有限公司|有限责任公司|集团有限公司|有限公司|管委会|国资委|财政局|办公室|政府|集团|局|公司))[\s\S]{0,80}?持有\s*(?:发行人|公司)\s*(\d+(?:\.\d+)?)\s*%\s*(?:股权)?',
            # 模式14: 控股股东为XX公司，持股XX%（短句，适配换行，后缀按最长到最短排序）
            r'控股股东.{0,5}?为.{0,5}?([一-龥（）()]{2,25}(?:股份有限公司|有限责任公司|集团有限公司|有限公司|管委会|国资委|财政局|办公室|政府|集团|局|公司))[\s\S]{0,30}?持股[\s\S]{0,20}?(\d+(?:\.\d+)?)\s*%',
            # 模式14b: 控股股东的基本/具体情况如下：名称：XX公司
            # 放在实际控制人模式之前，优先匹配具体公司名
            r'控股股东[的]?.{0,4}情况如下[\s\S]{0,200}?名称[：:\s]*([一-龥（）()]{4,50}(?:有限公司|有限责任公司|股份有限公司|集团有限公司|管委会|国资委|财政局|办公室|政府|集团|局|公司))',
            # 模式15: 实际控制人为XX
            r'实际控制人\s*为\s*([，。；\n]{0,3}[一-龥]{2,40}?(?:人民政府|国资委|财政局|国资办|公资办|公司|集团|局|政府|办公室|管委会))',
            # 模式16: 控股股东和/及实际控制人均为/为XX（无比例，适配财政局/国资委等政府机构）
            # 放在具体模式之后，避免优先匹配到政府机构名
            r'控股股东(?:和|及)实际控制人(?:均|及)?\s*为\s*([^"\'\n，。；]{2,40}?(?:财政局|国资委|国资办|公资办|人民政府|政府|局|办公室|管委会))',
            # 模式17: 发行人的控股股东为XX（无比例，适配财政局/国资委等政府机构）
            r'发行人(?:的)?控股股东\s*为\s*([^"\'\n，。；]{2,40}?(?:财政局|国资委|国资办|公资办|人民政府|政府|局|办公室|管委会))',
            # 模式18: （已合并到模式7b）
            # 模式19: 控股股东的基本/具体情况如下：名称：XX公司
            # 允许"如下"和"名称"之间有PDF文件名等噪声
            r'控股股东[的]?.{0,4}情况如下[\s\S]{0,200}?名称[：:\s]*([一-龥（）()]{4,50}(?:有限公司|有限责任公司|股份有限公司|集团有限公司|管委会|国资委|财政局|办公室|政府|集团|局|公司))',
            # 模式20: XX为发行人控股股东/实际控制人（无比例）
            r'([一-龥（）()]{4,40}(?:有限公司|有限责任公司|股份有限公司|集团有限公司|管委会|国资委|财政局|办公室|政府|集团|局|公司|中心))\s*为\s*发行人\s*(?:控股)?股东',
        ]

        for pattern in chain_patterns:
            match = re.search(pattern, controlling_text, re.IGNORECASE | re.DOTALL)
            if match:
                groups = match.groups()
                if len(groups) >= 2:
                    # 判断哪个是公司名，哪个是比例
                    company = groups[0].strip()
                    ratio = groups[1].strip() if groups[1] is not None else None

                    # 如果第一个是数字（比例），第二个是公司名（模式6）
                    if ratio is not None and re.match(r'^[\d\.]+$', company.replace('%', '').strip()):
                        ratio = company.replace('%', '').strip()
                        company = groups[1].strip()

                    # 清理公司名称
                    company = clean_company_name(company)

                    # 过滤片段式错误匹配（如"办公室）持有..."被清理为"办公室）"）
                    # 特征：包含未配对的右括号
                    if ('）' in company and '（' not in company) or (')' in company and '(' not in company):
                        continue

                    # 验证并过滤无效名称
                    if is_valid_company_name(company):
                        if not any(h[0] == company for h in all_holders):
                            all_holders.append((company, ratio))
                            break  # 找到一个有效匹配就停止，避免重复
                elif len(groups) == 1:
                    # 模式10/15/16/17 只有一个公司名（无比例）
                    company = clean_company_name(groups[0])
                    if is_valid_company_name(company):
                        if not any(h[0] == company for h in all_holders):
                            all_holders.append((company, None))
                            break

        # 3. 如果链条模式没找到，尝试从"股权结构图如下"模式提取简单的两层架构
        if not all_holders:
            simple_architecture_patterns = [
                # 模式: 股权结构图如下 + 发行人名 + 股东名 + 比例
                # 使用[一-龥]限制只匹配中文字符，避免捕获百分比等噪声
                r'股权结构图如下[:：]\s*([一-龥]{2,40}?)\s+[一-龥]+\s*\d+%\s*([一-龥]{3,40}?(?:公司|集团|局|政府|办公室|财政局|国资委|管委会|有限公司))\s+(\d+(?:\.\d+)?)\s*%',
                # 模式: 截至...股权结构图如下 + 股东名 + 比例
                r'截至[^\n]*股权结构图如下[:：]?\s*\n?\s*([^\n]{2,40}?)\s*\n\s*([^\n]{3,40}?(?:公司|集团|局|政府|办公室|财政局|国资委|管委会))\s*\n?\s*(\d+(?:\.\d+)?)\s*%',
            ]

            for pattern in simple_architecture_patterns:
                match = re.search(pattern, controlling_text)
                if match:
                    if len(match.groups()) == 3:
                        potential_issuer = match.group(1).strip()
                        company = match.group(2).strip()
                        ratio = match.group(3).strip()
                    else:
                        company = match.group(1).strip()
                        ratio = match.group(2).strip() if len(match.groups()) > 1 else None

                    # 验证提取的公司名是否有效
                    company_cleaned = clean_company_name(company)
                    if is_valid_company_name(company_cleaned):
                        all_holders.append((company_cleaned, ratio))
                        break

        # 4. 如果没找到链条，尝试简单提取控股股东和实际控制人
        if not all_holders:
            simple_patterns = [
                # 模式1: 控股股东为XX公司（后缀按最长到最短排序）
                r'控股股东\s*为\s*[:：]?\s*([^"\'\n，。；]{3,35}?(?:有限公司|有限责任公司|股份有限公司|集团有限公司|管委会|国资委|财政局|办公室|政府|集团|局|公司|公资办|资产办))',
                # 模式1b: 控股股东及实际控制人均为XX（处理"均为"格式）
                r'控股股东及实际控制人均为\s*([^"\'\n，。；]{3,40}?(?:有限公司|有限责任公司|股份有限公司|集团有限公司|管委会|国资委|财政局|办公室|政府|集团|局|公司|人民政府|公资办|资产办|监督管理办公室))',
                # 模式2: 实际控制人为XX
                r'实际控制人\s*为\s*[:：]?\s*([^"\'\n，。；]{3,35}?(?:有限公司|有限责任公司|股份有限公司|集团有限公司|管委会|国资委|财政局|办公室|政府|集团|局|公司|人民政府|公资办|资产办))',
                # 模式3: XX公司是控股股东
                r'([^"\'\n]{3,35}?(?:有限公司|有限责任公司|股份有限公司|集团有限公司|管委会|国资委|财政局|办公室|政府|集团|局|公司|公资办|资产办))\s*是\s*(?:发行人|公司)\s*的\s*控股股东',
                # 模式4: 发行人为XX公司的全资子公司/控股子公司
                r'([^"\'\n]{3,35}?(?:有限公司|有限责任公司|股份有限公司|集团有限公司|管委会|国资委|财政局|办公室|政府|集团|局|公司))[^"\'\n]{0,30}?(?:全资|控股)子?公司',
                # 模式5: 由XX公司/局/政府出资设立
                r'由\s*([^"\'\n，。；]{3,35}?(?:有限公司|有限责任公司|股份有限公司|集团有限公司|管委会|国资委|财政局|办公室|政府|集团|局|公司))[^"\'\n]{0,20}?(?:出资|组建|批准)',
            ]

            for pattern in simple_patterns:
                match = re.search(pattern, controlling_text, re.IGNORECASE)
                if match:
                    holder_name = clean_company_name(match.group(1))

                    if is_valid_company_name(holder_name):
                        # 查找持股比例
                        ratio = None
                        ratio_patterns = [
                            r'(?:持有|控股|持股|占比)\s*(?:发行人|公司)?\s*[:：]?\s*(\d+(?:\.\d+)?)\s*%',
                            r'(?:股权|股份)\s*[:：]?\s*(\d+(?:\.\d+)?)\s*%',
                            r'(\d+(?:\.\d+)?)\s*%\s*(?:股权|股份|控股)',
                        ]
                        for rp in ratio_patterns:
                            rm = re.search(rp, controlling_text[:800])
                            if rm:
                                ratio = rm.group(1)
                                break

                        all_holders.append((holder_name, ratio))
                        break  # 找到第一个有效匹配就停止

        # 5. 尝试从表格格式数据提取（如：股东名称 | 持股比例）
        if not all_holders:
            table_patterns = [
                # 匹配 "股东名称" "持股比例" 格式的表格内容
                r'(?:股东名称|股东)[：:\s]*([^\n|]{3,30}(?:公司|集团|局|政府))[^\n]*?(?:持股)?\s*(?:比例)?[：:\s]*(\d+(?:\.\d+)?)\s*%',
                # 匹配股东列表后跟随比例
                r'([一-龥]{2,6}(?:区|县|市)[^\n]{0,20}(?:局|办|委|政府|公司)).*?\n[^\n]*?(\d+(?:\.\d+)?)\s*%',
                # 匹配 "发行人名称 + 股东名称 + 100%" 格式（常见于股权架构图下方的文字）
                r'(?:发行人|公司)\s*[:：]?\s*\n?\s*([^\n]{2,40}?)\s*\n\s*([^\n]{3,35}?(?:公司|集团|局|政府|办公室|财政局|国资委|管委会))\s*\n?\s*(\d+(?:\.\d+)?)\s*%',
            ]
            for pattern in table_patterns:
                matches = re.finditer(pattern, controlling_text, re.DOTALL)
                for match in matches:
                    # 处理不同模式的捕获组
                    if len(match.groups()) == 3:
                        # 模式3有三个捕获组：发行人、股东、比例
                        company = clean_company_name(match.group(2))
                        ratio = match.group(3).strip()
                    else:
                        company = clean_company_name(match.group(1))
                        ratio = match.group(2).strip() if len(match.groups()) > 1 else None

                    if is_valid_company_name(company):
                        if not any(h[0] == company for h in all_holders):
                            all_holders.append((company, ratio))
                            break  # 找到有效匹配就停止
                if all_holders:
                    break

        # 6. 构建股权架构图
        if all_holders:
            lines.append("```")
            lines.append("股权架构:")
            lines.append("")

            # 清理公司名称
            cleaned_holders = []
            for company, ratio in all_holders:
                company = clean_company_name(company)
                # 额外清理：移除时间相关词汇
                company = re.sub(r'截至.*$', '', company)
                company = re.sub(r'发行人的股权结构.*$', '', company)
                company = company.strip()
                if company and is_valid_company_name(company):
                    cleaned_holders.append((company, ratio))

            if not cleaned_holders:
                return "（待提取）"

            # 去重并保持顺序（增强：处理公司名缩写）
            def is_duplicate(new_company, existing_holders):
                """检查是否已存在相同或缩写形式的公司"""
                new_short = re.sub(r'(有限公司|有限责任公司|股份有限公司|集团有限公司)$', '', new_company)
                for existing, _ in existing_holders:
                    existing_short = re.sub(r'(有限公司|有限责任公司|股份有限公司|集团有限公司)$', '', existing)
                    # 完全匹配或缩写匹配
                    if new_company == existing or new_short == existing_short:
                        return True
                    # 一个包含另一个（如"鹤壁投资集团" vs "鹤壁投资集团有限公司"）
                    if new_short in existing_short or existing_short in new_short:
                        return True
                return False

            seen = set()
            unique_holders = []
            for company, ratio in cleaned_holders:
                if company not in seen and not is_duplicate(company, unique_holders):
                    seen.add(company)
                    unique_holders.append((company, ratio))

            # 反转列表，使得最高层级（最终控制人）在最上面
            unique_holders.reverse()

            for i, (company, ratio) in enumerate(unique_holders[:5]):  # 最多显示5层
                ratio_str = f" ({ratio}%)" if ratio else ""
                prefix = "┌─" if i == 0 else "├─"
                lines.append(f"{prefix} {company}{ratio_str}")

                if i < len(unique_holders) - 1:
                    lines.append("│")
                    lines.append("▼")

            lines.append("│")
            lines.append("▼")
            lines.append(f"└─ {issuer_name}")
            lines.append("```")
            return '\n'.join(lines)

        return "（待提取）"

    def _extract_equity_from_section_four(self) -> str:
        """
        当找不到"三、股权结构"时，从"第四节 发行人基本情况"直接提取股权信息
        这是备选方案，用于处理那些没有独立"三、股权结构"章节的募集说明书
        """
        self.extract_text()

        # 查找"第四节 发行人基本情况"章节 - 在整个文档中搜索
        section_patterns = [
            "第四节 发行人基本情况",
            "第四节发行人基本情况",
            "四、发行人基本情况",
            "四、发行人概况",
            "第四节\n发行人基本情况",
        ]

        section_start_idx = -1
        matched_pattern = ""
        for pattern in section_patterns:
            idx = self.full_text.find(pattern)
            if idx >= 0:
                # 检查是否是目录行（后面有很多点号）
                context = self.full_text[idx:idx + 200]
                if '....' in context and context.count('.') > 20:
                    # 可能是目录，跳过，继续查找
                    idx2 = self.full_text.find(pattern, idx + len(pattern))
                    if idx2 >= 0:
                        section_start_idx = idx2
                        matched_pattern = pattern
                        break
                else:
                    section_start_idx = idx
                    matched_pattern = pattern
                    break

        if section_start_idx < 0:
            return "（待提取）"

        # 找到第四节结束的位置（第五节开始）
        end_patterns = ["第五节", "五、", "第六节", "第五节 发行人主要财务情况"]
        section_end_idx = len(self.full_text)
        for pattern in end_patterns:
            idx = self.full_text.find(pattern, section_start_idx + 50)
            if idx > section_start_idx:
                section_end_idx = min(section_end_idx, idx)

        section_text = self.full_text[section_start_idx:section_end_idx]

        if len(section_text.strip()) < 100:
            return "（待提取）"

        # 清理文本
        processed_text = re.sub(r'<[^>]+>', '\n', section_text)
        processed_text = re.sub(r'\n\s*\n', '\n', processed_text)

        # 处理逐字换行格式：合并被换行分割的连续中文字符
        processed_text = self._merge_char_newlines(processed_text)

        # 查找"二、"或"（二）"开头的控股股东/实际控制人部分
        controlling_patterns = [
            r'(?:二|2)[、\.\s]+.*?股权结构',
            r'(?:二|2)[、\.\s]+.*?控股股东',
            r'（二）.*?股权结构',
            r'（二）.*?控股股东',
            r'\(二\).*?股权结构',
            r'\(二\).*?控股股东',
            r'(?:三|3)[、\.\s]+.*?股权结构',
            r'（三）.*?股权结构',
            r'三、发行人的股权结构',
            r'三、发行人股权结构',
            r'三、发行人控股股东',
        ]

        controlling_start_idx = -1
        for pattern in controlling_patterns:
            match = re.search(pattern, processed_text)
            if match:
                controlling_start_idx = match.start()
                break

        if controlling_start_idx < 0:
            # 如果没找到特定小节，在整个第四节中查找控股股东信息
            return self._extract_equity_structure_from_controlling_shareholder(processed_text)

        # 找到小节结束的位置
        subsection_end_patterns = [
            r'(?:三|3)[、\.\s]+',
            r'（三）',
            r'\(三\)',
            r'四、',
        ]
        controlling_end_idx = len(processed_text)
        for pattern in subsection_end_patterns:
            match = re.search(pattern, processed_text[controlling_start_idx + 50:])
            if match:
                controlling_end_idx = controlling_start_idx + 50 + match.start()
                break

        controlling_text = processed_text[controlling_start_idx:controlling_end_idx]
        return self._extract_equity_structure_from_controlling_shareholder(controlling_text)

    # ===== task 64：完整股权结构提取（文字陈述 + 股东表 + 股权结构图） =====
    # 机构名后缀（长的放前面，避免"公司"截断"有限公司"）
    _EQ_SUFFIX = (
        r'(?:国有资产监督管理委员会|国有资产监督管理办公室|国有资产监督管理局|'
        r'政府国有资产监督管理委员会|新区管理委员会|高新技术产业开发区管理委员会|'
        r'经济技术开发区管理委员会|管理委员会|监督管理委员会|'
        r'国有资产运营服务中心|国有资产事务中心|国有资产管理服务中心|'
        r'集团有限公司|股份有限公司|有限责任公司|有限公司|'
        r'管委会|国资委|国资办|国资局|财政局|国资运营中心|人民政府|政府|委员会|'
        r'街道办事处|办事处|集团|公司|中心|办公室|局)'
    )

    def _extract_equity_chain_complete(self, section_text: str) -> str:
        """
        完整股权结构提取（task 64）：综合三类信息重建完整股权链条
          1) 文字陈述："X 持有发行人Y%的股权，为发行人控股股东"、"实际控制人为Z"
          2) 股东表（股东名称 / 认缴出资额 / 持股比例）
          3) 股权结构图（PDF 文本层中的图形文字，按阅读顺序取实体名与比例）
        输出多层级"股权架构"代码块；提取失败返回"（待提取）"。
        """
        issuer = self._issuer_name or "发行人"
        if not section_text or len(section_text.strip()) < 30:
            return "（待提取）"

        txt = re.sub(r'<[^>]+>', '\n', section_text)
        try:
            txt = self._merge_char_newlines(txt)
        except Exception:
            pass

        # 合并被分栏/换行拆断的机构名（未闭合全角括号续行，
        # 如"深圳市龙华区财政局（区国有资产"+"监督管理局、区集体资产管理局）"）
        lines = []
        buf = ""
        skip_issuer_line = False
        for raw in txt.split('\n'):
            ls = raw.strip()
            if not ls:
                continue
            # 过滤页眉页脚（"……公司债券（第一期）募集说明书"+单独页码），避免跨页处把
            # 机构名切断（如"黄石市人民政府国有资产" + 页眉 + "监督管理委员会"）；
            # 正文行（如"截至本募集说明书签署日，X公司"）不含"债券/第X期"，不会被丢弃
            if '募集说明书' in ls and ('债券' in ls or re.search(r'第[一二三四五六七八九十\d]+期', ls)):
                # 页眉块首行/次行常为发行人全称，一并丢弃
                if lines and (lines[-1] == issuer
                              or (issuer and len(lines[-1]) < 40 and issuer in lines[-1])):
                    lines.pop()
                skip_issuer_line = True
                continue
            if re.fullmatch(r'\d{1,4}', ls):
                continue
            if skip_issuer_line:
                skip_issuer_line = False
                if ls == issuer or (issuer and len(ls) < 40 and issuer in ls):
                    continue
            if buf:
                ls = buf + ls
                buf = ""
            if ls.count('（') > ls.count('）'):
                buf = ls
                continue
            lines.append(ls)
        if buf:
            lines.append(buf)

        flat = re.sub(r'\s+', '', '\n'.join(lines))  # 无空白版本（名字跨行已合并）
        SUF = self._EQ_SUFFIX
        # 贪婪前缀：一次匹配整个机构名（含"淮北市人民政府国有资产监督管理委员会"这类叠加后缀）；
        # 字符类含顿号、全角括号，并允许名称以"）"收尾（如"…财政局（区国资…局）"）
        NAME = r'([\u4e00-\u9fa5（）()·、]{2,50}' + SUF + r'）?)'
        name_re = re.compile(NAME)

        JUNK_PREFIX = re.compile(
            r'^.*(?:的控股股东|控股股东|实际控制人|的股东|股东|变更为|成为|出资人由|'
            r'基本情况|情况如下|如下所示|截至|签署日|报告期末|报告期|股权结构图|股权结构|'
            r'因此|同时|此外|另外|其中|因|故|而|则|其)'
        )
        # 前置括号块（如经营范围括号、授权说明括号）不是名称的一部分
        LEAD_PAREN = re.compile(r'^[（(][^）)]{0,80}[）)]')

        def clean_name(nm):
            nm = (nm or '').strip()
            # 去掉前文修饰语/章节标题残留，只保留机构名本身
            nm = JUNK_PREFIX.sub('', nm)
            nm = LEAD_PAREN.sub('', nm)
            nm = re.sub(r'[（(][^）)]*以下简称[^）)]*[）)]', '', nm)
            nm = re.sub(r'[（(][^）)]*简称[^）)]*[）)]', '', nm)
            nm = re.sub(r'^(?:的|及|和|与|系|为|是|由)+', '', nm)
            nm = nm.strip('，。；、： ')
            # 正文中以"全称（以下简称"简称"）"定义过简称时，用全称替换简称
            if nm and len(nm) <= 15 and len(nm) >= 4:
                am = re.search(r'([\u4e00-\u9fa5（）()]{4,40}?)[（(]以下简称[“"]?'
                               + re.escape(nm) + r'[”"]?[）)]', flat)
                if am and valid_name(am.group(1)):
                    nm = am.group(1)
            return nm.strip('，。；、： ')

        def norm_ratio(r):
            """比例合法性校验：0<v<=100，否则视为无效（避免把年份/金额当比例）"""
            if not r:
                return None
            s = str(r).strip().rstrip('%').replace(',', '')
            try:
                v = float(s)
            except ValueError:
                return None
            if v <= 0 or v > 100:
                return None
            return s

        def valid_name(nm):
            if not nm or not (6 <= len(nm) <= 60):
                return False
            if re.fullmatch(SUF, nm):
                return False  # 只有后缀（如"有限公司"）不是有效名称
            # 名称必须以机构后缀结尾（可带收尾括号），避免句子碎片（如"…集团成立于"）
            if not re.search(SUF + r'）?$', nm):
                return False
            if not re.search(r'[\u4e00-\u9fa5]{2,}', re.sub(SUF + r'）?$', '', nm)):
                return False
            if any(k in nm for k in ('依法须经批准', '营业执照', '经营范围', '经营项目',
                                     '募集说明书', '债券', '非公开发行', '发行人', '本公司',
                                     '公司债', '本次')):
                return False
            if re.search(r'\d', nm):
                return False
            if re.search(r'变更为|成为|持有|控股股东|实际控制|出资', nm):
                return False
            return True

        def norm_key(nm):
            k = re.sub(r'[（(].*?[）)]', '', nm or '')
            k = re.sub(r'(?:集团)?有限公司$|有限责任公司$|股份有限公司$|有限公司$|集团$|公司$', '', k)
            return k.strip()

        def same_entity(a, b):
            """机构同一性判断：去除组织形式后缀后比较。
            允许"后缀包含"（如"费县国有资产管理服务中心"与"山东省临沂市费县
            国有资产管理服务中心"为同一机构，前者是后者后缀），
            但不能用"前缀包含"——否则发行人"XX市文化旅游股份有限公司"会被误判
            为股东"XX市文化旅游投资集团有限公司"（task 64）。"""
            ka, kb = norm_key(a), norm_key(b)
            if not ka or not kb:
                return False
            if ka == kb:
                return True
            if len(ka) >= 6 and len(kb) >= 6:
                if kb.endswith(ka) or ka.endswith(kb):
                    return True
            return False

        def is_issuer(nm):
            """是否为发行人自身（含名称被前缀污染的情况，如"深圳市深圳市福田…公司公司"）"""
            if same_entity(nm, issuer):
                return True
            iss = issuer or ""
            if len(iss) >= 6 and iss in (nm or ""):
                return True
            return False

        holders = []  # [(name, ratio or None)] 直接股东（按出现顺序）
        holder_pos = {}  # {name: 首次出现位置}，用于剔除报告期内历史股东

        holder_trace = []

        def push_holder(nm, ratio, src='', pos=-1):
            raw = nm
            nm = clean_name(nm)
            ok = valid_name(nm)
            if os.environ.get('EQ_DEBUG'):
                holder_trace.append((src, raw, nm, ratio, ok))
            if not ok:
                return
            if is_issuer(nm):
                return  # 表格/图里的发行人自身不是持股股东
            ratio = norm_ratio(ratio)
            for i, (ex, r) in enumerate(holders):
                if same_entity(nm, ex):
                    if ratio and not r:
                        holders[i] = (ex, ratio)
                    return
            if pos >= 0:
                holder_pos[nm] = pos
            holders.append((nm, ratio))

        # ---------- 1) 文字陈述：持股比例 ----------
        hold_pats = [
            # X（以下简称"XX"）持有发行人/公司 Y% 的股权
            # （中间允许"股权比例为/的股权为"等少量措辞；bridge 用于排除
            #  "X持有Y公司100%股权"这类对上层母公司的持股陈述）
            re.compile(NAME + r'\s*(?:（[^）]{0,30}）)?\s*(?:直接|合计|间接)?(?:持有|持股)\s*'
                       r'([^。；，]{0,12}?)\s*([\d,]+(?:\.\d+)?)\s*%'),
            # 控股股东（及实际控制人）为 X，持有发行人 Y%
            re.compile(r'(?:发行人|公司)(?:的)?控股股东(?:(?:及|和)实际控制人)?\s*(?:为|是|系)\s*[^。；，]{0,15}?'
                       + NAME + r'[^。；]{0,60}?([\d,]+(?:\.\d+)?)\s*%'),
            # X 系/为/是 发行人控股股东，持有 Y%
            re.compile(NAME + r'\s*(?:系|为|是)\s*(?:发行人|公司)(?:的)?控股股东[^。；]{0,60}?([\d,]+(?:\.\d+)?)\s*%'),
        ]
        # pattern 0 的捕获组为 (名称, 桥接文本, 比例)；其余为 (名称, 比例)
        for pi, pat in enumerate(hold_pats):
            for mm in pat.finditer(flat):
                if pi == 0:
                    nm_c, bridge, ratio_c = mm.group(1), mm.group(2), mm.group(3)
                else:
                    nm_c, bridge, ratio_c = mm.group(1), '', mm.group(2)
                seg = mm.group(0)
                # "间接持有公司X%，为公司实际控制人"属于控制人层级（task 64），
                # 不作为直接股东
                if '间接' in seg or '实际控制人' in seg:
                    continue
                # 仅接受"对发行人本体的直接持股"陈述：桥接文本必须是泛指的
                # 发行人/公司/股权/比例等措辞（白名单）。出现其它机构名
                #（"X持有Y公司100%股权"）或代词（"X持有其100%股权"，其指上层
                # 母公司）时，属于上层持股陈述，不作为直接股东。
                if bridge and not re.fullmatch(
                        r'(?:发行人|公司|本公司|标的公司)?(?:的)?(?:股权|股份)?(?:比例)?(?:为)?',
                        bridge):
                    continue
                push_holder(nm_c, ratio_c, src=f'hold{pi}', pos=mm.start())

        # ---------- 2) 文字陈述：控股股东（可能无比例） ----------
        holder_only_pats = [
            # task 64：允许"控股股东和实际控制人均为X"这类"均/皆"插入语
            re.compile(r'(?:发行人|公司)(?:的)?控股股东(?:(?:及|和)实际控制人)?\s*(?:均|皆)?\s*'
                       r'(?:为|是|系)\s*[^。；，]{0,15}?' + NAME),
            re.compile(NAME + r'\s*(?:均|皆)?\s*(?:系|为|是)\s*(?:发行人|公司)(?:的)?控股股东'),
        ]
        for pat in holder_only_pats:
            for mm in pat.finditer(flat):
                seg = mm.group(0)
                if '实际控制人' in seg and '控股股东' not in seg:
                    continue
                push_holder(mm.group(1), None, src=f'only{holder_only_pats.index(pat)}', pos=mm.start())

        # ---------- 3) 文字陈述：实际控制人（含间接持股比例） ----------
        controller = None
        controller_ratio = None
        controller_indirect = False
        # 3a) 带比例的实控人："X（间接）持有公司Y%股权，为公司实际控制人"
        # 组：(1)名称 (2)直接/间接 (3)发行人代词 (4)中间主体 (5)比例
        ctrl_ratio_pats = [
            re.compile(NAME + r'\s*(直接|间接)?持有(?:(发行人|公司|标的公司))?'
                       r'([^。；，]{0,45}?)([\d,]+(?:\.\d+)?)\s*%'
                       r'[^。；]{0,40}?(?:均|皆)?(?:为|是|系)[^。；]{0,8}实际控制人'),
            # task 64："X通过持有Y公司A%的股权，实现对发行人的实际控制"
            re.compile(NAME + r'\s*(直接|间接)?[^。；，]{0,10}?持有(?:(发行人|公司|标的公司))?'
                       r'([^。；，]{0,45}?)([\d,]+(?:\.\d+)?)\s*%[^。；]{0,60}?'
                       r'(?:均|皆)?(?:为|是|系)[^。；]{0,8}实际控制人'),
        ]
        for pat in ctrl_ratio_pats:
            for mm in pat.finditer(flat):
                nm = clean_name(mm.group(1))
                if os.environ.get('EQ_DEBUG'):
                    print(f"[EQ_DEBUG] ctrl: {mm.group(1)!r} mid={(mm.group(4) or '')!r} "
                          f"ratio={mm.group(5)!r} seg={mm.group(0)!r}")
                if valid_name(nm):
                    mid = clean_name(mm.group(4) or '')
                    ratio = mm.group(5)
                    tail = mm.group(0)[mm.end(5) - mm.start(0):]
                    # "…持有发行人100%的股权，为发行人的控股股东，发行人实际控制人为X"：
                    # 该句的持有主体是控股股东而非实际控制人，整句跳过（如怀集县锦鹏）
                    if re.search(r'(?:为|是|系)[^。；，]{0,8}?控股股东', tail):
                        continue
                    # "…因此，安吉县财政局（…办公室）为发行人的实际控制人"：
                    # 句中另起了实际控制人的主语，持有主体并非实际控制人，跳过
                    if re.search(SUF + r'）?[，,]?(?:均|皆)?(?:为|是|系)[^。；]{0,8}实际控制人', tail):
                        continue
                    # 比例若指向链外的中间主体（如"通过持有扬子国资100%股权实现对…实际控制"），
                    # 不能当作对下一层的持股标注，仅保留控制人名称
                    if mid and not any(same_entity(mid, h[0]) for h in holders):
                        ratio = None
                    controller = nm
                    controller_indirect = (mm.group(2) == '间接')
                    controller_ratio = ratio
                    break
            if controller:
                break
        # 3b) 无比例的实控人（允许省略主语，如"，实际控制人为X"）
        if not controller:
            ctrl_pats = [
                re.compile(r'(?:发行人|公司)?(?:的)?实际控制人\s*(?:均|皆)?\s*(?:为|是|系)\s*[^。；]{0,10}?' + NAME),
                re.compile(NAME + r'\s*(?:均|皆)?\s*(?:系|为|是)\s*(?:发行人|公司)(?:的)?实际控制人'),
            ]
            for pat in ctrl_pats:
                for mm in pat.finditer(flat):
                    nm = clean_name(mm.group(1))
                    if valid_name(nm):
                        controller = nm
                        break
                if controller:
                    break

        # ---------- 4) 股东表（股东名称 / 出资额 / 持股比例） ----------
        if len(holders) < 2:
            for i, l in enumerate(lines):
                if ('股东名称' in l) or ('股东' in l and re.search(r'(持股比例|出资比例|股权占比)', l)):
                    j = i + 1
                    guard = 0
                    while j < len(lines) and guard < 10 and (
                            lines[j] in ('序号', '股东名称', '认缴出资额', '实缴出资额', '持股比例',
                                         '出资额', '股权占比', '股权比例', '认缴出资', '实收资本',
                                         '注册资本', '%', '（%）', '（万元）')
                            or re.fullmatch(r'[\d,]+(?:\.\d+)?%?', lines[j] or '')):
                        j += 1
                        guard += 1
                    while j < len(lines) and '合计' not in lines[j]:
                        nm = lines[j]
                        if len(nm) >= 4 and not re.search(r'\d', nm) \
                                and re.search(SUF + r'）?$', nm) \
                                and not re.search(r'如下|所示|单位|成立于|年度|年末|关于', nm):
                            nums = []
                            k = j + 1
                            while k < len(lines) and len(nums) < 6 and \
                                    re.fullmatch(r'[\d,]+(?:\.\d+)?%?', lines[k] or ''):
                                nums.append(lines[k].rstrip('%'))
                                k += 1
                            if nums:
                                push_holder(nm, nums[-1], src='table')
                                j = k
                                continue
                        j += 1

        # ---------- 5) 股权结构图（文本层图形文字） ----------
        diagram = []  # [(name, ratio or None)] 自上而下
        try:
            seg_start = -1
            for m in re.finditer(r'股权结构图|股权结构如下|股权结构如右', txt):
                seg_start = m.end()
            if seg_start >= 0:
                seg = txt[seg_start:seg_start + 1800]
                seg = seg.split('（二）')[0].split('(二)')[0].split('四、')[0]
                for raw in seg.split('\n'):
                    ls = raw.strip()
                    if not ls:
                        continue
                    if re.fullmatch(r'[\d,]+(?:\.\d+)?%', ls):
                        # 比例文字紧跟其上方实体 → 归属上一个实体
                        if diagram and diagram[-1][1] is None:
                            diagram[-1] = (diagram[-1][0], ls.rstrip('%'))
                        continue
                    if re.search(SUF, ls) and len(ls) <= 45 and not re.search(r'\d', ls) \
                            and not re.search(r'如下|所示|图[:：]|表[:：]|单位', ls):
                        nm = clean_name(ls)
                        if valid_name(nm):
                            diagram.append((nm, None))
        except Exception:
            diagram = []

        # ---------- 5.5) 剔除历史股东（报告期内被更名/划转/变更的主体） ----------
        # 出现在正文后段的股东若处在"变更为/原控股股东/无偿划转"等变更语境中，
        # 属于报告期内已退出的历史股东，不应计入当前股权结构（如泰州凤城）。
        if len(holders) > 1 and holder_pos:
            first_pos = min(holder_pos.values())
            kept_holders = []
            for nm, ratio in holders:
                pos = holder_pos.get(nm, first_pos)
                if pos > first_pos + 300:
                    ctx = flat[max(0, pos - 120): pos + 120]
                    if re.search(r'变更为|原控股股东|更名为|无偿划转|转让给|受让|变更为发行人', ctx):
                        if os.environ.get('EQ_DEBUG'):
                            print(f"[EQ_DEBUG] 剔除历史股东: {nm!r} @{pos}")
                        continue
                kept_holders.append((nm, ratio))
            holders = kept_holders

        # ---------- 6) 组装链条（按层级渲染） ----------
        if not holders and diagram:
            for nm, ratio in diagram:
                if is_issuer(nm):
                    continue
                if not any(same_entity(nm, h[0]) for h in holders):
                    holders.append((nm, ratio))

        if os.environ.get('EQ_DEBUG'):
            print(f"[EQ_DEBUG] holders={holders!r} controller={controller!r} "
                  f"ctrl_ratio={controller_ratio!r} indirect={controller_indirect} "
                  f"diagram={diagram!r}")
            k = flat.find('控股股东为')
            if k < 0:
                k = flat.find('控股股东')
            print(f"[EQ_DEBUG] flat片段: {flat[k:k + 120]!r}")
            for kw in ('实际控制人为', '实际控制人均为'):
                k2 = flat.find(kw)
                if k2 >= 0:
                    print(f"[EQ_DEBUG] ctrl片段: {flat[k2:k2 + 60]!r}")
                    break
            print(f"[EQ_DEBUG] push轨迹: {holder_trace!r}")

        # 实际控制人若同时被正文表述为"持有发行人100%股权"的直接股东，
        # 且还存在其他直接股东，说明其系通过该股东间接持股：提升为最上层，
        # 不与其他直接股东并列（如抚州高新区智城）。
        if controller and valid_name(controller) and len(holders) > 1:
            rest = [(nm, r) for nm, r in holders if not same_entity(nm, controller)]
            if rest:
                holders = rest

        if not holders:
            return "（待提取）"

        # 实际控制人补到最上层（与直接股东不同、且非发行人本身时）
        levels = []  # [[(name, ratio_str), ...], ...] 自上而下
        if controller and valid_name(controller) and not is_issuer(controller):
            if not any(same_entity(controller, h[0]) for h in holders):
                ctrl_label = f"间接 {controller_ratio}" if (controller_indirect and controller_ratio) \
                    else (controller_ratio if controller_ratio else None)
                levels.append([(controller, ctrl_label)])
        levels.append(list(holders))

        out = ["```", "股权架构:", ""]
        first = True
        for lvl in levels:
            for i, (nm, ratio) in enumerate(lvl):
                prefix = "┌─" if first else "├─"
                first = False
                rs = f" ({ratio}%)" if ratio else ""
                out.append(f"{prefix} {nm}{rs}")
            out.append("│")
            out.append("▼")
        out.append(f"└─ {issuer}")
        out.append("```")
        return '\n'.join(out)

    def _extract_equity_structure_within_section(self) -> str:
        """
        从"三、发行人的股权结构"章节中精确提取股权结构
        将股权结构以架构图形式展示。如果检测到图片，则尝试从控股股东部分提取
        """
        self.extract_text()

        # 预处理文本：移除HTML标签但保留换行，便于章节定位
        processed_text = re.sub(r'<[^>]+>', '\n', self.full_text)
        processed_text = re.sub(r'\n\s*\n', '\n', processed_text)

        # 首先找到"三、发行人的股权结构"的位置（跳过目录引用）
        section_start_patterns = [
            "三、发行人的股权结构",
            "三、发行人股权结构",
            "三、 发行人的股权结构",
            "三、股权结构",
            "（三）股权结构",
            "三、发行人控股股东及实际控制人情况",
            "三、控股股东及实际控制人情况",
            # task 64：更多章节标题变体
            "三、发行人控股股东及实际控制人的基本情况",
            "三、发行人控股股东和实际控制人情况",
            "三、发行人控股股东、实际控制人情况",
            "二、发行人股权结构",
            "二、发行人的股权结构",
            "四、发行人股权结构",
            "发行人股权结构及实际控制人情况",
        ]
        section_start_idx = -1

        for pattern in section_start_patterns:
            idx = -1
            while True:
                idx = processed_text.find(pattern, idx + 1)
                if idx < 0:
                    break

                # 检查是否是目录条目（后面紧跟很多点号表示页码）
                next_chars = processed_text[idx:idx + 200]
                # 目录特征1：点号后跟数字页码（如"............ 44"）
                has_page_number = re.search(r'\.{4,}\s*\d+\s*$', next_chars[:150])
                # 目录特征2：紧跟在标题后就是大量点号（TOC 行特征）
                title_len = len(pattern)
                after_title = next_chars[title_len:title_len + 50]
                has_dots_immediate = after_title.strip().startswith('...') or after_title.lstrip('\n').strip().startswith('.')
                # 目录特征3：有很多点号但没有"（一）"子章节
                has_dots_no_content = next_chars.count('.') > 30 and '（一）' not in next_chars[:200]
                # 目录特征4：直接出现其他章节标题（如"四、"）
                has_next_section_early = re.search(r'[三四五六七八九][、\.\s]+', next_chars[30:100])
                # 目录特征5：在"三、发行人的股权结构"后紧跟"四、"或其他章节
                is_toc = has_page_number or has_dots_immediate or has_dots_no_content or \
                         (has_next_section_early and '（一）' not in next_chars[:150])

                if is_toc:
                    continue

                # 进一步检查：实际内容应该包含"（一）"或"截至"等关键词
                context = processed_text[idx:idx + 400]
                has_subsection = '（一）' in context or '(一)' in context
                has_keyword = '截至' in context or '股权结构图' in context or '控股股东' in context
                if not has_subsection and not has_keyword:
                    # 可能是目录，继续查找
                    continue

                section_start_idx = idx
                break
            if section_start_idx >= 0:
                break

        if section_start_idx < 0:
            # 找不到编号章节标题时（task 64），退化为"（一）股权结构"锚点定位
            anchor = -1
            for m in re.finditer(r'[（(][一二][)）]\s*(?:发行人)?股权结构', processed_text):
                ctx = processed_text[m.start():m.start() + 300]
                if '....' in ctx[:200] or re.search(r'\.{4,}\s*\d+', ctx[:200]):
                    continue  # 目录行
                anchor = m.start()
                break
            if anchor >= 0:
                section_start_idx = anchor
            else:
                # 最后尝试从第四节直接提取
                return self._extract_equity_from_section_four()

        # 找到"三、"的结束位置
        section_end_patterns = [
            "四、发行人主要子公司情况",
            "四、发行人权益投资情况",
            "四、发行人重要权益投资情况",
            "四、发行人",
            "四、",
            "第五节",
            "第六节",
        ]
        section_end_idx = len(processed_text)
        for pattern in section_end_patterns:
            idx = processed_text.find(pattern, section_start_idx + 20)
            if idx > section_start_idx:
                section_end_idx = min(section_end_idx, idx)

        section_text = processed_text[section_start_idx:section_end_idx]

        if len(section_text.strip()) < 30:
            return "（待提取）"

        # task 64：优先用"完整股权链"提取（文字陈述 + 股东表 + 股权结构图），
        # 成功则直接返回；失败时回落到原有单层持股提取逻辑
        try:
            complete_chain = self._extract_equity_chain_complete(section_text)
            if complete_chain and complete_chain != "（待提取）":
                return complete_chain
        except Exception as e:
            print(f"  完整股权链提取失败，回退旧逻辑: {e}")

        # 在章节内精确定位"（一）股权结构"
        equity_start_patterns = [
            "（一）股权结构",
            "（一） 股权结构",
            "一）股权结构",
            "1、股权结构",
            "1.股权结构",
            "（一）发行人的股权结构",
        ]
        equity_start_idx = -1

        for pattern in equity_start_patterns:
            idx = section_text.find(pattern)
            if idx >= 0:
                equity_start_idx = idx + len(pattern)
                break

        if equity_start_idx < 0:
            # 如果没有找到（一），尝试从控股股东部分提取
            return self._extract_equity_structure_from_controlling_shareholder(section_text)

        # 找到"（一）"的结束位置（"（二）"开始）
        equity_end_patterns = [
            "（二）",
            "(二)",
            "四、",
            "第二节",
        ]
        equity_end_idx = len(section_text)
        for pattern in equity_end_patterns:
            idx = section_text.find(pattern, equity_start_idx)
            if idx > equity_start_idx:
                equity_end_idx = min(equity_end_idx, idx)

        equity_text = section_text[equity_start_idx:equity_end_idx]

        # 如果没有提取到有效的股权信息或检测到图片引用，尝试从控股股东部分提取
        if len(equity_text.strip()) < 30 or '股权结构图' in equity_text or '如下' in equity_text[:100] or '所示' in equity_text[:100]:
            # 先尝试从控股股东部分提取
            controlling_result = self._extract_equity_structure_from_controlling_shareholder(section_text)
            if controlling_result and controlling_result != "（待提取）":
                return controlling_result

            # 如果控股股东提取失败，尝试OCR识别
            try:
                ocr_result = self._try_ocr_for_equity(section_start_idx, section_end_idx)
                if ocr_result:
                    return ocr_result
            except Exception as e:
                print(f"  OCR识别失败: {e}")

            # OCR失败，再次尝试控股股东提取
            return self._extract_equity_structure_from_controlling_shareholder(section_text)

        return self._format_equity_structure_diagram(equity_text)

    def _format_equity_structure_diagram(self, text: str) -> str:
        """解析股权结构文本，格式化为架构图形式"""
        if not text or len(text.strip()) < 10:
            return "（待提取）"

        lines = []
        issuer_name = self._issuer_name or "发行人"

        # 清理文本 - 先移除页码和目录标记
        text = re.sub(r'\.{3,}\s*\d+\s*$', '', text, flags=re.MULTILINE)
        text = re.sub(r'\.+\s*\d+', '', text)

        # 提取截至日期
        date_patterns = [
            r'截至\s*报告期末',
            r'截至\s*募集说明书签署之日?',
            r'截至\s*\d{4}\s*年\s*\d{1,2}\s*月\s*\d{1,2}\s*日',
            r'截至[^，。\n]{0,20}?[，。\n]',
        ]
        date_found = False
        for pattern in date_patterns:
            date_match = re.search(pattern, text)
            if date_match:
                date_str = date_match.group(0).strip()
                if len(date_str) > 3 and not date_str.endswith('（'):
                    lines.append(f"**{date_str}**")
                    lines.append("")
                    date_found = True
                    break

        # 清理文本
        text = re.sub(r'图[：:]?\s*发行人股权结构图', '', text)

        # 移除标题部分
        header_match = re.search(r'(截至[^\n]*股权结构图[^\n]*[:：])', text)
        if header_match:
            text = text[header_match.end():]

        # 清理行 - 过滤页眉页脚
        lines_clean = []
        for line in text.split('\n'):
            line = line.strip()
            if '募集说明书' in line and len(line) > 20:
                continue
            if re.match(r'^\s*\d+\s*$', line):
                continue
            if re.search(r'\d{4}年.*债券.*第.*期', line):
                continue
            if re.match(r'^[\d,\.]+$', line.replace(' ', '')):
                continue
            if line:
                lines_clean.append(line)

        # 提取持股比例
        ratios = re.findall(r'(\d+(?:\.\d+)?)\s*%', text)

        # 提取股东名称 - 更严格的过滤
        holder_candidates = []
        for line in lines_clean[:25]:
            # 跳过发行人自身
            if issuer_name in line and len(line) < len(issuer_name) + 15:
                continue
            # 跳过包含特定关键词的行
            if any(x in line for x in ['股票代码', '债券代码', '简称', '第', '期',
                                       '为发行人', '控股股东', '实际控制人', '持有发行人',
                                       '的股权', '以下简称', '募集说明书']):
                continue
            # 必须是看起来像公司名的行
            if not any(kw in line for kw in ['公司', '办公室', '财政局', '国资委',
                                              '政府', '集团', '控股', '中心', '委员会']):
                continue
            # 长度要合理（4-50字符）
            name = line.strip()
            if not (4 <= len(name) <= 50):
                continue
            # 不能包含多个公司名关键词（避免多行合并后的行）
            company_count = sum(1 for kw in ['有限公司', '集团', '控股', '公司'] if kw in name)
            if company_count > 2:
                continue
            # 不能包含多个百分比（避免多行合并后的行）
            if name.count('%') > 1:
                continue
            # 排除纯字母或纯数字
            if re.match(r'^[a-zA-Z0-9\s]+$', name):
                continue
            holder_candidates.append(name)

        # 去重
        holder_candidates = list(dict.fromkeys(holder_candidates))

        # 生成架构图
        if holder_candidates or ratios:
            lines.append("```")
            lines.append("股权架构:")
            lines.append("")

            if len(holder_candidates) == 1 and ratios:
                lines.append(f"┌─ {holder_candidates[0]} ({ratios[0]}%)")
                lines.append(f"│")
                lines.append(f"▼")
                lines.append(f"└─ {issuer_name}")
            elif len(holder_candidates) >= 2 and ratios:
                for i, holder in enumerate(holder_candidates[:3]):
                    ratio = ratios[i] if i < len(ratios) else "?"
                    prefix = "┌─" if i == 0 else "├─"
                    lines.append(f"{prefix} {holder} ({ratio}%)")
                lines.append(f"│")
                lines.append(f"▼")
                lines.append(f"└─ {issuer_name}")
            elif len(holder_candidates) == 1:
                lines.append(f"┌─ {holder_candidates[0]}")
                lines.append(f"│")
                lines.append(f"▼")
                lines.append(f"└─ {issuer_name}")
            elif len(holder_candidates) >= 2:
                for i, holder in enumerate(holder_candidates[:3]):
                    prefix = "┌─" if i == 0 else "├─"
                    lines.append(f"{prefix} {holder}")
                lines.append(f"│")
                lines.append(f"▼")
                lines.append(f"└─ {issuer_name}")
            elif ratios:
                for i, ratio in enumerate(ratios[:3]):
                    prefix = "┌─" if i == 0 else "├─"
                    lines.append(f"{prefix} 股东{i+1} ({ratio}%)")
                lines.append(f"│")
                lines.append(f"▼")
                lines.append(f"└─ {issuer_name}")

            lines.append("```")
        else:
            # 如果没有提取到任何有效信息，返回待提取
            return "（待提取）"

        return '\n'.join(lines)

    def _try_ocr_for_equity(self, section_start: int, section_end: int) -> str:
        """尝试使用PaddleOCR从股权结构章节的图片中识别股权架构"""
        # 计算页码范围（估算）
        chars_per_page = 3000
        start_page = section_start // chars_per_page
        end_page = section_end // chars_per_page + 1

        # 限制在合理范围内
        doc = fitz.open(self.pdf_path)
        total_pages = len(doc)
        doc.close()

        start_page = max(0, start_page)
        end_page = min(total_pages, end_page + 2)

        issuer_name = self._issuer_name or "发行人"

        # 使用PaddleOCR识别
        try:
            print(f"  尝试使用PaddleOCR识别股权架构图片...")
            paddle_ocr = EquityPaddleOCR(use_gpu=False)
            result = paddle_ocr.find_and_recognize_equity_images(
                self.pdf_path,
                issuer_name,
                (start_page, end_page)
            )
            if result and "股权架构" in result:
                print(f"  PaddleOCR识别成功")
                return result
        except ImportError as e:
            print(f"  PaddleOCR未安装，跳过OCR识别: {e}")
        except Exception as e:
            print(f"  PaddleOCR识别失败: {e}")

        return ""

    def extract_issuer_info(self) -> Dict[str, any]:
        """提取发行人基本信息 - 从募集说明书第四节提取"""
        issuer_overview_text = self._extract_section_after(
            "第四节 发行人基本情况",
            self.SECTION_PATTERNS["issuer_overview"]["start"],
            self.SECTION_PATTERNS["issuer_overview"]["end"]
        )

        basic_info = self._extract_basic_info_fields(issuer_overview_text)
        equity_structure = self._extract_equity_structure_within_section()

        return {
            "issuer_overview": issuer_overview_text,
            "basic_info": basic_info,
            "equity_structure": equity_structure
        }

    def _format_basic_info(self, basic_info: Dict[str, str]) -> str:
        """格式化基本信息为列表形式"""
        lines = []
        fields_order = [
            ("注册名称", "注册名称"),
            ("注册资本", "注册资本"),
            ("实缴资本", "实缴资本"),
            ("设立日期", "设立（工商注册）日期"),
            ("经营范围", "经营范围"),
        ]
        for key, label in fields_order:
            value = basic_info.get(key, "")
            if value:
                lines.append(f"- **{label}**：{value}")
            else:
                lines.append(f"- **{label}**：（未提取到）")
        return '\n'.join(lines)

    def generate_note(self, output_base: str) -> str:
        """生成发行人概况笔记"""
        info = {
            "issuer": self._issuer_name,
            "bond_type": self._bond_info.bond_type.value if self._bond_info else "公司债"
        }
        issuer_data = self.extract_issuer_info()
        basic_info = issuer_data.get('basic_info', {})

        frontmatter = self.get_frontmatter(
            note_type=self.NOTE_TYPE,
            tags=self.TAGS + [f"#{info['bond_type']}"],
            extra_fields={
                "issuer": info.get("issuer", ""),
                "bond_type": info.get("bond_type", ""),
            }
        )

        template = f"""{frontmatter}
# {info['issuer']} - 概况

## 基本信息

{self._format_basic_info(basic_info)}

## 股权结构

{issuer_data.get('equity_structure', '（待提取）')}

---
**来源**: {self.pdf_name}
**提取日期**: {datetime.now().strftime('%Y-%m-%d')}
"""

        output_path = os.path.join(
            output_base, self.OUTPUT_DIR,
            f"{info['issuer']}-概况.md"
        )
        self.write_note(output_path, template)
        return output_path


def main():
    """主函数"""
    import argparse

    parser = argparse.ArgumentParser(description="发行人基本情况提取")
    parser.add_argument("--files", nargs="*", default=None,
                        help="指定要处理的PDF文件名（多个用空格隔开），不指定则处理raw/下所有PDF")
    args = parser.parse_args()

    raw_dir = "raw"
    knowledge_dir = "knowledge"

    if args.files:
        pdf_files = [f for f in args.files if f.endswith(".pdf")]
        for f in pdf_files:
            fp = os.path.join(raw_dir, f)
            if not os.path.exists(fp):
                print(f"[警告] 文件不存在，跳过：{fp}")
        pdf_files = [f for f in pdf_files if os.path.exists(os.path.join(raw_dir, f))]
    else:
        pdf_files = [f for f in os.listdir(raw_dir) if f.endswith(".pdf")]

    print(f"发现 {len(pdf_files)} 份 PDF 文件\n")

    for pdf_file in pdf_files:
        pdf_path = os.path.join(raw_dir, pdf_file)
        print(f"处理：{pdf_file}")

        with IssuerProfileExtractor(pdf_path) as extractor:
            extractor.parse_issuer_name()
            extractor.parse_bond_info()
            output_file = extractor.generate_note(knowledge_dir)
            print(f"  生成：{output_file}")

        print("-" * 50)

    print("\n处理完成！")


if __name__ == "__main__":
    main()
