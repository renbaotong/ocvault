#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
发行人基本情况详细信息提取工具
从 PDF 中提取基本信息、历史沿革、股权结构（含图片）、重要权益投资
"""

import fitz
import os
import re
import json
from datetime import datetime
from pathlib import Path


class IssuerDetailExtractor:
    """发行人详细信息提取器"""

    def __init__(self, pdf_path: str, output_base_dir: str = "knowledge"):
        self.pdf_path = pdf_path
        self.pdf_name = os.path.basename(pdf_path)
        self.doc = None
        self.full_text = ""
        self.output_base_dir = output_base_dir
        self.issuer_name = ""

    def open_pdf(self):
        """打开 PDF 文件"""
        self.doc = fitz.open(self.pdf_path)

    def close_pdf(self):
        """关闭 PDF 文件"""
        if self.doc:
            self.doc.close()

    def parse_issuer_name(self) -> str:
        """从文件名提取发行人名称"""
        name = self.pdf_name.replace(".pdf", "")
        match = re.match(r'(.*?)(20\d{2}年)', name)
        if match:
            self.issuer_name = match.group(1).strip()
        else:
            self.issuer_name = name
        return self.issuer_name

    def find_section_four_text(self) -> str:
        """查找第四节 发行人基本情况的文本内容"""
        if not self.doc:
            self.open_pdf()

        # 查找第四节起始页
        section_start = None
        section_end = None

        for i, page in enumerate(self.doc):
            text = page.get_text()
            # 查找第四节标题
            if "第四节" in text and ("发行人基本情况" in text or "发行人" in text):
                section_start = i
                break

        if section_start is None:
            # 尝试从全文查找
            return ""

        # 查找第五节作为结束
        for i in range(section_start + 1, len(self.doc)):
            text = self.doc[i].get_text()
            if "第五节" in text:
                section_end = i
                break

        if section_end is None:
            section_end = min(section_start + 15, len(self.doc))  # 最多取15页

        # 提取文本
        section_text = ""
        for i in range(section_start, section_end):
            section_text += self.doc[i].get_text()

        return section_text

    def extract_basic_info(self, section_text: str) -> dict:
        """提取基本信息"""
        info = {
            "issuer_full_name": "",
            "unified_social_credit_code": "",
            "registered_capital": "",
            "paid_in_capital": "",
            "legal_representative": "",
            "establishment_date": "",
            "registered_address": "",
            "office_address": "",
            "postal_code": "",
            "actual_controller": "",
            "controlling_shareholder": "",
            "business_scope": ""
        }

        # 清理文本
        clean_text = section_text.replace('\n', ' ')
        clean_text = re.sub(r'\s+', ' ', clean_text)

        # 发行人全称
        patterns = [
            r'注册名称\s*[:：]\s*([^\n。]{5,50})',
            r'发行人全称\s*[:：]\s*([^\n。]{5,50})',
            r'公司名称\s*[:：]\s*([^\n。]{5,50})',
        ]
        for pattern in patterns:
            match = re.search(pattern, section_text)
            if match:
                info["issuer_full_name"] = match.group(1).strip()
                break

        # 统一社会信用代码
        match = re.search(r'统一社会信用代码\s*[:：]\s*([A-Z0-9]{18})', section_text)
        if match:
            info["unified_social_credit_code"] = match.group(1)

        # 注册资本 - 支持多种格式
        match = re.search(r'注册资本\s*[:：]\s*(?:人民币)?\s*([\d,\.]+)\s*(万元|亿元|元)', section_text, re.IGNORECASE)
        if match:
            info["registered_capital"] = f"{match.group(1).replace(',', '')}{match.group(2)}"

        # 实缴资本
        match = re.search(r'实缴资本\s*[:：]\s*(?:人民币)?\s*([\d,\.]+)\s*(万元|亿元|元)', section_text, re.IGNORECASE)
        if match:
            info["paid_in_capital"] = f"{match.group(1).replace(',', '')}{match.group(2)}"

        # 法定代表人
        match = re.search(r'法定代表人\s*[:：]\s*([^\s\n]{2,10})', section_text)
        if match:
            info["legal_representative"] = match.group(1).strip()

        # 成立/设立日期
        patterns = [
            r'成立日期\s*[:：]\s*(\d{4}[年\s]\d{1,2}[月\s]\d{1,2}[日\s]?)',
            r'设立日期\s*[:：]\s*(\d{4}[年\s]\d{1,2}[月\s]\d{1,2}[日\s]?)',
            r'成立时间\s*[:：]\s*(\d{4}[年\s]\d{1,2}[月\s]\d{1,2}[日\s]?)',
        ]
        for pattern in patterns:
            match = re.search(pattern, section_text)
            if match:
                date_str = match.group(1).replace(' ', '').replace('年', '年').replace('月', '月').replace('日', '日')
                info["establishment_date"] = date_str
                break

        # 注册地址/住所
        patterns = [
            r'住所\s*\(注册地\)\s*[:：]\s*([^\n]{5,100})',
            r'注册地址\s*[:：]\s*([^\n]{5,100})',
            r'住所\s*[:：]\s*([^\n]{5,100})',
        ]
        for pattern in patterns:
            match = re.search(pattern, section_text)
            if match:
                addr = match.group(1).strip()
                # 截断到合理长度
                if len(addr) > 100:
                    addr = addr[:100]
                info["registered_address"] = addr
                break

        # 办公地址
        match = re.search(r'办公地址\s*[:：]\s*([^\n]{5,100})', section_text)
        if match:
            addr = match.group(1).strip()
            if len(addr) > 100:
                addr = addr[:100]
            info["office_address"] = addr

        # 邮政编码
        match = re.search(r'邮政编码\s*[:：]\s*(\d{6})', section_text)
        if match:
            info["postal_code"] = match.group(1)

        # 实际控制人
        patterns = [
            r'实际控制人\s*[:：]\s*([^\n]{2,30})',
            r'公司实际控制人\s*[:：]\s*([^\n]{2,30})',
        ]
        for pattern in patterns:
            match = re.search(pattern, section_text)
            if match:
                ctrl = match.group(1).strip()
                # 清理常见的后续文本
                ctrl = re.split(r'[。，、；]|截至|报告期', ctrl)[0]
                info["actual_controller"] = ctrl
                break

        # 控股股东
        patterns = [
            r'控股股东\s*[:：]\s*([^\n]{2,30})',
            r'公司控股股东\s*[:：]\s*([^\n]{2,30})',
            r'股东名称\s*[:：]\s*([^\n]{2,30})',
        ]
        for pattern in patterns:
            match = re.search(pattern, section_text)
            if match:
                holder = match.group(1).strip()
                holder = re.split(r'[。，、；]|截至|报告期', holder)[0]
                info["controlling_shareholder"] = holder
                break

        # 经营范围
        match = re.search(r'经营范围\s*[:：]\s*([^\n]{10,500})', section_text)
        if match:
            scope = match.group(1).strip()
            scope = re.split(r'\n{2,}|\d+\s*[、\.]', scope)[0]  # 截断到第一段
            info["business_scope"] = scope[:300]

        return info

    def extract_history_evolution(self, section_text: str) -> list:
        """提取历史沿革信息"""
        history = []

        # 查找历史沿革部分
        history_start = section_text.find("历史沿革")
        if history_start < 0:
            history_start = section_text.find("公司设立")
        if history_start < 0:
            history_start = section_text.find("设立情况")

        if history_start < 0:
            return history

        # 提取历史沿革段落
        history_text = section_text[history_start:history_start + 5000]

        # 尝试提取时间线 - 模式：年份 + 事件
        # 匹配模式如：2020年7月、2021年、2022年3月15日等
        patterns = [
            r'(\d{4}[年\s][\d{1,2}\s]*[月]?\d{0,2}[日]?)\s*[,，、]\s*([^\n]{10,200})',
            r'(\d{4}[年\s][\d{1,2}\s]*[月]?)\s*[,，、]\s*([^\n]{10,200})',
            r'(\d{4}[年])\s*[,，、]\s*([^\n]{10,200})',
        ]

        for pattern in patterns:
            matches = re.findall(pattern, history_text)
            for match in matches:
                time_str = match[0].strip()
                detail = match[1].strip()
                # 清理并截断
                detail = re.split(r'[。；]|\n', detail)[0]
                if len(detail) > 10:  # 至少有一些内容
                    history.append({
                        "time": time_str,
                        "event": self._detect_event_type(detail),
                        "detail": detail[:150]
                    })

        # 去重
        seen = set()
        unique_history = []
        for item in history:
            key = item["time"] + item["detail"][:30]
            if key not in seen:
                seen.add(key)
                unique_history.append(item)

        return unique_history[:10]  # 最多10条

    def _detect_event_type(self, detail: str) -> str:
        """检测事件类型"""
        if "设立" in detail or "成立" in detail:
            return "设立"
        elif "增资" in detail or "增加注册资本" in detail:
            return "增资"
        elif "改制" in detail or "变更" in detail:
            return "改制"
        elif "合并" in detail or "分立" in detail:
            return "重组"
        elif "股东" in detail or "股权" in detail:
            return "股权变更"
        elif "名称" in detail:
            return "更名"
        else:
            return "其他"

    def extract_equity_structure_image(self, output_dir: str) -> str:
        """提取股权结构图"""
        if not self.doc:
            self.open_pdf()

        # 查找包含"股权结构"的页面
        image_paths = []
        image_count = 0

        for page_num in range(len(self.doc)):
            page = self.doc[page_num]
            text = page.get_text()

            # 检查是否包含股权结构相关关键词
            if any(keyword in text for keyword in ["股权结构", "股权架构", "出资结构", "持股比例"]):
                # 提取该页面的图片
                images = page.get_images()

                for img_index, img in enumerate(images):
                    try:
                        xref = img[0]
                        base_image = self.doc.extract_image(xref)
                        image_bytes = base_image["image"]
                        image_ext = base_image["ext"]

                        # 保存图片
                        image_filename = f"{self.issuer_name}_股权结构_{image_count}.{image_ext}"
                        image_path = os.path.join(output_dir, image_filename)

                        with open(image_path, "wb") as f:
                            f.write(image_bytes)

                        image_paths.append(image_path)
                        image_count += 1
                    except Exception as e:
                        print(f"  提取图片失败: {e}")
                        continue

        # 返回第一个股权结构图的路径（相对路径）
        if image_paths:
            return os.path.basename(image_paths[0])
        return ""

    def extract_subsidiaries(self, section_text: str) -> list:
        """提取重要权益投资（子公司）信息"""
        subsidiaries = []

        # 查找重要权益投资或子公司部分
        sub_start = section_text.find("重要权益投资")
        if sub_start < 0:
            sub_start = section_text.find("主要子公司")
        if sub_start < 0:
            sub_start = section_text.find("控股子公司")
        if sub_start < 0:
            sub_start = section_text.find("子公司情况")

        if sub_start < 0:
            return subsidiaries

        # 提取子公司段落
        sub_text = section_text[sub_start:sub_start + 8000]

        # 尝试提取表格中的子公司信息
        # 模式：子公司名称、持股比例、注册资本、主营业务

        # 方法1：从表格中提取
        table_patterns = [
            r'([^\s]{3,30}有限公司)\s*[|｜]\s*([\d\.]+)\s*%?\s*[|｜]\s*([\d,\.]+\s*[万元亿元]+)\s*[|｜]\s*([^\n|]{5,100})',
            r'([^\s]{3,30}有限公司)\s+([\d\.]+)\s*%?\s+([\d,\.]+\s*[万元亿元]?)\s+([^\n]{5,100})',
        ]

        for pattern in table_patterns:
            matches = re.findall(pattern, sub_text)
            for match in matches:
                subsidiaries.append({
                    "name": match[0].strip(),
                    "holding_ratio": f"{match[1].strip()}%" if "%" not in match[1] else match[1].strip(),
                    "registered_capital": match[2].strip(),
                    "main_business": match[3].strip()[:100]
                })

        # 方法2：从文本中提取
        if not subsidiaries:
            # 查找一级子公司列表
            name_pattern = r'([\u4e00-\u9fa5]{3,20}有限公司)'
            names = re.findall(name_pattern, sub_text)

            for name in names[:10]:  # 最多10个
                # 查找对应的持股比例
                holding_pattern = f"{re.escape(name)}.*?([\d\.]+)\s*%"
                holding_match = re.search(holding_pattern, sub_text)
                holding = holding_match.group(1) + "%" if holding_match else ""

                # 查找注册资本
                capital_pattern = f"{re.escape(name)}.*?注册资本.*?([\d,\.]+\s*[万元亿元]+)"
                capital_match = re.search(capital_pattern, sub_text)
                capital = capital_match.group(1) if capital_match else ""

                if name not in [s["name"] for s in subsidiaries]:
                    subsidiaries.append({
                        "name": name,
                        "holding_ratio": holding,
                        "registered_capital": capital,
                        "main_business": ""
                    })

        return subsidiaries[:10]  # 最多10个子公司

    def generate_updated_profile(self, output_dir: str) -> str:
        """生成更新后的发行人概况文件"""
        self.parse_issuer_name()

        # 提取第四节文本
        section_text = self.find_section_four_text()
        if not section_text:
            print(f"  警告：未能找到第四节内容")
            return ""

        # 提取各类信息
        basic_info = self.extract_basic_info(section_text)
        history = self.extract_history_evolution(section_text)
        subsidiaries = self.extract_subsidiaries(section_text)

        # 提取股权结构图
        image_output_dir = os.path.join(output_dir, "03-发行人基本情况", "images")
        os.makedirs(image_output_dir, exist_ok=True)
        equity_image = self.extract_equity_structure_image(image_output_dir)

        # 生成历史沿革表格
        history_table = ""
        if history:
            for item in history:
                history_table += f"| {item['time']} | {item['event']} | {item['detail']} |\n"
        else:
            history_table = "| | 设立 | |\n"

        # 生成股权结构部分
        equity_section = ""
        if equity_image:
            equity_section = f"""## 股权结构

![股权结构图](./images/{equity_image})

### 主要股东

| 股东名称 | 持股比例 | 股东性质 |
|---------|---------|---------|
| {basic_info.get('controlling_shareholder', '')} | | |
| {basic_info.get('actual_controller', '')} | | 实际控制人 |
"""
        else:
            equity_section = """## 股权结构

```
{股权结构图}
```

### 主要股东

| 股东名称 | 持股比例 | 股东性质 |
|---------|---------|---------|
| """ + basic_info.get('controlling_shareholder', '') + """ | | |
| """ + basic_info.get('actual_controller', '') + """ | | 实际控制人 |
"""

        # 生成子公司表格
        subsidiaries_table = ""
        if subsidiaries:
            for sub in subsidiaries:
                subsidiaries_table += f"| {sub['name']} | {sub['holding_ratio']} | {sub['registered_capital']} | {sub['main_business']} |\n"
        else:
            subsidiaries_table = "| | | | |\n"

        # 构建markdown内容
        template = f"""---
created: {datetime.now().strftime('%Y-%m-%d')}
type: issuer_profile
tags: [发行人/概况, #公司债]
---

# {self.issuer_name} - 概况

## 基本信息

| 项目 | 内容 |
|------|------|
| 发行人全称 | {basic_info.get('issuer_full_name', self.issuer_name)} |
| 统一社会信用代码 | {basic_info.get('unified_social_credit_code', '')} |
| 注册资本 | {basic_info.get('registered_capital', '')} |
| 实缴资本 | {basic_info.get('paid_in_capital', '')} |
| 法定代表人 | {basic_info.get('legal_representative', '')} |
| 成立日期 | {basic_info.get('establishment_date', '')} |
| 注册地址 | {basic_info.get('registered_address', '')} |
| 办公地址 | {basic_info.get('office_address', '')} |
| 邮政编码 | {basic_info.get('postal_code', '')} |
| 实际控制人 | {basic_info.get('actual_controller', '')} |
| 控股股东 | {basic_info.get('controlling_shareholder', '')} |

### 经营范围

{basic_info.get('business_scope', '')}

## 历史沿革

| 时间 | 事项 | 详情 |
|------|------|------|
{history_table}

{equity_section}

## 重要权益投资

### 一级子公司

| 子公司名称 | 持股比例 | 注册资本 | 主营业务 |
|-----------|---------|---------|---------|
{subsidiaries_table}

---
**来源**: {self.pdf_name}
**提取日期**: {datetime.now().strftime('%Y-%m-%d')}
"""

        # 保存文件
        output_path = os.path.join(output_dir, "03-发行人基本情况", f"{self.issuer_name}-概况.md")
        os.makedirs(os.path.dirname(output_path), exist_ok=True)
        with open(output_path, 'w', encoding='utf-8') as f:
            f.write(template)

        return output_path


def main():
    """批量处理 raw 目录下的 PDF"""
    raw_dir = "raw"
    knowledge_dir = "knowledge"

    pdf_files = [f for f in os.listdir(raw_dir) if f.endswith(".pdf")]
    print(f"发现 {len(pdf_files)} 份 PDF 文件\n")

    all_generated = []
    for pdf_file in pdf_files:
        pdf_path = os.path.join(raw_dir, pdf_file)
        print(f"处理：{pdf_file}")

        try:
            extractor = IssuerDetailExtractor(pdf_path, knowledge_dir)
            extractor.open_pdf()

            # 生成更新后的概况文件
            output_path = extractor.generate_updated_profile(knowledge_dir)
            if output_path:
                all_generated.append(output_path)
                print(f"  ✓ 已更新: {output_path}")
            else:
                print(f"  ✗ 未能提取内容")

            extractor.close_pdf()
        except Exception as e:
            print(f"  ✗ 处理失败: {e}")

        print("-" * 50)

    print(f"\n处理完成！共更新 {len(all_generated)} 个文件")
    return all_generated


if __name__ == "__main__":
    main()
