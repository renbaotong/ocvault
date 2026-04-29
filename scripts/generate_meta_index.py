#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
生成 Meta 索引文件
生成 knowledge/00-Meta/目录下的两个索引文件：
- 发行人索引.md
- 债券索引.md
"""

import os
import re
import glob
from datetime import datetime
from pathlib import Path
from typing import List, Dict, Optional, Set
from dataclasses import dataclass, field
import logging

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)


@dataclass
class NoteInfo:
    """笔记信息"""
    file: str
    filename: str
    issuer: str
    note_type: str
    tags: str
    dir: str
    # 债券信息（从发行条款笔记中提取）
    bond_short: str = ""
    bond_type: str = ""
    year: str = ""
    issue_scale: str = ""
    bond_term: str = ""
    guarantee: str = ""


class MetaIndexGenerator:
    """Meta 索引生成器"""

    def __init__(self, knowledge_dir: str = "knowledge"):
        self.knowledge_dir = knowledge_dir
        self.meta_dir = os.path.join(knowledge_dir, "00-Meta")
        self._logger = logging.getLogger(self.__class__.__name__)

    def scan_all_notes(self) -> List[NoteInfo]:
        """扫描所有笔记文件，提取关键信息"""
        notes = []

        dirs_to_scan = [
            ("01-发行条款", "bond_terms"),
            ("03-发行人基本情况", "issuer_profile"),
        ]

        for dir_name, note_type in dirs_to_scan:
            dir_path = os.path.join(self.knowledge_dir, dir_name)
            if not os.path.exists(dir_path):
                continue

            for md_file in glob.glob(os.path.join(dir_path, "*.md")):
                info = self._parse_note(md_file)
                if info:
                    notes.append(info)

        self._logger.info(f"扫描完成，发现 {len(notes)} 个笔记")
        return notes

    def _parse_note(self, md_path: str) -> Optional[NoteInfo]:
        """解析笔记文件，提取 frontmatter 和关键信息"""
        try:
            with open(md_path, 'r', encoding='utf-8') as f:
                content = f.read()

            # 提取 frontmatter
            frontmatter = {}
            match = re.search(r'---\n(.+?)\n---', content, re.DOTALL)
            if match:
                for line in match.group(1).split('\n'):
                    if ':' in line:
                        key, value = line.split(':', 1)
                        frontmatter[key.strip()] = value.strip()

            # 从文件名提取信息
            filename = os.path.basename(md_path)
            issuer_match = re.search(r'(.+?)-', filename)
            issuer = issuer_match.group(1) if issuer_match else ""

            # 从内容中提取债券简称（从表格中）
            bond_short = ""
            if "01-发行条款" in md_path:
                match = re.search(r'\| 债券简称 \| (.+?) \|', content)
                if match:
                    bond_short = match.group(1).strip()

            return NoteInfo(
                file=md_path,
                filename=filename,
                issuer=issuer,
                note_type=frontmatter.get('type', ''),
                tags=frontmatter.get('tags', ''),
                dir=os.path.basename(os.path.dirname(md_path)),
                bond_short=bond_short
            )
        except Exception as e:
            self._logger.error(f"解析失败 {md_path}: {e}")
            return None

    def _parse_bond_terms(self, md_path: str) -> Optional[NoteInfo]:
        """解析发行条款笔记"""
        try:
            with open(md_path, 'r', encoding='utf-8') as f:
                content = f.read()

            filename = os.path.basename(md_path)
            issuer_match = re.search(r'(.+?)-', filename)
            issuer = issuer_match.group(1) if issuer_match else ""

            data = NoteInfo(
                file=md_path,
                filename=filename,
                issuer=issuer,
                note_type="bond_terms",
                tags="",
                dir="01-发行条款",
            )

            # 从表格中提取信息
            extractors = {
                'bond_short': r'\| 债券简称 \| (.+?) \|',
                'bond_type': r'\| 债券类型 \| (.+?) \|',
                'year': r'\| 发行日期 \| (.+?) \|',
                'issue_scale': r'\| 本期发行规模 \| (.+?) \|',
                'bond_term': r'\| 债券期限 \| (.+?) \|',
                'guarantee': r'\| 增信措施 \| (.+?) \|',
            }

            for attr, pattern in extractors.items():
                match = re.search(pattern, content)
                if match:
                    setattr(data, attr, match.group(1).strip())

            return data
        except Exception as e:
            self._logger.error(f"解析失败 {md_path}: {e}")
            return None

    def generate_issuer_index(self, notes: List[NoteInfo]) -> str:
        """生成发行人索引"""
        # 按发行人分组
        issuers: Dict[str, Dict] = {}

        for note in notes:
            if not note or not note.issuer:
                continue

            issuer = note.issuer
            if issuer not in issuers:
                issuers[issuer] = {
                    'tags': set(),
                    'files': {}
                }

            # 提取标签
            for tag in re.findall(r'#([\u4e00-\u9fa5A-Za-z]+)', note.tags):
                issuers[issuer]['tags'].add(f"#{tag}")

            # 记录文件
            rel_path = os.path.relpath(note.file, self.knowledge_dir)
            if note.dir not in issuers[issuer]['files']:
                issuers[issuer]['files'][note.dir] = rel_path

        # 构建 markdown 内容
        lines = [
            "---",
            f"created: {datetime.now().strftime('%Y-%m-%d')}",
            "type: index",
            "tags: [索引]",
            "---",
            "",
            "# 发行人索引",
            "",
            "## 索引表",
            "",
            "| 发行人 | 债券类型 | 概况 |",
            "|--------|---------|------|"
        ]

        # 按发行人名称排序
        for issuer in sorted(issuers.keys()):
            info = issuers[issuer]
            tags = '、'.join(sorted(info['tags']))

            profile_link = ""
            if "03-发行人基本情况" in info['files']:
                rel_path = info['files']["03-发行人基本情况"]
                profile_link = f"[概况](../{rel_path})"

            lines.append(f"| {issuer} | {tags} | {profile_link} |")

        # 按区域统计
        lines.extend([
            "",
            "## 按区域统计",
            "",
            "| 省份/区域 | 发行人 | 数量 |",
            "|----------|--------|------|"
        ])

        # 按发行人名称首字母分组（简化为按省份）
        provinces: Dict[str, List[str]] = {}
        for issuer in issuers.keys():
            province = issuer[:2]
            if province not in provinces:
                provinces[province] = []
            provinces[province].append(issuer)

        for province in sorted(provinces.keys()):
            issuer_list = provinces[province]
            lines.append(
                f"| {province} | {'、'.join(issuer_list)} | {len(issuer_list)} |"
            )

        lines.extend([
            "",
            "---",
            f"**更新日期**: {datetime.now().strftime('%Y-%m-%d')}"
        ])

        return '\n'.join(lines)

    def generate_bond_index(self, notes: List[NoteInfo]) -> str:
        """生成债券索引"""
        # 扫描发行条款目录获取债券信息
        bonds: List[NoteInfo] = []
        terms_dir = os.path.join(self.knowledge_dir, "01-发行条款")

        if os.path.exists(terms_dir):
            for md_file in glob.glob(os.path.join(terms_dir, "*.md")):
                bond_info = self._parse_bond_terms(md_file)
                if bond_info:
                    bonds.append(bond_info)

        # 构建 markdown 内容
        lines = [
            "---",
            f"created: {datetime.now().strftime('%Y-%m-%d')}",
            "type: index",
            "tags: [索引]",
            "---",
            "",
            "# 债券索引",
            "",
            "## 按债券类型统计",
            "",
            "| 债券类型 | 数量 | 债券简称 |",
            "|---------|------|---------|"
        ]

        # 按债券类型分组
        by_type: Dict[str, List[str]] = {}
        for bond in bonds:
            bond_type = bond.bond_type or '公司债'
            if bond_type not in by_type:
                by_type[bond_type] = []
            by_type[bond_type].append(bond.bond_short or '')

        for bond_type in sorted(by_type.keys()):
            bond_list = by_type[bond_type]
            lines.append(
                f"| {bond_type} | {len(bond_list)} | {'、'.join(bond_list)} |"
            )

        # 按发行年份统计
        lines.extend([
            "",
            "### 按发行年份统计",
            "",
            "| 年份 | 数量 | 债券简称 |",
            "|------|------|---------|"
        ])

        by_year: Dict[str, List[str]] = {}
        for bond in bonds:
            year = bond.year or '未知'
            if year not in by_year:
                by_year[year] = []
            by_year[year].append(bond.bond_short or '')

        for year in sorted(by_year.keys()):
            bond_list = by_year[year]
            lines.append(
                f"| {year} | {len(bond_list)} | {'、'.join(bond_list)} |"
            )

        # 按增信方式统计
        lines.extend([
            "",
            "### 按增信方式统计",
            "",
            "| 增信方式 | 数量 | 债券简称 |",
            "|---------|------|---------|"
        ])

        by_guarantee: Dict[str, List[str]] = {}
        for bond in bonds:
            guarantee = bond.guarantee or '信用'
            if guarantee not in by_guarantee:
                by_guarantee[guarantee] = []
            by_guarantee[guarantee].append(bond.bond_short or '')

        for guarantee in sorted(by_guarantee.keys()):
            bond_list = by_guarantee[guarantee]
            lines.append(
                f"| {guarantee} | {len(bond_list)} | {'、'.join(bond_list)} |"
            )

        # 详细索引表
        lines.extend([
            "",
            "## 索引表",
            "",
            "| 债券简称 | 发行人 | 发行年份 | 发行规模 | 债券期限 | 增信方式 | 发行条款 |",
            "|---------|--------|---------|---------|---------|---------|---------|"
        ])

        for bond in sorted(bonds, key=lambda x: x.bond_short or ''):
            rel_path = os.path.relpath(bond.file, self.knowledge_dir)
            lines.append(
                f"| {bond.bond_short or '/'} | {bond.issuer or '/'} | "
                f"{bond.year or '/'} | {bond.issue_scale or '/'} | "
                f"{bond.bond_term or '/'} | {bond.guarantee or '/'} | "
                f"[发行条款](../{rel_path}) |"
            )

        # 统计摘要
        lines.extend([
            "",
            "## 统计摘要",
            "",
        ])

        for bond_type, bond_list in sorted(by_type.items()):
            lines.append(f"- {bond_type}: {len(bond_list)}")

        lines.extend([
            "",
            "---",
            f"**更新日期**: {datetime.now().strftime('%Y-%m-%d')}"
        ])

        return '\n'.join(lines)

    def generate_all(self):
        """生成所有索引文件"""
        os.makedirs(self.meta_dir, exist_ok=True)

        self._logger.info("扫描所有笔记文件...")
        notes = self.scan_all_notes()
        self._logger.info(f"  发现 {len(notes)} 个笔记")

        # 生成发行人索引
        self._logger.info("生成发行人索引...")
        issuer_index = self.generate_issuer_index(notes)
        issuer_path = os.path.join(self.meta_dir, "发行人索引.md")
        with open(issuer_path, 'w', encoding='utf-8') as f:
            f.write(issuer_index)
        self._logger.info(f"  已保存：{issuer_path}")

        # 生成债券索引
        self._logger.info("生成债券索引...")
        bond_index = self.generate_bond_index(notes)
        bond_path = os.path.join(self.meta_dir, "债券索引.md")
        with open(bond_path, 'w', encoding='utf-8') as f:
            f.write(bond_index)
        self._logger.info(f"  已保存：{bond_path}")

        self._logger.info("索引生成完成！")


def main():
    """主函数"""
    generator = MetaIndexGenerator()
    generator.generate_all()


if __name__ == "__main__":
    main()
