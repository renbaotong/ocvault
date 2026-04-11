#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
公司债募集说明书 PDF 处理脚本 - 增强版
提取关键信息并生成 Obsidian Markdown 笔记
"""

import fitz  # PyMuPDF
import os
import re
import json
from datetime import datetime
from pathlib import Path


class ProspectusProcessor:
    """募集说明书处理器"""

    def __init__(self, pdf_path: str):
        self.pdf_path = pdf_path
        self.pdf_name = os.path.basename(pdf_path)
        self.doc = None
        self.full_text = ""
        self.sections = {}

    def open_pdf(self):
        """打开 PDF 文件"""
        self.doc = fitz.open(self.pdf_path)

    def close_pdf(self):
        """关闭 PDF 文件"""
        if self.doc:
            self.doc.close()

    def extract_text(self) -> str:
        """从 PDF 提取全部文本"""
        if not self.doc:
            self.open_pdf()
        self.full_text = ""
        for page in self.doc:
            self.full_text += page.get_text()
        return self.full_text

    def find_section_pages(self, section_title: str) -> tuple:
        """查找章节所在的页码范围"""
        if not self.doc:
            self.open_pdf()

        start_page = None
        end_page = len(self.doc)

        for i, page in enumerate(self.doc):
            text = page.get_text()
            if section_title in text:
                if start_page is None:
                    start_page = i

        return (start_page, end_page) if start_page else (None, None)

    def extract_section(self, section_title: str) -> str:
        """提取指定章节内容"""
        if not self.doc:
            self.open_pdf()

        section_start_patterns = [
            section_title,
            section_title.replace(" ", ""),
        ]

        # 查找章节起始页
        start_page = None
        for i, page in enumerate(self.doc):
            text = page.get_text()
            for pattern in section_start_patterns:
                if pattern in text:
                    start_page = i
                    break
            if start_page:
                break

        if start_page is None:
            return ""

        # 查找下一章节起始页
        next_sections = [
            "第一节", "第二节", "第三节", "第四节", "第五节",
            "第六节", "第七节", "第八节", "第九节", "第十节"
        ]
        current_num = re.search(r'[一二三四五六七八九十]+', section_title)
        current_num = current_num.group(0) if current_num else ""

        end_page = len(self.doc)
        for i in range(start_page + 1, len(self.doc)):
            text = self.doc[i].get_text()
            for next_sec in next_sections:
                if next_sec in text and next_sec != section_title:
                    end_page = i
                    break

        # 提取章节文本
        section_text = ""
        for i in range(start_page, min(end_page, len(self.doc))):
            section_text += self.doc[i].get_text()

        return section_text

    def extract_all_sections(self) -> dict:
        """提取所有章节"""
        if not self.doc:
            self.open_pdf()

        self.sections = {
            "第二节": self.extract_section("第二节"),
            "第三节": self.extract_section("第三节"),
            "第四节": self.extract_section("第四节"),
            "第五节": self.extract_section("第五节"),
        }
        return self.sections

    def get_issuer_name(self) -> str:
        """从文件名提取发行人名称"""
        # 佛山市南海区大沥投资发展有限公司 2026 年面向专业投资者非公开发行公司债券（第一期）募集说明书.pdf
        name = self.pdf_name.replace(".pdf", "")
        # 移除年份及之后的内容
        match = re.match(r'(.*?)(20\d{2}年)', name)
        if match:
            return match.group(1)
        return name

    def get_bond_name(self) -> str:
        """从文件名提取债券相关信息"""
        name = self.pdf_name.replace(".pdf", "")
        # 提取债券简称（第一期之前的内容）
        match = re.search(r'公司债券（第 [一二三四五] 期）', name)
        if match:
            return name[match.start():match.end()]
        return ""


def generate_bond_terms_note(processor: ProspectusProcessor, output_dir: str):
    """生成发行条款笔记"""
    issuer_name = processor.get_issuer_name()
    bond_info = processor.get_bond_name()

    template = f"""---
created: {datetime.now().strftime('%Y-%m-%d')}
type: bond_terms
tags: [债券/发行条款]
---

# {issuer_name} - 发行条款

## 基本信息

| 项目 | 内容 |
|------|------|
| 发行人全称 | {issuer_name} |
| 债券全称 | |
| 债券简称 | |
| 发行日期 | |
| 注册规模 | 亿元 |
| 本期发行规模 | 亿元 |
| 债券期限 | 年 |
| 票面利率 | % |
| 增信措施 | |

## 增信措施详情

{{如有增信措施，详细描述}}

## 还本付息方式

{{描述还本付息方式}}

## 特殊条款

{{如有回售、赎回等特殊条款，在此描述}}

---
**来源**: {processor.pdf_name}
**提取日期**: {datetime.now().strftime('%Y-%m-%d')}
"""

    output_path = os.path.join(output_dir, "01-发行条款", f"{issuer_name}-发行条款.md")
    with open(output_path, 'w', encoding='utf-8') as f:
        f.write(template)
    print(f"  生成：{output_path}")


def main():
    """批量处理 raw 目录下的 PDF"""
    raw_dir = "raw"
    knowledge_dir = "knowledge"

    pdf_files = [f for f in os.listdir(raw_dir) if f.endswith(".pdf")]
    print(f"发现 {len(pdf_files)} 份 PDF 文件\n")

    for pdf_file in pdf_files:
        pdf_path = os.path.join(raw_dir, pdf_file)
        print(f"处理：{pdf_file}")

        processor = ProspectusProcessor(pdf_path)
        processor.open_pdf()

        # 提取章节
        sections = processor.extract_all_sections()
        print(f"  第二节（发行条款）: {len(sections['第二节'])} 字符")
        print(f"  第三节（募集资金）: {len(sections['第三节'])} 字符")
        print(f"  第四节（发行人）: {len(sections['第四节'])} 字符")
        print(f"  第五节（财务）: {len(sections['第五节'])} 字符")

        # 生成笔记
        generate_bond_terms_note(processor, knowledge_dir)

        processor.close_pdf()
        print("-" * 50)

    print("\n处理完成！")


if __name__ == "__main__":
    main()
