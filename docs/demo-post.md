**标签：** 学习工作

**标题：** 【学习工作赛道】DocFlow —— AI智能文档识别与管理系统

---

## 一、Demo 简介

**是什么：** DocFlow 是一个 Web + 桌面双端的 AI 智能文档识别与管理系统。用户上传文档照片（错题/笔记/试卷/合同/票据），系统通过 PaddleOCR 多模态 AI 自动识别文字、公式、表格、图表、版面结构，生成结构化 Markdown 文档。

**面向谁：**
- 学生 —— 整理错题、笔记、试卷，AI 自动识别生成复习资料
- 办公族 —— 管理合同、票据、会议纪要，AI 提取关键信息
- 教师 —— 收集典型错题，快速生成错题集用于讲评

**核心功能：**

1. **AI 多模态识别** —— 集成 PaddleOCR-VL-1.6，支持文字 + 公式 + 表格 + 图表 + 版面结构一体化识别，自动生成结构化 Markdown

![上传识别界面](screenshot-1-upload.png)

2. **批量处理 + 历史管理** —— 最多支持 20 个文件批量上传，SQLite 持久化存储，按时间检索，支持 ZIP 打包导出

![历史记录管理](screenshot-2-history.png)

3. **Web + 桌面双端** —— Web 端在线使用（评委可直接体验），桌面端离线场景（已打包为 Claw.exe），共享同一后端

![桌面端应用](screenshot-3-desktop.png)

---

## 二、Demo 创作思路

**灵感来源：**

我是一名高中生，每天课后都要整理错题和笔记。一道含公式和图表的错题，手工抄写 + 排版至少 5-10 分钟，一晚上整理十几道题就要一两个小时。身边的同学都有同样的痛苦——拍照存了找不到，手工抄太慢，用普通 OCR 识别公式和表格全是乱码。

**想解决的问题：**

文档管理是学习和工作中最高频的刚需场景，但现有方案都有明显短板：

| 方案 | 问题 |
|------|------|
| 手工抄写 | 耗时 5-10 分钟/篇，公式图表无法还原 |
| 拍照存储 | 无法编辑、检索、分类，等于"电子囤积" |
| 普通 OCR | 公式/表格乱码，版面混乱，无法生成可编辑文档 |

**为什么做这个方向：**

随着 PaddleOCR 多模态 AI 技术成熟，终于可以实现"拍照即归档"——文字、公式、表格、图表一次性识别，自动生成结构化 Markdown。我将项目从"错题管理"扩展为通用"文档识别与管理"，覆盖学生（错题/笔记/试卷）和办公族（合同/票据/会议纪要）双场景，让 AI 真正服务于日常高频需求。

---

## 三、Demo 体验地址

**在线体验：** https://huxiaoyang.dpdns.org

> 打开后自动进入前端界面，点击"上传文件"选择文档照片（支持 JPG/PNG/BMP/WebP/TIFF/PDF），系统自动识别并生成 Markdown 报告。可在"处理记录"中查看历史，"报告中心"下载/预览报告。

**桌面端：** 已打包为 Claw.exe，见 GitHub 仓库 `apps/desktop/dist/`

**GitHub：** https://github.com/FZOI-HXY/CUOTI_Claw_trae

---

## 四、TRAE 实践过程

整个项目从创意到落地完全使用 TRAE IDE 开发完成。以下是关键开发阶段：

### 阶段 1：项目架构搭建

用 TRAE IDE 搭建了 FastAPI 后端 + 原生 Web 前端 + PyQt6 桌面端的三层架构。通过对话描述需求，TRAE 自动生成了项目骨架代码、API 路由、数据模型和前端界面。

![TRAE 开发截图 - 架构搭建](screenshot-4-trae-arch.png)

**Session ID：** `6a492d8d43262e88b5f91f9f`

> 在这个阶段，我让 TRAE 帮我生成了 FastAPI 的完整后端框架，包括 27 个 API 端点、Pydantic 数据模型、SQLite 数据库层（WAL 模式）和异步任务架构。

### 阶段 2：PaddleOCR API 集成

通过 TRAE 对话集成百度 PaddleOCR 多模态 API，实现了异步任务提交 → 轮询结果 → 自动提取 Markdown 和图片 → 生成报告的完整链路。TRAE 帮我处理了 httpx 异步请求、错误重试、结果解析等复杂逻辑。

![TRAE 开发截图 - OCR集成](screenshot-5-trae-ocr.png)

**Session ID：** `<从 TRAE 对话中复制 Session ID 填入此处>`

> 这个阶段最难的是 PaddleOCR 返回结果的解析——包含版面分析、表格识别、公式识别、图片提取等多层嵌套结构。TRAE 帮我写了解析器，把 JSON 结果转换为结构化 Markdown。

### 阶段 3：安全加固与生产部署

使用 TRAE 进行了全面的安全加固和部署配置：
- 修复了路径遍历、XSS、SSRF 等安全问题
- 添加了速率限制、文件名消毒、HTML 转义等防护
- 配置了 Docker 多阶段构建（Python 3.13）
- 通过 Cloudflare Tunnel 实现免费公网部署（无需服务器）

![TRAE 开发截图 - 安全加固](screenshot-6-trae-security.png)

**Session ID：** `<从 TRAE 对话中复制 Session ID 填入此处>`

> 安全加固是最考验细节的阶段。TRAE 帮我逐一排查了 30+ 个安全要点，从路径遍历防护到 SSRF 验证，每个修复都有对应的安全测试用例。

### 开发心得

1. **AI 降低了全栈开发门槛** —— 作为高中生，我之前只熟悉 Python 后端。TRAE 帮我完成了前端界面、Docker 部署、Cloudflare Tunnel 配置等我从未接触过的工作。

2. **迭代式开发很高效** —— 先让 AI 生成基础框架，再逐步添加安全加固、部署配置、模型升级。每个阶段都有明确的目标和验证。

3. **安全意识很重要** —— 从开发第一天就考虑安全，比上线后再补救高效得多。TRAE 在这个过程中充当了安全顾问的角色。

---

## 五、技术架构

**用户层：** Web 浏览器 / 桌面端 Claw.exe

**网关层：** Cloudflare Tunnel（HTTPS，huxiaoyang.dpdns.org → 本地 :8500）

**后端层：** FastAPI（Python 3.13）
- API 路由层（27 个端点）
- 任务服务（异步提交 + 轮询 + 结果提取）
- 数据层（SQLite WAL 模式）
- 安全中间件（速率限制、CORS、TrustedHost、认证）

**AI 层：** 百度 PaddleOCR 多模态 API（PaddleOCR-VL-1.6 / PP-OCRv6）

**技术栈：**
- 后端：FastAPI + Python 3.13 + SQLite (WAL)
- 前端：HTML5 + CSS3 + 原生 JavaScript
- 桌面端：PyQt6 + PyInstaller
- AI 引擎：PaddleOCR-VL-1.6 多模态识别
- 部署：Cloudflare Tunnel + Docker

---

## 六、报名帖链接

报名帖：<在此填写你通过的报名帖链接，如 https://forum.trae.cn/t/topic/xxxxx>

---

> DocFlow 将文档整理效率提升 10 倍以上，让 AI 真正服务于学习和工作中最高频的场景。欢迎大家体验！