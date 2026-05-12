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
                # TOC 特征：紧跟 pattern 后有 4+ 个点号
                after_text = next_clean[len(pattern):]
                has_toc_dots = after_text.lstrip(' \t').startswith('....')
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
                        has_toc_dots = after_text.lstrip(' \t').startswith('....')
                        if has_toc_dots:
                            continue
                        start_idx = idx
                        break

        if start_idx < 0:
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
            r'(?:注册名称|公司名称|企业名称)\s*[:：|]\s*\n?\s*([\s\S]+?)(?=\n\s*(?:法定代表|注册资本|实缴资本|设立日期|统一社会信用代码|注册地址|所属行业|经营范围|企业类型|二、|$))',
            r'(?:注册名称|公司名称|企业名称)\s*[:：|]?\s*\n?\s*([\s\S]+?)(?=\n\s*(?:法定代表|注册资本|实缴资本|设立日期|统一社会信用代码|注册地址|所属行业|经营范围|企业类型|二、|$))',
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
            r'注册资本\s*[:：|]\s*\n?\s*人民币?\s*\n?\s*([\d,\.]+)\s*\n?\s*(万[元]?|亿[元]?|元)',
            r'注册资本\s*[:：|]\s*\n?\s*([\d,\.]+)\s*\n?\s*(万[元]?|亿[元]?|元)',
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
            r'(?:实缴资本|实收资本)\s*[:：|]\s*\n?\s*人民币?\s*\n?\s*([\d,\.]+)\s*\n?\s*(万[元]?|亿[元]?|元)',
            r'(?:实缴资本|实收资本)\s*[:：|]\s*\n?\s*([\d,\.]+)\s*\n?\s*(万[元]?|亿[元]?|元)',
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
                          '公司注册地址', '联系人', '电话号码', '传真号码']
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
                value = ' '.join(value_lines)
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
            # 移除"控股股东为"前缀（pattern 10 捕获）
            name = re.sub(r'^控股股东为\s*', '', name)
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
            # 如果找不到"三、股权结构"，尝试从第四节直接提取
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
    raw_dir = "raw"
    knowledge_dir = "knowledge"

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
