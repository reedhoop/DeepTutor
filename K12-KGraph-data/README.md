# K12-KGraph 数据（内嵌副本 / vendored copy）

本目录是 **K12-KGraph** 知识图数据集的一份**内嵌副本**，随 `reedhoop/DeepTutor`
fork 一同分发，免去单独 clone 外部仓库的步骤。

---

## 1. 数据来源 / Provenance

- **原始仓库（GitHub，含两份许可文件）**：[haolpku/K12-KGraph](https://github.com/haolpku/K12-KGraph)
  —— 仓库内含 `LICENSE`（**CC BY-NC-SA 4.0**，覆盖数据集 / 知识图谱 / K12-Bench / K12-Train）
  与 `LICENSE-CODE`（**MIT**，覆盖项目源代码 / 脚本 / 工具代码）。
- **数据集镜像（HuggingFace）**：[lhpku20010120/K12-KGraph](https://huggingface.co/datasets/lhpku20010120/K12-KGraph)
  （国内镜像：`https://hf-mirror.com/datasets/lhpku20010120/K12-KGraph`；另有 `anonymous-K12/K12-KGraph` 镜像）
- **代码 / 构建流水线（GitHub）**：[haolpku/K12-Dataset](https://github.com/haolpku/K12-Dataset)
  （注意库名是 **K12-Dataset**，不是 K12-KGraph；该部分协议为 MIT，与本目录数据无关）
- **项目主页**：<https://haolpku.github.io/K12-KGraph-page/>
- **论文**：*K12-KGraph: A Curriculum-Aligned Knowledge Graph for Benchmarking
  and Training Educational LLMs*，arXiv: [2605.09635](https://arxiv.org/abs/2605.09635)
- **原始教材来源**：本数据集构建自人民教育出版社（PEP）K-12 官方教材，
  涵盖数学、物理、化学、生物（小学 / 初中 / 高中）。

## 2. 授权协议 / License ⚠️（务必阅读）

| 内容 | 许可文件 | 协议 | 关键约束 |
|---|---|---|---|
| **数据集 / 知识图谱（即本目录内容）** | 上游 `LICENSE` | **CC BY-NC-SA 4.0** | **署名（BY）+ 非商业（NC）+ 相同方式共享（SA）**；**不可商用**，商业化需另谈授权 |
| **代码 / 构建流水线（K12-Dataset）** | 上游 `LICENSE-CODE` | **MIT** | 可任意修改、商用，保留版权声明即可（**本目录未包含其代码，MIT 与本副本无关**） |

**对本内嵌副本的含义：**

- 📌 **本副本只含数据集（K12-KGraph 图谱），不含任何上游代码**。因此：
  - 约束本副本的协议是 **CC BY-NC-SA 4.0**（上游 `LICENSE` 文件）；
  - 上游 `LICENSE-CODE`（MIT）仅约束其**源代码 / 脚本**，与本目录内容无关。
- ✅ **允许再分发**：CC BY-NC-SA 4.0 明确允许共享与再分发。随本仓库（无论私有或公开）
  携带这份数据副本**合规**，前提是满足以下三点：
  1. **署名（BY）**：引用北京大学（PKU）原项目 `haolpku/K12-KGraph` 与论文
     *K12-KGraph: A Curriculum-Aligned Knowledge Graph...*（arXiv:2605.09635）；
  2. **非商业（NC）**：**本项目明确为非商业用途**（学术研究 / 个人非盈利实验 / 高校课题），
     不用于任何商业化产品、付费教育 SaaS 或商用 AI 助教；
  3. **相同方式共享（SA）**：若对本数据做清洗 / 重构、衍生出新图谱，衍生数据集
     仍须以 CC BY-NC-SA 4.0 开源。
- ❌ **禁止商用**：任何商业化产品 / 服务 / 部署，**不可直接使用原始数据集**，
  须就数据集授权与上游（PKU 团队）另行书面协商。

## 3. 本目录包含 / 不含

DeepTutor 运行时**只读取**以下两个子目录（约 16MB）：

| 路径 | 内容 |
|---|---|
| `K12-KGraph/global_KG/` | 全局图谱拓扑：`nodes.json` + `edges.json`（约 23k 边） |
| `K12-KGraph/subject_specific_KG/` | 4 个学科 JSON：`biology` / `chemistry` / `math` / `physics`（知识点节点 + 章节树） |

**未包含**（上游仓库有，但本项目不需要，故未 vendor）：
`K12-Bench`、`K12-Train`、`SFT-Baselines`、`afterclass_exercises/`、
以及上游根 `README.md`。

> 注：`node_vectors.json`（~232MB 语义向量缓存）**不是**本目录内容，它由
> DeepTutor 在首次语义检索时于 `data/knowledge_bases/k12_kg/` 本地自动生成
> （需可用 embedding 端点），请勿将其提交进本目录。

## 4. 更新本副本

数据集有新版本时，重新执行：

```bash
# 从上游拉最新，再同步到本目录（仅同步两个用到的子目录）
git clone --depth 1 https://hf-mirror.com/datasets/lhpku20010120/K12-KGraph /tmp/k12kg
rm -rf K12-KGraph-data/K12-KGraph/global_KG K12-KGraph-data/K12-KGraph/subject_specific_KG
cp -r /tmp/k12kg/K12-KGraph/global_KG K12-KGraph-data/K12-KGraph/
cp -r /tmp/k12kg/K12-KGraph/subject_specific_KG K12-KGraph-data/K12-KGraph/
```
