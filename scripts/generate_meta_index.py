#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
生成 Meta 索引文件
生成 knowledge/00-Meta/目录下的索引文件：
- 发行人索引.md（静态表）
- 债券索引.md（静态表）
"""

import os
import re
import glob
from datetime import datetime
from typing import List, Dict, Optional
from dataclasses import dataclass, field
import logging

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)


# 笔记类型到目录的映射
NOTE_DIR_MAP = [
    ("01-发行条款", "bond_terms"),
    ("02-募集资金运用", "fund_usage"),
    ("03-发行人基本情况", "issuer_profile"),
    ("04-主营业务分析", "business_analysis"),
    ("05-资产结构分析", "financial_analysis"),
]

# 显示名称映射
DIR_DISPLAY = {
    "01-发行条款": "发行条款",
    "02-募集资金运用": "资金运用",
    "03-发行人基本情况": "概况",
    "04-主营业务分析": "主营业务",
    "05-资产结构分析": "资产结构",
}


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
    # task 77：去重后的展示用简称（重名时追加发行人区分词）
    display_short: str = ""
    bond_type: str = ""
    year: str = ""
    issue_date: str = ""   # task 75：完整发行日期（YYYY年M月D日）
    issue_scale: str = ""
    bond_term: str = ""
    guarantee: str = ""
    credit_rating: str = ""
    segments: List[str] = field(default_factory=list)  # task 75：主营业务板块


class MetaIndexGenerator:
    """Meta 索引生成器"""

    def __init__(self, knowledge_dir: str = "knowledge"):
        self.knowledge_dir = knowledge_dir
        self.meta_dir = os.path.join(knowledge_dir, "00-Meta")
        self._logger = logging.getLogger(self.__class__.__name__)

    def scan_all_notes(self) -> List[NoteInfo]:
        """扫描所有笔记文件，提取关键信息"""
        notes = []

        for dir_name, note_type in NOTE_DIR_MAP:
            dir_path = os.path.join(self.knowledge_dir, dir_name)
            if not os.path.exists(dir_path):
                continue

            for md_file in sorted(glob.glob(os.path.join(dir_path, "*.md"))):
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
                match = re.search(r'\|\s*债券简称\s*\|\s*(.+?)\s*\|', content)
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
        """解析发行条款笔记，提取全部字段"""
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

            # 从表格中提取信息（允许表格单元格被手工对齐填充，task 75）
            extractors = {
                'bond_short': r'\|\s*债券简称\s*\|\s*(.+?)\s*\|',
                'bond_type': r'\|\s*债券类型\s*\|\s*(.+?)\s*\|',
                'issue_date': r'\|\s*发行日期\s*\|\s*(.+?)\s*\|',
                'issue_scale': r'\|\s*本期发行规模\s*\|\s*(.+?)\s*\|',
                'bond_term': r'\|\s*债券期限\s*\|\s*(.+?)\s*\|',
                'guarantee': r'\|\s*增信措施\s*\|\s*(.+?)\s*\|',
                'credit_rating': r'\|\s*主体评级\s*\|\s*(.+?)\s*\|',
            }

            for attr, pattern in extractors.items():
                match = re.search(pattern, content)
                if match:
                    val = match.group(1).strip()
                    # 清理占位符
                    if val and val != '/':
                        setattr(data, attr, val)

            # task 75：由完整发行日期派生年份（索引按年月统计与展示）
            m = re.match(r'(\d{4})\s*年', data.issue_date or '')
            if m:
                data.year = m.group(1)
                data.issue_date = data.issue_date.strip()

            return data
        except Exception as e:
            self._logger.error(f"解析失败 {md_path}: {e}")
            return None

    # task 75：业务板块统计时忽略的非板块行标签
    _SEGMENT_SKIP = {
        '', '/', '-', '—', '合计', '小计', '总计', '项目', '科目', '业务类型',
        '业务板块', '业务板块名称', '业务名称', '其中：', '其中', '收入', '占比',
        '金额', '成本', '毛利润', '毛利率',
        # 结构性/汇总行（非业务板块）
        '主营业务', '主营业务收入', '其他业务', '其他业务收入', '营业收入',
        '营业收入构成情况', '其他', '其它', '其他收入', '其他小计', '其他主营业务',
    }

    # 行标签前缀：编号（一、/（1）/1.）与"其中："
    _SEGMENT_PREFIX = re.compile(
        r'^(?:[（(]?[一二三四五六七八九十百\d]{1,3}[）)]?\s*[、.．]\s*|\d+\s*[、.．]\s*|其中\s*[：:]\s*)+')

    def _clean_segment(self, name: str) -> str:
        """清洗业务板块行标签：去掉编号前缀/"其中："与结尾冒号"""
        s = self._SEGMENT_PREFIX.sub('', name or '').strip()
        s = s.strip('：: 　')
        return s

    def _parse_segments(self, md_path: str) -> List[str]:
        """从 04-主营业务分析 笔记的「1、营业收入」表提取业务板块名称（task 75）。

        兼容两种表头：
        - 单标签列（首列为业务板块，如"租赁业务/光伏供电/…"）
        - 双标签列（"科目 | 业务类型"，如"主营收入 | 莱赛尔"，取业务类型列）
        会剔除合计/小计等结构性行，并清理"一、""2.""其中："等编号前缀。
        """
        try:
            with open(md_path, 'r', encoding='utf-8') as f:
                content = f.read()
        except Exception:
            return []

        m = re.search(r'###\s*1、营业收入(.*?)(?:\n###|\n---|\Z)', content, re.DOTALL)
        if not m:
            return []
        rows = [l for l in m.group(1).split('\n') if l.strip().startswith('|')]
        if len(rows) < 2:
            return []

        def cells(line: str) -> List[str]:
            return [c.strip() for c in line.strip().strip('|').split('|')]

        header = cells(rows[0])
        dual = len(header) > 1 and any(k in header[0] for k in ('科目', '项目')) \
            and any(k in header[1] for k in ('业务类型', '业务名称', '业务板块'))

        segs: List[str] = []
        for line in rows[1:]:
            cs = cells(line)
            if not cs or not ''.join(cs).strip(' -.') or set(''.join(cs)) <= set('-: |'):
                continue  # 分隔行
            if dual and len(cs) > 1 and cs[1]:
                raw = cs[1]
            else:
                raw = cs[0]
            name = self._clean_segment(raw)
            if not name or name in self._SEGMENT_SKIP:
                continue
            if re.search(r'小计|合计|总计', name):
                continue
            if re.fullmatch(r'[\d,\.%\-]+', name):
                continue
            if name not in segs:
                segs.append(name)
        return segs

    def _bond_month_key(self, issue_date: str) -> str:
        """task 75：由发行日期得到"YYYY年M月"分组键（月份缺失时标注）"""
        m = re.match(r'(\d{4})\s*年\s*(\d{1,2})\s*月', issue_date or '')
        if m:
            return f"{m.group(1)}年{int(m.group(2))}月"
        m = re.match(r'(\d{4})\s*年', issue_date or '')
        if m:
            return f"{m.group(1)}年（月份未披露）"
        return '发行日期未知'

    @staticmethod
    def _month_sort_key(key: str):
        m = re.match(r'(\d{4})年(?:(\d{1,2})月)?', key)
        if not m:
            return (9999, 99, key)
        return (int(m.group(1)), int(m.group(2)) if m.group(2) else 99, key)

    @staticmethod
    def _date_sort_key(issue_date: str):
        """task 76：索引表按发行日期倒序排序的键（无日期者排最后）。

        返回 (分组, -年, -月, -日)：分组 0 为有日期、1 为无日期；
        年月日取负值，配合默认升序即"最新发行排最前"。
        """
        d = (issue_date or '').strip()
        m = re.match(r'(\d{4})\s*年\s*(\d{1,2})\s*月\s*(\d{1,2})\s*日', d)
        if m:
            return (0, -int(m.group(1)), -int(m.group(2)), -int(m.group(3)))
        m = re.match(r'(\d{4})\s*年\s*(\d{1,2})\s*月', d)
        if m:
            return (0, -int(m.group(1)), -int(m.group(2)), 0)
        m = re.match(r'(\d{4})\s*年', d)
        if m:
            return (0, -int(m.group(1)), 0, 0)
        return (1, 0, 0, 0)

    @staticmethod
    def _issuer_suffix(issuer: str, width: int) -> str:
        """task 77：取发行人名称中用于区分同名债券的部分。

        债券简称形如「山东债 01」（省/市首 2 字 + 债 + 序号），同省市发行人
        必然重名。这里先去掉开头的行政区划前缀再取 width 个字作为区分词：
        - 前 4 字内出现「省」「市」时截到该字为止（佛山市南海区… → 南海区…）
          只在前 4 字内判断，避免「重庆秀城城市运营…」的「城市」被误当行政后缀
        - 否则按 2 字前缀截断（山东同舟… → 同舟…）
        结果为「同舟」「福田」「大足」这类可读且通常唯一的片段。
        """
        name = (issuer or '').strip()
        if len(name) <= 2:
            return name

        prefix_end = 0
        for i, ch in enumerate(name[:4]):
            if ch in ('省', '市'):
                prefix_end = i + 1
                break
        if not prefix_end:
            prefix_end = 2

        suffix = name[prefix_end:prefix_end + width]
        # 后缀不足或为空时回退为完整名称，确保仍可区分
        return suffix or name

    def _assign_unique_short_names(self, bonds: List[NoteInfo]) -> None:
        """task 77：为每只债券计算全局唯一的展示简称。

        - 简称本身不重复：直接使用原简称；
        - 简称重复：追加发行人区分词，如「山东债 01（同舟）」；
          区分词长度从 2 字起逐级加长，仍冲突时回退为完整发行人名称。
        原 frontmatter/正文中的「债券简称」保持不动，仅索引展示用唯一名称。
        """
        groups: Dict[str, List[NoteInfo]] = {}
        for bond in bonds:
            groups.setdefault(bond.bond_short or '', []).append(bond)

        for short, group in groups.items():
            if not short:
                for bond in group:
                    bond.display_short = bond.issuer or '(未命名)'
                continue

            if len(group) == 1:
                group[0].display_short = short
                continue

            suffixes: List[str] = []
            width = 2
            while width <= 12:
                suffixes = [self._issuer_suffix(b.issuer, width) for b in group]
                if len(set(suffixes)) == len(suffixes):
                    break
                width += 1
            else:
                suffixes = [b.issuer or '(未命名)' for b in group]

            for bond, suffix in zip(group, suffixes):
                if suffix and suffix != (bond.issuer or ''):
                    bond.display_short = f"{short}（{suffix}）"
                else:
                    bond.display_short = suffix or short

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

            # 提取标签（YAML tags 规范不带 #）
            for tag in re.findall(r'([一-龥A-Za-z/]+)', note.tags):
                tag = tag.strip()
                if tag and len(tag) > 1 and not tag.isdigit():
                    issuers[issuer]['tags'].add(tag)

            # 记录文件
            rel_path = os.path.relpath(note.file, self.knowledge_dir).replace('\\', '/')
            if note.dir not in issuers[issuer]['files']:
                issuers[issuer]['files'][note.dir] = rel_path

        # 构建 markdown 内容
        lines = [
            "---",
            "type: index",
            'tags: ["索引"]',
            "---",
            "",
            "# 发行人索引",
            "",
        ]

        # 发行索引表：发行人 | 标签 | 发行条款 | 概况 | 资金运用 | 主营业务 | 资产结构
        lines.extend([
            "## 索引表",
            "",
            "| 发行人 | 标签 | 发行条款 | 概况 | 资金运用 | 主营业务 | 资产结构 |",
            "|--------|------|---------|------|---------|---------|---------|",
        ])

        # 按发行人名称排序
        for issuer in sorted(issuers.keys()):
            info = issuers[issuer]
            tags = '、'.join(sorted(info['tags']))

            cells = []
            for dir_name, _ in NOTE_DIR_MAP:
                if dir_name in info['files']:
                    rel_path = info['files'][dir_name]
                    display_name = DIR_DISPLAY.get(dir_name, dir_name)
                    cells.append(f"[{display_name}](../{rel_path})")
                else:
                    cells.append("—")

            lines.append(f"| {issuer} | {tags} | {' | '.join(cells)} |")

        # 按区域统计
        lines.extend([
            "",
            "## 按区域统计",
            "",
            "| 省份/区域 | 发行人 | 数量 |",
            "|----------|--------|------|",
        ])

        # 按发行人名称首字分组
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
            f"**最后更新**: `= date(this.file.mtime)`",
        ])

        return '\n'.join(lines)

    def generate_bond_index(self, notes: List[NoteInfo]) -> str:
        """生成债券索引"""
        # 扫描发行条款目录获取债券信息
        bonds: List[NoteInfo] = []
        terms_dir = os.path.join(self.knowledge_dir, "01-发行条款")

        if os.path.exists(terms_dir):
            for md_file in sorted(glob.glob(os.path.join(terms_dir, "*.md"))):
                bond_info = self._parse_bond_terms(md_file)
                if bond_info:
                    bonds.append(bond_info)

        # task 77：计算全局唯一展示简称（同名简称追加发行人区分词）
        self._assign_unique_short_names(bonds)

        # task 75：发行人 → 各类笔记相对路径（用于债券简称链接到 5 类笔记）
        issuer_files: Dict[str, Dict[str, str]] = {}
        for note in notes:
            if not note.issuer:
                continue
            rel = os.path.relpath(note.file, self.knowledge_dir).replace('\\', '/')
            issuer_files.setdefault(note.issuer, {})
            if note.dir not in issuer_files[note.issuer]:
                issuer_files[note.issuer][note.dir] = rel

        def note_link(issuer: str, dir_name: str, label: str) -> str:
            rel = issuer_files.get(issuer, {}).get(dir_name)
            return f"[{label}](../{rel})" if rel else "—"

        def bond_label(bond: NoteInfo) -> str:
            """分组列表中的展示名：优先唯一简称，缺失时回退为发行人名称"""
            return bond.display_short or bond.bond_short or bond.issuer or '(未命名)'

        # task 75：债券简称 → 主营业务板块（取该发行人 04-主营业务分析 笔记）
        bond_segments: Dict[str, List[str]] = {}
        for bond in bonds:
            rel = issuer_files.get(bond.issuer, {}).get('04-主营业务分析')
            if rel:
                segs = self._parse_segments(os.path.join(self.knowledge_dir, rel))
                if segs:
                    bond_segments[bond_label(bond)] = segs

        # 构建 markdown 内容
        lines = [
            "---",
            "type: index",
            'tags: ["索引"]',
            "---",
            "",
            "# 债券索引",
            "",
        ]

        # 按债券类型统计
        lines.extend([
            "## 按债券类型统计",
            "",
            "| 债券类型 | 数量 | 债券简称 |",
            "|---------|------|---------|",
        ])

        by_type: Dict[str, List[str]] = {}
        for bond in bonds:
            bond_type = bond.bond_type or '公司债'
            if bond_type not in by_type:
                by_type[bond_type] = []
            by_type[bond_type].append(bond_label(bond))

        for bond_type in sorted(by_type.keys()):
            bond_list = by_type[bond_type]
            lines.append(
                f"| {bond_type} | {len(bond_list)} | {'、'.join(bond_list)} |"
            )

        # task 75：按发行月份统计（原"按发行年份统计"细化到月份）
        lines.extend([
            "",
            "### 按发行月份统计",
            "",
            "| 发行月份 | 数量 | 债券简称 |",
            "|---------|------|---------|",
        ])

        by_month: Dict[str, List[str]] = {}
        for bond in bonds:
            key = self._bond_month_key(bond.issue_date)
            by_month.setdefault(key, []).append(bond_label(bond))

        for key in sorted(by_month.keys(), key=self._month_sort_key):
            bond_list = by_month[key]
            lines.append(
                f"| {key} | {len(bond_list)} | {'、'.join(bond_list)} |"
            )

        # 按增信方式统计
        lines.extend([
            "",
            "### 按增信方式统计",
            "",
            "| 增信方式 | 数量 | 债券简称 |",
            "|---------|------|---------|",
        ])

        by_guarantee: Dict[str, List[str]] = {}
        for bond in bonds:
            guarantee = bond.guarantee or '信用'
            if guarantee not in by_guarantee:
                by_guarantee[guarantee] = []
            by_guarantee[guarantee].append(bond_label(bond))

        for guarantee in sorted(by_guarantee.keys()):
            bond_list = by_guarantee[guarantee]
            lines.append(
                f"| {guarantee} | {len(bond_list)} | {'、'.join(bond_list)} |"
            )

        # task 75：按主营业务板块统计
        lines.extend([
            "",
            "### 按业务板块统计",
            "",
            "> 取自各发行人 04-主营业务分析 笔记「营业收入」表的业务板块行标签。",
            "",
            "| 业务板块 | 数量 | 债券简称 |",
            "|---------|------|---------|",
        ])

        by_segment: Dict[str, List[str]] = {}
        for short, segs in bond_segments.items():
            for seg in segs:
                by_segment.setdefault(seg, [])
                if short and short not in by_segment[seg]:
                    by_segment[seg].append(short)

        for seg in sorted(by_segment.keys(), key=lambda s: (-len(by_segment[s]), s)):
            bond_list = sorted(by_segment[seg])
            lines.append(
                f"| {seg} | {len(bond_list)} | {'、'.join(bond_list)} |"
            )

        # 详细索引表：债券简称链接到发行条款，并列出 5 类笔记链接
        lines.extend([
            "",
            "## 索引表",
            "",
            "> 索引表按发行日期倒序排列（最新发行在前）；债券简称链接到该债券的发行条款笔记，",
            "> 其后各列依次链接到 5 类笔记。",
            "",
            "| 债券简称 | 发行人 | 发行日期 | 发行规模 | 债券期限 | 增信方式 | 主体评级 | 发行条款 | 概况 | 资金运用 | 主营业务 | 资产结构 |",
            "|---------|--------|---------|---------|---------|---------|---------|---------|------|---------|---------|---------|",
        ])

        for bond in sorted(bonds, key=lambda b: (self._date_sort_key(b.issue_date), bond_label(b))):
            short_cell = note_link(bond.issuer, '01-发行条款', bond_label(bond))
            lines.append(
                f"| {short_cell} | {bond.issuer or '/'} | "
                f"{bond.issue_date or '/'} | {bond.issue_scale or '/'} | "
                f"{bond.bond_term or '/'} | {bond.guarantee or '/'} | "
                f"{bond.credit_rating or '/'} | "
                f"{note_link(bond.issuer, '01-发行条款', '发行条款')} | "
                f"{note_link(bond.issuer, '03-发行人基本情况', '概况')} | "
                f"{note_link(bond.issuer, '02-募集资金运用', '资金运用')} | "
                f"{note_link(bond.issuer, '04-主营业务分析', '主营业务')} | "
                f"{note_link(bond.issuer, '05-资产结构分析', '资产结构')} |"
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
            f"**最后更新**: `= date(this.file.mtime)`",
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
