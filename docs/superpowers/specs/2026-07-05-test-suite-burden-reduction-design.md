# 测试套件维护负担精简设计

**日期**: 2026-07-05
**状态**: 已批准（用户口头确认各章节）
**前置工作**: 2026-07-03-test-suite-pruning-design.md（第一轮裁剪已完成 7/14 任务）

---

## 1. 目标与范围

**目标**: 在不丢失任何业务覆盖点的前提下，消除 `test_security.py` 28 处 app 重载 copy-paste、修复 5 个集成类的 `@pytest.mark.unit` mislabel、放宽 5 处脆性断言、删除 1 个零覆盖测试类、合并 1 对文件内重复测试。

**范围**: 仅修改 `tests/` 下文件与 `tests/conftest.py`，不触碰 `apps/` 源码。

**改动分类**（4 类）:
1. **删除零价值**: `TestReportDeleteSecurity` 类、`test_history_accumulates_correctly` 方法
2. **Setup 去重**: 抽取 `_load_backend_app` helper、`svc_factory` fixture、共享 fixture 提到 session scope
3. **Mislabel 修正**: 5 个集成类改标 `@pytest.mark.integration`（不移动文件）
4. **脆性放宽**: CSP 切片、handler 类型、线程名格式、API key 前缀长度等 5 处断言放宽

**明确不做**:
- 不执行原计划 Tasks 8-12（移动 5 个类到 test_api.py）——分析发现移动不降 setup 成本，只是表面工作
- 不抽取源码层 `_is_internal_ip` / `_validate_result_url` 共享模块（属源码重构，应独立立项）
- 不减少 `test_task_service.py` 并发测试线程数（10×100→3×20 可能漏 race condition）
- 不改 `api_client` fixture 的 scope（保留 function scope，仅抽取 helper；scope 调整降级为可选项，不在本轮做）

**预期效果**: ~10 个测试删除/放宽，`test_security.py` 减约 200 行，`test_task_service.py` 减约 100 行，`pytest -m unit` 能正确快速跑通。

---

## 2. 删除零价值测试

### 2.1 删除 `TestReportDeleteSecurity` 类

**位置**: `tests/test_security.py` line 588-638

**删除原因**: 测试方法内部重新定义本地 `_test_safe_report_dir` 函数，不导入 `apps.web.api.main._safe_report_dir`。如果 main.py 的 `_safe_report_dir` 实现变了，这两个测试不会感知——它们测的是"我手写的函数"，不是项目代码。**覆盖点为零**。

**涉及方法**:
- `TestReportDeleteSecurity::test_safe_report_dir_rejects_file`
- `TestReportDeleteSecurity::test_safe_report_dir_allows_directory`

### 2.2 删除 `test_history_accumulates_correctly` 方法

**位置**: `tests/test_api.py::TestEndToEndFlow::test_history_accumulates_correctly` (line 624)

**删除原因**: 与 `test_full_pipeline_multiple_files` (line 602) 走同一代码路径（多次 upload/submit/poll 循环），仅循环次数（3 vs 2）和断言重点（completed vs history total）不同。

**前置确认**: 删除前检查 `test_full_pipeline_multiple_files` 是否已断言 history total。若未断言，则在 `test_full_pipeline_multiple_files` 中补充 `len(history) == 3` 断言后再删除。

---

## 3. Setup 去重

### 3.1 抽取 `_load_backend_app` helper

**问题**: `test_security.py` 28 处 `importlib.util.spec_from_file_location` + `exec_module` + settings 修改 copy-paste，module name 还要手动保证唯一。

**方案**: 在 `tests/conftest.py` 新增模块级 helper:

```python
def _load_backend_app(temp_dir, name_suffix="", mock_paddle=True):
    """加载 backend main.py 并返回 backend_main 模块

    替代 28 处 importlib.util.spec_from_file_location copy-paste。
    每次调用生成唯一 module name，避免 sys.modules 冲突。

    Args:
        temp_dir: 临时目录 Path 对象
        name_suffix: 模块名后缀（用于避免 sys.modules 冲突）
        mock_paddle: 是否 mock paddle_service 的 submit_task/poll_once/extract_result

    Returns:
        backend_main 模块对象（含 app, paddle_service 等属性）
    """
    from apps.web.api.config import settings
    settings.upload_dir = str(temp_dir / "uploads")
    settings.output_dir = str(temp_dir / "output")
    settings.log_dir = str(temp_dir / "logs")
    settings.paddleocr_api_key = "test_token_for_mock"

    Path(settings.upload_dir).mkdir(parents=True, exist_ok=True)
    Path(settings.output_dir).mkdir(parents=True, exist_ok=True)
    Path(settings.log_dir).mkdir(parents=True, exist_ok=True)

    backend_main_path = Path(__file__).parent.parent / "apps" / "web" / "api" / "main.py"
    unique_name = f"backend_main_{name_suffix}_{id(temp_dir)}"
    spec = importlib.util.spec_from_file_location(unique_name, backend_main_path)
    backend_main = importlib.util.module_from_spec(spec)
    sys.modules[unique_name] = backend_main
    spec.loader.exec_module(backend_main)

    # 重置 task_service DB 连接（settings.output_dir 已改）
    from apps.web.api.services.task_service import task_service
    task_service._task_store.clear()
    task_service._history.clear()
    if task_service._db is not None:
        try:
            task_service._db.close()
        except Exception:
            pass
        task_service._db = None

    return backend_main
```

**应用范围**:
- `test_security.py` 5 个集成测试类所有方法内的 setup 段替换为单行 `backend_main = _load_backend_app(temp_dir, "auth")`
- `test_api.py::api_client` fixture 内部 setup 替换为 helper 调用（含 paddle mock 逻辑保留在 fixture 内）
- `test_api.py` 中 `TestSubmitUrlAPI` / `TestBatchAPI` / `TestBatchDownloadAPI` / `TestUploadAndProcessAPI` / `TestBatchDeleteConcurrency` 等自定义 setup 替换为 helper 调用

### 3.2 `api_client` fixture 保留 function scope

**修订说明**: 原方案考虑改 `scope="module"` + autouse 清理，但有状态泄漏风险。修订为**保留 `scope="function"`**，仅抽取 helper（3.1）。运行时间下降幅度减小，但风险降为低。scope 调整作为可选项不在本轮做。

### 3.3 抽取 `svc_factory` fixture

**位置**: `tests/test_task_service.py`

**问题**: 9 个测试类、20+ 个测试方法每个都写 5-7 行 monkeypatch `_get_db_path` + 实例化 `TaskService` 的模板。

**方案**: 在 `tests/test_task_service.py` 顶部新增 fixture:

```python
@pytest.fixture
def svc_factory(temp_dir, monkeypatch):
    """返回工厂函数：调用 (name) 返回 (svc, db_path)

    替代 20+ 处手动 monkeypatch _get_db_path + TaskService() 模板。
    每次调用生成独立的 db_path（基于 name 参数），避免类间污染。
    """
    import importlib
    ts_module = importlib.import_module("apps.web.api.services.task_service")

    def _create(name="default"):
        db_path = temp_dir / f"test_{name}.db"
        monkeypatch.setattr(ts_module, "_get_db_path", lambda: db_path)
        return ts_module.TaskService(), db_path
    return _create
```

**改动**: 所有测试方法将 5-7 行 setup 替换为 `svc, db_path = svc_factory("类名_测试名")`。

### 3.4 `sample_image_bytes` / `sample_image_file` 改 `scope="session"`

**位置**: `tests/conftest.py`

**理由**: 纯内存不可变对象（PIL.Image.new + save JPEG bytes），无副作用，function scope 重复创建纯属浪费。

**方案**:
```python
@pytest.fixture(scope="session")
def sample_image_bytes():
    """生成测试用 JPEG 图片字节（session scope：纯内存不可变）"""
    from PIL import Image
    img = Image.new("RGB", (100, 100), color=(255, 0, 0))
    buf = io.BytesIO()
    img.save(buf, format="JPEG")
    return buf.getvalue()

@pytest.fixture(scope="session")
def sample_image_file(sample_image_bytes):
    """生成测试用 JPEG 文件（session scope：独立 temp 文件，不依赖 function-scope temp_dir）"""
    import tempfile, os
    file_path = Path(tempfile.gettempdir()) / f"claw_sample_{os.getpid()}.jpg"
    file_path.write_bytes(sample_image_bytes)
    yield file_path
    file_path.unlink(missing_ok=True)
```

---

## 4. Mislabel 修正

### 4.1 5 个集成类改标 `@pytest.mark.integration`

**位置**: `tests/test_security.py`

**问题**: 5 个类通过 `importlib` 重载整个 FastAPI app + TestClient，本质是集成测试，但标为 `@pytest.mark.unit`。导致 `pytest -m unit` 实际跑不通快速测试。

**改动**: 将以下 5 个类的 `@pytest.mark.unit` 改为 `@pytest.mark.integration`:

| 类名 | line | 方法数 |
|------|------|--------|
| `TestAuthMiddleware` | 953 | 4 |
| `TestRateLimit` | 428 | 2 |
| `TestSecurityHeadersMiddleware` | 1120 | 2 |
| `TestErrorMessagesEnv` | 260 | 2 |
| `TestHistoryIdFormat` | 137 | 2 |

**不移动文件**: 分析发现移动到 `test_api.py` 不降 setup 成本（仍需 app 加载），只是表面工作。改 marker 即可让 `pytest -m unit` 正确快速跑通。

---

## 5. 脆性断言放宽

### 5.1 放宽 `TestSecurityHeadersMiddleware::test_csp_header_restricts_script_sources`

**位置**: `tests/test_security.py` line 1163

**问题**: `assert "https://" not in csp.split("script-src")[1].split(";")[0]` 假设 CSP 格式严格是 `script-src ...; ...`。

**放宽为**:
```python
# 验证 script-src 指令不含 unsafe-inline 或外域 URL
script_src_part = ""
for directive in csp.split(";"):
    if "script-src" in directive:
        script_src_part = directive
        break
assert "unsafe-inline" not in script_src_part
assert "unsafe-eval" not in script_src_part
assert "'self'" in script_src_part or "https://" not in script_src_part
```

### 5.2 删除 `TestLoggerHandlers::test_has_console_handler`

**位置**: `tests/test_logger.py` line 32

**问题**: 断言 `logger.handlers` 中存在 `logging.StreamHandler` 实例。handler 类型是实现细节。

**放宽为**: 删除此方法。`test_logger_has_handlers`（同文件）已覆盖"handlers 不为空"行为。

### 5.3 放宽 `TestApiTaskBasic::test_api_task_name_format`

**位置**: `tests/test_api_task.py` line 200

**问题**: 断言 `task.objectName()` 包含 `"API-GET-/api/health"`。线程命名格式是内部实现细节。

**放宽为**:
```python
def test_api_task_name_format(self, qtbot):
    """线程 objectName 应包含 method 和 endpoint 信息（不依赖具体格式）"""
    task = ApiGetTask(url="http://localhost:8000/api/health")
    name = task.objectName()
    assert "GET" in name
    assert "/api/health" in name
```

### 5.4 放宽 `TestThreadSafety::test_thread_name_unique_counter`

**位置**: `tests/test_api_task.py` line 463

**问题**: 写死 `"Worker-{counter}"` 格式，通过 `n.split("-")[1]` 提取 counter。

**放宽为**:
```python
def test_thread_name_unique_counter(self, qtbot):
    """5 个工作线程的 objectName 应互不相同"""
    tasks = []
    for _ in range(5):
        task = ApiGetTask(url="http://localhost:8000/api/health")
        tasks.append(task)
    names = [t.objectName() for t in tasks]
    assert len(set(names)) == 5  # 仅断言唯一性，不依赖命名格式
```

### 5.5 放宽 `TestErrorHandling::test_api_key_not_leaked_in_config`

**位置**: `tests/test_api.py` line 677

**问题**: `assert len(prefix) < 20`。前缀长度是实现选择，不是 API 契约。

**放宽为**:
```python
# API key 不应完整出现在响应中
assert prefix != settings.paddleocr_api_key
assert settings.paddleocr_api_key not in resp.text
# 不再断言 len(prefix) < 20
```

### 5.6 不放宽的项（保留）

| 测试 | 原因 |
|------|------|
| `test_ui_guidelines.py::test_no_three_dot_ellipsis_in_html` | 文案级断言适合迁移到 lint，但迁移属另一任务，本轮不动 |
| `test_ui_guidelines.py::test_labels_associated_with_inputs` | 删除会降无障碍覆盖，改写逻辑复杂，本轮不动 |
| `test_paddle_service_standalone.py` SSRF 参数化用例 | 与 `test_paddle_service.py` 覆盖点重叠但保留差异用例，删除会丢差异覆盖 |

---

## 6. 风险与回滚

### 6.1 风险矩阵

| 改动 | 风险 | 缓解 |
|------|------|------|
| 删除 `TestReportDeleteSecurity` | 低 | 已确认覆盖点为零 |
| 删除 `test_history_accumulates_correctly` | 低 | 删前确认 `test_full_pipeline_multiple_files` 已断言 history total |
| `_load_backend_app` helper 抽取 | 低 | 纯重构，行为不变；逐个类替换后跑测试验证 |
| `api_client` 保留 function scope | 低 | 无 scope 变化 |
| `svc_factory` fixture 抽取 | 低 | 纯重构，monkeypatch 行为不变 |
| `sample_image_*` 改 session scope | 低 | 纯内存不可变对象，无副作用 |
| 5 个类改 `@pytest.mark.integration` | 低 | 仅 marker 变化，测试逻辑不变 |
| 5 处脆性断言放宽 | 中 | 每处放宽后单独跑测试验证；断言放宽不删覆盖点 |

### 6.2 回滚策略

- **每个改动单独提交**: 5 类改动分批提交，每批一个 commit
- **任一提交后测试失败**: `git revert <commit>` 单独回滚
- **总验证点**: 每节改动后跑 `python -m pytest tests/ -v`，最终跑 `python -m pytest tests/ -m unit -v` 验证 mislabel 修正生效

### 6.3 验证清单

- [ ] `pytest tests/` 通过数与改动前一致或减少（减少数 = 删除的测试数）
- [ ] `pytest tests/ -m unit` 不再包含 5 个集成类
- [ ] `pytest tests/ -m integration` 包含 5 个集成类
- [ ] `test_security.py` 代码行数减少约 200 行（28 处 copy-paste → 1 个 helper）
- [ ] `test_task_service.py` 代码行数减少约 100 行（20+ 处 monkeypatch → 1 个 fixture）
- [ ] 无新增 skip 测试

---

## 7. 任务清单概览

| # | 任务 | 文件 | 类型 | 并行性 |
|---|------|------|------|--------|
| T1 | 删除 `TestReportDeleteSecurity` 类 | test_security.py | 删除零价值 | 可独立 |
| T2 | 删除 `test_history_accumulates_correctly`（含前置确认） | test_api.py | 删除零价值 | 可独立 |
| T3 | 在 `conftest.py` 新增 `_load_backend_app` helper | conftest.py | Setup 去重 | T4/T5/T6 前置 |
| T4 | `test_security.py` 5 个集成类替换 setup 为 helper 调用 | test_security.py | Setup 去重 | 依赖 T3，与 T9 同文件 |
| T5 | `test_api.py::api_client` fixture 替换 setup 为 helper 调用 | test_api.py | Setup 去重 | 依赖 T3，与 T2/T6 同文件 |
| T6 | `test_api.py` 4-5 处自定义 setup 替换为 helper | test_api.py | Setup 去重 | 依赖 T3，与 T2/T5 同文件 |
| T7 | `test_task_service.py` 抽取 `svc_factory` fixture | test_task_service.py | Setup 去重 | 可独立 |
| T8 | `sample_image_bytes` / `sample_image_file` 改 session scope | conftest.py | Setup 去重 | 与 T3 同文件 |
| T9 | 5 个集成类 marker: `unit` → `integration` | test_security.py | Mislabel 修正 | 与 T4 同文件 |
| T10 | 放宽 5 处脆性断言 | 4 个文件 | 脆性放宽 | 可独立 |
| T11 | 最终验证 | - | 验证 | 最后 |

**并行批次**:
- 批次 1（独立）: T1, T2, T7, T10
- 批次 2（依赖 T3）: T3 + T8（同文件 conftest.py，合并执行）
- 批次 3（依赖 T3）: T4 + T9（同文件 test_security.py，合并执行）
- 批次 4（依赖 T3）: T5 + T6 + T2（同文件 test_api.py，合并执行；T2 已在批次 1 执行则跳过）
- 批次 5: T11 最终验证

**预期提交数**: 约 8-10 个 commit。
