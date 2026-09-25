# page-parity

**cross-page consistency** + **layout overflow** auditor for static sites.  
Two-second diagnosis: "Is this page like the others? Is anything spilling out?"

---

## When you'd use it

- Just finished a site redesign — want a quick sanity check before showing anyone.
- Not sure if every page still has the same menu, footer, tracking code, CSS variables.
- Need a grep-able verdict in CI or local terminal, not a visual diff gallery.

---

## Install

```bash
pipx install page-parity
# or: uv tool install page-parity
```

Requires Python 3.11+ (on 3.9 / 3.10 everything works too, except that reading a
`page-parity.toml` config then needs `pip install tomli`; the built-in checklist needs no
dependency). L2 (overflow) needs Playwright (`playwright install chromium`).

---

## Minimal example (5 lines)

```bash
page-parity check --dir ./my-site
# → {"verdict":"findings","exit_reason":"FINDINGS","codes":["MISSING_ON_PAGE","VALUE_DRIFT"],"counts":{"pages":17,"findings":4},"details_url":"file:///tmp/page-parity-abc123.json"}
# Human: 4 issues — watermark missing on 15 pages, --primary color differs on 3 pages, 2 orphan pages (expected)
```

---

## Real output

**JSON (stdout, single line, ≤400 bytes):**
```json
{"verdict":"findings","exit_reason":"FINDINGS","codes":["MISSING_ON_PAGE","VALUE_DRIFT","ORPHAN_PAGE"],"counts":{"pages":17,"findings":4},"details_url":"file:///tmp/page-parity-x7k9.json"}
```

**Human summary (stderr, 3 sentences max):**
> 17 pages scanned. Watermark missing on 15 pages. `--primary` has 3 different values across pages. 2 orphan pages flagged as expected exceptions (redirect + noindex).

---

## Exit codes

| Code | Meaning |
|------|---------|
| 0 | OK — everything consistent, no overflow |
| 1 | FINDINGS — confirmed inconsistencies or overflow |
| 2 | INDETERMINATE — parse error, no input, browser unavailable |
| 3 | USAGE — bad flags |
| 4 | INTERNAL — bug in page-parity |

---

## When **not** to use it

| Need | Use instead |
|------|-------------|
| Pixel-perfect visual regression | Playwright screenshot diff / BackstopJS |
| Semantic DOM diff with file:line attribution | `Shinyaigeek/qain` (CDP DOMSnapshot + CSS.forcePseudoState) |
| CI gate that blocks deploy | page-parity is **diagnostic only** — it exits 1 on findings, but "no one watches CI" is a false assumption |
| Dynamic SPA routes / JS-heavy pages | L2 only checks static HTML + rendered layout at fixed widths |

---

## What it actually checks

**L1 — Cross-page consistency (stdlib only, ~2s / 17 pages)**
- Required elements present on every page (canonical, OG tags, viewport, favicon, GA, footer text, menu items, watermark, `lang`)
- CSS custom property (`--x: value`) drift across pages (nesting-aware, comment-stripped)
- Orphan pages (zero inbound links), with explicit exception list for intentional cases

**L2 — Layout overflow (Playwright, ~3min / 17 pages × 7 widths)**
- Page-level: `documentElement.scrollWidth > clientWidth + 2px`
- Element-level: any element `scrollWidth > clientWidth + 2px` **even when page doesn't scroll**
- Fixed-position elements obscuring interactive targets (links, buttons)
- Default widths: 320, 360, 390, 430, 768, 1024, 1440

---

## Command reference

```bash
# L1 only (default, no browser)
page-parity check --dir ./site --format json

# L1 + L2 (layout overflow) with custom widths
page-parity check --dir ./site --l1 --l2 --widths 320,768,1440 --format json

# L1 only, explicit
page-parity check --dir ./site --l1 --format json

# L2 only (layout overflow only)
page-parity check --dir ./site --l2 --widths 320,768,1440 --format json

# Run only specific L1 checks (a1=consistency, a2=CSS vars, a3=orphans)
page-parity check --dir ./site --only a1,a3 --format json

# Custom config file
page-parity check --dir ./site --config ./page-parity.toml --format json

# Human-readable output
page-parity check --dir ./site --format human

# Both JSON + human
page-parity check --dir ./site --format both

# Recursive directory scan
page-parity check --dir ./site --recursive --format json

# Input from URL list file
page-parity check --urls urls.txt --format json

# Custom tolerance (pixels) for overflow detection
page-parity check --dir ./site --l2 --tol 5 --format json

# Self-test (validates the tool itself)
page-parity --self-test

# Show JSON schema for output validation
page-parity --schema

# Read full details report
page-parity details file:///path/to/details-xxx.json
```

---

## Configuration

`page-parity.toml` in project root (optional — sensible defaults built in):

```toml
# [[items]] — each entry is one "should look the same everywhere" check
#   kind    = "selector" | "text" | "css_backdrop"
#   scope   = "all" | "min:N" | "any"      (all => any page missing it is a finding)
#   compare = "none" | "attr" | "text" | "set"

[[items]]
id = "canonical"
kind = "selector"
selector = 'link[rel="canonical"]'
scope = "all"
compare = "none"

[[items]]
id = "menu_items"
kind = "selector"
selector = "nav a"
scope = "all"
compare = "set"

# ---------------------------------------------------------------- exceptions
# Deliberate per-page inconsistencies must be listed here WITH a reason so
# they still appear in the report but do not count as failures.
#
# [[expect_exceptions]]
# page = "legacy-redirect.html"
# reason = "HTTP 301 + noindex, deliberately no menu"
```

### Item kinds

| Kind | Use for | Value extraction |
|------|---------|------------------|
| `selector` | DOM elements | `compare=attr` (attribute), `compare=text` (text), `compare=set` (set of texts) |
| `text` | Regex pattern in raw HTML | Presence only |
| `css_backdrop` | Watermark/fixed overlays via CSS | Presence only |

### Scope values

- `"all"` — Every page must have it (default)
- `"min:N"` — At least N pages must have it
- `"any"` — At least one page must have it

### Exceptions

`expect_exceptions` entries require both `page` (path or basename) and `reason` (string). Matched pages are reported but not counted as findings.

---

## Output schema

```json
{
  "verdict": "ok" | "findings" | "indeterminate" | "usage" | "internal",
  "exit_reason": "OK" | "FINDINGS" | "INDETERMINATE" | "USAGE" | "INTERNAL",
  "codes": ["MISSING_ON_PAGE", "VALUE_DRIFT", "ORPHAN_PAGE", ...],
  "counts": {"pages": 17, "findings": 4, "advisories": 2},
  "details_url": "file:///tmp/page-parity-xxx.json"
}
```

- `verdict` is **lowercase**; `exit_reason` is **UPPERCASE**
- `advisories` in `counts` = items flagged as advisory (e.g., `ABSENT_EVERYWHERE`, `CSR_SHELL_DETECTED`, `ENCODING_UNCERTAIN`) — doesn't affect exit code
- `details_url` points to full report with per-page breakdown

---

## Finding codes

| Code | Layer | Meaning |
|------|-------|---------|
| `MISSING_ON_PAGE` | L1 | Required element absent on some pages (scope not met) |
| `VALUE_DRIFT` | L1 | Same CSS var / meta tag / element set has different values |
| `ORPHAN_PAGE` | L1 | Page with zero inbound links (check `expect_exceptions`) |
| `ABSENT_EVERYWHERE` | L1 | Item absent on **every** page — **advisory only**, never affects exit code |
| `CSR_SHELL_DETECTED` | L1 | Empty container detected (menu likely JS-injected) — **advisory** |
| `ENCODING_UNCERTAIN` | L1 | Page encoding detection uncertain — **advisory** |
| `PAGE_OVERFLOW` | L2 | Whole page scrolls horizontally at a test width |
| `ELEMENT_OVERFLOW` | L2 | Element overflows its container (page doesn't scroll) |
| `FIXED_OBSCURES` | L2 | Fixed/sticky element covers a clickable target |
| `PARSE_ERROR` | L1/L2 | HTML/CSS couldn't be parsed |
| `NO_BROWSER` | L2 | Playwright not installed / browser launch failed |

---

## Decision logic

```python
if verdict == "ok":
    # Ship it — everything consistent, no overflow
elif verdict == "findings":
    if "MISSING_ON_PAGE" in codes or "VALUE_DRIFT" in codes:
        # Content/structure inconsistency — fetch details_url for page lists
    if "ORPHAN_PAGE" in codes:
        # Check expect_exceptions in config — some are expected
    if "CSR_SHELL_DETECTED" in codes or "ENCODING_UNCERTAIN" in codes:
        # Advisory only — JS-injected content or encoding uncertainty
    if any(c.endswith("_OVERFLOW") or c == "FIXED_OBSCURES" for c in codes):
        # Layout bug — fetch details_url for selector paths + widths
elif verdict == "indeterminate":
    # Parse error or no browser for L2 — re-run without --l2 or install Playwright
```

---

## 支援範圍與限制

**V1 只支援 SSG/SSR 靜態 HTML**
- 只讀取本地 `.html` 檔案，不會執行 JavaScript
- SPA 路由、JS 注入的選單、Client-side rendered 內容**看不到**
- `--recursive` 只掃描 `.html` 副檔名

**L2 需要 Playwright**
- `pipx inject page-parity playwright` 然後 `playwright install chromium`
- 無瀏覽器時回傳 `NO_BROWSER` (exit code 2, verdict=indeterminate)
- 只載入 `file://` 協定，完全離線、不發網路請求

**不做視覺回歸**
- 無截圖比對、無像素級 diff
- 視覺回歸請用 Playwright/BackstopJS
- 語義 DOM diff 請用 `Shinyaigeek/qain`

**不支援**
- 動態路由 / SPA client-side navigation
- 需要登入/cookie 的頁面
- 外部 URL（L2 會 abort 所有非 file:// 請求）

---

## 常見誤報與如何處理

| 現象 | 原因 | 處理 |
|------|------|------|
| `ORPHAN_PAGE` on index.html | 首頁常沒有內部連結指向 | 在 `expect_exceptions` 加入 `{page="index.html", reason="entry point, no inbound links needed"}` |
| `VALUE_DRIFT` on CSS variable | 不同頁面確實用不同主題色 | 若為設計刻意，調整 `scope` 為 `"min:1"` 或加入例外 |
| `ABSENT_EVERYWHERE` advisory | 整站都沒用該功能（如 watermark） | 此為建議提示，**不影響 exit code**，可忽略或從 checklist 移除 |
| `CSR_SHELL_DETECTED` advisory | 選單容器存在但為空（JS 動態注入） | 此為建議提示，**不影響 exit code**；若為 SPA，改用動態測試工具 |
| `ENCODING_UNCERTAIN` advisory | 頁面編碼偵測不確定 | 確認 HTML 儲存為 UTF-8 並加上 `<meta charset="utf-8">` |
| Clean URLs (無 .html 副檔名) | 連結為 `/about` 而非 `/about.html` | 已支援：解析時會自動補上 `.html` 比對 |
| Cookie 橫幅遮擋連結 | 固定定位元素覆蓋互動目標 | 屬 `FIXED_OBSCURES` advisory；若為 GDPR 必備，加入例外或調整設計 |
| `PARSE_ERROR` | HTML 不合法或編碼問題 | 檢查該頁面編碼為 UTF-8、標籤正確閉合 |

---

## Philosophy

- **Diagnostic, not a gate.** Runs in 2 seconds. Tells you *what* differs. You decide if it matters.
- **No guessing.** Uncertain → `exit 2 INDETERMINATE`. Zero never means "didn't check."
- **Exceptions must be declared.** Intentional differences go in the config with a reason. Silent ignores don't exist.
- **Zero LLM, zero network (L1).** L2 only launches a headless browser to load local files.
- **Agent-first CLI.** JSON on stdout, human on stderr. One call → verdict. Fetch `details_url` only if you need the full list.