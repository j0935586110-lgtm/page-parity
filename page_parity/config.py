"""Configuration loading for page-parity.

The shipped ``page-parity.toml`` is the default checklist.  It contains only
generic selectors and text patterns (``nav a``, ``footer``, ``html[lang]`` ...);
no page name, brand or site-specific literal is ever embedded in code.
"""

from __future__ import annotations

import os
import tomllib

DEFAULT_ITEMS = [
    {"id": "canonical", "kind": "selector", "selector": 'link[rel="canonical"]',
     "scope": "all", "compare": "none"},
    {"id": "og_title", "kind": "selector", "selector": 'meta[property="og:title"]',
     "scope": "all", "compare": "none"},
    {"id": "og_image", "kind": "selector", "selector": 'meta[property="og:image"]',
     "scope": "all", "compare": "none"},
    {"id": "viewport", "kind": "selector", "selector": 'meta[name="viewport"]',
     "scope": "all", "compare": "attr", "value_attr": "content"},
    {"id": "favicon", "kind": "selector", "selector": 'link[rel~="icon"]',
     "scope": "all", "compare": "none"},
    {"id": "lang", "kind": "selector", "selector": "html[lang]",
     "scope": "all", "compare": "attr", "value_attr": "lang"},
    {"id": "analytics", "kind": "text",
     "pattern": r"googletagmanager|gtag\(|google-analytics|G-[A-Z0-9]{6,}|UA-[0-9]+",
     "scope": "all", "compare": "none"},
    {"id": "menu_items", "kind": "selector", "selector": "nav a",
     "scope": "all", "compare": "set"},
    {"id": "footer", "kind": "selector", "selector": "body > footer",
     "scope": "all", "compare": "text"},
    {"id": "watermark", "kind": "css_backdrop", "scope": "all", "compare": "none"},
]


class Config:
    def __init__(self, items, expect_exceptions, source):
        self.items = items
        self.expect_exceptions = expect_exceptions
        self.source = source


def _normalize_item(raw, index):
    if "id" not in raw:
        raise ValueError("checklist item #%d is missing 'id'" % index)
    kind = raw.get("kind", "selector")
    item = dict(raw)
    item["kind"] = kind
    item.setdefault("scope", "all")
    item.setdefault("compare", "none")
    if kind == "selector" and not item.get("selector"):
        raise ValueError("item %r needs a 'selector'" % item["id"])
    if kind == "text" and not item.get("pattern"):
        raise ValueError("item %r needs a 'pattern'" % item["id"])
    if kind not in ("selector", "text", "css_backdrop"):
        raise ValueError("item %r has unknown kind %r" % (item["id"], kind))
    return item


def _normalize_exception(raw, index):
    if "page" not in raw:
        raise ValueError("expect_exceptions #%d is missing 'page'" % index)
    return {"page": str(raw["page"]), "reason": str(raw.get("reason", "listed exception"))}


def from_mapping(data, source):
    raw_items = data.get("items")
    if raw_items is None:
        items = [dict(i) for i in DEFAULT_ITEMS]
    else:
        items = [_normalize_item(i, n) for n, i in enumerate(raw_items)]
    raw_exc = data.get("expect_exceptions") or []
    exceptions = [_normalize_exception(e, n) for n, e in enumerate(raw_exc)]
    return Config(items, exceptions, source)


def load(path=None):
    argv_config = path
    candidates = []
    if argv_config:
        candidates.append(argv_config)
    env = os.environ.get("PAGE_PARITY_CONFIG")
    if env:
        candidates.append(env)
    candidates.append(os.path.join(os.getcwd(), "page-parity.toml"))
    candidates.append(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                                   "page-parity.toml"))
    for cand in candidates:
        if cand and os.path.isfile(cand):
            with open(cand, "rb") as fh:
                data = tomllib.load(fh)
            return from_mapping(data, os.path.abspath(cand))
    if argv_config:
        raise FileNotFoundError("config not found: %s" % argv_config)
    return from_mapping({}, "<built-in defaults>")
