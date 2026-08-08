// Single source of truth for math detection + unified KaTeX options.
//
// Historically two divergent "is this math?" definitions existed:
//   1. MarkdownRenderer.detectMathContent — too strict; it missed pure inline
//      math such as `$x=5$`, `$3$`, `$α$`, `$x>0$`, so those silently fell
//      through to the Simple renderer (no KaTeX).
//   2. markdown-display.MATH_SPAN_REGEX — the correct "tight" rule, but it was
//      duplicated privately and never reused by the dispatcher.
// Both consumers now import from here so the heuristic can never drift apart,
// guaranteeing identical math detection across chat / textbook / error-book /
// variant-exercise rendering paths.

// Display math (\[…\], \(…\), $$…$$) plus single-dollar inline math ($…$).
// The inline form mirrors remark-math's "tight" rule — no space just inside the
// delimiters — so prose currency like "$5 and $10" is not swallowed, while real
// inline math ($x = 5$) is detected and rendered with KaTeX.
const MATH_SPAN_REGEX_GLOBAL =
  /\\\[[\s\S]*?\\\]|\\\([\s\S]*?\\\)|\$\$[\s\S]*?\$\$|\$(?!\s)(?:\\.|[^$\n])*?(?<!\s)\$/g;

// Global copy — safe for `.replace()`-based masking (resets lastIndex per call).
export const MATH_SPAN_REGEX = MATH_SPAN_REGEX_GLOBAL;

// Non-global copy (built from the same source) for boolean `.test()` detection.
// A bare global regex would share mutable `lastIndex` state across call sites,
// so we always detect with a fresh, non-global instance.
const MATH_DETECT_REGEX = new RegExp(MATH_SPAN_REGEX_GLOBAL.source);

// Opening-token fast path. Streaming markdown must upgrade Simple→Rich the
// moment an opening token appears and never downgrade back (monotonic), so the
// partial `$$`, `\(`, `\[` are matched immediately rather than waiting for the
// closing delimiter. A single `$` inline span still needs a matched pair.
const OPENING_TOKEN_REGEX = /(^|[^\\])\$\$|\\\(|\\\[/;

export function detectMathContent(content: string): boolean {
  if (!content) return false;
  if (OPENING_TOKEN_REGEX.test(content)) return true;
  return MATH_DETECT_REGEX.test(content);
}

// Unified KaTeX / rehype-katex options. Passing the same object on every formula
// path guarantees identical rendering — shared macros, error tolerance, and CJK
// friendliness. `throwOnError:false` keeps one malformed formula from blanking
// the whole chat message / exercise card, which is essential for K12 robustness.
export const KATEX_OPTIONS = {
  throwOnError: false,
  errorColor: "#cc0000",
  strict: false,
  trust: false,
  // Common notation shortcuts used in Chinese K12 math. Adding them here (rather
  // than ad-hoc in prompts) keeps every path's macro set identical.
  macros: {
    "\\RR": "\\mathbb{R}",
    "\\NN": "\\mathbb{N}",
    "\\ZZ": "\\mathbb{Z}",
    "\\QQ": "\\mathbb{Q}",
    "\\CC": "\\mathbb{C}",
    "\\dd": "\\,\\mathrm{d}",
  },
};
