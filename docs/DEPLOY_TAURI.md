# 错题本（CuoTi）— Tauri 桌面端部署操作手册

> 适用版本：v0.1.0（Rust 后端切换到多模态 LLM 识别）
> 技术栈：**Tauri 2 + Rust + Vue 3 + Vite + SQLite**

本手册覆盖 Tauri 桌面端从**环境准备 → 开发运行 → 构建打包 → LLM 配置 → 数据管理 → 常见问题**的完整部署流程。

---

## 一、目录结构

```
tauri/
├── Cargo.toml            # Rust workspace（core + src-tauri）
├── core/                 # 独立核心库（数据层 + 识别 + RAG），不依赖 Tauri
│   ├── src/
│   │   ├── cleaner.rs    # LLM 清洗 / 多模态图片识别 / RAG 问答
│   │   ├── commands/     # question / ocr / rag / config / stats 等命令
│   │   ├── db.rs        # SQLite 初始化
│   │   └── models.rs
│   └── tests/           # 单元/集成测试；llm_e2e.rs 需真实 API Key
├── frontend/             # Vue 3 + TypeScript + Vite + Tailwind
└── src-tauri/            # Tauri 二进制 crate
    ├── tauri.conf.json   # 应用标识、窗口、产物配置
    ├── capabilities/     # 权限声明
    └── src/main.rs       # 命令注册入口
```

---

## 二、环境要求

| 组件 | 最低版本 | 说明 |
|------|----------|------|
| Rust | 1.77+ | 使用 rustup 安装 |
| Node.js | 18+ | 构建前端 |
| Tauri CLI | 2.x | `cargo install tauri-cli --version ^2` |
| SQLite | 内置 | 经 SQLx 编译进程序，无需单独安装 |

### 各平台系统依赖

**Windows（Win10+）**
- **winget**：Win10/11 自带，用于安装 Rust/Node
- **MSVC Build Tools**：提供 C++ 链接器（`x86_64-pc-windows-msvc` toolchain 需要），安装 `Microsoft.VisualStudio.2022.BuildTools` 时勾选「使用 C++ 的桌面开发」工作负载
- **WebView2 Runtime**：Win10/11 自带；Win7/旧系统需手动装

**macOS**
- Xcode Command Line Tools：`xcode-select --install`

**Linux（Debian/Ubuntu）**
```bash
sudo apt update
sudo apt install -y \
  libwebkit2gtk-4.1-dev \
  build-essential curl wget file \
  libxdo-dev \
  libssl-dev \
  libayatana-appindicator3-dev \
  librsvg2-dev
```

---

## 三、依赖安装

### Windows（PowerShell）专属步骤

> 以下命令在 **PowerShell** 中执行。Windows 下**不要**使用下面的 `curl | sh` 那条 Unix 命令。

```powershell
# 1. 安装 Rust（rustup）与 Node.js LTS
winget install Rustlang.Rustup
winget install OpenJS.NodeJS.LTS

# 2. 重新打开 PowerShell，验证安装
rustc --version
cargo --version
node --version
npm --version

# 3. 若 rustc 报缺 MSVC 链接器，安装 VS Build Tools（含 C++ 桌面开发）
winget install Microsoft.VisualStudio.2022.BuildTools

# 4. 进入项目安装前端依赖（路径换成你的实际项目位置）
cd tauri/frontend
npm install
cd ..

# 5. 安装 Tauri CLI
cargo install tauri-cli --version "^2" --locked
```

### Linux / macOS（bash）

```bash
# 1. Rust 工具链（如未安装）
curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh

# 2. Tauri CLI
cargo install tauri-cli --version "^2" --locked

# 3. 前端依赖
cd tauri/frontend
npm install
```

> 首次 `cargo build` 会拉取并编译较多依赖，耗时较长属正常。

---

## 四、开发模式运行

```bash
cd tauri
cargo tauri dev
```

- 会先启动 Vite dev server（端口 1420），再弹出桌面窗口。
- 前端改动热更新；Rust 改动需重新编译。
- 纯浏览器预览（无 Tauri runtime）：`cd frontend && npm run dev`，但**数据/识别/RAG 等依赖 IPC 的功能不可用**，仅用于调试 UI。

### 常用开发命令

```bash
# Rust 核心库测试（无需系统依赖，沙箱/CI 均可用）
cargo test -p cuoti-core

# 前端类型检查
cd frontend && npx tsc --noEmit

# 前端单元测试
cd frontend && npx vitest run

# 多模态识别端到端验证（需真实 API Key）
BIGMODEL_API_KEY=<你的Key> cargo test -p cuoti-core --test llm_e2e clean_image -- --ignored --nocapture
```

---

## 五、构建打包（发布）

### 1. 构建前端产物

```bash
cd tauri/frontend
npm run build          # 输出到 frontend/dist
```

### 2. 打包桌面应用

```bash
cd tauri
cargo tauri build
```

- 自动执行 release 构建（启用 `strip` + `LTO` + `codegen-units=1`，见 [Cargo.toml](file:///workspace/tauri/Cargo.toml)）。
- 生成物位于 `src-tauri/target/release/bundle/`：

| 平台 | 产物 |
|------|------|
| Windows | `.msi` / `.exe`（NSIS 安装包） |
| macOS | `.dmg` / `.app` |
| Linux | `.deb` / `.rpm` / `.AppImage` |

### 3. 交叉编译注意事项

- **Windows**：仅能在 Windows 或带 MSVC 交叉环境的机器上打 `.msi`/`.exe`。
- **macOS**：仅能在 macOS 上打 `.dmg`（受签名与平台限制）。
- **Linux**：可在 CI（GitHub Actions）中为多发行版构建 `.deb`/`.AppImage`。

### 4. 分发方式

无自动更新（未配置 updater 插件），建议：
- 将安装包上传到内网共享 / 网盘 / GitHub Releases。
- 升级时卸载旧版或直接覆盖安装，数据保留在应用数据目录（见第七节）。

---

## 六、LLM 多模态配置（AI 识别）

> 自 v0.1.0 起，识别由「PaddleOCR + LLM 清洗」切换为**直接调用多模态大模型**（智谱 `glm-4.5-air`），一次调用输出结构化错题 JSON。

### 1. 获取智谱 API Key

1. 访问 <https://open.bigmodel.cn/> 注册并登录。
2. 进入「API Keys」创建密钥，形如 `xxxxxxxx.yyyyyyyyy`。
3. Base URL：`https://open.bigmodel.cn/api/paas/v4`
4. 模型：`glm-4.5-air`（多模态，支持文字+图片输入）

### 2. 在「设置」页配置

打开应用 → **设置 → AI 识别（多模态 LLM）**：

| 字段 | 填写 |
|------|------|
| 启用 | ☑ 勾选 |
| Base URL | `https://open.bigmodel.cn/api/paas/v4` |
| API Key | 你的智谱密钥 |
| 模型 | `glm-4.5-air` |

点击「保存设置」。

### 3. 使用 AI 识别

- 新增/编辑错题页 → 点击 **「✨ AI 识别」** → 选择图片 → 自动识别并填充表单。
- 图片限制：**≤ 10MB**；支持 jpg / jpeg / png / webp / gif / bmp（按文件头识别，不依赖扩展名）。
- 识别失败时前端会弹出具体错误提示。

### 4. 配置存储与安全

- 配置保存在 SQLite `config` 表（`llm_base_url` / `llm_api_key` / `llm_model` / `llm_enabled`）。
- API Key 返回前端时以 `********` 掩码，避免明文泄露。
- 相关 JSON 字段（LLM 返回）：`qtype/single|multiple|judge|fill|answer`、`title`、`options[]`、`answer`、`analysis`、`difficulty(1-5)`、`subject`、`chapter`、`tags[]`。

---

## 七、数据存储与备份

### 数据目录

应用标识为 `com.cuoti.app`，数据位于各平台的应用数据目录：

| 平台 | 路径 |
|------|------|
| Windows | `%APPDATA%\com.cuoti.app\`（即 `C:\Users\<用户>\AppData\Roaming\com.cuoti.app\`） |
| macOS | `~/Library/Application Support/com.cuoti.app/` |
| Linux | `~/.local/share/com.cuoti.app/` |

目录内容：
- `errors.db`：SQLite 主数据库（错题、科目、知识点、标签、配置）
- `images/`：持久化的错题图片

### 迁移 / 备份

- 备份 = 复制整个应用数据目录，或使用应用内「导出/导入」功能（`export_all` / `import_all`，生成 JSON）。
- 升级前建议先导出备份。

---

## 八、常见问题（FAQ）

**Q1：`cargo tauri dev` 报系统库缺失？**
定位到对应平台系统依赖，参见第二节。Linux 常见缺 `libwebkit2gtk-4.1-dev`。

**Q2：纯浏览器打开 `npm run dev` 报 `invoke is undefined`？**
正常。浏览器无 Tauri IPC runtime，仅 UI 可用。真实功能需 `cargo tauri dev` 桌面运行。

**Q3：AI 识别无反应 / 静默失败？**
- 确认「设置 → AI 识别」已勾选「启用」并保存。
- 确认 API Key / Base URL / 模型正确，且账号有余额或配额。
- 图片 ≤ 10MB。
- 查看应用日志定位 HTTP 错误码。

**Q4：识别结果字段乱 / 题型不对？**
模型返回的 `qtype` 会做白名单归一化（`single/multiple/judge/fill/answer`），非约定值会被忽略置空，可手动补充。

**Q5：打包一直在编译很慢？**
首次 release 构建需编译全部依赖 + 启用 LTO，耗时较长。后续增量构建会快很多。

**Q6：如何彻底卸载？**
删除安装的程序 + 删除对应平台的应用数据目录（见第七节）。

---

## 九、验证清单

- [ ] `cargo test -p cuoti-core` 全绿
- [ ] `cd frontend && npx tsc --noEmit` 无错误
- [ ] `cargo tauri dev` 桌面窗口正常启动
- [ ] 设置页可保存 LLM 配置
- [ ] 用真实图片调用「✨ AI 识别」能填充表单
- [ ] `cargo tauri build` 产出对应平台安装包
- [ ] 导出备份 JSON 成功