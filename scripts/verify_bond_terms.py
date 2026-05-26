#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
验证发行条款提取脚本的输出是否与现有的 knowledge/01-发行条款/ 文件一致
"""

import os
import re
import sys
import logging

logging.disable(logging.CRITICAL)
sys.path.insert(0, os.path.join(os.path.dirname(__file__)))

from extract_bond_terms import BondTermsExtractor

RAW_DIR = os.path.join(os.path.dirname(__file__), '..', 'raw')
KNOWN_DIR = os.path.join(os.path.dirname(__file__), '..', 'knowledge', '01-发行条款')


def extract_register_number(rs_str):
    """从注册规模字符串中提取纯数字"""
    if not rs_str:
        return None
    m = re.search(r'(\d+(?:\.\d+)?)\s*亿', rs_str)
    if m:
        return float(m.group(1))
    return None


def extract_issue_number(iss_str):
    """从发行规模字符串中提取纯数字"""
    if not iss_str or iss_str == '/':
        return None
    m = re.search(r'(\d+(?:\.\d+)?)\s*亿', iss_str)
    if m:
        return float(m.group(1))
    return None


def read_known_file(filepath):
    """读取已知的发行条款文件，提取关键字段"""
    with open(filepath, 'r', encoding='utf-8') as f:
        content = f.read()

    result = {}

    # 从 frontmatter 提取
    m = re.search(r'^issuer: (.+)', content, re.MULTILINE)
    result['issuer'] = m.group(1).strip() if m else ''

    m = re.search(r'^bond_type: (.+)', content, re.MULTILINE)
    result['bond_type'] = m.group(1).strip() if m else ''

    m = re.search(r'^guarantee: (.+)', content, re.MULTILINE)
    result['guarantee'] = m.group(1).strip() if m else ''

    m = re.search(r'^credit_rating: (.+)', content, re.MULTILINE)
    result['credit_rating'] = m.group(1).strip() if m else ''

    # 从表格中提取
    table_patterns = {
        'register_scale': r'\| 注册规模 \| (.+?) \|',
        'issue_scale': r'\| 本期发行规模 \| (.+?) \|',
        'bond_term': r'\| 债券期限 \| (.+?) \|',
        'lead_underwriter': r'\| 牵头主承销商 \| (.+?) \|',
        'co_underwriter': r'\| 联席主承销商 \| (.+?) \|',
    }

    for key, pattern in table_patterns.items():
        m = re.search(pattern, content)
        result[key] = m.group(1).strip() if m else ''

    return result


def normalize_register(rs):
    """标准化注册规模用于比较"""
    if not rs:
        return ''
    # 去掉括号部分
    rs = re.sub(r'\s*[（(][^)）]*[)）]\s*', '', rs).strip()
    return rs


def main():
    # 收集所有已知文件的信息
    known_files = {}
    for fn in os.listdir(KNOWN_DIR):
        if not fn.endswith('.md'):
            continue
        filepath = os.path.join(KNOWN_DIR, fn)
        known = read_known_file(filepath)
        if known['issuer']:
            known_files[known['issuer']] = {
                'fn': fn,
                'data': known
            }

    # 处理每个 PDF
    errors = []
    fixed_files = []

    for fn in sorted(os.listdir(RAW_DIR)):
        if not fn.endswith('.pdf'):
            continue
        pdf_path = os.path.join(RAW_DIR, fn)

        try:
            extractor = BondTermsExtractor(pdf_path)
            extractor.extract_text()
            extractor.parse_issuer_name()
            extractor.parse_bond_info()
            info = extractor.extract_key_info()
        except Exception as e:
            errors.append(f'{fn[:40]}: 提取失败: {e}')
            continue

        issuer = info.get('issuer', '')
        if not issuer:
            errors.append(f'{fn[:40]}: 未能提取发行人名称')
            continue

        if issuer not in known_files:
            errors.append(f'{issuer}: 未找到对应的知识文件')
            continue

        known = known_files[issuer]['data']
        file_fn = known_files[issuer]['fn']

        # 比较各字段
        diffs = []

        # 注册规模（考虑现有文件中的括号后缀）
        ext_rs = info.get('register_scale', '')
        known_rs = known.get('register_scale', '')
        ext_rs_normalized = normalize_register(ext_rs)
        known_rs_normalized = normalize_register(known_rs)

        if ext_rs_normalized != known_rs_normalized:
            diffs.append(f'注册规模: 提取="{ext_rs}" vs 现有="{known_rs}"')

        # 发行规模
        ext_iss = info.get('issue_scale', '')
        known_iss = known.get('issue_scale', '')

        # 空值处理：现有文件可能用 "/" 表示空
        if ext_iss != known_iss and known_iss != '/' and ext_iss:
            diffs.append(f'发行规模: 提取="{ext_iss}" vs 现有="{known_iss}"')

        # 债券期限
        ext_term = info.get('bond_term', '')
        known_term = known.get('bond_term', '')
        if ext_term and known_term and ext_term != known_term:
            diffs.append(f'债券期限: 提取="{ext_term}" vs 现有="{known_term}"')

        # 增信措施
        ext_guar = info.get('guarantee', '')
        known_guar = known.get('guarantee', '')
        if ext_guar and known_guar and ext_guar != known_guar:
            diffs.append(f'增信措施: 提取="{ext_guar}" vs 现有="{known_guar}"')

        # 主体评级
        ext_rating = info.get('credit_rating', '')
        known_rating = known.get('credit_rating', '')
        if ext_rating and known_rating and ext_rating != known_rating:
            diffs.append(f'主体评级: 提取="{ext_rating}" vs 现有="{known_rating}"')

        # 牵头主承销商
        ext_lead = info.get('lead_underwriter', '')
        known_lead = known.get('lead_underwriter', '')
        if ext_lead and known_lead and ext_lead != known_lead:
            diffs.append(f'牵头主承销商: 提取="{ext_lead}" vs 现有="{known_lead}"')

        if diffs:
            print(f'\n## {issuer}')
            for d in diffs:
                print(f'  {d}')

        # 收集可修复的文件
        rs_fix = None
        if ext_rs and known_rs == '' and normalize_register(ext_rs):
            rs_fix = ('register_scale', ext_rs)
        iss_fix = None
        if ext_iss and (known_iss == '' or known_iss == '/') and ext_iss:
            iss_fix = ('issue_scale', ext_iss)

        if rs_fix or iss_fix:
            fixed_files.append((issuer, file_fn, rs_fix, iss_fix))

    # 汇总
    print(f'\n{"="*60}')
    print(f'共检查 {len(known_files)} 个发行人')
    print(f'发现 {len(errors)} 个错误')
    for e in errors:
        print(f'  ERROR: {e}')

    print(f'\n可填补的空缺:')
    for issuer, fn, rs_fix, iss_fix in fixed_files:
        fixes = []
        if rs_fix:
            fixes.append(f'{rs_fix[0]}="{rs_fix[1]}"')
        if iss_fix:
            fixes.append(f'{iss_fix[0]}="{iss_fix[1]}"')
        print(f'  {issuer}: {", ".join(fixes)}')


if __name__ == '__main__':
    main()
