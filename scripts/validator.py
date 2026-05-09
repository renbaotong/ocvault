#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
数据校验模块 — 检查笔记间的数据一致性

校验规则：
1. 资产平衡：资产总计 = 流动资产合计 + 非流动资产合计（05-资产结构分析）
2. 资金用途：募集资金用途比例合计应接近 100%（02-募集资金运用）
3. 规模一致性：同一发行人的发行规模在各笔记中应一致（01 vs 02）
4. 必填字段：各类型笔记的必填字段检查
"""

import os
import re
import json
import sys
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass, asdict
from datetime import datetime


# ============================================================================
# 数据类型
# ============================================================================

@dataclass
class ValidationIssue:
    """校验问题"""
    issuer: str
    note_type: str
    rule: str
    severity: str  # "error" | "warning"
    message: str


# ============================================================================
# 校验规则
# ============================================================================

class FinancialBalanceChecker:
    """资产平衡校验：资产总计 = 流动资产合计 + 非流动资产合计"""

    RULE_NAME = "financial_balance"

    @staticmethod
    def check(content: str, issuer: str) -> List[ValidationIssue]:
        issues = []
        lines = content.split('\n')

        current_total = {}  # col_idx -> value
        asset_total = {}    # col_idx -> value
        non_current_items = []  # col_idx -> list of values per year

        # The columns we care about: col 1=2025, col 3=2024, col 5=2023
        TARGET_COLS = {1: '2025', 3: '2024', 5: '2023'}
        CURRENT_ROW_FOUND = False

        for line in lines:
            if '|' not in line:
                continue
            cells = [c.strip().strip('*') for c in line.split('|')[1:-1]]
            if len(cells) < 7:
                continue

            project = cells[0].strip('*')

            if '流动资产合计' in project:
                for col_idx in TARGET_COLS:
                    if col_idx < len(cells):
                        val = parse_number(cells[col_idx])
                        if val:
                            current_total[col_idx] = val
                CURRENT_ROW_FOUND = True
            elif '资产总计' in project:
                for col_idx in TARGET_COLS:
                    if col_idx < len(cells):
                        val = parse_number(cells[col_idx])
                        if val:
                            asset_total[col_idx] = val
            elif CURRENT_ROW_FOUND and '资产总计' not in project:
                # Collect non-current asset items
                for col_idx in TARGET_COLS:
                    if col_idx < len(cells):
                        val = parse_number(cells[col_idx])
                        if val and col_idx not in current_total:
                            non_current_items.append((col_idx, val))

        # Check balance: current_total + non_current_sum should ≈ asset_total
        # Aggregate non-current items by column
        non_current_sum = {}
        for col_idx, val in non_current_items:
            non_current_sum[col_idx] = non_current_sum.get(col_idx, 0) + val

        for col_idx in TARGET_COLS:
            year = TARGET_COLS[col_idx]
            if col_idx in current_total and col_idx in asset_total and col_idx in non_current_sum:
                expected = current_total[col_idx] + non_current_sum[col_idx]
                actual = asset_total[col_idx]
                if abs(expected - actual) / actual > 0.05:  # 5% tolerance
                    diff = expected - actual
                    issues.append(ValidationIssue(
                        issuer=issuer,
                        note_type="financial_analysis",
                        rule=FinancialBalanceChecker.RULE_NAME,
                        severity="error",
                        message=f"{year}年资产不平衡：流动资产({current_total[col_idx]:.0f}) + 非流动资产({non_current_sum[col_idx]:.0f}) = {expected:.0f}，但资产总计={actual:.0f}，差值={diff:+.0f} ({diff/actual*100:.1f}%)"
                    ))
                elif abs(expected - actual) / actual > 0.01:
                    issues.append(ValidationIssue(
                        issuer=issuer,
                        note_type="financial_analysis",
                        rule=FinancialBalanceChecker.RULE_NAME,
                        severity="warning",
                        message=f"{year}年资产轻微不平衡：流动资产+非流动资产={expected:.0f} vs 资产总计={actual:.0f}，差值={expected-actual:+.0f}"
                    ))

        return issues


class FundUsageChecker:
    """资金用途比例校验：合计应接近 100%"""

    RULE_NAME = "fund_usage_total"

    @staticmethod
    def check(content: str, issuer: str) -> List[ValidationIssue]:
        issues = []

        # 查找表格中的"合计"行
        for match in re.finditer(r'\|\s*\*\*合计\*\*\s*\|\s*([^|]+)\s*\|\s*([^|]+)\s*\|', content):
            amount_str = match.group(1).strip()
            pct_str = match.group(2).strip().replace('%', '')
            try:
                pct = float(pct_str)
                if abs(pct - 100) > 1:  # 1% 容差
                    issues.append(ValidationIssue(
                        issuer=issuer,
                        note_type="fund_usage",
                        rule=FundUsageChecker.RULE_NAME,
                        severity="error",
                        message=f"资金用途比例合计={pct}%，不等于100%"
                    ))
            except ValueError:
                pass

        return issues


class ScaleConsistencyChecker:
    """跨笔记发行规模一致性校验"""

    RULE_NAME = "scale_consistency"

    @staticmethod
    def check(terms_content: str, fund_content: str, issuer: str) -> List[ValidationIssue]:
        issues = []

        terms_scale = extract_scale(terms_content, "本期发行规模")
        fund_scale = extract_scale(fund_content, "发行规模")

        if terms_scale and fund_scale:
            if abs(terms_scale - fund_scale) / max(terms_scale, fund_scale) > 0.01:
                issues.append(ValidationIssue(
                    issuer=issuer,
                    note_type="cross_note",
                    rule=ScaleConsistencyChecker.RULE_NAME,
                    severity="warning",
                    message=f"发行规模不一致：发行条款={terms_scale}亿，募集资金运用={fund_scale}亿"
                ))

        return issues


class RevenueSumChecker:
    """营业收入分板块合计校验"""

    RULE_NAME = "revenue_sum"

    @staticmethod
    def check(content: str, issuer: str) -> List[ValidationIssue]:
        issues = []
        # 查找营业收入表格中的合计行
        lines = content.split('\n')
        in_revenue_section = False
        header_found = False

        for line in lines:
            if '营业收入' in line and '###' in line:
                in_revenue_section = True
                header_found = False
                continue
            if in_revenue_section and line.startswith('###'):
                in_revenue_section = False
                continue
            if in_revenue_section and '|' in line:
                cells = [c.strip() for c in line.split('|')[1:-1]]
                if not header_found:
                    header_found = True
                    continue
                if '合计' in line:
                    # 检查占比列是否接近 100%
                    for col_idx in range(2, len(cells), 2):
                        if col_idx < len(cells):
                            pct_str = cells[col_idx].replace('%', '').strip()
                            try:
                                pct = float(pct_str)
                                if abs(pct - 100) > 1:
                                    issues.append(ValidationIssue(
                                        issuer=issuer,
                                        note_type="business_analysis",
                                        rule=RevenueSumChecker.RULE_NAME,
                                        severity="error",
                                        message=f"营业收入占比合计={pct}%，不等于100%"
                                    ))
                            except ValueError:
                                pass
                    break

        return issues


class RequiredFieldChecker:
    """必填字段检查"""

    REQUIRED = {
        "bond_terms": ["issuer"],
        "fund_usage": ["issuer"],
        "issuer_profile": ["issuer"],
        "business_analysis": ["issuer"],
        "financial_analysis": ["issuer"],
    }

    RULE_NAME = "required_fields"

    @staticmethod
    def check(content: str, issuer: str, note_type: str) -> List[ValidationIssue]:
        issues = []
        required = RequiredFieldChecker.REQUIRED.get(note_type, [])

        # 检查 frontmatter
        fm_match = re.match(r'^---\s*\n(.*?)\n---', content, re.DOTALL)
        if fm_match:
            fm_text = fm_match.group(1)
            for field in required:
                if field not in fm_text:
                    issues.append(ValidationIssue(
                        issuer=issuer,
                        note_type=note_type,
                        rule=RequiredFieldChecker.RULE_NAME,
                        severity="warning",
                        message=f"frontmatter 缺失必填字段: {field}"
                    ))

        return issues


# ============================================================================
# 工具函数
# ============================================================================

def parse_number(s: str) -> Optional[float]:
    """从字符串解析数字，支持千分位逗号"""
    s = s.strip().replace(',', '')
    # 移除 ** 等 markdown 标记
    s = s.replace('**', '')
    try:
        return float(s)
    except ValueError:
        return None


def extract_scale(content: str, field_name: str) -> Optional[float]:
    """从笔记中提取规模数值（亿元）"""
    # 尝试从表格提取
    match = re.search(rf'\|\s*{field_name}[^|]*\|\s*([^|]+)\s*\|', content)
    if match:
        val = match.group(1).strip()
        # 匹配 "X亿元" 或 "X亿"
        num_match = re.search(r'(\d+(?:\.\d+)?)\s*亿', val)
        if num_match:
            return float(num_match.group(1))

    # 尝试从 bullet 提取
    match = re.search(rf'{field_name}.*?(\d+(?:\.\d+)?)\s*亿', content)
    if match:
        return float(match.group(1))

    return None


def extract_issuer_from_path(filepath: str) -> str:
    """从文件路径提取发行人名称"""
    name = os.path.basename(filepath).replace('.md', '')
    suffixes = ['-发行条款', '-募集资金运用', '-概况', '-主营业务', '-资产结构分析']
    for suffix in suffixes:
        if name.endswith(suffix):
            return name[:-len(suffix)]
    return name


DIR_TYPE_MAP = {
    "01-发行条款": "bond_terms",
    "02-募集资金运用": "fund_usage",
    "03-发行人基本情况": "issuer_profile",
    "04-主营业务分析": "business_analysis",
    "05-资产结构分析": "financial_analysis",
}


# ============================================================================
# 主校验器
# ============================================================================

class DataValidator:
    """数据校验器"""

    def __init__(self, knowledge_dir: str = "knowledge"):
        self.knowledge_dir = knowledge_dir
        self.issues: List[ValidationIssue] = []
        self.notes_cache: Dict[str, Dict[str, str]] = {}  # issuer -> {type: content}

    def validate_all(self) -> List[ValidationIssue]:
        """运行所有校验规则"""
        self.issues = []
        self._load_notes()

        # 逐文件校验
        for dir_name, note_type in DIR_TYPE_MAP.items():
            dir_path = os.path.join(self.knowledge_dir, dir_name)
            if not os.path.exists(dir_path):
                continue

            for md_file in sorted(os.listdir(dir_path)):
                if not md_file.endswith('.md'):
                    continue
                filepath = os.path.join(dir_path, md_file)
                with open(filepath, 'r', encoding='utf-8') as f:
                    content = f.read()

                issuer = extract_issuer_from_path(filepath)

                # 必填字段检查
                self.issues.extend(RequiredFieldChecker.check(content, issuer, note_type))

                # 财务平衡检查
                if note_type == "financial_analysis":
                    self.issues.extend(FinancialBalanceChecker.check(content, issuer))

                # 资金用途检查
                if note_type == "fund_usage":
                    self.issues.extend(FundUsageChecker.check(content, issuer))

                # 营收合计检查
                if note_type == "business_analysis":
                    self.issues.extend(RevenueSumChecker.check(content, issuer))

        # 跨笔记一致性检查
        for issuer, notes in self.notes_cache.items():
            if "bond_terms" in notes and "fund_usage" in notes:
                self.issues.extend(
                    ScaleConsistencyChecker.check(
                        notes["bond_terms"], notes["fund_usage"], issuer
                    )
                )

        return self.issues

    def _load_notes(self):
        """缓存所有笔记内容（用于跨笔记校验）"""
        for dir_name, note_type in DIR_TYPE_MAP.items():
            dir_path = os.path.join(self.knowledge_dir, dir_name)
            if not os.path.exists(dir_path):
                continue
            for md_file in os.listdir(dir_path):
                if not md_file.endswith('.md'):
                    continue
                filepath = os.path.join(dir_path, md_file)
                issuer = extract_issuer_from_path(filepath)
                with open(filepath, 'r', encoding='utf-8') as f:
                    content = f.read()
                if issuer not in self.notes_cache:
                    self.notes_cache[issuer] = {}
                self.notes_cache[issuer][note_type] = content

    def print_summary(self):
        """打印校验摘要"""
        if not self.issues:
            print("\n" + "=" * 60)
            print("数据校验通过：所有检查项均正常")
            print("=" * 60)
            return

        errors = [i for i in self.issues if i.severity == "error"]
        warnings = [i for i in self.issues if i.severity == "warning"]

        print("\n" + "=" * 60)
        print("数据校验报告")
        print("=" * 60)
        print(f"错误：{len(errors)}  警告：{len(warnings)}  总计：{len(self.issues)}")

        if errors:
            print(f"\n{'='*40}")
            print("错误（需修正）:")
            for i in errors:
                print(f"  [{i.issuer}] {i.rule}: {i.message}")

        if warnings:
            print(f"\n{'='*40}")
            print("警告（建议检查）:")
            for i in warnings[:20]:  # 限制显示数量
                print(f"  [{i.issuer}] {i.rule}: {i.message}")
            if len(warnings) > 20:
                print(f"  ... 还有 {len(warnings) - 20} 条警告")

    def export_json(self, output_path: str):
        """导出 JSON 报告"""
        data = {
            "timestamp": datetime.now().isoformat(),
            "total_issues": len(self.issues),
            "errors": len([i for i in self.issues if i.severity == "error"]),
            "warnings": len([i for i in self.issues if i.severity == "warning"]),
            "issues": [asdict(i) for i in self.issues],
        }
        with open(output_path, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)


def main():
    """主函数"""
    import argparse

    parser = argparse.ArgumentParser(description="数据校验")
    parser.add_argument("--knowledge-dir", type=str, default="knowledge")
    parser.add_argument("--export", type=str, default=None, help="导出 JSON 报告路径")
    args = parser.parse_args()

    validator = DataValidator(args.knowledge_dir)
    issues = validator.validate_all()
    validator.print_summary()

    if args.export:
        validator.export_json(args.export)
        print(f"\n报告已导出：{args.export}")


if __name__ == "__main__":
    main()
