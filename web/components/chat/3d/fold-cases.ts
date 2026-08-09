/**
 * ER-9 folding cases — "平面智能长成立体" 启发式案例库.
 *
 * 每个案例定义若干刚性面片：`foldedVerts` 给出面片在折叠体上的 3D 顶点
 * （数据驱动，几何量由 `computeFaceGeometry` 在运行时计算），`flat` 给出
 * 展开（平面）姿态的摆放中心与平面内旋转。动画把每个面从 flat 位姿
 * 插值到 folded 位姿 —— 视觉即"平面图形翻折成 3D 体"。新增案例 = 新增
 * 一条数据，无需改渲染代码。
 */

export interface FoldFace {
  id: string;
  /** 折叠态顶点（右手系，z 向上为体高方向）。多边形按顶点序扇状三角化。 */
  foldedVerts: [number, number, number][];
  /** 展开态：平面 (x, y) 摆放中心 + 平面内绕 Y 轴旋转（度，0 = 面正对观察者）。 */
  flat: { x: number; y: number; ry?: number };
  /** 面片配色（three Color 字符串）。 */
  color: string;
  /** 翻折顺序（stagger）：0 先动，越大越晚。 */
  order: number;
}

export interface FoldCase {
  id: string;
  nameZh: string;
  nameEn: string;
  /** 展开图上底面形状（仅用于 UI 提示文案）。 */
  baseShape: "square" | "triangle" | "rect";
  hintZh: string;
  hintEn: string;
  faces: FoldFace[];
}

const C = {
  bottom: "#8b9dc3",
  sideA: "#f2a65a",
  sideB: "#7ac9a7",
  sideC: "#e58fb1",
  sideD: "#9f8be8",
  top: "#f6d365",
};

// 等边三角形（边长 1）顶点，z=0 平面。
const EQ_A: [number, number, number] = [-0.5, -0.2887, 0];
const EQ_B: [number, number, number] = [0.5, -0.2887, 0];
const EQ_C: [number, number, number] = [0, 0.5774, 0];

export const FOLD_CASES: FoldCase[] = [
  {
    id: "cube",
    nameZh: "正方形 → 正方体",
    nameEn: "Square → Cube",
    baseShape: "square",
    hintZh: "十字展开图：底面固定，四个侧面沿折痕立起，顶面最后盖上。",
    hintEn: "Cross net: base fixed, four sides fold up along the creases, top closes last.",
    faces: [
      {
        id: "bottom",
        color: C.bottom,
        order: 0,
        flat: { x: 0, y: 0 },
        foldedVerts: [
          [-0.5, -0.5, 0],
          [0.5, -0.5, 0],
          [0.5, 0.5, 0],
          [-0.5, 0.5, 0],
        ],
      },
      {
        id: "front",
        color: C.sideA,
        order: 1,
        flat: { x: 0, y: 1 },
        foldedVerts: [
          [-0.5, 0.5, 0],
          [0.5, 0.5, 0],
          [0.5, 0.5, 1],
          [-0.5, 0.5, 1],
        ],
      },
      {
        id: "back",
        color: C.sideB,
        order: 1,
        flat: { x: 0, y: -1 },
        foldedVerts: [
          [-0.5, -0.5, 0],
          [-0.5, -0.5, 1],
          [0.5, -0.5, 1],
          [0.5, -0.5, 0],
        ],
      },
      {
        id: "left",
        color: C.sideC,
        order: 1,
        flat: { x: -1, y: 0, ry: 90 },
        foldedVerts: [
          [-0.5, -0.5, 0],
          [-0.5, 0.5, 0],
          [-0.5, 0.5, 1],
          [-0.5, -0.5, 1],
        ],
      },
      {
        id: "right",
        color: C.sideD,
        order: 1,
        flat: { x: 1, y: 0, ry: -90 },
        foldedVerts: [
          [0.5, -0.5, 0],
          [0.5, -0.5, 1],
          [0.5, 0.5, 1],
          [0.5, 0.5, 0],
        ],
      },
      {
        id: "top",
        color: C.top,
        order: 2,
        flat: { x: 0, y: 2 },
        foldedVerts: [
          [-0.5, -0.5, 1],
          [0.5, -0.5, 1],
          [0.5, 0.5, 1],
          [-0.5, 0.5, 1],
        ],
      },
    ],
  },
  {
    id: "rect_prism",
    nameZh: "矩形 → 长方体",
    nameEn: "Rect → Rectangular Prism",
    baseShape: "rect",
    hintZh: "长 1.2 × 宽 0.8 × 高 0.6：四周立起后顶面盖上。",
    hintEn: "1.2 × 0.8 × 0.6 prism: sides fold up, top closes.",
    faces: [
      {
        id: "bottom",
        color: C.bottom,
        order: 0,
        flat: { x: 0, y: 0 },
        foldedVerts: [
          [-0.6, -0.4, 0],
          [0.6, -0.4, 0],
          [0.6, 0.4, 0],
          [-0.6, 0.4, 0],
        ],
      },
      {
        id: "front",
        color: C.sideA,
        order: 1,
        flat: { x: 0, y: 0.9 },
        foldedVerts: [
          [-0.6, 0.4, 0],
          [0.6, 0.4, 0],
          [0.6, 0.4, 0.6],
          [-0.6, 0.4, 0.6],
        ],
      },
      {
        id: "back",
        color: C.sideB,
        order: 1,
        flat: { x: 0, y: -0.9 },
        foldedVerts: [
          [-0.6, -0.4, 0],
          [-0.6, -0.4, 0.6],
          [0.6, -0.4, 0.6],
          [0.6, -0.4, 0],
        ],
      },
      {
        id: "left",
        color: C.sideC,
        order: 1,
        flat: { x: -1, y: 0, ry: 90 },
        foldedVerts: [
          [-0.6, -0.4, 0],
          [-0.6, 0.4, 0],
          [-0.6, 0.4, 0.6],
          [-0.6, -0.4, 0.6],
        ],
      },
      {
        id: "right",
        color: C.sideD,
        order: 1,
        flat: { x: 1, y: 0, ry: -90 },
        foldedVerts: [
          [0.6, -0.4, 0],
          [0.6, -0.4, 0.6],
          [0.6, 0.4, 0.6],
          [0.6, 0.4, 0],
        ],
      },
      {
        id: "top",
        color: C.top,
        order: 2,
        flat: { x: 0, y: 1.8 },
        foldedVerts: [
          [-0.6, -0.4, 0.6],
          [0.6, -0.4, 0.6],
          [0.6, 0.4, 0.6],
          [-0.6, 0.4, 0.6],
        ],
      },
    ],
  },
  {
    id: "triangular_prism",
    nameZh: "三角形 → 三棱柱",
    nameEn: "Triangle → Triangular Prism",
    baseShape: "triangle",
    hintZh: "两个等边三角形底面 + 三个矩形侧面，沿三条底边翻折。",
    hintEn: "Two equilateral triangle bases plus three rectangular sides folding up.",
    faces: [
      {
        id: "bottom",
        color: C.bottom,
        order: 0,
        flat: { x: 0, y: 0 },
        foldedVerts: [EQ_A, EQ_B, EQ_C],
      },
      {
        id: "s1",
        color: C.sideA,
        order: 1,
        flat: { x: 0, y: -1 },
        foldedVerts: [
          [-0.5, -0.2887, 0],
          [0.5, -0.2887, 0],
          [0.5, -0.2887, 1],
          [-0.5, -0.2887, 1],
        ],
      },
      {
        id: "s2",
        color: C.sideB,
        order: 1,
        flat: { x: -1.2, y: 0.4, ry: -20 },
        foldedVerts: [
          [-0.5, -0.2887, 0],
          [0, 0.5774, 0],
          [0, 0.5774, 1],
          [-0.5, -0.2887, 1],
        ],
      },
      {
        id: "s3",
        color: C.sideC,
        order: 1,
        flat: { x: 1.2, y: 0.4, ry: 20 },
        foldedVerts: [
          [0, 0.5774, 0],
          [0.5, -0.2887, 0],
          [0.5, -0.2887, 1],
          [0, 0.5774, 1],
        ],
      },
      {
        id: "top",
        color: C.top,
        order: 2,
        flat: { x: 0, y: 1.2 },
        foldedVerts: [
          [-0.5, -0.2887, 1],
          [0.5, -0.2887, 1],
          [0, 0.5774, 1],
        ],
      },
    ],
  },
  {
    id: "square_pyramid",
    nameZh: "正方形 → 四棱锥",
    nameEn: "Square → Square Pyramid",
    baseShape: "square",
    hintZh: "正方形底面 + 四个等腰三角形侧面，顶点在中心上方收拢。",
    hintEn: "Square base with four isosceles triangles meeting at the apex.",
    faces: [
      {
        id: "bottom",
        color: C.bottom,
        order: 0,
        flat: { x: 0, y: 0 },
        foldedVerts: [
          [-0.5, -0.5, 0],
          [0.5, -0.5, 0],
          [0.5, 0.5, 0],
          [-0.5, 0.5, 0],
        ],
      },
      {
        id: "f_front",
        color: C.sideA,
        order: 1,
        flat: { x: 0, y: 1 },
        foldedVerts: [
          [-0.5, 0.5, 0],
          [0.5, 0.5, 0],
          [0, 0, 0.7],
        ],
      },
      {
        id: "f_back",
        color: C.sideB,
        order: 1,
        flat: { x: 0, y: -1 },
        foldedVerts: [
          [-0.5, -0.5, 0],
          [0, 0, 0.7],
          [0.5, -0.5, 0],
        ],
      },
      {
        id: "f_left",
        color: C.sideC,
        order: 1,
        flat: { x: -1, y: 0, ry: 90 },
        foldedVerts: [
          [-0.5, -0.5, 0],
          [-0.5, 0.5, 0],
          [0, 0, 0.7],
        ],
      },
      {
        id: "f_right",
        color: C.sideD,
        order: 1,
        flat: { x: 1, y: 0, ry: -90 },
        foldedVerts: [
          [0.5, -0.5, 0],
          [0, 0, 0.7],
          [0.5, 0.5, 0],
        ],
      },
    ],
  },
];

/** 运行时按 id 找案例；未知 id 回落 cube（并保留原始 id 供提示）。
 *  容忍 ``er3d:cube`` 前缀与围栏首词多余内容。 */
export function resolveFoldCase(id: string | null | undefined): FoldCase {
  const want =
    (id || "")
      .trim()
      .toLowerCase()
      .replace(/^er3d:/, "")
      .split(/\s+/)[0] || "cube";
  return FOLD_CASES.find((c) => c.id === want) ?? FOLD_CASES[0];
}

export interface FaceGeometry {
  /** 以面质心为原点的顶点（interleaved xyz）。 */
  localVerts: Float32Array;
  /** 折叠态质心。 */
  centroid: [number, number, number];
  /** 折叠态面法向（单位）。 */
  normal: [number, number, number];
  /** 顶点数。 */
  count: number;
  /** fan 三角化索引。 */
  indices: number[];
}

/** 面法向（右手序）：cross(v1-v0, v2-v0) 归一化。 */
function faceNormal(verts: [number, number, number][]): [number, number, number] {
  const [ax, ay, az] = verts[0];
  const [bx, by, bz] = verts[1];
  const [cx, cy, cz] = verts[2];
  const ux = bx - ax, uy = by - ay, uz = bz - az;
  const vx = cx - ax, vy = cy - ay, vz = cz - az;
  let nx = uy * vz - uz * vy;
  let ny = uz * vx - ux * vz;
  let nz = ux * vy - uy * vx;
  const len = Math.hypot(nx, ny, nz) || 1;
  return [nx / len, ny / len, nz / len];
}

/**
 * 由折叠态顶点构建面片几何：
 * - 质心 = 顶点均值；局部顶点 = 顶点 - 质心（面片刚性，展开/折叠共用同一形状）。
 * - 多边形按 fan 三角化（凸多边形 / 三角形均可）。
 */
export function computeFaceGeometry(verts: [number, number, number][]): FaceGeometry {
  const count = verts.length;
  const cx = verts.reduce((s, v) => s + v[0], 0) / count;
  const cy = verts.reduce((s, v) => s + v[1], 0) / count;
  const cz = verts.reduce((s, v) => s + v[2], 0) / count;
  const local: number[] = [];
  for (let i = 0; i < count; i++) {
    local.push(verts[i][0] - cx, verts[i][1] - cy, verts[i][2] - cz);
  }
  const indices: number[] = [];
  for (let i = 1; i < count - 1; i++) {
    indices.push(0, i, i + 1);
  }
  return {
    localVerts: new Float32Array(local),
    centroid: [cx, cy, cz],
    normal: faceNormal(verts),
    count,
    indices,
  };
}
