"""Minimal, dependency-free HTML parsing and CSS-selector matching.

This module is deliberately small: page-parity only needs a tolerant DOM tree
plus a subset of CSS selectors (tag, .class, #id, [attr], [attr=..], descendant
and child combinators).  Everything here is pure stdlib.
"""

from __future__ import annotations

import re
from html.parser import HTMLParser

VOID = {
    "area", "base", "br", "col", "embed", "hr", "img", "input",
    "link", "meta", "param", "source", "track", "wbr",
    "command", "keygen", "menuitem",
}

_WS = re.compile(r"\s+")


def norm_text(s):
    if s is None:
        return ""
    return _WS.sub(" ", s).strip()


class Node:
    __slots__ = ("tag", "attrs", "children", "parent")

    def __init__(self, tag, attrs, parent):
        self.tag = tag              # lower-case tag name, or '#document'/'#text'
        self.attrs = attrs          # dict[str, str]
        self.children = []          # list[Node | str]
        self.parent = parent

    # -- convenience -----------------------------------------------------
    @property
    def classes(self):
        cls = self.attrs.get("class", "")
        return [c for c in _WS.split(cls) if c]

    @property
    def id(self):
        return self.attrs.get("id", "")

    def text(self):
        parts = []
        _collect_text(self, parts)
        return norm_text("".join(parts))

    def iter_elements(self):
        # Iterative pre-order walk: a 1000-deep document must not blow the
        # interpreter recursion limit (that used to surface as exit 4).
        stack = list(reversed(self.children))
        while stack:
            node = stack.pop()
            if isinstance(node, Node):
                yield node
                stack.extend(reversed(node.children))

    def ancestors(self):
        p = self.parent
        while p is not None:
            if p.tag != "#document":
                yield p
            p = p.parent


def _collect_text(node, out):
    # Iterative pre-order walk, appending text in document order.
    stack = [node]
    while stack:
        current = stack.pop()
        if isinstance(current, str):
            out.append(current)
            continue
        if current.tag == "#text":
            out.append(current.attrs.get("_data", ""))
            continue
        stack.extend(reversed(current.children))


class _Parser(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.root = Node("#document", {}, None)
        self.stack = [self.root]
        self.styles = []
        self._style_buf = None

    # HTMLParser callbacks ------------------------------------------------
    def handle_starttag(self, tag, attrs):
        self._start(tag, attrs, push=(tag not in VOID))

    def handle_startendtag(self, tag, attrs):
        self._start(tag, attrs, push=False)

    def _start(self, tag, attrs, push):
        tag = tag.lower()
        adict = {}
        for k, v in attrs:
            adict[k.lower()] = "" if v is None else v
        node = Node(tag, adict, self.stack[-1])
        self.stack[-1].children.append(node)
        if tag == "style":
            self._style_buf = []
        if push:
            self.stack.append(node)

    def handle_endtag(self, tag):
        tag = tag.lower()
        if tag == "style" and self._style_buf is not None:
            self.styles.append("".join(self._style_buf))
            self._style_buf = None
        for i in range(len(self.stack) - 1, 0, -1):
            if self.stack[i].tag == tag:
                del self.stack[i:]
                return

    def handle_data(self, data):
        if self._style_buf is not None:
            self._style_buf.append(data)
        else:
            self.stack[-1].children.append(data)


# ---------------------------------------------------------------------------
# Selector subset
# ---------------------------------------------------------------------------

_ATTR_RE = re.compile(
    r"""\[\s*([\w:.-]+)\s*"""
    r"""(?:([~^$*|]?=)\s*(?:"([^"]*)"|'([^']*)'|([^\]\s]+)))?\s*\]"""
)
_TAG_RE = re.compile(r"^(\*|[A-Za-z][\w-]*)")
_CLASS_RE = re.compile(r"^\.([\w-]+)")
_ID_RE = re.compile(r"^#([\w-]+)")
_PSEUDO_RE = re.compile(r"^::?[\w-]+(?:\([^)]*\))?")


class Compound:
    __slots__ = ("tag", "classes", "eid", "attrs")

    def __init__(self):
        self.tag = None
        self.classes = []
        self.eid = None
        self.attrs = []  # list[(name, op, value)]


def _parse_compound(text):
    c = Compound()
    i = 0
    m = _TAG_RE.match(text)
    if m:
        c.tag = m.group(1)
        i = m.end()
    n = len(text)
    while i < n:
        ch = text[i]
        if ch == ".":
            m = _CLASS_RE.match(text, i)
            if not m:
                i += 1
                continue
            c.classes.append(m.group(1))
            i = m.end()
        elif ch == "#":
            m = _ID_RE.match(text, i)
            if not m:
                i += 1
                continue
            c.eid = m.group(1)
            i = m.end()
        elif ch == "[":
            m = _ATTR_RE.match(text, i)
            if not m:
                i += 1
                continue
            name = m.group(1)
            op = m.group(2)
            val = m.group(3) if m.group(3) is not None else (
                m.group(4) if m.group(4) is not None else m.group(5))
            if op is None:
                c.attrs.append((name, None, None))
            else:
                c.attrs.append((name, op, val if val is not None else ""))
            i = m.end()
        elif ch == ":":
            m = _PSEUDO_RE.match(text, i)
            i = m.end() if m else i + 1
        else:
            i += 1
    return c


def _split_selector(selector):
    """Split a comma list into groups of (compounds, combinators)."""
    groups = []
    depth = 0
    cur = ""
    for ch in selector:
        if ch in "([":
            depth += 1
        elif ch in ")]":
            depth -= 1
        if ch == "," and depth == 0:
            groups.append(cur)
            cur = ""
        else:
            cur += ch
    groups.append(cur)
    out = []
    for g in groups:
        g = g.strip()
        if not g:
            continue
        parts, combinators = _tokenize(g)
        if parts:
            out.append(([_parse_compound(p) for p in parts], combinators))
    return out


def _tokenize(group):
    parts = []
    combinators = []
    token = ""
    depth = 0
    pending = None
    for ch in group:
        if ch in "([":
            depth += 1
            token += ch
        elif ch in ")]":
            depth = max(0, depth - 1)
            token += ch
        elif depth == 0 and ch == ">":
            if token:
                parts.append(token)
                token = ""
            pending = ">"
        elif depth == 0 and ch.isspace():
            if token:
                parts.append(token)
                token = ""
            if pending is None:
                pending = " "
        else:
            if token == "" and pending is not None and parts:
                combinators.append(pending)
                pending = None
            token += ch
    if token:
        if pending is not None and parts:
            combinators.append(pending)
        parts.append(token)
    return parts, combinators


def _match_compound(el, c):
    if c.tag and c.tag != "*" and el.tag != c.tag:
        return False
    if c.eid is not None and el.id != c.eid:
        return False
    if c.classes:
        elc = el.classes
        for cl in c.classes:
            if cl not in elc:
                return False
    for name, op, val in c.attrs:
        if name not in el.attrs:
            return False
        if op is None:
            continue
        av = el.attrs.get(name, "")
        if op == "=":
            if av != val:
                return False
        elif op == "~=":
            if val not in _WS.split(av):
                return False
        elif op == "^=":
            if not av.startswith(val):
                return False
        elif op == "$=":
            if not av.endswith(val):
                return False
        elif op == "*=":
            if val not in av:
                return False
        elif op == "|=":
            if not (av == val or av.startswith(val + "-")):
                return False
    return True


def _match_chain(el, parts, combinators):
    if not _match_compound(el, parts[-1]):
        return False
    if len(parts) == 1:
        return True
    # Iterative backwards search over ancestors (order is irrelevant for a
    # boolean match), so deep documents cannot exhaust the recursion limit.
    stack = [(el, len(parts) - 2)]
    while stack:
        node, idx = stack.pop()
        if idx < 0:
            return True
        comb = combinators[idx] if idx < len(combinators) else " "
        target = parts[idx]
        if comb == ">":
            parent = node.parent
            if parent is None or parent.tag == "#document":
                continue
            if _match_compound(parent, target):
                stack.append((parent, idx - 1))
        else:
            anc = node.parent
            while anc is not None and anc.tag != "#document":
                if _match_compound(anc, target):
                    stack.append((anc, idx - 1))
                anc = anc.parent
    return False


def query(root, selector):
    """Return matching elements for a subset of CSS selectors."""
    results = []
    groups = _split_selector(selector)
    if not groups:
        return results
    for el in root.iter_elements():
        for parts, combinators in groups:
            if _match_chain(el, parts, combinators):
                results.append(el)
                break
    return results


def parse_html(text):
    p = _Parser()
    try:
        p.feed(text)
        p.close()
    except Exception:
        # HTMLParser is very tolerant; close() can still raise on malformed
        # declarations.  Callers surface this as PARSE_ERROR.
        raise
    return p.root, p.styles
