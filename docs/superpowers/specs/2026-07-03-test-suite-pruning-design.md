# 测试套件中度精简 + SSRF 盲区补测设计

**日期**: 2026-07-03
**状态**: 已批准（待实施）
**类型**: 测试质量改进

## 1. 背景与目标

### 1.1 当前状况

测试套件经多轮 QA 后膨胀至 **357 个测试方法、6389 行代码、11 个测试文件**。其中存在：

- **测试被测代码以外事物的测试**（~13 个）：测试 Python `logging` 标准库缓存机制、测试 lambda 闭包语言语义、零断言测试
- **边界值过度拆分**（~47 个方法）：同一函数被拆成 6-11 个测试方法，断言点相同但输入变体不同
- **职责边界模糊**：`test_api.py` 与 `test_security.py` 都通过 `spec_from_file_location` 重新加载 `main.py`，双重覆盖 ~95 个测试
- **长期 skip 的死测试**：5 个 PyQt6 信号测试因 mock 环境不稳定被 skip，长期无价值产出
- **高风险盲区**：`apps/desktop/paddle_service_standalone.py`（791 行，含刚修复的 SSRF 防护逻辑）零测试覆盖

### 1.2 目标

| 维度 | 当前 | 目标 |
|------|------|------|
| 测试方法数 | 357 | ~310 |
| 代码行数 | 6389 | ~5600 |
| 测试文件数 | 11 | 12（新增 standalone 补测文件）|
| 高风险盲区 | paddle_service_standalone.py 零覆盖 | SSRF 防护逻辑有测试覆盖 |

### 1.3 精简原则

1. **只删除"测试被测代码以外事物"的测试**：Python 标准库行为、语言语义、零断言测试
2. **参数化合并保留所有覆盖点**：用 `@pytest.mark.parametrize` 把同断言点变体合并，覆盖点不减少
3. **物理移动明确职责边界**：`test_security.py` 只留纯函数单元测试，集成测试移到 `test_api.py`
4. **补测优先于精简**：确保高风险盲区先有覆盖

### 1.4 验证策略

每个步骤完成后运行 `python -m pytest tests/ -q` 确认 0 失败，4 步全部完成后运行完整套件做最终验证。

## 2. 步骤 1：删除无价值测试

**风险**：极低
**预计删除**：13 个测试方法，~150 行代码

### 2.1 test_logger.py（删除 6 个）

| 测试类 | 方法 | 删除理由 |
|--------|------|---------|
| `TestLoggerWriting` | `test_info_log` | 零 assert，仅调用 `logger.info("Test info")` |
| `TestLoggerWriting` | `test_warning_log` | 零 assert |
| `TestLoggerWriting` | `test_error_log` | 零 assert |
| `TestLoggerWriting` | `test_format_log` | 零 assert |
| `TestSetupLogger` | `test_same_name_reuses_logger` | 测试 Python `logging.getLogger` 缓存机制 |
| `TestSetupLogger` | `test_different_names_different_loggers` | 测试标准库行为 |

**保留**：`TestSetupLogger::test_logger_name_correct`（验证项目函数返回值）、`TestLoggerHandlers`（验证项目配置的 handler）。

### 2.2 test_api_task.py（删除 9 个）

| 测试类 | 方法 | 删除理由 |
|--------|------|---------|
| `TestLambdaVariableCapture` | `test_default_arg_captures_current_value` | 测试 Python lambda 默认参数捕获语义 |
| `TestLambdaVariableCapture` | `test_closure_captures_variable_not_value` | 测试语言闭包机制 |
| `TestLambdaVariableCapture` | `test_default_arg_works_as_expected` | 同上 |
| `TestLambdaVariableCapture` | `test_lambda_capture_does_not_break_logic` | 同上 |
| `TestApiTaskBasic` | `test_api_task_finished_signal_on_success` | `@pytest.mark.skip` 长期跳过 |
| `TestApiTaskBasic` | `test_api_task_error_signal_on_failure` | `@pytest.mark.skip` |
| `TestSubmitWorker` | `test_submit_worker_result_type_validation` | `@pytest.mark.skip` |
| `TestPollWorker` | `test_poll_worker_gathers_multiple_tasks` | `@pytest.mark.skip` |
| `TestPollWorker` | `test_poll_worker_handles_task_error` | `@pytest.mark.skip` |

**删除整个 `TestLambdaVariableCapture` 类**（4 个方法），因为整个类测试的是 Python 语言语义而非项目代码。

## 3. 步骤 2：参数化合并边界值测试

**风险**：低
**预计减少**：~47 个方法 → ~13 个参数化测试，~600 行代码减少
**覆盖点**：不减少（参数化后每个用例仍独立计数）

### 3.1 test_security.py

#### TestIsValidReportIdFormat（11 → 3）

合并为 3 个参数化测试：

```python
@pytest.mark.parametrize("report_id,expected", [
    ("20260613_235614_a1b2c3d4", True),
    ("20260613_235614", True),
    ("20260613_235614_A1B2C3D4", True),
    ("report-1", True),
    ("", False),
    ("a" * 65, False),
])
def test_valid_and_invalid_formats(report_id, expected):
    assert _is_valid_report_id_format(report_id) is expected

@pytest.mark.parametrize("malicious", [
    "../../etc/passwd", "../secret", "..\\windows\\system32",
    "report|test", "report;rm -rf", "report`echo`",
    "report/test", "report\\test",
])
def test_malicious_ids_rejected(malicious):
    assert _is_valid_report_id_format(malicious) is False

def test_edge_cases():
    # 含点号和空格
    assert _is_valid_report_id_format("report.test") is False
    assert _is_valid_report_id_format("report test") is False
    # 刚好 64 字符通过
    assert _is_valid_report_id_format("a" * 64) is True
```

#### TestMarkdownHtmlEscape（9 → 2）

合并为 2 个参数化测试：

```python
@pytest.mark.parametrize("payload", [
    "<script>alert('xss')</script>",
    '<img src=x onerror=alert(1)>',
    '<table><tr><td>inject</td></tr></table>',
    '```\ncode block injection\n```',
    '<blockquote>quoted</blockquote>',
    '![alt](javascript:alert(1))',
])
def test_xss_payloads_escaped(payload):
    html = render_markdown_html(payload, ...)
    assert "<script>" not in html
    assert "onerror=" not in html
    assert "<img" not in html or html.count("&lt;img") >= 0

def test_empty_and_plain_text():
    # 空字符串和纯文本不破坏
    assert render_markdown_html("", ...) == ""
    plain = "Hello World"
    assert render_markdown_html(plain, ...) == plain
```

### 3.2 test_paddle_service.py

#### TestValidateResultUrl（10 → 3）

```python
@pytest.mark.parametrize("url", [
    "https://paddleocr.baidu.com/result.json",
    "http://example.com/file.md",
])
def test_valid_urls_pass(url):
    _validate_result_url(url)  # 不抛异常

@pytest.mark.parametrize("url", [
    "https://localhost/result.json",
    "https://127.0.0.1/result.json",
    "https://10.0.0.1/result.json",
    "https://172.16.0.1/result.json",
    "https://192.168.1.1/result.json",
    "https://[::1]/result.json",
])
def test_internal_urls_rejected(url):
    with pytest.raises(ResultUrlValidationError):
        _validate_result_url(url)

@pytest.mark.parametrize("url", [
    "", "ftp://example.com/file.json", "file:///etc/passwd",
    "https:///nohost", "https://",
])
def test_invalid_format_rejected(url):
    with pytest.raises(ResultUrlValidationError):
        _validate_result_url(url)
```

#### TestPaddleIsInternalIp（6 → 1）

```python
@pytest.mark.parametrize("host,expected", [
    ("localhost", True),
    ("127.0.0.1", True),
    ("10.0.0.1", True),
    ("172.16.0.1", True),
    ("192.168.1.1", True),
    ("8.8.8.8", False),
    ("example.com", False),
])
def test_is_internal_ip(host, expected):
    assert _is_internal_ip(host) is expected
```

### 3.3 test_markdown_generator.py

#### TestEscapeMdTableCell（11 → 4）

保留 4 个有差异化断言的测试：
- `test_escapes_pipe_and_newline`（合并原 pipe + newline 两个，断言转义后字符）
- `test_escapes_html_tags`（合并原 angle brackets 测试，断言 `&lt;` `&gt;`）
- `test_handles_empty_and_none`（合并原 empty string + None + non-string）
- `test_build_report_integration`（保留 build_report 集成测试，断言完整报告输出）

删除 7 个同断言点的变体测试。

## 4. 步骤 3：物理移动集成测试类

**风险**：中
**预计移动**：5 个测试类，~20 个测试方法

### 4.1 从 test_security.py 移到 test_api.py

| 测试类 | 方法数 | 移动理由 |
|--------|-------|---------|
| `TestAuthMiddleware` | 4 | 使用 TestClient 跑完整 FastAPI，是集成测试 |
| `TestRateLimit` | 2 | 使用 TestClient，标记应为 integration |
| `TestSecurityHeadersMiddleware` | 2 | 使用 TestClient，是集成测试 |
| `TestHistoryIdFormat` | 2 | 跑完整上传→提交→轮询→查历史流程 |
| `TestErrorMessagesEnv` | 2 | 端到端验证 debug 模式错误消息 |

### 4.2 移动后 test_security.py 只保留

- `TestSecureFilename`（纯函数单元测试）
- `TestSecurityUtils`（纯函数）
- `TestIsValidReportIdFormat`（参数化合并后）
- `TestMarkdownHtmlEscape`（参数化合并后）
- `TestMarkdownLengthLimit`（纯函数）
- `TestReportDeleteSecurity`（纯函数）
- `TestSQLiteWAL`（数据库配置检查）
- `TestUtils`（`format_size` 工具函数）

### 4.3 test_api.py 新增分区

```python
# ──────────────────────────────────────────────────
# 安全相关集成测试（从 test_security.py 迁入）
# ──────────────────────────────────────────────────
```

移动的测试类标记为 `@pytest.mark.integration`。

### 4.4 注意事项

- 移动时需确保 import 依赖正确（`TestClient`、`spec_from_file_location` 等）
- 移动后需验证 `@pytest.mark.integration` 标记正确设置
- 不删除任何测试逻辑，只改变文件归属

## 5. 步骤 4：补测 SSRF 盲区

**风险**：低
**预计新增**：~6-8 个测试方法，~150 行代码

### 5.1 新增测试文件

`tests/test_paddle_service_standalone.py`

### 5.2 测试清单

| 测试类 | 测试方法 | 被测函数 | 验证点 |
|--------|---------|---------|--------|
| `TestStandaloneValidateResultUrl` | `test_valid_url_passes` | `_validate_result_url` | https 公网 URL 通过 |
| | `test_empty_url_rejected` | | 空 URL 抛 `ResultUrlValidationError` |
| | `test_non_http_rejected` | | 非 http(s) 协议被拒 |
| | `test_localhost_rejected` | | localhost 被拒 |
| | `test_internal_ip_rejected` | | 10.x/172.16.x/192.168.x 被拒 |
| | `test_dns_resolution_to_internal_rejected` | | 解析到内网的域名被拒 |
| `TestStandaloneDownloadResultJson` | `test_ssrf_blocked_returns_empty` | `_download_result_json` | SSRF URL 时返回 `("", None)` |
| `TestStandaloneDownloadMarkdownResult` | `test_ssrf_blocked_returns_empty` | `_download_markdown_result` | SSRF URL 时返回 `""` |

### 5.3 测试策略

- 直接导入 `apps.desktop.paddle_service_standalone` 模块
- 对 `_validate_result_url` 和 `_is_internal_ip` 用真实函数测试（不 mock）
- 对下载方法测试 SSRF 拦截行为（验证返回空值，不实际发起网络请求）
- 标记为 `@pytest.mark.unit`

## 6. 执行顺序与验证

| 步骤 | 操作 | 预计减少方法数 | 预计减少代码行 | 验证命令 |
|------|------|--------------|--------------|---------|
| 1 | 删除无价值测试 | -13 | -150 | `pytest tests/ -q` |
| 2 | 参数化合并 | -34（方法数，覆盖点不减） | -600 | `pytest tests/ -q` |
| 3 | 物理移动 | 0（只移动） | 0 | `pytest tests/ -q` |
| 4 | 补测 SSRF | +8 | +150 | `pytest tests/ -q` |
| **合计** | | **-39** | **-600** | |

最终验证：`python -m pytest tests/ -v --tb=short` 确认 0 失败。

## 7. 不在本次范围内

以下问题在分析中发现但本次不处理：

1. **被测代码重复**：`_is_internal_ip` 在 `main.py`、`paddle_service.py`、`paddle_service_standalone.py`、`markdown_generator.py` 四处重复实现。建议未来抽取到共享的 `security_utils.py` 模块。
2. **私有方法测试重构**：`TestBuildHeadersBearer`、`TestImagePathReplacement` 等改为通过公开接口间接验证。属于"激进精简"范畴。
3. **低价值常量断言**：`test_config.py` 中验证默认常量值的测试。保留作为烟雾测试。
4. **5 个 skip 测试的替代方案**：引入 pytest-qt 在真实 Qt 环境下补测。本次直接删除。
