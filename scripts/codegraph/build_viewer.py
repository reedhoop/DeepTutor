"""Build a self-contained viewer HTML for the DeepTutor fork code-graph.

Reads reports/codegraph/custom_layer.json and inlines it into
reports/codegraph/index.html as ``window.__GRAPH_DATA__`` so the page works
when opened directly via file:// (no fetch/CORS issues). The page still falls
back to fetch() if the inline data is absent (e.g. served version).

IMPORTANT: the template's only <script> block holds BOTH the data assignment
and the rendering app code. So we must strip ONLY the assignment statement(s)
(never the <script> tag / app code), then re-inject one fresh assignment right
after the first <script> tag.
"""

import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(HERE))
HTML = os.path.join(REPO, "reports", "codegraph", "index.html")
DATA = os.path.join(REPO, "reports", "codegraph", "custom_layer.json")

# Matches `window.__GRAPH_DATA__ = {...};` (JSON has no ';' inside, so the
# non-greedy match stops at our appended ';'). Removes stale assignments.
DATA_STMT_RE = re.compile(r"window\.__GRAPH_DATA__\s*=\s*.*?;", re.DOTALL)

SCRIPT_OPEN = "<script>"


def main():
    with open(DATA, encoding="utf-8") as f:
        payload = json.load(f)
    data_js = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))

    with open(HTML, encoding="utf-8") as f:
        html = f.read()

    # 1) Strip every prior data assignment (keeps <script> tag + app code).
    html = DATA_STMT_RE.sub("", html)

    # 2) Inject one fresh assignment right after the first <script> tag.
    idx = html.find(SCRIPT_OPEN)
    if idx == -1:
        print("ERROR: <script> tag not found in index.html")
        sys.exit(1)
    inject = "\nwindow.__GRAPH_DATA__ = " + data_js + ";\n"
    html = html[: idx + len(SCRIPT_OPEN)] + inject + html[idx + len(SCRIPT_OPEN) :]

    with open(HTML, "w", encoding="utf-8") as f:
        f.write(html)

    size = os.path.getsize(HTML)
    print("built self-contained viewer: %s (%.2f MB, inline nodes=%d edges=%d)" %
          (HTML, size / 1e6, len(payload["nodes"]), len(payload["edges"])))


if __name__ == "__main__":
    main()
