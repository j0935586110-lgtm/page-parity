"""Small, tolerant CSS scanner used by the L1 checks.

It does not attempt to be a full CSS parser.  It only needs to:

* strip comments (so commented-out declarations never count),
* be nesting aware (blocks inside blocks, ``@media`` wrappers), and
* classify each custom-property declaration as *global* (declared under
  ``:root``/``html``) or *scoped* (declared under any other selector).

Only global declarations take part in cross-page drift comparison.  That is
what keeps intentionally scoped variables (for example a per-component colour
declared under ``.component``) from being reported as drift.
"""

from __future__ import annotations

import re

_COMMENT_RE = re.compile(r"/\*.*?\*/", re.S)
_WS = re.compile(r"\s+")
_GLOBAL_SELECTORS = {":root", "html", ":root, html"}


def strip_comments(css):
    return _COMMENT_RE.sub("", css)


class StyleRule:
    __slots__ = ("context", "at_context", "prelude", "decls")

    def __init__(self, context, at_context, prelude, decls):
        self.context = context      # tuple[str] of ancestor style-rule preludes
        self.at_context = at_context  # tuple[str] of ancestor at-rule preludes
        self.prelude = prelude      # this rule's selector text
        self.decls = decls          # list[(name, value)]

    @property
    def selectors(self):
        chain = list(self.context) + [self.prelude]
        out = []
        for frame in chain:
            out.extend([p.strip() for p in frame.split(",") if p.strip()])
        return out

    def context_key(self):
        """Stable identity of the *at-rule* nesting a declaration lives in.

        A custom property declared at the top level and the same property
        re-declared inside ``@media (min-width: 768px)`` are two different
        declarations.  Cross-page drift must compare like with like, otherwise
        a responsive breakpoint override would be misread as two rival values.
        """
        if not self.at_context:
            return ""
        return _WS.sub(" ", " ".join(self.at_context)).strip()


def _add_decl(block, text):
    text = text.strip()
    if not text:
        return
    # A declaration without a colon is not a declaration (e.g. a stray token).
    if ":" not in text:
        return
    name, value = text.split(":", 1)
    name = name.strip()
    if not name or name.startswith("@") or "{" in name or "}" in name:
        return
    block["decls"].append((name, value.strip()))


def iter_style_rules(css):
    """Yield every style rule (declaration block) with its ancestor context."""
    css = strip_comments(css)
    stack = []            # list[dict(prelude, decls, is_at)]
    buf = ""
    for ch in css:
        if ch == "{":
            prelude = buf.strip()
            buf = ""
            stack.append({"prelude": prelude, "decls": [], "is_at": prelude.startswith("@")})
        elif ch == "}":
            if stack:
                block = stack.pop()
                if not block["is_at"]:
                    context = tuple(
                        b["prelude"] for b in stack if not b["is_at"]
                    )
                    at_context = tuple(
                        b["prelude"] for b in stack if b["is_at"]
                    )
                    yield StyleRule(context, at_context, block["prelude"], block["decls"])
            buf = ""
        elif ch == ";":
            if stack and not stack[-1]["is_at"]:
                _add_decl(stack[-1], buf)
            buf = ""
        else:
            buf += ch
    # tolerate a trailing declaration without closing brace
    if stack and not stack[-1]["is_at"]:
        _add_decl(stack[-1], buf)


def _is_global_context(rule):
    chain = list(rule.context) + [rule.prelude]
    for frame in chain:
        parts = {p.strip() for p in frame.split(",") if p.strip()}
        if not (parts & _GLOBAL_SELECTORS):
            return False
    return True


def global_custom_props(css):
    """Yield (name, value, context_key) for global custom-property declarations."""
    for rule in iter_style_rules(css):
        if not _is_global_context(rule):
            continue
        for name, value in rule.decls:
            if name.startswith("--"):
                yield name, value, rule.context_key()


def all_custom_props(css):
    """Yield (name, value, is_global, context_key) for every custom property.

    ``context_key`` is the at-rule nesting (``@media`` ...) the declaration was
    found in, or ``""`` for a top-level declaration.
    """
    for rule in iter_style_rules(css):
        is_global = _is_global_context(rule)
        context_key = rule.context_key()
        for name, value in rule.decls:
            if name.startswith("--"):
                yield name, value, is_global, context_key


_BACKDROP_SELECTOR_RE = re.compile(
    r"^(?:(?:html|body)\s*::?\s*(?:before|after))$", re.I
)


def backdrop_layers(css):
    """Return the preludes of full-viewport pseudo-element background layers.

    A "watermark" in this tool's vocabulary is a decorative background image
    painted by ``html``/``body``'s ``::before``/``::after`` pseudo-element.
    Detection is purely structural, so it works on any site.
    """
    found = []
    for rule in iter_style_rules(css):
        parts = [p.strip() for p in rule.prelude.split(",") if p.strip()]
        if not any(_BACKDROP_SELECTOR_RE.match(p) for p in parts):
            continue
        for name, value in rule.decls:
            if name in ("background", "background-image") and "url(" in value.lower():
                found.append(rule.prelude)
                break
    return found
