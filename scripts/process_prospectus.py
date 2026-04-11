#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
公司债募集说明书 PDF 处理脚本
提取 PDF 文本并生成结构化 Markdown 笔记
"""

import fitz  # PyMuPDF
import os
import re
import json
from datetime import datetime
from pathlib import Path


def extract_text_from_pdf(pdf_path: str) -> str:
    """从 PDF 提取全部文本"""
    doc = fitz.open(pdf_path)
    text = ""
    for page in doc:
        text += page.get_text()
    doc.close()
    return text


def extract_section_text(full_text: str, section_title: str) -> str:
    """提取指定章节内容"""
    # 简单实现，后续可根据实际 PDF 结构调整
    pattern = f"{section_title}.*?(?=第 [一二三四五六七八九十]+节|$)"
    match = re.search(pattern, full_text, re.DOTALL)
    if match:
        return match.group(0)
    return ""


def parse_bond_terms(section_text: str) -> dict:
    """解析发行条款"""
    terms = {
        "发行人全称": "",
        "债券全称": "",
        "债券简称": "",
        "注册规模": "",
        "本期发行规模": "",
        "债券期限": "",
        "增信措施": ""
    }
    # 简单解析逻辑，后续可完善
    for line in section_text.split("\n"):
        if "发行人" in line and "全称" in line:
            terms["发行人全称"] = line.split("：")[-1].strip() if "：" in line else ""
        if "注册规模" in line or "注册额度" in line:
            terms["注册规模"] = line.split("：")[-1].strip() if "：" in line else ""
    return terms


def process_prospectus(pdf_path: str, output_dir: str):
    """处理单份募集说明书"""
    pdf_name = os.path.basename(pdf_path)
    print(f"处理：{pdf_name}")

    # 提取文本
    full_text = extract_text_from_pdf(pdf_path)

    # 提取各章节
    sections = {
        "第二节": extract_section_text(full_text, "第二节"),
        "第三节": extract_section_text(full_text, "第三节"),
        "第四节": extract_section_text(full_text, "第四节"),
        "第五节": extract_section_text(full_text, "第五节"),
    }

    # 输出简要报告
    print(f"提取完成，全文长度：{len(full_text)} 字符")
    for sec, text in sections.items():
        print(f"  {sec}: {len(text)} 字符")

    return {
        "pdf_name": pdf_name,
        "full_text": full_text,
        "sections": sections
    }


def main():
    """批量处理 raw 目录下的 PDF"""
    raw_dir = "raw"
    knowledge_dir = "knowledge"

    pdf_files = [f for f in os.listdir(raw_dir) if f.endswith(".pdf")]
    print(f"发现 {len(pdf_files)} 份 PDF 文件")

    for pdf_file in pdf_files:
        pdf_path = os.path.join(raw_dir, pdf_file)
        process_prospectus(pdf_path, knowledge_dir)
        print("-" * 50)


if __name__ == "__main__":
    main()
