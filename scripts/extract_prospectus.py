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

        info = {
            "issuer": self.issuer_name,
            "bond_type": self.bond_info.get("type", ""),
            "period": self.bond_info.get("period", ""),
            "year": self.bond_info.get("year", ""),
            "register_scale": "",
            "issue_scale": "",
            "bond_term": "",
            "guarantee": "",
            "fund_usage": []
        }

        # 清理文本 - 只移除换行符，保留空格
        clean_text = self.full_text.replace('\n', '')

        # 注册规模
        match = re.search(r"注册金额.*?(\d+) 亿", clean_text)
        if match:
            info["register_scale"] = f"{match.group(1)} 亿元"
        else:
            match = re.search(r"注册规模.*?(\d+) 亿", clean_text)
            if match:
                info["register_scale"] = f"{match.group(1)} 亿元"

        # 发行总额/本期发行规模
        match = re.search(r"本期发行 [金额总额].*?(\d+) 亿", clean_text)
        if match:
            info["issue_scale"] = f"{match.group(1)} 亿元"
        else:
            match = re.search(r"发行 [金额总额].*?(\d+) 亿", clean_text)
            if match:
                info["issue_scale"] = f"{match.group(1)} 亿元"

        # 债券期限 - 避免匹配年份
        match = re.search(r"债券期限为 (\d+) 年", clean_text)
        if match and not match.group(1).startswith('20'):
            info["bond_term"] = f"{match.group(1)} 年"
        else:
            match = re.search(r"债券期限.*?(\d+) 年", clean_text)
            if match and not match.group(1).startswith('20'):
                info["bond_term"] = f"{match.group(1)} 年"

        # 增信措施 - 查找"由 XXX 提供担保"，确保是担保机构
        guarantee_match = re.search(r"增信情况.*?由 (.*?) 提供", self.full_text, re.DOTALL)
        if guarantee_match:
            text = guarantee_match.group(1).strip()
            if "担保" in text or "融资" in text or "信用" in text:
                info["guarantee"] = f"由{text}提供"[:80]
        else:
            # 简单提取
            start = self.full_text.find("由")
            end = self.full_text.find("提供", start)
            if start >= 0 and end > start:
                text = self.full_text[start+1:end].strip()
                if "担保" in text or "融资" in text or "信用" in text:
                    info["guarantee"] = f"由{text}提供"[:80]

        # 发行人全称
        section2 = self.sections.get("二", "")
        clean_section2 = section2.replace('\n', '').replace('  ', ' ')
        pattern_issuer = r"发行人全称 [为：:]?([^.。]+)"
        match = re.search(pattern_issuer, clean_section2)
        if match:
            info["issuer"] = match.group(1).strip()

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

    def _generate_bond_terms_note(self, output_dir: str) -> str:
        """生成发行条款笔记"""
        info = self.extract_key_info()

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
| 债券全称 | |
| 债券简称 | |
| 发行日期 | |
| 注册规模 | {info['register_scale'] or ''} |
| 本期发行规模 | {info['issue_scale'] or ''} |
| 债券期限 | {info['bond_term'] or ''} |
| 票面利率 | |
| 增信措施 | {info['guarantee'] or ''} |
| 债券类型 | {info['bond_type']} |
| 期数 | {info['period']} |

## 增信措施详情

{{如有增信措施，详细描述}}

## 还本付息方式

{{描述还本付息方式}}

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
        section3 = self.sections.get("三", "")

        template = f"""---
created: {datetime.now().strftime('%Y-%m-%d')}
type: fund_usage
tags: [债券/资金用途，#{info['bond_type']}]
---

# {info['issuer']} - 募集资金运用

## 本期发行规模

- 发行规模：{info['issue_scale'] or info['register_scale'] or ''}

## 募集资金使用计划

| 用途 | 金额（亿元） | 占比 |
|-----|------------|------|
| | | |
| **合计** | | 100% |

## 项目使用情况

### 项目建设类

| 项目名称 | 投资总额 | 拟使用募集资金 | 合法性文件 |
|---------|---------|---------------|-----------|
| | | | |

### 偿还项目贷款类

| 贷款银行 | 贷款合同编号 | 贷款余额 | 拟偿还金额 |
|---------|-------------|---------|-----------|
| | | | |

## 募集资金管理制度

{{描述募集资金专户管理、使用审批等制度}}

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
        section4 = self.sections.get("四", "")

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
| 统一社会信用代码 | |
| 注册资本 | |
| 实缴资本 | |
| 法定代表人 | |
| 成立日期 | |
| 注册地址 | |
| 办公地址 | |
| 实际控制人 | |
| 控股股东 | |

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

        template = f"""---
created: {datetime.now().strftime('%Y-%m-%d')}
type: financial_analysis
tags: [财务/分析，#{info['bond_type']}]
---

# {info['issuer']} - 财务分析

## 主要财务数据

| 项目 | 20{{}}年 | 20{{}}年 | 20{{}}年 |
|------|---------|---------|---------|
| 资产总计 | | | |
| 负债总计 | | | |
| 所有者权益 | | | |
| 营业收入 | | | |
| 净利润 | | | |
| 经营活动现金流净额 | | | |

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

## 偿债能力指标

| 指标 | 20{{}}年 | 20{{}}年 | 20{{}}年 |
|------|---------|---------|---------|
| 资产负债率 | % | % | % |
| 流动比率 | | | |
| 速动比率 | | | |
| EBITDA 利息保障倍数 | | | |

---
**来源**: {self.pdf_name}
**提取日期**: {datetime.now().strftime('%Y-%m-%d')}
"""

        output_path = os.path.join(output_dir, "04-财务状况", f"{info['issuer']}-财务分析.md")
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
