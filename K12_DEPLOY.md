# K12 版 DeepTutor 部署指南（reedhoop/DeepTutor）

> 本文档只讲 **K12 fork 专属** 的部署要点。基础安装（PyPI / 源码 / Docker）请看主
> [README.md](README.md) 与 [CONTAINERIZATION.md](CONTAINERIZATION.md)。
>
> 一句话：**基础 DeepTutor 很好部署，但 K12 叠加层缺一个「一键 + 自举」的入口。**
> 本仓库提供的 [`scripts/deploy_k12.py`](scripts/deploy_k12.py) 就是这个入口。

---

## 1. 为什么需要专门的 K12 部署

相对上游 HKUDS/DeepTutor，本 fork 额外加了三层「没人帮你自动化」的东西：

| 卡点 | 现状 | 本 harness 如何处理 |
|---|---|---|
| **K12-KGraph** 知识图 | 已内嵌进私有 fork 仓库 `K12-KGraph-data/`（仅含运行时必需的 `global_KG/` + `subject_specific_KG/`，约 16MB；含来源与版权说明见该目录 `README.md`） | ✅ 开箱即用；也可设 `K12_KGRAPH_DATA_DIR` 指向外部副本 |
| **4 个 VLM 解析引擎**（ovisocr2 / paddleocr_vl / pp_structurev3 / chandra） | 需自建外部 vLLM 服务 + HF/ModelScope 权重；不在 requirements；`deeptutor init` 完全不提示 | ⚠️ 自动写好引擎默认配置，文档说明如何起 vLLM（权重不自动下） |
| **K12 配置初始化** | `.env.example` 只覆盖端口+TZ；KGraph 路径 / VLM / 语音 API key 全要手动补 | ✅ 非交互 seed `model_catalog.json` + `system.json` |

缺 KGraph 时大部分功能**优雅降级**（仅跳过概念锚定 / 错题变式等少数路径），不会崩；
但 `node_vectors.json`（~232MB 语义向量缓存）首次语义检索时才生成，且需要 embedding 端点。

---

## 2. 最简部署（三段式）

> ⚠️ **脚本本身在仓库内，不能真的"空目录一条命令"**。必须先 clone 再从这个目录里运行。

完整 K12 部署只需三步：

```bash
# 0) 拉代码（公开仓库，无需登录）
git clone https://github.com/reedhoop/DeepTutor.git mytutor && cd mytutor

# 1) 写密钥（必须！否则 app 能启动但无法辅导）——见 §5 完整变量表
cat > .deploy-k12.env <<'EOF'
LLM_API_KEY=sk-xxx
LLM_BASE_URL=https://api.openai.com/v1
LLM_MODEL=gpt-4o
EMBEDDING_API_KEY=sk-yyy
EMBEDDING_BASE_URL=https://api.siliconflow.cn/v1
EMBEDDING_MODEL=BAAI/bge-m3
VLM_SEED=true
EOF

# 2) 一条命令：clone(KGraph) → 装依赖 → 写配置 → 起服务
python scripts/deploy_k12.py all --non-interactive
#   中途会硬性检查 LLM/EMBEDDING 配置，缺了直接报错退出，不会白跑
```

它会：

1. **preflight**：检查 python3.11+ / node20+ / git，并提示是否检测到密钥。
2. **requirements 门禁**：若缺 `LLM_*` 或 `EMBEDDING_*`，**直接 FAIL 退出**（加 `--skip-key-check` 可绕过，仅用于部署空壳）。
3. **clone**：DeepTutor 已在当前目录则跳过；`K12-KGraph-data` 已随仓库内嵌则跳过 clone，否则按 `K12_KGRAPH_REPO` 克隆到同级目录（自动先 `git lfs install`）。
4. **install**：建 `.venv`，`pip install -e .`，`npm ci`（web 前端）。
5. **configure**：非交互地生成 settings——LLM/Embedding/TTS/STT profile（来自环境变量）+ 4 个 VLM 引擎默认切片 + 端口 + `K12_KGRAPH_DATA_DIR`。
6. **start**：后台拉起 `deeptutor start`，等待前端就绪。

默认端口：后端 `8001`、前端 `3782`（上游默认）。本地若用其它端口，见 §5。

> 所有步骤**幂等**：已完成的自动跳过，可重复运行。

✅ **部署成功标志**：最后出现 `bootstrap OK` 且 `status` 显示前端返回 200。此时即可打开 `http://127.0.0.1:3782` 使用（VLM 引擎需另行起 vLLM，见 §7，不影响其余功能）。

---

## 3. 分步执行（调试友好）

```bash
python scripts/deploy_k12.py preflight    # 只查环境
python scripts/deploy_k12.py clone        # 只拉仓库
python scripts/deploy_k12.py install      # 只装依赖
python scripts/deploy_k12.py configure    # 只写配置
python scripts/deploy_k12.py start        # 只启动（后台）
python scripts/deploy_k12.py status       # 健康检查（前端/后端端口）
python scripts/deploy_k12.py stop         # 停止后台进程
```

---

## 4. 给 Agent 的无人值守部署

脚本对 agent 友好：`--json` 输出 NDJSON 事件流（`ts` / `level` / `step` / `status` / `detail`），**全程无交互**，配置全部来自环境变量 / `.deploy-k12.env`。

### Agent 标准流程（照做即可）
1. `git clone https://github.com/reedhoop/DeepTutor.git <dir> && cd <dir>`（脚本在仓库内，必须先 clone）。
2. 把密钥写进 `<dir>/.deploy-k12.env`（至少 `LLM_*` 与 `EMBEDDING_*`），见 §5 完整变量表。
3. 运行 `python scripts/deploy_k12.py all --non-interactive --json`，捕获 stdout。
4. 解析事件流判定结果（见下）。

### 成功 / 失败判定（关键，agent 必须遵守）
- **出现任一 `status:"FAIL"` 事件 → 部署未成功，立即停止**，读取该事件的 `detail` 定位原因（常见：网络不通无法 clone、`pip`/`npm` 失败、缺 `LLM`/`EMBEDDING` 配置门禁未过）。
- **最终出现 `step:"bootstrap" status:"OK"` 且 `status` 子命令显示前端 200 → 部署成功**。但注意：
  - `bootstrap OK` **只代表进程起来了**，不代表"能辅导"。必须确认 §2 的 `LLM_*`/`EMBEDDING_*` 已提供（门禁会拦下缺失的情况）。
  - 用 `python scripts/deploy_k12.py status` 复核：前端 `http://127.0.0.1:<FRONTEND_PORT>` 应返回 200，后端 `http://127.0.0.1:<BACKEND_PORT>` 应在线。
- **缺 VLM 不算失败**：VLM 引擎按设计需另行起 vLLM（§7），缺它时其余功能照常，部署仍判成功。

```bash
# 1) 先 clone（脚本在仓库内，空目录直接跑会找不到脚本）；2) 写密钥；3) 一键跑
cd /path/to/DeepTutor   # 即上面 git clone 出来的目录
cat > .deploy-k12.env <<'EOF'
LLM_API_KEY=sk-xxx
LLM_BASE_URL=https://api.openai.com/v1
LLM_MODEL=gpt-4o
EMBEDDING_API_KEY=sk-yyy
EMBEDDING_BASE_URL=https://api.siliconflow.cn/v1
EMBEDDING_MODEL=BAAI/bge-m3
VLM_SEED=true
EOF

python scripts/deploy_k12.py all --non-interactive --json
```

事件流示例：
```json
{"ts":"2026-08-15T10:52:42+00:00","level":"info","step":"configure","status":"OK","detail":"已写入 LLM profile（active）"}
{"ts":"2026-08-15T10:52:43+00:00","level":"info","step":"configure","status":"OK","detail":"已写入 VLM 引擎默认配置：ovisocr2, paddleocr_vl, pp_structurev3, chandra"}
```

---

## 5. 配置参考（环境变量 / `.deploy-k12.env`）

| 变量 | 含义 | 默认 |
|---|---|---|
| `DEEPTUTOR_REPO` | DeepTutor fork 地址 | `https://github.com/reedhoop/DeepTutor.git` |
| `DEEPTUTOR_BRANCH` | 分支 | `main` |
| `K12_KGRAPH_REPO` | K12-KGraph 仓库 | `https://hf-mirror.com/datasets/lhpku20010120/K12-KGraph` |
| `DEEPTUTOR_HOME` | 工作区目录 | 当前目录 |
| `BACKEND_PORT` / `FRONTEND_PORT` | 端口 | `8001` / `3782` |
| `INSTALL_EXTRAS` | pip extras（逗号） | `""`（建议 `"math-animator"` 开数学动画） |
| `DEV` | 是否 `deeptutor start --dev` | `false` |
| `VLM_SEED` | 是否写入 4 个 VLM 引擎默认配置 | `true` |
| `KGRAPH_WARM` | 是否预热 node_vectors（需 embedding key，较慢） | `false` |

模型配置（**缺省时仍会 seed 一个空 profile**，启动后在 Settings 页面补；不阻断启动）：

```
LLM_API_KEY / LLM_BASE_URL / LLM_MODEL / LLM_NAME / LLM_BINDING
EMBEDDING_API_KEY / EMBEDDING_BASE_URL / EMBEDDING_MODEL / EMBEDDING_BINDING
TTS_API_KEY / TTS_BASE_URL / TTS_MODEL / TTS_VOICE / TTS_BINDING
STT_API_KEY / STT_BASE_URL / STT_MODEL / STT_BINDING
```

---

## 6. K12-KGraph 知识图

- **数据已内嵌**于仓库 `K12-KGraph-data/`（仅 `global_KG/` + `subject_specific_KG/`，约 16MB），
  默认即可用，无需单独 clone。来源、授权与版权说明见该目录 `README.md`。
- **回退方案**：若仓库内无该目录（例如从上游拉取时未包含），`deploy_k12.py` 会按
  `K12_KGRAPH_REPO`（`https://hf-mirror.com/datasets/lhpku20010120/K12-KGraph`）自动 clone 到
  `DEEPTUTOR_HOME` 同级 `K12-KGraph-data` 并写 `K12_KGRAPH_DATA_DIR`（clone 前会自动 `git lfs install`）；
  也可手动 clone 后设置：`export K12_KGRAPH_DATA_DIR=/path/to/K12-KGraph-data`。
- ⚠️ **若该仓库含 git-lfs 大文件**：clone 前请确认本机已 `git lfs install`（脚本会尝试，但若失败，手动 clone 该仓库并设好 `K12_KGRAPH_DATA_DIR` 即可，不影响其余步骤）。
- `node_vectors.json`（~232MB 语义向量缓存）**首次语义检索时自动生成**，需要可用的
  embedding 端点（见 §5 的 `EMBEDDING_*`）。想预热可设 `KGRAPH_WARM=true` 后再启动。
- 缺 KGraph 时：大部分功能降级（跳过概念锚定、错题变式等少数路径会报错），其余照常。

> **授权提醒**：上游 `haolpku/K12-KGraph` 含两份许可——`LICENSE`（**CC BY-NC-SA 4.0**，覆盖数据集/图谱/K12-Bench/K12-Train）
> 与 `LICENSE-CODE`（**MIT**，覆盖源代码/脚本）。本内嵌副本**只含数据集**，故仅受 **CC BY-NC-SA 4.0** 约束。
> **本项目明确为非商业用途**（研究/个人非盈利/高校课题），满足非商业（NC）条款；须署名 PKU 原项目+论文，
> 且衍生图谱继续 CC BY-NC-SA 4.0。**商用须与上游（PKU 团队）另谈授权**。详见 `K12-KGraph-data/README.md`。

---

## 7. VLM 解析引擎（需要自建 vLLM）

4 个引擎的**配置**脚本已自动写好（在 `system.json → document_parsing.engines`），
但权重与 vLLM 服务需你自行准备（脚本不自动下十几 GB 权重）：

| 引擎 | 模型 | 默认 vLLM 地址 | 启动方式 |
|---|---|---|---|
| `ovisocr2` | `ATH-MaaS/OvisOCR2` | `:8200/v1` | `vllm serve ATH-MaaS/OvisOCR2 --port 8200` |
| `paddleocr_vl` | `PaddleOCR-VL-1.6-0.9B` | `:8118/v1` | `paddleocr genai_server`（默认监听 8118） |
| `pp_structurev3` | 本地 PaddleOCR 管线 | 无（本地跑） | 装 `paddleocr` 包；首次需下载权重（`allow_local_model_download`） |
| `chandra` | **需自填** | `:8230/v1` | 部署 Chandra 的 vLLM 后，在 **Settings → 解析引擎** 填入 model_name + 地址 |

让引擎真正生效：

1. 拉起对应 vLLM 服务（GPU 机器；端口见上表）。
2. 打开 **Settings → 解析引擎**，确认各引擎的 `api_base_url` / `model_name` 正确。
   - `chandra` 的 `model_name` 故意留空——必须填了你部署的 Chandra 模型名才能用。
3. `routing_mode` 默认 `manual`（行为不变）；想自动选最优引擎可切 `auto`。

> `pp_structurev3` 不依赖 vLLM，但是本地 PaddleOCR，需 `pip install paddleocr` 并允许权重下载。
> 该包可走 Settings 页面「一键安装」，或在 `pip install -e ".[<extra>]"` 中纳入。

**没有 VLM 时能用什么（重要边界）**：VLM 引擎是"增强项"，不是"必需项"。
- 不起 vLLM / 不填模型：课本、题目仍走上游默认解析（基础 OCR / PDF 文本提取）可用；
  辅导对话、KGraph 概念锚定、错题本、three.js 3D、语音、math_animation **全部不受影响**。
- 只有"K12 增强的版面 / 公式 / 手写一体化识别"这一项会降级。所以**部署成功 ≠ 必须配 VLM**，
  agent 判定部署结果时不要因 VLM 未配而判失败。

---

## 8. 常见问题

- **前端起来了但「Backend unreachable」**：后端没起。看 `deploy-k12.start.log`。
- **状态检查后端 8001 不通**：确认你没改 `BACKEND_PORT`；本地若用 8101 等非默认端口，
  给脚本传 `BACKEND_PORT=8101`。
- **KGraph 没生效**：检查 `K12_KGRAPH_DATA_DIR` 指向的目录存在且含仓库内容；
  语义检索首次会触发 `node_vectors.json` 生成（需 embedding key，耗时）。
- **VLM 一直解析失败**：vLLM 服务是否在对应端口运行？`model_name` 是否填对（尤其 chandra）？
- **想从头重来**：`python scripts/deploy_k12.py stop` 后删除 `.venv` / `data/user/settings` 重跑。

---

## 9. 设计取舍

- **为什么不做「自动下 VLM 权重 + 自动起 vLLM」**：权重通常 10GB+，需 GPU，且来源
  （HF/ModelScope）与许可证各异；自动下载既慢又可能踩合规。故采用 deepseek-harness 思路：
  **脚本把配置/路径/依赖关系理清楚，重活留给用户或 agent 显式触发**。
- **为什么 seed 配置而非依赖交互式 `deeptutor init`**：`init` 不提示任何 K12 项；
  直接生成 `model_catalog.json` / `system.json`（schema 与运行时一致）才能实现无人值守。
