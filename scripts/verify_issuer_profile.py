#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
验证发行人基本情况提取脚本与现有 knowledge 数据的一致性。
对 raw/ 下每个 PDF 运行提取器，与 knowledge/03-发行人基本情况/ 下对应的 md 文件逐字段比较。
"""

import os
import re
import sys
import traceback

# 确保可以从项目根目录导入 extractors
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from extract_issuer_profile import IssuerProfileExtractor


def parse_existing_md(filepath: str) -> dict:
    """解析现有的 md 文件，提取 frontmatter 和正文中的字段"""
    with open(filepath, 'r', encoding='utf-8') as f:
        content = f.read()

    result = {
        "注册名称": "",
        "注册资本": "",
        "实缴资本": "",
        "设立日期": "",
        "经营范围": "",
        "股权结构": "",
    }

    body = content

    # 提取注册名称（从 body 的 **注册名称** 字段获取，包含曾用名等信息）
    # 注意：不用 DOTALL，只匹配到下一行
    m = re.search(r'\*\*注册名称\*\*[：:]\s*(.+?)(?=\n\s*-?\s?\*\*)', body)
    if m:
        result["注册名称"] = m.group(1).strip()
    else:
        # 回落：从 frontmatter issuer 获取
        fm_match = re.match(r'^---\n(.*?)\n---', content, re.DOTALL)
        if fm_match:
            fm_text = fm_match.group(1)
            issuer_match = re.search(r'issuer:\s*(.+)', fm_text)
            if issuer_match:
                result["注册名称"] = issuer_match.group(1).strip()

    # 提取注册资本
    m = re.search(r'\*\*注册资本\*\*[：:]\s*(.+?)(?:\n|$)', body)
    if m:
        result["注册资本"] = m.group(1).strip()

    # 提取实缴资本
    m = re.search(r'\*\*实缴资本\*\*[：:]\s*(.+?)(?:\n|$)', body)
    if m:
        result["实缴资本"] = m.group(1).strip()

    # 提取设立日期
    m = re.search(r'\*\*设立（工商注册）日期\*\*[：:]\s*(.+?)(?:\n|$)', body)
    if m:
        result["设立日期"] = m.group(1).strip()
    else:
        # 尝试旧格式
        m = re.search(r'\*\*设立日期\*\*[：:]\s*(.+?)(?:\n|$)', body)
        if m:
            result["设立日期"] = m.group(1).strip()

    # 提取经营范围
    m = re.search(r'\*\*经营范围\*\*[：:]\s*(.+?)(?=\n\n|\n##|\n---)', body, re.DOTALL)
    if m:
        scope = m.group(1).strip()
        result["经营范围"] = scope

    # 提取股权结构
    equity_m = re.search(r'## 股权结构\n\n(```[\s\S]*?```)', body)
    if equity_m:
        result["股权结构"] = equity_m.group(1).strip()
    else:
        # 可能是（待提取）
        equity_m2 = re.search(r'## 股权结构\n\n(.+?)(?:\n---|\Z)', body, re.DOTALL)
        if equity_m2:
            result["股权结构"] = equity_m2.group(1).strip()

    return result


def normalize_scope(scope: str) -> str:
    """规范化经营范围用于比较：去除空格差异"""
    if not scope:
        return scope
    # 去除所有空白字符做比较
    return re.sub(r'\s+', '', scope)


def normalize_equity(equity: str) -> str:
    """规范化股权结构用于比较"""
    if not equity:
        return equity
    # 去除尾部空白
    return equity.strip()


def compare_issuer_name(a: str, b: str) -> bool:
    """比较发行人名称是否一致（容忍标点差异）"""
    return a.replace('（', '(').replace('）', ')').replace('，', ',').strip() == \
           b.replace('（', '(').replace('）', ')').replace('，', ',').strip()


def main():
    raw_dir = "raw"
    knowledge_dir = "knowledge/03-发行人基本情况"

    pdf_files = sorted([f for f in os.listdir(raw_dir) if f.endswith(".pdf")])

    results = {
        "pass": 0,
        "fail": 0,
        "errors": 0,
        "details": []
    }

    for pdf_file in pdf_files:
        pdf_path = os.path.join(raw_dir, pdf_file)
        print(f"\n{'='*60}")
        print(f"验证：{pdf_file}")

        try:
            with IssuerProfileExtractor(pdf_path) as extractor:
                extractor.parse_issuer_name()
                extractor.parse_bond_info()

                # 提取数据（注意：generate_note 会写文件，这里我们直接调用 extract_issuer_info）
                issuer_data = extractor.extract_issuer_info()
                basic_info = issuer_data.get('basic_info', {})

                extracted = {
                    "注册名称": basic_info.get("注册名称", ""),
                    "注册资本": basic_info.get("注册资本", ""),
                    "实缴资本": basic_info.get("实缴资本", ""),
                    "设立日期": basic_info.get("设立日期", ""),
                    "经营范围": basic_info.get("经营范围", ""),
                    "股权结构": issuer_data.get('equity_structure', '（待提取）'),
                }

                # 解析现有文件中的发行人名
                issuer_name_actual = extractor._issuer_name or ""

        except Exception as e:
            print(f"  [ERROR] 提取失败: {e}")
            traceback.print_exc()
            results["errors"] += 1
            results["details"].append({
                "pdf": pdf_file,
                "status": "error",
                "message": str(e)
            })
            continue

        # 找到对应的 md 文件
        md_files = [f for f in os.listdir(knowledge_dir) if f.endswith("-概况.md")]
        matched_md = None
        for md_file in md_files:
            md_path = os.path.join(knowledge_dir, md_file)
            md_issuer = md_file.replace("-概况.md", "")
            # 检查发行人名称是否匹配
            if md_issuer == issuer_name_actual or md_issuer.replace('（', '(').replace('）', ')') == issuer_name_actual.replace('（', '(').replace('）', ')'):
                matched_md = md_path
                break

        if not matched_md:
            print(f"  [WARN] 未找到匹配的 md 文件 (issuer: {issuer_name_actual})")
            # 再通过文件名模糊匹配试试
            for md_file in md_files:
                md_short = md_file.replace("-概况.md", "").replace('（', '(').replace('）', ')')
                issuer_short = issuer_name_actual.replace('（', '(').replace('）', ')')
                if md_short in issuer_short or issuer_short in md_short:
                    matched_md = os.path.join(knowledge_dir, md_file)
                    print(f"  [INFO] 模糊匹配: {md_file}")
                    break

        if not matched_md:
            print(f"  [ERROR] 无法匹配任何现有 md 文件")
            results["errors"] += 1
            continue

        existing = parse_existing_md(matched_md)
        md_filename = os.path.basename(matched_md)

        # 逐字段比较
        diffs = []
        fields_to_compare = ["注册名称", "注册资本", "实缴资本", "设立日期"]

        for field in fields_to_compare:
            e_val = str(extracted.get(field, "")).strip()
            x_val = str(existing.get(field, "")).strip()

            # 处理（未提取到）和空值的等价性
            if x_val in ("（未提取到）", "") and e_val in ("（未提取到）", ""):
                continue

            if field == "注册名称":
                if not compare_issuer_name(e_val, x_val):
                    diffs.append(f"    {field}: 提取='{e_val}' vs 现有='{x_val}'")
            elif field == "设立日期":
                # 容忍格式差异：2009年09月01日 vs 2009年9月1日
                e_norm = re.sub(r'0(\d)', r'\1', e_val)
                x_norm = re.sub(r'0(\d)', r'\1', x_val)
                if e_norm != x_norm:
                    diffs.append(f"    {field}: 提取='{e_val}' vs 现有='{x_val}'")
            else:
                if e_val != x_val:
                    diffs.append(f"    {field}: 提取='{e_val}' vs 现有='{x_val}'")

        # 比较经营范围（忽略空白差异）
        e_scope = normalize_scope(extracted.get("经营范围", ""))
        x_scope = normalize_scope(existing.get("经营范围", ""))
        if e_scope and x_scope and e_scope != x_scope:
            # 一个包含另一个也算匹配
            if e_scope not in x_scope and x_scope not in e_scope:
                diffs.append(f"    经营范围: 提取长度={len(e_scope)} vs 现有长度={len(x_scope)}，内容不一致")

        # 比较股权结构
        e_equity = normalize_equity(extracted.get("股权结构", ""))
        x_equity = normalize_equity(existing.get("股权结构", ""))
        if e_equity and x_equity:
            if e_equity != x_equity:
                # 检查是否都包含 "（待提取）"
                if "（待提取）" in e_equity and "（待提取）" in x_equity:
                    pass  # 双方都是待提取，OK
                else:
                    diffs.append(f"    股权结构: 不一致")
                    diffs.append(f"      提取版: {e_equity[:100]}...")
                    diffs.append(f"      现有版: {x_equity[:100]}...")

        if diffs:
            print(f"  [FAIL] 存在 {len(diffs)} 处差异:")
            for d in diffs:
                print(d)
            results["fail"] += 1
            results["details"].append({
                "pdf": pdf_file,
                "md": md_filename,
                "status": "fail",
                "diffs": diffs,
                "extracted": extracted,
                "existing": existing,
            })
        else:
            print(f"  [PASS] 全部字段一致")
            results["pass"] += 1
            results["details"].append({
                "pdf": pdf_file,
                "md": md_filename,
                "status": "pass",
            })

    # 汇总
    print(f"\n{'='*60}")
    print(f"验证完成！")
    print(f"  通过: {results['pass']}")
    print(f"  失败: {results['fail']}")
    print(f"  错误: {results['errors']}")
    print(f"  总数: {results['pass'] + results['fail'] + results['errors']}")

    # 输出详细失败信息到文件
    if results["fail"] > 0:
        report_path = "verify_issuer_profile_report.md"
        with open(report_path, 'w', encoding='utf-8') as f:
            f.write(f"# 发行人基本情况验证报告\n\n")
            f.write(f"**时间**: {__import__('datetime').datetime.now().strftime('%Y-%m-%d %H:%M')}\n\n")
            f.write(f"| 结果 | 数量 |\n|------|------|\n")
            f.write(f"| 通过 | {results['pass']} |\n")
            f.write(f"| 失败 | {results['fail']} |\n")
            f.write(f"| 错误 | {results['errors']} |\n")
            f.write(f"| 总数 | {results['pass'] + results['fail'] + results['errors']} |\n\n")

            if results["details"]:
                f.write("## 详细差异\n\n")
                for d in results["details"]:
                    if d["status"] != "pass":
                        f.write(f"### {d['pdf']}\n\n")
                        f.write(f"- **对应文件**: {d.get('md', 'N/A')}\n")
                        f.write(f"- **状态**: {d['status']}\n\n")
                        if "diffs" in d:
                            f.write("差异:\n\n")
                            for diff in d["diffs"]:
                                f.write(f"  - {diff}\n")
                            f.write("\n")

        print(f"\n详细报告已保存至: {report_path}")

    return 0 if results["fail"] == 0 and results["errors"] == 0 else 1


if __name__ == "__main__":
    main()
