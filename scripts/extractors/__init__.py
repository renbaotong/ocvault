#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
提取器模块
提供统一的 PDF 提取功能
"""

from .base import (
    BaseExtractor,
    ExtractionResult,
    BondInfo,
    BondType,
    GuaranteeType,
)
from .config import (
    BOND_TERMS_PATTERNS,
    FUND_USAGE_PATTERNS,
    FUND_USAGE_FLAGS,
    ISSUER_PROFILE_PATTERNS,
    BUSINESS_ANALYSIS_PATTERNS,
    FINANCIAL_SECTION_PATTERNS,
    FINANCIAL_ITEM_PATTERNS,
)
from .utils import (
    clean_text,
    extract_number,
    format_amount,
    find_section,
    calculate_ratio,
    validate_extraction,
    calculate_confidence,
)

__all__ = [
    # 基类
    "BaseExtractor",
    "ExtractionResult",
    "BondInfo",
    "BondType",
    "GuaranteeType",
    # 配置
    "BOND_TERMS_PATTERNS",
    "FUND_USAGE_PATTERNS",
    "FUND_USAGE_FLAGS",
    "ISSUER_PROFILE_PATTERNS",
    "BUSINESS_ANALYSIS_PATTERNS",
    "FINANCIAL_SECTION_PATTERNS",
    "FINANCIAL_ITEM_PATTERNS",
    # 工具
    "clean_text",
    "extract_number",
    "format_amount",
    "find_section",
    "calculate_ratio",
    "validate_extraction",
    "calculate_confidence",
]
