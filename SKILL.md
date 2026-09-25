---
name: page-parity
description: "Check cross-page consistency and layout overflow on static sites."
version: "1.0.0"
author: "j0935586110-lgtm"
license: "MIT"
---

# page-parity Skill

Load this skill when the user asks: **"Check if all pages have the same menu, footer, CSS variables, and no horizontal overflow."**

## Trigger phrases (agent matches these)

- "pages consistent"
- "cross-page consistency"
- "layout overflow"
- "orphan pages"
- "CSS variable drift"
- "menu missing on some pages"
- "horizontal scroll on mobile"

## One-shot invocation

```bash
page-parity check --dir <site-dir> --format json
```

Returns single-line JSON on stdout. Parse `verdict`, `exit_reason`, `codes[]`, `counts{}`, `details_url`.

## Decision matrix

| `verdict` | `exit_reason` | Action |
|-----------|---------------|--------|
| `ok` | `OK` | All consistent, no overflow |
| `findings` | `FINDINGS` | Read `codes[]` → fetch `details_url` for specifics |
| `indeterminate` | `INDETERMINATE` | Re-run without `--l2` or install Playwright |
| — | `USAGE` | Fix flags |
| — | `INTERNAL` | Report bug |

## Finding codes

- `MISSING_ON_PAGE` — required element absent (canonical, OG, menu, watermark, etc.)
- `VALUE_DRIFT` — same CSS var / meta tag has different values across pages
- `ORPHAN_PAGE` — zero inbound links (check config `expect_exceptions`)
- `ABSENT_EVERYWHERE` — item absent on **all** pages (advisory only, no exit code impact)
- `CSR_SHELL_DETECTED` — empty container detected (menu likely JS-injected) — advisory
- `ENCODING_UNCERTAIN` — page encoding detection uncertain — advisory
- `PAGE_OVERFLOW` — page scrolls horizontally at a test width
- `ELEMENT_OVERFLOW` — element overflows container (page doesn't scroll)
- `FIXED_OBSCURES` — fixed/sticky element covers link/button
- `PARSE_ERROR` — HTML/CSS parse failure
- `NO_BROWSER` — Playwright unavailable for L2

## Config (page-parity.toml)

```toml
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

[[expect_exceptions]]
page = "redirect.html"
reason = "301 + noindex"
```

Scope values: `"all"` (every page), `"min:N"` (at least N pages), `"any"` (at least one).

Item kinds: `selector` (DOM), `text` (regex), `css_backdrop` (watermark).
Compare modes: `none`, `attr`, `text`, `set`.

## Performance

- L1 only (default): ~2s / 17 pages (stdlib)
- L1+L2: `--l1 --l2` → ~3min / 17 pages × 7 widths (Playwright)
- Custom widths: `--widths 320,768,1440`
- Custom tolerance: `--tol 5`

## When NOT to use this skill

| User wants | Use instead |
|------------|-------------|
| Pixel-perfect visual regression | Playwright / BackstopJS |
| Semantic DOM diff with file:line | `Shinyaigeek/qain` |
| CI deploy gate | This is diagnostic only |
| SPA / JS-heavy routes | L2 only checks static render |

## Example workflow

1. User: "Just rebuilt the site, check consistency"
2. Agent runs: `page-parity check --dir ./dist --format json`
3. Parses stdout JSON
4. If `verdict == "findings"` and `"VALUE_DRIFT" in codes`:
   - Fetches `details_url`
   - Reports: "`--primary` has 3 values: #0066cc (12 pages), #0055aa (3 pages), #0077dd (2 pages)"
5. If `verdict == "ok"`: "All 17 pages consistent, no overflow at any width."