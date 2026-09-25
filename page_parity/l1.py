"""L1 - cross-page consistency audit (pure stdlib, no browser, no network)."""

from __future__ import annotations

import os
import posixpath
import re
import urllib.parse

from . import css as cssmod
from . import dom as dommod

REMOTE_SCHEMES = ("http:", "https:", "//", "mailto:", "tel:", "javascript:", "data:", "blob:")


# ---------------------------------------------------------------------------
# Input collection
# ---------------------------------------------------------------------------

class Page:
    def __init__(self, rel, abspath):
        self.rel = rel
        self.abspath = abspath
        self.text = ""
        self.dom = None
        self.styles = []
        self.linked_css = []          # list[(relpath, text)]
        self.remote_css = []          # list[str] hrefs that could not be read offline
        self.redirect = False
        self.noindex = False
        self.canonical = False
        self.refresh = False
        self.encoding_uncertain = False
        self.ok = True

    @property
    def all_css(self):
        return "\n".join(self.styles + [t for _, t in self.linked_css])

    @property
    def inline_css(self):
        return "\n".join(self.styles)


class Site:
    def __init__(self, root, pages, errors):
        self.root = root
        self.pages = pages
        self.errors = errors


def _reset(page):
    page.text = ""
    page.dom = None
    page.styles = []
    page.linked_css = []
    page.remote_css = []
    page.encoding_uncertain = False


def _decode_text(raw):
    """Decode UTF-8, flagging lossy replacement instead of hiding it.

    ``errors="replace"`` maps every undecodable byte of every page to U+FFFD.
    On two different pages that makes two *different* corrupt byte runs look
    byte-identical, i.e. a false "these pages agree".  We keep the tolerant
    decode (never crash on a real site) but report the page as uncertain so
    the comparison does not silently treat garbage as evidence of parity.
    """
    text = raw.decode("utf-8", errors="replace")
    return text, "\ufffd" in text


def _read_text(path):
    with open(path, "rb") as fh:
        raw = fh.read()
    text, _ = _decode_text(raw)
    return text


def _local_href(href):
    if not href:
        return None
    low = href.strip().lower()
    for scheme in REMOTE_SCHEMES:
        if low.startswith(scheme):
            return None
    if low.startswith("#"):
        return None
    return href


def _within(root_real, candidate):
    """True when *candidate* (a real path) is inside *root_real*.

    Uses ``os.path.commonpath`` on real paths, so ``..`` traversal and symlink
    escapes are both rejected.  A naive ``str.startswith`` would let a sibling
    directory such as ``/site2`` masquerade as a child of ``/site``.
    """
    if not root_real:
        return False
    try:
        return os.path.commonpath([root_real, candidate]) == root_real
    except ValueError:  # different drives / empty path
        return False


def _load_page(page, root=None):
    _reset(page)
    try:
        with open(page.abspath, "rb") as fh:
            raw = fh.read()
        page.text, page.encoding_uncertain = _decode_text(raw)
        page.dom, page.styles = dommod.parse_html(page.text)
    except Exception as exc:  # noqa: BLE001 - surfaced as PARSE_ERROR
        page.ok = False
        return "parse error: %s: %s" % (page.rel, exc)

    root_real = os.path.realpath(root) if root else os.path.realpath(os.path.dirname(page.abspath))
    base = os.path.dirname(page.abspath)
    seen = set()
    for link in dommod.query(page.dom, 'link[href]'):
        rel = link.attrs.get("rel", "").lower()
        if "stylesheet" not in rel:
            continue
        href = _local_href(link.attrs.get("href", ""))
        if href is None:
            if link.attrs.get("href"):
                page.remote_css.append(link.attrs["href"])
            continue
        clean = urllib.parse.urlparse(href).path
        if not clean or clean in seen:
            continue
        seen.add(clean)
        cand = os.path.normpath(os.path.join(base, urllib.parse.unquote(clean)))
        cand_real = os.path.realpath(cand)
        if not os.path.isfile(cand_real):
            continue
        if not _within(root_real, cand_real):
            # Out-of-tree stylesheet: never read it.  Treated like any other
            # unreachable/remote stylesheet - recorded, not parsed.
            page.remote_css.append(href)
            continue
        try:
            page.linked_css.append((clean, _read_text(cand_real)))
        except Exception as exc:  # noqa: BLE001
            page.ok = False
            return "stylesheet error: %s: %s" % (clean, exc)

    meta = dommod.query(page.dom, "meta")
    page.refresh = any(
        m.attrs.get("http-equiv", "").lower() == "refresh" for m in meta
    )
    for m in meta:
        if m.attrs.get("name", "").lower() == "robots" and "noindex" in m.attrs.get("content", "").lower():
            page.noindex = True
    page.canonical = bool(dommod.query(page.dom, 'link[rel="canonical"]'))
    page.redirect = page.refresh or (page.noindex and page.canonical)
    return None


def build_site(directory=None, urls_file=None, recursive=False):
    errors = []
    pages = []
    if directory:
        directory = os.path.abspath(directory)
        if not os.path.isdir(directory):
            return None, ["input directory not found: %s" % directory]
        found = []
        if recursive:
            for dirpath, dirnames, filenames in os.walk(directory):
                dirnames[:] = sorted(
                    d for d in dirnames if not d.startswith(".") and d != "node_modules"
                )
                for name in sorted(filenames):
                    if name.lower().endswith(".html"):
                        found.append(os.path.join(dirpath, name))
        else:
            for name in sorted(os.listdir(directory)):
                if name.startswith("."):
                    continue
                candidate = os.path.join(directory, name)
                if os.path.isfile(candidate) and name.lower().endswith(".html"):
                    found.append(candidate)
        for abspath in found:
            rel = os.path.relpath(abspath, directory).replace(os.sep, "/")
            pages.append(Page(rel, abspath))
        root = directory
    elif urls_file:
        try:
            with open(urls_file, encoding="utf-8") as fh:
                entries = [ln.strip() for ln in fh if ln.strip() and not ln.strip().startswith("#")]
        except OSError as exc:
            return None, ["cannot read urls file: %s" % exc]
        if not entries:
            return None, ["urls file is empty: %s" % urls_file]
        paths = []
        for entry in entries:
            if entry.startswith("file://"):
                entry = urllib.parse.unquote(urllib.parse.urlparse(entry).path)
            low = entry.lower()
            if low.startswith(("http://", "https://", "//")):
                return None, ["offline mode: remote url not allowed: %s" % entry]
            abspath = os.path.abspath(entry)
            if not os.path.isfile(abspath):
                return None, ["input file not found: %s" % entry]
            paths.append(abspath)
        root = os.path.commonpath([os.path.dirname(p) for p in paths]) if paths else ""
        for abspath in paths:
            rel = os.path.relpath(abspath, root).replace(os.sep, "/")
            pages.append(Page(rel, abspath))
    else:
        return None, ["no input: pass --dir or --urls"]

    pages.sort(key=lambda p: (p.rel.count("/"), p.rel))
    for page in pages:
        err = _load_page(page, root)
        if err:
            errors.append(err)
    return Site(root, pages, errors), errors


# ---------------------------------------------------------------------------
# Value normalisation
# ---------------------------------------------------------------------------

_HEX3 = re.compile(r"#([0-9a-f]{3})\b")
_HEX4 = re.compile(r"#([0-9a-f]{4})\b")
_LEADING_ZERO = re.compile(r"(?<![\w.])0+\.(\d)")
_WS = re.compile(r"\s+")


def normalize_css_value(value):
    if value is None:
        return ""
    v = value.strip().lower()
    v = _WS.sub(" ", v)
    v = re.sub(r"\s*,\s*", ",", v)
    v = _LEADING_ZERO.sub(r".\1", v)
    v = _HEX3.sub(lambda m: "#" + "".join(c * 2 for c in m.group(1)), v)
    v = _HEX4.sub(lambda m: "#" + "".join(c * 2 for c in m.group(1)), v)
    return v.strip()


# ---------------------------------------------------------------------------
# A1 - should-be-consistent checklist
# ---------------------------------------------------------------------------

def _item_occurrences(item, page):
    kind = item["kind"]
    if kind == "selector":
        matches = dommod.query(page.dom, item["selector"])
        count = len(matches)
    elif kind == "text":
        count = len(re.findall(item["pattern"], page.text))
        matches = []
    elif kind == "css_backdrop":
        # A1 inspects what *this page itself* declares (inline <style> + DOM),
        # not shared external stylesheets.  Shared CSS is covered by A2.
        count = len(cssmod.backdrop_layers(page.inline_css))
        if not count:
            count = len(dommod.query(page.dom, '[class*="watermark"], [id*="watermark"]'))
        matches = []
    else:  # pragma: no cover - config validation guarantees this
        count, matches = 0, []

    value = None
    compare = item.get("compare", "none")
    if count and compare != "none":
        if kind == "selector" and compare == "attr":
            attr = item.get("value_attr", "")
            vals = sorted({normalize_css_value(m.attrs.get(attr, "")) for m in matches})
            value = tuple(vals)
        elif kind == "selector" and compare == "set":
            value = tuple(sorted({dommod.norm_text(m.text()) for m in matches}))
        elif kind == "selector" and compare == "text":
            value = tuple(sorted({dommod.norm_text(m.text()) for m in matches})) or ("",)
        else:
            value = (normalize_css_value(page.text),)
    return count, value


def _is_excepted(page, config):
    if page.redirect:
        return "redirect/retired page (meta refresh or canonical+noindex)"
    if page.noindex:
        return "noindex page (intentionally excluded from navigation)"
    for exc in config.expect_exceptions:
        if exc["page"] in (page.rel, os.path.basename(page.rel)):
            return exc["reason"]
    return None


def _fmt_value(value):
    if isinstance(value, tuple):
        return " | ".join(value)
    return str(value)


def check_a1(site, config, seen_pages=None):
    pages = [p for p in site.pages if p.ok]
    total = len(pages)
    report = {"items": [], "findings": [], "advisories": []}
    for item in config.items:
        per_page = {}
        values = {}   # value tuple -> [pages]
        uncertain = []  # pages whose text decode was lossy
        for page in pages:
            count, value = _item_occurrences(item, page)
            per_page[page.rel] = count
            if page.encoding_uncertain:
                # A page with replacement characters cannot vouch for a value;
                # excluding it prevents two differently-corrupt pages from
                # looking byte-identical.
                if count:
                    uncertain.append(page.rel)
                continue
            if value is not None and count:
                values.setdefault(value, []).append(page.rel)

        present = [rel for rel, c in per_page.items() if c > 0]
        absent = [rel for rel, c in per_page.items() if c == 0]
        exceptions = []
        missing = []
        for rel in absent:
            page = seen_pages[rel] if seen_pages else None
            reason = _is_excepted(page, config) if page is not None else None
            if reason:
                exceptions.append({"page": rel, "reason": reason})
            else:
                missing.append(rel)

        multi = {v: sorted(p) for v, p in values.items()}
        scope = item.get("scope", "all")
        scope_ok = True
        if scope == "all":
            scope_ok = not missing
        elif isinstance(scope, str) and scope.startswith("min:"):
            try:
                need = int(scope.split(":", 1)[1])
            except ValueError:
                need = 0
            scope_ok = len(present) >= need
        value_drift = len(multi) > 1

        findings = []
        advisories = []
        if not present:
            # SPEC v1.1 §1.1: an item that no page carries is a site-wide
            # absence, not a per-page inconsistency.  It is reported as an
            # advisory (ABSENT_EVERYWHERE) and must NOT affect the exit code;
            # otherwise every minimal site would drown in false findings.
            item_verdict = "absent_everywhere"
            advisories.append({
                "code": "ABSENT_EVERYWHERE",
                "item": item["id"],
                "present": 0,
                "total": total,
            })
        else:
            if not scope_ok and missing:
                findings.append({
                    "code": "MISSING_ON_PAGE",
                    "item": item["id"],
                    "missing": missing,
                })
            if value_drift:
                findings.append({
                    "code": "VALUE_DRIFT",
                    "item": item["id"],
                    "values": {_fmt_value(v): p for v, p in multi.items()},
                })
            item_verdict = "inconsistent" if findings else "ok"

        report["items"].append({
            "id": item["id"],
            "scope": scope,
            "verdict": item_verdict,
            "present": len(present),
            "total": total,
            "present_pages": sorted(present),
            "absent": sorted(absent),
            "missing": missing,
            "missing_excepted": exceptions,
            "uncertain_pages": sorted(uncertain),
            "values": {_fmt_value(v): p for v, p in multi.items()},
            "findings": findings,
        })
        report["findings"].extend(findings)
        report["advisories"].extend(advisories)
    return report


# ---------------------------------------------------------------------------
# A2 - variable declaration drift
# ---------------------------------------------------------------------------

def _fmt_context(context):
    return context or ""


def check_a2(site):
    checked = 0
    scoped_ignored = 0
    scoped_names = set()
    uncertain_pages = []
    # name -> context_key -> {norm_value: [pages]}
    by_name_context = {}
    # name -> {page.rel: frozenset((context_key, norm_value))}
    by_name_page = {}
    for page in [p for p in site.pages if p.ok]:
        if page.encoding_uncertain:
            uncertain_pages.append(page.rel)
            continue
        for name, value, is_global, context in cssmod.all_custom_props(page.all_css):
            if not is_global:
                scoped_ignored += 1
                scoped_names.add(name)
                continue
            checked += 1
            norm = normalize_css_value(value)
            by_name_context.setdefault(name, {}).setdefault(context, {}).setdefault(norm, [])
            if page.rel not in by_name_context[name][context][norm]:
                by_name_context[name][context][norm].append(page.rel)
            by_name_page.setdefault(name, {}).setdefault(page.rel, set()).add((context, norm))

    variables = []
    findings = []
    for name in sorted(by_name_page):
        page_maps = by_name_page[name]
        # Drift means: not every page declares the same *set* of
        # (context, value) pairs.  A single page that declares the same
        # variable twice - e.g. once top-level and once inside
        # ``@media (min-width: 768px)`` - has one coherent set; both values
        # belonging to the same page is not drift.
        signatures = {frozenset(decls) for decls in page_maps.values()}
        if len(signatures) <= 1:
            continue
        values = {}
        for context in sorted(by_name_context.get(name, {})):
            for norm in sorted(by_name_context[name][context]):
                pages = sorted(by_name_context[name][context][norm])
                key = norm if not context else "%s @%s" % (norm, _fmt_context(context))
                values[key] = pages
        variables.append({"name": name, "values": values})
        findings.append({
            "code": "VALUE_DRIFT",
            "item": "css_variable:%s" % name,
            "values": values,
        })
    return {
        "checked": checked,
        "scoped_ignored": scoped_ignored,
        "scoped_ignored_names": sorted(scoped_names),
        "uncertain_pages": sorted(uncertain_pages),
        "drifted": variables,
        "findings": findings,
    }, findings


# ---------------------------------------------------------------------------
# A3 - orphan pages
# ---------------------------------------------------------------------------

def _resolve_link(href, page, names):
    """Resolve an ``<a href>`` to a page relative path, or None.

    Besides the literal target this understands the two ubiquitous static-site
    layouts: an extensionless link (``/about`` -> ``about.html``) and a clean
    URL directory (``/about/`` -> ``about/index.html``).  The site root
    (``/``, ``.`` or an empty href) points at the top-level ``index.html``.
    """
    href = href.strip()
    if not href:
        return _pick(names, "index.html")
    low = href.lower()
    for scheme in REMOTE_SCHEMES:
        if low.startswith(scheme):
            return None
    href = href.split("#", 1)[0].split("?", 1)[0]
    if not href:
        # A fragment/query-only link points at the current page, not the root.
        return None
    href = urllib.parse.unquote(href)
    if href.startswith("/"):
        cand = posixpath.normpath(href.lstrip("/"))
    else:
        base = posixpath.dirname(page.rel)
        cand = posixpath.normpath(posixpath.join(base, href))
    if cand in (".", ""):
        return _pick(names, "index.html")
    # 1. literal target, 2. extensionless route, 3. directory route.
    for candidate in (cand, cand + ".html", posixpath.join(cand, "index.html")):
        if candidate in names:
            return candidate
    return None


def _pick(names, candidate):
    return candidate if candidate in names else None


def _entry_page(site):
    """The site's own front door - it is reached by URL, never by a link."""
    for page in site.pages:
        if page.rel == "index.html":
            return page.rel
    return None


def check_a3(site, config, seen_pages=None):
    ok_pages = [p for p in site.pages if p.ok]
    names = {p.rel for p in ok_pages}
    entry = _entry_page(site)
    inbound = {p.rel: set() for p in ok_pages}
    for page in ok_pages:
        for a in dommod.query(page.dom, "a[href]"):
            tgt = _resolve_link(a.attrs.get("href", ""), page, names)
            if tgt and tgt != page.rel:
                inbound[tgt].add(page.rel)
    orphans = []
    exceptions = []
    findings = []
    # A one-page site has no link graph to speak of; reporting it as an orphan
    # is meaningless noise.
    single_page = len(ok_pages) <= 1
    for page in ok_pages:
        if inbound[page.rel]:
            continue
        reason = None
        if page.redirect:
            reason = "redirect/retired page (meta refresh or canonical+noindex)"
        elif page.noindex:
            reason = "noindex page (intentionally unlinked)"
        elif page.rel == entry:
            reason = "site entry page (reached by URL, no inbound link expected)"
        else:
            for exc in config.expect_exceptions:
                if exc["page"] in (page.rel, os.path.basename(page.rel)):
                    reason = exc["reason"]
                    break
        entry_rec = {"page": page.rel, "inbound": 0}
        if single_page and reason is None:
            # nothing else can link to it; keep it visible as an exception.
            reason = "single-page site (no other page can link to it)"
        if reason:
            entry_rec["exception"] = reason
            exceptions.append(entry_rec)
        else:
            orphans.append(entry_rec)
            findings.append({"code": "ORPHAN_PAGE", "page": page.rel, "inbound": 0})
    return {
        "pages": [{"page": p.rel, "inbound": len(inbound[p.rel])} for p in ok_pages],
        "entry_page": entry,
        "single_page": single_page,
        "orphans": orphans,
        "orphan_exceptions": exceptions,
        "orphans_all": orphans + exceptions,
        "findings": findings,
    }, findings


# ---------------------------------------------------------------------------
# advisory probes (never affect the exit code)
# ---------------------------------------------------------------------------

# Navigation landmarks that normally hold the site menu.  An empty one means
# the menu is almost certainly injected by client-side JavaScript, which a
# static scan cannot see.  A bare ``<header>`` is deliberately NOT included:
# article/section headers legitimately hold a title and no links.
_NAV_CONTAINERS = ('nav', '[role="navigation"]')


def _csr_shells(site):
    shells = []
    for page in [p for p in site.pages if p.ok]:
        if page.redirect:
            continue
        for selector in _NAV_CONTAINERS:
            for el in dommod.query(page.dom, selector):
                if dommod.query(el, "a[href]"):
                    continue
                shells.append({"page": page.rel, "container": selector})
    return shells


def _encoding_uncertain(site):
    return sorted(p.rel for p in site.pages if p.ok and p.encoding_uncertain)


# ---------------------------------------------------------------------------
# orchestration
# ---------------------------------------------------------------------------

def run_l1(site, config, only=None):
    seen_pages = {p.rel: p for p in site.pages}
    active = set(only or ["a1", "a2", "a3"])
    result = {"a1": None, "a2": None, "a3": None, "findings": [], "advisories": []}
    codes = set()
    if "a1" in active:
        a1 = check_a1(site, config, seen_pages)
        result["a1"] = a1
        result["findings"].extend(a1["findings"])
        result["advisories"].extend(a1["advisories"])
    if "a2" in active:
        a2, a2_findings = check_a2(site)
        result["a2"] = a2
        result["findings"].extend(a2_findings)
    if "a3" in active:
        a3, a3_findings = check_a3(site, config, seen_pages)
        result["a3"] = a3
        result["findings"].extend(a3_findings)

    uncertain = _encoding_uncertain(site)
    if uncertain:
        result["advisories"].append({
            "code": "ENCODING_UNCERTAIN",
            "pages": uncertain,
            "message": "page text contained undecodable bytes (U+FFFD); values "
                       "from these pages were excluded from equality checks",
        })
    shells = _csr_shells(site)
    if shells:
        result["advisories"].append({
            "code": "CSR_SHELL_DETECTED",
            "shells": shells,
            "message": "empty navigation container: the menu is likely injected "
                       "by JavaScript and cannot be audited statically",
        })

    for f in result["findings"]:
        codes.add(f["code"])
    for a in result["advisories"]:
        codes.add(a["code"])
    result["advisory_count"] = len(result["advisories"])
    result["codes"] = sorted(codes)
    return result
