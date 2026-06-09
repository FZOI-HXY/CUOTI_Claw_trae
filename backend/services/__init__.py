"""后端服务层 - 业务逻辑与状态管理"""
# pyright: reportUnusedImport=false
from backend.services.task_service import TaskService, task_service
from backend.services.config_service import save_env_file, ENV_KEY_MAPPING
from backend.services.paddle_parser import extract_ocr_result, _extract_ocr_items, _parse_result_json

