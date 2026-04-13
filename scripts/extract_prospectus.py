#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
公司债募集说明书信息提取工具
从 PDF 中提取关键信息并生成完整的 Obsidian 笔记
"""

import fitz
import os
import re
import json
from datetime import datetime
from pathlib import Path


class ProspectusExtractor:
    """募集说明书信息提取器"""

    def __init__(self, pdf_path: str):
        self.pdf_path = pdf_path
        self.pdf_name = os.path.basename(pdf_path)
        self.doc = None
        self.full_text = ""
        self.sections = {}
        self.issuer_name = ""
        self.bond_name = ""

    def open_pdf(self):
        """打开 PDF 文件"""
        self.doc = fitz.open(self.pdf_path)

    def close_pdf(self):
        """关闭 PDF 文件"""
        if self.doc:
            self.doc.close()

    def extract_text(self) -> str:
        """从 PDF 提取全部文本"""
        if not self.doc:
            self.open_pdf()
        self.full_text = ""
        for page in self.doc:
            self.full_text += page.get_text()
        return self.full_text

    def parse_issuer_name(self) -> str:
        """从文件名提取发行人名称"""
        name = self.pdf_name.replace(".pdf", "")
        # 移除年份及之后的内容
        match = re.match(r'(.*?)(20\d{2}年)', name)
        if match:
            self.issuer_name = match.group(1).strip()
        else:
            self.issuer_name = name
        return self.issuer_name

    def parse_bond_info(self) -> dict:
        """从文件名提取债券信息"""
        name = self.pdf_name.replace(".pdf", "")

        # 判断债券类型
        bond_type = "公司债"
        if "乡村振兴" in name:
            bond_type = "乡村振兴债"
        if "革命老区" in name:
            bond_type = "革命老区债"

        # 提取期数
        period_match = re.search(r'（第 [一二三四五] 期）', name)
        period = period_match.group(0) if period_match else ""

        self.bond_info = {
            "type": bond_type,
            "period": period,
            "year": re.search(r'20\d{2}年', name).group(0) if re.search(r'20\d{2}年', name) else ""
        }
        return self.bond_info

    def find_section_pages(self, section_num: str) -> tuple:
        """查找章节所在的页码范围"""
        if not self.doc:
            self.open_pdf()

        section_patterns = [
            f"第{section_num}节",
            f"第{section_num}节 ",
        ]

        start_page = None
        end_page = len(self.doc)

        # 查找起始页
        for i, page in enumerate(self.doc):
            text = page.get_text()
            for pattern in section_patterns:
                if pattern in text:
                    start_page = i
                    break
            if start_page:
                break

        if start_page is None:
            return (None, None)

        # 查找结束页（下一章节开始）
        section_nums = ["一", "二", "三", "四", "五", "六", "七", "八", "九", "十"]
        current_idx = section_nums.index(section_num) if section_num in section_nums else -1

        if current_idx >= 0 and current_idx < len(section_nums) - 1:
            next_num = section_nums[current_idx + 1]
            for i in range(start_page + 1, len(self.doc)):
                text = self.doc[i].get_text()
                if f"第{next_num}节" in text:
                    end_page = i
                    break

        return (start_page, end_page)

    def extract_section_text(self, section_num: str) -> str:
        """提取指定章节文本"""
        start_page, end_page = self.find_section_pages(section_num)
        if start_page is None:
            return ""

        section_text = ""
        for i in range(start_page, min(end_page, len(self.doc))):
            section_text += self.doc[i].get_text()

        return section_text

    def extract_all_sections(self) -> dict:
        """提取所有章节"""
        if not self.doc:
            self.open_pdf()

        # 首先提取全文本
        self.full_text = ""
        for page in self.doc:
            self.full_text += page.get_text()

        self.sections = {
            "二": self.extract_section_text("二"),
            "三": self.extract_section_text("三"),
            "四": self.extract_section_text("四"),
            "五": self.extract_section_text("五"),
        }
        return self.sections

    def extract_key_info(self) -> dict:
        """提取关键信息"""
        if not self.sections:
            self.extract_all_sections()

        # 额外提取第 1 页（封面页）的文本
        cover_text = ""
        if self.doc and len(self.doc) > 0:
            cover_text = self.doc[0].get_text().replace('\n', '')

        info = {
            "issuer": self.issuer_name,
            "bond_type": self.bond_info.get("type", ""),
            "period": self.bond_info.get("period", ""),
            "year": self.bond_info.get("year", ""),
            "register_scale": "",
            "issue_scale": "",
            "bond_term": "",
            "guarantee": "",
            "fund_usage": [],
            "credit_rating": "",
            "bond_rating": "",
            "interest_rate": "",
            "repayment_method": ""
        }

        # 清理文本 - 只移除换行符，保留空格
        clean_text = self.full_text.replace('\n', '')

        # === 从封面页提取（优先级高）===
        # 注册规模
        match = re.search(r"注册金额.*?(\d+)\s*亿", cover_text)
        if match:
            info["register_scale"] = f"{match.group(1)} 亿元"

        # 本期发行规模
        match = re.search(r"本期发行金额.*?(\d+)\s*亿", cover_text)
        if match:
            info["issue_scale"] = f"{match.group(1)} 亿元"

        # 增信措施 - 从封面页提取
        start = cover_text.find("增信情况")
        if start >= 0:
            text = cover_text[start:]
            by_idx = text.find("由")
            provide_idx = text.find("提供")
            if by_idx >= 0 and provide_idx > by_idx:
                guarantor = text[by_idx+1:provide_idx].strip()
                if "担保" in guarantor or "融资" in guarantor or "信用" in guarantor:
                    info["guarantee"] = f"由{guarantor}提供担保"[:80]

        # === 从正文提取（补充）===
        # 注册规模（如果封面没有）- 支持多种格式
        if not info["register_scale"]:
            # 模式 1：注册***不超过 X 亿元（最简单模式）
            match = re.search(r"注册.*?不超过.*?(\d+(?:\.\d+)?)\s*亿", clean_text)
            if match:
                info["register_scale"] = f"{match.group(1)} 亿元"
            # 模式 2：直接数字（如"注册金额 10 亿元"）
            else:
                match = re.search(r"注册 [金额规模总额]?.*?(\d+(?:\.\d+)?)\s*亿", clean_text)
                if match:
                    info["register_scale"] = f"{match.group(1)} 亿元"

        # 发行总额/本期发行规模（如果封面没有）- 支持多种格式
        if not info["issue_scale"]:
            # 模式 1：本期发行不超过 X 亿元
            match = re.search(r"本期发行.*?不超过.*?(\d+(?:\.\d+)?)\s*亿", clean_text)
            if match:
                info["issue_scale"] = f"{match.group(1)} 亿元"
            # 模式 2：本期发行 X 亿元
            else:
                match = re.search(r"本期发行 [规模金额总额]?.*?(\d+(?:\.\d+)?)\s*亿", clean_text)
                if match:
                    info["issue_scale"] = f"{match.group(1)} 亿元"
            # 模式 3：发行规模不超过 X 亿元
            if not info["issue_scale"]:
                match = re.search(r"发行规模.*?不超过.*?(\d+(?:\.\d+)?)\s*亿", clean_text)
                if match:
                    info["issue_scale"] = f"{match.group(1)} 亿元"
            # 模式 4：发行规模为 X 亿元
            if not info["issue_scale"]:
                match = re.search(r"发行规模为.*?(\d+(?:\.\d+)?)\s*亿", clean_text)
                if match:
                    info["issue_scale"] = f"{match.group(1)} 亿元"
            # 模式 5：本期债券面值总额不超过 X 亿元
            if not info["issue_scale"]:
                match = re.search(r"本期债券.*?不超过.*?(\d+(?:\.\d+)?)\s*亿", clean_text)
                if match:
                    info["issue_scale"] = f"{match.group(1)} 亿元"

        # 债券期限 - 避免匹配年份，支持"附选择权"格式
        match = re.search(r"债券期限 [为：:]?\s*(\d+)\s*年", clean_text)
        if match and not match.group(1).startswith('20'):
            info["bond_term"] = f"{match.group(1)} 年"
        else:
            match = re.search(r"本期债券期限.*?(\d+)\s*年", clean_text)
            if match and not match.group(1).startswith('20'):
                info["bond_term"] = f"{match.group(1)} 年"

        # 票面利率
        match = re.search(r"票面利率 [为：:]?\s*([\d\.]+)", clean_text)
        if match:
            info["interest_rate"] = f"{match.group(1)}%"

        # 还本付息方式
        match = re.search(r"还本付息方式 [为：:]?\s*(.+?)(?:。|；|第)", clean_text)
        if match:
            info["repayment_method"] = match.group(1).strip()[:50]
        else:
            # 尝试其他模式
            if "按年付息" in clean_text and "到期一次还本" in clean_text:
                info["repayment_method"] = "按年付息，到期一次还本"
            elif "按年付息" in clean_text and "一次还本" in clean_text:
                info["repayment_method"] = "按年付息，到期一次还本"

        # 增信措施 - 从正文提取（如果封面没有）
        if not info["guarantee"]:
            # 模式 1：增信情况
            match = re.search(r"增信措施 [为：:]?\s*本期债券 (?:无担保 | 无)", clean_text)
            if match:
                info["guarantee"] = "无担保"
            else:
                # 模式 2：由 XXX 提供担保
                start = clean_text.find("增信")
                if start >= 0:
                    text = clean_text[start:start+200]
                    by_idx = text.find("由")
                    provide_idx = text.find("提供")
                    if by_idx >= 0 and provide_idx > by_idx:
                        guarantor = text[by_idx+1:provide_idx].strip()
                        if "担保" in guarantor or "融资" in guarantor or "信用" in guarantor:
                            info["guarantee"] = f"由{guarantor}提供担保"[:80]

        # 发行人全称 - 从第二节提取
        section2 = self.sections.get("二", "")
        if section2:
            clean_section2 = section2.replace('\n', '').replace('  ', ' ')
            pattern_issuer = r"发行人全称 [为：:]?([^.。]+)"
            match = re.search(pattern_issuer, clean_section2)
            if match:
                info["issuer"] = match.group(1).strip()

        # 主体信用评级
        match = re.search(r"发行人主体信用等级 [为：:]?\s*([A-Z\+]+)", clean_text)
        if match:
            info["credit_rating"] = match.group(1).strip()

        # 债券信用评级
        match = re.search(r"(?:本期)?债券 [信用]? 等级 [为：:]?\s*([A-Z\+]+|无)", clean_text)
        if match:
            info["bond_rating"] = match.group(1).strip()

        return info

    def generate_notes(self, output_dir: str) -> list:
        """生成所有笔记文件"""
        generated_files = []

        # 1. 发行条款笔记
        terms_file = self._generate_bond_terms_note(output_dir)
        if terms_file:
            generated_files.append(terms_file)

        # 2. 募集资金运用笔记
        fund_file = self._generate_fund_usage_note(output_dir)
        if fund_file:
            generated_files.append(fund_file)

        # 3. 发行人基本情况笔记
        issuer_file = self._generate_issuer_profile_note(output_dir)
        if issuer_file:
            generated_files.append(issuer_file)

        # 4. 财务分析笔记
        finance_file = self._generate_financial_analysis_note(output_dir)
        if finance_file:
            generated_files.append(finance_file)

        return generated_files

    def _extract_fund_usage(self) -> dict:
        """提取募集资金运用信息"""
        section3 = self.sections.get("三", "")
        if not section3:
            # 尝试从 full_text 中查找第三节
            start = self.full_text.find("第三节")
            end = self.full_text.find("第四节")
            if start > 0 and end > start:
                section3 = self.full_text[start:end]

        clean_text = section3.replace('\n', '')

        usage = {
            "total_amount": "",
            "usage_plan": "",
            "project_list": [],
            "debt_repayment": "",
            "supplement_flow": ""
        }

        # 募集资金总额 - 支持多种格式
        # 模式 1：本期债券发行金额为不超过 X 亿元
        match = re.search(r"本期债券 (?:发行金额 | 募集资金 | 发行规模) [为额]?[不]*超过 [人民币]*\s*(\d+(?:\.\d+)?)\s*亿", clean_text)
        if match:
            usage["total_amount"] = f"{match.group(1)} 亿元"
        # 模式 2：注册总额不超过 X 亿元，可一次发行或分期发行
        else:
            match = re.search(r"注册总额不超过 [人民币]*\s*(\d+(?:\.\d+)?)\s*亿", clean_text)
            if match:
                usage["total_amount"] = f"{match.group(1)} 亿元"
        # 模式 3：直接匹配"X 亿元"
        if not usage["total_amount"]:
            match = re.search(r"本期发行 [金额规模]?[为额]*[不]*超过.*?(\d+(?:\.\d+)?)\s*亿", clean_text)
            if match:
                usage["total_amount"] = f"{match.group(1)} 亿元"

        # 资金用途概述
        match = re.search(r"募集资金扣除发行费用后 [，,] 拟 (.*?)(?:根据 | 二、| 三、| 四、| 募集资金)", clean_text)
        if match:
            usage["usage_plan"] = match.group(1).strip()[:300]

        # 偿还有息债务 - 支持多种模式
        # 模式 1：募集资金 X 亿元拟用于偿还有息债务
        match = re.search(r"募集资金 (\d+(?:\.\d+)?)\s*亿元拟用于偿还", clean_text)
        if match:
            usage["debt_repayment"] = f"{match.group(1)} 亿元"
        # 模式 2：本期债券募集资金 X 亿元拟用于偿还到期债务
        else:
            match = re.search(r"募集资金.*?偿还.*?(\d+(?:\.\d+)?)\s*亿元", clean_text)
            if match:
                usage["debt_repayment"] = f"{match.group(1)} 亿元"
        # 模式 3：从表格中提取（偿还到期债务 X.XX 亿元）
        if not usage["debt_repayment"]:
            match = re.search(r"偿还.*?(\d+(?:\.\d+)?)\s*亿", clean_text)
            if match:
                usage["debt_repayment"] = f"{match.group(1)} 亿元"
        # 模式 4：从全文查找（fallback）
        if not usage["debt_repayment"]:
            match = re.search(r"(\d+(?:\.\d+)?)\s*亿元用于偿还有息负债", self.full_text)
            if match:
                usage["debt_repayment"] = f"{match.group(1)} 亿元"

        # 补充流动资金 - 支持多种模式
        # 模式 1：募集资金 X 亿元用于补充流动资金
        match = re.search(r"募集资金 (\d+(?:\.\d+)?)\s*亿元 [拟]*用于补充流动资金", clean_text)
        if match:
            usage["supplement_flow"] = f"{match.group(1)} 亿元"
        # 模式 2：X 亿元用于补充公司...日常生产经营所需流动资金
        else:
            match = re.search(r"(\d+(?:\.\d+)?)\s*亿元 [拟]*用于补充 [^\d]{0,30}流动资金", clean_text)
            if match:
                usage["supplement_flow"] = f"{match.group(1)} 亿元"
        # 模式 3：补充流动资金 X 亿元
        if not usage["supplement_flow"]:
            match = re.search(r"补充流动资金.*?(\d+(?:\.\d+)?)\s*亿", clean_text)
            if match:
                usage["supplement_flow"] = f"{match.group(1)} 亿元"
        # 模式 4：从全文查找（fallback）
        if not usage["supplement_flow"]:
            match = re.search(r"(\d+(?:\.\d+)?)\s*亿元用于补充流动资金", self.full_text)
            if match:
                usage["supplement_flow"] = f"{match.group(1)} 亿元"

        return usage

    def _extract_issuer_info(self) -> dict:
        """提取发行人基本信息"""
        # 逐页扫描 PDF，找到包含发行人基本信息的页面
        issuer_text = ""
        for page in self.doc:
            text = page.get_text()
            # 查找包含"注册名称"或"注册资本"且包含"发行人基本情况"的页面
            if ('注册资本' in text and '万元' in text) or ('注册名称' in text and '法定代表人' in text):
                issuer_text = text
                break

        # 如果还没找到，尝试从 full_text 中查找第四节
        if not issuer_text or len(issuer_text) < 500:
            start = self.full_text.find("第四节发行人基本情况")
            if start > 0:
                # 向后查找 5000 字符
                issuer_text = self.full_text[start:start+5000]

        issuer = {
            "registered_capital": "",
            "paid_in_capital": "",
            "legal_representative": "",
            "establishment_date": "",
            "unified_social_credit_code": "",
            "registered_address": "",
            "office_address": "",
            "actual_controller": "",
            "controlling_shareholder": ""
        }

        # 清理文本，保留基本结构
        clean_text = issuer_text.replace('\n', ' ')
        clean_text = re.sub(r'\s+', ' ', clean_text)

        # 注册资本 - 支持"74,000 万元"、"人民币 50,000.00 万元"格式
        match = re.search(r'注册资本\s*(?:人民币\s*)?([\d,]+\.?\d*)\s*万元', clean_text)
        if match:
            capital = match.group(1).replace(',', '')
            issuer["registered_capital"] = f"{float(capital):.0f}万元"
        else:
            match = re.search(r'注册资本\s*(?:人民币\s*)?([\d,]+\.?\d*)\s*亿元', clean_text)
            if match:
                capital = match.group(1).replace(',', '')
                issuer["registered_capital"] = f"{float(capital):.2f}亿元"

        # 实缴资本 - 支持"人民币 44,802.15 万元"格式
        match = re.search(r'实缴资本\s*(?:人民币\s*)?([\d,]+\.?\d*)\s*万元', clean_text)
        if match:
            capital = match.group(1).replace(',', '')
            issuer["paid_in_capital"] = f"{float(capital):.0f}万元"
        else:
            match = re.search(r'实缴资本\s*(?:人民币\s*)?([\d,]+\.?\d*)\s*亿元', clean_text)
            if match:
                capital = match.group(1).replace(',', '')
                issuer["paid_in_capital"] = f"{float(capital):.2f}亿元"

        # 法定代表人
        match = re.search(r'法定代表人\s*(\S+)', issuer_text)
        if match:
            issuer["legal_representative"] = match.group(1).strip()[:20]

        # 成立日期 - 支持空格分隔的日期格式（如"2020 年 7 月 6 日"）
        match = re.search(r'设立日期\s*([\d\s\u5e74\u6708\u65e5]+)', issuer_text)
        if match:
            date_str = match.group(1).strip()
            issuer["establishment_date"] = re.sub(r'\s+', '', date_str)
        else:
            match = re.search(r'成立日期\s*([\d\s\u5e74\u6708\u65e5]+)', issuer_text)
            if match:
                date_str = match.group(1).strip()
                issuer["establishment_date"] = re.sub(r'\s+', '', date_str)

        # 统一社会信用代码
        match = re.search(r'统一社会信用代码\s*([A-Z0-9]+)', issuer_text)
        if match:
            issuer["unified_social_credit_code"] = match.group(1)

        # 注册地址/住所 - 支持多种格式
        # 模式 1：住所（注册地）
        match = re.search(r'住所 [（(] 注册地 [）)]?\s*(.+?)\s*(?:邮政|办公地址|所在)', issuer_text, re.DOTALL)
        if match:
            issuer["registered_address"] = match.group(1).strip().replace('\n', '')[:100]
        # 模式 2：注册地址
        elif not issuer["registered_address"]:
            match = re.search(r'注册地址\s*[为：:]?\s*(.+?)\n', issuer_text)
            if match:
                issuer["registered_address"] = match.group(1).strip()[:100]
        # 模式 3：住所
        elif not issuer["registered_address"]:
            match = re.search(r'住所\s*[为：:]?\s*(.+?)\s*(?:，|。|办公)', issuer_text)
            if match:
                issuer["registered_address"] = match.group(1).strip()[:100]

        # 办公地址
        match = re.search(r'办公地址\s*(.+?)\n', issuer_text)
        if match:
            issuer["office_address"] = match.group(1).strip()[:100]
        else:
            match = re.search(r'办公地址\s*(.+?)\s*(?:邮政|所在)', issuer_text)
            if match:
                issuer["office_address"] = match.group(1).strip()[:100]

        return issuer

    def _extract_financial_data(self) -> dict:
        """提取主要财务数据"""
        financial = {
            "total_assets_2024": "",
            "total_assets_2023": "",
            "total_assets_2022": "",
            "total_liabilities_2024": "",
            "total_liabilities_2023": "",
            "total_liabilities_2022": "",
            "net_equity_2024": "",
            "net_equity_2023": "",
            "net_equity_2022": "",
            "operating_revenue_2024": "",
            "operating_revenue_2023": "",
            "operating_revenue_2022": "",
            "net_profit_2024": "",
            "net_profit_2023": "",
            "net_profit_2022": "",
            "asset_liability_ratio_2024": "",
            "asset_liability_ratio_2023": "",
            "asset_liability_ratio_2022": ""
        }

        # 查找资产负债表数据 - 逐页扫描
        for page in self.doc:
            text = page.get_text()
            if '合并资产负债表' in text:
                lines = text.split('\n')

                for i, line in enumerate(lines):
                    line = line.strip()

                    # 资产总计（排除"非流动资产合计"和"流动资产合计"）
                    if line == '资产总计':
                        # 提取后面三行数字
                        nums = []
                        for j in range(i+1, min(i+10, len(lines))):
                            next_line = lines[j].strip()
                            # 检查是否是数字行
                            num_match = re.match(r'^([\d,]+\.?\d*)$', next_line)
                            if num_match:
                                nums.append(num_match.group(1).replace(',', ''))
                            elif next_line and not num_match:
                                # 遇到非数字行，停止
                                if nums:
                                    break
                        if len(nums) >= 3:
                            financial["total_assets_2024"] = f"{nums[0]}万元"
                            financial["total_assets_2023"] = f"{nums[1]}万元"
                            financial["total_assets_2022"] = f"{nums[2]}万元"

                    # 负债合计
                    if line == '负债合计':
                        nums = []
                        for j in range(i+1, min(i+10, len(lines))):
                            next_line = lines[j].strip()
                            num_match = re.match(r'^([\d,]+\.?\d*)$', next_line)
                            if num_match:
                                nums.append(num_match.group(1).replace(',', ''))
                            elif next_line and not num_match:
                                if nums:
                                    break
                        if len(nums) >= 3:
                            financial["total_liabilities_2024"] = f"{nums[0]}万元"
                            financial["total_liabilities_2023"] = f"{nums[1]}万元"
                            financial["total_liabilities_2022"] = f"{nums[2]}万元"

                    # 所有者权益合计
                    if '所有者权益合计' in line or line == '所有者权益':
                        nums = []
                        for j in range(i+1, min(i+10, len(lines))):
                            next_line = lines[j].strip()
                            num_match = re.match(r'^([\d,]+\.?\d*)$', next_line)
                            if num_match:
                                nums.append(num_match.group(1).replace(',', ''))
                            elif next_line and not num_match:
                                if nums:
                                    break
                        if len(nums) >= 3:
                            financial["net_equity_2024"] = f"{nums[0]}万元"
                            financial["net_equity_2023"] = f"{nums[1]}万元"
                            financial["net_equity_2022"] = f"{nums[2]}万元"

        # 查找利润表数据
        for page in self.doc:
            text = page.get_text()
            if '合并利润表' in text or ('利润表' in text and '合并' not in text):
                lines = text.split('\n')

                for i, line in enumerate(lines):
                    line = line.strip()

                    # 营业总收入或营业收入（排除"其中："行）
                    if ('营业总收入' in line or '营业收入' in line) and '其中：' not in line and '合计' not in line:
                        nums = []
                        for j in range(i+1, min(i+10, len(lines))):
                            next_line = lines[j].strip()
                            num_match = re.match(r'^([\d,]+\.?\d*)$', next_line)
                            if num_match:
                                nums.append(num_match.group(1).replace(',', ''))
                            elif next_line and not num_match:
                                if nums:
                                    break
                        if len(nums) >= 3:
                            financial["operating_revenue_2024"] = f"{nums[0]}万元"
                            financial["operating_revenue_2023"] = f"{nums[1]}万元"
                            financial["operating_revenue_2022"] = f"{nums[2]}万元"

                    # 净利润（排除带括号的解释行）
                    if '净利润' in line and '(' not in line and '其中：' not in line:
                        nums = []
                        for j in range(i+1, min(i+10, len(lines))):
                            next_line = lines[j].strip()
                            num_match = re.match(r'^([\d,]+\.?\d*)$', next_line)
                            if num_match:
                                nums.append(num_match.group(1).replace(',', ''))
                            elif next_line and not num_match:
                                if nums:
                                    break
                        if len(nums) >= 3:
                            financial["net_profit_2024"] = f"{nums[0]}万元"
                            financial["net_profit_2023"] = f"{nums[1]}万元"
                            financial["net_profit_2022"] = f"{nums[2]}万元"

        # 计算资产负债率
        def calc_ratio(assets, liabilities):
            if not assets or not liabilities:
                return ""
            try:
                a = float(re.search(r"([\d.]+)", assets).group(1))
                l = float(re.search(r"([\d.]+)", liabilities).group(1))
                if a > 0:
                    return f"{(l/a*100):.1f}%"
            except:
                pass
            return ""

        financial["asset_liability_ratio_2024"] = calc_ratio(financial["total_assets_2024"], financial["total_liabilities_2024"])
        financial["asset_liability_ratio_2023"] = calc_ratio(financial["total_assets_2023"], financial["total_liabilities_2023"])
        financial["asset_liability_ratio_2022"] = calc_ratio(financial["total_assets_2022"], financial["total_liabilities_2022"])

        return financial

    def _generate_bond_terms_note(self, output_dir: str) -> str:
        """生成发行条款笔记"""
        info = self.extract_key_info()

        # 从文件名提取债券全称和简称
        bond_full_name = f"{info['issuer']}2024 年面向专业投资者非公开发行公司债券（第一期）"
        bond_short_name = f"{info['issuer'][:2]}债 01"

        template = f"""---
created: {datetime.now().strftime('%Y-%m-%d')}
type: bond_terms
tags: [债券/发行条款，#{info['bond_type']}，{info['year'].replace('年','')}]
---

# {info['issuer']} - 发行条款

## 基本信息

| 项目 | 内容 |
|------|------|
| 发行人全称 | {info['issuer']} |
| 债券全称 | {bond_full_name} |
| 债券简称 | {bond_short_name} |
| 发行日期 | {info['year'].replace('年', '')}年 |
| 注册规模 | {info['register_scale'] or ''} |
| 本期发行规模 | {info['issue_scale'] or ''} |
| 债券期限 | {info['bond_term'] or ''} |
| 票面利率 | {info['interest_rate'] or ''} |
| 增信措施 | {info['guarantee'] or '无'} |
| 主体评级 | {info['credit_rating'] or ''} |
| 债项评级 | {info['bond_rating'] or ''} |
| 债券类型 | {info['bond_type']} |
| 期数 | {info['period']} |

## 增信措施详情

{info['guarantee'] if info['guarantee'] else '本期债券无增信措施'}

## 还本付息方式

{info['repayment_method'] if info['repayment_method'] else '按年付息，到期一次还本'}

## 特殊条款

{{如有回售、赎回等特殊条款，在此描述}}

---
**来源**: {self.pdf_name}
**提取日期**: {datetime.now().strftime('%Y-%m-%d')}
"""

        output_path = os.path.join(output_dir, "01-发行条款", f"{info['issuer']}-发行条款.md")
        os.makedirs(os.path.dirname(output_path), exist_ok=True)
        with open(output_path, 'w', encoding='utf-8') as f:
            f.write(template)
        return output_path

    def _generate_fund_usage_note(self, output_dir: str) -> str:
        """生成募集资金运用笔记"""
        info = self.extract_key_info()
        usage = self._extract_fund_usage()

        # 计算占比
        total = usage.get("total_amount", "")
        debt = usage.get("debt_repayment", "")
        flow = usage.get("supplement_flow", "")

        # 提取数字计算占比
        def extract_num(s):
            if not s:
                return 0
            match = re.search(r"(\d+(?:\.\d+)?)", s)
            return float(match.group(1)) if match else 0

        debt_num = extract_num(debt)
        flow_num = extract_num(flow)
        total_num = extract_num(total)

        # 如果 total 为空，尝试从 debt+flow 计算
        if total_num == 0 and (debt_num > 0 or flow_num > 0):
            total_num = debt_num + flow_num
            total = f"{total_num}亿元"

        debt_ratio = f"{(debt_num/total_num*100):.1f}%" if total_num > 0 else ""
        flow_ratio = f"{(flow_num/total_num*100):.1f}%" if total_num > 0 else ""

        # 资金用途概述，移除"偿还到期债务及补充流动资金"等笼统描述
        usage_plan = usage.get('usage_plan', '')
        if usage_plan and len(usage_plan) < 30:
            usage_plan = '详见募集说明书原文'

        template = f"""---
created: {datetime.now().strftime('%Y-%m-%d')}
type: fund_usage
tags: [债券/资金用途，#{info['bond_type']}]
---

# {info['issuer']} - 募集资金运用

## 本期发行规模

- 发行规模：{info['issue_scale'] or total or ''}

## 募集资金使用计划

| 用途 | 金额（亿元） | 占比 |
|-----|------------|------|
| 偿还有息债务 | {debt or '/'} | {debt_ratio or '/'} |
| 补充流动资金 | {flow or '/'} | {flow_ratio or '/'} |
| **合计** | {total or '/'} | 100% |

## 资金用途概述

{usage_plan if usage_plan and usage_plan != '详见募集说明书原文' else '详见募集说明书原文'}

## 项目使用情况

### 项目建设类

{{项目建设类信息，包括项目名称、投资总额、拟使用募集资金、合法性文件等}}

### 偿还项目贷款类

{{偿还贷款明细}}

## 募集资金管理制度

{{描述募集资金专户管理、使用审批等制度}}

## 前次募集资金使用情况

{{如有前次募集资金，描述使用情况}}

---
**来源**: {self.pdf_name}
**提取日期**: {datetime.now().strftime('%Y-%m-%d')}
"""

        output_path = os.path.join(output_dir, "02-募集资金运用", f"{info['issuer']}-募集资金运用.md")
        os.makedirs(os.path.dirname(output_path), exist_ok=True)
        with open(output_path, 'w', encoding='utf-8') as f:
            f.write(template)
        return output_path

    def _generate_issuer_profile_note(self, output_dir: str) -> str:
        """生成发行人概况笔记"""
        info = self.extract_key_info()
        issuer_data = self._extract_issuer_info()

        template = f"""---
created: {datetime.now().strftime('%Y-%m-%d')}
type: issuer_profile
tags: [发行人/概况，#{info['bond_type']}]
---

# {info['issuer']} - 概况

## 基本信息

| 项目 | 内容 |
|------|------|
| 发行人全称 | {info['issuer']} |
| 统一社会信用代码 | {issuer_data.get('unified_social_credit_code', '')} |
| 注册资本 | {issuer_data.get('registered_capital', '')} |
| 实缴资本 | {issuer_data.get('paid_in_capital', '')} |
| 法定代表人 | {issuer_data.get('legal_representative', '')} |
| 成立日期 | {issuer_data.get('establishment_date', '')} |
| 注册地址 | {issuer_data.get('registered_address', '')} |
| 办公地址 | {issuer_data.get('office_address', '')} |
| 实际控制人 | {issuer_data.get('actual_controller', '')} |
| 控股股东 | {issuer_data.get('controlling_shareholder', '')} |

## 历史沿革

| 时间 | 事项 | 详情 |
|------|------|------|
| | 设立 | |

## 股权结构

{{股权结构图}}

## 重要权益投资

### 一级子公司

| 子公司名称 | 持股比例 | 注册资本 | 主营业务 |
|-----------|---------|---------|---------|
| | | | |

## 主营业务分析

详见：[[{info['issuer']}-主营业务]]

---
**来源**: {self.pdf_name}
**提取日期**: {datetime.now().strftime('%Y-%m-%d')}
"""

        output_path = os.path.join(output_dir, "03-发行人基本情况", f"{info['issuer']}-概况.md")
        os.makedirs(os.path.dirname(output_path), exist_ok=True)
        with open(output_path, 'w', encoding='utf-8') as f:
            f.write(template)
        return output_path

    def _generate_financial_analysis_note(self, output_dir: str) -> str:
        """生成财务分析笔记"""
        info = self.extract_key_info()
        financial = self._extract_financial_data()

        template = f"""---
created: {datetime.now().strftime('%Y-%m-%d')}
type: financial_analysis
tags: [财务/分析，#{info['bond_type']}]
---

# {info['issuer']} - 财务分析

## 主要财务数据

| 项目 | 2024 年 | 2023 年 | 2022 年 |
|------|---------|---------|---------|
| 资产总计 | {financial.get('total_assets_2024', '')} | {financial.get('total_assets_2023', '')} | {financial.get('total_assets_2022', '')} |
| 负债总计 | {financial.get('total_liabilities_2024', '')} | {financial.get('total_liabilities_2023', '')} | {financial.get('total_liabilities_2022', '')} |
| 所有者权益 | {financial.get('net_equity_2024', '')} | {financial.get('net_equity_2023', '')} | {financial.get('net_equity_2022', '')} |
| 营业收入 | {financial.get('operating_revenue_2024', '')} | {financial.get('operating_revenue_2023', '')} | {financial.get('operating_revenue_2022', '')} |
| 净利润 | {financial.get('net_profit_2024', '')} | {financial.get('net_profit_2023', '')} | {financial.get('net_profit_2022', '')} |
| 经营活动现金流净额 | | | |

## 偿债能力指标

| 指标 | 2024 年 | 2023 年 | 2022 年 |
|------|---------|---------|---------|
| 资产负债率 | {financial.get('asset_liability_ratio_2024', '')} | {financial.get('asset_liability_ratio_2023', '')} | {financial.get('asset_liability_ratio_2022', '')} |
| 流动比率 | | | |
| 速动比率 | | | |
| EBITDA 利息保障倍数 | | | |

## 资产结构分析

### 经营性资产

| 项目 | 金额 | 占比 | 说明 |
|------|------|------|------|
| | | | |

### 非经营性资产

| 项目 | 金额 | 占比 | 说明 |
|------|------|------|------|
| | | | |

### 政府性资产识别

| 资产类型 | 金额 | 收益特征 | 交易对手 |
|---------|------|---------|---------|
| | | □无收益 □低收益 | □政府 □政府部门 □其他 |

---
**来源**: {self.pdf_name}
**提取日期**: {datetime.now().strftime('%Y-%m-%d')}
"""

        output_path = os.path.join(output_dir, "05-资产状况", f"{info['issuer']}-财务分析.md")
        os.makedirs(os.path.dirname(output_path), exist_ok=True)
        with open(output_path, 'w', encoding='utf-8') as f:
            f.write(template)
        return output_path


def main():
    """批量处理 raw 目录下的 PDF"""
    raw_dir = "raw"
    knowledge_dir = "knowledge"

    pdf_files = [f for f in os.listdir(raw_dir) if f.endswith(".pdf")]
    print(f"发现 {len(pdf_files)} 份 PDF 文件\n")

    all_generated = []
    for pdf_file in pdf_files:
        pdf_path = os.path.join(raw_dir, pdf_file)
        print(f"处理：{pdf_file}")

        extractor = ProspectusExtractor(pdf_path)
        extractor.open_pdf()
        extractor.parse_issuer_name()
        extractor.parse_bond_info()
        extractor.extract_all_sections()

        # 生成笔记
        generated = extractor.generate_notes(knowledge_dir)
        all_generated.extend(generated)
        print(f"  生成 {len(generated)} 个笔记文件")

        extractor.close_pdf()
        print("-" * 50)

    print(f"\n处理完成！共生成 {len(all_generated)} 个笔记文件")
    return all_generated


if __name__ == "__main__":
    main()
