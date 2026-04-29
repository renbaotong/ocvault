#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
股权架构图片OCR识别模块 (PaddleOCR版本)
使用PaddleOCR从PDF图片中提取股权架构文字，支持版面分析和层级结构重建

依赖安装:
pip install paddleocr -i https://pypi.tuna.tsinghua.edu.cn/simple
pip install paddlepaddle
"""

import io
import re
from typing import List, Tuple, Optional, Dict
from dataclasses import dataclass
import fitz  # PyMuPDF


@dataclass
class OcrTextBox:
    """OCR识别的文字框"""
    text: str
    x: float  # 左上角X坐标
    y: float  # 左上角Y坐标
    width: float
    height: float
    confidence: float


class EquityPaddleOCR:
    """基于PaddleOCR的股权架构图片识别器"""

    def __init__(self, use_gpu: bool = False, lang: str = 'ch'):
        """
        初始化PaddleOCR识别器

        Args:
            use_gpu: 是否使用GPU加速
            lang: 语言，默认 'ch' (中文)
        """
        self.use_gpu = use_gpu
        self.lang = lang
        self._ocr = None

    @property
    def ocr(self):
        """延迟初始化PaddleOCR"""
        if self._ocr is None:
            try:
                from paddleocr import PaddleOCR
                print(f"正在初始化PaddleOCR (语言: {self.lang})...")
                self._ocr = PaddleOCR(
                    use_angle_cls=True,  # 使用方向分类器
                    lang=self.lang,
                    use_gpu=self.use_gpu,
                    show_log=False  # 减少日志输出
                )
                print("PaddleOCR初始化完成")
            except ImportError as e:
                raise ImportError(
                    f"PaddleOCR未安装，请运行: pip install paddleocr\n错误: {e}"
                )
        return self._ocr

    def extract_images_from_pdf(self, pdf_path: str, page_range: Optional[Tuple[int, int]] = None) -> List[Tuple[int, bytes]]:
        """
        从PDF中提取图片

        Args:
            pdf_path: PDF文件路径
            page_range: 页码范围元组 (start, end)，None表示全部页面

        Returns:
            图片列表，每项为 (页码, 图片字节数据)
        """
        images = []
        doc = fitz.open(pdf_path)

        start_page = page_range[0] if page_range else 0
        end_page = page_range[1] if page_range else len(doc)

        for page_num in range(start_page, min(end_page, len(doc))):
            page = doc[page_num]
            # 获取页面图片列表
            img_list = page.get_images(full=True)

            for img_index, img in enumerate(img_list, start=1):
                xref = img[0]
                base_image = doc.extract_image(xref)
                image_bytes = base_image["image"]
                images.append((page_num, image_bytes))

        doc.close()
        return images

    def recognize_image(self, image_bytes: bytes) -> List[OcrTextBox]:
        """
        识别图片中的文字及其位置

        Args:
            image_bytes: 图片字节数据

        Returns:
            文字框列表，包含文字、位置和置信度
        """
        from PIL import Image
        import numpy as np

        # 将字节数据转换为PIL Image
        image = Image.open(io.BytesIO(image_bytes))
        image_array = np.array(image)

        # 使用PaddleOCR识别
        result = self.ocr.ocr(image_array, cls=True)

        text_boxes = []
        if result and result[0]:
            for line in result[0]:
                if line:
                    # line格式: [坐标, (文字, 置信度)]
                    coords = line[0]  # [[x1,y1], [x2,y1], [x2,y2], [x1,y2]]
                    text = line[1][0]
                    confidence = line[1][1]

                    # 计算包围盒
                    x = min(c[0] for c in coords)
                    y = min(c[1] for c in coords)
                    width = max(c[0] for c in coords) - x
                    height = max(c[1] for c in coords) - y

                    text_boxes.append(OcrTextBox(
                        text=text,
                        x=x,
                        y=y,
                        width=width,
                        height=height,
                        confidence=confidence
                    ))

        return text_boxes

    def _is_hierarchy_symbol(self, text: str) -> bool:
        """判断是否为层级结构符号"""
        hierarchy_symbols = ['┌', '├', '└', '│', '─', '▼', '▲', '↑', '↓', '→', '←']
        return any(s in text for s in hierarchy_symbols)

    def _is_percentage(self, text: str) -> bool:
        """判断是否为百分比"""
        return '%' in text or '％' in text

    def _is_company_name(self, text: str) -> bool:
        """判断是否可能为公司/机构名称"""
        company_keywords = ['公司', '集团', '中心', '政府', '办公室', '财政局', '国资委', '管委会', '控股', '发展', '投资', '实业', '产业']
        # 排除常见的非公司名称词汇
        exclude_keywords = ['募集资金', '偿债计划', '资金用途', '本期债券', '募集说明书', '发行人']
        has_keyword = any(kw in text for kw in company_keywords)
        has_exclude = any(kw in text for kw in exclude_keywords)
        return has_keyword and not has_exclude and len(text) >= 4 and len(text) <= 60

    def _extract_percentage(self, text: str) -> Optional[str]:
        """从文本中提取百分比数字"""
        # 匹配纯数字（可能是100）
        if text.isdigit() and len(text) <= 3:
            return text
        # 匹配百分比格式
        match = re.search(r'(\d+(?:\.\d+)?)\s*[%％]', text)
        if match:
            return match.group(1)
        # 匹配带%的纯数字
        match = re.search(r'(\d+(?:\.\d+)?)', text)
        if match:
            return match.group(1)
        return None

    def analyze_equity_structure(self, text_boxes: List[OcrTextBox], issuer_name: str = "发行人") -> Tuple[List[Dict], List[str]]:
        """
        分析股权架构层级结构

        基于文字框的Y坐标（垂直位置）判断层级关系
        假设：Y坐标越小（越靠上）表示层级越高

        Args:
            text_boxes: OCR识别的文字框列表
            issuer_name: 发行人名称

        Returns:
            (层级结构列表, 未分类的文字列表)
        """
        if not text_boxes:
            return [], []

        # 按Y坐标排序（从上到下）
        sorted_boxes = sorted(text_boxes, key=lambda b: b.y)

        # 分组：按Y坐标相近程度分组（垂直间距小于平均高度的视为同一层级）
        if len(sorted_boxes) < 2:
            return [], [b.text for b in sorted_boxes]

        avg_height = sum(b.height for b in sorted_boxes) / len(sorted_boxes)
        y_threshold = avg_height * 1.8  # 增大层级间距阈值

        levels = []
        current_level = [sorted_boxes[0]]

        for i in range(1, len(sorted_boxes)):
            current_box = sorted_boxes[i]
            prev_box = sorted_boxes[i-1]

            if abs(current_box.y - prev_box.y) < y_threshold:
                current_level.append(current_box)
            else:
                levels.append(current_level)
                current_level = [current_box]

        if current_level:
            levels.append(current_level)

        # 解析每个层级的信息
        equity_levels = []
        uncategorized = []

        for level_boxes in levels:
            # 按X坐标排序（从左到右）
            level_boxes.sort(key=lambda b: b.x)
            level_texts = [b.text for b in level_boxes]

            # 分析当前层级
            level_info = {
                'texts': level_texts,
                'companies': [],
                'percentages': [],
                'symbols': []
            }

            for text in level_texts:
                cleaned_text = text.strip()
                if self._is_hierarchy_symbol(cleaned_text):
                    level_info['symbols'].append(cleaned_text)
                elif self._is_percentage(cleaned_text):
                    pct = self._extract_percentage(cleaned_text)
                    if pct:
                        level_info['percentages'].append(pct)
                elif self._is_company_name(cleaned_text):
                    # 清理公司名称中的额外字符
                    cleaned = re.sub(r'[：:（(].*?[）)]', '', cleaned_text)
                    cleaned = cleaned.strip()
                    if cleaned and len(cleaned) >= 4:
                        level_info['companies'].append(cleaned)
                else:
                    uncategorized.append(cleaned_text)

            if level_info['companies'] or level_info['percentages']:
                equity_levels.append(level_info)

        return equity_levels, uncategorized

    def format_equity_structure(self, equity_levels: List[Dict], issuer_name: str = "发行人") -> str:
        """
        格式化股权架构为文本图形

        Args:
            equity_levels: 层级结构列表
            issuer_name: 发行人名称

        Returns:
            格式化的股权架构文本
        """
        if not equity_levels:
            return ""

        lines = ["```", "股权架构 (OCR识别):", ""]

        # 构建层级结构
        # 假设：最后一个层级是发行人，前面的层级是股东

        all_companies = []
        all_ratios = []

        # 收集所有层级的公司和持股比例
        for level in equity_levels:
            companies = level.get('companies', [])
            ratios = level.get('percentages', [])
            for i, company in enumerate(companies):
                ratio = ratios[i] if i < len(ratios) else None
                all_companies.append(company)
                all_ratios.append(ratio)

        # 移除发行人自身（如果在列表中）
        filtered = [(c, r) for c, r in zip(all_companies, all_ratios)
                    if issuer_name not in c and len(c) < 50]

        if not filtered:
            return ""

        # 构建架构图（从上到下）
        # 支持多层级：如 财政局 -> 控股集团 -> 发行人
        for i, (company, ratio) in enumerate(filtered):
            ratio_str = f" ({ratio}%)" if ratio else ""
            if i == 0:
                lines.append(f"┌─ {company}{ratio_str}")
            else:
                lines.append(f"├─ {company}{ratio_str}")

            # 如果不是最后一个，添加连接符
            if i < len(filtered) - 1:
                lines.append("│")
                lines.append("▼")

        lines.append("│")
        lines.append("▼")
        lines.append(f"└─ {issuer_name}")
        lines.append("```")

        return '\n'.join(lines)

    def find_and_recognize_equity_images(self, pdf_path: str, issuer_name: str = "发行人",
                                         equity_section_pages: Optional[Tuple[int, int]] = None) -> str:
        """
        在股权结构章节中查找并识别图片

        Args:
            pdf_path: PDF文件路径
            issuer_name: 发行人名称
            equity_section_pages: 股权结构章节的页码范围 (start, end)

        Returns:
            识别出的股权架构文字，如果没有图片则返回空字符串
        """
        # 提取图片
        images = self.extract_images_from_pdf(pdf_path, equity_section_pages)

        if not images:
            return ""

        # 优先处理第一个图片（通常是股权架构图）
        for page_num, image_bytes in images[:3]:  # 最多处理前3张图片
            try:
                text_boxes = self.recognize_image(image_bytes)
                if text_boxes and len(text_boxes) >= 2:  # 至少识别到2个文字框
                    equity_levels, _ = self.analyze_equity_structure(text_boxes, issuer_name)
                    if equity_levels:
                        result = self.format_equity_structure(equity_levels, issuer_name)
                        if result:
                            return result
            except Exception as e:
                print(f"  图片OCR识别失败: {e}")
                continue

        return ""


def extract_equity_from_pdf_with_paddle_ocr(pdf_path: str, issuer_name: str = "发行人",
                                            equity_section_pages: Optional[Tuple[int, int]] = None,
                                            use_gpu: bool = False) -> str:
    """
    从PDF中使用PaddleOCR提取股权架构

    Args:
        pdf_path: PDF文件路径
        issuer_name: 发行人名称
        equity_section_pages: 股权结构章节的页码范围
        use_gpu: 是否使用GPU加速

    Returns:
        格式化的股权架构字符串
    """
    try:
        ocr = EquityPaddleOCR(use_gpu=use_gpu)
        result = ocr.find_and_recognize_equity_images(pdf_path, issuer_name, equity_section_pages)
        return result
    except ImportError as e:
        print(f"PaddleOCR未安装: {e}")
        return ""
    except Exception as e:
        print(f"PaddleOCR识别失败: {e}")
        return ""


if __name__ == "__main__":
    # 测试代码
    import sys
    if len(sys.argv) > 1:
        pdf_path = sys.argv[1]
        issuer = sys.argv[2] if len(sys.argv) > 2 else "发行人"

        print(f"正在识别: {pdf_path}")
        print(f"发行人: {issuer}")
        print("-" * 50)

        result = extract_equity_from_pdf_with_paddle_ocr(pdf_path, issuer)
        print("\n识别结果:")
        print(result)
    else:
        print("用法: python equity_paddle_ocr.py <pdf_path> [issuer_name]")
