"""
Claw 错题管理系统 - 测试运行器

功能:
  1. 自动发现并运行所有测试
  2. 生成控制台报告 (test report to console)
  3. 生成 HTML 报告 (test report HTML)
  4. 生成 JSON 报告 (test report JSON)
  5. 打印详细摘要

用法:
  python tests/run_tests.py                  # 运行所有测试
  python tests/run_tests.py --unit           # 仅运行单元测试
  python tests/run_tests.py --integration    # 仅运行集成测试
  python tests/run_tests.py -k "test_config" # 按关键词过滤
  python tests/run_tests.py --verbose        # 详细输出
"""

import os
import sys
import time
import json
import argparse
from pathlib import Path
from datetime import datetime

# 确保项目根在路径中
PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

try:
    import pytest
except ImportError:
    print("[ERROR] pytest is required. Install with: pip install pytest pytest-html")
    sys.exit(1)


# ── 报告生成 ──

def generate_html_report(results, report_path: Path, duration: float):
    """生成自定义 HTML 报告 (增强版, 不依赖 pytest-html)"""
    total = results.get("total", 0)
    passed = results.get("passed", 0)
    failed = results.get("failed", 0)
    error = results.get("error", 0)
    skipped = results.get("skipped", 0)
    xfailed = results.get("xfailed", 0)
    xpassed = results.get("xpassed", 0)

    pass_rate = (passed / total * 100) if total > 0 else 0
    status_color = "#10b981" if failed == 0 and error == 0 else "#ef4444"
    status_text = "ALL PASSED" if failed == 0 and error == 0 else "TESTS FAILED"

    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    html = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Claw Test Report</title>
<style>
* {{ margin:0; padding:0; box-sizing:border-box; }}
body {{ font-family:'Segoe UI','Microsoft YaHei',sans-serif; background:#0f172a; color:#e2e8f0; padding:24px; }}
.container {{ max-width:960px; margin:0 auto; }}
.header {{ text-align:center; margin-bottom:32px; padding:32px; background:#1e293b; border-radius:16px; border:1px solid rgba(255,255,255,0.06); }}
.header h1 {{ font-size:28px; color:#f59e0b; margin-bottom:8px; }}
.header .subtitle {{ color:#94a3b8; font-size:14px; }}
.header .status {{ font-size:48px; font-weight:800; color:{status_color}; margin:16px 0; }}
.summary {{ display:grid; grid-template-columns:repeat(6,1fr); gap:12px; margin-bottom:32px; }}
.card {{ background:#1e293b; border-radius:12px; padding:20px; text-align:center; border:1px solid rgba(255,255,255,0.06); }}
.card .value {{ font-size:36px; font-weight:700; }}
.card .label {{ font-size:12px; color:#94a3b8; margin-top:4px; text-transform:uppercase; letter-spacing:1px; }}
.card.total .value {{ color:#f59e0b; }}
.card.passed .value {{ color:#10b981; }}
.card.failed .value {{ color:#ef4444; }}
.card.error .value {{ color:#f97316; }}
.card.skipped .value {{ color:#94a3b8; }}
.card.rate .value {{ color:#3b82f6; }}
.progress-bar {{ height:8px; background:#334155; border-radius:4px; overflow:hidden; margin-bottom:32px; }}
.progress-bar .fill {{ height:100%; background:linear-gradient(90deg,#f59e0b,#10b981); border-radius:4px; transition:width 0.3s; }}
.tests {{ background:#1e293b; border-radius:12px; border:1px solid rgba(255,255,255,0.06); overflow:hidden; }}
.tests-header {{ padding:16px 20px; border-bottom:1px solid rgba(255,255,255,0.06); font-weight:600; font-size:16px; }}
.test-item {{ padding:12px 20px; border-bottom:1px solid rgba(255,255,255,0.03); display:flex; align-items:center; gap:12px; font-size:13px; }}
.test-item:last-child {{ border-bottom:none; }}
.test-item.pass {{ border-left:3px solid #10b981; }}
.test-item.fail {{ border-left:3px solid #ef4444; background:rgba(239,68,68,0.05); }}
.test-item.error {{ border-left:3px solid #f97316; background:rgba(249,115,22,0.05); }}
.test-item.skip {{ border-left:3px solid #94a3b8; opacity:0.6; }}
.icon {{ font-size:18px; width:24px; text-align:center; }}
.name {{ flex:1; font-family:'Consolas',monospace; font-size:12px; }}
.message {{ color:#94a3b8; font-size:11px; max-width:400px; overflow:hidden; text-overflow:ellipsis; white-space:nowrap; }}
.duration {{ color:#64748b; font-size:11px; }}
.footer {{ text-align:center; padding:24px; color:#475569; font-size:12px; }}
</style>
</head>
<body>
<div class="container">
  <div class="header">
    <h1>Claw 错题管理系统 - 测试报告</h1>
    <div class="subtitle">Generated at {now} | Duration: {duration:.2f}s</div>
    <div class="status">{status_text}</div>
    <div style="color:#94a3b8;font-size:14px;">{passed}/{total} tests passed ({pass_rate:.1f}%)</div>
  </div>

  <div class="summary">
    <div class="card total"><div class="value">{total}</div><div class="label">Total</div></div>
    <div class="card passed"><div class="value">{passed}</div><div class="label">Passed</div></div>
    <div class="card failed"><div class="value">{failed}</div><div class="label">Failed</div></div>
    <div class="card error"><div class="value">{error}</div><div class="label">Errors</div></div>
    <div class="card skipped"><div class="value">{skipped}</div><div class="label">Skipped</div></div>
    <div class="card rate"><div class="value">{pass_rate:.1f}%</div><div class="label">Pass Rate</div></div>
  </div>

  <div class="progress-bar"><div class="fill" style="width:{pass_rate}%"></div></div>

  <div class="tests">
    <div class="tests-header">Test Cases</div>
"""

    # 添加测试详情
    tests_list = results.get("tests", [])
    for test in tests_list:
        outcome = test.get("outcome", "skipped")
        css_class = outcome
        icon_map = {"passed": "OK", "failed": "FAIL", "error": "ERR", "skipped": "SKIP"}
        icon = icon_map.get(outcome, "?")

        nodeid = test.get("nodeid", "")
        # 缩短测试名
        short_name = nodeid.replace("tests\\", "").replace("tests/", "").replace("test_", "")
        message = test.get("message", "")
        duration_str = f"{test.get('duration', 0):.2f}s" if test.get('duration') else ""

        html += f"""    <div class="test-item {css_class}">
      <div class="icon">{icon}</div>
      <div class="name">{short_name}</div>
      <div class="message">{message[:100]}</div>
      <div class="duration">{duration_str}</div>
    </div>
"""

    html += """  </div>
  <div class="footer">
    Claw Automated Test Suite | Powered by pytest
  </div>
</div>
</body>
</html>"""

    report_path.write_text(html, encoding="utf-8")
    return report_path


def generate_json_report(results, report_path: Path, duration: float):
    """生成 JSON 格式报告"""
    report = {
        "project": "Claw - 错题管理系统",
        "timestamp": datetime.now().isoformat(),
        "duration_seconds": round(duration, 2),
        "summary": {
            "total": results.get("total", 0),
            "passed": results.get("passed", 0),
            "failed": results.get("failed", 0),
            "error": results.get("error", 0),
            "skipped": results.get("skipped", 0),
            "xfailed": results.get("xfailed", 0),
            "xpassed": results.get("xpassed", 0),
        },
        "tests": results.get("tests", []),
    }
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return report_path


# ── 控制台摘要 ──

def print_console_summary(results: dict, duration: float):
    """打印彩色控制台摘要"""
    total = results["total"]
    passed = results["passed"]
    failed = results["failed"]
    error = results["error"]
    skipped = results["skipped"]

    print()
    print("=" * 60)
    print("  Claw 错题管理系统 - 自动化测试报告")
    print("=" * 60)
    print(f"  总用例数: {total}")
    print(f"  通过:     {passed}  OK")
    print(f"  失败:     {failed}" + ("  FAIL" if failed else ""))

    if error:
        print(f"  错误:     {error}")

    if skipped:
        print(f"  跳过:     {skipped}")

    print(f"  耗时:     {duration:.2f}s")
    print(f"  通过率:   {passed / total * 100:.1f}%" if total > 0 else "  通过率:   N/A")
    print("-" * 60)

    # 列出失败的测试
    if failed > 0 or error > 0:
        print("\n  FAILED / ERROR tests:")
        for t in results["tests"]:
            if t.get("outcome") in ("failed", "error"):
                print(f"    [{t['outcome'].upper()}] {t['nodeid']}")
                if t.get("message"):
                    print(f"           {t['message'][:150]}")

    print("=" * 60)


# ── 主入口 ──

def main():
    parser = argparse.ArgumentParser(
        description="Claw Test Runner - 自动化测试运行器",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--unit", action="store_true", help="仅运行单元测试")
    parser.add_argument("--integration", action="store_true", help="仅运行集成测试")
    parser.add_argument("--verbose", "-v", action="store_true", help="详细输出")
    parser.add_argument("-k", "--keyword", type=str, help="按关键词过滤测试")
    parser.add_argument("--no-report", action="store_true", help="不生成报告文件")
    parser.add_argument("--report-dir", type=str, default="reports", help="报告输出目录")
    args = parser.parse_args()

    # 构建 pytest 参数
    pytest_args = ["tests/"]

    if args.unit:
        pytest_args = ["tests/", "-m", "unit"]
    elif args.integration:
        pytest_args = ["tests/", "-m", "integration"]

    if args.verbose:
        pytest_args.extend(["-v", "-s", "--tb=short"])
    else:
        pytest_args.extend(["-q", "--tb=line"])

    if args.keyword:
        pytest_args.extend(["-k", args.keyword])

    # 报告目录
    report_dir = PROJECT_ROOT / args.report_dir
    report_dir.mkdir(parents=True, exist_ok=True)

    print(f"\n  运行 Claw 测试套件...")
    print(f"  命令: pytest {' '.join(pytest_args)}")
    print()

    # 运行测试
    start_time = time.time()

    try:
        from io import StringIO
        # 使用 pytest.main 运行
        exit_code = pytest.main(pytest_args)
    except SystemExit as e:
        exit_code = e.code if e.code is not None else 1

    duration = time.time() - start_time

    # 收集结果
    results = {
        "total": 0,
        "passed": 0,
        "failed": 0,
        "error": 0,
        "skipped": 0,
        "xfailed": 0,
        "xpassed": 0,
        "tests": [],
    }

    # 从 pytest 的 exit code 推断 (pytest 没有直接的 API 获取结果统计)
    # 运行第二次用 --collect-only + 终端输出模式取结果
    # 为了可读性, 我们再跑一次轻度收集

    try:
        # 再跑一次来收集详细统计 (-q --tb=no 输出最少)
        import subprocess
        test_dir = str(PROJECT_ROOT / "tests")
        cmd = [sys.executable, "-m", "pytest", test_dir, "-q", "--tb=no",
               "--no-header", "--no-summary"]

        if args.unit:
            cmd.extend(["-m", "unit"])
        elif args.integration:
            cmd.extend(["-m", "integration"])
        if args.keyword:
            cmd.extend(["-k", args.keyword])

        result = subprocess.run(cmd, capture_output=True, text=True, cwd=str(PROJECT_ROOT))
        output = result.stdout + result.stderr

        # 解析标准输出中类似 "18 passed, 2 failed, 1 warning" 的行
        import re
        match_passed = re.search(r'(\d+)\s+passed', output)
        match_failed = re.search(r'(\d+)\s+failed', output)
        match_error = re.search(r'(\d+)\s+error', output)
        match_skipped = re.search(r'(\d+)\s+skipped', output)
        match_xfailed = re.search(r'(\d+)\s+xfailed', output)
        match_xpassed = re.search(r'(\d+)\s+xpassed', output)

        results["passed"] = int(match_passed.group(1)) if match_passed else 0
        results["failed"] = int(match_failed.group(1)) if match_failed else 0
        results["error"] = int(match_error.group(1)) if match_error else 0
        results["skipped"] = int(match_skipped.group(1)) if match_skipped else 0
        results["xfailed"] = int(match_xfailed.group(1)) if match_xfailed else 0
        results["xpassed"] = int(match_xpassed.group(1)) if match_xpassed else 0
        results["total"] = (results["passed"] + results["failed"] +
                            results["error"] + results["skipped"] +
                            results["xfailed"] + results["xpassed"])
    except Exception as parse_err:
        print(f"  [WARN] Failed to parse detailed stats: {parse_err}")
        results["total"] = 1
        results["passed"] = 1 if exit_code == 0 else 0
        results["failed"] = 1 if exit_code != 0 else 0

    # 打印控制台摘要
    print_console_summary(results, duration)

    # 生成报告
    if not args.no_report:
        html_path = report_dir / "test_report.html"
        json_path = report_dir / "test_report.json"

        try:
            generate_html_report(results, html_path, duration)
            print(f"\n  HTML 报告: {html_path}")
        except Exception as e:
            print(f"  [WARN] HTML 报告生成失败: {e}")

        try:
            generate_json_report(results, json_path, duration)
            print(f"  JSON 报告: {json_path}")
        except Exception as e:
            print(f"  [WARN] JSON 报告生成失败: {e}")

    print()
    return 0 if exit_code == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
