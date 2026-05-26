#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
发行条款提取器
从 PDF 中提取债券发行条款信息，生成 knowledge/01-发行条款/目录下的笔记文件
"""

import os
import re
from datetime import datetime
from typing import Dict, List, Optional

from extractors import (
    BaseExtractor,
    BondInfo,
    BOND_TERMS_PATTERNS,
    clean_text,
    validate_extraction,
    calculate_confidence,
)
from typing import Dict, List, Optional


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
            "year": self._bond_info.year if self._bond_info else "",
            "register_scale": "",
            "issue_scale": "",
            "bond_varieties": "",  # 多品种信息
            "bond_term": "",
            "guarantee": "",
            "credit_rating": "",
            "interest_rate": "",
            "repayment_method": "按年付息，到期一次还本",
            "approval_letter": "",
            "lead_underwriter": "",
            "co_underwriter": "",
        }

        # 先提取注册规模（注册规模是固定的，不超过此值）
        info["register_scale"], info["approval_letter"] = self._extract_register_scale(clean)

        # 如果注册规模提取成功但没有获取到函号，尝试独立提取函号
        if info["register_scale"] and not info["approval_letter"]:
            letter_match = re.search(r'(?:[上深]|.{0,3})证函[^号]*号', clean)
            if letter_match:
                info["approval_letter"] = letter_match.group(0)
            else:
                letter_match = re.search(r'证函[^号]*号', clean)
                if letter_match:
                    info["approval_letter"] = letter_match.group(0)

        # 如果注册规模未提取到但存在函号，仍应记录函号
        if not info["register_scale"]:
            letter_match = re.search(r'(?:[上深]|.{0,3})证函[^号]*号', clean)
            if letter_match:
                info["approval_letter"] = letter_match.group(0)
            else:
                letter_match = re.search(r'证函[^号]*号', clean)
                if letter_match:
                    info["approval_letter"] = letter_match.group(0)

        # 优先在章节范围内提取本期发行规模，如果章节文本太短或未找到则回退到全文
        search_text = section_text if len(section_text) > 5000 else clean
        info["issue_scale"] = self._extract_issue_scale(search_text)
        # 如果在限定范围内未找到，尝试全文
        if not info["issue_scale"] and search_text != clean:
            info["issue_scale"] = self._extract_issue_scale(clean)

        if info["bond_varieties"]:
            # 如果有多品种信息，优先使用品种总计
            match = re.search(r'品种.*?总计.*?(\d+(?:\.\d+)?)\s*亿', info["bond_varieties"])
            if match:
                info["issue_scale"] = f"{match.group(1)}亿元"

        if not info["register_scale"]:
            val = self.find_pattern(
                [r"注册金额.*?(\d+(?:\.\d+)?)\s*亿", r"注册.*?(\d+(?:\.\d+)?)\s*亿"],
                cover_text
            )
            if val and float(val) > 0:
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
            if val and float(val) > 0:
                info["issue_scale"] = f"{val}亿元"

        if not info["register_scale"]:
            val = self.find_pattern(BOND_TERMS_PATTERNS["register_scale"], clean)
            if val and float(val) > 0:
                # 安全验证：确认匹配的不是银行授信额度等无关内容
                # 在匹配点附近搜索关键词，排除"授信""银行"等场景
                for pattern in BOND_TERMS_PATTERNS["register_scale"]:
                    m = re.search(pattern, clean)
                    if m:
                        context = clean[max(0, m.start() - 100):m.start()]
                        if '授信' not in context and '银行' not in context:
                            info["register_scale"] = f"{val}亿元"
                            break
                        else:
                            self._logger.warning(
                                f"register_scale 匹配到授信/银行相关内容({val}亿)，已跳过"
                            )

        if not info["issue_scale"]:
            match = re.search(
                r'深证函.*?号.*?同意.*?发行.*?不超过.*?(\d+(?:\.\d+)?)\s*亿',
                clean
            )
            if match and float(match.group(1)) > 0:
                info["issue_scale"] = f"{match.group(1)}亿元"

        if not info["issue_scale"]:
            val = self.find_pattern(BOND_TERMS_PATTERNS["issue_scale"], clean)
            if val and float(val) > 0:
                # 安全验证：排除授信/银行额度等无关内容
                for pattern in BOND_TERMS_PATTERNS["issue_scale"]:
                    m = re.search(pattern, clean)
                    if m:
                        context = clean[max(0, m.start() - 100):m.start()]
                        if '授信' not in context and '银行' not in context:
                            info["issue_scale"] = f"{val}亿元"
                            break
                        else:
                            self._logger.warning(
                                f"issue_scale 匹配到授信/银行相关内容({val}亿)，已跳过"
                            )

        # 校验：本期发行规模不应超过注册规模，且应在合理范围（1-50亿）
        if info["register_scale"] and info["issue_scale"]:
            reg_match = re.search(r'(\d+(?:\.\d+)?)', info["register_scale"])
            iss_match = re.search(r'(\d+(?:\.\d+)?)', info["issue_scale"])
            if reg_match and iss_match:
                reg_val = float(reg_match.group(1))
                iss_val = float(iss_match.group(1))
                # 业务规则：注册规模不超过50亿、不少于1亿
                if reg_val > 50:
                    self._logger.warning(f"注册规模({reg_val}亿)超过业务合理范围(50亿)")
                if iss_val > 50:
                    self._logger.warning(f"本期发行规模({iss_val}亿)超过业务合理范围(50亿)")
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

        info["guarantee"] = self._extract_guarantee(clean, cover_text)

        info["credit_rating"] = self.find_pattern(
            [r"发行人主体信用等级 [为：:]?\s*([A-Z][A-Z\+\-]+)", r"主体评级.*?([A-Z][A-Z\+\-]+)"],
            clean
        )

        # 提取承销商信息
        underwriters = self._extract_underwriters(cover_text, clean)
        info["lead_underwriter"] = underwriters["lead_underwriter"]
        info["co_underwriter"] = underwriters["co_underwriter"]

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

        # 模式0c: 精确查找"注册金额为不超过 X 亿元"（适配无"人民币"关键词的场景）
        match = re.search(
            r'注册金额为不超过\s*(\d+(?:\.\d+)?)\s*亿',
            clean_text
        )
        if match and float(match.group(1)) > 0:
            letter_match = re.search(r'[上深]证函.*?号', clean_text)
            letter = letter_match.group(0) if letter_match else "已获取无异议函"
            return f"{match.group(1)}亿元", letter

        # 模式0d: 精确查找"注册规模为不超过 X 亿元"
        match = re.search(
            r'注册规模为不超过\s*(\d+(?:\.\d+)?)\s*亿',
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

        # 模式2b：无异议函...上证函/深证函号...注册金额为/注册总额为...人民币 X 亿元
        # （比模式2宽松，同时匹配"注册金额"和"注册总额"）
        match = re.search(
            r'无异议函.*?[上深]证函.*?号.*?注册[总金]额为.*?人民币.*?(\d+(?:\.\d+)?)\s*亿',
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

        # 模式3a：上证函/深证函...号...注册金额为...X 亿元
        match = re.search(
            r'[上深]证函.*?号.*?注册金额为.*?(\d+(?:\.\d+)?)\s*亿',
            clean_text
        )
        if match and float(match.group(1)) > 0:
            letter_match = re.search(r'[上深]证函.*?号', clean_text)
            letter = letter_match.group(0) if letter_match else "已获取无异议函"
            return f"{match.group(1)}亿元", letter

        # 模式3b：上证函/深证函...号...注...X 亿元（宽松模式，适配 PDF 编码乱码）
        # 在"证函...号"附近找包含"注"字的注册金额数字，限制在合理范围
        match = re.search(
            r'[上深]证函.{0,200}注[^\d]{0,30}?(\d+(?:\.\d+)?)\s*亿',
            clean_text
        )
        if match and 0 < float(match.group(1)) <= 50:
            letter_match = re.search(r'[上深]证函.*?号', clean_text)
            letter = letter_match.group(0) if letter_match else ""
            return f"{match.group(1)}亿元", letter

        # 模式4：上证函/深证函...号...同意...不超过...（限制范围，业务规则：不超过50亿）
        # 注意：[^\d]{0,30} 防止 . 贪婪匹配吃掉数字前缀（如 "5.6" 中的 "5."），避免只捕获到 "6"
        match = re.search(
            r'[上深]证函.{0,150}同意.{0,80}不超过[^\d]{0,30}(\d+(?:\.\d+)?)\s*亿',
            clean_text
        )
        if match and 0 < float(match.group(1)) <= 50:
            letter_match = re.search(r'[上深]证函.*?号', clean_text)
            letter = letter_match.group(0) if letter_match else "已获取无异议函"
            return f"{match.group(1)}亿元", letter

        # 模式5：无异议函...不超过...（不含函号，业务规则：不超过50亿）
        match = re.search(
            r'无异议函.*?不超过.*?(\d+(?:\.\d+)?)\s*亿',
            clean_text
        )
        if match and 0 < float(match.group(1)) <= 50:
            return f"{match.group(1)}亿元", "已获取无异议函"

        # 模式6：同意...发行...不超过...（业务规则：不超过50亿）
        match = re.search(
            r'同意.*?发行.*?不超过.*?(\d+(?:\.\d+)?)\s*亿',
            clean_text
        )
        if match and 0 < float(match.group(1)) <= 50:
            return f"{match.group(1)}亿元", ""

        # 模式7：注册[金额度]...不超过...（兜底，业务规则：不超过50亿且不少于1亿）
        # 注意：.{0,100}? 非贪婪匹配，防止跳过第一个"不超过"导致错误的金额
        match = re.search(
            r'注册[金额度]?.{0,100}?不超过.*?(\d+(?:\.\d+)?)\s*亿',
            clean_text
        )
        if match and 0 < float(match.group(1)) <= 50:
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

        # 找到第一个章节开始位置（跳过 TOC 条目）
        start_idx = -1
        for pattern in section_starts:
            idx = -1
            while True:
                idx = clean.find(pattern, idx + 1)
                if idx < 0:
                    break
                # 检查是否是 TOC 条目（后面跟大量点号）
                after = clean[idx + len(pattern):idx + len(pattern) + 100]
                if after.lstrip().startswith('....') or after.count('.') > 20:
                    continue  # TOC entry, skip
                start_idx = idx
                break
            if start_idx >= 0:
                break

        if start_idx < 0:
            return ""

        # 找到章节结束位置（跳过 TOC 条目）
        end_idx = len(clean)
        for pattern in section_ends:
            idx = -1
            while True:
                idx = clean.find(pattern, idx + 1)
                if idx < 0 or idx <= start_idx:
                    break
                after = clean[idx + len(pattern):idx + len(pattern) + 100]
                if after.lstrip().startswith('....') or after.count('.') > 20:
                    continue  # TOC entry, skip
                if idx < end_idx:
                    end_idx = idx
                break

        section_text = clean[start_idx:end_idx]
        self._logger.debug(f"提取章节文本长度: {len(section_text)} 字符")
        return section_text

    def _extract_issue_scale(self, clean_text: str) -> str:
        """提取本期发行规模"""
        # 模式 0b：本期债券发行总金额/总额/总额度不超过人民币 X 亿元（优先，最可靠）
        match = re.search(
            r'本期债券发行总[金额规模度]*\s*不超过[人民币\s]*(\d+(?:\.\d+)?)\s*亿',
            clean_text
        )
        if match:
            return f"{match.group(1)}亿元"

        # 模式 1：本期债券发行规模不超过人民币 X 亿元
        match = re.search(
            r'本期债券发行规模\s*不超过[人民币\s]*(\d+(?:\.\d+)?)\s*亿',
            clean_text
        )
        if match:
            return f"{match.group(1)}亿元"

        # 模式 1b：本期债券发行金额不超过人民币 X 亿元
        match = re.search(
            r'本期债券发行金额\s*不超过[人民币\s]*(\d+(?:\.\d+)?)\s*亿',
            clean_text
        )
        if match:
            return f"{match.group(1)}亿元"

        # 模式 3e：发行金额：本期债券发行总额不超过人民币 X 亿元
        match = re.search(
            r'发行金额[：:]\s*本期债券发行总额\s*不超过[人民币\s]*(\d+(?:\.\d+)?)\s*亿',
            clean_text
        )
        if match:
            return f"{match.group(1)}亿元"

        # 模式 3d：发行规模...不超过 X 亿元（限制距离，避免跨段落匹配）
        match = re.search(
            r'发行规模.{0,60}不超过[人民币\s]*(\d+(?:\.\d+)?)\s*亿元',
            clean_text
        )
        if match:
            return f"{match.group(1)}亿元"

        # 模式 3c：发行金额...不超过 X 亿元（限制距离）
        match = re.search(
            r'发行金额.{0,60}不超过[人民币\s]*(\d+(?:\.\d+)?)\s*亿元',
            clean_text
        )
        if match:
            return f"{match.group(1)}亿元"

        # 模式 2：发行规模...本期债券...不超过 X 亿元（限制距离）
        match = re.search(
            r'发行规模.{0,200}本期债券.{0,50}不超过[人民币\s]*(\d+(?:\.\d+)?)\s*亿',
            clean_text
        )
        if match:
            return f"{match.group(1)}亿元"

        # 模式 3：发行规模...不超过 X 亿元（含 X 亿元）
        match = re.search(
            r'发行规模.{0,60}不超过[人民币\s]*(\d+(?:\.\d+)?)\s*亿元[？(（] 含',
            clean_text
        )
        if match:
            return f"{match.group(1)}亿元"

        # 模式 3b：发行金额...不超过 X 亿元（含 X 亿元）
        match = re.search(
            r'发行金额.{0,60}不超过[人民币\s]*(\d+(?:\.\d+)?)\s*亿元[？(（] 含',
            clean_text
        )
        if match:
            return f"{match.group(1)}亿元"

        # 模式 2：本期/本次债券面值总额不超过 X 亿元（含 X 亿元）
        match = re.search(
            r'(?:本期|本次) 债券面值总额\s*不超过[人民币\s]*(\d+(?:\.\d+)?)\s*亿.*?[（(] 含',
            clean_text
        )
        if match:
            return f"{match.group(1)}亿元"

        # 模式 2b：本期/本次债券发行总额不超过 X 亿元（含 X 亿元）
        match = re.search(
            r'(?:本期|本次) 债券发行总额\s*不超过[人民币\s]*(\d+(?:\.\d+)?)\s*亿元[？(（] 含',
            clean_text
        )
        if match:
            return f"{match.group(1)}亿元"

        # 模式 3：本期/本次债券发行规模为 X 亿元
        match = re.search(
            r'(?:本期|本次) 债券发行规模.{0,50}为\s*(?:人民币\s*)?(\d+(?:\.\d+)?)\s*亿',
            clean_text
        )
        if match:
            return f"{match.group(1)}亿元"

        # 模式 4：本期/本次债券发行总额为 X 亿元
        match = re.search(
            r'(?:本期|本次) 债券发行总额.{0,50}为\s*(?:人民币\s*)?(\d+(?:\.\d+)?)\s*亿',
            clean_text
        )
        if match:
            return f"{match.group(1)}亿元"

        # 模式 5：本期/本次债券发行规模/总额不超过 X 亿元
        match = re.search(
            r'(?:本期|本次) 债券发行\s*(?:规模|总额).{0,50}不超过[人民币\s]*(\d+(?:\.\d+)?)\s*亿',
            clean_text
        )
        if match:
            return f"{match.group(1)}亿元"

        # 模式 5b：本期/本次债券发行总额不超过 X 亿元
        match = re.search(
            r'(?:本期|本次) 债券发行总额\s*不超过[人民币\s]*(\d+(?:\.\d+)?)\s*亿',
            clean_text
        )
        if match:
            return f"{match.group(1)}亿元"

        # 模式 5c：本期/本次债券发行金额不超过 X 亿元
        match = re.search(
            r'(?:本期|本次) 债券发行金额.{0,50}不超过[人民币\s]*(\d+(?:\.\d+)?)\s*亿',
            clean_text
        )
        if match:
            return f"{match.group(1)}亿元"

        # 模式 6：本期/本次债券发行...为 X 亿元
        match = re.search(
            r'(?:本期|本次) 债券发行.{0,50}为\s*(?:人民币\s*)?(\d+(?:\.\d+)?)\s*亿',
            clean_text
        )
        if match:
            return f"{match.group(1)}亿元"

        # 模式 7：本期/本次债券发行规模不超过 X 亿元
        match = re.search(
            r'(?:本期|本次) 债券发行规模.{0,50}不超过[人民币\s]*(\d+(?:\.\d+)?)\s*亿',
            clean_text
        )
        if match:
            return f"{match.group(1)}亿元"

        # 模式 8：发行规模/发行金额：本期/本次债券...X 亿元
        match = re.search(
            r'发行\s*(?:规模|金额)[：:]\s*(?:本期|本次) 债券.{0,50}不超过[人民币\s]*(\d+(?:\.\d+)?)\s*亿',
            clean_text
        )
        if match:
            return f"{match.group(1)}亿元"

        # 模式 9：发行规模/发行金额...不超过 X 亿元
        match = re.search(
            r'发行\s*(?:规模|金额)[：:].{0,60}不超过[人民币\s]*(\d+(?:\.\d+)?)\s*亿',
            clean_text
        )
        if match:
            return f"{match.group(1)}亿元"

        # 模式 10：本期/本次债券...规模 X 亿元
        match = re.search(
            r'(?:本期|本次) 债券发行规模.{0,50}(\d+(?:\.\d+)?)\s*亿',
            clean_text
        )
        if match:
            return f"{match.group(1)}亿元"

        # 模式 11：本期发行 X 亿元
        match = re.search(
            r'本期发行\s*[债面额]*[总规模]*[：:]?\s*(\d+(?:\.\d+)?)\s*亿',
            clean_text
        )
        if match:
            return f"{match.group(1)}亿元"

        # 模式 12：直接匹配"XX 债券发行规模不超过 X 亿元"
        match = re.search(
            r'债券发行规模\s*不超过[人民币\s]*(\d+(?:\.\d+)?)\s*亿',
            clean_text
        )
        if match:
            return f"{match.group(1)}亿元"

        # ====== 以下是有品种（多品种）债券的提取逻辑 ======
        # 放在后面，因为上面的通用模式可能更精确

        if '品种一' in clean_text or '品种二' in clean_text:
            # 查找品种总计（限制品种和合计之间的距离，避免跨段落匹配）
            match = re.search(
                r'品种[一二].{0,200}合计.*?(\d+(?:\.\d+)?)\s*亿',
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
                return f"{match.group(1)}亿元"
            # 查找"品种一发行规模为不超过（含）X 亿元；品种二发行规模为不超过（含）Y 亿元"
            # （限制品种名称与金额之间的距离，避免捕获无关数字）
            match = re.search(
                r'品种一.{0,50}发行规模.*?不超过.*?(\d+(?:\.\d+)?)\s*亿.{0,200}品种二.{0,50}发行规模.*?不超过.*?(\d+(?:\.\d+)?)\s*亿',
                clean_text
            )
            if match:
                total = float(match.group(1)) + float(match.group(2))
                return f"{total}亿元"
            # 查找"品种一...X 亿元；品种二...Y 亿元"
            # （同上，限制距离并限定"发行规模"关键词）
            match = re.search(
                r'品种一发行规模.{0,50}(\d+(?:\.\d+)?)\s*亿.{0,200}品种二发行规模.{0,50}(\d+(?:\.\d+)?)\s*亿',
                clean_text
            )
            if match:
                total = float(match.group(1)) + float(match.group(2))
                return f"{total}亿元"

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

    def _extract_underwriter_from_text(self, text: str, patterns: List[str]) -> str:
        """按优先级试正则模式，返回首个有效公司名"""
        for pattern in patterns:
            match = re.search(pattern, text)
            if match:
                value = match.group(1).strip()
                if any(suffix in value for suffix in ['股份有限公司', '有限责任公司', '有限公司']):
                    return value
        return ""

    def _clean_company_name(self, name: str) -> str:
        """清理公司名，处理多公司列表"""
        if not name:
            return ""
        # 去除括号及之后的地址信息
        name = re.sub(r'[\s(（].*$', '', name)
        name = name.strip()
        # 处理多家公司（用顿号/逗号分隔）
        companies = re.split(r'[、，,，;；]', name)
        cleaned = []
        for c in companies:
            c = c.strip()
            if c and len(c) >= 4 and any(s in c for s in ['股份有限公司', '有限责任公司', '有限公司']):
                cleaned.append(c)
        return '、'.join(cleaned) if cleaned else name

    def _extract_underwriters(self, cover_text: str, clean_text: str) -> Dict[str, str]:
        """从封面和释义章节提取承销商信息"""
        result: Dict[str, str] = {"lead_underwriter": "", "co_underwriter": ""}

        # --- Step 1: 封面页（去换行） ---
        cover = cover_text.replace('\n', '').replace(' ', '')

        # 牵头主承销商
        result["lead_underwriter"] = self._extract_single_underwriter(cover, "牵头主承销商")
        if not result["lead_underwriter"]:
            # fallback: 主承销商（排除牵头/联席前缀）
            result["lead_underwriter"] = self._extract_single_underwriter(cover, "主承销商", exclude_prefixes=["牵头", "联席"])

        # 联席主承销商
        result["co_underwriter"] = self._extract_single_underwriter(cover, "联席主承销商")

        # --- Step 2: 释义章节 fallback ---
        if not result["lead_underwriter"] or not result["co_underwriter"]:
            definition_text = self.extract_section_text(
                start_patterns=["释义"],
                end_patterns=["第二节", "二、发行条款", "发行条款"],
                max_length=15000
            )
            if definition_text:
                definition_text = definition_text.replace('\n', '').replace(' ', '')
                if not result["lead_underwriter"]:
                    result["lead_underwriter"] = self._extract_underwriter_from_text(
                        definition_text,
                        [
                            r"(?:牵头主承销商|主承销商)[^指]*?指\s*([一-龥·（）()]{4,60}?(?:股份有限公司|有限责任公司|有限公司))",
                            r"(?:牵头主承销商|主承销商)[、/]*\s*指\s*([一-龥·（）()]{4,60}?(?:股份有限公司|有限责任公司|有限公司))",
                        ]
                    )
                if not result["co_underwriter"]:
                    co_match = re.search(
                        r"联席主承销商指([^指]+)",
                        definition_text
                    )
                    if co_match:
                        raw_text = co_match.group(1)
                        # Split by separators and extract company names
                        parts = re.split(r'[、，,，;；]', raw_text)
                        cleaned = []
                        for p in parts:
                            p = p.strip()
                            m = re.search(r'([一-龥·]{2,60}?(?:股份有限公司|有限责任公司|有限公司))', p)
                            if m:
                                cleaned.append(m.group(1))
                        if cleaned:
                            result["co_underwriter"] = '、'.join(cleaned)

        # --- Step 3: 发行有关机构章节 fallback ---
        # Always check back pages if either field is empty
        if not result["lead_underwriter"] or not result["co_underwriter"]:
            institution_info = self._extract_institutions_from_back_pages()
            if not result["lead_underwriter"] and institution_info.get("lead_underwriter"):
                result["lead_underwriter"] = institution_info["lead_underwriter"]
            # If co_underwriter from back pages is longer (more companies), use it
            if not result["co_underwriter"] and institution_info.get("co_underwriter"):
                result["co_underwriter"] = institution_info["co_underwriter"]
            elif institution_info.get("co_underwriter") and len(institution_info["co_underwriter"]) > len(result.get("co_underwriter", "")):
                result["co_underwriter"] = institution_info["co_underwriter"]

        # --- Step 4: 清理结果 ---
        if result["lead_underwriter"]:
            result["lead_underwriter"] = self._clean_company_name(result["lead_underwriter"])
        if result["co_underwriter"]:
            result["co_underwriter"] = self._clean_company_name(result["co_underwriter"])

        return result

    def _extract_single_underwriter(self, text: str, label: str, exclude_prefixes: Optional[List[str]] = None) -> str:
        """提取单个承销商，支持 / 分隔和 : 分隔格式"""
        exclude_prefixes = exclude_prefixes or []

        # 找 label 位置
        idx = text.find(label)
        if idx < 0:
            return ""

        # 检查是否被排除的前缀
        for prefix in exclude_prefixes:
            before = text[max(0, idx - len(prefix)):idx]
            if before.endswith(prefix):
                return ""

        rest = text[idx + len(label):]

        # 格式1: label/其他标签...公司名 或 label/其他标签：（住所：...）（公司名在别处）
        if rest.startswith('/'):
            rest = rest[1:]  # 去掉 /
            # 先检查是否是 label/标签：（住所：...）格式（公司名未列出）
            # 如果 / 后面紧跟的是标签（簿记管理人/受托管理人等）然后是冒号和括号，则公司名未直接列出
            if re.match(r'(?:簿记管理人|受托管理人|承销商)[：:=]\s*[（(]', rest):
                return ""
            # 否则找第一个公司名（跳过簿记管理人/受托管理人等中间标签）
            company_pat = re.compile(
                r'(?:簿记管理人|受托管理人|承销商|管理人)?'
                r'([一-龥·]{4,20}?(?:股份有限公司|有限责任公司|有限公司))'
            )
            m = company_pat.search(rest)
            if m:
                # 验证：公司名不应包含增信/担保相关关键词
                name = m.group(1)
                if any(kw in name for kw in ['增信', '担保', '融资担保', '信用评级', '评级', '会计师', '审计', '律师', '法律顾问']):
                    return ""
                return name

        # 格式2: label、其他标签：公司名
        colon_match = re.match(r'[、，,][^：:=]*[：:=]\s*([一-龥·]{4,60}?(?:股份有限公司|有限责任公司|有限公司))', rest)
        if colon_match:
            return colon_match.group(1)

        # 格式3: label：公司名
        colon_match = re.match(r'[：:=]\s*([一-龥·]{4,60}?(?:股份有限公司|有限责任公司|有限公司))', rest)
        if colon_match:
            return colon_match.group(1)

        return ""

    def _extract_institutions_from_back_pages(self) -> Dict[str, str]:
        """从募集说明书后半部分的'发行有关机构'章节提取承销商信息"""
        result: Dict[str, str] = {"lead_underwriter": "", "co_underwriter": ""}

        # 提取最后 80 页文本
        start_page = max(0, len(self.doc) - 80)
        section_text = ""
        for page in self.doc[start_page:]:
            section_text += page.get_text()
        section_clean = section_text.replace('\n', '').replace(' ', '')

        # 找到"发行有关机构"章节（支持多种标题变体）
        idx = -1
        for header in ['本期债券发行的有关机构', '本次债券发行的有关机构', '发行有关机构']:
            idx = section_clean.find(header)
            if idx >= 0:
                break
        if idx < 0:
            return result

        inst_section = section_clean[idx:idx + 10000]

        # === 提取主承销商/牵头主承销商 ===
        # 常见格式：
        # （二）主承销商/簿记管理人/债券受托管理人名称：东莞证券股份有限公司
        # （二）主承销商/簿记管理人/债券受托管理人：广发证券股份有限公司
        # （二）主承销商、簿记管理人、受托管理人名称：中信建投证券股份有限公司
        # 二、主承销商/受托管理人/簿记管理人名称：华金证券股份有限公司
        lead_patterns = [
            # 牵头主承销商（明确标注）
            r'牵头主承销商[^名]{0,30}?名称\s*[：:=]\s*([一-龥·]{4,60}?(?:股份有限公司|有限责任公司|有限公司))',
            r'牵头主承销商[^：:=]*[：:=]\s*([一-龥·]{4,60}?(?:股份有限公司|有限责任公司|有限公司))',
            # 主承销商/簿记管理人/...名称：XXX
            r'主承销商[/、，,][^名]{0,40}?名称\s*[：:=]\s*([一-龥·]{4,60}?(?:股份有限公司|有限责任公司|有限公司))',
            # 主承销商/簿记管理人/...：XXX（无"名称"二字）
            r'主承销商[/、，,][^：:=]{0,20}[：:=]\s*([一-龥·]{4,60}?(?:股份有限公司|有限责任公司|有限公司))',
            # 主承销商、...名称：XXX
            r'主承销商、[^名]{0,40}?名称\s*[：:=]\s*([一-龥·]{4,60}?(?:股份有限公司|有限责任公司|有限公司))',
            # 主承销商：XXX
            r'主承销商[：:=]\s*([一-龥·]{4,60}?(?:股份有限公司|有限责任公司|有限公司))',
            # 承销机构、簿记管理人、受托管理人名称：XXX（部分PDF用"承销机构"替代"主承销商"）
            r'承销机构[^名]{0,30}?名称\s*[：:=]\s*([一-龥·]{4,60}?(?:股份有限公司|有限责任公司|有限公司))',
        ]

        for pattern in lead_patterns:
            m = re.search(pattern, inst_section)
            if m:
                name = m.group(1)
                result["lead_underwriter"] = self._clean_company_name(name)
                break

        # === 提取所有联席主承销商（支持多家）===
        co_companies = []

        # 先用 re.findall 捕获所有格式A的匹配（可能有多家独立的"联席主承销商：XXX"）
        co_patterns = [
            r'联席主承销商[^名]{0,30}?名称\s*[：:=]\s*([一-龥·]{4,60}?(?:股份有限公司|有限责任公司|有限公司))',
            r'联席主承销商[^：:=]*[：:=]\s*([一-龥·]{4,60}?(?:股份有限公司|有限责任公司|有限公司))',
            r'联席主承销商[/、，,][^名]{0,40}?名称\s*[：:=]\s*([一-龥·]{4,60}?(?:股份有限公司|有限责任公司|有限公司))',
        ]
        for pattern in co_patterns:
            matches = re.findall(pattern, inst_section)
            co_from_a = [self._clean_company_name(m) for m in matches if self._clean_company_name(m)]
            if co_from_a:
                co_companies.extend(co_from_a)
                break

        # 再用格式B：在"联席主承销商"区块内找所有"名称：XXX"（补充同区块下的多家公司）
        co_header_idx = inst_section.find('联席主承销商')
        if co_header_idx >= 0:
            co_section = inst_section[co_header_idx:]
            # 找到联席区块结尾（律师事务所、登记结算、或下一数字标题）
            end_patterns = ['律师事务所', '登记、托管', '登记结算', '托管、结算',
                            '（三）', '三、', '(三)',
                            '（四）', '四、', '(四)',
                            '五、', '六、', '七、']
            co_end = len(co_section)
            for end_pat in end_patterns:
                e = co_section.find(end_pat)
                if e > 0 and e < co_end:
                    co_end = e
            co_section = co_section[:co_end]

            # 提取区块内所有"名称：XXX公司"
            name_matches = re.findall(
                r'名称\s*[：:=]\s*([一-龥·]{4,60}?(?:股份有限公司|有限责任公司|有限公司))',
                co_section
            )
            for m in name_matches:
                cleaned = self._clean_company_name(m)
                if cleaned and cleaned not in co_companies:
                    co_companies.append(cleaned)

        # 过滤掉已经作为牵头主承销商提取的公司
        if result["lead_underwriter"] and result["lead_underwriter"] in co_companies:
            co_companies.remove(result["lead_underwriter"])

        if co_companies:
            result["co_underwriter"] = '、'.join(co_companies)

        return result

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
            tags=self.TAGS + [f"#{info['bond_type']}"],
            extra_fields={
                "issuer": info["issuer"],
                "bond_short": bond_short,
                "bond_type": info["bond_type"],
                "year": info["year"].replace("年", ""),
                "guarantee": info.get("guarantee", ""),
                "credit_rating": info.get("credit_rating", ""),
            }
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
| 增信措施 | {info['guarantee'] or '/'} |
| 主体评级 | {info['credit_rating'] or '/'} |
| 债券类型 | {info['bond_type']} |
| 牵头主承销商 | {info['lead_underwriter'] or '/'} |
| 联席主承销商 | {info['co_underwriter'] or '/'} |

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
