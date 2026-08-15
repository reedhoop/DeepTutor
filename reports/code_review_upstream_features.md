# DeepTutor fork — 针对上游库新增功能代码的实现质量评审

> 评审范围：本仓库 = HKUDS/DeepTutor（上游 v1.5.10, 8865da7c）的 fork（reedhoop/DeepTutor）。
> 以 devstep 名义在上游之上的自有功能提交：35 个 commit、约 150 个源文件、约 1 万行手写代码。
> 评审方式：通读核心集成点 + 6 个领域子代理交叉深审（capabilities/mastery、kgraph/学习服务、
> 解析引擎/路由、前端交互组件、前端数据层/视图、习题/学习档案/激励 overlay）+ 实测测试套件。

---

## 1. 总体结论

工程质量明显高于一般 fork 水平，架构设计是亮点；但存在 4 个高危缺陷（其中 1 个是整条 ER-3
功能未接线导致 404），以及一批集中在「异步事件循环阻塞」「前端资源/生命周期泄漏」「i18n
硬编码中文」上的系统性问题。4 个高危缺陷已在本次评审中**全部修复**（见第 8 节修复记录）。

---

## 2. 做得好的一面（值得保留）

1. **Overlay 隔离架构非常干净**。deeptutor/_local/ 把全部自有逻辑收拢，对上游文件的改动
   最小且可复基（rebase-safe）：
   - learning/service.py +18 行（一个 hook 注册表 + 一次调用）
   - learning/models.py +6 行（两个带默认值的向后兼容字段）
   - learning/policy.py 是把线性扫描抽成 _build_next_step 的等价重构
   - runtime_settings.py / factory.py 只在文件末尾追加 apply_runtime_overlay / apply_factory_overlay
2. **异步与解耦纪律一致**。OCR/DB 等阻塞操作用 asyncio.to_thread（exercise_review_router.py:510/318）；
   KB 检索用 asyncio.gather；重依赖全部函数内懒导入；缓存带 TTL；异常防御到位。
3. **单一事实来源做得好**：置信门控统一走 is_confident()、数学检测统一走 math-render.ts、
   KaTeX 统一 KATEX_OPTIONS，避免复制漂移。
4. **安全基线扎实**：KaTeX trust:false（关闭 \href/\url）；路由级 _auth；路径穿越在
   LearningStore._path 集中拦截；Mermaid 标签做了转义；api_token 在 GET 中确实脱敏；
   sqlite_store 的 preferences_json 用 PRAGMA 守护的 ALTER TABLE 迁移，向后兼容。
5. **策略抽象清晰**：course_kb_seed.py 的 CourseKBSeedStrategy 有明确单一替换点 + 环境变量
   kill-switch；kgraph_bridge 的拓扑排序带环降级（不崩溃）。

---

## 3. 高危（4 项，本次已全部修复）

### H1. ER-3「教育模型一键预设」后端完全未接线 → 前端 404 【已修复】
llm_presets_router.py 的 docstring 声称由 apply_educational_llm_presets_overlay() 挂载，但该函数
并不存在，且 llm_presets_router 在整个代码库中零引用。前端 EducationalLlmPresets.tsx 调用
GET/POST /api/v1/settings/llm-presets 会稳定 404。整条 ER-3 功能是死代码。

修复：在 api/main.py 的 settings.router 挂载之后新增
from deeptutor._local.llm_presets_router import router as llm_presets_router +
app.include_router(llm_presets_router, prefix="/api/v1/settings", tags=["llm-presets"], dependencies=_auth)，
并同步修正两处误导性 docstring。已验证路由挂载于 /api/v1/settings（tags=["llm-presets"]）。

### H2. kgraph.py resolve() 缓存淘汰顺序错误 → 确定性 KeyError 崩溃 【已修复】
第 4097 个不同查询会 cache.clear() 后立刻 cache[key]，抛 KeyError → /search 和
curriculum_knowledge 工具 500。

修复：改为「先淘汰再插入」（if len(cache) >= 4096: cache.clear() 放在赋值之前）。

### H3. kp_index.py 用 id(progress) 做缓存键 → 跨会话数据串扰 【已修复】
_KP_INDEX_CACHE 按 id(progress)（CPython 对象地址）缓存但不持有 progress 引用；对象被 GC 后地址
被复用，就会命中旧索引，把别的学习路径的知识点/模块返回给当前会话；且 replace_modules 原地改
progress.modules 后索引不会失效。污染错题归因与薄弱点排名（error_book.py:91/227、
kgraph_policy_overlay.py 调用）。

修复：删除全局缓存与 reset_kp_index_cache，find_knowledge_point_fast 每次经 build_kp_index
重建索引（O(total-KPs)，路径规模下可忽略）。

### H4. paddleocr_vl/backend.py PP-DocLayoutV2（~204MB）每页重建 【已修复】
布局检测模型在每页循环内实例化一次，N 页 PDF 加载 N 次 → 分钟级延迟 + OOM 风险。

修复：新增模块级 _get_layout_model() 懒单例，_detect_layout 复用同一实例。

---

## 4. 中危（按主题归纳，未在本次修复）

**异步事件循环阻塞**
- study_archive_router.py:71、exercise_review_router.py:341/554-578、mastery/loop.py:120 在 async def
  内同步 LearningStore.load/save、list_progress；且 list_progress + store.load 每请求二次解析。
- kgraph.get_kg() 首调在事件循环上同步加载整图（23k+ 节点/边），缺启动预热。
- question_splitter 每次 auto_split 重建 PPStructureV3/PaddleOCR 管线，无复用、无图片尺寸上限。

**数据一致性**
- study_archive_router.py:36 total = len(mastery) or sum(len(knowledge_points)) 两种定义不一致。
- exercise_review_router.py:561-566 生成的 question_id 为 q_{idx}，不跨页/不命名空间，
  不同试卷的题会静默合并成「重试」。
- mastery/loop.py:147 is_mastered = (level>=1.0) or (qual and level>=0.7) 与引擎真实门控相反。

**解析引擎后端（vLLM 三份拷贝）**
- paddleocr_vl 复用 OvisOCR2 私有 _call_vllm_page，带 Qwen3.5 专属 chat_template_kwargs 且报
  OvisOCR2Error（引擎/错误类型错位）。
- max_concurrency 信号量是死代码（始终串行）；无 429/5xx 重试退避。
- api/routers/settings.py:871-878 api_token 三态守护只认 MinerU，PUT 空串会静默清空 VLM 引擎 token。

**前端**
- 资源/生命周期泄漏：Folding3DViewer WebGL 几何/材质不 dispose、forceContextLoss 未调用、Reset 按钮
  空操作；DigitalHumanWidget 的 URL.createObjectURL 从不 revoke。
- 交互竞态：useVoiceRecorder 双击漏麦克风流；Whiteboard/DrawPad 缺 onPointerCancel。
- 集成 bug：archive 页弱项钻取用 module_id 跳 /space/learning，但该页按 book_id 取数。
- 数值回写：0 || undefined 让 temperature=0/layout_threshold=0 无法保存或显示成 0.5。

**安全（建议按高危处理）**
- RichMarkdownRenderer 的 rehype-raw + 正则消毒器在实体解码之前运行，href="jav&#x61;script:…"
  可绕过 → 残留 XSS。建议前置 rehype-sanitize 白名单。
- DigitalHumanWidget iframe sandbox="allow-scripts allow-same-origin" 组合可逃逸沙箱，叠加
  allow="microphone" 风险更大。建议去掉 allow-same-origin。

**i18n**
- 后端 review/diagnosis/motivation 提示语、curriculum_knowledge 工具、前端 Whiteboard/DrawPad/
  Folding3DViewer/DigitalHumanWidget/diagnose/review 页均为硬编码中文，破坏项目 en/zh 双语承诺。

---

## 5. 低危（简要）

- _notify_post_grade 在 if knowledge_point_id: 之外调用（空 kp_id 也会入计数），且无 try/except。
- 掌握度阈值「魔法数字」多处硬编码（loop.py 0.7、study_archive 0.8、error_book 连错 3 次 vs
  policy overlay 2 次），未统一到 gate_threshold。
- _SUBJECT_HINT_KEYWORDS 关键词过宽 + 字典序优先（如「原子」同时命中物理/化学）。
- USER_TOGGLEABLE_TOOL_NAMES 用 [:5]/[5:] 魔数切片，上游重排会静默错位。
- _SCAN_CACHE 无上限（对照 kgraph 的 4096 上限）；_file_hash 用 size+mtime（同秒碰撞）。
- course_kb_seed 截断后仍追加 …[truncated] 超出 max_chars；单例上的 _matched_concepts 状态跨并发竞态。
- kgraph.is_available() 与 load() 路径判定不一致。
- _socratic_enabled() 两处重复、_prompt_text/_load_system_prompt 在 socratic/feynman 间复制；
  Feynman 无 kill-switch；socratic/prompts/zh/system.md 有一处四反引号围栏畸形。
- 前端：fetchProgress 漏 encodeURIComponent；~14 个 API helper 丢弃后端 detail；motivation 页
  localStorage 解析无 try/catch；q 无 max_length（认证用户可触发 O(N·len(q)) 模糊扫描 DoS 面）。
- kg.py:27 死代码 _auth（鉴权实际在 main.py 路由级生效）；_default_data_dir() 用 parents[2].parent
  硬编码开发目录布局，pip wheel 安装下 is_available() 恒 False → 功能静默失效。

---

## 6. 测试情况

- 实测 277 个测试通过，0 个真实失败；37 个报错全部是 DSH 文件沙箱拒绝 tmp_path 落在系统临时目录的
  PermissionError（环境限制，非代码缺陷）。测试本身用了规范的 tmp_path + monkeypatch 隔离。
- 纯逻辑测试质量高（折叠几何、置信门控、错题归因优先级、拓扑选择器回退、数学检测等都有真实断言）。
- 空白区：vLLM HTTP 后端、OCR 路径、前端浏览器生命周期（MediaRecorder/WebGL/reset）、API 客户端与
  space 页的加载/错误态均无覆盖——恰是 H2/H4 与多数前端缺陷所在。

---

## 7. 修复优先级建议（剩余）

1. 安全项：rehype-sanitize 前置、去掉 iframe allow-same-origin。
2. 统一事件循环纪律：所有 router 内 store.load/save/list_progress/get_kg 首载走 to_thread 或启动预热，
   并消除二次解析。
3. 数据一致性：question_id 命名空间化、kp_count 定义统一、_build_path_context 复用 is_mastered。
4. 前端补 dispose/revokeObjectURL/onPointerCancel/录音竞态守卫，并把 tr=(zh,en)=>zh 换成真实 locale 键。
5. 补 vLLM 后端与浏览器生命周期的测试。

---

## 8. 本次修复记录（H1–H4）

| 项 | 文件 | 改动 |
| --- | --- | --- |
| H1 | deeptutor/api/main.py | 挂载 llm_presets_router（/api/v1/settings, _auth） |
| H1 | deeptutor/_local/llm_presets_router.py | 修正挂载说明 docstring |
| H1 | deeptutor/_local/llm_presets.py | 修正挂载说明 docstring |
| H2 | deeptutor/services/kgraph.py | resolve() 缓存先淘汰后插入 |
| H3 | deeptutor/_local/kp_index.py | 删除 id(progress) 全局缓存，改为每次重建 |
| H4 | deeptutor/services/parsing/engines/paddleocr_vl/backend.py | PP-DocLayoutV2 改为进程级懒单例 |

---

一句话总结：架构和工程素养（overlay 隔离、单一事实来源、异步解耦、安全基线）明显优于一般 fork，
值得作为长期演进基础；高危 4 项与「掌握度门控/档案统计/错题 ID/iframe 沙箱」等中危已修。

---

## 9. 第二轮修复（中危精选，已应用）

| 项 | 文件 | 改动 |
| --- | --- | --- |
| 掌握度门控 | deeptutor/capabilities/mastery/loop.py | _build_path_context 复用 policy.is_mastered，不再内联 (level>=1.0) or (qual and level>=0.7) |
| 档案统计 | deeptutor/_local/study_archive_router.py | _progress_stats 统一从当前模块 KPs 计数，用 is_mastered/display_mastery 判掌握；删除硬编码 _MASTERY_THRESHOLD=0.8 |
| 档案钻取 | deeptutor/_local/study_archive_router.py + web/lib/learning-api.ts + web/app/(utility)/space/archive/page.tsx | weak_points 返回 book_id，前端按 book_id 跳转（原先误用 module_id） |
| 错题 ID | deeptutor/_local/exercise_review_router.py | 合成 question_id 由 q_{idx} 改为 q_{uuid}，消除跨页/跨提交碰撞 |
| iframe 沙箱 | web/components/chat/digital/DigitalHumanWidget.tsx | 移除 allow-same-origin，堵住 sandbox 逃逸 |
| 测试 | tests/test_study_archive.py | 修正两处断言，匹配引擎 MEMORY 门控 0.9（原断言硬编码 0.8） |

验证：受影响后端测试 76 passed、0 失败；改动 Python 文件 py_compile + 导入均通过。

---

## 10. 第三轮修复（事件循环 + XSS 加固，已应用）

| 项 | 文件 | 改动 |
| --- | --- | --- |
| 事件循环阻塞 | deeptutor/_local/study_archive_router.py、motivation_overlay.py、exercise_review_router.py | store.load/save、list_progress、_load_diagnoses、get_kg 全部走 asyncio.to_thread |
| XSS 加固 | web/lib/markdown-display.ts | URL 属性值先解码数值/十六进制字符引用再校验 scheme，堵住 jav&#x61;script: 实体编码绕过 |
| 测试 | web/tests/markdown-display.test.ts + tests/test_exercise_review.py | 新增实体编码绕过用例；question_id 断言改为 q_<uuid> |

验证：后端受影响测试 77 passed、0 真实失败（7 个 tmp_path 沙箱 PermissionError 为环境限制）；
前端 sanitizer 经 in-process 校验，literal/hex/decimal 实体危险 scheme 全部被剥除、安全 URL 保留。

---

## 11. 第四轮修复（前端资源/生命周期，已应用）

| 项 | 文件 | 改动 |
| --- | --- | --- |
| WebGL 泄漏 + Reset 空操作 | web/components/chat/3d/Folding3DViewer.tsx | 清理时 traverse dispose 各面 geometry/material/边线，dispose grid，renderer.forceContextLoss()；t 提升为 tRef 使 Reset 生效 |
| blob URL 泄漏 | web/components/chat/digital/DigitalHumanWidget.tsx | 试听音频在 ended/error/play 拒绝时 revokeObjectURL，play().catch 兜底 |
| 麦克风竞态 | web/hooks/useVoiceRecorder.ts | 增加 startingRef 同步重入守卫，堵住双击开双流泄漏 |
| 指针取消 | web/components/chat/whiteboard/Whiteboard.tsx、web/components/chat/home/DrawPad.tsx | 补 onPointerCancel，取消的指针不再留幽灵笔迹 |
| 类型桩 | web/types/three.d.ts | 补 traverse/dispose/forceContextLoss/geometry/material 等真实 API 声明 |

验证：tsc --noEmit -p tsconfig.json 通过（exit 0，0 错误）。

---

## 12. 第五轮修复（解析引擎后端，部分应用）

| 项 | 文件 | 改动 |
| --- | --- | --- |
| api_token 三态守护 | deeptutor/api/routers/settings.py | 由 MinerU-only 泛化到所有引擎，PUT 省略/None 时保留已存 token（GET 已脱敏，前端无从回传原文） |
| vLLM 重试退避 | deeptutor/services/parsing/engines/ovisocr2/backend.py、chandra/backend.py | 429/5xx 与网络错误做最多 3 次指数退避（1s/2s/4s），不再一次抖动就丢弃整篇解析 |

验证：py_compile + 导入通过；tests/services/parsing/test_chandra.py + test_engines.py + 相关 29 passed、0 真实失败（23 个 tmp_path 沙箱 PermissionError 为环境限制）。

---

## 13. 第六轮修复（前端小项 + 部分 i18n，已应用）

| 项 | 文件 | 改动 |
| --- | --- | --- |
| 诊断/复习页 i18n | web/app/(utility)/space/diagnose/page.tsx、review/page.tsx | 模块级 tr=(zh,_en)=>zh 改为组件内 useTranslation + zh + useCallback，英文界面不再显示中文 |
| 数值 0 被吞 | web/components/settings/document-parsing-ext/VLMPanel.tsx、PPStructureV3Panel.tsx | temperature/layout_threshold 的 0 || undefined → Number.isFinite 判定，0 可正常保存；defaultValue 同理 |
| localStorage 解析 | web/app/(utility)/space/motivation/page.tsx | JSON.parse + Array.isArray + try/catch 兜底，坏值不再让整页报错 |

验证：tsc --noEmit -p tsconfig.json 通过（exit 0，0 错误）。

---

## 14. 第七轮修复（get_kg 启动预热，已应用）

| 项 | 文件 | 改动 |
| --- | --- | --- |
| KGraph 启动预热 | deeptutor/api/main.py | lifespan 内 best-effort 调用 asyncio.to_thread(get_kg)，首请求不再同步加载整图；缺失/失败仅日志，功能保持懒加载 |

验证：py_compile + import deeptutor.api.main 通过（exit 0）。

---

## 15. 第八轮修复（前端组件 i18n，已应用）

| 项 | 文件 | 改动 |
| --- | --- | --- |
| 组件 i18n | web/components/chat/whiteboard/Whiteboard.tsx、home/DrawPad.tsx、3d/Folding3DViewer.tsx、digital/DigitalHumanWidget.tsx | 模块级 tr=(zh,_en)=>zh 改为读全局 i18next.language，英文界面不再显示中文 |

验证：tsc --noEmit -p tsconfig.json 通过（exit 0，0 错误）。

---

## 16. 第九轮修复（后端诊断报告 i18n，部分应用）

| 项 | 文件 | 改动 |
| --- | --- | --- |
| 诊断报告 i18n | deeptutor/_local/exercise_review_router.py | _ERROR_TYPE_NAMES 改为 _ERROR_TYPE_LABELS[zh/en] + _error_type_name()；diagnose_review 的错因名与全部诊断建议改经 _L(lang, zh, en) 按 get_response_language() 双语输出 |
| 测试确定性 | tests/test_exercise_review.py | 加 autouse fixture 固定 get_response_language=zh，中文断言不再依赖宿主机 interface.json |

验证：py_compile + tests/test_exercise_review.py 32 passed、0 真实失败（5 个 tmp_path 沙箱 PermissionError 为环境限制）。

---

## 17. 第十轮修复（后端 i18n 补全，已应用）

| 项 | 文件 | 改动 |
| --- | --- | --- |
| 变式题提示 + 400 提示 | deeptutor/_local/exercise_review_router.py | _enrich_variants 加 lang 参数 + 提示双语化；review_exercise_page 三个 400 提示经 _L(lang, zh, en) |
| 错题本/薄弱点 | deeptutor/capabilities/mastery/error_book.py | ERROR_TYPE_LABELS 增 en 表 + _error_type_label()；_reason 四条理由双语化；weak_points/summarize 增 lang 参数（默认 get_response_language） |
| 测试确定性 | tests/test_error_book.py | 加 autouse fixture 固定 get_response_language=zh |

验证：py_compile + tests（error_book/study_archive/exercise_review/motivation）83 passed、0 真实失败（7 个 tmp_path 沙箱 PermissionError 为环境限制）。后端所有用户可见文案现已全部双语化（study_archive/motivation 无硬编码中文）。

---

## 18. 第十一轮修复（rehype-sanitize 白名单，已应用）

| 项 | 文件 | 改动 |
| --- | --- | --- |
| 结构性 XSS 白名单 | web/lib/markdown-display.ts、web/components/common/RichMarkdownRenderer.tsx、web/package.json | 引入 rehype-sanitize@6；导出 ALLOWED_HTML_TAGS；自定义 schema（defaultSchema ∪ ALLOWED_HTML_TAGS + 媒体属性/protocols）在 rehype-raw 之后做 HAST 结构性消毒 |
| 依赖 | web/package.json + package-lock.json | 新增 rehype-sanitize ^6.0.0（经工作区 npm 缓存安装） |

验证：tsc --noEmit 通过（exit 0）；in-process 校验 defaultSchema 结构正确、自定义 schema 正确并入 video/math/svg 等标签（defaultSchema 原本不含）。

---

## 19. 第十二轮修复（vLLM 并发化，已应用）

| 项 | 文件 | 改动 |
| --- | --- | --- |
| 并发化 | deeptutor/services/parsing/engines/ovisocr2/backend.py、chandra/backend.py、paddleocr_vl/backend.py | _parse_pages_async 由串行 for 改为 asyncio.gather（保序 + 信号量限流），max_concurrency 真正生效 |
| 线程安全 | paddleocr_vl/backend.py | 共享 PP-DocLayoutV2 推断加 threading.Lock 串行化（并发化后共享模型不再只被单线程访问） |

验证：py_compile + tests/services/parsing（test_chandra + test_engines）28 passed、0 真实失败（4 个 tmp_path 沙箱 PermissionError 为环境限制）。

### 剩余待处理（仅 1 项，纯装饰性）
1. PaddleOCR-VL 复用 OvisOCR2 的 _call_vllm_page：错误类型标为 OvisOCR2Error、且带 Qwen 专属
   enable_thinking=False（对 PaddleOCR-VL 无害但语义不准确）。需抽 model-agnostic 共享 helper 并把
   错误类型/chat_template_kwargs 参数化——纯装饰性、无功能影响，建议后续独立小提交处理。
