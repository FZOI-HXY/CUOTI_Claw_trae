"""
测试: apps/web/api/services/paddle_parser.py - PaddleOCR 结果解析器

覆盖:
  - _parse_result_json: JSON/JSONL 格式解析
  - _extract_ocr_items: 多嵌套结构提取
  - extract_ocr_result: 完整结果提取（VL/Structure/OCR 模型）
  - 错误处理与边界条件
"""

import json

import pytest


@pytest.mark.unit
class TestParseResultJson:
    """测试 _parse_result_json 函数"""

    def test_parse_standard_json(self):
        """标准 JSON 格式解析"""
        from apps.web.api.services.paddle_parser import _parse_result_json

        json_text = json.dumps({
            "result": {
                "layoutParsingResults": [
                    {"markdown": {"text": "Test content"}}
                ]
            }
        })
        result = _parse_result_json(json_text)

        assert len(result) == 1
        assert result[0]["markdown"]["text"] == "Test content"

    def test_parse_jsonl_format(self):
        """JSONL 格式解析（每行一个 JSON）"""
        from apps.web.api.services.paddle_parser import _parse_result_json

        jsonl_text = (
            '{"result": {"layoutParsingResults": [{"markdown": {"text": "Line 1"}}]}}\n'
            '{"result": {"layoutParsingResults": [{"markdown": {"text": "Line 2"}}]}}\n'
        )
        result = _parse_result_json(jsonl_text)

        assert len(result) == 2
        assert result[0]["markdown"]["text"] == "Line 1"
        assert result[1]["markdown"]["text"] == "Line 2"

    def test_parse_empty_string(self):
        """空字符串应返回空列表"""
        from apps.web.api.services.paddle_parser import _parse_result_json

        result = _parse_result_json("")
        assert result == []

    def test_parse_invalid_json(self):
        """无效 JSON 应返回空列表"""
        from apps.web.api.services.paddle_parser import _parse_result_json

        result = _parse_result_json("not valid json")
        assert result == []

    def test_parse_jsonl_with_invalid_lines(self):
        """JSONL 中包含无效行应跳过"""
        from apps.web.api.services.paddle_parser import _parse_result_json

        jsonl_text = (
            '{"result": {"layoutParsingResults": [{"text": "Valid"}]}}\n'
            'not valid json\n'
            '{"result": {"layoutParsingResults": [{"text": "Valid2"}]}}\n'
        )
        result = _parse_result_json(jsonl_text)

        assert len(result) == 2

    def test_parse_direct_list(self):
        """直接解析列表格式"""
        from apps.web.api.services.paddle_parser import _parse_result_json

        json_text = json.dumps([
            {"markdown": {"text": "Item 1"}},
            {"markdown": {"text": "Item 2"}}
        ])
        result = _parse_result_json(json_text)

        assert len(result) == 2


@pytest.mark.unit
class TestExtractOcrItems:
    """测试 _extract_ocr_items 函数"""

    def test_extract_layout_parsing_results(self):
        """提取 layoutParsingResults（VL/Structure 模型）"""
        from apps.web.api.services.paddle_parser import _extract_ocr_items

        json_obj = {
            "result": {
                "layoutParsingResults": [
                    {"type": "text", "content": "Content 1"},
                    {"type": "table", "content": "Content 2"}
                ]
            }
        }
        result = _extract_ocr_items(json_obj)

        assert len(result) == 2
        assert result[0]["type"] == "text"

    def test_extract_ocr_results(self):
        """提取 ocrResults（PP-OCRv5/v6 模型）"""
        from apps.web.api.services.paddle_parser import _extract_ocr_items

        json_obj = {
            "result": {
                "ocrResults": [
                    {"ocrImage": "img1.jpg"},
                    {"ocrImage": "img2.jpg"}
                ]
            }
        }
        result = _extract_ocr_items(json_obj)

        assert len(result) == 2

    def test_extract_direct_list(self):
        """直接列表格式"""
        from apps.web.api.services.paddle_parser import _extract_ocr_items

        json_obj = [
            {"markdown": {"text": "Direct item"}},
            {"markdown": {"text": "Direct item 2"}}
        ]
        result = _extract_ocr_items(json_obj)

        assert len(result) == 2

    def test_extract_empty_result(self):
        """空结果应返回空列表"""
        from apps.web.api.services.paddle_parser import _extract_ocr_items

        json_obj = {"result": {}}
        result = _extract_ocr_items(json_obj)

        assert result == []

    def test_extract_no_result_key(self):
        """无 result 键时直接解析"""
        from apps.web.api.services.paddle_parser import _extract_ocr_items

        json_obj = {
            "layoutParsingResults": [{"text": "No result key"}]
        }
        result = _extract_ocr_items(json_obj)

        assert len(result) == 1


@pytest.mark.unit
class TestExtractOcrResult:
    """测试 extract_ocr_result 函数"""

    def test_extract_vl_model_result(self):
        """提取 VL 模型结果（含 markdown 和 images）"""
        from apps.web.api.services.paddle_parser import extract_ocr_result

        poll_result = {
            "json_text": json.dumps({
                "result": {
                    "layoutParsingResults": [
                        {
                            "markdown": {
                                "text": "# Title\n\nContent",
                                "images": {"img_0": "https://example.com/img.png"}
                            },
                            "layoutType": "text",
                            "region": {"x": 10, "y": 10, "width": 100, "height": 50}
                        }
                    ]
                }
            })
        }
        result = extract_ocr_result(poll_result)

        assert result["markdown_text"] == "# Title\n\nContent"
        assert "img_0" in result["images"]
        assert len(result["layout_items"]) == 1
        assert result["layout_items"][0]["type"] == "text"

    def test_extract_pp_structure_v3_result(self):
        """提取 PP-StructureV3 模型结果"""
        from apps.web.api.services.paddle_parser import extract_ocr_result

        poll_result = {
            "json_text": json.dumps({
                "result": {
                    "layoutParsingResults": [
                        {
                            "markdown": {"text": "Structure content"},
                            "layoutType": "table",
                            "region": {"x": 0, "y": 0, "width": 200, "height": 100}
                        }
                    ]
                }
            })
        }
        result = extract_ocr_result(poll_result)

        assert "Structure content" in result["markdown_text"]
        assert result["layout_items"][0]["type"] == "table"

    def test_extract_pp_ocr_v5_result(self):
        """提取 PP-OCRv5 模型结果（仅 ocrResults）"""
        from apps.web.api.services.paddle_parser import extract_ocr_result

        poll_result = {
            "json_text": json.dumps({
                "result": {
                    "ocrResults": [
                        {"ocrImage": "https://example.com/ocr.png"}
                    ]
                }
            })
        }
        result = extract_ocr_result(poll_result)

        assert result["layout_image"] == "https://example.com/ocr.png"

    def test_extract_with_raw_json(self):
        """使用已解析的 raw_json"""
        from apps.web.api.services.paddle_parser import extract_ocr_result

        poll_result = {
            "raw_json": {
                "result": {
                    "layoutParsingResults": [
                        {"markdown": {"text": "Raw JSON content"}}
                    ]
                }
            }
        }
        result = extract_ocr_result(poll_result)

        assert "Raw JSON content" in result["markdown_text"]

    def test_extract_direct_markdown_text(self):
        """API 直接返回的 markdown_text 优先使用"""
        from apps.web.api.services.paddle_parser import extract_ocr_result

        poll_result = {
            "markdown_text": "Direct markdown",
            "json_text": json.dumps({
                "result": {
                    "layoutParsingResults": [
                        {"markdown": {"text": "Parsed markdown"}}
                    ]
                }
            })
        }
        result = extract_ocr_result(poll_result)

        assert result["markdown_text"] == "Direct markdown"

    def test_extract_empty_result(self):
        """空结果应返回默认值"""
        from apps.web.api.services.paddle_parser import extract_ocr_result

        poll_result = {}
        result = extract_ocr_result(poll_result)

        assert result["markdown_text"] == ""
        assert result["images"] == {}
        assert result["layout_items"] == []

    def test_extract_pruned_result(self):
        """提取 prunedResult 中的数据（新版 API）"""
        from apps.web.api.services.paddle_parser import extract_ocr_result

        poll_result = {
            "json_text": json.dumps({
                "result": {
                    "layoutParsingResults": [
                        {
                            "prunedResult": {
                                "markdown": {"text": "Pruned content"},
                                "parsing_res_list": [
                                    {
                                        "block_label": "title",
                                        "block_bbox": [10, 10, 200, 50],
                                        "block_content": "Chapter 1"
                                    }
                                ]
                            }
                        }
                    ]
                }
            })
        }
        result = extract_ocr_result(poll_result)

        assert "Pruned content" in result["markdown_text"]
        assert len(result["layout_items"]) == 1
        assert result["layout_items"][0]["type"] == "title"

    def test_extract_output_images(self):
        """提取 outputImages"""
        from apps.web.api.services.paddle_parser import extract_ocr_result

        poll_result = {
            "json_text": json.dumps({
                "result": {
                    "layoutParsingResults": [
                        {
                            "outputImages": {"0": "https://example.com/out.png"}
                        }
                    ]
                }
            })
        }
        result = extract_ocr_result(poll_result)

        assert "0" in result["images"]
        assert result["images"]["0"] == "https://example.com/out.png"

    def test_extract_output_images_multiple_items(self):
        """多个结果项时 outputImages 键应添加前缀"""
        from apps.web.api.services.paddle_parser import extract_ocr_result

        poll_result = {
            "json_text": json.dumps({
                "result": {
                    "layoutParsingResults": [
                        {"outputImages": {"0": "https://example.com/img1.png"}},
                        {"outputImages": {"0": "https://example.com/img2.png"}}
                    ]
                }
            })
        }
        result = extract_ocr_result(poll_result)

        assert "0" in result["images"]
        assert "out_1_0" in result["images"]

    def test_extract_multiple_items(self):
        """提取多个 OCR 结果项"""
        from apps.web.api.services.paddle_parser import extract_ocr_result

        poll_result = {
            "json_text": json.dumps({
                "result": {
                    "layoutParsingResults": [
                        {"markdown": {"text": "Page 1"}},
                        {"markdown": {"text": "Page 2"}}
                    ]
                }
            })
        }
        result = extract_ocr_result(poll_result)

        assert "Page 1" in result["markdown_text"]
        assert "Page 2" in result["markdown_text"]

    def test_extract_error_handling(self):
        """解析错误应优雅处理"""
        from apps.web.api.services.paddle_parser import extract_ocr_result

        poll_result = {
            "json_text": "invalid json"
        }
        result = extract_ocr_result(poll_result)

        assert result["markdown_text"] == ""
        assert result["images"] == {}

    def test_extract_content_preview_truncated(self):
        """content_preview 应被截断到 120 字符"""
        from apps.web.api.services.paddle_parser import extract_ocr_result

        long_text = "a" * 200
        poll_result = {
            "json_text": json.dumps({
                "result": {
                    "layoutParsingResults": [
                        {
                            "markdown": {"text": long_text},
                            "layoutType": "text",
                            "region": {}
                        }
                    ]
                }
            })
        }
        result = extract_ocr_result(poll_result)

        assert len(result["layout_items"][0]["content_preview"]) == 120