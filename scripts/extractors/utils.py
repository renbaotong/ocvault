#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
提取器工具模块
"""

import re
from typing import Optional, List, Dict, Any


def clean_text(text: str) -> str:
    """
    清洗文本

    Args:
        text: 原始文本

    Returns:
        清洗后的文本
    """
    text = re.sub(r'<[^>]+>', '\n', text)  # 移除 HTML 标签
    text = re.sub(r'\n\s*\n', '\n', text)  # 合并空行
    text = re.sub(r' +', ' ', text)  # 合并空格
    return text.strip()


def extract_number(text: str) -> Optional[float]:
    """
    从文本中提取数字

    Args:
        text: 包含数字的文本

    Returns:
        提取的数字，失败返回 None
    """
    match = re.search(r"(\d+(?:\.\d+)?)", text)
    return float(match.group(1)) if match else None


def format_amount(value: float, unit: str = "亿元") -> str:
    """
    格式化金额

    Args:
        value: 数值
        unit: 单位

    Returns:
        格式化后的金额字符串
    """
    if unit == "亿元":
        return f"{value:.2f}亿元"
    elif unit == "万元":
        return f"{value:.0f}万元"
    return f"{value}{unit}"


def parse_table_row(line: str) -> List[str]:
    """
    解析 Markdown 表格行

    Args:
        line: 表格行字符串

    Returns:
        单元格列表
    """
    cells = line.split('|')
    return [cell.strip() for cell in cells if cell.strip()]


def find_section(
    text: str,
    start_markers: List[str],
    end_markers: List[str],
    max_length: int = 10000
) -> str:
    """
    查找章节内容

    Args:
        text: 完整文本
        start_markers: 起始标记列表
        end_markers: 结束标记列表
        max_length: 最大长度

    Returns:
        章节内容
    """
    clean = text.replace('\n', '')

    # 找到起始位置
    start_idx = -1
    for marker in start_markers:
        idx = clean.find(marker)
        if idx >= 0:
            start_idx = idx
            break

    if start_idx < 0:
        return ""

    # 找到结束位置
    end_idx = len(clean)
    for marker in end_markers:
        idx = clean.find(marker, start_idx)
        if 0 < idx < end_idx:
            end_idx = idx

    return clean[start_idx:end_idx][:max_length]


def calculate_ratio(numerator: str, denominator: str, fmt: str = "{:.1f}%") -> str:
    """
    计算比率

    Args:
        numerator: 分子（可包含单位）
        denominator: 分母
        fmt: 格式化字符串

    Returns:
        计算后的比率
    """
    try:
        num = extract_number(numerator)
        den = extract_number(denominator)

        if num and den and den > 0:
            return fmt.format(num / den * 100)
    except:
        pass
    return ""


def validate_extraction(data: Dict[str, Any], required_fields: List[str]) -> List[str]:
    """
    验证提取结果

    Args:
        data: 提取的数据
        required_fields: 必填字段列表

    Returns:
        缺失字段列表
    """
    missing = []
    for field in required_fields:
        if not data.get(field):
            missing.append(field)
    return missing


def calculate_confidence(data: Dict[str, Any], total_fields: int) -> float:
    """
    计算提取置信度

    Args:
        data: 提取的数据
        total_fields: 总字段数

    Returns:
        置信度 (0-1)
    """
    filled = sum(1 for v in data.values() if v)
    return filled / total_fields if total_fields > 0 else 0.0


def merge_extracted_data(base: Dict[str, Any], override: Dict[str, Any]) -> Dict[str, Any]:
    """
    合并提取结果

    Args:
        base: 基础数据
        override: 覆盖数据

    Returns:
        合并后的数据
    """
    result = base.copy()
    for key, value in override.items():
        if value and not result.get(key):
            result[key] = value
    return result
