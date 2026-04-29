#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
募集资金运用提取器
从 PDF 中提取募集资金运用信息，生成 knowledge/02-募集资金运用/目录下的笔记文件
"""

import os
import re
from datetime import datetime
from typing import Dict, List, Optional

from extractors import (
    BaseExtractor,
    FUND_USAGE_PATTERNS,
    FUND_USAGE_FLAGS,
    clean_text,
    extract_number,
    validate_extraction,
    calculate_confidence,
)

# 募集资金运用章节定位模式
FUND_USAGE_SECTION_PATTERNS = {
    "start": ["第三节 募集资金运用", "第三节募集资金运用", "三、募集资金运用"],
    "end": ["第四节 发行人基本情况", "第四节发行人基本情况", "四、发行人基本情况"],
}


class FundUsageExtractor(BaseExtractor):
    """募集资金运用提取器"""

    NOTE_TYPE = "fund_usage"
    OUTPUT_DIR = "02-募集资金运用"
    TAGS = ["债券/资金用途"]

    # 乱码字符映射（PDF 编码问题）
    GARBLED_CHARS = {
        'Ԫ': '元',
        'ծ': '债',
        'Ϣ': '息',
        'ʽ': '流',
        'ȫ': '全',
        '۳': '扣',
    }

    def __init__(self, pdf_path: str):
        super().__init__(pdf_path)

    def extract_fund_usage(self) -> Dict[str, str]:
        """提取募集资金运用信息"""
        self.extract_text()
        clean = self.full_text.replace('\n', '')

        # 解码乱码字符
        decoded = self._decode_garbled_text(clean)

        # 提取所有用途及其金额
        all_usages = self._extract_all_usages(clean, decoded)

        # 募集资金总额
        total_amount = self._extract_total_amount(clean, decoded)

        usage = {
            "total_amount": total_amount,
            "all_usages": all_usages,  # 存储所有提取的用途
        }

        return usage

    def _extract_all_usages(self, clean: str, decoded: str) -> List[Dict[str, str]]:
        """提取所有资金用途及其金额"""
        usages = []

        # 先尝试在募集资金运用章节内提取
        section_text = self._extract_section_text()

        # 如果章节内容太短或不对，使用全文搜索
        search_text = clean

        # 提取金额的模式：支持 亿元 和 万元（万元需转换为亿元）
        # 基于募集说明书中的常见表述优化
        patterns = [
            # 扣除发行费用后 + 万元 + 用于 (with amount)
            r"扣除发行费用后[^\n]{0,20}?(\d+(?:,\d{3})*(?:\.\d+)?)\s*万元[^\n]{0,60}?用于[^\n]{0,50}?([^\n，。,，；]+)",
            # 扣除发行费用后 + 亿元 + 用于 (with amount)
            r"扣除发行费用后[^\n]{0,20}?(\d+(?:\.\d+)?)\s*亿元[^\n]{0,60}?用于[^\n]{0,50}?([^\n，。,，；]+)",
            # 本期债券募集资金 + 亿元 + 用于
            r"本期债券募集资金[^\n]{0,30}?(\d+(?:\.\d+)?)\s*亿元[^\n]{0,60}?用于[^\n]{0,50}?([^\n，。,，；]+)",
            # 本期公司债券募集资金 + 亿元 + 用于
            r"本期公司债券募集资金[^\n]{0,30}?(\d+(?:\.\d+)?)\s*亿元[^\n]{0,60}?用于[^\n]{0,50}?([^\n，。,，；]+)",
            # 本次公司债券募集资金 + 亿元 + 用于
            r"本次公司债券募集资金[^\n]{0,30}?(\d+(?:\.\d+)?)\s*亿元[^\n]{0,60}?用于[^\n]{0,50}?([^\n，。,，；]+)",
            # 本期债券计划发行规模 + 亿元 + 用于
            r"本期债券计划发行规模[^\n]{0,30}?(\d+(?:\.\d+)?)\s*亿元[^\n]{0,60}?用于[^\n]{0,50}?([^\n，。,，；]+)",
            # X亿元用于XX项目
            r"(\d+(?:\.\d+)?)\s*亿元[^\n]{0,30}?用于[^\n]{0,50}?([^\n，。,，；]+)",
            # 万元 + 用于
            r"(\d+(?:,\d{3})*(?:\.\d+)?)\s*万元[^\n]{0,60}?用于[^\n]{0,50}?([^\n，。,，；]+)",
            # 不超过X亿元 + 用于
            r"不超过(\d+(?:\.\d+)?)\s*亿元[^\n]{0,30}?用于[^\n]{0,50}?([^\n，。,，；]+)",
            # 不低于X%部分用于
            r"不低于.*?(\d+(?:\.\d+)?)\s*亿元.*?用于[^\n]{0,50}?([^\n，。,，；]+)",
        ]

        # 额外模式：捕获有用途但没有明确金额的情况
        # 从发行规模推断金额
        purpose_patterns = [
            r"扣除发行费用后[^\n]{0,30}?用于[^\n]{0,30}?([^\n，。,，；]+)",
            r"本期债券募集资金[^\n]{0,30}?用于[^\n]{0,30}?([^\n，。,，；]+)",
            r"募集资金.*?用于[^\n]{0,30}?([^\n，。,，；]+)",
        ]

        for pattern in patterns:
            matches = re.findall(pattern, search_text)
            for match in matches:
                try:
                    amount_str = match[0].replace(',', '')
                    amount = float(amount_str)
                    usage_name = match[1].strip()

                    # 判断单位：如果是万元，转换为亿元
                    # 检查模式中是否包含"万元"
                    if '万元' in pattern:
                        amount = amount / 10000  # 万元转亿元

                    # 业务规则验证：金额在0.1-15亿范围内（允许更小的金额）
                    if 0.1 <= amount <= 15 and usage_name and len(usage_name) >= 2:
                        # 清理用途名称
                        usage_name = self._clean_usage_name(usage_name)

                        # 避免重复添加（允许0.01亿误差）
                        if not any(abs(u["amount"] - amount) < 0.01 for u in usages):
                            usages.append({
                                "amount": amount,
                                "name": usage_name
                            })
                except (ValueError, IndexError):
                    continue

        # 如果没有提取到具体金额，但有发行规模，尝试从全文搜索用途描述
        if not usages:
            purpose_patterns = [
                r"扣除发行费用后[^\n]{0,20}?用于[^\n]{0,40}?([^\n，。,，；]+)",
                r"本期债券募集资金[^\n]{0,30}?用于[^\n]{0,40}?([^\n，。,，；]+)",
            ]
            for pattern in purpose_patterns:
                match = re.search(pattern, search_text)
                if match:
                    purpose = match.group(1).strip()
                    purpose = purpose.rstrip('。,.，')
                    if purpose and len(purpose) >= 2:
                        # 清理用途名称
                        purpose = self._clean_usage_name(purpose)
                        # 添加一个默认用途
                        usages.append({
                            "amount": 0,  # 金额未知
                            "name": purpose
                        })
                        break

        # 按金额排序
        usages.sort(key=lambda x: x["amount"], reverse=True)

        return usages

    def _clean_usage_name(self, name: str) -> str:
        """清理用途名称"""
        # 移除常见的前缀和标点
        name = name.strip()
        # 移除句末的标点
        name = name.rstrip('。,.，')

        # 简化常见的用途描述
        replacements = {
            "偿还有息负债本金": "偿还有息负债",
            "偿还相关项目的有息负债本金": "偿还项目有息负债",
            "偿还乡村振兴领域相关项目的有息负债本金": "偿还乡村振兴项目有息负债",
            "偿还涉农业务乡村振兴相关领域有息负债本金": "偿还涉农有息负债",
            "偿还非乡村振兴相关领域的有息负债本金": "偿还其他有息负债",
            "补充涉农业务支持乡村振兴相关领域所需的流动资金": "补充流动资金",
            "置换前期科技创新领域的基金出资": "置换前期基金出资",
            "置换前期项目投资资金": "置换前期项目投资",
        }

        for old, new in replacements.items():
            if old in name:
                name = new
                break

        # 如果名称过长，截取关键部分
        if len(name) > 20:
            # 查找常见关键词位置
            keywords = ["偿还", "补充", "投资", "置换", "归还", "建设", "研发", "项目"]
            for kw in keywords:
                idx = name.find(kw)
                if idx >= 0:
                    # 从关键词开始截取
                    name = name[idx:idx+20]
                    break

        return name if name else "募集资金用途"

    def _decode_garbled_text(self, text: str) -> str:
        """解码乱码文本"""
        result = text
        for garbled, normal in self.GARBLED_CHARS.items():
            result = result.replace(garbled, normal)
        return result

    def _extract_section_text(self) -> str:
        """提取募集资金运用章节文本"""
        clean = self.full_text.replace('\n', '')

        # 使用配置文件中的章节模式
        section_starts = FUND_USAGE_SECTION_PATTERNS.get("start", [])
        section_ends = FUND_USAGE_SECTION_PATTERNS.get("end", [])

        # 添加备用模式（更灵活匹配）
        section_starts.extend([
            "第三节 募集资金用途",
            "第三节募集资金用途",
            "三、 募集资金运用",
            "募集资金使用计划",
        ])
        section_ends.extend([
            "募集资金的现金管理",
        ])

        # 找到章节开始位置
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
        return section_text

    def _extract_total_amount(self, clean: str, decoded: str) -> str:
        """提取募集资金总额"""
        # 优先在封面页和发行条款章节中提取
        # 提取前几页作为封面区域
        cover_text = ""
        if self.doc:
            for i in range(min(5, len(self.doc))):
                cover_text += self.doc[i].get_text()

        cover_clean = cover_text.replace('\n', '') if cover_text else ""

        # 优先在封面区域搜索
        patterns = [
            r"本期债券发行规模[为是]?\s*(\d+(?:\.\d+)?)\s*亿",
            r"本期债券发行金额[为是]?\s*(\d+(?:\.\d+)?)\s*亿",
            r"本期发行规模[为是]?\s*(\d+(?:\.\d+)?)\s*亿",
        ]

        for pattern in patterns:
            # 先搜索封面
            match = re.search(pattern, cover_clean)
            if match:
                val = float(match.group(1))
                if 1 <= val <= 15:
                    return f"{val} 亿元"

            # 再搜索全文
            match = re.search(pattern, clean)
            if match:
                val = float(match.group(1))
                if 1 <= val <= 15:
                    return f"{val} 亿元"

        # 备选：在募集资金运用章节内提取
        section_text = self._extract_section_text()
        if section_text:
            for pattern in patterns:
                match = re.search(pattern, section_text)
                if match:
                    val = float(match.group(1))
                    if 1 <= val <= 15:
                        return f"{val} 亿元"

        return ""

    def _extract_debt_repayment(self, clean: str, decoded: str) -> str:
        """提取偿还债务金额 - 在第三节募集资金运用章节内提取"""
        # 获取募集资金运用章节文本
        section_text = self._extract_section_text()

        if not section_text or len(section_text) < 100:
            # 如果章节提取失败，在全文中搜索
            search_text = clean
        else:
            search_text = section_text

        # 使用用户提供的关键字优化提取
        # 格式: 本期债券募集资金...用于... / 本期债券计划发行规模...用于...
        patterns = [
            # 用户提供的关键字模式
            r"本期债券募集资金[^\n]{0,50}?(\d+(?:\.\d+)?)\s*亿元[^\n]{0,30}?用于[^\n]{0,30}?偿还",
            r"本期债券计划发行规模[^\n]{0,50}?(\d+(?:\.\d+)?)\s*亿元[^\n]{0,30}?用于[^\n]{0,30}?偿还",
            r"本次公司债券募集资金[^\n]{0,50}?(\d+(?:\.\d+)?)\s*亿元[^\n]{0,30}?用于[^\n]{0,30}?偿还",
            r"本期债券的募集资金[^\n]{0,50}?(\d+(?:\.\d+)?)\s*亿元[^\n]{0,30}?用于[^\n]{0,30}?偿还",
            r"本期公司债券募集资金[^\n]{0,50}?(\d+(?:\.\d+)?)\s*亿元[^\n]{0,30}?用于[^\n]{0,30}?偿还",
            # 备选模式
            r"募集资金[^\n]{0,30}?(\d+(?:\.\d+)?)\s*亿元[^\n]{0,30}?用于[^\n]{0,30}?偿还[有息债务]",
            r"(\d+(?:\.\d+)?)\s*亿元[^\n]{0,30}?用于[^\n]{0,30}?偿还有息[债务负债]",
            r"拟使用募集资金[^\n]{0,30}?(\d+(?:\.\d+)?)\s*亿元[^\n]{0,30}?用于[^\n]{0,30}?偿还",
            r"偿还[^\n]{0,20}?(\d+(?:\.\d+)?)\s*亿元",
            r"用于偿还[^\n]{0,20}?(\d+(?:\.\d+)?)\s*亿元",
        ]

        for pattern in patterns:
            match = re.search(pattern, search_text)
            if match:
                val = float(match.group(1))
                # 业务规则：单笔金额在1-15亿范围内
                if 1 <= val <= 15:
                    return f"{val} 亿元"

        return ""

    def _extract_supplement_flow(self, clean: str, decoded: str) -> str:
        """提取补充流动资金金额 - 在第三节募集资金运用章节内提取"""
        # 获取募集资金运用章节文本
        section_text = self._extract_section_text()

        if not section_text or len(section_text) < 100:
            # 如果章节提取失败，在全文中搜索
            search_text = clean
        else:
            search_text = section_text

        # 使用用户提供的关键字优化提取
        # 格式: 本期债券募集资金...用于...补充流动资金
        patterns = [
            # 用户提供的关键字模式
            r"本期债券募集资金[^\n]{0,50}?(\d+(?:\.\d+)?)\s*亿元[^\n]{0,30}?用于[^\n]{0,30}?补充[流动资金营运资金]",
            r"本期债券计划发行规模[^\n]{0,50}?(\d+(?:\.\d+)?)\s*亿元[^\n]{0,30}?用于[^\n]{0,30}?补充[流动资金营运资金]",
            r"本次公司债券募集资金[^\n]{0,50}?(\d+(?:\.\d+)?)\s*亿元[^\n]{0,30}?用于[^\n]{0,30}?补充[流动资金营运资金]",
            r"本期债券的募集资金[^\n]{0,50}?(\d+(?:\.\d+)?)\s*亿元[^\n]{0,30}?用于[^\n]{0,30}?补充[流动资金营运资金]",
            r"本期公司债券募集资金[^\n]{0,50}?(\d+(?:\.\d+)?)\s*亿元[^\n]{0,30}?用于[^\n]{0,30}?补充[流动资金营运资金]",
            # 备选模式
            r"募集资金[^\n]{0,30}?(\d+(?:\.\d+)?)\s*亿元[^\n]{0,30}?用于[^\n]{0,30}?补充流动资金",
            r"(\d+(?:\.\d+)?)\s*亿元[^\n]{0,30}?用于[^\n]{0,30}?补充流动资金",
            r"(\d+(?:\.\d+)?)\s*亿元[^\n]{0,30}?用于[^\n]{0,30}?补充营运资金",
            r"拟使用募集资金[^\n]{0,30}?(\d+(?:\.\d+)?)\s*亿元[^\n]{0,30}?用于[^\n]{0,30}?补充",
            r"补充流动资金[^\n]{0,20}?(\d+(?:\.\d+)?)\s*亿元",
            r"用于补充[^\n]{0,20}?(\d+(?:\.\d+)?)\s*亿元",
        ]

        for pattern in patterns:
            match = re.search(pattern, search_text)
            if match:
                val = float(match.group(1))
                # 业务规则：单笔金额在1-15亿范围内
                if 1 <= val <= 15:
                    return f"{val} 亿元"

        return ""

    def _check_all_for_debt(self, clean: str, decoded: str) -> bool:
        """检查是否全部用于偿还"""
        patterns = [
            r"全部.*?用于.*?偿还",
            r"全部.*?用于.*?有息债务",
        ]

        for pattern in patterns:
            if re.search(pattern, clean):
                return True

        return False

    def _check_after_fees(self, clean: str, decoded: str) -> bool:
        """检查是否有扣除发行费用后的描述"""
        patterns = [
            r"扣除发行费用后.*?用于",
            r"ծȯ.*?ļʽ.*?۳.*?зú",  # 乱码版本
        ]

        for pattern in patterns:
            if re.search(pattern, clean) or re.search(pattern, decoded):
                return True

        return False

    def _extract_usage_detail(self, clean: str) -> Dict[str, str]:
        """提取使用明细（偿还有息债务、补充流动资金等）"""
        result = {"debt": "", "flow": ""}

        # 查找包含明细的章节
        detail_start_patterns = [
            r"明细如下",
            r"使用情况如下表所示",
            r"具体情况如下",
            r"具体如下",
            r"募投项目以及募集资金拟投入基本情况",
            r"拟使用项目包括",
            r"投向情况如下",
        ]

        section_text = self._extract_section_text()
        if not section_text:
            return result

        # 找到明细章节的起始位置
        start_idx = -1
        for pattern in detail_start_patterns:
            idx = section_text.find(pattern)
            if idx >= 0:
                start_idx = idx
                break

        if start_idx < 0:
            # 如果没有找到明确的明细标记，在募集资金运用章节中搜索
            start_idx = 0

        detail_text = section_text[start_idx:start_idx + 2000] if start_idx >= 0 else section_text[:2000]

        # 提取偿还相关金额
        debt_patterns = [
            r"偿还[有息债务贷款负债]*.*?(\d+(?:\.\d+)?)\s*亿元",
            r"用于偿还.*?(\d+(?:\.\d+)?)\s*亿元",
            r"偿还有息.*?(\d+(?:\.\d+)?)\s*亿元",
        ]
        for pattern in debt_patterns:
            match = re.search(pattern, detail_text)
            if match:
                val = float(match.group(1))
                if 1 <= val <= 15:
                    result["debt"] = f"{val} 亿元"
                    break

        # 提取补充流动资金相关金额
        flow_patterns = [
            r"补充[流动资金营运资金]*.*?(\d+(?:\.\d+)?)\s*亿元",
            r"用于补充.*?(\d+(?:\.\d+)?)\s*亿元",
            r"补充流动.*?(\d+(?:\.\d+)?)\s*亿元",
        ]
        for pattern in flow_patterns:
            match = re.search(pattern, detail_text)
            if match:
                val = float(match.group(1))
                if 1 <= val <= 15:
                    result["flow"] = f"{val} 亿元"
                    break

        return result

    def _fallback_extraction(
        self,
        clean: str,
        decoded: str,
        usage: Dict[str, str]
    ):
        """备用提取方案"""
        # 查找所有数字，并验证业务规则（1-15亿）
        all_amounts = re.findall(r'(\d+\.\d+)\s*[元Ԫ]', clean)

        valid_amounts = []
        for amt in all_amounts:
            try:
                val = float(amt)
                if 1 <= val <= 15:
                    valid_amounts.append(amt)
            except ValueError:
                pass

        if valid_amounts and len(valid_amounts) >= 2:
            if not usage["debt_repayment"]:
                usage["debt_repayment"] = f"{valid_amounts[0]} 亿元"
            if not usage["supplement_flow"] and len(valid_amounts) > 1:
                usage["supplement_flow"] = f"{valid_amounts[1]} 亿元"

    def _read_registration_scale_from_bond_terms(self) -> str:
        """从发行条款笔记读取发行规模"""
        import os

        bond_terms_dir = os.path.join("knowledge", "01-发行条款")
        if not os.path.exists(bond_terms_dir):
            return ""

        # 查找对应发行人的发行条款笔记
        issuer_file = f"{self._issuer_name}-发行条款.md"
        file_path = os.path.join(bond_terms_dir, issuer_file)

        if not os.path.exists(file_path):
            # 尝试模糊匹配
            for f in os.listdir(bond_terms_dir):
                if self._issuer_name in f and "发行条款" in f:
                    file_path = os.path.join(bond_terms_dir, f)
                    break
            else:
                return ""

        try:
            with open(file_path, "r", encoding="utf-8") as f:
                content = f.read()

            # 优先从本期发行规模字段提取
            match = re.search(r"本期发行规模.*?(\d+(?:\.\d+)?)\s*亿元", content)
            if match:
                val = float(match.group(1))
                if 1 <= val <= 15:
                    return f"{val} 亿元"

            # 从注册规模字段提取
            match = re.search(r"注册规模.*?(\d+(?:\.\d+)?)\s*亿元", content)
            if match:
                val = float(match.group(1))
                if 1 <= val <= 15:
                    return f"{val} 亿元"

        except Exception:
            pass

        return ""

    def extract_key_info(self) -> Dict[str, str]:
        """提取关键信息"""
        self.extract_text()
        clean = self.full_text.replace('\n', '')
        cover_text = self.doc[0].get_text().replace('\n', '') if self.doc else ""

        usage = self.extract_fund_usage()

        info = {
            "issuer": self._issuer_name,
            "bond_type": self._bond_info.bond_type.value if self._bond_info else "公司债",
            "issue_scale": "",
            "debt_repayment": usage.get("debt_repayment", ""),
            "supplement_flow": usage.get("supplement_flow", ""),
            "guarantee": "",
            "rating_issuer": "",
            "rating_bond": ""
        }

        # 发行规模 - 优先使用提取的金额，但需要业务规则验证（1-15亿）
        total_amount = usage.get("total_amount", "")
        if total_amount:
            match = re.search(r"(\d+(?:\.\d+)?)", total_amount)
            if match:
                val = float(match.group(1))
                if 1 <= val <= 15:
                    info["issue_scale"] = total_amount

        # Fallback: 从全文搜索发行规模（更全面的模式）
        if not info["issue_scale"]:
            patterns = [
                r"本期债券发行面值总额不超过[人民币]*(\d+(?:\.\d+)?)\s*亿元",
                r"本期债券发行规模[为是]?\s*(\d+(?:\.\d+)?)\s*亿元",
                r"本期发行金额.*?(\d+(?:\.\d+)?)\s*亿",
                r"本期债券发行.*?(\d+(?:\.\d+)?)\s*亿元",
                r"发行总额不超过(\d+(?:\.\d+)?)\s*亿元",
                r"发行规模.*?(\d+(?:\.\d+)?)\s*亿",
            ]
            for pattern in patterns:
                match = re.search(pattern, clean)
                if match:
                    val = float(match.group(1))
                    if 1 <= val <= 15:
                        info["issue_scale"] = f"{val} 亿元"
                        break

        # Fallback: 从发行条款笔记读取发行规模
        if not info["issue_scale"]:
            info["issue_scale"] = self._read_registration_scale_from_bond_terms()

        # 增信方式
        guarantee_match = re.search(
            r"(?:担保方式 | 增信方式).*?(?:保证担保 | 抵押担保 | 质押担保 | 信用)",
            clean
        )
        if guarantee_match:
            info["guarantee"] = guarantee_match.group(0)[-10:]
        elif "担保" in clean:
            match = re.search(r"(.*?担保)", clean)
            if match:
                info["guarantee"] = match.group(1)[:20]
        else:
            info["guarantee"] = "信用"

        # 评级信息
        match = re.search(r"主体评级.*?(AAA|AA\+|AA|AA\-|A\+)", clean)
        if match:
            info["rating_issuer"] = match.group(1)

        match = re.search(r"债项评级.*?(AAA|AA\+|AA|AA\-|A\+)", clean)
        if match:
            info["rating_bond"] = match.group(1)

        return info

    def extract_fund_usage_detail(self) -> str:
        """提取资金用途详细描述"""
        self.extract_text()
        clean = self.full_text.replace('\n', '')

        # 查找募集资金运用章节
        patterns = [
            r"(?:募集资金运用 | 募集资金使用计划 | 募集资金用途 | 本期债券募集资金用途).*?"
            r"(?=第 [一二三四五六七八九十][、节]|重要提示 | 风险因素 | 释义 | 目录)",
        ]

        for pattern in patterns:
            match = re.search(pattern, clean, re.DOTALL)
            if match:
                detail = match.group(0)[:3000]
                detail = re.sub(r'<[^>]+>', '', detail)
                detail = re.sub(r'\n\s*\n', '\n\n', detail)
                # 过滤掉目录内容
                if not re.search(r'\d{2,}', detail):
                    return detail.strip()

        # 尝试提取包含资金用途描述的段落
        match = re.search(
            r"本期债券募集资金.*?(?:用于 | 拟用于).*?[\u3000-\u9fa5]{50,500}",
            clean
        )
        if match:
            detail = match.group(0)[:1500]
            return re.sub(r'<[^>]+>', '', detail)

        return ""

    def generate_note(self, output_base: str) -> str:
        """生成募集资金运用笔记"""
        info = self.extract_key_info()
        usage = self.extract_fund_usage()

        total = usage.get("total_amount", "")
        all_usages = usage.get("all_usages", [])

        # 计算总额
        def extract_num(s):
            if not s:
                return 0
            match = re.search(r"(\d+(?:\.\d+)?)", s)
            return float(match.group(1)) if match else 0

        # 获取发行规模
        issue_scale = info.get('issue_scale', '')
        issue_num = extract_num(issue_scale)

        # 计算实际用途总额，并限制不超过发行规模
        usage_total = sum(u["amount"] for u in all_usages)

        # 如果用途总额超过发行规模，按比例缩减
        if issue_num > 0 and usage_total > issue_num:
            # 按比例缩减
            ratio = issue_num / usage_total
            for u in all_usages:
                u["amount"] = round(u["amount"] * ratio, 2)
            usage_total = sum(u["amount"] for u in all_usages)

        total_num = usage_total if issue_num > 0 else usage_total

        # 生成文字描述（募集资金使用计划）
        if all_usages:
            # 构建用途描述 - 过滤掉金额为0或太小的
            usage_descs = []
            for u in all_usages:
                if u['amount'] > 0.01:  # 过滤掉金额太小的
                    usage_descs.append(f"{u['amount']}亿元用于{u['name']}")

            if not usage_descs and issue_num > 0:
                # 如果没有有效金额但有用途描述，使用发行规模
                for u in all_usages:
                    if u['amount'] <= 0.01 and u['name']:
                        usage_descs.append(f"{issue_num}亿元用于{u['name']}")
                        break

            if usage_descs:
                usage_text = "，".join(usage_descs)
                if issue_scale:
                    usage_text = f"本期债券募集资金{issue_scale}，扣除发行费用后，{usage_text}。"
                else:
                    usage_text = f"募集资金用途：{usage_text}。"
            else:
                usage_text = "详见募集说明书原文"
        else:
            usage_text = "详见募集说明书原文"

        # 生成明细表格 - 只包含有效金额的用途
        valid_usages = [u for u in all_usages if u['amount'] > 0.01]
        if issue_num > 0 and valid_usages:
            # 如果用途金额总和超过发行规模，按比例缩减
            valid_total = sum(u['amount'] for u in valid_usages)
            if valid_total > issue_num:
                ratio = issue_num / valid_total
                for u in valid_usages:
                    u['amount'] = round(u['amount'] * ratio, 2)
                valid_total = sum(u['amount'] for u in valid_usages)
        usage_total = sum(u['amount'] for u in valid_usages)

        if valid_usages and len(valid_usages) > 1:
            table_rows = []
            for u in valid_usages:
                amount_str = f"{u['amount']} 亿元"
                ratio_str = f"{(u['amount']/usage_total*100):.1f}%" if usage_total > 0 else ""
                table_rows.append(f"| {u['name']} | {amount_str} | {ratio_str} |")
            detail_content = f"""
## 具体使用明细

| 用途 | 金额（亿元） | 占比 |
|-----|------------|------|
{chr(10).join(table_rows)}
| **合计** | {usage_total:.2f}亿元 | 100% |
"""
        else:
            detail_content = ""

        frontmatter = self.get_frontmatter(
            note_type=self.NOTE_TYPE,
            tags=self.TAGS + [f"#{info['bond_type']}"]
        )

        template = f"""{frontmatter}
# {info['issuer']} - 募集资金运用

## 本期发行规模

- 发行规模：{issue_scale or total or '/'}

## 募集资金使用计划

{usage_text}
{detail_content}
---
**来源**: {self.pdf_name}
**提取日期**: {datetime.now().strftime('%Y-%m-%d')}
"""

        output_path = os.path.join(
            output_base, self.OUTPUT_DIR,
            f"{info['issuer']}-募集资金运用.md"
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

        with FundUsageExtractor(pdf_path) as extractor:
            extractor.parse_issuer_name()
            extractor.parse_bond_info()
            output_file = extractor.generate_note(knowledge_dir)
            print(f"  生成：{output_file}")

        print("-" * 50)

    print("\n处理完成！")


if __name__ == "__main__":
    main()
