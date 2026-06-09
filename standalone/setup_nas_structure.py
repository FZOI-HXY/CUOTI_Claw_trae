"""
NAS 标准变更记录目录结构部署脚本
===================================

在 NAS ( \\192.168.0.79\\maker ) 根目录下建立标准化的项目变更记录文件夹结构。

命名规范:
  - 日期格式: YYYY-MM-DD 或 YYYYMMDD （ISO 8601 兼容）
  - 版本号:   v<MAJOR>.<MINOR>.<PATCH> （语义化版本）
  - 序号补丁: NNN （三位零填充，如 001）
  - 分类前缀: 01_ 02_ ... （确保排序稳定）

目录树概览:
  maker/
  ├── README.txt                         # 根目录说明
  └── CLAW_CHANGE_RECORDS/               # 项目专属变更记录区
      ├── INDEX.md                       # 全局索引与检索指南
      │
      ├── 01_changelogs/                 # 变更日志（按日期归档）
      │   └── YYYY-MM/
      │       └── CHANGELOG_YYYY-MM-DD.md
      │
      ├── 02_releases/                   # 版本发布记录
      │   └── v<MAJOR>.<MINOR>.<PATCH>/
      │       ├── release_notes.md
      │       ├── artifacts/             # 发布产物
      │       └── checksums.md5
      │
      ├── 03_snapshots/                  # 代码/数据快照
      │   └── YYYY-MM-DD_vX.X.X/
      │       ├── snapshot_manifest.json
      │       └── files/
      │
      ├── 04_configs_backup/             # 配置文件备份
      │   └── config_backup_YYYYMMDD_HHMMSS/
      │       └── *.json
      │
      ├── 05_patches/                    # 补丁与热修复
      │   └── YYYY-MM/
      │       └── patch_YYYYMMDD_NNN_<brief>/
      │           ├── patch_info.json
      │           ├── files/
      │           └── rollback/
      │
      ├── 06_database/                   # 数据库变更与迁移
      │   └── YYYY-MM/
      │       └── migration_YYYYMMDD_NNN.sql
      │
      ├── 07_logs/                       # 运行日志归档
      │   └── YYYY-MM/
      │       └── app_log_YYYY-MM-DD.log
      │
      ├── 08_shared_data/               # 跨网段共享数据（原 claw_sync）
      │   ├── reports/
      │   ├── history/
      │   └── shared_config.json
      │
      └── templates/                    # 记录模板
          ├── CHANGELOG_TEMPLATE.md
          ├── RELEASE_NOTES_TEMPLATE.md
          └── PATCH_TEMPLATE.md

用法:
  python setup_nas_structure.py              # 仅打印计划（干运行）
  python setup_nas_structure.py --execute    # 实际创建目录结构
  python setup_nas_structure.py --verify     # 验证现有结构完整性
"""

import os
import json
import argparse
from pathlib import Path
from datetime import datetime
from typing import Dict, List, Tuple

# ============================================================
#  配置
# ============================================================

NAS_HOST = "192.168.0.79"
NAS_SHARE = "maker"
NAS_USER = "maker"
NAS_PASS = "maker"

# 项目根目录在 NAS 上的名称
PROJECT_ROOT = "CLAW_CHANGE_RECORDS"

# 各版本初始示例内容
TEMPLATES = {
    "INDEX.md": """# CLAW 项目变更记录索引

> NAS 地址: \\\\{host}\\{share}\\
> 项目根: {project_root}
> 最后更新: {date}

---

## 目录结构速查

| 目录 | 用途 | 访问模式 |
|------|------|----------|
| `01_changelogs/` | 变更日志（按日/月） | 按日期检索 |
| `02_releases/` | 版本发布记录与制品 | 按版本号检索 |
| `03_snapshots/` | 系统/数据快照 | 按日期+版本 |
| `04_configs_backup/` | 配置文件备份 | 按时间戳 |
| `05_patches/` | 补丁/热修复记录 | 按日期+序号 |
| `06_database/` | 数据库迁移脚本 | 按日期+序号 |
| `07_logs/` | 运行日志归档 | 按日期 |
| `08_shared_data/` | 跨网段共享数据 | 自动同步 |
| `templates/` | 记录模板 | 只读参考 |

---

## 文件命名规范

| 类型 | 格式 | 示例 |
|------|------|------|
| 变更日志 | `CHANGELOG_YYYY-MM-DD.md` | `CHANGELOG_2026-06-09.md` |
| 发布说明 | `release_notes.md` | 位于版本目录内 |
| 快照清单 | `snapshot_manifest.json` | 位于快照目录内 |
| 配置备份 | `config_backup_YYYYMMDD_HHMMSS/*.json` | `config_backup_20260609_133000/` |
| 补丁信息 | `patch_YYYYMMDD_NNN_<简述>/` | `patch_20260609_001_auth_fix/` |
| 迁移脚本 | `migration_YYYYMMDD_NNN.sql` | `migration_20260609_001.sql` |
| 日志归档 | `app_log_YYYY-MM-DD.log` | `app_log_2026-06-09.log` |
| 共享报告 | `reports/<report_id>/` | `reports/report_20260609_001/` |

## 版本号规范

- 格式: `v<MAJOR>.<MINOR>.<PATCH>`
- MAJOR: 不兼容的大改动
- MINOR: 向下兼容的新功能
- PATCH: 向下兼容的缺陷修复

---

*本索引由 setup_nas_structure.py 自动生成*
""",

    "CHANGELOG_TEMPLATE.md": """# 变更日志 - {date}

## 版本信息
- **版本号**: vX.X.X
- **发布日期**: {date}
- **变更人**: （填写）

---

## 新增功能 (Added)

- [ ] 

## 变更 (Changed)

- [ ] 

## 废弃 (Deprecated)

- [ ] 

## 移除 (Removed)

- [ ] 

## 修复 (Fixed)

- [ ] 

## 安全 (Security)

- [ ] 

---

## 影响范围

| 模块 | 影响程度 | 说明 |
|------|----------|------|
|      |          |      |

## 测试要点

1. 
2. 

---

*模板遵循 [Keep a Changelog](https://keepachangelog.com/) 格式*
""",

    "RELEASE_NOTES_TEMPLATE.md": """# 发布说明 - v{VERSION}

**发布日期**: {date}
**发布类型**: [正式版 / 预览版 / 热修复]

---

## 版本概述

（简要描述此版本的变更内容）

## 新增功能

1. 
2. 

## 已知问题

1. 
2. 

## 升级指南

### 从上一版本升级

1. 停止运行中的实例
2. 备份当前配置: `04_configs_backup/`
3. 应用变更
4. 重启实例

### 回滚步骤

1. 恢复备份的配置
2. 还原对应版本的快照

## 制品校验

| 文件名 | MD5 |
|--------|-----|
|        |     |

---

*制品位于 `artifacts/` 目录*
""",

    "PATCH_TEMPLATE.md": """# 补丁信息 - {patch_id}

**补丁ID**: {patch_id}
**适用版本**: vX.X.X
**创建日期**: {date}
**紧急程度**: [ 低 / 中 / 高 / 紧急 ]

---

## 问题描述

（描述本补丁修复的问题）

## 变更文件清单

| 文件路径 | 变更类型 | 说明 |
|----------|----------|------|
|          |          |      |

## 应用方式

```
# 1. 将 files/ 中的内容覆盖到对应位置
# 2. 执行验证
```

## 回滚方式

```
# 使用 rollback/ 中的原始文件覆盖
```

## 验证步骤

1. 
2. 

---

*补丁文件位于 `files/`，回滚文件位于 `rollback/`*
""",
}


# ============================================================
#  目录结构定义 (路径, 说明, 是否创建示例文件?)
# ============================================================

DIRECTORY_STRUCTURE: List[Tuple[str, str, bool]] = [
    # (相对于 PROJECT_ROOT 的路径, 说明, 是否创建示例/README)
    ("01_changelogs", "变更日志（每日 changelog）", False),
    ("01_changelogs/2026-06", "2026年6月变更日志", False),
    ("02_releases", "版本发布记录与制品", False),
    ("02_releases/v1.0.0/artifacts", "v1.0.0 发布制品", False),
    ("03_snapshots", "代码与数据快照存档", False),
    ("04_configs_backup", "配置文件时间点备份", False),
    ("05_patches", "补丁与热修复记录", False),
    ("06_database", "数据库变更与迁移脚本", False),
    ("07_logs", "应用运行日志归档", False),
    ("07_logs/2026-06", "2026年6月日志档案", False),
    ("08_shared_data/reports", "跨网段共享：报告数据", False),
    ("08_shared_data/history", "跨网段共享：处理历史", False),
    ("templates", "记录模板文件", False),
]

# 需要创建的示例/模板文件
EXAMPLE_FILES: List[Tuple[str, str, str]] = [
    # (路径, 文件名, 内容键)
    ("", "INDEX.md", "INDEX.md"),
    ("templates", "CHANGELOG_TEMPLATE.md", "CHANGELOG_TEMPLATE.md"),
    ("templates", "RELEASE_NOTES_TEMPLATE.md", "RELEASE_NOTES_TEMPLATE.md"),
    ("templates", "PATCH_TEMPLATE.md", "PATCH_TEMPLATE.md"),
    ("08_shared_data", "shared_config.json", None),  # 单独处理
]


def get_root_unc() -> str:
    """返回 NAS 根 UNC 路径"""
    return f"\\\\{NAS_HOST}\\{NAS_SHARE}"


def get_project_root_unc() -> str:
    """返回项目变更记录在 NAS 上的完整 UNC 路径"""
    return os.path.join(get_root_unc(), PROJECT_ROOT)


def format_path_for_display(rel_path: str) -> str:
    """将相对路径格式化为可读的树形显示"""
    depth = rel_path.count("/") + rel_path.count("\\")
    indent = "    " * depth + ("├── " if rel_path else "")
    leaf = os.path.basename(rel_path) if rel_path else PROJECT_ROOT
    return f"{indent}{leaf}"


def build_template_content(template_key: str) -> str:
    """根据模板键填充实际内容"""
    now = datetime.now()
    date_str = now.strftime("%Y-%m-%d")
    iso_str = now.isoformat()

    replacements = {
        "date": date_str,
        "host": NAS_HOST,
        "share": NAS_SHARE,
        "project_root": PROJECT_ROOT,
        "{VERSION}": "1.0.0",
        "patch_id": f"patch_{now.strftime('%Y%m%d')}_001_example",
    }

    content = TEMPLATES[template_key]
    for key, val in replacements.items():
        content = content.replace("{" + key + "}", val)
        content = content.replace(key, val)  # fallback for {} wrapped ones

    # 最后补一遍 {} 包裹的
    content = content.replace("{date}", date_str)
    content = content.replace("{ DATE }", date_str)
    content = content.replace("{VERSION}", "1.0.0")

    return content


def build_shared_config() -> str:
    """生成初始 shared_config.json"""
    cfg = {
        "project": "CLAW",
        "description": "错题管理系统跨网段共享配置",
        "created_at": datetime.now().isoformat(),
        "updated_at": datetime.now().isoformat(),
        "nas_host": NAS_HOST,
        "nas_share": NAS_SHARE,
        "sync_root": f"{PROJECT_ROOT}/08_shared_data",
        "settings": {
            "auto_sync": True,
            "sync_interval_minutes": 5,
            "max_file_size_mb": 100,
            "retention_days": 90,
        },
    }
    return json.dumps(cfg, ensure_ascii=False, indent=2)


# ============================================================
#  核心操作
# ============================================================


def test_nas_connection() -> bool:
    """测试 NAS 连通性"""
    unc = get_root_unc()
    print(f"[测试] 检查 NAS 连通性: {unc}")

    # 方式1: Path.exists()
    try:
        if Path(unc).exists():
            print(f"  [OK] UNC 路径可访问: {unc}")
            return True
    except (OSError, PermissionError):
        pass

    # 方式2: os.listdir
    try:
        items = os.listdir(unc)
        print(f"  [OK] 可列出目录内容 ({len(items)} 项): {unc}")
        return True
    except (FileNotFoundError, NotADirectoryError):
        print(f"  [OK] UNC 可访问但根目录为空")
        return True
    except (OSError, PermissionError) as e:
        print(f"  [FAIL] 权限不足: {e}")
        return False

    # 方式3: 尝试 SMB 认证
    import subprocess
    try:
        cmd = [
            "net", "use", unc,
            f"/user:{NAS_USER}", NAS_PASS,
            "/persistent:no",
        ]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        combined = (result.stdout or "") + (result.stderr or "")
        if result.returncode == 0 or "已连接" in combined or "already" in combined.lower():
            print(f"  [OK] SMB 认证成功: {unc}")
            return True
        print(f"  [FAIL] SMB 认证失败: {combined[:200]}")
        return False
    except Exception as e:
        print(f"  [FAIL] 连接异常: {e}")
        return False


def get_existing_structure(root_unc: str) -> set:
    """获取 NAS 上已存在的目录/文件集合"""
    existing = set()
    try:
        for item in os.listdir(root_unc):
            existing.add(item)
    except Exception:
        pass
    return existing


def create_directory_structure(root_unc: str, dry_run: bool = True) -> Dict[str, bool]:
    """
    创建目录结构
    返回 {路径: 是否新建}
    """
    results = {}

    # 1. 创建项目根目录
    project_root = os.path.join(root_unc, PROJECT_ROOT)
    if dry_run:
        print(f"[计划] 创建项目根目录: {project_root}")
        results[PROJECT_ROOT] = not Path(project_root).exists() if _path_safe(project_root) else True
    else:
        created = _mkdir(project_root)
        results[PROJECT_ROOT] = created
        if created:
            print(f"  [OK] 创建: {project_root}")
        else:
            print(f"  [SKIP] 已存在: {project_root}")

    # 2. 创建子目录结构
    for rel_path, description, _ in DIRECTORY_STRUCTURE:
        full_path = os.path.join(root_unc, PROJECT_ROOT, rel_path.replace("/", os.sep))
        target_components = rel_path.replace("/", os.sep).split(os.sep)

        if dry_run:
            display = format_path_for_display(rel_path)
            print(f"[计划] {display}  ({description})")
            results[rel_path] = True
        else:
            created = _mkdir(full_path)
            results[rel_path] = created
            if created:
                print(f"  [OK] 创建: {rel_path}  ({description})")
            else:
                print(f"  [SKIP] 已存在: {rel_path}")

    # 3. 创建模板/示例文件
    for rel_dir, filename, template_key in EXAMPLE_FILES:
        dir_path = os.path.join(root_unc, PROJECT_ROOT, rel_dir.replace("/", os.sep))
        file_path = os.path.join(dir_path, filename)

        # 确定内容
        if template_key:
            content = build_template_content(template_key)
        else:
            content = build_shared_config()

        if dry_run:
            print(f"[计划] 创建文件: {os.path.join(rel_dir, filename)}")
            results[f"{rel_dir}/{filename}"] = True
        else:
            if _path_safe(file_path) and Path(file_path).exists():
                print(f"  [SKIP] 已存在: {os.path.join(rel_dir, filename)} （跳过）")
                results[f"{rel_dir}/{filename}"] = False
            else:
                try:
                    Path(dir_path).mkdir(parents=True, exist_ok=True)
                    Path(file_path).write_text(content, encoding="utf-8")
                    print(f"  [OK] 创建文件: {os.path.join(rel_dir, filename)}")
                    results[f"{rel_dir}/{filename}"] = True
                except Exception as e:
                    print(f"  [FAIL] 创建失败: {os.path.join(rel_dir, filename)}: {e}")
                    results[f"{rel_dir}/{filename}"] = False

    return results


def _path_safe(path: str) -> bool:
    """安全检测路径是否可以访问（不抛异常）"""
    try:
        Path(path).exists()
        return True
    except (OSError, PermissionError, ValueError):
        return False


def _mkdir(path: str) -> bool:
    """创建目录，返回 True 表示新建，False 表示已存在"""
    try:
        p = Path(path)
        if p.exists():
            return False
        p.mkdir(parents=True, exist_ok=True)
        return True
    except FileExistsError:
        return False
    except Exception as e:
        print(f"  [FAIL] 创建失败: {path}: {e}")
        return False


def verify_structure(root_unc: str) -> Tuple[int, int]:
    """验证目录结构完整性，返回 (存在数, 缺失数)"""
    project_root = os.path.join(root_unc, PROJECT_ROOT)
    missing = []
    present = []

    # 检查项目根目录
    if not _path_safe(project_root):
        missing.append(PROJECT_ROOT)
    else:
        present.append(PROJECT_ROOT)

    # 检查子目录
    for rel_path, description, _ in DIRECTORY_STRUCTURE:
        full_path = os.path.join(root_unc, PROJECT_ROOT, rel_path.replace("/", os.sep))
        if _path_safe(full_path) and Path(full_path).is_dir():
            present.append(rel_path)
        else:
            missing.append(rel_path)

    # 检查文件
    for rel_dir, filename, _ in EXAMPLE_FILES:
        file_path = os.path.join(root_unc, PROJECT_ROOT, rel_dir.replace("/", os.sep), filename)
        if _path_safe(file_path) and Path(file_path).is_file():
            present.append(f"{rel_dir}/{filename}")
        else:
            missing.append(f"{rel_dir}/{filename}")

    if missing:
        print("\n[WARN] 缺失的目录/文件:")
        for m in missing:
            print(f"  - {m}")
    else:
        print("\n[OK] 所有目录和文件均完整")

    if present:
        print(f"\n已存在的项目: {len(present)}")

    return len(present), len(missing)


def print_tree(prefix: str = "", rel_path: str = "") -> str:
    """打印可视化的目录树"""
    lines = []

    root = PROJECT_ROOT if not rel_path else os.path.basename(rel_path)
    is_root = not rel_path

    if is_root:
        lines.append(f"{PROJECT_ROOT}/")
    else:
        lines.append(f"{prefix}├── {root}/")

    # 找到直接子项
    children = []
    for dir_path, desc, _ in DIRECTORY_STRUCTURE:
        dir_path = dir_path.replace("/", os.sep)
        if os.path.dirname(dir_path) == rel_path:
            children.append(("d", os.path.basename(dir_path), desc))
    for rdir, fname, _ in EXAMPLE_FILES:
        parent = rdir.replace("/", os.sep)
        if parent == rel_path:
            children.append(("f", fname, ""))

    for i, (c_type, c_name, c_desc) in enumerate(children):
        is_last = i == len(children) - 1
        connector = "└── " if is_last else "├── "
        icon = "[FILE] " if c_type == "f" else "[DIR] "
        desc_str = f"  -- {c_desc}" if c_desc else ""
        indent = "    " if is_root else prefix + "    "
        lines.append(f"{indent}{connector}{icon}{c_name}{desc_str}")

    return "\n".join(lines)


# ============================================================
#  CLI 入口
# ============================================================


def main():
    global NAS_HOST, NAS_SHARE, NAS_USER, NAS_PASS, PROJECT_ROOT

    parser = argparse.ArgumentParser(
        description="在 SMB NAS 上创建标准化的项目变更记录目录结构",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=f"""
示例:
  python setup_nas_structure.py                  # 干运行，预览计划
  python setup_nas_structure.py --execute        # 在 NAS 上实际创建
  python setup_nas_structure.py --verify         # 验证现有结构
  python setup_nas_structure.py --host 192.168.1.100  # 指定其他 NAS

NAS 地址: \\\\{NAS_HOST}\\{NAS_SHARE}
凭据: {NAS_USER} / ***
        """
    )
    parser.add_argument("--execute", action="store_true", help="实际执行创建操作（默认仅预览）")
    parser.add_argument("--verify", action="store_true", help="验证现有结构完整性")
    parser.add_argument("--host", default=NAS_HOST, help=f"NAS IP 地址 (默认: {NAS_HOST})")
    parser.add_argument("--share", default=NAS_SHARE, help=f"SMB 共享名 (默认: {NAS_SHARE})")
    parser.add_argument("--user", default=NAS_USER, help=f"SMB 用户名 (默认: {NAS_USER})")
    parser.add_argument("--password", default=NAS_PASS, help="SMB 密码")
    parser.add_argument("--project-root", default=PROJECT_ROOT,
                        help=f"项目根目录名 (默认: {PROJECT_ROOT})")
    args = parser.parse_args()

    # 使用参数覆盖全局配置
    NAS_HOST = args.host
    NAS_SHARE = args.share
    NAS_USER = args.user
    NAS_PASS = args.password
    PROJECT_ROOT = args.project_root

    root_unc = get_root_unc()
    project_root_unc = get_project_root_unc()

    print("=" * 70)
    print("  NAS 变更记录目录结构管理工具")
    print("=" * 70)
    print(f"  NAS UNC:     {root_unc}")
    print(f"  项目根目录:  {project_root_unc}")
    print(f"  模式:        {'验证' if args.verify else '执行' if args.execute else '预览（干运行）'}")
    print("-" * 70)

    if args.verify:
        # -------- 验证模式 --------
        connected = test_nas_connection()
        if not connected:
            print("\n[FAIL] 无法连接到 NAS，请检查网络和凭据")
            return 1
        present, missing = verify_structure(root_unc)
        if missing > 0:
            return 1
        return 0

    # -------- 预览或执行 --------
    print("\n[PREVIEW] 目录结构预览:\n")
    print(print_tree())
    print()

    if not args.execute:
        print("\n[TIP] 这是干运行模式，未执行任何实际操作。")
        print("   使用 --execute 参数实际创建目录结构。")
        print("   使用 --verify  参数验证已有结构。")
        return 0

    # -------- 执行模式 --------
    # 1. 先测试连接
    connected = test_nas_connection()
    if not connected:
        print("\n" + "=" * 70)
        print("[WARN] 无法连接到 NAS，将尝试进行 SMB 认证...")
        print("=" * 70)
        import subprocess
        try:
            cmd = [
                "net", "use", root_unc,
                f"/user:{NAS_USER}", NAS_PASS,
                "/persistent:no",
            ]
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
            if result.returncode != 0:
                print(f"\n[FAIL] SMB 认证失败，无法继续。")
                print(f"  错误: {(result.stderr or result.stdout)[:300]}")
                return 1
            print("  [OK] SMB 认证成功")
        except Exception as e:
            print(f"\n[FAIL] SMB 认证异常: {e}")
            return 1

    # 2. 创建目录结构
    print(f"\n[EXEC] 正在创建目录结构...\n")
    results = create_directory_structure(root_unc, dry_run=False)

    # 3. 统计
    new_dirs = sum(1 for k, v in results.items() if v and "/" not in k)
    new_files = sum(1 for k, v in results.items() if v and "/" in k)
    existing = sum(1 for v in results.values() if not v)

    print(f"\n[STATS] 统计:")
    print(f"  新建目录: {new_dirs - new_files}")
    print(f"  新建文件: {new_files}")
    print(f"  已存在:   {existing}")
    print(f"  共计:     {len(results)}")

    # 4. 验证
    print(f"\n[VERIFY] 验证结构完整性...")
    present, missing = verify_structure(root_unc)

    if missing == 0:
        print(f"\n[PASS] 目录结构创建完成，所有项目验证通过！")
        print(f"   访问: {project_root_unc}")
    else:
        print(f"\n[WARN] 有 {missing} 个项目缺失，请检查 NAS 权限和网络。")

    return 0 if missing == 0 else 1


if __name__ == "__main__":
    exit(main())
