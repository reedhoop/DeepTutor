import test from "node:test";
import assert from "node:assert/strict";
import {
  MATH_SPAN_REGEX,
  detectMathContent,
  KATEX_OPTIONS,
} from "../lib/math-render";

// ---------------------------------------------------------------------------
// detectMathContent — must catch PURE inline math that the old heuristic missed
// (no \\cmd, no {}_^): $x=5$, $3$, $α$, $x>0$. These previously fell through to
// the Simple renderer and showed raw LaTeX.
// ---------------------------------------------------------------------------

const SHOULD_DETECT = [
  ["block $$", "$$x^2 + 1 = 0$$"],
  ["block $$ with newline", "$$\n\\frac{a}{b}\n$$"],
  ["\\( \\) inline", "Solve \\(a > 0\\) now"],
  ["\\[ \\] block", "Before \\[x^2\\] after"],
  ["inline single var", "设 $x$ 为未知数"],
  ["inline equation", "解得 $x=5$"],
  ["inline number", "结果是 $3$ 厘米"],
  ["inline greek", "角 $α$ 的度数"],
  ["inline inequality", "当$x>0$时函数递增"],
  ["inline fraction", "面积为 $\\frac{1}{2}ab$"],
  ["inline subscript", "首项为 $a_1$"],
  ["inline mixed with text", "由 $E = mc^2$ 可知"],
];

for (const [label, input] of SHOULD_DETECT) {
  test(`detectMathContent detects: ${label}`, () => {
    assert.equal(detectMathContent(input), true, `expected math in: ${input}`);
  });
}

// ---------------------------------------------------------------------------
// Negative cases — prose that must NOT be upgraded to the Rich (KaTeX) path.
// Currency with a space inside the delimiter is the canonical "tight" rule
// safeguard; so is plain text.
// ---------------------------------------------------------------------------

const SHOULD_NOT_DETECT = [
  ["currency pair", "我用 $5 和 $10 买了两本书"],
  ["single dollar amount", "价格是 $5 元"],
  ["plain prose", "这是一段没有任何公式的普通说明文字"],
  ["empty string", ""],
  ["mentions dollar loosely", "The cost is $5 but not math"],
];

for (const [label, input] of SHOULD_NOT_DETECT) {
  test(`detectMathContent ignores: ${label}`, () => {
    assert.equal(
      detectMathContent(input),
      false,
      `expected NO math in: ${input}`,
    );
  });
}

// ---------------------------------------------------------------------------
// Streaming monotonicity — an opening token ($, \(, \[) must trigger Rich even
// before the closing delimiter arrives, so the renderer never downgrades
// Simple→Rich→Simple mid-stream.
// ---------------------------------------------------------------------------

test("detectMathContent: opening $$ upgrades immediately (partial stream)", () => {
  assert.equal(detectMathContent("计算 $$\\frac"), true);
});

test("detectMathContent: opening \\[ upgrades immediately", () => {
  assert.equal(detectMathContent("看图 \\[x"), true);
});

test("detectMathContent: opening \\( upgrades immediately", () => {
  assert.equal(detectMathContent("令 \\(a"), true);
});

// ---------------------------------------------------------------------------
// MATH_SPAN_REGEX — the masking rule reused by markdown-display must itself
// capture the same inline math the detector catches (single source of truth).
// ---------------------------------------------------------------------------

test("MATH_SPAN_REGEX captures pure inline math spans", () => {
  const matches = "解得 $x=5$ 与 $α$".match(MATH_SPAN_REGEX);
  assert.ok(matches);
  assert.deepEqual(matches, ["$x=5$", "$α$"]);
});

test("MATH_SPAN_REGEX does not swallow spaced currency", () => {
  const matches = "花费 $5 和 $10".match(MATH_SPAN_REGEX);
  assert.equal(matches, null);
});

test("MATH_SPAN_REGEX is global (replace-based masking safe)", () => {
  const input = "已知 $a_1$ 与 $a_2$ 满足";
  const masked = input.replace(MATH_SPAN_REGEX, "🔢");
  assert.ok(masked.includes("🔢 与 🔢"));
  assert.ok(!masked.includes("$a_1$"));
});

// ---------------------------------------------------------------------------
// KATEX_OPTIONS — contract shared by every formula path. Robustness for K12: a
// malformed formula must not throw (throwOnError:false) and the common
// number-set macros must be defined.
// ---------------------------------------------------------------------------

test("KATEX_OPTIONS: tolerant rendering (no throw on error)", () => {
  assert.equal(KATEX_OPTIONS.throwOnError, false);
  assert.equal(KATEX_OPTIONS.strict, false);
});

test("KATEX_OPTIONS: number-set macros present", () => {
  for (const m of ["\\RR", "\\NN", "\\ZZ", "\\QQ", "\\CC"]) {
    assert.ok(
      m in KATEX_OPTIONS.macros,
      `expected macro ${m} in KATEX_OPTIONS.macros`,
    );
  }
});
