# DeepTutor 生产部署指南（Windows NSSM 服务化）

> 把 DeepTutor 以**两个 Windows 服务**常驻运行：开机自启、崩溃自愈，适合 7×24 生产环境。
> 本指南覆盖部署 commit `3186638a` 涉及的全部内容：K12 默认开启 + NSSM 安装器加固 + Python 安装器。
>
> 本地开发 / K12 一键部署（`scripts/deploy_k12.py`，端口 8001/3782 的 dev 模式）见 [K12_DEPLOY.md](K12_DEPLOY.md)；
> 基础安装（PyPI / 源码 / Docker）见 [README.md](README.md)。

---

## 1. 部署架构

| 服务 | 进程 | 说明 |
|---|---|---|
| `DeepTutorBackend` | `<repo>\.venv\Scripts\python.exe -m uvicorn deeptutor.api.main:app --host 0.0.0.0 --port 8002 --log-level info --no-access-log --ws-max-size 43341141 --timeout-keep-alive 300` | FastAPI 后端 |
| `DeepTutorFrontend` | `node .next\standalone\server.js`（工作目录 `web`，`PORT=3800`、`DEEPTUTOR_API_BASE_URL=http://localhost:8002`） | Next.js 16 standalone 前端，**依赖后端服务** |

两个服务均：
- 启动类型 **Automatic**（开机自启）；
- NSSM `AppExit Default=Restart`（进程崩溃自动拉起，5s 节流防风暴）；
- 日志分别写入仓库根 `prod-backend.log` / `prod-frontend.log`。

> `--timeout-keep-alive 300` 是刻意为之：必须大于前端代理的 5s socket 收割器，
> 否则两者竞态关闭同一空闲连接导致请求 ECONNRESET。

---

## 2. 依赖与要求（部署前逐项核对）

### 必选依赖

| 依赖 | 要求 | 说明 |
|---|---|---|
| 操作系统 | Windows 10/11（x64） | 服务化依赖 NSSM，仅支持 Windows |
| 权限 | **管理员** | 注册服务要写 SCM，必须提权（`net session` 可验证，报「拒绝访问」即未提权） |
| Git | 任意可用版本 | 拉取仓库代码 |
| Python | **3.12.x**（推荐 3.12.8） | 用于建 `.venv` 并装后端依赖；3.11 / 3.13 **未验证**。装好后后端服务固定用 `.venv` 解释器，与系统 Python 无关 |
| Node.js | **22 LTS+**（24 实测可用），且在 PATH | 前端构建 + standalone 运行都需要 |
| npm | 随 Node 自带 | 前端构建需要 |
| 网络 | 首次安装需可达 npm registry / PyPI（或镜像）/ nssm.cc | ① `npm install` ② `pip install -e .` ③ NSSM 自动下载（也可离线把 `nssm.exe` 放入 `scripts\bin\` 绕过 ③） |
| 端口 | `8002` / `3800` 空闲 | 被占可用 `--backend-port` / `--frontend-port` 换端口；对外提供访问时防火墙需放行 |

### 后端依赖安装（仓库内执行）

```powershell
cd <repo>
python -m venv .venv                      # 用 3.12.x 的 python 建
.venv\Scripts\pip install -e .            # 基础依赖
# 可选 extras（如数学动画，见 K12_DEPLOY.md 的 INSTALL_EXTRAS）：
.venv\Scripts\pip install -e ".[math-animator]"
# 若 setuptools>=61 装不上（清华源偶发空包），换阿里云源 + --no-build-isolation：
.venv\Scripts\pip install "setuptools>=61.0" wheel -i https://mirrors.aliyun.com/pypi/simple/
.venv\Scripts\pip install -e . --no-build-isolation -i https://mirrors.aliyun.com/pypi/simple/
```

### 前端构建

- 安装器首次安装自动执行 `npm install && npm run build` 并产出 `web\.next\standalone`（需网络）。
- 已有构建可加 `--skip-build` 跳过（省时）；若此时 `web\.next\standalone\server.js` 缺失，安装器会告警且前端服务将无法启动。

### 可选依赖（不影响服务启动，只影响对应功能）

- **Embedding 端点**（OpenAI 兼容）：K12 语义检索首次会生成 `node_vectors.json`（约 232MB，生成较慢）——没有则语义检索降级，其余 K12 功能（概念锚定/学习路径/掌握度）照常。
  ⚠️ **上线前务必先预热向量**：首次语义检索会**同步**全量 embed 全部 KG 节点（10-30 分钟），此时第一个用户请求会被卡死。配好 embedding 后先跑
  `python scripts\prewarm_node_vectors.py`（写入 `data\knowledge_bases\k12_kg\node_vectors.json`）再开放访问；临时应急可放一个空 `{}` 的
  `node_vectors.json` 让语义搜索降级跳过（静态概念匹配不受影响），预热完成后再覆盖为真实向量。
- **VLM 引擎 vLLM 服务**（ovisocr2 / paddleocr_vl / pp_structurev3 / chandra）：K12 增强的版面/公式/手写一体化解析用；缺了回落基础 OCR，服务照常（详见 K12_DEPLOY.md §7）。
- **`auth.json`**：加 `--enable-auth` 开启多用户登录时，需 `data\user\settings\auth.json` 已存在，否则安装器告警并跳过。
- **磁盘**：仓库（含 K12 数据约 16MB）+ `.venv` + 前端构建产物 + 可选 `node_vectors.json`（232MB）。

---

## 3. 快速开始（推荐：Python 安装器）

> 命令中的 `python` 可以是任意系统 Python（安装器内部自己解析 venv，不依赖执行它的解释器）。

```powershell
# 以管理员身份打开 PowerShell
cd <repo>

python scripts\install_prod_service.py status                    # 查两个服务状态
python scripts\install_prod_service.py install --skip-build      # 安装/重装（复用已有前端构建）
python scripts\install_prod_service.py install                   # 安装并重建前端（npm install + next build）
python scripts\install_prod_service.py install --dry-run --skip-build   # 只打印计划，不落盘
python scripts\install_prod_service.py uninstall                 # 卸载（停 + 删两个服务）
```

**幂等**：服务已存在时先 `sc.exe stop` + `sc.exe delete`，并**轮询等旧服务真正消失**再全新注册，
不会出现「同名服务残留导致安装失败」。

### 常用参数（install）

| 参数 | 说明 | 默认 |
|---|---|---|
| `--backend-port` / `--frontend-port` | 覆盖端口 | `8002` / `3800` |
| `--skip-build` | 复用已有 `web\.next\standalone` | 关 |
| `--dry-run` | 只打印计划（跳过构建） | 关 |
| `--k12-data-dir` / `--k12-cache-dir` | 覆盖 K12 数据/缓存目录 | 见下 |
| `--enable-auth` / `--secure-cookies` | 开启多用户登录（写 `auth.json`） | 关 |
| `--nssm-path` | 指定 nssm.exe | 自动解析 |

### K12 默认开启

K12-KGraph 数据已 **vendor 进仓库**（`<repo>/K12-KGraph-data/`，仅 `global_KG/` + `subject_specific_KG/`，
约 16MB，来源与版权见该目录 `README.md`）。解析顺序：

```
--k12-data-dir > 环境变量 K12_KGRAPH_DATA_DIR > <repo>/K12-KGraph-data（仓库内，默认命中） > 同级 sibling 回退
```

**全新 clone 无需任何参数即可启用 K12**；缓存目录默认 `<repo>\data\knowledge_bases\k12_kg`。

---

## 4. 验证部署成功

```powershell
Get-Service DeepTutorBackend, DeepTutorFrontend          # 应均为 Running
```

- 后端日志 `prod-backend.log` 应出现：`Application startup complete` + `Uvicorn running on http://0.0.0.0:8002`
  + `K12-KGraph index loaded`。
- 前端日志 `prod-frontend.log` 应出现：`Next.js 16.x.x` + `✓ Ready`。
- 健康检查（**后端没有顶层 `/health`**，各子路由自带 `/api/v1/<router>/health`）：

  ```powershell
  curl http://localhost:8002/api/v1/knowledge/health     # 期望 200 {"status":"ok",...}
  curl http://localhost:3800                             # 期望 200 <title>DeepTutor</title>
  curl http://localhost:3800/api/v1/knowledge/health     # 期望 200（前端代理后端 = 端到端通）
  ```

---

## 5. 排障手册（都是踩过的坑）

1. **必须提权**：`net session` 报「拒绝访问」= 不是管理员，NSSM/sc 写 SCM 会被拒。
   右键「以管理员身份运行」重开 PowerShell。
2. **PowerShell 里用 `sc.exe`，不要用 `sc`**：`sc` 是 `Set-Content` 的别名，`sc query/stop/delete`
   全是空操作（无输出、无效果）。服务操作一律 `sc.exe`。
3. **旧服务删不掉**：服务处于 `STOP_PENDING` / 「已标记删除」(SCM 1072) 时，`nssm remove` 会失败。
   正确姿势：`sc.exe stop <name>`（容忍 1062 未运行）→ `sc.exe delete <name>`（容忍 1072）→
   **轮询到服务真正消失**再重装。Python 安装器已自动处理；手动时可重复 `sc.exe query <name>` 确认。
4. **服务起来了却是 REPL（日志是 `>>>` / `>`）**：说明 NSSM 只启动了 exe 本体、`AppParameters` 为空。
   原因多半是 `nssm install <svc> <app> <args>` 在部分 NSSM 构建下不写参数。正确姿势：
   `nssm install <svc> <app>`（只装 exe）→ `nssm set <svc> AppParameters "<args>"` → 再 set 其余项。
   Python 安装器装完会**校验 AppParameters 非空**，空则中止并报错（不会再产出空壳服务）。
5. **改文件/`git reset` 报 Permission denied**：某个还开着的 PowerShell 窗口跑过该 `.ps1` 后会
   **一直持有文件句柄**（删除拒绝锁）。**关掉那个窗口**（锁随进程释放）再改。
6. **`nssm get` 输出是 UTF-16**：字符串里夹 `\x00`，解析前先剥 NUL（脚本已处理）。

---

## 6. NSSM 解析与旧脚本说明

NSSM 解析顺序：`--nssm-path` > PATH 上的 `nssm` > `scripts\bin\nssm.exe` >
自动从 nssm.cc 下载 2.24 到 `scripts\bin`（离线环境可手动放入 `scripts\bin\nssm.exe`）。

> 旧 PowerShell 安装器（`install-prod-service.ps1` / `uninstall-prod-service.ps1`）已在本提交中
> **移除**——其功能（含 K12 默认与 NSSM 加固）由 Python 版完整覆盖，且规避了 PowerShell 的
> `$Args` 保留变量、`$ErrorActionPreference` 把原生 stderr 当终止异常等易踩坑点。
> `scripts/start-prod.ps1`（进程级启动，非服务化）仍保留，未受影响。
