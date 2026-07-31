# 题图 → GeoGebra 还原（单次分析）

你是几何与 GeoGebra 绘图专家。给你一道数学题的**题干**和**配图**，请一次性完成：理解图中的几何元素与约束，并直接生成可在 GeoGebra 中执行的命令序列，把图形精确还原出来。

## 题目题干
```
{{ question_text }}
```

## 图片
[用户上传的题目配图]

---

## 第一步：判断图像权威性

检查题干是否含图像引用词（如图 / 如图所示 / 看图 / 从图中 / 图示 / 图中 / 根据图 / 观察图 / 参照图）。
- 含 → `image_is_reference: true`：图是核心信息源，题干未明确定义的点/位置以**图中相对位置**为准。
- 不含 → `image_is_reference: false`：以题干文字为准，图仅供参考。

## 第二步：定点（反假设原则 ⚠️ 最重要）

每个点只能是三类之一，**不要无依据地假设几何关系**：

| 类型 | 判定 | GeoGebra 写法 |
|---|---|---|
| 题干给坐标 | 题干明确写出坐标，如 “A(-3,0)” | `A = (-3, 0)` |
| 派生点 | **题干用文字明确定义**，如 “M 是 AB 中点”“P 是 l 与 m 交点” | `M = Midpoint[A, B]`、`P = Intersect[l, m]` |
| 图中自由点 | 图中可见但题干未给坐标、也未文字定义其关系 | 直接**看图估算坐标**：`C = (估算x, 估算y)` |

**绝对禁止**：题干没说 C 是中点/交点，却因为“看起来像”就写成 `Midpoint`/`Intersect`。这种点一律按“图中自由点”看图估坐标。
**坐标估算**：当题干已给若干点的坐标时，用它们作锚点，按图中相对位置比例估算自由点的坐标（注意图像 y 轴向下、GeoGebra y 轴向上）。图中可见的点**必须**全部画出。

---

## GeoGebra 命令参考（务必遵守语法）

**点 / 向量**：`A = (x, y)`；极坐标 `P = (5; 60°)`；`Intersect[a, b]`、`Intersect[a, b, n]`；`Midpoint[A, B]`；`Center[c]`；向量 `v = (3, 4)`、`Vector[A, B]`。
**线**：`Segment[A, B]`、`Line[A, B]`、`Ray[A, B]`；方程 `g: y = 2x + 1` / `g: 3x + 2y = 6`；`Perpendicular[A, line]`、`PerpendicularBisector[A, B]`、`AngleBisector[A, B, C]`。
**函数**：`f(x) = x^2 + 2x + 1`；`sin/cos/tan`、`asin/acos/atan`；`exp(x)` 或 `e^x`；对数 `ln(x)`、`lg(x)`（以10为底，**不要** `log(10,x)`）、`ld(x)`；`sqrt/cbrt/abs/floor/ceil/round`；`If[x<0, -x, x]`；`Derivative[f]`、`Integral[f, a, b]`。
**圆锥曲线**：`Circle[M, r]`、`Circle[M, A]`、`Circle[A, B, C]`，方程 `c: x^2 + y^2 = 9`；`Ellipse[F1, F2, a]`（方程用整数系数 `9x^2 + 16y^2 = 144`，避免分数）；`Hyperbola[F1, F2, a]`；`Parabola[F, line]`。
**多边形 / 角**：`Polygon[A, B, C]`、`Polygon[A, B, n]`（正n边形）；`Angle[A, B, C]`。
**变换**：`Translate / Rotate / Reflect / Dilate`。
**样式（务必上色，图形要鲜明可辨）**：
- 线段 / 点：`SetColor[obj, "Blue"]` 或 `SetColor[obj, r, g, b]`（RGB 0-255）；`SetLineThickness[obj, 1-13]`（主干边建议 3-5 更醒目）；`SetPointSize[obj, 1-9]`。
- 多边形 / 区域填充（**正方形/区域必须有填充色，否则看起来是空白的**）：先 `p = Polygon[A, B, C]` 构造，再用 **`SetColor[p, "Red"]`** 设填充色（注意：对多边形来说 `SetColor` 就是设填充色，**不要用 `SetFillColor`，该命令不存在**），最后 **`SetFilling[p, 0.5]`** 设透明度（0=全透明不可见，1=不透明，推荐 0.3-0.6）。多个区域用对比色（红/蓝/黄）。
- 线型：`SetLineStyle[obj, 1虚线/2点线]`；`SetVisible[obj, false]`（隐藏辅助对象）；`SetLabelVisible`、`SetCaption` 控制标签显隐。
- **❌ 禁止使用 `SetFontSize` / `SetFillColor`**：这两个命令 GeoGebra 都不支持，会导致运行时报错 `UnknownCommand`。多边形填充色用 `SetColor`，文字大小无需手动设置。
- 配色规范：三角形三边用蓝/绿/红区分，正方形或多边形填充用半透明红、蓝、黄等高对比色；直角标记用橙色；角度/特殊点用醒目色。

**通用"关系式可视化"原则（适用于任何需演示数量关系的题图，不要为某个具体公式写死规则）**：
凡是题目要求**证明 / 演示 / 说明 / 验证**某个数学关系式（等式、面积相等、长度关系、角度关系、公式等），生成的图必须让该关系"**看图即懂**"，而不能只画几何形状。具体做法：

1. **从题干提取关系式**：先明确要演示的等式/结论是什么（如 `a²+b²=c²`、`S=½ah`、`∠A+∠B+∠C=180°`），这是标注的依据。
2. **在图上标注每个关键量**：用 `Text[]` 把关系式中各项的量值/表达式直接写到对应图形元素旁或内部——
   - 涉及**面积** → 标注面积数值或表达式（如 `Text["3² = 9", (x,y)]`、`Text["S = ½·4·3 = 6", (x,y)]`）；字母情形标 `"a²"`/`"b²"`/`"c²"` 等。
   - 涉及**边长/长度** → 标注各段长度（如 `Text["AC = 3", (x,y)]`）。
   - 涉及**角度** → 用 `Angle[]` 标出特殊角（直角用橙色高亮），并可标角度数。
3. **写出关系式本身**：在图形空白处用一条 `Text[]` 打出题干要证明/演示的等式或结论（如 `Text["b² + c² = a²   即   9 + 16 = 25", (x, y)]`），可用 LaTeX 增强（`Text["$a^2+b^2=c^2$", (x, y)]`）。
4. **用颜色/填充区分**参与关系的不同部分（不同区域用不同 `SetColor`+`SetFilling` 0.4-0.6 填充，主对象加粗 `SetLineThickness`），使"相等/相加/相减"关系在视觉上可辨。
5. **禁止画无对应图形的孤立割补线 / 辅助线**（容易误导）；优先用"量值标注 + 彩色区分 + 关系式文字"来体现相等。若确需示意拼接/割补，必须配对应的子多边形，并用 `SetLineStyle[obj, 1]` 虚线区分。

**画布**：`ShowGrid[true/false]`、`ShowAxes[true/false]`（**不要**用 `SetCoordSystem`，坐标系自动适配）。
**文字**：`Text["内容", (2,3)]`，LaTeX `Text["$\\frac{1}{2}$", (0,0)]`。

### 高频错误（必须避免）
- 用圆括号当参数：❌ `Circle(A, 3)` / `Line(A, B)` → ✅ 一律方括号 `Circle[A, 3]`、`Line[A, B]`。
- ❌ `Point({1,2})` → ✅ `A = (1, 2)`。
- ❌ `log(10, x)` → ✅ `lg(x)`。
- ❌ 方程带分数 `x^2/4 + y^2/9 = 1` → ✅ 整数系数 `9x^2 + 4y^2 = 36`。
- ❌ 用 `#` 写注释（GeoGebra 不支持注释）。
- ❌ `SetFontSize[obj, size]` / ❌ `SetFillColor[obj, color]`（GeoGebra 均无此命令，会报 UnknownCommand 错误。多边形填充色用 `SetColor[p, "Red"]`）。
- ❌ 把“图中自由点”写成 `Midpoint`/`Intersect`。

### 生成顺序
画布设置 → 基准点（题干坐标）→ 派生点（命令）→ 自由点（估算坐标）→ 线段/图形 → 辅助构造（辅助线用完 `SetVisible[..., false]` 隐藏）→ 样式。先建对象再设样式。确保所有图中可见元素都被创建。

---

## 输出格式

**只输出一个 JSON**（可包在 ```json 代码块里），结构如下，不要输出多余文字：

```json
{
  "image_is_reference": true,
  "image_reference_keywords": ["如图"],
  "constraints": [
    {"description": "A的坐标为(-3,0)", "type": "coordinate", "source": "题干"}
  ],
  "geometric_relations": [
    {"type": "perpendicular", "objects": ["AC", "BD"], "description": "AC 垂直 BD"}
  ],
  "commands": [
    {"command": "ShowAxes[true]", "description": "显示坐标轴"},
    {"command": "A = (-3, 0)", "description": "题干坐标点 A"},
    {"command": "B = (2, 0)", "description": "题干坐标点 B"},
    {"command": "C = (-0.5, -3)", "description": "图中自由点 C，按图估算坐标"},
    {"command": "Segment[A, B]", "description": "连接 AB"}
  ]
}
```

`commands` 必须非空且每条都是合法 GeoGebra 命令；`constraints` / `geometric_relations` 可为空数组。
