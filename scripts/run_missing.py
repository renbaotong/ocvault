#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
仅为缺失的募集说明书运行提取脚本。
对于每个输出目录，检查缺少哪些发行人，仅处理这些。
"""

import os
import re
import sys
import time

# 添加脚本目录到路径
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

raw_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "raw")
knowledge_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "knowledge")


def extract_issuer_from_knowledge(filename):
    """从知识库文件名提取发行人名称: '{name}-发行条款.md' -> name"""
    parts = filename.rsplit('-', 1)
    return parts[0] if len(parts) == 2 else filename.replace('.md', '')


def pdf_issuer_name(filename):
    """从 PDF 文件名提取发行人名称"""
    name = filename.replace('.pdf', '')
    name = re.sub(r'^[\d]+[^：]*[：]', '', name)
    name = re.sub(r'\d{4}年.*$', '', name)
    return name.strip()


def find_missing(output_dir):
    """返回缺失的发行人名称列表"""
    existing = set()
    if os.path.exists(output_dir):
        for f in os.listdir(output_dir):
            if f.endswith('.md') and '-' in f:
                existing.add(extract_issuer_from_knowledge(f))

    # 收集所有 PDF 发行人
    all_pdf_issuers = set()
    pdf_map = {}  # issuer_name -> filename
    for f in os.listdir(raw_dir):
        if not f.endswith('.pdf'):
            continue
        issuer = pdf_issuer_name(f)
        all_pdf_issuers.add(issuer)
        pdf_map[issuer] = f

    missing = sorted(all_pdf_issuers - existing)
    return missing, pdf_map


def run_script(script_name, extractor_class_name, output_subdir, pdf_files_to_process):
    """运行单个提取脚本，仅处理指定 PDF"""
    if not pdf_files_to_process:
        return

    script_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), script_name)
    # generate_note() 内部会拼接 output_base + self.OUTPUT_DIR，所以传顶层 knowledge 路径
    output_base = knowledge_dir

    # 动态导入
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        script_name.replace('.py', ''),
        script_path
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    ExtractorClass = getattr(module, extractor_class_name)

    for pdf_file in pdf_files_to_process:
        pdf_path = os.path.join(raw_dir, pdf_file)
        print(f"  处理：{pdf_file}")
        try:
            with ExtractorClass(pdf_path) as extractor:
                extractor.parse_issuer_name()
                extractor.parse_bond_info()
                output_file = extractor.generate_note(output_base)
                print(f"  生成：{output_file}")
        except Exception as e:
            print(f"  错误：{e}")
            import traceback
            traceback.print_exc()
        print("  " + "-" * 40)


def main():
    # 扫描缺失情况
    tasks = [
        ("extract_bond_terms.py",      "BondTermsExtractor",      "01-发行条款"),
        ("extract_fund_usage.py",      "FundUsageExtractor",      "02-募集资金运用"),
        ("extract_issuer_profile.py",  "IssuerProfileExtractor",  "03-发行人基本情况"),
        ("extract_financial_analysis.py", "FinancialAnalysisExtractor", "05-资产结构分析"),
    ]

    # 预先收集所有缺失
    all_missing = {}  # output_subdir -> [issuer_names]
    pdf_map = {}
    for _, _, output_subdir in tasks:
        missing, pmap = find_missing(os.path.join(knowledge_dir, output_subdir))
        all_missing[output_subdir] = missing
        pdf_map = pmap  # same for all

    total = 0
    for script_name, extractor_cls, output_subdir in tasks:
        missing = all_missing[output_subdir]
        if not missing:
            print(f"[{output_subdir}] 无需新增（全部 {len(os.listdir(os.path.join(knowledge_dir, output_subdir)))} 个已存在）")
            continue

        pdfs = [pdf_map[m] for m in missing if m in pdf_map]
        print(f"[{output_subdir}] 缺少 {len(missing)} 个：{[m for m in missing]}")
        run_script(script_name, extractor_cls, output_subdir, pdfs)
        total += len(pdfs)

    if total > 0:
        print(f"\n全部完成！新增处理 {total} 次提取。")
    else:
        print("\n全部已存在，无需处理。")


if __name__ == "__main__":
    main()
