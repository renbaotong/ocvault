#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
提取器测试和验证模块
用于测试提取质量，验证提取结果
"""

import os
import re
import json
from typing import Dict, List, Any, Optional
from dataclasses import dataclass, asdict
from datetime import datetime


@dataclass
class ValidationReport:
    """验证报告"""
    file: str
    issuer: str
    note_type: str
    total_fields: int
    filled_fields: int
    missing_fields: List[str]
    confidence: float
    warnings: List[str]
    timestamp: str


class ExtractionValidator:
    """提取结果验证器"""

    # 各类型笔记的必填字段
    REQUIRED_FIELDS = {
        "bond_terms": ["issuer", "issue_scale", "bond_type", "bond_term"],
        "fund_usage": ["issuer", "total_amount"],
        "issuer_profile": ["issuer", "registered_capital"],
        "business_analysis": ["issuer"],
        "financial_analysis": ["issuer"],
    }

    # 各类型笔记的所有字段
    ALL_FIELDS = {
        "bond_terms": [
            "issuer", "bond_type", "period", "year", "register_scale",
            "issue_scale", "bond_term", "guarantee", "credit_rating",
            "bond_rating", "interest_rate", "repayment_method"
        ],
        "fund_usage": [
            "issuer", "bond_type", "issue_scale", "debt_repayment",
            "supplement_flow", "guarantee", "rating_issuer", "rating_bond"
        ],
        "issuer_profile": [
            "issuer", "registered_capital", "paid_in_capital",
            "legal_representative", "establishment_date",
            "unified_social_credit_code", "registered_address", "office_address"
        ],
        "business_analysis": [
            "issuer", "overview", "revenue_structure", "main_products", "business_model"
        ],
        "financial_analysis": [
            "issuer", "total_assets_2024", "total_assets_2023", "total_assets_2022",
            "total_liabilities_2024", "operating_revenue_2024", "net_profit_2024"
        ],
    }

    def __init__(self, knowledge_dir: str = "knowledge"):
        self.knowledge_dir = knowledge_dir
        self.reports: List[ValidationReport] = []

    def validate_note(self, md_path: str) -> Optional[ValidationReport]:
        """
        验证单个笔记文件

        Args:
            md_path: Markdown 文件路径

        Returns:
            验证报告
        """
        try:
            with open(md_path, 'r', encoding='utf-8') as f:
                content = f.read()

            # 提取文件名和类型
            filename = os.path.basename(md_path)
            dir_name = os.path.basename(os.path.dirname(md_path))

            # 确定笔记类型
            note_type = self._guess_note_type(dir_name)
            if not note_type:
                return None

            # 提取发行人
            issuer_match = re.search(r'(.+?)-', filename)
            issuer = issuer_match.group(1) if issuer_match else "未知"

            # 获取必填字段和所有字段
            required = self.REQUIRED_FIELDS.get(note_type, [])
            all_fields = self.ALL_FIELDS.get(note_type, [])

            # 检查字段填充情况
            filled = 0
            missing = []

            for field in all_fields:
                if self._check_field(content, field):
                    filled += 1
                else:
                    if field in required:
                        missing.append(field)

            # 生成警告
            warnings = []
            if missing:
                warnings.append(f"缺失必填字段：{missing}")

            # 计算置信度
            confidence = filled / len(all_fields) if all_fields else 0

            return ValidationReport(
                file=md_path,
                issuer=issuer,
                note_type=note_type,
                total_fields=len(all_fields),
                filled_fields=filled,
                missing_fields=missing,
                confidence=confidence,
                warnings=warnings,
                timestamp=datetime.now().isoformat()
            )

        except Exception as e:
            print(f"验证失败 {md_path}: {e}")
            return None

    def _guess_note_type(self, dir_name: str) -> Optional[str]:
        """根据目录名猜测笔记类型"""
        mapping = {
            "01-发行条款": "bond_terms",
            "02-募集资金运用": "fund_usage",
            "03-发行人基本情况": "issuer_profile",
            "04-主营业务分析": "business_analysis",
            "05-资产结构分析": "financial_analysis",
        }
        return mapping.get(dir_name)

    def _check_field(self, content: str, field: str) -> bool:
        """检查字段是否有值"""
        # 检查 frontmatter
        frontmatter_match = re.search(r'---\n(.+?)\n---', content, re.DOTALL)
        if frontmatter_match:
            frontmatter = frontmatter_match.group(1)
            if field in frontmatter:
                return True

        # 检查表格中的值
        table_match = re.search(
            rf'\|\s*[^|]*{field}[^|]*\|\s*([^|]+)\s*\|',
            content, re.IGNORECASE
        )
        if table_match:
            value = table_match.group(1).strip()
            # 排除空值和占位符
            if value and value not in ['/', '', '详见募集说明书原文', '{}']:
                return True

        # 检查正文内容
        if field in content.lower():
            return True

        return False

    def validate_all(self) -> List[ValidationReport]:
        """验证所有笔记文件"""
        reports = []

        for dir_name in [
            "01-发行条款", "02-募集资金运用", "03-发行人基本情况",
            "04-主营业务分析", "05-资产结构分析"
        ]:
            dir_path = os.path.join(self.knowledge_dir, dir_name)
            if not os.path.exists(dir_path):
                continue

            for md_file in os.listdir(dir_path):
                if not md_file.endswith('.md'):
                    continue

                md_path = os.path.join(dir_path, md_file)
                report = self.validate_note(md_path)
                if report:
                    reports.append(report)

        self.reports = reports
        return reports

    def print_summary(self, reports: List[ValidationReport] = None):
        """打印验证摘要"""
        if not reports:
            reports = self.reports

        if not reports:
            print("没有验证报告")
            return

        print("\n" + "=" * 60)
        print("提取质量验证摘要")
        print("=" * 60)

        # 总体统计
        total = len(reports)
        avg_confidence = sum(r.confidence for r in reports) / total if total else 0

        print(f"验证文件数：{total}")
        print(f"平均置信度：{avg_confidence:.1%}")

        # 按类型统计
        by_type: Dict[str, List[ValidationReport]] = {}
        for report in reports:
            if report.note_type not in by_type:
                by_type[report.note_type] = []
            by_type[report.note_type].append(report)

        print("\n按类型统计:")
        for note_type, type_reports in sorted(by_type.items()):
            avg = sum(r.confidence for r in type_reports) / len(type_reports)
            low_quality = sum(1 for r in type_reports if r.confidence < 0.5)
            print(f"  {note_type}: {len(type_reports)} 文件，"
                  f"平均 {avg:.1%}, 低质量 {low_quality}")

        # 低质量文件列表
        low_quality_reports = [r for r in reports if r.confidence < 0.5]
        if low_quality_reports:
            print("\n低质量文件 (置信度 < 50%):")
            for r in low_quality_reports[:10]:  # 只显示前 10 个
                print(f"  - {r.issuer} ({r.note_type}): {r.confidence:.1%}")

    def export_report(self, output_path: str, format: str = "json"):
        """导出验证报告"""
        if format == "json":
            data = [asdict(r) for r in self.reports]
            with open(output_path, 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
        elif format == "markdown":
            lines = ["# 提取质量验证报告\n"]
            for r in self.reports:
                lines.append(f"## {r.issuer} - {r.note_type}")
                lines.append(f"- 文件：{r.file}")
                lines.append(f"- 置信度：{r.confidence:.1%}")
                lines.append(f"- 缺失字段：{r.missing_fields}")
                if r.warnings:
                    lines.append(f"- 警告：{r.warnings}")
                lines.append("")
            with open(output_path, 'w', encoding='utf-8') as f:
                '\n'.join(lines)


def main():
    """主函数"""
    import argparse

    parser = argparse.ArgumentParser(description="验证提取结果质量")
    parser.add_argument(
        "--export",
        type=str,
        default=None,
        help="导出报告路径"
    )
    parser.add_argument(
        "--knowledge-dir",
        type=str,
        default="knowledge",
        help="知识库目录"
    )
    args = parser.parse_args()

    validator = ExtractionValidator(args.knowledge_dir)
    reports = validator.validate_all()
    validator.print_summary(reports)

    if args.export:
        validator.export_report(args.export)
        print(f"\n报告已导出：{args.export}")


if __name__ == "__main__":
    main()
