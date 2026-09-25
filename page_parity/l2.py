"""L2 - element/page layout overflow (needs a browser, loaded lazily).

Playwright is imported only when L2 is actually requested.  If it is missing
(or no browser binary is available) the caller turns this into exit 2
``NO_BROWSER`` - never a silent pass.

Only local ``file://`` documents are allowed.  Every non-``file:`` request is
aborted, so L2 never touches the network.
"""

from __future__ import annotations

DEFAULT_WIDTHS = [320, 360, 390, 430, 768, 1024, 1440]
DEFAULT_TOL = 2

MEASURE_JS = r"""
(opts) => {
  const tol = opts.tol;
  const out = {page: [], elements: [], fixed: []};

  const selectorPath = (el) => {
    const parts = [];
    let node = el;
    while (node && node.nodeType === 1 && node !== document.documentElement) {
      let s = node.tagName.toLowerCase();
      if (node.id) {
        s += '#' + node.id;
      } else if (node.classList && node.classList.length) {
        s += '.' + Array.from(node.classList).slice(0, 2).join('.');
      }
      parts.unshift(s);
      node = node.parentElement;
    }
    return parts.join(' > ');
  };

  const de = document.documentElement;
  if (de.scrollWidth > de.clientWidth + tol) {
    out.page.push({
      selector: 'html',
      client_width: de.clientWidth,
      scroll_width: de.scrollWidth,
      overflow_px: de.scrollWidth - de.clientWidth,
    });
  }

  const all = Array.from(document.querySelectorAll('body *'));
  for (const el of all) {
    const cw = el.clientWidth;
    const sw = el.scrollWidth;
    if (sw <= cw + tol) continue;
    const cs = getComputedStyle(el);
    if (cs.display === 'none' || cs.visibility === 'hidden') continue;
    if (cw === 0 && el.clientHeight === 0) continue;
    out.elements.push({
      selector: selectorPath(el),
      client_width: cw,
      scroll_width: sw,
      overflow_px: sw - cw,
      text: (el.textContent || '').replace(/\s+/g, ' ').trim().slice(0, 80),
    });
  }

  const clickable = all.filter((el) => el.matches('a[href],button,input,select,textarea,summary,[role="button"]'));

  // Consent / cookie banners are expected chrome.  They are reported for
  // visibility but never as a hard finding, because dismissing them is the
  // user's job, not a layout defect.
  const looksLikeConsent = (el) => {
    let cls = el.className;
    if (cls && typeof cls !== 'string') cls = cls.baseVal || '';
    const hay = [el.id || '', cls || '', el.getAttribute('role') || '',
                 el.getAttribute('aria-label') || '', el.getAttribute('title') || '']
                 .join(' ').toLowerCase();
    if (/(consent|cookie|gdpr|privacy|tracking[-_ ]?notice)/.test(hay)) return true;
    const fr = el.getBoundingClientRect();
    if (!(fr.bottom >= window.innerHeight - 2 && fr.top > window.innerHeight * 0.5)) return false;
    const ctrl = el.querySelector('button,[role="button"],a[href],input[type="button"],input[type="submit"]');
    if (!ctrl) return false;
    const label = ((ctrl.textContent || '') + ' ' + (ctrl.getAttribute('aria-label') || '') +
                   ' ' + (ctrl.value || '') + ' ' + hay).toLowerCase();
    return /(accept|agree|allow|close|dismiss|got it|consent|\u540c\u610f|\u63a5\u53d7|\u5141\u8a31|\u78ba\u8a8d|\u95dc\u9589|\u77e5\u9053)/.test(label);
  };

  for (const fel of all) {
    const cs = getComputedStyle(fel);
    if (cs.position !== 'fixed' && cs.position !== 'sticky') continue;
    if (cs.display === 'none' || cs.visibility === 'hidden' || parseFloat(cs.opacity) === 0) continue;
    // An element that ignores pointer events cannot actually intercept a tap.
    if (cs.pointerEvents === 'none') continue;
    const fr = fel.getBoundingClientRect();
    if (fr.width <= 0 || fr.height <= 0) continue;
    if (fr.bottom <= 0 || fr.top >= window.innerHeight || fr.right <= 0 || fr.left >= window.innerWidth) continue;
    for (const ce of clickable) {
      if (fel === ce || fel.contains(ce) || ce.contains(fel)) continue;
      const cr = ce.getBoundingClientRect();
      if (cr.width <= 0 || cr.height <= 0) continue;
      const cx = cr.left + cr.width / 2;
      const cy = cr.top + cr.height / 2;
      if (cx < 0 || cy < 0 || cx > window.innerWidth || cy > window.innerHeight) continue;
      const top = document.elementFromPoint(cx, cy);
      if (top && (top === fel || fel.contains(top))) {
        out.fixed.push({
          selector: selectorPath(fel),
          covered: selectorPath(ce),
          covered_text: (ce.textContent || '').replace(/\s+/g, ' ').trim().slice(0, 60),
          consent: looksLikeConsent(fel),
        });
        break;
      }
    }
  }
  return out;
}
"""


class NoBrowser(Exception):
    pass


def _load_sync_playwright():
    try:
        from playwright.sync_api import sync_playwright
    except Exception as exc:  # pragma: no cover - depends on environment
        raise NoBrowser("playwright is not importable: %s" % exc) from exc
    return sync_playwright


def classify_fixed(fixed_raw):
    """Split raw ``FIXED_OBSCURES`` hits into findings and advisories.

    * one entry per ``(page, selector)`` regardless of how many widths matched;
    * consent/cookie chrome (``consent_like``) becomes an advisory, so it is
      still reported but never changes the exit code;
    * any other fixed/sticky element that covers a control stays a finding.
    """
    findings = []
    advisories = []
    offenders = []
    seen = set()
    for entry in fixed_raw:
        key = (entry["page"], entry["selector"])
        if key in seen:
            continue
        seen.add(key)
        record = dict(entry)
        if record.pop("consent_like", False):
            record["advisory"] = True
            advisories.append(record)
        else:
            findings.append(record)
            offenders.append(record)
    return findings, advisories, offenders


def run_l2(pages, widths=None, tol=DEFAULT_TOL):
    """Measure each page at each width.

    ``pages`` is a list of ``(rel, abspath)`` tuples.  Returns a dict; raises
    :class:`NoBrowser` when the browser cannot be started.
    """
    widths = list(widths or DEFAULT_WIDTHS)
    sync_playwright = _load_sync_playwright()
    findings = []
    offenders = []
    advisories = []
    fixed_raw = []
    errors = []
    try:
        with sync_playwright() as pw:
            try:
                browser = pw.chromium.launch(args=[
                    "--no-sandbox",
                    "--disable-background-networking",
                    "--disable-component-update",
                    "--disable-default-apps",
                    "--disable-sync",
                    "--no-first-run",
                    "--host-resolver-rules=MAP * ~NOTFOUND",
                ])
            except Exception as exc:  # pragma: no cover - environment dependent
                raise NoBrowser("could not launch chromium: %s" % exc) from exc
            context = browser.new_context()
            context.route(
                "**/*",
                lambda route: route.abort()
                if not route.request.url.startswith("file:")
                else route.continue_(),
            )
            page = context.new_page()
            for rel, abspath in pages:
                try:
                    page.goto("file://" + abspath, wait_until="load", timeout=30000)
                except Exception as exc:  # noqa: BLE001
                    errors.append("load error: %s: %s" % (rel, exc))
                    continue
                for width in widths:
                    try:
                        page.set_viewport_size({"width": int(width), "height": 900})
                        page.wait_for_timeout(30)
                        data = page.evaluate(MEASURE_JS, {"tol": tol})
                    except Exception as exc:  # noqa: BLE001
                        errors.append("measure error: %s @%s: %s" % (rel, width, exc))
                        continue
                    for p in data.get("page", []):
                        entry = {
                            "code": "PAGE_OVERFLOW",
                            "page": rel,
                            "width": int(width),
                            "selector": p.get("selector", "html"),
                            "client_width": p.get("client_width"),
                            "scroll_width": p.get("scroll_width"),
                            "overflow_px": p.get("overflow_px"),
                        }
                        offenders.append(entry)
                        findings.append(entry)
                    for e in data.get("elements", []):
                        entry = {
                            "code": "ELEMENT_OVERFLOW",
                            "page": rel,
                            "width": int(width),
                            "selector": e.get("selector"),
                            "client_width": e.get("client_width"),
                            "scroll_width": e.get("scroll_width"),
                            "overflow_px": e.get("overflow_px"),
                            "text": e.get("text", ""),
                        }
                        offenders.append(entry)
                        findings.append(entry)
                    for f in data.get("fixed", []):
                        fixed_raw.append({
                            "code": "FIXED_OBSCURES",
                            "page": rel,
                            "width": int(width),
                            "selector": f.get("selector"),
                            "covered": f.get("covered"),
                            "covered_text": f.get("covered_text", ""),
                            "consent_like": bool(f.get("consent")),
                        })
            browser.close()
    except NoBrowser:
        raise
    except Exception as exc:  # pragma: no cover - environment dependent
        raise NoBrowser("browser session failed: %s" % exc) from exc

    # One element must be reported once per page, no matter how many viewport
    # widths it happened to obscure at; consent chrome becomes advisory.
    fixed_findings, advisories, fixed_offenders = classify_fixed(fixed_raw)
    findings.extend(fixed_findings)
    offenders.extend(fixed_offenders)

    return {
        "widths": [int(w) for w in widths],
        "tol": tol,
        "pages": len(pages),
        "offenders": offenders,
        "advisories": advisories,
        "errors": errors,
        "findings": findings,
    }
