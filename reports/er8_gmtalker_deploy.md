# ER-8 数字人形象与嘴型 — GMTalker 部署与接入指南

> 对应报告 ER-8「数字人形象与嘴型」（P3）。本文档说明如何把 DeepTutor
> 的数字人 widget 从「内置 SVG 形象（随 TTS 嘴型）」切换到真实数字人
> **GMTalker**（FunASR 语音识别 + MeloTTS 语音合成 + 嘴型驱动），满足
> 验收「学生语音提问 → 数字人形象语音回答，离线可跑」。

## 一、两条链路，按需选择

| 模式 | 说明 | 资源需求 |
|------|------|----------|
| **builtin（默认）** | 内置 SVG 数字人形象，嘴型随 DeepTutor 现有 TTS（`/api/v1/voice/tts`）播放自动开合（monkey-patch `HTMLMediaElement.prototype.play` 捕获所有音频播放）。已随代码落地，**零额外部署**，离线可跑。 | 无（复用现有 TTS 服务） |
| **iframe（GMTalker）** | 嵌入外部数字人网页（需自行部署 GMTalker），获得真实形象 + 端到端语音问答。 | Docker + **GPU（推荐 ≥4GB 显存）** |

## 二、GMTalker 部署（iframe 模式）

### 1. 拉取镜像并启动

```bash
# 建议先确认 GPU 驱动与 nvidia-container-toolkit 可用
docker pull ghcr.io/GMTalker/gmtalker:latest   # 以官方发布为准

docker run -d --name gmtalker \
  --gpus all \
  -p 8231:8231 \
  -v gmtalker-models:/app/models \
  ghcr.io/GMTalker/gmtalker:latest
```

> 端口 `8231` 与 DeepTutor 其他服务错开（8101 后端 / 3782 前端 / 8200、8118、
> 8230 为解析引擎），避免冲突。

### 2. 首次启动拉取模型

FunASR（语音识别）+ MeloTTS（语音合成）+ 嘴型模型合计约数 GB，首次启动会自动下载
到 `gmtalker-models` 卷；**离线环境需提前在有网机器上 `docker pull` + 预下载模型后
再导入**。

### 3. 验证 GMTalker 自身可用

```bash
curl -s http://127.0.0.1:8231/health   # 期望返回 ok
```

网页入口：`http://127.0.0.1:8231/`（含麦克风授权提示，需允许浏览器使用麦克风）。

## 三、接入 DeepTutor

1. 打开任意对话页，右下角点 **Sparkles** 按钮展开「数字人」面板。
2. 打开「启用数字人」开关。
3. 「形象」下拉选择 **GMTalker / 外部数字人 iframe**。
4. 粘贴 GMTalker 网页地址（如 `http://127.0.0.1:8231/`），点「保存 iframe 地址」。
5. 面板内即嵌入 GMTalker 数字人；学生在 GMTalker 里语音提问，由 FunASR 识别 →
   MeloTTS 合成回答 → 数字人嘴型同步，**全链路离线**。

设置持久化于 `ui.digital_human`（`GET/PUT /api/v1/settings/digital-human`），
前端钩子 `web/hooks/useDigitalHuman.ts` 负责读写与跨页面同步。

## 四、内置形象的嘴型验证（无需 GMTalker）

面板内点「试听（验证嘴型）」——前端调用现有 `POST /api/v1/voice/tts` 播放一句样本，
内置数字人嘴部随语音开合。该机制同时作用于对话中任意 TTS 播报（含助手自动播报），
无需任何部署即可验证「形象 + 嘴型驱动」。

## 五、风险与合规（对应报告）

- **资源**：GMTalker 重基础设施 + GPU；无 GPU 环境请停留在 builtin 模式。
- **声音克隆**：如使用复刻声音能力，需确保被克隆人授权；DeepTutor 侧不提供克隆，
  仅外接 GMTalker，合规责任在部署方。
- **"课本原生人物"**：属内容工程（制作指定形象/声音素材），非技术工程，ROI 低，
  建议仅在确有必要时投入。

## 六、相关代码

- 后端：`deeptutor/api/routers/settings.py`（`DEFAULT_UI_SETTINGS["digital_human"]` +
  `PUT /digital-human`）
- 前端钩子：`web/hooks/useDigitalHuman.ts`
- 前端组件：`web/components/chat/digital/DigitalHumanWidget.tsx`
- 挂载点：`web/app/(workspace)/home/[[...sessionId]]/page.tsx`
