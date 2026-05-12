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

FUND_USAGE_SECTION_PATTERNS = {
    "start": ["第三节 募集资金运用", "第三节募集资金运用", "三、募集资金运用"],
    "end": ["第四节 发行人基本情况", "第四节发行人基本情况", "四、发行人基本情况"],
}


class FundUsageExtractor(BaseExtractor):
    """募集资金运用提取器"""

    NOTE_TYPE = "fund_usage"
    OUTPUT_DIR = "02-募集资金运用"
    TAGS = ["债券/资金用途"]

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
        self.extract_text()
        clean = self.full_text.replace('\n', '')
        decoded = self._decode_garbled_text(clean)
        all_usages = self._extract_all_usages(clean, decoded)
        total_amount = self._extract_total_amount(clean, decoded)
        return {
            "total_amount": total_amount,
            "all_usages": all_usages,
        }

    def _extract_all_usages(self, clean: str, decoded: str) -> List[Dict[str, str]]:
        """提取所有资金用途及其金额"""
        usages = []
        search_text = clean

        patterns = [
            r"扣除发行费用后[^\n]{0,20}?(\d+(?:,\d{3})*(?:\.\d+)?)\s*万元[^\n]{0,60}?用于[^\n]{0,50}?([^\n，。,，；]+)",
            r"扣除发行费用后[^\n]{0,20}?(\d+(?:\.\d+)?)\s*亿元[^\n]{0,60}?用于[^\n]{0,50}?([^\n，。,，；]+)",
            r"本期债券募集资金[^\n]{0,30}?(\d+(?:\.\d+)?)\s*亿元[^\n]{0,60}?用于[^\n]{0,50}?([^\n，。,，；]+)",
            r"本期公司债券募集资金[^\n]{0,30}?(\d+(?:\.\d+)?)\s*亿元[^\n]{0,60}?用于[^\n]{0,50}?([^\n，。,，；]+)",
            r"本次公司债券募集资金[^\n]{0,30}?(\d+(?:\.\d+)?)\s*亿元[^\n]{0,60}?用于[^\n]{0,50}?([^\n，。,，；]+)",
            r"本期债券计划发行规模[^\n]{0,30}?(\d+(?:\.\d+)?)\s*亿元[^\n]{0,60}?用于[^\n]{0,50}?([^\n，。,，；]+)",
            r"(\d+(?:\.\d+)?)\s*亿元[^\n]{0,30}?用于[^\n]{0,50}?([^\n，。,，；]+)",
            r"(\d+(?:,\d{3})*(?:\.\d+)?)\s*万元[^\n]{0,60}?用于[^\n]{0,50}?([^\n，。,，；]+)",
            r"不超过(\d+(?:\.\d+)?)\s*亿元[^\n]{0,30}?用于[^\n]{0,50}?([^\n，。,，；]+)",
            r"不低于.*?(\d+(?:\.\d+)?)\s*亿元.*?用于[^\n]{0,50}?([^\n，。,，；]+)",
        ]

        for pattern in patterns:
            matches = re.findall(pattern, search_text)
            for match in matches:
                try:
                    amount_str = match[0].replace(',', '')
                    amount = float(amount_str)
                    usage_name = match[1].strip()
                    if '万元' in pattern:
                        amount = amount / 10000
                    if 0.1 <= amount <= 50 and usage_name and len(usage_name) >= 2:
                        if any(kw in usage_name for kw in ['不足', '不可', '不得', '无法', '不能']):
                            continue
                        usage_name = self._clean_usage_name(usage_name)
                        if not usage_name or usage_name == "募集资金用途":
                            continue
                        existing = next((u for u in usages if abs(u["amount"] - amount) < 0.01), None)
                        if not existing:
                            same_name = next((u for u in usages if u["name"] == usage_name), None)
                            if same_name:
                                same_name["amount"] = round(same_name["amount"] + amount, 2)
                            else:
                                usages.append({"amount": amount, "name": usage_name})
                except (ValueError, IndexError):
                    continue

        # 如果文本提取没有得到有效结果，尝试用 pdfplumber 提取汇总表
        if not usages or len(usages) < 3:
            table_usages = self._extract_summary_table()
            if table_usages:
                seen_amounts = set()
                for u in usages:
                    seen_amounts.add(round(u["amount"], 2))
                for u in table_usages:
                    key = round(u["amount"], 2)
                    if key not in seen_amounts:
                        usages.append(u)
                        seen_amounts.add(key)

        # 用发行规模验证提取结果，如果总额偏差过大，尝试表格提取
        if usages:
            total_found = sum(u["amount"] for u in usages)
            issue_scale = self._read_registration_scale_from_bond_terms()
            if issue_scale:
                m = re.search(r"(\d+(?:\.\d+)?)", issue_scale)
                issue_num = float(m.group(1)) if m else 0
                # 如果提取总额超过发行规模的1.5倍，说明提取有问题
                if issue_num > 0 and total_found > issue_num * 1.5:
                    table_usages = self._extract_summary_table()
                    if table_usages:
                        table_total = sum(u["amount"] for u in table_usages)
                        if abs(table_total - issue_num) < abs(total_found - issue_num):
                            usages = table_usages

        # 如果还是没有结果，尝试搜索用途描述
        if not usages:
            for pattern in [
                r"扣除发行费用后[^\n]{0,20}?用于[^\n]{0,40}?([^\n，。,，；]+)",
                r"本期债券募集资金[^\n]{0,30}?用于[^\n]{0,40}?([^\n，。,，；]+)",
            ]:
                match = re.search(pattern, search_text)
                if match:
                    purpose = match.group(1).strip().rstrip('。,.，')
                    if purpose and len(purpose) >= 2:
                        usages.append({"amount": 0, "name": self._clean_usage_name(purpose)})
                        break

        usages.sort(key=lambda x: x["amount"], reverse=True)
        return usages

    def _extract_summary_table(self) -> List[Dict[str, str]]:
        """用 pdfplumber 提取募集资金汇总表（仅针对募集资金运用章节附近的表格）"""
        try:
            import pdfplumber
        except ImportError:
            return []

        # 先用 PyMuPDF 定位募集资金运用章节所在页面范围
        fund_page_range = self._find_fund_usage_page_range()
        if not fund_page_range:
            return []

        start_page, end_page = fund_page_range

        try:
            pdf = pdfplumber.open(self.pdf_path)
        except Exception:
            return []

        items = []
        for page_idx in range(start_page - 1, min(end_page, len(pdf.pages))):
            page = pdf.pages[page_idx]
            tables = page.extract_tables()
            for table in tables:
                if len(table) < 5:
                    continue
                # 检查表头：必须有3-4列
                header = table[0]
                if len(header) < 3:
                    continue
                # 尝试解析表格数据
                table_items = self._parse_summary_table_rows(table)
                items.extend(table_items)

        pdf.close()

        # 合并同类别项（按分类名称而非原始表格名称）
        if items:
            merged = {}
            for row in items:
                category = row["name"]  # 已经是分类后的名称
                if category in merged:
                    merged[category]["amount"] = round(merged[category]["amount"] + row["amount"], 2)
                else:
                    merged[category] = row
            return list(merged.values())
        return []

    def _find_fund_usage_page_range(self):
        """用 PyMuPDF 找到募集资金运用章节的页面范围"""
        import fitz
        try:
            doc = fitz.open(self.pdf_path)
        except Exception:
            return None

        start_page = None
        end_page = None
        total_pages = len(doc)

        for page_num in range(total_pages):
            page = doc[page_num]
            text = page.get_text()
            # 只在正文范围内查找（跳过前15页的目录部分）
            if page_num < 15:
                continue
            if start_page is None and any(kw in text for kw in ['第三节 募集资金运用', '第三节募集资金运用', '募集资金运用\n二', '募集资金的运用']):
                start_page = page_num + 1
            if start_page is not None and end_page is None and any(kw in text for kw in ['第四节 发行人', '第四节发行人']):
                end_page = page_num

        doc.close()

        if not start_page:
            return None

        if end_page is None:
            end_page = total_pages

        # 提取开始页和下一页（汇总表通常跨2页）
        return (start_page, min(start_page + 1, end_page))

    def _parse_summary_table_rows(self, table) -> List[Dict[str, str]]:
        """解析单个汇总表的数据行

        募集资金汇总表通常是分层结构：
        - 分类标题行（如"过去12个月已实施..."）- 无金额
        - 分类小计行 - 有金额和占比
        - 子项行（"其中：XXX公司"）- 有金额和占比

        我们只提取分类小计行，跳过子项。
        """
        items = []
        for i, row in enumerate(table):
            if len(row) < 2:
                continue
            name_cell = str(row[0] or '').strip().replace('\n', '')
            amount_cell = str(row[1] or '').strip()
            ratio_cell = str(row[2] or '').strip() if len(row) > 2 else ''

            try:
                amount = float(amount_cell)
            except (ValueError, TypeError):
                continue

            # 跳过合计/小计/总计/项目行
            if any(kw in name_cell for kw in ['合计', '小计', '总计', '项目']):
                continue
            # 占比为空的分类标题行跳过
            if not ratio_cell:
                continue
            if amount < 0.01 or amount > 50:
                continue

            # 占比应该是百分比数字
            try:
                ratio = float(ratio_cell.replace('%', ''))
                if ratio < 0.1 or ratio > 100:
                    continue
            except (ValueError, TypeError):
                continue

            # 汇总表中的分类行名称通常较短（不超过12字符）
            # 子项行（具体公司名）通常很长（乱码后超过12字符）
            if len(name_cell) > 12:
                continue
            if name_cell.startswith('其中'):
                continue

            category = self._classify_table_row(name_cell, amount, ratio)
            if category:
                items.append({"amount": amount, "name": category})

        return items

    def _classify_table_row(self, name: str, amount: float, ratio: float = None) -> str:
        """根据表格行名称和金额，识别资金用途类别"""
        # 优先使用占比推断（对于汇总表，占比比名称更可靠）
        if ratio is not None:
            if ratio > 45:
                return "增加实收资本"
            elif ratio > 15:
                return "科创领域出资"
            elif ratio > 5:
                return "偿还有息负债"
            else:
                return "其他用途"

        # 无占比信息时，用关键词匹配
        category_keywords = {
            "增加实收资本": ["实收资本", "注册资本", "增加资本"],
            "补充流动资金": ["补充流动", "流动资金", "营运资金", "补流"],
            "偿还有息负债": ["偿还", "有息负债", "偿债", "归还债务"],
            "科创领域出资": ["科创", "科技创新", "创业投资", "产业投资", "股权出资"],
            "置换前期出资": ["置换", "前期"],
            "项目投资": ["项目投资", "建设项目", "项目建设"],
        }

        for category, keywords in category_keywords.items():
            for kw in keywords:
                if kw in name:
                    return category

        if name and len(name) > 0:
            chinese_ratio = sum(1 for c in name if '一' <= c <= '鿿') / max(len(name), 1)
            if chinese_ratio > 0.3:
                return self._clean_usage_name(name)

        return None

    def _clean_usage_name(self, name: str) -> str:
        name = name.strip().rstrip('。,.，')
        invalid_keywords = ['偿债保障', '可变现', '不足', '不可', '不得', '无法', '不能', '风险', '提示']
        if any(kw in name for kw in invalid_keywords):
            return ""
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
        if len(name) > 20:
            keywords = ["偿还", "补充", "投资", "置换", "归还", "建设", "研发", "项目"]
            for kw in keywords:
                idx = name.find(kw)
                if idx >= 0:
                    name = name[idx:idx+20]
                    break
        return name if name else "募集资金用途"

    def _decode_garbled_text(self, text: str) -> str:
        result = text
        for garbled, normal in self.GARBLED_CHARS.items():
            result = result.replace(garbled, normal)
        return result

    def _extract_section_text(self) -> str:
        clean = self.full_text.replace('\n', '')
        section_starts = FUND_USAGE_SECTION_PATTERNS.get("start", [])
        section_ends = FUND_USAGE_SECTION_PATTERNS.get("end", [])
        section_starts.extend(["第三节 募集资金用途", "第三节募集资金用途", "三、 募集资金运用", "募集资金使用计划"])
        section_ends.extend(["募集资金的现金管理"])

        start_idx = -1
        for pattern in section_starts:
            idx = clean.find(pattern)
            if idx >= 0:
                start_idx = idx
                break
        if start_idx < 0:
            return ""

        end_idx = len(clean)
        for pattern in section_ends:
            idx = clean.find(pattern, start_idx + 10)
            if 0 < idx < end_idx:
                end_idx = idx

        return clean[start_idx:end_idx]

    def _extract_total_amount(self, clean: str, decoded: str) -> str:
        cover_text = ""
        if self.doc:
            for i in range(min(5, len(self.doc))):
                cover_text += self.doc[i].get_text()
        cover_clean = cover_text.replace('\n', '') if cover_text else ""

        patterns = [
            r"本期债券发行规模[为是]?\s*(\d+(?:\.\d+)?)\s*亿",
            r"本期债券发行金额[为是]?\s*(\d+(?:\.\d+)?)\s*亿",
            r"本期发行规模[为是]?\s*(\d+(?:\.\d+)?)\s*亿",
        ]

        for pattern in patterns:
            for text in [cover_clean, clean]:
                match = re.search(pattern, text)
                if match:
                    val = float(match.group(1))
                    if 1 <= val <= 50:
                        return f"{val} 亿元"

        section_text = self._extract_section_text()
        if section_text:
            for pattern in patterns:
                match = re.search(pattern, section_text)
                if match:
                    val = float(match.group(1))
                    if 1 <= val <= 50:
                        return f"{val} 亿元"
        return ""

    def _extract_usage_detail(self, clean: str) -> Dict[str, str]:
        result = {"debt": "", "flow": ""}
        section_text = self._extract_section_text()
        if not section_text:
            return result

        detail_text = section_text[:2000]
        for pattern in [r"偿还[有息债务贷款负债]*.*?(\d+(?:\.\d+)?)\s*亿元", r"用于偿还.*?(\d+(?:\.\d+)?)\s*亿元"]:
            match = re.search(pattern, detail_text)
            if match:
                val = float(match.group(1))
                if 1 <= val <= 50:
                    result["debt"] = f"{val} 亿元"
                    break

        for pattern in [r"补充[流动资金营运资金]*.*?(\d+(?:\.\d+)?)\s*亿元", r"用于补充.*?(\d+(?:\.\d+)?)\s*亿元"]:
            match = re.search(pattern, detail_text)
            if match:
                val = float(match.group(1))
                if 1 <= val <= 50:
                    result["flow"] = f"{val} 亿元"
                    break
        return result

    def _read_registration_scale_from_bond_terms(self) -> str:
        bond_terms_dir = os.path.join("knowledge", "01-发行条款")
        if not os.path.exists(bond_terms_dir):
            return ""
        issuer_file = f"{self._issuer_name}-发行条款.md"
        file_path = os.path.join(bond_terms_dir, issuer_file)
        if not os.path.exists(file_path):
            for f in os.listdir(bond_terms_dir):
                if self._issuer_name in f and "发行条款" in f:
                    file_path = os.path.join(bond_terms_dir, f)
                    break
            else:
                return ""
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                content = f.read()
            for field in [r"本期发行规模", r"注册规模"]:
                match = re.search(field + r".*?(\d+(?:\.\d+)?)\s*亿元", content)
                if match:
                    val = float(match.group(1))
                    if 1 <= val <= 50:
                        return f"{val} 亿元"
        except Exception:
            pass
        return ""

    def extract_key_info(self) -> Dict[str, str]:
        self.extract_text()
        clean = self.full_text.replace('\n', '')
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

        total_amount = usage.get("total_amount", "")
        if total_amount:
            match = re.search(r"(\d+(?:\.\d+)?)", total_amount)
            if match:
                val = float(match.group(1))
                if 1 <= val <= 50:
                    info["issue_scale"] = total_amount

        if not info["issue_scale"]:
            for pattern in [
                r"本期债券发行面值总额不超过[人民币]*(\d+(?:\.\d+)?)\s*亿元",
                r"本期债券发行规模[为是]?\s*(\d+(?:\.\d+)?)\s*亿元",
                r"本期发行金额.*?(\d+(?:\.\d+)?)\s*亿",
                r"本期债券发行.*?(\d+(?:\.\d+)?)\s*亿元",
                r"发行总额不超过(\d+(?:\.\d+)?)\s*亿元",
                r"发行规模.*?(\d+(?:\.\d+)?)\s*亿",
            ]:
                match = re.search(pattern, clean)
                if match:
                    val = float(match.group(1))
                    if 1 <= val <= 50:
                        info["issue_scale"] = f"{val} 亿元"
                        break

        if not info["issue_scale"]:
            info["issue_scale"] = self._read_registration_scale_from_bond_terms()

        guarantee_match = re.search(r"(?:担保方式|增信方式).*?(?:保证担保|抵押担保|质押担保|信用)", clean)
        if guarantee_match:
            info["guarantee"] = guarantee_match.group(0)[-10:]
        elif "担保" in clean:
            match = re.search(r"(.*?担保)", clean)
            if match:
                info["guarantee"] = match.group(1)[:20]
        else:
            info["guarantee"] = "信用"

        match = re.search(r"主体评级.*?(AAA|AA\+|AA|AA\-|A\+)", clean)
        if match:
            info["rating_issuer"] = match.group(1)
        match = re.search(r"债项评级.*?(AAA|AA\+|AA|AA\-|A\+)", clean)
        if match:
            info["rating_bond"] = match.group(1)

        return info

    def extract_fund_usage_detail(self) -> str:
        return ""

    def generate_note(self, output_base: str) -> str:
        info = self.extract_key_info()
        usage = self.extract_fund_usage()

        total = usage.get("total_amount", "")
        all_usages = usage.get("all_usages", [])

        def extract_num(s):
            if not s:
                return 0
            match = re.search(r"(\d+(?:\.\d+)?)", s)
            return float(match.group(1)) if match else 0

        issue_scale = info.get('issue_scale', '')
        issue_num = extract_num(issue_scale)
        usage_total = sum(u["amount"] for u in all_usages)

        if issue_num > 0 and usage_total > issue_num:
            ratio = issue_num / usage_total
            for u in all_usages:
                u["amount"] = round(u["amount"] * ratio, 2)
            usage_total = sum(u["amount"] for u in all_usages)

        if all_usages:
            usage_descs = []
            for u in all_usages:
                if u['amount'] > 0.01:
                    usage_descs.append(f"{u['amount']}亿元用于{u['name']}")
            if not usage_descs and issue_num > 0:
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

        valid_usages = [u for u in all_usages if u['amount'] > 0.01]
        if issue_num > 0 and valid_usages:
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
            tags=self.TAGS + [f"#{info['bond_type']}"],
            extra_fields={
                "issuer": info.get("issuer", ""),
                "bond_type": info.get("bond_type", ""),
            }
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

        output_path = os.path.join(output_base, self.OUTPUT_DIR, f"{info['issuer']}-募集资金运用.md")
        self.write_note(output_path, template)
        return output_path


def main():
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
