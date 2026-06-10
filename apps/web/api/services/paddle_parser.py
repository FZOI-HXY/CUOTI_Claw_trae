"""
PaddleOCR 结果解析器
将 PaddleOCR API 返回的 JSON/JSONL 结果提取为结构化数据
"""
import json
from typing import Dict, Any

from apps.web.api.logger import setup_logger

logger = setup_logger("PaddleParser")


def extract_ocr_result(poll_result: Dict[str, Any]) -> Dict[str, Any]:
    """
    从 JSON/JSONL 结果中提取结构化数据

    支持的结果字段:
    - layoutParsingResults[].markdown.text / markdown.images (PP-StructureV3 / VL系列)
    - layoutParsingResults[].outputImages (PP-StructureV3 输出图片)
    - ocrResults[].ocrImage (PP-OCRv5)
    - layoutParsingResults[].layoutType / region (版面分析)

    JSONL 每行格式 (官方API):
    {
        "result": {
            "layoutParsingResults": [
                {
                    "markdown": {
                        "text": "Markdown文本",
                        "images": {"img_0": "https://..."}
                    },
                    "outputImages": {"0": "https://..."},
                    "layoutType": "text/table/figure/...",
                    "region": {"x": ..., "y": ..., "width": ..., "height": ...}
                }
            ]
        }
    }

    返回: {"markdown_text": "...", "images": {...}, "layout_image": "...",
           "layout_items": [{"type": "...", "region": {...}}, ...]}
    """
    extracted = {
        "markdown_text": "",
        "images": {},
        "layout_image": None,
        "layout_items": [],
    }

    try:
        json_text = poll_result.get("json_text", "")
        raw_json = poll_result.get("raw_json")

        # 如果 API 直接返回了 markdown_text，优先使用
        direct_md = poll_result.get("markdown_text", "")
        if direct_md:
            extracted["markdown_text"] = direct_md
            logger.info(f"使用API直接返回的Markdown: {len(direct_md)}字符")

        # 优先使用已解析的 raw_json
        if raw_json is not None:
            parsed_list = _extract_ocr_items(raw_json)
        elif json_text:
            parsed_list = _parse_result_json(json_text)
        else:
            if not direct_md:
                logger.warning("JSON 结果为空，无可用数据")
            return extracted

        if not parsed_list:
            if not direct_md:
                logger.warning("解析结果中未找到有效的 OCR 数据")
            return extracted

        md_parts = []
        all_images = {}

        for item_index, ocr_result_item in enumerate(parsed_list):
            markdown_data = ocr_result_item.get("markdown", {})
            if not markdown_data:
                pruned = ocr_result_item.get("prunedResult", {})
                markdown_data = pruned.get("markdown", {})

            # 提取 Markdown 文本
            md_text = markdown_data.get("text", "")
            if md_text:
                md_parts.append(str(md_text))

            # 提取内嵌图片（URL）
            images_map = markdown_data.get("images", {})
            if isinstance(images_map, dict):
                for img_key, img_value in images_map.items():
                    if isinstance(img_value, str) and img_value:
                        unique_key = (
                            f"img_{item_index}_{img_key}"
                            if item_index > 0
                            else img_key
                        )
                        all_images[unique_key] = img_value

            # 提取 outputImages
            output_images = ocr_result_item.get("outputImages", {})
            if isinstance(output_images, dict):
                for img_key, img_value in output_images.items():
                    if isinstance(img_value, str) and img_value:
                        unique_key = f"out_{item_index}_{img_key}" if item_index > 0 else img_key
                        all_images[unique_key] = img_value

            # 提取 OCR 结果图片 URL（版面图）
            ocr_image = ocr_result_item.get("ocrImage", "")
            if ocr_image and not extracted["layout_image"]:
                extracted["layout_image"] = str(ocr_image)

            # 提取 PP-StructureV3 特有字段: layoutType / region
            layout_type = ocr_result_item.get("layoutType", "")
            region = ocr_result_item.get("region", {})
            if layout_type or region:
                item_content = str(md_text).strip() if md_text else ""
                extracted["layout_items"].append({
                    "type": layout_type,
                    "region": region,
                    "content_preview": item_content[:120],
                })

            # 从 prunedResult.parsing_res_list 提取版面区域 (新版 API)
            pruned = ocr_result_item.get("prunedResult", {})
            parsing_list = pruned.get("parsing_res_list", [])
            for block in parsing_list:
                block_label = block.get("block_label", "")
                block_bbox = block.get("block_bbox", {})
                if block_label:
                    extracted["layout_items"].append({
                        "type": block_label,
                        "region": {"bbox": block_bbox},
                        "content_preview": str(block.get("block_content", ""))[:120],
                    })

        # 合并 markdown（API 直接返回的优先）
        parsed_md = "\n\n".join(md_parts)
        if parsed_md:
            if extracted["markdown_text"]:
                if len(extracted["markdown_text"]) < len(parsed_md):
                    extracted["markdown_text"] = parsed_md
            else:
                extracted["markdown_text"] = parsed_md

        extracted["images"] = all_images

        logger.info(
            f"提取结果: {len(extracted['markdown_text'])}字符Markdown, "
            f"{len(all_images)}张内嵌图片, "
            f"{len(extracted['layout_items'])}个版面区域"
        )

    except Exception as e:
        logger.error(f"解析JSON结果失败: {e}", exc_info=True)

    return extracted


def _extract_ocr_items(json_obj) -> list:
    """
    从已解析的 JSON 对象中提取 OCR 结果列表

    支持多种嵌套结构:
    - result.layoutParsingResults[] (VL系列 / PP-StructureV3，含 markdown，优先)
    - result.ocrResults[] (PP-OCRv5)
    - 直接的列表
    """
    if isinstance(json_obj, list):
        return json_obj

    result = json_obj.get("result", json_obj)

    # VL系列 / PP-StructureV3: 优先取 layoutParsingResults（含结构化 Markdown）
    layout_results = result.get("layoutParsingResults", [])
    if layout_results:
        return layout_results

    # PP-OCRv5: 只有 ocrResults
    ocr_results = result.get("ocrResults", [])
    if ocr_results:
        return ocr_results

    return []


def _parse_result_json(json_text: str) -> list:
    """
    解析结果 JSON 文本，支持三种格式：
    1. JSONL: 每行一个 JSON 对象
    2. 标准 JSON: 整个文本就是一个 JSON 对象
    3. 带 BOM 或其他前缀的 JSON

    返回 OCR 结果项列表
    """
    text = json_text.strip()
    if not text:
        return []

    # 尝试按标准 JSON 解析
    try:
        obj = json.loads(text)
        return _extract_ocr_items(obj)
    except (json.JSONDecodeError, ValueError):
        pass

    # 尝试 JSONL 格式（每行一个 JSON）
    lines = text.split("\n")
    ocr_items = []
    for line_num, line in enumerate(lines):
        line = line.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
            items = _extract_ocr_items(obj)
            ocr_items.extend(items)
        except (json.JSONDecodeError, ValueError):
            logger.warning(f"JSONL 第{line_num + 1}行解析失败，跳过")
            continue

    return ocr_items
