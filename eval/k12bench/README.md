# K12-KGraph 评测集（Phase 5 / E6）

本目录是 K12-KGraph 接入 DeepTutor 的**离线确定性评测集**，用于取代过去手工「出没出图 / 概念卡渲染对不对」的冒烟测试，提供可复现、可进 CI 的回归保证。

## 为什么是离线集，而不是上游 K12-Bench？

原方案（E6）提议复用上游 MIT 的 `eval/` runner 跑 K12-Bench。但：

1. 本 fork 里**没有**上游的 `eval/` runner；
2. K12-Bench 是外部数据集，沙箱无法联网拉取，也没有训练栈（E8 K12-Train 同理受限）。

因此这里用一份**自包含的确定性评测集**覆盖我们这一层（课程知识图谱解析 / `curriculum_knowledge` 工具 / 苏格拉底织入）的回归价值。后续若要增强，可在此基础上加一条「LLM 评判」轨道（见下）。

## 覆盖内容

- **精确匹配（exact）**：定理 / 概念名称直接命中，如 `勾股定理`、`一次函数`、`欧姆定律`。
- **子串 / 单候选匹配**：如 `整式加减`、`勾股定理逆定理`。
- **前置知识链路回归**：断言多个前置概念 id 出现在结果里（`prereqs_subset`），防止图谱拓扑回退。
- **学科消歧（P1-3）**：`函数` 在 `subject=physics` 下应无匹配；`勾股定理` 在 `subject=math` 下应精确命中。
- **歧义负例**：`三角形内角和`、`酸碱中和` 不应臆测——必须返回「未确定 / 候选」而非错误概念。

所有 `expect` 均从**真实索引探针**导出，跑 `run.py` 当前应 100% 通过。

## 运行

```bash
# 从仓库根目录
python eval/k12bench/run.py            # 跑全部用例，失败时退出码 1
python eval/k12bench/run.py --quiet    # 仅打印失败
```

无需 LLM、无需联网、无需 embedding —— 纯图遍历 / JSON 查表，确定性可测。

## 进 CI

`tests/services/test_k12bench_evalset.py` 以 `cases.jsonl` 为**唯一数据源**做参数化，随 `pytest` 一起跑，保证评测集本身不被漏测。

## 扩展评测集

直接在 `cases.jsonl` 追加一行 JSON：

```json
{"id":"kb-030","query":"一元二次方程","subject":null,"expect":{"confident":true,"concept_id":"<从探针得到的真实 id>","subject_prefix":"math"},"note":"..."}
```

约定：

- `expect.confident`：期望是否「确定命中」（用工具的 `_is_confident` 门控判定）。
- `expect.concept_id`：可选，精确断言解析到的节点 id。
- `expect.subject_prefix`：可选，断言 id 前缀（学科），**不要臆测学科**，以图谱实际归因为准。
- `expect.prereqs_subset`：可选，这些前置 id 必须出现在结果中。
- 负例用 `"confident": false, "concept_id": null`。

加完用 `python eval/k12bench/run.py` 验证通过，再提交。

## 未来增强（可选）

- **LLM 评判轨道**：对每条用例额外跑一次真实对话，断言导师确实调用了 `curriculum_knowledge` 工具 / 注入了 `course_kb` seed（受 API key 与联网限制，默认跳过，可用 `--live` 显式开启）。
- **教材依据轨道**：断言 `evidence_data` 返回的教材原文非空，覆盖「教材依据」展示回归。
