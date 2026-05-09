#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
一次性迁移脚本 v2：为现有笔记增强 frontmatter
"""

import os
import re
import sys
import yaml
from pathlib import Path

# Windows console encoding fix (only when run directly)
if sys.stdout.encoding != 'utf-8':
    import io
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    sys.stderr.reconfigure(encoding='utf-8', errors='replace')

KNOWLEDGE_DIR = Path(__file__).parent.parent / "knowledge"

DIR_TYPE_MAP = {
    "01-发行条款": "bond_terms",
    "02-募集资金运用": "fund_usage",
    "03-发行人基本情况": "issuer_profile",
    "04-主营业务分析": "business_analysis",
    "05-资产结构分析": "financial_analysis",
}

# 文件名后缀到 issuer 的映射
SUFFIXES = ["-发行条款", "-募集资金运用", "-概况", "-主营业务", "-资产结构分析"]

BOND_TYPE_KEYWORDS = {
    "乡村振兴": "乡村振兴债",
    "革命老区": "革命老区债",
    "低碳转型": "低碳转型债",
    "科技创新": "科技创新债",
    "绿色": "绿色债",
    "可续期": "可续期债",
}


def extract_issuer(filename):
    """从文件名提取发行人"""
    name = filename.replace(".md", "")
    for suffix in SUFFIXES:
        if name.endswith(suffix):
            return name[:-len(suffix)]
    return name


def extract_table_field(content, field_name):
    """从 Markdown 表格提取字段值"""
    pattern = rf'\|\s*{re.escape(field_name)}\s*\|\s*([^|]+?)\s*\|'
    match = re.search(pattern, content)
    if match:
        return re.sub(r'\*\*', '', match.group(1).strip())
    return ""


def migrate_file(filepath, dir_name):
    content = filepath.read_text(encoding='utf-8')

    # 解析 frontmatter
    fm_match = re.match(r'^---\s*\n(.*?)\n---\s*\n(.*)$', content, re.DOTALL)
    if not fm_match:
        return "skipped_no_fm"

    raw_fm = fm_match.group(1)
    body = fm_match.group(2)

    # 修复 tags 行 YAML 解析问题
    def fix_tags_line(m):
        items = []
        for t in m.group(1).split(','):
            t = t.strip().strip('"').strip("'")
            if not t or re.match(r'^\d{4}$', t):
                continue  # 跳过空值和年份
            if '/' not in t and not t.startswith('#'):
                t = '#' + t
            elif '/' in t and not t.startswith('#'):
                t = '#' + t
            items.append(f'"{t}"')
        return f'tags: [{", ".join(items)}]'

    raw_fm = re.sub(r'^tags:\s*\[(.*?)\]$', fix_tags_line, raw_fm, flags=re.MULTILINE)

    try:
        fm = yaml.safe_load(raw_fm) or {}
    except yaml.YAMLError:
        return "skipped_yaml"

    changes = []
    issuer = extract_issuer(filepath.name)

    # 更新 issuer
    if fm.get("issuer") != issuer:
        changes.append(f"issuer: {fm.get('issuer', 'none')} -> {issuer}")
        fm["issuer"] = issuer

    # 添加 bond_type
    if not fm.get("bond_type"):
        for kw, bt in BOND_TYPE_KEYWORDS.items():
            if kw in body:
                fm["bond_type"] = bt
                changes.append(f"bond_type: {bt}")
                break
        else:
            fm["bond_type"] = "公司债"
            changes.append("bond_type: 公司债")

    # 01-发行条款 额外字段
    if dir_name == "01-发行条款":
        if not fm.get("year"):
            ym = re.search(r'发行日期.*?\|\s*(\d{4})年', body)
            if ym:
                fm["year"] = ym.group(1)
                changes.append(f"year: {ym.group(1)}")

        if not fm.get("bond_short"):
            bs = extract_table_field(body, "债券简称")
            if bs and bs != '/':
                fm["bond_short"] = bs
                changes.append(f"bond_short: {bs}")

        if not fm.get("guarantee"):
            g = extract_table_field(body, "增信措施")
            if g and g != '/':
                fm["guarantee"] = g
                changes.append(f"guarantee: {g}")

        if not fm.get("credit_rating"):
            cr = extract_table_field(body, "主体评级")
            if cr and cr != '/':
                fm["credit_rating"] = cr
                changes.append(f"credit_rating: {cr}")

        if not fm.get("bond_rating"):
            br = extract_table_field(body, "债项评级")
            if br and br != '/':
                fm["bond_rating"] = br
                changes.append(f"bond_rating: {br}")

    if not changes:
        return "unchanged"

    # 重写 frontmatter
    lines = ["---"]
    for key in ["created", "type", "tags", "issuer", "bond_type", "bond_short", "year", "guarantee", "credit_rating", "bond_rating"]:
        val = fm.get(key)
        if val is not None:
            if isinstance(val, list):
                lines.append(f"{key}: [{', '.join(val)}]")
            else:
                lines.append(f"{key}: {val}")
    lines.append("---")
    lines.append("")

    filepath.write_text("\n".join(lines) + body, encoding='utf-8')
    return changes


def main():
    stats = {"updated": 0, "unchanged": 0, "skipped_no_fm": 0, "skipped_yaml": 0}

    for dir_name in DIR_TYPE_MAP:
        dir_path = KNOWLEDGE_DIR / dir_name
        if not dir_path.exists():
            continue

        files = sorted(dir_path.glob("*.md"))
        print(f"\n处理 {dir_name}: {len(files)} 个文件")

        for f in files:
            result = migrate_file(f, dir_name)
            if isinstance(result, list):
                stats["updated"] += 1
                print(f"  ✓ {f.name}")
                for c in result:
                    print(f"      {c}")
            else:
                stats[result] += 1
                if result.startswith("skipped"):
                    print(f"  - {f.name}: {result}")

    print(f"\n{'='*50}")
    print(f"迁移完成: 更新 {stats['updated']}, 无变化 {stats['unchanged']}, 跳过 {stats['skipped_no_fm'] + stats['skipped_yaml']}")


if __name__ == "__main__":
    main()
