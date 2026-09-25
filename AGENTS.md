# AGENTS.md — page-parity usage guide for agents

## When to call page-parity

Trigger **once** after any of these:
- Site rebuild / redesign complete
- New page added to a static site
- CSS variable refactor (tokens.css migration)
- Pre-merge sanity check on a feature branch
- "Does every page still have the menu / footer / tracking?"

**Do not** call it:
- On every file save (too noisy)
- As a CI deploy gate (it's diagnostic, not a blocker)
- For visual regression — use Playwright/BackstopJS
- For semantic DOM diff — use `Shinyaigeek/qain`

---

## One call, one verdict

```bash
page-parity check --dir ./site --format json
```

Parse stdout (single-line JSON). **Do not read raw output files.** The `details_url` is for *you* to fetch *only if* the verdict needs drilling down.

### JSON fields you care about

| Field | Type | Meaning |
|-------|------|---------|
| `verdict` | `"ok" \| "findings" \| "indeterminate" \| "usage" \| "internal"` | Final answer (**lowercase**) |
| `exit_reason` | `"OK" \| "FINDINGS" \| "INDETERMINATE" \| "USAGE" \| "INTERNAL"` | Why (**UPPERCASE**) |
| `codes[]` | array of finding codes | What kinds of issues |
| `counts.pages` | int | Pages scanned |
| `counts.findings` | int | Total individual findings (excludes advisories) |
| `counts.advisories` | int | Advisory items (ABSENT_EVERYWHERE, CSR_SHELL_DETECTED, ENCODING_UNCERTAIN) |
| `details_url` | `file://...` | Full report (fetch only if needed) |

### Finding codes (grep-able)

| Code | Layer | What it means |
|------|-------|---------------|
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
    # Read codes[] to categorize:
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

## Common patterns

**Quick L1 only (no browser, ~2s):**
```bash
page-parity check --dir ./site --format json
# or explicit:
page-parity check --dir ./site --l1 --format json
```

**Full L1+L2 with specific widths:**
```bash
page-parity check --dir ./site --l1 --l2 --widths 320,768,1440 --format json
```

**Run only specific checks:**
```bash
# a1=consistency, a2=CSS vars, a3=orphans
page-parity check --dir ./site --only a1,a3 --format json
```

**Self-test (validates the tool itself):**
```bash
page-parity --self-test
```

**Read full details report:**
```bash
page-parity details file:///path/to/details-xxx.json
```

---

## What NOT to do

| ❌ Don't | ✅ Do |
|----------|-------|
| `cat $(page-parity ... | jq -r .details_url)` | Parse stdout JSON directly |
| Treat exit code 0 as "no findings" | Exit 0 = OK; exit 1 = findings; exit 2 = uncertain |
| Assume `ORPHAN_PAGE` = bug | Check `expect_exceptions` in config — some are intentional |
| Use for visual diff | Use Playwright/BackstopJS |
| Feed raw HTML to LLM for comparison | page-parity already did the structured extraction |
| Use `--level L1` / `--level L2` | These flags **don't exist**; use `--l1` / `--l2` |
| Expect `verdict: "OK"` | It's `"ok"` (lowercase) |

---

## Config location

`page-parity.toml` in the site root (same dir as `--dir`). If absent, built-in defaults apply.

Key knobs:
- `items[].scope = "all" | "min:N" | "any"`
- `expect_exceptions = [{page="...", reason="..."}]` — **reason required**

### Config structure (actual)

```toml
[[items]]
id = "menu_items"
kind = "selector"
selector = "nav a"
scope = "all"
compare = "set"

[[expect_exceptions]]
page = "legacy-redirect.html"
reason = "HTTP 301 + noindex, deliberately no menu"
```

**NOT** `[checks]` / `[exceptions]` — the actual keys are `items` (array of tables) and `expect_exceptions` (array of tables).

---

## Performance budgets

- L1: ≤2 seconds / 17 pages (pure Python stdlib)
- L2: ≤3 minutes / 17 pages × 7 widths (Playwright)

If it's slower, something's wrong — report it.