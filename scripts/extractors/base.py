#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
提取器基类
所有提取器的公共父类，提供通用的 PDF 处理和文本提取功能
"""

import fitz
import os
import re
from datetime import datetime
from html import unescape
from typing import Optional, Dict, List, Any
from dataclasses import dataclass, field
from enum import Enum
import logging


# ============================================================================
# 日志配置
# ============================================================================

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)


# ============================================================================
# 数据类型定义
# ============================================================================

class BondType(Enum):
    """债券类型枚举"""
    COMPANY_BOND = "公司债"
    RURAL_REVITAL = "乡村振兴债"
    OLD_REVOLUTIONARY = "革命老区债"
    LOW_CARBON = "低碳转型债"
    TECH_INNOVATION = "科技创新债"
    GREEN_BOND = "绿色债"
    PERPETUAL = "可续期债"


class GuaranteeType(Enum):
    """增信方式枚举"""
    GUARANTEE = "保证担保"
    MORTGAGE = "抵押担保"
    PLEDGE = "质押担保"
    CREDIT = "信用"


@dataclass
class ExtractionResult:
    """提取结果容器"""
    success: bool
    data: Dict[str, Any] = field(default_factory=dict)
    warnings: List[str] = field(default_factory=list)
    errors: List[str] = field(default_factory=list)
    confidence: float = 1.0  # 置信度 0-1


@dataclass
class BondInfo:
    """债券信息"""
    issuer: str
    bond_type: BondType
    period: str  # 期数，如 "第一期"
    year: str  # 年份，如 "2026 年"
    bond_short: str = ""  # 债券简称


# ============================================================================
# 基类定义
# ============================================================================

class BaseExtractor:
    """
    PDF 提取器基类

    提供通用的 PDF 处理功能：
    - PDF 打开/关闭
    - 文本提取（HTML 模式，解决中文编码）
    - 文件名解析
    - 债券信息识别
    """

    def __init__(self, pdf_path: str, logger: Optional[logging.Logger] = None):
        """
        初始化提取器

        Args:
            pdf_path: PDF 文件路径
            logger: 日志记录器，默认使用类名创建 logger
        """
        self.pdf_path = pdf_path
        self.pdf_name = os.path.basename(pdf_path)
        self.doc: Optional[fitz.Document] = None
        self.full_text = ""
        self._logger = logger or logging.getLogger(self.__class__.__name__)

        # 解析结果缓存
        self._issuer_name = ""
        self._bond_info: Optional[BondInfo] = None

    # --------------------------------------------------------------------------
    # PDF 管理方法
    # --------------------------------------------------------------------------

    def open_pdf(self) -> bool:
        """打开 PDF 文档"""
        try:
            self.doc = fitz.open(self.pdf_path)
            self._logger.debug(f"成功打开 PDF: {self.pdf_name}")
            return True
        except Exception as e:
            self._logger.error(f"打开 PDF 失败：{e}")
            return False

    def close_pdf(self):
        """关闭 PDF 文档"""
        if self.doc:
            self.doc.close()
            self.doc = None
            self._logger.debug(f"已关闭 PDF: {self.pdf_name}")

    def __enter__(self):
        """上下文管理器入口"""
        self.open_pdf()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        """上下文管理器出口"""
        self.close_pdf()

    # --------------------------------------------------------------------------
    # 文本提取方法
    # --------------------------------------------------------------------------

    def extract_text(self, use_cache: bool = True) -> str:
        """
        从 PDF 提取全部文本

        使用 HTML 模式提取，通过 html.unescape 解决中文 Unicode 编码问题

        Args:
            use_cache: 是否使用缓存，True 则返回已提取的文本

        Returns:
            提取的完整文本
        """
        if use_cache and self.full_text:
            return self.full_text

        if not self.doc:
            self.open_pdf()

        self.full_text = ""
        for page_idx, page in enumerate(self.doc):
            try:
                html = page.get_text('html')
                text = unescape(html)
                text = self._clean_text(text)
                self.full_text += text + "\n"
            except Exception as e:
                self._logger.warning(f"第{page_idx + 1}页提取失败：{e}")

        self._logger.info(f"完成文本提取，共{len(self.doc)}页，{len(self.full_text)}字符")
        return self.full_text

    def extract_page_text(self, page_indices: List[int]) -> str:
        """
        提取指定页面的文本

        Args:
            page_indices: 页码列表（从 0 开始）

        Returns:
            指定页面的文本
        """
        if not self.doc:
            self.open_pdf()

        result = ""
        for page_idx in page_indices:
            if 0 <= page_idx < len(self.doc):
                page = self.doc[page_idx]
                html = page.get_text('html')
                text = unescape(html)
                result += self._clean_text(text) + "\n"

        return result

    def extract_section_text(
        self,
        start_patterns: List[str],
        end_patterns: List[str],
        max_length: int = 10000
    ) -> str:
        """
        提取指定章节的文本

        Args:
            start_patterns: 章节起始标记
            end_patterns: 章节结束标记
            max_length: 最大提取长度

        Returns:
            章节文本
        """
        text = self.extract_text()
        clean_text = text.replace('\n', '')

        start_idx = -1
        for pattern in start_patterns:
            idx = clean_text.find(pattern)
            if idx >= 0:
                start_idx = idx
                break

        if start_idx < 0:
            return ""

        end_idx = len(clean_text)
        for pattern in end_patterns:
            idx = clean_text.find(pattern, start_idx)
            if 0 < idx < end_idx:
                end_idx = idx

        section = clean_text[start_idx:end_idx]
        return section[:max_length]

    def _clean_text(self, text: str) -> str:
        """
        清洗文本

        Args:
            text: 原始文本

        Returns:
            清洗后的文本
        """
        text = re.sub(r'<[^>]+>', '\n', text)  # 移除 HTML 标签
        text = re.sub(r'\n\s*\n', '\n', text)  # 合并空行
        text = re.sub(r' +', ' ', text)  # 合并空格
        return text.strip()

    # --------------------------------------------------------------------------
    # 文件名解析方法
    # --------------------------------------------------------------------------

    def parse_issuer_name(self) -> str:
        """
        从文件名解析发行人名称

        文件名格式：{序号}{发行人}-{债券信息}.pdf
        例如：26 封开 01(134993.SZ)：封开县公有资产发展有限公司 2026 年...pdf

        Returns:
            发行人名称
        """
        name = self.pdf_name.replace(".pdf", "")

        # 移除序号前缀（如"26 封开 01(..."）
        name = re.sub(r'^\d{2}[\u4e00-\u9fa5]+.*?[）)]', '', name)
        name = re.sub(r'^[）):：]', '', name)

        # 提取年份前的内容作为发行人
        match = re.match(r'(.*?)(20\d{2}年)', name)
        if match:
            self._issuer_name = match.group(1).strip()
        else:
            self._issuer_name = name

        self._logger.debug(f"解析发行人：{self._issuer_name}")
        return self._issuer_name

    def parse_bond_info(self) -> BondInfo:
        """
        从文件名解析债券信息

        Returns:
            BondInfo 对象
        """
        if self._bond_info:
            return self._bond_info

        name = self.pdf_name.replace(".pdf", "")

        # 识别债券类型
        bond_type = BondType.COMPANY_BOND
        if "乡村振兴" in name:
            bond_type = BondType.RURAL_REVITAL
        elif "革命老区" in name:
            bond_type = BondType.OLD_REVOLUTIONARY
        elif "低碳转型" in name:
            bond_type = BondType.LOW_CARBON
        elif "科技创新" in name:
            bond_type = BondType.TECH_INNOVATION
        elif "绿色" in name:
            bond_type = BondType.GREEN_BOND
        elif "可续期" in name:
            bond_type = BondType.PERPETUAL

        # 提取期数
        period_match = re.search(r'（第 [一二三四五] 期）', name)
        period = period_match.group(0) if period_match else ""

        # 提取年份
        year_match = re.search(r'(20\d{2} 年)', name)
        year = year_match.group(0) if year_match else ""

        self._bond_info = BondInfo(
            issuer=self._issuer_name or self.parse_issuer_name(),
            bond_type=bond_type,
            period=period,
            year=year
        )

        self._logger.debug(f"解析债券信息：{self._bond_info}")
        return self._bond_info

    # --------------------------------------------------------------------------
    # 工具方法
    # --------------------------------------------------------------------------

    def find_pattern(
        self,
        patterns: List[str],
        text: Optional[str] = None,
        group: int = 1
    ) -> Optional[str]:
        """
        按顺序尝试多个正则模式，返回第一个匹配结果

        Args:
            patterns: 正则模式列表
            text: 待搜索文本，默认使用 full_text
            group: 返回的分组编号

        Returns:
            匹配结果，无匹配返回 None
        """
        search_text = text or self.full_text.replace('\n', '')

        for pattern in patterns:
            match = re.search(pattern, search_text)
            if match:
                return match.group(group)

        return None

    def find_all_patterns(
        self,
        patterns: List[str],
        text: Optional[str] = None
    ) -> List[str]:
        """
        查找所有匹配的数字

        Args:
            patterns: 正则模式列表
            text: 待搜索文本

        Returns:
            匹配结果列表
        """
        search_text = text or self.full_text.replace('\n', '')
        results = []

        for pattern in patterns:
            matches = re.findall(pattern, search_text)
            results.extend(matches)

        return results

    def generate_bond_short_name(self) -> str:
        """生成债券简称"""
        issuer = self._issuer_name or self.parse_issuer_name()
        return f"{issuer[:2]}债 01"

    def get_output_dir(self, base_dir: str, dir_name: str) -> str:
        """
        获取输出目录路径

        Args:
            base_dir: 基础目录
            dir_name: 子目录名

        Returns:
            完整的目录路径
        """
        path = os.path.join(base_dir, dir_name)
        os.makedirs(path, exist_ok=True)
        return path

    def write_note(self, path: str, content: str) -> bool:
        """
        写入笔记文件

        Args:
            path: 文件路径
            content: 文件内容

        Returns:
            是否写入成功
        """
        try:
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, 'w', encoding='utf-8') as f:
                f.write(content)
            self._logger.info(f"已写入：{path}")
            return True
        except Exception as e:
            self._logger.error(f"写入失败：{e}")
            return False

    def get_frontmatter(self, note_type: str, tags: List[str]) -> str:
        """
        生成 Frontmatter

        Args:
            note_type: 笔记类型
            tags: 标签列表

        Returns:
            Frontmatter 字符串
        """
        tags_str = ', '.join(tags)
        return f"""---
created: {datetime.now().strftime('%Y-%m-%d')}
type: {note_type}
tags: [{tags_str}]
---

"""
