#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
提取财务指标和资产分析内容
从PDF第五节提取：
1. 三、发行人最近两年及一期主要财务指标
2. 四、发行人财务分析 -> 1、流动资产分析 和 2、非流动资产分析
"""

import fitz
import os
import re
from datetime import datetime


def extract_section_five_financial_data(pdf_path, issuer_name):
    """提取第五节财务会计信息中的财务指标和资产分析"""
    doc = fitz.open(pdf_path)

    # 找到第五节的位置
    section_five_start = None
    section_six_start = None

    for i in range(len(doc)):
        text = doc[i].get_text()
        if '第五节' in text and ('财务会计' in text or '财务信息' in text):
            section_five_start = i
        if section_five_start and '第六节' in text:
            section_six_start = i
            break

    if section_five_start is None:
        print(f"  未找到第五节: {issuer_name}")
        doc.close()
        return None

    if section_six_start is None:
        section_six_start = min(section_five_start + 40, len(doc))

    # 提取第五节全部文本
    section_text = ""
    for i in range(section_five_start, section_six_start):
        section_text += doc[i].get_text() + "\n"

    doc.close()

    result = {
        'financial_indicators': '',
        'current_assets_analysis': '',
        'non_current_assets_analysis': ''
    }

    # 1. 提取"三、发行人最近两年及一期主要财务指标"
    # 查找"三、"和"财务指标"相关内容
    pattern_three = r'三[、\s]+发行人最近两年及一期主要财务指标(.+?)(?:四[、\s]+|第[一二三四五六七八九十]+节|\Z)'
    match_three = re.search(pattern_three, section_text, re.DOTALL)
    if match_three:
        result['financial_indicators'] = match_three.group(1).strip()[:5000]
    else:
        # 尝试其他模式
        idx = section_text.find('主要财务指标')
        if idx > 0:
            # 向前找到"三、"
            start = section_text.rfind('三、', 0, idx)
            if start > 0:
                end = section_text.find('四、', idx)
                if end < 0:
                    end = len(section_text)
                result['financial_indicators'] = section_text[start:end].strip()[:5000]

    # 2. 提取"四、发行人财务分析"中的"1、流动资产分析"和"2、非流动资产分析"
    pattern_four = r'四[、\s]+发行人财务分析(.+?)(?:五[、\s]+|第[一二三四五六七八九十]+节|\Z)'
    match_four = re.search(pattern_four, section_text, re.DOTALL)

    if match_four:
        financial_analysis = match_four.group(1)

        # 提取1、流动资产分析
        pattern_current = r'1[、\s]+流动资产分析(.+?)(?:2[、\s]+|3[、\s]+|四[、\s]+|\Z)'
        match_current = re.search(pattern_current, financial_analysis, re.DOTALL)
        if match_current:
            result['current_assets_analysis'] = match_current.group(1).strip()[:5000]
        else:
            # 尝试查找"流动资产"
            idx = financial_analysis.find('流动资产')
            if idx > 0:
                end = financial_analysis.find('非流动资产', idx)
                if end < 0:
                    end = len(financial_analysis)
                result['current_assets_analysis'] = financial_analysis[idx:end].strip()[:5000]

        # 提取2、非流动资产分析
        pattern_non_current = r'2[、\s]+非流动资产分析(.+?)(?:3[、\s]+|4[、\s]+|\Z)'
        match_non_current = re.search(pattern_non_current, financial_analysis, re.DOTALL)
        if match_non_current:
            result['non_current_assets_analysis'] = match_non_current.group(1).strip()[:5000]
        else:
            # 尝试查找"非流动资产"
            idx = financial_analysis.find('非流动资产')
            if idx > 0:
                end = financial_analysis.find('3、', idx)
                if end < 0:
                    end = len(financial_analysis)
                result['non_current_assets_analysis'] = financial_analysis[idx:end].strip()[:5000]

    return result


def generate_asset_status_note(issuer_name, pdf_name, data):
    """生成资产状况笔记"""

    # 确定债券类型标签
    bond_type = "公司债"
    if "乡村振兴" in pdf_name:
        bond_type = "乡村振兴债"
    if "革命老区" in pdf_name:
        bond_type = "革命老区债"

    template = f"""---
created: {datetime.now().strftime('%Y-%m-%d')}
type: asset_status
tags: [资产/状况, #{bond_type}]
---

# {issuer_name} - 资产状况

## 一、最近两年及一期主要财务指标

{{财务指标内容}}

## 二、资产状况分析

### 1、流动资产分析

{{流动资产分析内容}}

### 2、非流动资产分析

{{非流动资产分析内容}}

---
**来源**: {pdf_name}
**提取日期**: {datetime.now().strftime('%Y-%m-%d')}

## 原始提取内容

### 三、发行人最近两年及一期主要财务指标（原文）

```
{data.get('financial_indicators', '未提取到内容')}
```

### 四、发行人财务分析 - 1、流动资产分析（原文）

```
{data.get('current_assets_analysis', '未提取到内容')}
```

### 四、发行人财务分析 - 2、非流动资产分析（原文）

```
{data.get('non_current_assets_analysis', '未提取到内容')}
```
"""

    # 替换占位符
    template = template.replace('{{财务指标内容}}', _format_financial_indicators(data.get('financial_indicators', '')))
    template = template.replace('{{流动资产分析内容}}', _format_assets_analysis(data.get('current_assets_analysis', '')))
    template = template.replace('{{非流动资产分析内容}}', _format_assets_analysis(data.get('non_current_assets_analysis', '')))

    return template


def _format_financial_indicators(text):
    """格式化财务指标内容"""
    if not text:
        return "待补充"

    # 清理文本
    lines = text.split('\n')
    formatted_lines = []

    for line in lines:
        line = line.strip()
        if line and len(line) > 5:
            formatted_lines.append(line)

    return '\n\n'.join(formatted_lines[:50])  # 限制行数


def _format_assets_analysis(text):
    """格式化资产分析内容"""
    if not text:
        return "待补充"

    # 清理文本
    lines = text.split('\n')
    formatted_lines = []

    for line in lines:
        line = line.strip()
        if line and len(line) > 5:
            formatted_lines.append(line)

    return '\n\n'.join(formatted_lines[:50])  # 限制行数


def main():
    """批量处理"""
    raw_dir = "raw"
    output_dir = "knowledge/05-资产状况"

    os.makedirs(output_dir, exist_ok=True)

    pdf_files = [
        ('佛山市南海区大沥投资发展有限公司', '佛山市南海区大沥投资发展有限公司2026年面向专业投资者非公开发行公司债券（第一期）募集说明书.pdf'),
        ('樟树市创业投资发展有限公司', '樟树市创业投资发展有限公司2024年面向专业投资者非公开发行公司债券（第一期）募集说明书.pdf'),
        ('泾县泾城实业发展集团有限公司', '泾县泾城实业发展集团有限公司2026年面向专业投资者非公开发行公司债券（第一期）募集说明书.pdf'),
        ('湖南花垣十八洞发展集团有限公司', '湖南花垣十八洞发展集团有限公司2026年面向专业投资者非公开发行乡村振兴公司债券（第一期）募集说明书.pdf'),
        ('山东阳都智圣产业投资集团有限公司', '山东阳都智圣产业投资集团有限公司2025年面向专业投资者非公开发行乡村振兴公司债券（革命老区）（第一期）募集说明书(1).pdf'),
        ('湖州南浔强村富民发展集团有限公司', '湖州南浔强村富民发展集团有限公司2025年面向专业投资者非公开发行乡村振兴公司债券（第一期）募集说明书.pdf'),
    ]

    print(f"发现 {len(pdf_files)} 份 PDF 文件\\n")

    for issuer_name, pdf_file in pdf_files:
        pdf_path = os.path.join(raw_dir, pdf_file)
        print(f"处理：{issuer_name}")

        try:
            # 提取财务数据
            data = extract_section_five_financial_data(pdf_path, issuer_name)

            if data:
                has_content = any(data.values())
                if has_content:
                    print(f"  ✓ 提取到内容")
                    # 生成笔记文件
                    note_content = generate_asset_status_note(issuer_name, pdf_file, data)
                else:
                    print(f"  ⚠ 未提取到详细内容，生成模板")
                    note_content = generate_asset_status_note(issuer_name, pdf_file, {})
            else:
                print(f"  ✗ 提取失败")
                note_content = generate_asset_status_note(issuer_name, pdf_file, {})

            output_path = os.path.join(output_dir, f"{issuer_name}-资产状况.md")
            with open(output_path, 'w', encoding='utf-8') as f:
                f.write(note_content)

            print(f"  ✓ 已生成: {output_path}")

        except Exception as e:
            print(f"  ✗ 处理失败: {e}")

        print("-" * 50)

    print(f"\\n处理完成！")


if __name__ == "__main__":
    main()
