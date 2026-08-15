#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
全量验证脚本（task 52）：用 raw/ 下的每个 PDF 重新提取知识库，
与 knowledge/ 下现有笔记逐字节对比（忽略 created/提取日期 字段），
确保提取脚本输出与知识库完全一致。

用法:
    python scripts/verify_all.py                      # 验证 raw/ 下所有 PDF
    python scripts/verify_all.py --files a.pdf b.pdf  # 只验证指定 PDF
    python scripts/verify_all.py --keep-temp          # 保留临时提取目录便于人工比对

退出码: 全部一致返回 0；存在差异返回 1。
"""

import os
import re
import sys
import tempfile
import shutil
import argparse

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from extract_bond_terms import BondTermsExtractor
from extract_fund_usage import FundUsageExtractor
from extract_issuer_profile import IssuerProfileExtractor
from extract_business_analysis import BusinessAnalysisExtractorV3
from extract_financial_analysis import FinancialAnalysisExtractor

RAW_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'raw')
KNOWLEDGE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'knowledge')
PROJECT_ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..')

# (提取器类, 输出目录)
EXTRACTORS = [
    (BondTermsExtractor, "01-发行条款"),
    (FundUsageExtractor, "02-募集资金运用"),
    (IssuerProfileExtractor, "03-发行人基本情况"),
    (BusinessAnalysisExtractorV3, "04-主营业务分析"),
    (FinancialAnalysisExtractor, "05-资产结构分析"),
]

# 忽略日期字段（created / 提取日期），它们随运行日期变化，不属于提取内容差异
DATE_RE = re.compile(r'^(created:.*|.*提取日期.*)$', re.M)


def normalize(content: bytes) -> str:
    """规范化：统一行尾 + 抹平日期字段，用于内容对比"""
    return DATE_RE.sub('__DATE__', content.decode('utf-8').replace('\r\n', '\n'))


def main():
    parser = argparse.ArgumentParser(description="全量验证知识库提取脚本输出与知识库一致性")
    parser.add_argument("--files", nargs="*", default=None,
                        help="指定要验证的PDF文件名（不指定则验证raw/下所有PDF）")
    parser.add_argument("--keep-temp", action="store_true",
                        help="保留临时提取目录（默认自动清理）")
    args = parser.parse_args()

    if args.files:
        pdf_files = [f for f in args.files if f.endswith('.pdf')]
        pdf_files = [f for f in pdf_files if os.path.exists(os.path.join(RAW_DIR, f))]
    else:
        pdf_files = [f for f in os.listdir(RAW_DIR) if f.endswith('.pdf')]

    if not pdf_files:
        print("未找到任何 PDF 文件")
        return 1

    print(f"发现 {len(pdf_files)} 份 PDF，开始提取到临时目录...")

    # 临时目录放在项目根目录内（系统 Temp 可能因权限/沙箱限制无法写入）
    tmp_base = tempfile.mkdtemp(prefix='_kb_verify_', dir=PROJECT_ROOT)
    # 部分受限环境（沙箱等）禁止向新建目录写入，此时回退到固定的 _tmp_kb
    probe = os.path.join(tmp_base, '.probe')
    try:
        with open(probe, 'w') as fh:
            fh.write('x')
        os.remove(probe)
    except OSError:
        fallback = os.path.join(PROJECT_ROOT, '_tmp_kb')
        os.makedirs(fallback, exist_ok=True)
        # 清空回退目录的旧内容，避免与本次提取结果混淆
        for entry in os.listdir(fallback):
            entry_path = os.path.join(fallback, entry)
            if os.path.isdir(entry_path):
                shutil.rmtree(entry_path, ignore_errors=True)
            else:
                try:
                    os.remove(entry_path)
                except OSError:
                    pass
        shutil.rmtree(tmp_base, ignore_errors=True)
        tmp_base = fallback
        print(f"新建临时目录不可写，回退到: {tmp_base}")
    print(f"临时目录: {tmp_base}")

    errors = []
    for i, pdf in enumerate(pdf_files, 1):
        path = os.path.join(RAW_DIR, pdf)
        for cls, tag in EXTRACTORS:
            try:
                with cls(path) as ex:
                    ex.parse_issuer_name()
                    ex.parse_bond_info()
                    ex.generate_note(tmp_base)
            except Exception as e:
                errors.append(f"[提取失败 {tag}] {pdf}: {type(e).__name__}: {e}")
        if i % 10 == 0:
            print(f"  已处理 {i}/{len(pdf_files)}")

    print("\n提取完成，开始对比 knowledge/ ...")

    diffs = []
    missing = []
    checked = 0
    for root, dirs, files in os.walk(tmp_base):
        for fn in files:
            rel = os.path.relpath(os.path.join(root, fn), tmp_base)
            kb_path = os.path.join(KNOWLEDGE_DIR, rel)
            if not os.path.exists(kb_path):
                missing.append(rel)
                continue
            with open(os.path.join(root, fn), 'rb') as fh:
                tmp_text = normalize(fh.read())
            with open(kb_path, 'rb') as fh:
                kb_text = normalize(fh.read())
            checked += 1
            if tmp_text != kb_text:
                diffs.append(rel)

    print("=" * 50)
    print(f"验证 {checked} 篇笔记（{len(pdf_files)} 份 PDF x {len(EXTRACTORS)} 类）")
    print(f"一致: {checked - len(diffs)}，不一致: {len(diffs)}")
    for d in sorted(diffs):
        print(f"  [DIFF] {d}")
    for m in sorted(missing):
        print(f"  [知识库缺失对应笔记] {m}")
    for e in errors:
        print(f"  [提取错误] {e}")

    if not args.keep_temp:
        shutil.rmtree(tmp_base, ignore_errors=True)
    else:
        print(f"临时目录已保留: {tmp_base}")

    ok = not diffs and not missing and not errors
    print("结果: " + ("全部一致 ✓" if ok else "存在差异 ✗"))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
