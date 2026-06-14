"""
错题管理系统 - Markdown文档生成器
支持 PaddleOCR-VL-1.6 / PP-StructureV3 返回的结构化 Markdown，提取内嵌图片并保存。
适配多模型输出格式（VL 系列的 layoutParsingResults 和 OCR 系列的 ocrResults）。
"""
import base64
import re
import json
import httpx
from datetime import datetime
from pathlib import Path
from typing import Dict, Any, List, Optional
from apps.web.api.logger import setup_logger

logger = setup_logger("MarkdownGenerator")


class MarkdownGenerator:
    """将 PaddleOCR-VL-1.6 / PP-StructureV3 等模型返回的结果保存为结构化报告"""

    def __init__(self, output_dir: Path):
        self.output_dir = output_dir
        self.output_dir.mkdir(parents=True, exist_ok=True)

    def build_report(
        self,
        original_filename: str,
        markdown_text: str,
        images: Dict[str, str],
        layout_image_base64: Optional[str] = None,
        layout_items: Optional[List[Dict[str, Any]]] = None,
        structure_result: Optional[Dict[str, Any]] = None,
        processing_time: float = 0,
    ) -> str:
        """
        基于 PaddleOCR-VL-1.6 / PP-StructureV3 返回的 markdown 构建完整报告。

        VL 系列 / PP-StructureV3 已经返回了完整的结构化 Markdown，
        这里只做两件事：
        1. 将内嵌 base64 图片的引用替换为本地文件引用
        2. 在文档头部添加元信息（来源、时间等）

        参数:
            original_filename: 原始文件名
            markdown_text: PP-StructureV3 返回的 Markdown 文本
            images: 内嵌图片字典 {"img_0": "base64...", ...}
            layout_image_base64: 版面分析可视化图
            layout_items: 版面分析详情列表 [{"type":"title","region":...,"content_preview":"..."}, ...]
            structure_result: 原始API返回（可选，用于存档）
            processing_time: 处理耗时

        返回: 最终 Markdown 文本
        """
        logger.info(f"构建报告: {original_filename}")

        now = datetime.now()
        lines = []

        # ===== 文档头部元信息 =====
        lines.append(f"# 错题分析报告")
        lines.append("")
        lines.append(f"| 属性 | 值 |")
        lines.append(f"|------|-----|")
        lines.append(f"| **生成时间** | {now.strftime('%Y-%m-%d %H:%M:%S')} |")
        lines.append(f"| **原始文件** | {original_filename} |")
        lines.append(f"| **处理耗时** | {processing_time}s |")
        lines.append(f"| **内嵌图片** | {len(images)} 张 |")
        lines.append(f"| **版面区域** | {len(layout_items) if layout_items else 0} 个 |")
        lines.append(f"| **文本长度** | {len(markdown_text)} 字符 |")
        lines.append("")
        lines.append("---")
        lines.append("")

        # ===== 版面分析详情 =====
        if layout_items:
            lines.append("## 版面分析详情")
            lines.append("")
            lines.append("| 序号 | 类型 | 内容预览 |")
            lines.append("|------|------|----------|")
            for idx, item in enumerate(layout_items, 1):
                item_type = item.get("type", "unknown")
                preview = item.get("content_preview", "")
                if preview:
                    preview = preview.replace("|", "\\|").replace("\n", " ")
                    if len(preview) > 100:
                        preview = preview[:100] + "..."
                else:
                    preview = "(无文字内容)"
                lines.append(f"| {idx} | **{item_type}** | {preview} |")
            lines.append("")
            lines.append("---")
            lines.append("")

        # ===== PP-StructureV3 结构化识别结果 =====
        lines.append("## 识别结果")
        lines.append("")

        if markdown_text:
            # 将 markdown 中内嵌的 base64 图片引用替换为本地文件引用
            processed_md = self._replace_image_refs(markdown_text, images)
            lines.append(processed_md)
        else:
            lines.append("> 未能识别到文本内容")

        lines.append("")
        lines.append("---")
        lines.append("")

        # ===== 版面分析可视化 =====
        if layout_image_base64:
            lines.append("## 版面分析可视化")
            lines.append("")
            lines.append("![版面分析](layout_analysis.png)")
            lines.append("")

        # ===== 提取出的图片 =====
        if images:
            lines.append("## 识别图片")
            lines.append("")
            for i, img_key in enumerate(images.keys(), 1):
                safe_name = self._safe_image_name(img_key)
                rel_path = f"imgs/{safe_name}"
                lines.append(f"![{img_key}]({rel_path})")
                lines.append(f"*图片 {i}: {img_key}*")
                lines.append("")

        # ===== 原始 API 返回 (JSON) =====
        if structure_result:
            lines.append("## API原始返回")
            lines.append("")
            lines.append("```json")
            lines.append(json.dumps(structure_result, ensure_ascii=False, indent=2))
            lines.append("```")
            lines.append("")

        lines.append("---")
        lines.append("*本文档由错题管理系统自动生成，基于 PaddleOCR-VL / PP-StructureV3*")

        report = "\n".join(lines)
        logger.info(f"报告构建完成，共 {len(report)} 字符")
        return report

    def build_layout_report(
        self,
        original_filename: str,
        layout_items: List[Dict[str, Any]],
        layout_image_base64: Optional[str] = None,
        processing_time: float = 0,
    ) -> str:
        """构建仅包含版面分析结果的报告（不含完整识别内容）。"""
        logger.info(f"构建版面分析报告: {original_filename}")

        now = datetime.now()
        lines = []

        lines.append("# 版面分析报告")
        lines.append("")
        lines.append("| 属性 | 值 |")
        lines.append("|------|-----|")
        lines.append(f"| **生成时间** | {now.strftime('%Y-%m-%d %H:%M:%S')} |")
        lines.append(f"| **原始文件** | {original_filename} |")
        lines.append(f"| **处理耗时** | {processing_time}s |")
        lines.append(f"| **版面区域** | {len(layout_items)} 个 |")
        lines.append("")
        lines.append("---")
        lines.append("")

        if layout_image_base64:
            lines.append("## 版面分析可视化")
            lines.append("")
            lines.append("![版面分析](layout_analysis.png)")
            lines.append("")
            lines.append("---")
            lines.append("")

        lines.append("## 版面分析详情")
        lines.append("")
        lines.append("| 序号 | 类型 | 区域坐标 | 内容预览 |")
        lines.append("|------|------|----------|----------|")
        for idx, item in enumerate(layout_items, 1):
            item_type = item.get("type", "unknown")
            region = item.get("region", {})
            region_str = ""
            if region:
                bbox = region.get("bbox", [])
                if isinstance(bbox, list) and len(bbox) >= 4:
                    region_str = f"({bbox[0]}, {bbox[1]}, {bbox[2]}, {bbox[3]})"
                else:
                    x = region.get("x", "")
                    y = region.get("y", "")
                    w = region.get("width", "")
                    h = region.get("height", "")
                    if x != "":
                        region_str = f"({x}, {y}, {w}, {h})"

            preview = item.get("content_preview", "")
            if preview:
                preview = str(preview).replace("|", "\\|").replace("\n", " ")
                if len(preview) > 80:
                    preview = preview[:80] + "..."
            else:
                preview = "(无文字内容)"
            lines.append(f"| {idx} | **{item_type}** | {region_str} | {preview} |")
        lines.append("")
        lines.append("---")
        lines.append("*本文档由错题管理系统自动生成 - 版面分析报告*")

        report = "\n".join(lines)
        logger.info(f"版面分析报告构建完成，共 {len(report)} 字符")
        return report

    def save_layout_report_standalone(
        self,
        report_dir: Path,
        original_filename: str,
        layout_items: List[Dict[str, Any]],
        layout_image_base64: Optional[str] = None,
        processing_time: float = 0,
    ) -> Path:
        """在指定报告目录下保存独立的版面分析报告 (layout_report.md)。"""
        layout_content = self.build_layout_report(
            original_filename=original_filename,
            layout_items=layout_items,
            layout_image_base64=layout_image_base64,
            processing_time=processing_time,
        )
        layout_path = report_dir / "layout_report.md"
        with open(layout_path, "w", encoding="utf-8") as f:
            f.write(layout_content)
        logger.info(f"版面分析报告已保存: {layout_path}")
        return layout_path

    def _replace_image_refs(self, markdown_text: str, images: Dict[str, str]) -> str:
        """
        将 Markdown 中的 base64 图片引用替换为本地文件名引用。
        
        PP-StructureV3 返回的 Markdown 中图片可能是:
        - ![](img_0) 形式（引用 images 字典中的 key）
        - ![](data:image/png;base64,...) 形式（直接内嵌）
        
        替换为本地文件引用，便于后续保存和查看。
        """
        if not images:
            return markdown_text

        def replace_ref(match):
            alt = match.group(1)  # alt 文本
            ref = match.group(2)  # URL/路径
            # 跳过外部URL
            if ref.startswith("http://") or ref.startswith("https://"):
                return match.group(0)

            # 去掉 data:image 前缀（直接内嵌 base64 保持原样，Typora 可直接渲染）
            if ref.startswith("data:"):
                return match.group(0)

            # img_0, img_1 等引用
            img_key = ref.strip()
            if img_key in images:
                safe_name = self._safe_image_name(img_key)
                rel_path = f"imgs/{safe_name}"
                return f"![{alt or img_key}]({rel_path})"

            return match.group(0)

        # 替换 ![](ref) 形式
        markdown_text = re.sub(r'!\[([^\]]*)\]\(([^)]+)\)', replace_ref, markdown_text)

        return markdown_text

    @staticmethod
    def _safe_image_name(img_key: str) -> str:
        """生成安全的图片文件名"""
        # 移除不安全字符，确保以 .png 结尾
        safe = re.sub(r'[^\w\-.]', '_', img_key)
        if not safe.lower().endswith(('.png', '.jpg', '.jpeg', '.gif', '.webp', '.bmp')):
            safe += '.png'
        return safe

    @staticmethod
    def _resolve_image_data(image_value: str) -> Optional[bytes]:
        """
        解析图片数据，支持两种格式:
        1. HTTP URL → 下载获取二进制数据
        2. base64 字符串 → 解码获取二进制数据
        """
        if not image_value:
            return None

        # URL 格式
        if image_value.startswith(("http://", "https://")):
            try:
                headers = {
                    "Cache-Control": "no-cache, no-store, must-revalidate",
                    "Pragma": "no-cache",
                }
                resp = httpx.get(image_value, timeout=30.0, follow_redirects=True, headers=headers)
                resp.raise_for_status()
                if not resp.content:
                    logger.warning(f"下载图片为空 (status={resp.status_code}): {image_value[:80]}...")
                    return None
                return resp.content
            except Exception as e:
                logger.warning(f"下载图片失败 [{image_value[:80]}...]: {e}")
                return None

        # base64 data URI 格式 (data:image/png;base64,...)
        if image_value.startswith("data:"):
            try:
                base64_part = image_value.split(",", 1)[1]
                return base64.b64decode(base64_part)
            except Exception:
                logger.warning(f"base64 data URI 解码失败: {image_value[:80]}...")
                return None

        # 纯 base64 字符串
        try:
            return base64.b64decode(image_value)
        except Exception:
            logger.warning(f"base64解码失败: {image_value[:80]}...")
            return None

    def save_report(
        self,
        original_filename: str,
        markdown_text: str,
        images: Dict[str, str],
        layout_image_base64: Optional[str] = None,
        layout_items: Optional[List[Dict[str, Any]]] = None,
        original_image_data: Optional[bytes] = None,
        structure_result: Optional[Dict[str, Any]] = None,
        processing_time: float = 0,
    ) -> Path:
        """
        保存完整报告到磁盘。

        目录结构:
        output/20240608_120000/
            report.md              - 完整报告
            img_0.png              - 内嵌图片1
            img_1.png              - 内嵌图片2
            layout_analysis.png    - 版面分析可视化
            original.png           - 原始上传图片
            api_response.json      - API原始返回
        """
        now = datetime.now()
        report_name = now.strftime("%Y%m%d_%H%M%S")
        report_dir = self.output_dir / report_name
        report_dir.mkdir(parents=True, exist_ok=True)

        try:
            # 1. 构建并保存 Markdown 报告
            report_content = self.build_report(
                original_filename=original_filename,
                markdown_text=markdown_text,
                images=images,
                layout_image_base64=layout_image_base64,
                layout_items=layout_items,
                structure_result=structure_result,
                processing_time=processing_time,
            )
            md_path = report_dir / "report.md"
            with open(md_path, "w", encoding="utf-8") as f:
                f.write(report_content)
            logger.info(f"Markdown报告已保存: {md_path}")

            # 2. 保存内嵌图片到 imgs/ 子目录（支持 base64 和 URL 两种格式）
            imgs_dir = report_dir / "imgs"
            imgs_dir.mkdir(exist_ok=True)
            for img_key, img_value in images.items():
                try:
                    img_data = self._resolve_image_data(img_value)
                    if img_data:
                        safe_name = self._safe_image_name(img_key)
                        img_path = imgs_dir / safe_name
                        with open(img_path, "wb") as f:
                            f.write(img_data)
                except Exception as e:
                    logger.warning(f"保存内嵌图片失败 [{img_key}]: {e}")

            # 3. 保存版面分析可视化图
            if layout_image_base64:
                try:
                    layout_data = self._resolve_image_data(layout_image_base64)
                    if layout_data:
                        layout_path = report_dir / "layout_analysis.png"
                        with open(layout_path, "wb") as f:
                            f.write(layout_data)
                except Exception as e:
                    logger.warning(f"保存版面可视化图失败: {e}")

            # 4. 保存原始上传图片
            if original_image_data:
                orig_path = report_dir / "original.png"
                with open(orig_path, "wb") as f:
                    f.write(original_image_data)

            # 5. 保存 API 原始返回（调试用）
            if structure_result:
                api_path = report_dir / "api_response.json"
                with open(api_path, "w", encoding="utf-8") as f:
                    json.dump(structure_result, f, ensure_ascii=False, indent=2)

            logger.info(f"报告保存完成: {report_dir}")
            return report_dir

        except Exception as e:
            logger.error(f"保存报告失败: {e}")
            raise
