#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
发行条款提取器
从 PDF 中提取债券发行条款信息，生成 knowledge/01-发行条款/目录下的笔记文件
"""

import os
import re
from datetime import datetime
from typing import Dict, Optional

from extractors import (
    BaseExtractor,
    BondInfo,
    BOND_TERMS_PATTERNS,
    clean_text,
    validate_extraction,
    calculate_confidence,
)


class BondTermsExtractor(BaseExtractor):
    """发行条款提取器"""

    NOTE_TYPE = "bond_terms"
    OUTPUT_DIR = "01-发行条款"
    TAGS = ["债券/发行条款"]

    def __init__(self, pdf_path: str):
        super().__init__(pdf_path)

    def extract_key_info(self) -> Dict[str, str]:
        """提取关键信息"""
        self.extract_text()
        clean = clean_text(self.full_text).replace('\n', '')
        cover_text = self.doc[0].get_text().replace('\n', '') if self.doc else ""

        # 提取发行条款和募集资金运用章节，缩小搜索范围
        section_text = self._extract_sections_text()

        info = {
            "issuer": self._issuer_name,
            "bond_type": self._bond_info.bond_type.value if self._bond_info else "公司债",
            "period": self._bond_info.period if self._bond_info else "",
            "year": self._bond_info.year if self._bond_info else "",
            "register_scale": "",
            "issue_scale": "",
            "bond_varieties": "",  # 多品种信息
            "bond_term": "",
            "guarantee": "",
            "credit_rating": "",
            "bond_rating": "",
            "interest_rate": "",
            "repayment_method": "按年付息，到期一次还本",
            "approval_letter": "",
        }

        # 先提取注册规模（注册规模是固定的，不超过此值）
        info["register_scale"], info["approval_letter"] = self._extract_register_scale(clean)

        # 优先在章节范围内提取本期发行规模，如果章节文本太短则回退到全文
        search_text = section_text if len(section_text) > 500 else clean
        info["issue_scale"] = self._extract_issue_scale(search_text)
        

        if info["bond_varieties"]:
            # 如果有多品种信息，优先使用品种总计
            match = re.search(r'品种.*?总计.*?(\d+(?:\.\d+)?)\s*亿', info["bond_varieties"])
            if match:
                info["issue_scale"] = f"{match.group(1)}亿元"

        if not info["register_scale"]:
            val = self.find_pattern(
                [r"注册金额.*?(\d+)\s*亿", r"注册.*?(\d+)\s*亿"],
                cover_text
            )
            if val:
                info["register_scale"] = f"{val}亿元"

        if not info["issue_scale"]:
            val = self.find_pattern(
                [
                    r"本期发行金额.*?不超过.*?(\d+(?:\.\d+)?)\s*亿",
                    r"本期发行规模.*?(\d+(?:\.\d+)?)\s*亿.*?含",
                    r"本期发行规模.*?不超过.*?(\d+(?:\.\d+)?)\s*亿",
                ],
                cover_text
            )
            if val:
                info["issue_scale"] = f"{val}亿元"

        if not info["register_scale"]:
            val = self.find_pattern(BOND_TERMS_PATTERNS["register_scale"], clean)
            if val:
                info["register_scale"] = f"{val}亿元"

        if not info["issue_scale"]:
            match = re.search(
                r'深证函.*?号.*?同意.*?发行.*?不超过.*?(\d+(?:\.\d+)?)\s*亿',
                clean
            )
            if match:
                info["issue_scale"] = f"{match.group(1)}亿元"

        if not info["issue_scale"]:
            val = self.find_pattern(BOND_TERMS_PATTERNS["issue_scale"], clean)
            if val:
                info["issue_scale"] = f"{val}亿元"

        # 校验：本期发行规模不应超过注册规模，且应在合理范围（1-15亿）
        if info["register_scale"] and info["issue_scale"]:
            reg_match = re.search(r'(\d+(?:\.\d+)?)', info["register_scale"])
            iss_match = re.search(r'(\d+(?:\.\d+)?)', info["issue_scale"])
            if reg_match and iss_match:
                reg_val = float(reg_match.group(1))
                iss_val = float(iss_match.group(1))
                # 业务规则：注册规模不超过15亿、不少于1亿
                if reg_val > 15:
                    self._logger.warning(f"注册规模({reg_val}亿)超过业务合理范围(15亿)")
                if iss_val > 15:
                    self._logger.warning(f"本期发行规模({iss_val}亿)超过业务合理范围(15亿)")
                if iss_val > reg_val:
                    self._logger.warning(
                        f"本期发行规模({iss_val}亿)超过注册规模({reg_val}亿)，可能是提取错误"
                    )
                    # 将本期发行规模置空
                    info["issue_scale"] = ""

        bond_term_patterns = [
            r"债券.*?(\d+)\s*年 [期]",
            r"(\d+)\s*年 [期公司债券]",
            r"期限.*?(\d+)\s*年",
            r"存续期限.*?(\d+)\s*年",
            r"债券.*?(\d+) 年期",
            r"(\d+)\s*年期",
        ]
        for pattern in bond_term_patterns:
            match = re.search(pattern, clean)
            if match:
                term = match.group(1)
                if not term.startswith('20') and not term.startswith('19'):
                    info["bond_term"] = f"{term}年"
                    break

        match = re.search(r"票面利率 [为：:]?\s*([\d\.]+)", clean)
        if match:
            info["interest_rate"] = f"{match.group(1)}%"

        info["guarantee"] = self._extract_guarantee(clean, cover_text)

        info["credit_rating"] = self.find_pattern(
            [r"发行人主体信用等级 [为：:]?\s*([A-Z\+\-]+)", r"主体评级.*?([A-Z\+\-]+)"],
            clean
        )

        info["bond_rating"] = self.find_pattern(
            [r"债券 [信用]? 等级 [为：:]?\s*([A-Z\+\-]+)", r"债项评级.*?([A-Z\+\-]+)"],
            clean
        )

        required = ["issuer", "bond_type"]
        missing = validate_extraction(info, required)
        if missing:
            self._logger.warning(f"缺失字段：{missing}")

        return info

    def _extract_register_scale(self, clean_text: str) -> tuple:
        """提取注册规模（从无异议函）"""
        # 模式0: 精确查找"注册规模为人民币 X 亿元"（最优先）
        match = re.search(
            r'注册规模为人民币\s*(\d+(?:\.\d+)?)\s*亿',
            clean_text
        )
        if match and float(match.group(1)) > 0:
            letter_match = re.search(r'[上深]证函.*?号', clean_text)
            letter = letter_match.group(0) if letter_match else "已获取无异议函"
            return f"{match.group(1)}亿元", letter

        # 模式0b: 精确查找"注册金额为人民币 X 亿元"
        match = re.search(
            r'注册金额为人民币\s*(\d+(?:\.\d+)?)\s*亿',
            clean_text
        )
        if match and float(match.group(1)) > 0:
            letter_match = re.search(r'[上深]证函.*?号', clean_text)
            letter = letter_match.group(0) if letter_match else "已获取无异议函"
            return f"{match.group(1)}亿元", letter

        # 模式1：查找"注册总额为人民币 X 亿元"
        match = re.search(
            r'注册总额为人民币\s*(\d+(?:\.\d+)?)\s*亿',
            clean_text
        )
        if match and float(match.group(1)) > 0:
            letter_match = re.search(r'[上深]证函.*?号', clean_text)
            letter = letter_match.group(0) if letter_match else "已获取无异议函"
            return f"{match.group(1)}亿元", letter

        # 模式2：无异议函...上证函/深证函号...注册总额为人民币 X 亿元
        match = re.search(
            r'无异议函.*?[上深]证函.*?号.*?注册总额为.*?人民币.*?(\d+(?:\.\d+)?)\s*亿',
            clean_text
        )
        if match and float(match.group(1)) > 0:
            letter_match = re.search(r'[上深]证函.*?号', clean_text)
            letter = letter_match.group(0) if letter_match else "已获取无异议函"
            return f"{match.group(1)}亿元", letter

        # 模式3：上证函/深证函...号...注册总额为...
        match = re.search(
            r'[上深]证函.*?号.*?注册总额.{0,50}为.*?(\d+(?:\.\d+)?)\s*亿',
            clean_text
        )
        if match and float(match.group(1)) > 0:
            letter_match = re.search(r'[上深]证函.*?号', clean_text)
            letter = letter_match.group(0) if letter_match else "已获取无异议函"
            return f"{match.group(1)}亿元", letter

        # 模式4：上证函/深证函...号...同意...不超过...（限制范围，业务规则：不超过15亿）
        match = re.search(
            r'[上深]证函.{0,150}同意.{0,80}不超过.{0,30}(\d+(?:\.\d+)?)\s*亿',
            clean_text
        )
        if match and 0 < float(match.group(1)) <= 15:
            letter_match = re.search(r'[上深]证函.*?号', clean_text)
            letter = letter_match.group(0) if letter_match else "已获取无异议函"
            return f"{match.group(1)}亿元", letter

        # 模式5：无异议函...不超过...（不含函号，业务规则：不超过15亿）
        match = re.search(
            r'无异议函.*?不超过.*?(\d+(?:\.\d+)?)\s*亿',
            clean_text
        )
        if match and 0 < float(match.group(1)) <= 15:
            return f"{match.group(1)}亿元", "已获取无异议函"

        # 模式6：同意...发行...不超过...（业务规则：不超过15亿）
        match = re.search(
            r'同意.*?发行.*?不超过.*?(\d+(?:\.\d+)?)\s*亿',
            clean_text
        )
        if match and 0 < float(match.group(1)) <= 15:
            return f"{match.group(1)}亿元", ""

        # 模式7：注册[金额度]...不超过...（兜底，业务规则：不超过15亿且不少于1亿）
        match = re.search(
            r'注册[金额度]?.{0,100}不超过.*?(\d+(?:\.\d+)?)\s*亿',
            clean_text
        )
        if match and 0 < float(match.group(1)) <= 15:
            return f"{match.group(1)}亿元", ""

        return "", ""
        match = re.search(
            r'无异议函.*?[上深]证函.*?号.*?注册总额为.*?人民币.*?(\d+(?:\.\d+)?)\s*亿',
            clean_text
        )
        if match:
            letter_match = re.search(r'[上深]证函.*?号', clean_text)
            if letter_match:
                letter = letter_match.group(0)
            else:
                letter = "已获取无异议函"
            return f"{match.group(1)}亿元", letter

        # 模式2：上证函/深证函...号...注册总额为...
        match = re.search(
            r'[上深]证函.*?号.*?注册总额.{0,50}为.*?(\d+(?:\.\d+)?)\s*亿',
            clean_text
        )
        if match:
            letter_match = re.search(r'[上深]证函.*?号', clean_text)
            if letter_match:
                letter = letter_match.group(0)
            else:
                letter = "已获取无异议函"
            return f"{match.group(1)}亿元", letter

        # 模式3：注册总额不超过...（上证函/深证函格式）- 放在后面避免误匹配
        match = re.search(
            r'[上深]证函.*?号.*?注册总额.{0,100}不超过.*?(\d+(?:\.\d+)?)\s*亿',
            clean_text
        )
        if match:
            letter_match = re.search(r'[上深]证函.*?号', clean_text)
            if letter_match:
                letter = letter_match.group(0)
            else:
                letter = "已获取无异议函"
            return f"{match.group(1)}亿元", letter

        # 模式3b：上证函/深证函...号...注册金额为...（另一种格式）
        match = re.search(
            r'[上深]证函.*?号.*?注册金额.{0,50}为.*?(\d+(?:\.\d+)?)\s*亿',
            clean_text
        )
        if match:
            letter_match = re.search(r'[上深]证函.*?号', clean_text)
            if letter_match:
                letter = letter_match.group(0)
            else:
                letter = "已获取无异议函"
            return f"{match.group(1)}亿元", letter

        # 模式5：无异议函...不超过...（不含函号）
        match = re.search(
            r'无异议函.*?不超过.*?(\d+(?:\.\d+)?)\s*亿',
            clean_text
        )
        if match:
            return f"{match.group(1)}亿元", "已获取无异议函"

        # 模式5b：注册总额为人民币 X 亿元（更精确的注册规模提取）
        match = re.search(
            r'注册总额[为是]?.*?人民币.*?(\d+(?:\.\d+)?)\s*亿',
            clean_text
        )
        if match:
            letter_match = re.search(r'[上深]证函.*?号', clean_text)
            if letter_match:
                letter = letter_match.group(0)
            else:
                letter = "已获取无异议函"
            return f"{match.group(1)}亿元", letter

        # 模式5c：注册金额为人民币 X 亿元
        match = re.search(
            r'注册金额[为是]?人民币.*?(\d+(?:\.\d+)?)\s*亿',
            clean_text
        )
        if match:
            letter_match = re.search(r'[上深]证函.*?号', clean_text)
            if letter_match:
                letter = letter_match.group(0)
            else:
                letter = "已获取无异议函"
            return f"{match.group(1)}亿元", letter

        # 模式6：同意...发行...不超过...（不含函号或无异议函）
        match = re.search(
            r'同意.*?发行.*?不超过.*?(\d+(?:\.\d+)?)\s*亿',
            clean_text
        )
        if match:
            return f"{match.group(1)}亿元", ""

        # 模式7：注册[金额度]...不超过...（兜底）
        match = re.search(
            r'注册[金额度]?.{0,100}不超过.*?(\d+(?:\.\d+)?)\s*亿',
            clean_text
        )
        if match:
            return f"{match.group(1)}亿元", ""

        return "", ""

    def _extract_sections_text(self) -> str:
        """提取发行条款和募集资金运用章节的文本"""
        clean = clean_text(self.full_text).replace('\n', '')

        # 定义章节起始和结束模式
        section_starts = [
            "第二节 发行条款",
            "第二节发行条款",
            "二、发行条款",
            "发行条款",
            "第三节 募集资金运用",
            "第三节募集资金运用",
            "三、募集资金运用",
            "募集资金运用",
        ]
        section_ends = [
            "第三节 募集资金运用",
            "第三节募集资金运用",
            "三、募集资金运用",
            "第四节 发行人基本情况",
            "第四节发行人基本情况",
            "四、发行人基本情况",
        ]

        # 找到第一个章节开始位置
        start_idx = -1
        for pattern in section_starts:
            idx = clean.find(pattern)
            if idx >= 0:
                start_idx = idx
                break

        if start_idx < 0:
            return ""

        # 找到章节结束位置
        end_idx = len(clean)
        for pattern in section_ends:
            idx = clean.find(pattern, start_idx + 10)
            if 0 < idx < end_idx:
                end_idx = idx

        section_text = clean[start_idx:end_idx]
        self._logger.debug(f"提取章节文本长度: {len(section_text)} 字符")
        return section_text

    def _extract_issue_scale(self, clean_text: str) -> str:
        """提取本期发行规模"""
        # 模式 0：如果包含品种信息，提取品种总计
        if '品种一' in clean_text or '品种二' in clean_text:
            # 查找品种总计
            match = re.search(
                r'品种.*?合计.*?(\d+(?:\.\d+)?)\s*亿',
                clean_text
            )
            if match:
                return f"{match.group(1)}亿元"
            # 查找"不超过 X 亿元（含品种一 Y 亿元，品种二 Z 亿元）"
            match = re.search(
                r'本期债券发行规模.*?(\d+(?:\.\d+)?)\s*亿.*?品种一.*?(\d+(?:\.\d+)?)\s*亿.*?品种二.*?(\d+(?:\.\d+)?)\s*亿',
                clean_text
            )
            if match:
                # 返回第一个数字（总规模）
                return f"{match.group(1)}亿元"
            # 查找"品种一...X 亿元；品种二...Y 亿元"
            match = re.search(
                r'品种一.*?(\d+(?:\.\d+)?)\s*亿.*?品种二.*?(\d+(?:\.\d+)?)\s*亿',
                clean_text
            )
            if match:
                # 返回总计
                total = float(match.group(1)) + float(match.group(2))
                return f"{total}亿元"
            # 查找"品种一发行规模为不超过（含）X 亿元；品种二发行规模为不超过（含）Y 亿元"
            match = re.search(
                r'品种一发行规模.*?不超过.*?(\d+(?:\.\d+)?)\s*亿.*?品种二发行规模.*?不超过.*?(\d+(?:\.\d+)?)\s*亿',
                clean_text
            )
            if match:
                total = float(match.group(1)) + float(match.group(2))
                return f"{total}亿元"

        # 模式 1：本期债券发行规模不超过人民币 X 亿元（优先匹配"本期债券发行规模"）
        match = re.search(
            r'本期债券发行规模不超过.*?(\d+(?:\.\d+)?)\s*亿',
            clean_text
        )
        if match:
            return f"{match.group(1)}亿元"

        # 模式 1b：本期债券发行金额不超过人民币 X 亿元
        match = re.search(
            r'本期债券发行金额不超过.*?(\d+(?:\.\d+)?)\s*亿',
            clean_text
        )
        if match:
            return f"{match.group(1)}亿元"

        # 模式 2：发行规模...本期债券...不超过 X 亿元
        match = re.search(
            r'发行规模.*?本期债券.*?不超过.*?(\d+(?:\.\d+)?)\s*亿',
            clean_text
        )
        if match:
            return f"{match.group(1)}亿元"

        # 模式 3：发行规模...X 亿元（含 X 亿元）
        match = re.search(
            r'发行规模.{0,100}不超过.*?(\d+(?:\.\d+)?)\s*亿元？（含',
            clean_text
        )
        if match:
            return f"{match.group(1)}亿元"

        # 模式 3b：发行金额...X 亿元（含 X 亿元）
        match = re.search(
            r'发行金额.{0,100}不超过.*?(\d+(?:\.\d+)?)\s*亿元？（含',
            clean_text
        )
        if match:
            return f"{match.group(1)}亿元"

        # 模式 3c：发行金额...不超过 X 亿元
        match = re.search(
            r'发行金额.{0,100}不超过.*?(\d+(?:\.\d+)?)\s*亿元',
            clean_text
        )
        if match:
            return f"{match.group(1)}亿元"

        # 模式 3d：发行规模...不超过 X 亿元
        match = re.search(
            r'发行规模.{0,100}不超过.*?(\d+(?:\.\d+)?)\s*亿元',
            clean_text
        )
        if match:
            return f"{match.group(1)}亿元"

        # 模式 2：本期/本次债券面值总额不超过 X 亿元（含 X 亿元）
        match = re.search(
            r'(?:本期 | 本次) 债券面值总额.*?不超过.*?(\d+(?:\.\d+)?)\s*亿.*?[（(] 含',
            clean_text
        )
        if match:
            return f"{match.group(1)}亿元"

        # 模式 2b：本期/本次债券发行总额不超过 X 亿元（含 X 亿元）
        match = re.search(
            r'(?:本期 | 本次) 债券发行总额.*?不超过.*?(\d+(?:\.\d+)?)\s*亿元？（含',
            clean_text
        )
        if match:
            return f"{match.group(1)}亿元"

        # 模式 3：本期/本次债券发行规模为 X 亿元
        match = re.search(
            r'(?:本期 | 本次) 债券发行规模.{0,50}为 (?:人民币)?\s*(\d+(?:\.\d+)?)\s*亿',
            clean_text
        )
        if match:
            return f"{match.group(1)}亿元"

        # 模式 4：本期/本次债券发行总额为 X 亿元
        match = re.search(
            r'(?:本期 | 本次) 债券发行总额.{0,50}为 (?:人民币)?\s*(\d+(?:\.\d+)?)\s*亿',
            clean_text
        )
        if match:
            return f"{match.group(1)}亿元"

        # 模式 5：本期/本次债券发行规模/总额不超过 X 亿元
        match = re.search(
            r'(?:本期 | 本次) 债券发行 (?:规模 | 总额).{0,50}不超过.*?(\d+(?:\.\d+)?)\s*亿',
            clean_text
        )
        if match:
            return f"{match.group(1)}亿元"

        # 模式 5b：本期/本次债券发行总额不超过 X 亿元
        match = re.search(
            r'(?:本期 | 本次) 债券发行总额不超过.*?(\d+(?:\.\d+)?)\s*亿',
            clean_text
        )
        if match:
            return f"{match.group(1)}亿元"

        # 模式 5c：本期/本次债券发行金额不超过 X 亿元
        match = re.search(
            r'(?:本期 | 本次) 债券发行金额.{0,50}不超过.*?(\d+(?:\.\d+)?)\s*亿',
            clean_text
        )
        if match:
            return f"{match.group(1)}亿元"

        # 模式 6：本期/本次债券发行...为 X 亿元
        match = re.search(
            r'(?:本期 | 本次) 债券发行.{0,50}为 (?:人民币)?\s*(\d+(?:\.\d+)?)\s*亿',
            clean_text
        )
        if match:
            return f"{match.group(1)}亿元"

        # 模式 7：本期/本次债券发行规模不超过 X 亿元
        match = re.search(
            r'(?:本期 | 本次) 债券发行规模.{0,50}不超过.*?(\d+(?:\.\d+)?)\s*亿',
            clean_text
        )
        if match:
            return f"{match.group(1)}亿元"

        # 模式 8：发行规模/发行金额：本期/本次债券...X 亿元
        match = re.search(
            r'发行 (?:规模 | 金额)[:：].{0,100}(?:本期 | 本次) 债券.*?不超过.*?(\d+(?:\.\d+)?)\s*亿',
            clean_text
        )
        if match:
            return f"{match.group(1)}亿元"

        # 模式 9：发行规模/发行金额...不超过 X 亿元
        match = re.search(
            r'发行 (?:规模 | 金额)[:：].{0,100}不超过.*?(\d+(?:\.\d+)?)\s*亿',
            clean_text
        )
        if match:
            return f"{match.group(1)}亿元"

        # 模式 10：本期/本次债券...规模 X 亿元
        match = re.search(
            r'(?:本期 | 本次) 债券发行规模.{0,50}.*?(\d+(?:\.\d+)?)\s*亿',
            clean_text
        )
        if match:
            return f"{match.group(1)}亿元"

        # 模式 11：本期发行 X 亿元
        match = re.search(
            r'本期发行 [债面额]*[总规模]*[:：]?\s*(\d+(?:\.\d+)?)\s*亿',
            clean_text
        )
        if match:
            return f"{match.group(1)}亿元"

        # 模式 12：直接匹配"XX 债券发行规模不超过 X 亿元"（南通格式）
        match = re.search(
            r'债券发行规模不超过.*?(\d+(?:\.\d+)?)\s*亿',
            clean_text
        )
        if match:
            return f"{match.group(1)}亿元"

        return ""

    def _extract_guarantee(self, clean_text: str, cover_text: str) -> str:
        """提取增信措施"""
        start = cover_text.find("增信情况")
        if start >= 0:
            text = cover_text[start:]
            by_idx = text.find("由")
            provide_idx = text.find("提供")
            if by_idx >= 0 and provide_idx > by_idx:
                guarantor = text[by_idx + 1:provide_idx].strip()
                if "担保" in guarantor or "融资" in guarantor:
                    return f"由{guarantor}提供担保"[:80]

        if "无担保" in clean_text or "无增信" in clean_text:
            return "无担保"

        guarantee_match = re.search(
            r"(?:增信方式 | 担保方式).*?(?:保证担保 | 抵押担保 | 质押担保 | 信用)",
            clean_text
        )
        if guarantee_match:
            return guarantee_match.group(0)[-10:]

        return "信用"

    def generate_note(self, output_base: str) -> str:
        """生成发行条款笔记"""
        info = self.extract_key_info()

        bond_info = self.parse_bond_info()
        bond_full_name = (
            f"{info['issuer']}{info['year'].replace('年', '')}年面向专业投资者"
            f"非公开发行公司债券（第一期）"
        )
        bond_short = self.generate_bond_short_name()

        frontmatter = self.get_frontmatter(
            note_type=self.NOTE_TYPE,
            tags=self.TAGS + [f"#{info['bond_type']}", info['year'].replace('年', '')]
        )

        register_note = ""
        if info.get("approval_letter"):
            register_note = f"（{info['approval_letter']}）"

        template = f"""{frontmatter}
# {info['issuer']} - 发行条款

## 基本信息

| 项目 | 内容 |
|------|------|
| 发行人全称 | {info['issuer']} |
| 债券全称 | {bond_full_name} |
| 债券简称 | {bond_short} |
| 发行日期 | {info['year'].replace('年', '')}年 |
| 注册规模 | {info['register_scale'] or '/'} {register_note if register_note else ''} |
| 本期发行规模 | {info['issue_scale'] or '/'} |
| 债券期限 | {info['bond_term'] or '/'} |
| 票面利率 | {info['interest_rate'] or '/'} |
| 增信措施 | {info['guarantee'] or '/'} |
| 主体评级 | {info['credit_rating'] or '/'} |
| 债项评级 | {info['bond_rating'] or '/'} |
| 债券类型 | {info['bond_type']} |
| 期数 | {info['period']} |

## 注册文件依据

{f"根据 {info['approval_letter']}，同意发行人非公开发行面值不超过 {info['register_scale']} 的公司债券。" if info.get('approval_letter') and info['register_scale'] else '详见募集说明书原文'}

## 增信措施详情

{info['guarantee'] if info['guarantee'] and info['guarantee'] != '信用' else '本期债券无增信措施'}

## 还本付息方式

{info['repayment_method']}

---
**来源**: {self.pdf_name}
**提取日期**: {datetime.now().strftime('%Y-%m-%d')}
"""

        output_path = os.path.join(
            output_base, self.OUTPUT_DIR,
            f"{info['issuer']}-发行条款.md"
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

        with BondTermsExtractor(pdf_path) as extractor:
            extractor.parse_issuer_name()
            extractor.parse_bond_info()
            output_file = extractor.generate_note(knowledge_dir)
            print(f"  生成：{output_file}")

        print("-" * 50)

    print("\n处理完成！")


if __name__ == "__main__":
    main()
