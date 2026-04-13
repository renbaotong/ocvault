#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
提取主营业务分析内容
从PDF第四节"七、发行人主要业务情况"提取信息
"""

import fitz
import os
import re
from datetime import datetime


def extract_main_business(pdf_path, issuer_name):
    """提取主要业务情况"""
    doc = fitz.open(pdf_path)

    # 找到第四节的位置
    section_four_start = None
    section_five_start = None

    for i in range(len(doc)):
        text = doc[i].get_text()
        if '第四节' in text and ('发行人' in text or '基本情况' in text):
            section_four_start = i
        if section_four_start and '第五节' in text and ('财务会计' in text or '财务信息' in text):
            section_five_start = i
            break

    if section_four_start is None:
        print(f"  未找到第四节: {issuer_name}")
        doc.close()
        return None

    if section_five_start is None:
        section_five_start = min(section_four_start + 30, len(doc))

    # 提取第四节全部文本
    section_text = ""
    for i in range(section_four_start, section_five_start):
        section_text += doc[i].get_text() + "\n"

    doc.close()

    # 查找"七、发行人主要业务情况"或类似标题
    business_section = ""

    # 尝试多种模式匹配
    patterns = [
        r'七[、\s]+发行人主要业务情况(.+?)(?:八[、\s]+|九[、\s]+|第[一二三四五六七八九十]+节|\Z)',
        r'七[、\s]+发行人业务情况(.+?)(?:八[、\s]+|九[、\s]+|第[一二三四五六七八九十]+节|\Z)',
        r'七[、\s]+主要业务情况(.+?)(?:八[、\s]+|九[、\s]+|第[一二三四五六七八九十]+节|\Z)',
        r'七[、\s]+发行人主营业务(.+?)(?:八[、\s]+|九[、\s]+|第[一二三四五六七八九十]+节|\Z)',
    ]

    for pattern in patterns:
        match = re.search(pattern, section_text, re.DOTALL)
        if match:
            business_section = match.group(1).strip()
            break

    # 如果没找到，尝试从目录定位
    if not business_section:
        # 查找"主要业务情况"在文本中的位置
        idx = section_text.find('主要业务情况')
        if idx > 0:
            # 向后提取内容，直到遇到下一个"八、"或章节标题
            end_idx = len(section_text)
            for next_section in ['八、', '九、', '十、', '第五节', '第六节']:
                next_idx = section_text.find(next_section, idx + 10)
                if next_idx > 0 and next_idx < end_idx:
                    end_idx = next_idx
            business_section = section_text[idx:end_idx].strip()

    return business_section


def parse_business_content(text, issuer_name):
    """解析业务内容，提取关键信息"""
    if not text:
        return None

    # 清理文本
    text = re.sub(r'\n+', '\n', text)
    text = re.sub(r'\s+', ' ', text)

    result = {
        'overview': '',
        'business_segments': [],
        'revenue_structure': [],
        'cost_structure': [],
        'gross_margin': []
    }

    # 提取业务概况
    overview_patterns = [
        r'发行人[是|为]?([^。]{50,300}?)公司',
        r'主营业务[为|是]?[:：]?([^。]{50,300}?)',
    ]
    for pattern in overview_patterns:
        match = re.search(pattern, text)
        if match:
            result['overview'] = match.group(1).strip()[:300]
            break

    # 查找业务板块表格
    # 尝试提取主营业务收入构成表
    table_pattern = r'业务\s*收入\s*金额\s*占比.*?((?:\d{4}\s*年.*?)+)'
    table_match = re.search(table_pattern, text, re.DOTALL)

    return result


def generate_business_note(issuer_name, pdf_name, content):
    """生成主营业务分析笔记"""

    # 确定债券类型标签
    bond_type = "公司债"
    if "乡村振兴" in pdf_name:
        bond_type = "乡村振兴债"
    if "革命老区" in pdf_name:
        bond_type = "革命老区债"

    template = f"""---
created: {datetime.now().strftime('%Y-%m-%d')}
type: business_analysis
tags: [主营业务, #{bond_type}]
---

# {issuer_name} - 主营业务分析

## 业务概况

{{业务概况描述}}

## 主要业务板块

### 1. 业务板块一

**业务内容**：
**经营模式**：
**收入情况**：

### 2. 业务板块二

**业务内容**：
**经营模式**：
**收入情况**：

### 3. 业务板块三

**业务内容**：
**经营模式**：
**收入情况**：

## 营业收入构成

| 业务板块 | 收入金额（万元） | 占比 | 同比变化 |
|---------|----------------|------|---------|
| | | | |
| | | | |
| **合计** | | 100% | |

## 营业成本构成

| 业务板块 | 成本金额（万元） | 占比 |
|---------|----------------|------|
| | | |
| | | |

## 毛利率分析

| 业务板块 | 毛利率 | 同比变化 |
|---------|--------|---------|
| | | |
| | | |

## 上下游产业链

### 上游供应商

- 主要原材料/服务来源：
- 集中度分析：

### 下游客户

- 主要客户群体：
- 集中度分析：

## 行业地位与竞争优势

### 行业地位

{{发行人在行业中的地位}}

### 竞争优势

1.
2.
3.

## 业务发展计划

{{未来业务发展规划}}

---
**来源**: {pdf_name}
**提取日期**: {datetime.now().strftime('%Y-%m-%d')}

## 原始文本

```
{{从PDF提取的原始业务情况文本}}
```
"""

    # 如果有提取的内容，替换模板中的占位符
    if content:
        # 清理文本用于显示
        clean_content = content.replace('\n\n\n', '\n\n')[:5000]
        template = template.replace('{{从PDF提取的原始业务情况文本}}', clean_content)

        # 尝试提取业务概况
        # 查找前几句作为概况
        sentences = content.split('。')
        if len(sentences) > 0:
            overview = '。'.join(sentences[:3]) + '。'
            template = template.replace('{{业务概况描述}}', overview[:500])

    return template


def main():
    """批量处理"""
    raw_dir = "raw"
    output_dir = "knowledge/04-主营业务分析"

    os.makedirs(output_dir, exist_ok=True)

    pdf_files = [
        ('佛山市南海区大沥投资发展有限公司', '佛山市南海区大沥投资发展有限公司2026年面向专业投资者非公开发行公司债券（第一期）募集说明书.pdf'),
        ('樟树市创业投资发展有限公司', '樟树市创业投资发展有限公司2024年面向专业投资者非公开发行公司债券（第一期）募集说明书.pdf'),
        ('泾县泾城实业发展集团有限公司', '泾县泾城实业发展集团有限公司2026年面向专业投资者非公开发行公司债券（第一期）募集说明书.pdf'),
        ('湖南花垣十八洞发展集团有限公司', '湖南花垣十八洞发展集团有限公司2026年面向专业投资者非公开发行乡村振兴公司债券（第一期）募集说明书.pdf'),
        ('山东阳都智圣产业投资集团有限公司', '山东阳都智圣产业投资集团有限公司2025年面向专业投资者非公开发行乡村振兴公司债券（革命老区）（第一期）募集说明书(1).pdf'),
        ('湖州南浔强村富民发展集团有限公司', '湖州南浔强村富民发展集团有限公司2025年面向专业投资者非公开发行乡村振兴公司债券（第一期）募集说明书.pdf'),
    ]

    print(f"发现 {len(pdf_files)} 份 PDF 文件\n")

    for issuer_name, pdf_file in pdf_files:
        pdf_path = os.path.join(raw_dir, pdf_file)
        print(f"处理：{issuer_name}")

        try:
            # 提取业务内容
            content = extract_main_business(pdf_path, issuer_name)

            if content:
                print(f"  ✓ 提取到业务内容 ({len(content)} 字符)")

                # 生成笔记文件
                note_content = generate_business_note(issuer_name, pdf_file, content)
                output_path = os.path.join(output_dir, f"{issuer_name}-主营业务.md")

                with open(output_path, 'w', encoding='utf-8') as f:
                    f.write(note_content)

                print(f"  ✓ 已生成: {output_path}")
            else:
                print(f"  ✗ 未找到业务情况内容")
                # 仍然生成一个模板文件
                note_content = generate_business_note(issuer_name, pdf_file, "")
                output_path = os.path.join(output_dir, f"{issuer_name}-主营业务.md")
                with open(output_path, 'w', encoding='utf-8') as f:
                    f.write(note_content)
                print(f"  ✓ 已生成模板: {output_path}")

        except Exception as e:
            print(f"  ✗ 处理失败: {e}")

        print("-" * 50)

    print("\n处理完成！")


if __name__ == "__main__":
    main()
