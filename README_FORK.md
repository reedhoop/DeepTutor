# DeepTutor 项目特色介绍（reedhoop/DeepTutor fork）

> 本文基于上游 **HKUDS/DeepTutor** 官方 README 整理，并补充本 fork 的自研增强特色。官方完整文档以仓库内 `README.md` 与 <https://deeptutor.info> 为准。
>
> 项目论文：arXiv [2604.26962](https://arxiv.org/abs/2604.26962) ｜ 协议：Apache-2.0 ｜ 上游：<https://github.com/HKUDS/DeepTutor>

---

## 一、项目是什么

DeepTutor 是香港大学 HKUDS 团队开源的**「代理原生（agent-native）终身学习辅导系统」**——把辅导对话、解题、出题、研究、可视化、掌握度练习整合进一个可扩展的工作区，让学习者在同一条智能体循环（agent loop）里切换学习目标，而不是切换引擎。

本仓库 `reedhoop/DeepTutor` 是上游的一个 fork，在官方主干能力之上，**针对中小学 K12 场景与本地化部署**做了一系列自研增强（代号 **ER-1 ~ ER-14**），并接入了中小学学科知识图谱与多个自研 VLM 文档解析引擎。

---

## 二、上游主干核心能力

（以下能力为本 fork 继承的官方主干，完整说明见官方 README）

- **统一 Agent Loop**：Chat / Quiz / Research / Visualize / Solve / Mastery Path 共用一个智能体循环，切换的是目标而非引擎，上下文随学习者走。
- **连通的学习上下文**：知识库、书籍、Co-Writer 草稿、笔记本、题库、人格（persona）、记忆跨工作流共享，而非散落在孤立工具里。
- **多引擎知识库**：LlamaIndex（默认）/ PageIndex / GraphRAG / LightRAG / 链接 Obsidian 库，文档解析可插拔（Text-only、MinerU、Docling、markitdown、PyMuPDF4LLM）。
- **可扩展工具与技能**：内置工具、MCP 服务、CLI Apps、图像/视频/语音生成模型，以及 EduHub 社区技能市场（带安全导入门控）。
- **可审计的三层记忆**：L1 轨迹 / L2 分面摘要 / L3 跨面综合，配 Memory Graph 把每条结论回溯到原始证据。
- **多用户隔离部署**：可选鉴权，admin 工作区与每用户工作区（含伙伴工作区）并存的隔离布局。

---

## 三、本 fork 自研特色（重点）

### 1. K12 学科知识图谱深度融合（K12-KGraph）

- 接入中小学学科知识图谱（数据已内嵌进本仓库的 `K12-KGraph-data/` 目录，约 16MB，含来源与版权说明见该目录 `README.md`），提供**知识点关联、学习路径推荐、薄弱点定位**。
- 向量缓存（`node_vectors.json`，约 232MB，已 gitignore）支持规模化检索；以 `kgraph.is_available()` 实测可用性，不依赖环境变量是否设置。

### 2. 自研 VLM 文档解析引擎（9 引擎矩阵）

- 在官方 5 引擎（text_only / mineru / docling / markitdown / pymupdf4llm）之上，**新增 4 个自研 vLLM 引擎**：
  - `ovisocr2`、`paddleocr_vl`、`pp_structurev3`：各自专精 OCR / 版面 / 结构识别；
  - `chandra`：**公式 + 手写 + 版面一体化**的 vLLM 模型，与专精引擎形成"一体化 vs 专精"双轨。
- 引擎注册三件套（`deeptutor/_local/` 下的 `engines_registry` / `engine_defaults` / `engine_router`）实现协议级通用接入；新增 vLLM 引擎照 `ovisocr2` 模板即可。
- **智能 auto-router**：按各引擎就绪态自动选最优解析器，未就绪时安全回落，不破坏既有路由。

### 3. ER 系列增强（ER-1 ~ ER-14 已全部落地）

面向 K12 学习闭环的一系列功能增强，代号 ER-1 ~ ER-14，共 14 项，按编号缕列：

- **ER-1 课本页与知识图谱可视化**：课本浏览、学段分组（小学 / 初中 / 高中 → 教材）的沉浸式阅读体验；并引入 Mermaid 把 K12-KGraph 知识点关系图渲染出来。
- **ER-2 教材章节思维导图**：课本页内置 markmap 脑图视图，把教材目录树（前端 `fetchTextbookTree()` 取得）直接转 Markdown 渲染为可缩放、可折叠的思维脑图（组件 `TextbookMindmap.tsx`），零新增后端端点。
- **ER-3 教育 LLM 一键预设**：设置页新增「教育模型预设」面板（组件 `EducationalLlmPresets.tsx`），后端 `_local/llm_presets.py` + `llm_presets_router.py` 提供 `llm-presets` / `llm-presets/apply` 路由，一键切换 / 回滚到教育调优的模型配置。
- **ER-4 公式渲染单一真源**：`web/lib/math-render.ts` 统一 KaTeX 渲染与数学内容判定（`MATH_SPAN_REGEX` / `detectMathContent` / `KATEX_OPTIONS`），全站一处维护。
- **ER-5 Chandra 引擎接入**：公式 + 手写 + 版面一体化模型落地为可配置 VLM 解析引擎（见上文「9 引擎矩阵」）。
- **ER-6 几何作图内联渲染**：几何题经后端 `vision_solver` 工具链生成 `ggbscript`，前端 `RichMarkdownRenderer` 将 ```` ```ggbscript ```` 围栏渲染为可交互的 InlineGeoGebra 画板（右侧 `SessionViewerPanel` 内联），`agent_loop` 兜底注入确保几何题必有交互作图。
- **ER-7 学生画板**：对话输入区**内嵌轻量手写 canvas**（画笔 / 橡皮 / 6 色 / 3 档笔宽 / 逐笔撤销 / 清空，零外部依赖），画完以图片附件直接走既有多模态链路。
- **ER-8 数字人**：右下角浮动 widget，**内置 SVG 导师形象**（嘴型随 TTS 播放开合，零部署离线可用）；并预留 GMTalker（FunASR + MeloTTS + 嘴型）的 iframe 接入面，部署 GPU 后填 URL 即可升级为真数字人。
- **ER-9 Three.js 3D 几何翻折演示**：引入 Three.js，大模型生成参数化模型脚本，实现「平面图形翻折成立体」的启发式交互（案例库 `fold-cases.ts` + ```` ```er3d:case_id ```` 围栏自动触发），含几何校验。
- **ER-10 完整白板**：以 tldraw 为主界面的全屏白板 overlay 学习模式，提供形状 / 文本 / 网格 / 导出等完整工具集，与 chat / 教材 / 学习空间并存且不冲突（与 ER-7 轻量画板区分：ER-7 用于多模态草图输入，ER-10 用于整页演算讲解）。
- **ER-11 语音交互**：MediaRecorder → STT 识别、TTS 语音播报、**音色选择**（实测 17 种音色）、自动播报开关；后端清洗 SenseVoice 标签，前端 `cleanTranscript` 同步，默认关闭 autoplay（计费安全）。
- **ER-12 试卷切分与水平诊断**：试卷自动切分、水平诊断报告、与知识点自动关联、AI 习题讲评，并设独立入口。
- **ER-13 成长档案**：`/space/archive` 页面，复用 KGraphMermaid 展示**知识脉络 + 掌握度着色 + 学习时间线**，纯只读派生。
- **ER-14 学习激励**：`/space/motivation` 页面，**徽章墙（12 项）+ 学习积分 + 连续学习 streak**，纯正向激励、不做竞争排行。

### 4. Stage 3 错题闭环

- `error_book` 错题本 + `exercise_adapter` **四级变式练习**（direct → section → neighbor → chapter）+ 评分后 hook + `variant_exercise` 工具 + 前端 ErrorBook 页面，形成"错题 → 变式巩固 → 掌握度回写"的完整闭环。

### 5. 本地化与工程打磨

- 中文 i18n 双语（前端 `web/locales/{en,zh}/app.json` 同步 + `i18n_parity` 校验）。
- 前端布局/滚动打磨：修复 AppShell 高度链（`flex flex-col` 缺失导致全站列表不滚）、滚动条改为 6px + `color-mix` 透明（含旧浏览器实色 fallback）。

---

## 四、技术栈与本地启动

- **后端**：Python 3.12 + FastAPI（uvicorn），VLM 解析走自研 vLLM 引擎与 K12-KGraph。
- **前端**：Next.js 16 + React 19（Node 22 LTS）。
- **启动铁律**（本地开发）：
  - 后端：`uvicorn deeptutor.api.main:app --port 8101`（用项目 venv 解释器，禁用系统 `C:\Python312`）。
  - 前端：**必须带环境变量** `DEEPTUTOR_API_BASE_URL=http://127.0.0.1:8101 BACKEND_PORT=8101` 启动 Next dev（端口 3782），否则代理回落 8001 导致所有 `/api/*` 挂起；且务必用 `127.0.0.1` 而非 `localhost`（双栈 `::1` 回落失败）。
- 完整官方安装（PyPI / 源码 / Docker / CLI）见上游 README 的 *Get Started* 章节。
- **生产部署（Windows NSSM 服务化）**：`python scripts/install_prod_service.py install --skip-build` 一条命令注册
  `DeepTutorBackend`(:8002) / `DeepTutorFrontend`(:3800) 两个常驻服务（开机自启 + 崩溃自愈，K12 默认走仓库内
  `K12-KGraph-data`，无需额外参数），详见 [DEPLOY_PRODUCTION.md](DEPLOY_PRODUCTION.md)。

---

## 五、与上游的关系

- **上游**：HKUDS/DeepTutor（Apache-2.0，文档站 deeptutor.info）。
- **本 fork**：`reedhoop/DeepTutor`，对上游**单向消费**（仅 `git rebase upstream/main`），自研改动集中在 `deeptutor/_local/` overlay 与少量 fork 文件，便于持续同步上游。
- 欢迎基于本文进一步补充或并入官方 README；本文仅作快速了解项目定位与亮点的导读。
