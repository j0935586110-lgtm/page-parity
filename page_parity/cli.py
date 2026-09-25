"""CLI contract for page-parity (agent-first, single-line JSON by default)."""

from __future__ import annotations

import hashlib
import json
import os
import sys

from . import __version__
from . import config as configmod
from . import l1 as l1mod

HELP = (
    "page-parity - cross-page parity + overflow checks\n"
    "usage: page-parity check (--dir D | --urls F) [--l1] [--l2]\n"
    "       [--only a1,a2,a3] [--widths 320,360] [--format json|human|both]\n"
    "       [--config C] [--recursive] [--tol N] [--details-out F]\n"
    "       --help | --schema | --self-test | details URL\n"
)

CODES = [
    "MISSING_ON_PAGE", "VALUE_DRIFT", "ORPHAN_PAGE",
    "ELEMENT_OVERFLOW", "PAGE_OVERFLOW", "FIXED_OBSCURES",
    "PARSE_ERROR", "NO_BROWSER", "ABSENT_EVERYWHERE",
    "ENCODING_UNCERTAIN", "CSR_SHELL_DETECTED",
]

SCHEMA = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "$id": "https://page-parity.example/check.schema.json",
    "title": "page-parity check output",
    "type": "object",
    "additionalProperties": False,
    "required": ["verdict", "exit_reason", "codes", "counts", "details_url"],
    "properties": {
        "verdict": {"enum": ["ok", "findings", "indeterminate", "usage", "internal"]},
        "exit_reason": {"enum": ["OK", "FINDINGS", "INDETERMINATE", "USAGE", "INTERNAL"]},
        "codes": {
            "type": "array",
            "uniqueItems": True,
            "items": {"enum": CODES},
        },
        "counts": {
            "type": "object",
            "additionalProperties": {"type": "integer", "minimum": 0},
        },
        "details_url": {"type": "string"},
    },
}

EXIT_BY_VERDICT = {
    "ok": 0,
    "findings": 1,
    "indeterminate": 2,
    "usage": 3,
    "internal": 4,
}


class UsageError(Exception):
    pass


# ---------------------------------------------------------------------------
# arguments
# ---------------------------------------------------------------------------

def _parse_check_args(args):
    opts = {
        "dir": None, "urls": None, "recursive": False,
        "l1": False, "l2": False, "only": None,
        "widths": None, "tol": 2,
        "format": "json", "config": None, "details_out": None,
    }
    i = 0
    n = len(args)
    while i < n:
        arg = args[i]
        if arg == "--dir" or arg == "--urls" or arg == "--only" or arg == "--widths" \
                or arg == "--format" or arg == "--config" or arg == "--details-out" or arg == "--tol":
            if i + 1 >= n:
                raise UsageError("missing value for %s" % arg)
            val = args[i + 1]
            if arg == "--dir":
                opts["dir"] = val
            elif arg == "--urls":
                opts["urls"] = val
            elif arg == "--only":
                opts["only"] = [c.strip() for c in val.split(",") if c.strip()]
            elif arg == "--widths":
                try:
                    opts["widths"] = [int(x) for x in val.split(",") if x.strip()]
                except ValueError:
                    raise UsageError("--widths takes a comma list of integers")
            elif arg == "--format":
                if val not in ("json", "human", "both"):
                    raise UsageError("--format must be json|human|both")
                opts["format"] = val
            elif arg == "--config":
                opts["config"] = val
            elif arg == "--details-out":
                opts["details_out"] = val
            elif arg == "--tol":
                try:
                    opts["tol"] = int(val)
                except ValueError:
                    raise UsageError("--tol takes an integer")
            i += 2
            continue
        if arg.startswith("--") and "=" in arg:
            key, val = arg.split("=", 1)
            args = args[:i] + [key, val] + args[i + 1:]
            n += 1
            continue
        if arg == "--l1":
            opts["l1"] = True
        elif arg == "--l2":
            opts["l2"] = True
        elif arg == "--recursive":
            opts["recursive"] = True
        elif arg in ("-h", "--help"):
            raise UsageError("__help__")
        else:
            raise UsageError("unknown argument: %s" % arg)
        i += 1
    return opts


# ---------------------------------------------------------------------------
# output helpers
# ---------------------------------------------------------------------------

def _details_path(opts, details):
    if opts.get("details_out"):
        return os.path.abspath(opts["details_out"])
    digest = hashlib.sha1()
    digest.update(json.dumps(details.get("input", {}), sort_keys=True).encode("utf-8"))
    digest.update(json.dumps(details.get("summary", {}), sort_keys=True).encode("utf-8"))
    name = "details-%s.json" % digest.hexdigest()[:16]
    return os.path.join(os.getcwd(), ".page-parity", name)


def _write_details(details, opts):
    path = _details_path(opts, details)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    payload = json.dumps(details, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(payload)
    import pathlib
    return pathlib.Path(path).as_uri()


def _envelope(verdict, codes, counts, details_url):
    return {
        "verdict": verdict,
        "exit_reason": {
            "ok": "OK", "findings": "FINDINGS",
            "indeterminate": "INDETERMINATE", "usage": "USAGE", "internal": "INTERNAL",
        }[verdict],
        "codes": sorted(set(codes)),
        "counts": counts,
        "details_url": details_url,
    }


def _emit(envelope, details, opts, human):
    fmt = opts.get("format", "json")
    out = sys.stdout
    if fmt in ("json", "both"):
        line = json.dumps(envelope, ensure_ascii=False, separators=(",", ":"))
        out.write(line + "\n")
        sys.stderr.write(human + "\n")
    elif fmt == "human":
        out.write(human + "\n")
    out.flush()


def _human_summary(envelope, details):
    counts = envelope["counts"]
    codes = ",".join(envelope["codes"]) or "-"
    l1n = details.get("l1", {}).get("finding_count", 0) if details.get("l1") else 0
    l2n = details.get("l2", {}).get("finding_count", 0) if details.get("l2") else 0
    first = "page-parity: %s; %s page(s), %s finding(s) [%s]" % (
        envelope["verdict"], counts.get("pages", 0), counts.get("findings", 0), codes)
    second = "L1=%d L2=%d" % (l1n, l2n)
    advisories = counts.get("advisories", counts.get("absent_everywhere", 0))
    if advisories:
        second += " advisory=%d (not counted)" % advisories
    second += "; details: %s" % (envelope["details_url"] or "-")
    return first + "\n" + second


def _human_report(details):
    lines = []
    l1 = details.get("l1")
    if l1:
        a1 = l1.get("a1") or {"items": []}
        for item in a1["items"]:
            if item.get("verdict") == "absent_everywhere":
                status = "%d/%d ABSENT_EVERYWHERE (advisory)" % (item["present"], item["total"])
            elif item["present"] == item["total"]:
                status = "OK"
            else:
                status = "%d/%d" % (item["present"], item["total"])
            lines.append("[A1] %-12s %s" % (item["id"], status))
            for exc in item["missing_excepted"]:
                lines.append("      excepted %s: %s" % (exc["page"], exc["reason"]))
            if item.get("verdict") != "absent_everywhere":
                for miss in item["missing"]:
                    lines.append("      MISSING_ON_PAGE %s" % miss)
            if item["values"]:
                for value, pages in item["values"].items():
                    lines.append("      value %s -> %s" % (value, ",".join(pages)))
        a2 = l1.get("a2")
        if a2:
            lines.append("[A2] checked=%d scoped_ignored=%d drifted=%d" % (
                a2["checked"], a2["scoped_ignored"], len(a2["drifted"])))
            for var in a2["drifted"]:
                lines.append("      VALUE_DRIFT %s -> %s" % (var["name"], var["values"]))
        a3 = l1.get("a3")
        if a3:
            lines.append("[A3] orphans=%d (excepted=%d)" % (
                len(a3["orphans"]), len(a3["orphan_exceptions"])))
            for entry in a3["orphans_all"]:
                note = entry.get("exception", "not linked by any page")
                lines.append("      %s: %s" % (entry["page"], note))
    l2 = details.get("l2")
    if l2 and l2.get("offenders") is not None:
        lines.append("[L2] widths=%s tol=%dpx offenders=%d" % (
            ",".join(str(w) for w in l2["widths"]), l2["tol"], len(l2["offenders"])))
        for off in l2["offenders"][:40]:
            if off["code"] == "ELEMENT_OVERFLOW":
                lines.append("      %s @%d %s (%s->%s, %s)" % (
                    off["code"], off["width"], off["selector"],
                    off["client_width"], off["scroll_width"], off["overflow_px"]))
            else:
                lines.append("      %s @%d %s" % (off["code"], off["width"], off["selector"]))
        for adv in l2.get("advisories", []):
            lines.append("      %s @%d %s (advisory: consent/cookie chrome)" % (
                adv["code"], adv["width"], adv["selector"]))
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# check command
# ---------------------------------------------------------------------------

def _run_check(args):
    try:
        opts = _parse_check_args(args)
    except UsageError as exc:
        if str(exc) == "__help__":
            sys.stdout.write(HELP)
            return 0
        sys.stderr.write("usage error: %s\n" % exc)
        sys.stderr.write(HELP)
        return 3

    # decide which layers run
    only = opts["only"]
    if only is not None:
        unknown = [c for c in only if c not in ("a1", "a2", "a3")]
        if unknown:
            sys.stderr.write("usage error: unknown check(s): %s\n" % ",".join(unknown))
            return 3
    # Confine a *relative* --details-out to the working directory: a derived
    # path must never climb out with "..".  An absolute path is allowed because
    # the caller typed it explicitly (it is their own filesystem target).
    if opts["details_out"] and not os.path.isabs(opts["details_out"]):
        cwd = os.path.abspath(os.getcwd())
        target = os.path.abspath(opts["details_out"])
        try:
            inside = os.path.commonpath([cwd, target]) == cwd
        except ValueError:
            inside = False
        if not inside:
            sys.stderr.write(
                "usage error: relative --details-out must stay under cwd: %s\n"
                % opts["details_out"])
            return 3
    run_l1 = opts["l1"] or only is not None or not opts["l2"]
    run_l2 = opts["l2"]
    if only is None:
        only = ["a1", "a2", "a3"]

    details = {
        "tool": "page-parity",
        "version": __version__,
        "input": {"dir": opts["dir"], "urls": opts["urls"], "recursive": opts["recursive"]},
        "summary": {"l1": run_l1, "l2": run_l2, "only": only, "widths": opts["widths"], "tol": opts["tol"]},
        "l1": None,
        "l2": None,
        "findings": [],
        "advisories": [],
    }

    if not opts["dir"] and not opts["urls"]:
        env = _envelope("indeterminate", ["PARSE_ERROR"], {"pages": 0, "findings": 0}, "")
        _emit(env, details, opts, _human_summary(env, details))
        return 2

    # config
    try:
        cfg = configmod.load(opts["config"])
    except Exception as exc:  # noqa: BLE001
        sys.stderr.write("config error: %s\n" % exc)
        env = _envelope("indeterminate", ["PARSE_ERROR"], {"pages": 0, "findings": 0}, "")
        _emit(env, details, opts, _human_summary(env, details))
        return 2

    site, errors = l1mod.build_site(
        directory=opts["dir"], urls_file=opts["urls"], recursive=opts["recursive"])
    codes = []
    if errors:
        codes.append("PARSE_ERROR")
    if site is None:
        details["errors"] = errors
        env = _envelope("indeterminate", codes or ["PARSE_ERROR"],
                        {"pages": 0, "findings": 0}, "")
        _emit(env, details, opts, _human_summary(env, details))
        return 2

    if not site.pages:
        details["errors"] = errors + ["no html pages found in input"]
        env = _envelope("indeterminate", codes,
                        {"pages": 0, "findings": 0}, "")
        _emit(env, details, opts, _human_summary(env, details))
        return 2

    if run_l1:
        l1 = l1mod.run_l1(site, cfg, only=only)
        l1["finding_count"] = len(l1["findings"])
        details["l1"] = l1
        details["findings"].extend(l1["findings"])
        details["advisories"].extend(l1["advisories"])
        codes.extend(l1["codes"])

    if run_l2:
        from . import l2 as l2mod
        try:
            l2 = l2mod.run_l2(
                [(p.rel, p.abspath) for p in site.pages],
                widths=opts["widths"], tol=opts["tol"])
            l2["finding_count"] = len(l2["findings"])
            details["l2"] = l2
            details["findings"].extend(l2["findings"])
            details["advisories"].extend(l2.get("advisories", []))
            for f in l2["findings"]:
                codes.append(f["code"])
            for a in l2.get("advisories", []):
                codes.append(a["code"])
            if l2["errors"]:
                codes.append("PARSE_ERROR")
        except l2mod.NoBrowser as exc:
            details["l2"] = {"error": "NO_BROWSER", "message": str(exc),
                             "findings": [], "finding_count": 0}
            codes.append("NO_BROWSER")

    details["errors"] = errors
    codes = sorted(set(codes))
    finding_count = len(details["findings"])
    counts = {"pages": len(site.pages), "findings": finding_count}
    absent = sum(1 for a in details["advisories"] if a["code"] == "ABSENT_EVERYWHERE")
    if absent:
        counts["absent_everywhere"] = absent
    if len(details["advisories"]) > absent:
        counts["advisories"] = len(details["advisories"])

    hard_error = bool(errors) or "NO_BROWSER" in codes or "PARSE_ERROR" in codes
    if hard_error:
        verdict = "indeterminate"
    elif finding_count:
        verdict = "findings"
    else:
        verdict = "ok"

    details_url = _write_details(details, opts)
    env = _envelope(verdict, codes, counts, details_url)
    human = _human_summary(env, details)
    if opts.get("format") == "human":
        human = _human_report(details) + "\n" + human
    _emit(env, details, opts, human)
    return EXIT_BY_VERDICT[verdict]


# ---------------------------------------------------------------------------
# details / meta commands
# ---------------------------------------------------------------------------

def _run_details(args):
    if not args:
        sys.stderr.write("usage: page-parity details URL\n")
        return 3
    import urllib.parse
    url = args[0]
    if url.startswith("file://"):
        path = urllib.parse.unquote(urllib.parse.urlparse(url).path)
    else:
        path = url
    try:
        with open(path, encoding="utf-8") as fh:
            data = fh.read()
    except OSError as exc:
        sys.stderr.write("cannot read details: %s\n" % exc)
        return 2
    try:
        parsed = json.loads(data)
    except ValueError as exc:
        sys.stderr.write("details is not valid json: %s\n" % exc)
        return 2
    sys.stdout.write(json.dumps(parsed, indent=2, ensure_ascii=False, sort_keys=True) + "\n")
    return 0


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    if not argv:
        sys.stderr.write(HELP)
        return 3
    cmd = argv[0]
    if cmd in ("-h", "--help", "help"):
        sys.stdout.write(HELP)
        return 0
    if cmd == "--version":
        sys.stdout.write("page-parity %s\n" % __version__)
        return 0
    if cmd == "--schema":
        sys.stdout.write(json.dumps(SCHEMA, indent=2, sort_keys=True) + "\n")
        return 0
    if cmd == "--self-test":
        from . import selftest
        return selftest.run()
    if cmd == "check":
        try:
            return _run_check(argv[1:])
        except Exception as exc:  # noqa: BLE001 - last-resort contract guard
            sys.stderr.write("internal error: %s\n" % exc)
            env = _envelope("internal", [], {"pages": 0, "findings": 0}, "")
            sys.stdout.write(json.dumps(env, ensure_ascii=False, separators=(",", ":")) + "\n")
            return 4
    if cmd == "details":
        return _run_details(argv[1:])
    sys.stderr.write("unknown command: %s\n" % cmd)
    sys.stderr.write(HELP)
    return 3


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
