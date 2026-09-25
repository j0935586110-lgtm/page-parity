"""Built-in ``--self-test``: positive and negative controls on synthetic sites.

Everything here is synthetic and generic.  The negative control is explicit:
a deliberately broken sample MUST be judged as findings (never a clean pass).
"""

from __future__ import annotations

import contextlib
import io
import json
import os
import tempfile

from . import cli
from . import config as configmod
from . import dom as dommod
from . import l1 as l1mod
from . import l2 as l2mod

PAGE = """<!DOCTYPE html>
<html lang="{lang}"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{title}</title>
{head}
<style>
:root {{ --brand: {brand}; {vars} }}
{scoped}
</style>
</head><body>
{chrome}
</body></html>
"""

NAV = ('<nav><a href="index.html">Home</a><a href="one.html">One</a>'
       '<a href="two.html">Two</a></nav>')
FOOTER = "<footer>page-parity synthetic footer</footer>"


def _write(dirpath, name, brand="#111111", vars_="--t:0.3s;", scoped="",
           nav=True, footer=True, lang="en", head="", chrome_extra=""):
    html = PAGE.format(
        title=name, lang=lang, brand=brand, vars=vars_, scoped=scoped,
        head=head,
        chrome=(NAV if nav else "") + (FOOTER if footer else "") + chrome_extra,
    )
    with open(os.path.join(dirpath, name), "w", encoding="utf-8") as fh:
        fh.write(html)


def _small_config():
    return configmod.from_mapping({
        "items": [
            {"id": "menu", "kind": "selector", "selector": "nav a",
             "scope": "all", "compare": "set"},
            {"id": "footer", "kind": "selector", "selector": "body > footer",
             "scope": "all", "compare": "text"},
        ]
    }, "<self-test>")


def _raw_page(links=(), head="", footer=True, nav_container=None, extra=""):
    ahrefs = "".join('<a href="%s">%s</a>' % (h, h) for h in links)
    nav = nav_container if nav_container is not None else ("<nav>%s</nav>" % ahrefs)
    foot = "<footer>page-parity synthetic footer</footer>" if footer else ""
    return ("<!DOCTYPE html><html lang='en'><head><meta charset='utf-8'>"
            "<meta name='viewport' content='width=device-width, initial-scale=1'>"
            "%s</head><body>%s%s%s</body></html>" % (head, nav, foot, extra))


def _write_raw(dirpath, name, text):
    with open(os.path.join(dirpath, name), "w", encoding="utf-8") as fh:
        fh.write(text)


def _run_cli_capture(args):
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(buf):
        rc = cli.main(args)
    return rc, buf.getvalue()


def _details_from_stdout(text):
    line = next((ln for ln in text.splitlines() if ln.strip().startswith("{")), "")
    if not line:
        return {}
    try:
        envelope = json.loads(line)
    except ValueError:
        return {}
    url = envelope.get("details_url", "")
    path = url[7:] if url.startswith("file://") else url
    try:
        with open(path, encoding="utf-8") as fh:
            return json.load(fh)
    except OSError:
        return {}


class Runner:
    def __init__(self):
        self.passed = 0
        self.failed = 0
        self.lines = []

    def check(self, name, condition, detail=""):
        if condition:
            self.passed += 1
            self.lines.append("PASS %s" % name)
        else:
            self.failed += 1
            self.lines.append("FAIL %s %s" % (name, detail))

    def report(self):
        for line in self.lines:
            print(line)
        print("--self-test: %d passed, %d failed" % (self.passed, self.failed))
        return 0 if self.failed == 0 else 4


def _run_site(directory, config=None):
    site, errors = l1mod.build_site(directory=directory)
    assert not errors, errors
    return l1mod.run_l1(site, config or _small_config())


def run():
    r = Runner()
    with tempfile.TemporaryDirectory(prefix="page-parity-selftest-") as tmp:
        clean = os.path.join(tmp, "clean")
        os.makedirs(clean)
        for name in ("index.html", "one.html", "two.html"):
            _write(clean, name)
        res = _run_site(clean)
        r.check("clean site has no findings", len(res["findings"]) == 0,
                str(res["findings"]))
        r.check("clean site codes empty", res["codes"] == [], str(res["codes"]))

        # v1.1 §1.1: an item absent on *every* page is a site-wide absence, not a
        # per-page inconsistency.  It must be reported (ABSENT_EVERYWHERE) yet
        # must NOT flip the verdict or the exit code.
        absent = os.path.join(tmp, "absent")
        os.makedirs(absent)
        for name in ("index.html", "one.html", "two.html"):
            _write(absent, name)
        absent_cfg = os.path.join(tmp, "absent.toml")
        with open(absent_cfg, "w", encoding="utf-8") as fh:
            fh.write('[[items]]\nid = "ghost"\nkind = "css_backdrop"\n'
                     'scope = "all"\ncompare = "none"\n')
        import contextlib
        import io
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(buf):
            rc = cli.main(["check", "--dir", absent, "--config", absent_cfg,
                           "--details-out", os.path.join(tmp, "absent-details.json")])
        r.check("NEGATIVE CONTROL absent-everywhere does not affect exit code",
                rc == 0, "rc=%d" % rc)
        ares = _run_site(absent, configmod.from_mapping(
            {"items": [{"id": "ghost", "kind": "css_backdrop",
                        "scope": "all", "compare": "none"}]},
            "<self-test>"))
        r.check("absent-everywhere is advisory, not a finding",
                len(ares["findings"]) == 0
                and [a["code"] for a in ares["advisories"]] == ["ABSENT_EVERYWHERE"],
                str(ares.get("advisories")))
        r.check("absent-everywhere item verdict",
                ares["a1"]["items"][0]["verdict"] == "absent_everywhere",
                str(ares["a1"]["items"][0].get("verdict")))
        r.check("absent-everywhere never produces MISSING_ON_PAGE",
                "MISSING_ON_PAGE" not in ares["codes"], str(ares["codes"]))

        broken = os.path.join(tmp, "broken")
        os.makedirs(broken)
        _write(broken, "index.html", chrome_extra="")
        # one.html: no nav, different brand value -> MISSING_ON_PAGE + VALUE_DRIFT
        _write(broken, "one.html", brand="#222222", nav=False)
        # two.html: orphan (nothing links to it)
        _write(broken, "two.html", nav=True)
        # rewrite index so it never links two.html
        with open(os.path.join(broken, "index.html"), "w", encoding="utf-8") as fh:
            fh.write("<html lang='en'><head><style>:root{--brand:#111111;--t:0.3s}</style></head>"
                     "<body><nav><a href='index.html'>Home</a><a href='one.html'>One</a></nav>"
                     "<footer>page-parity synthetic footer</footer></body></html>")
        with open(os.path.join(broken, "one.html"), "a", encoding="utf-8") as fh:
            fh.write("")  # keep
        # make one.html also link two.html is NOT desired; keep one -> index only
        bres = _run_site(broken)
        codes = set(bres["codes"])
        # NEGATIVE CONTROL: broken must be judged as findings, not clean.
        r.check("NEGATIVE CONTROL broken site judged FAIL", len(bres["findings"]) > 0)
        r.check("broken: MISSING_ON_PAGE detected", "MISSING_ON_PAGE" in codes, str(codes))
        r.check("broken: VALUE_DRIFT detected", "VALUE_DRIFT" in codes, str(codes))
        r.check("broken: ORPHAN_PAGE detected", "ORPHAN_PAGE" in codes, str(codes))

        # value normalisation: 0.3s vs .3s must not drift
        norm = os.path.join(tmp, "norm")
        os.makedirs(norm)
        _write(norm, "index.html", vars_="--t:0.3s;")
        _write(norm, "one.html", vars_="--t:.3s;")
        _write(norm, "two.html", vars_="--t:0.3s;")
        nres = _run_site(norm)
        r.check("0.3s vs .3s is not drift", "VALUE_DRIFT" not in nres["codes"],
                str(nres["codes"]))

        norm2 = os.path.join(tmp, "norm2")
        os.makedirs(norm2)
        _write(norm2, "index.html", vars_="--t:0.05;")
        _write(norm2, "one.html", vars_="--t:.05;")
        _write(norm2, "two.html", vars_="--t:0.05;")
        n2 = _run_site(norm2)
        r.check("0.05 vs .05 is not drift", "VALUE_DRIFT" not in n2["codes"], str(n2["codes"]))

        # comments must be stripped
        cmt = os.path.join(tmp, "comment")
        os.makedirs(cmt)
        _write(cmt, "index.html", vars_="/* --t:9s; */ --t:.3s;")
        _write(cmt, "one.html", vars_="--t:.3s;")
        _write(cmt, "two.html", vars_="--t:.3s;")
        cres = _run_site(cmt)
        r.check("commented declaration ignored", "VALUE_DRIFT" not in cres["codes"],
                str(cres["codes"]))

        # scoped variables must not drift
        scoped = os.path.join(tmp, "scoped")
        os.makedirs(scoped)
        _write(scoped, "index.html", scoped=".widget { --paint: #111111; }")
        _write(scoped, "one.html", scoped=".widget { --paint: #222222; }")
        _write(scoped, "two.html", scoped=".widget { --paint: #111111; }")
        sres = _run_site(scoped)
        r.check("scoped variable not reported as drift",
                "VALUE_DRIFT" not in sres["codes"], str(sres["codes"]))
        r.check("scoped variable counted as ignored",
                sres["a2"]["scoped_ignored"] >= 3, str(sres["a2"]))

        # nested @media :root still global
        nested = os.path.join(tmp, "nested")
        os.makedirs(nested)
        media = "@media (min-width: 1px) { :root { --t: 0.3s; } }"
        nested_html = ("<html lang='en'><head><style>%s</style></head><body>"
                       "<nav><a href='index.html'>H</a></nav><footer>f</footer></body></html>")
        for name in ("index.html", "one.html", "two.html"):
            with open(os.path.join(nested, name), "w", encoding="utf-8") as fh:
                fh.write(nested_html % media)
        nres2 = _run_site(nested)
        r.check("nested @media :root is global and not drift",
                "VALUE_DRIFT" not in nres2["codes"] and nres2["a2"]["checked"] >= 3,
                str(nres2["codes"]))

        # redirect page is a reasonable exception for orphan + missing chrome
        redir = os.path.join(tmp, "redirect")
        os.makedirs(redir)
        _write(redir, "index.html")
        _write(redir, "one.html")
        _write(redir, "two.html")
        with open(os.path.join(redir, "legacy.html"), "w", encoding="utf-8") as fh:
            fh.write("<html lang='en'><head><link rel='canonical' href='index.html'>"
                     "<meta name='robots' content='noindex'><meta http-equiv='refresh' content='0;url=index.html'>"
                     "</head><body>moved</body></html>")
        rres = _run_site(redir)
        a3 = rres["a3"]
        r.check("redirect page is an orphan exception",
                any(e["page"] == "legacy.html" for e in a3["orphan_exceptions"]))
        r.check("redirect orphan is not a finding",
                all(f.get("page") != "legacy.html" for f in a3["findings"]))
        r.check("redirect page missing menu is excepted",
                any(e["page"] == "legacy.html"
                    for it in rres["a1"]["items"] if it["id"] == "menu"
                    for e in it["missing_excepted"]))

        # ------------------------------------------------------------------
        # P0-A path traversal: a stylesheet outside the site root must never be
        # read (positive control: an in-tree stylesheet IS read).
        # ------------------------------------------------------------------
        trav = os.path.join(tmp, "traversal")
        site_dir = os.path.join(trav, "site")
        os.makedirs(site_dir)
        with open(os.path.join(trav, "a.css"), "w", encoding="utf-8") as fh:
            fh.write(":root{--probe:LEAK_A_111111;}")
        with open(os.path.join(trav, "b.css"), "w", encoding="utf-8") as fh:
            fh.write(":root{--probe:LEAK_B_222222;}")
        _write_raw(site_dir, "index.html", _raw_page(
            links=("index.html", "other.html"), head='<link rel="stylesheet" href="../a.css">'))
        _write_raw(site_dir, "other.html", _raw_page(
            links=("index.html", "other.html"), head='<link rel="stylesheet" href="../b.css">'))
        out_path = os.path.join(trav, "traversal-details.json")
        trec, tout = _run_cli_capture(["check", "--dir", site_dir, "--only", "a2",
                                       "--details-out", out_path])
        with open(out_path, encoding="utf-8") as fh:
            tdetails = fh.read()
        r.check("NEGATIVE CONTROL out-of-root CSS is not read",
                "--probe" not in tdetails and "LEAK_" not in tdetails,
                "exposed=%s" % ("yes" if "--probe" in tdetails else "no"))
        r.check("out-of-root CSS judged remote (no A2 findings)", trec == 0, "rc=%d" % trec)
        inside = os.path.join(tmp, "inside")
        os.makedirs(inside)
        with open(os.path.join(inside, "tokens.css"), "w", encoding="utf-8") as fh:
            fh.write(":root{--probe:INSIDE;}")
        _write_raw(inside, "index.html", _raw_page(
            links=("index.html",), head='<link rel="stylesheet" href="tokens.css">'))
        irec, iout = _run_cli_capture(["check", "--dir", inside, "--only", "a2",
                                       "--details-out", os.path.join(inside, "d.json")])
        idet = _details_from_stdout(iout)
        r.check("POSITIVE CONTROL in-root CSS IS read",
                idet.get("l1", {}).get("a2", {}).get("checked", 0) >= 1,
                "checked=%s" % idet.get("l1", {}).get("a2", {}).get("checked"))

        # ------------------------------------------------------------------
        # P0-B @media re-declaration of one variable is not cross-page drift.
        # ------------------------------------------------------------------
        mq = os.path.join(tmp, "media")
        os.makedirs(mq)
        with open(os.path.join(mq, "styles.css"), "w", encoding="utf-8") as fh:
            fh.write(":root{--fs:14px;}\n@media (min-width:768px){:root{--fs:16px;}}\n")
        head = '<link rel="stylesheet" href="styles.css">'
        for name in ("index.html", "one.html", "two.html"):
            _write_raw(mq, name, _raw_page(links=("index.html", "one.html", "two.html"), head=head))
        mres = _run_site(mq)
        r.check("NEGATIVE CONTROL @media same-var re-declaration is not drift",
                "VALUE_DRIFT" not in mres["codes"], str(mres["codes"]))
        r.check("@media declaration still counted by A2",
                mres["a2"]["checked"] >= 6, "checked=%d" % mres["a2"]["checked"])
        mq2 = os.path.join(tmp, "media-diff")
        os.makedirs(mq2)
        with open(os.path.join(mq2, "styles.css"), "w", encoding="utf-8") as fh:
            fh.write(":root{--fs:14px;}\n@media (min-width:768px){:root{--fs:16px;}}\n")
        with open(os.path.join(mq2, "other.css"), "w", encoding="utf-8") as fh:
            fh.write(":root{--fs:14px;}\n@media (min-width:768px){:root{--fs:18px;}}\n")
        _write_raw(mq2, "index.html", _raw_page(links=("index.html", "one.html"), head=head))
        _write_raw(mq2, "one.html", _raw_page(
            links=("index.html", "one.html"), head='<link rel="stylesheet" href="other.css">'))
        m2 = _run_site(mq2)
        r.check("POSITIVE CONTROL different @media value still drifts",
                "VALUE_DRIFT" in m2["codes"], str(m2["codes"]))

        # ------------------------------------------------------------------
        # P1-C clean URLs (``/`` and ``/about/``) resolve to real files.
        # ------------------------------------------------------------------
        cu = os.path.join(tmp, "cleanurls")
        os.makedirs(cu)
        _write_raw(cu, "index.html", _raw_page(links=("/", "/about/")))
        _write_raw(cu, "about.html", _raw_page(links=("/", "/about/")))
        cures = _run_site(cu)
        r.check("NEGATIVE CONTROL clean URLs not judged orphans",
                "ORPHAN_PAGE" not in cures["codes"], str(cures["codes"]))
        cu2 = os.path.join(tmp, "cleanurls-neg")
        os.makedirs(cu2)
        _write_raw(cu2, "index.html", _raw_page(links=("/",)))
        _write_raw(cu2, "lost.html", _raw_page(links=("/",)))
        c2 = _run_site(cu2)
        r.check("POSITIVE CONTROL a genuinely unlinked page is still an orphan",
                "ORPHAN_PAGE" in c2["codes"], str(c2["codes"]))

        # ------------------------------------------------------------------
        # P1-D entry page never an orphan; one-page site has no A3 at all.
        # ------------------------------------------------------------------
        entry = os.path.join(tmp, "entry")
        os.makedirs(entry)
        _write_raw(entry, "index.html", _raw_page(links=("one.html",)))
        _write_raw(entry, "one.html", _raw_page(links=("two.html",)))
        _write_raw(entry, "two.html", _raw_page(links=("one.html",)))
        eres = _run_site(entry)
        r.check("NEGATIVE CONTROL unlinked entry page is not an orphan",
                "ORPHAN_PAGE" not in eres["codes"]
                and any(e["page"] == "index.html" for e in eres["a3"]["orphan_exceptions"]),
                str(eres["a3"]))
        single = os.path.join(tmp, "single")
        os.makedirs(single)
        _write_raw(single, "index.html", _raw_page())
        sres = _run_site(single)
        r.check("single-page site reports no A3 finding",
                "ORPHAN_PAGE" not in sres["codes"] and not sres["a3"]["orphans"],
                str(sres["a3"]))

        # ------------------------------------------------------------------
        # P1-E consent/cookie fixed bars: advisory + dedupe, real scrim stays.
        # ------------------------------------------------------------------
        l2find, l2adv, l2off = l2mod.classify_fixed([
            {"code": "FIXED_OBSCURES", "page": "p.html", "selector": "#consent-bar",
             "width": 320, "consent_like": True},
            {"code": "FIXED_OBSCURES", "page": "p.html", "selector": "#consent-bar",
             "width": 1440, "consent_like": True},
            {"code": "FIXED_OBSCURES", "page": "q.html", "selector": "div.scrim",
             "width": 320, "consent_like": False},
        ])
        r.check("NEGATIVE CONTROL consent bar is advisory, deduped across widths",
                len(l2adv) == 1 and l2adv[0]["selector"] == "#consent-bar"
                and l2adv[0].get("advisory") is True,
                str(l2adv))
        r.check("POSITIVE CONTROL a real fixed scrim stays a finding",
                len(l2find) == 1 and l2find[0]["selector"] == "div.scrim",
                str(l2find))
        r.check("consent advisory is not mixed into offenders",
                all(o["selector"] != "#consent-bar" for o in l2off), str(l2off))

        # ------------------------------------------------------------------
        # P2-F default footer is ``body > footer``: an in-article footer is not
        # mistaken for the site footer.
        # ------------------------------------------------------------------
        artf = os.path.join(tmp, "article-footer")
        os.makedirs(artf)
        art_page = ("<!DOCTYPE html><html lang='en'><head><meta charset='utf-8'>"
                    "<meta name='viewport' content='width=device-width, initial-scale=1'>"
                    "</head><body><article>story<footer>2026-01-01</footer></article>"
                    "<nav><a href='index.html'>Home</a></nav></body></html>")
        _write_raw(artf, "index.html", art_page)
        default_cfg = configmod.from_mapping({}, "<self-test>")
        asite, aerr = l1mod.build_site(directory=artf)
        ares = l1mod.run_l1(asite, default_cfg)
        foot_item = next(i for i in ares["a1"]["items"] if i["id"] == "footer")
        r.check("NEGATIVE CONTROL <article><footer> is not the site footer",
                foot_item["present"] == 0, str(foot_item["present"]))
        realf = os.path.join(tmp, "body-footer")
        os.makedirs(realf)
        _write_raw(realf, "index.html", _raw_page(links=("index.html",)))
        rsite, _ = l1mod.build_site(directory=realf)
        rres2 = l1mod.run_l1(rsite, default_cfg)
        foot_item2 = next(i for i in rres2["a1"]["items"] if i["id"] == "footer")
        r.check("POSITIVE CONTROL body > footer is the site footer",
                foot_item2["present"] == 1, str(foot_item2["present"]))

        # ------------------------------------------------------------------
        # P2-G deep nesting must not exhaust the recursion limit.
        # ------------------------------------------------------------------
        deep = os.path.join(tmp, "deep")
        os.makedirs(deep)
        nested = "<div>" * 500 + "x" + "</div>" * 500
        _write_raw(deep, "index.html", _raw_page(links=("index.html",), extra=nested))
        dom_root, _ = dommod.parse_html(open(
            os.path.join(deep, "index.html"), encoding="utf-8").read())
        dn = dommod.query(dom_root, "div")
        r.check("NEGATIVE CONTROL 500-deep DOM does not RecursionError",
                len(dn) == 500 and dn[-1].text() == "x", "n=%d" % len(dn))
        deepest = "<div>" * 3000 + "y" + "</div>" * 3000
        droot, _ = dommod.parse_html(deepest)
        r.check("3000-deep DOM also safe", dommod.query(droot, "div")[-1].text() == "y")
        dres = _run_site(deep)
        r.check("deep page does not flip the verdict to internal error",
                dres is not None)

        # ------------------------------------------------------------------
        # P2-H non-UTF-8 pages are flagged uncertain, never silently "equal".
        # ------------------------------------------------------------------
        bad = os.path.join(tmp, "nonutf8")
        os.makedirs(bad)
        for name, blob in (("index.html", b"\xff\xfe"), ("one.html", b"\x80\x81")):
            data = ("<!DOCTYPE html><html lang='en'><head><meta charset='utf-8'></head>"
                    "<body><nav><a href='index.html'>a</a></nav><footer>").encode("ascii")
            data += blob
            data += b"</footer></body></html>"
            with open(os.path.join(bad, name), "wb") as fh:
                fh.write(data)
        bsite, berr = l1mod.build_site(directory=bad)
        r.check("NEGATIVE CONTROL lossy decode flags the page",
                all(p.encoding_uncertain for p in bsite.pages), str(berr))
        bres = l1mod.run_l1(bsite, _small_config())
        r.check("non-UTF-8 pages are reported as uncertain",
                any(a["code"] == "ENCODING_UNCERTAIN" for a in bres["advisories"]),
                str(bres["advisories"]))
        bfoot = next(i for i in bres["a1"]["items"] if i["id"] == "footer")
        r.check("non-UTF-8 values are excluded from equality claims",
                bfoot["values"] == {} and len(bfoot["uncertain_pages"]) == 2,
                str(bfoot))

        # ------------------------------------------------------------------
        # P2-I an empty navigation container is called out, not passed over.
        # ------------------------------------------------------------------
        csr = os.path.join(tmp, "csr")
        os.makedirs(csr)
        shell = _raw_page(links=(), nav_container='<nav id="app-nav"></nav>')
        _write_raw(csr, "index.html", shell)
        _write_raw(csr, "about.html", shell)
        csres = _run_site(csr)
        r.check("NEGATIVE CONTROL empty nav shell is surfaced",
                any(a["code"] == "CSR_SHELL_DETECTED" for a in csres["advisories"]),
                str(csres["advisories"]))
        full = os.path.join(tmp, "csr-full")
        os.makedirs(full)
        _write_raw(full, "index.html", _raw_page(links=("index.html", "about.html")))
        _write_raw(full, "about.html", _raw_page(links=("index.html", "about.html")))
        fres = _run_site(full)
        r.check("POSITIVE CONTROL populated nav is not a CSR shell",
                not any(a["code"] == "CSR_SHELL_DETECTED" for a in fres["advisories"]),
                str(fres["advisories"]))

        # ------------------------------------------------------------------
        # P0-A (write side): a relative --details-out may not climb out of cwd.
        # ------------------------------------------------------------------
        escdir = os.path.join(tmp, "escape")
        os.makedirs(escdir)
        _write_raw(escdir, "index.html", _raw_page(links=("index.html",)))
        cwd_ctx = contextlib.chdir(escdir) if hasattr(contextlib, "chdir") \
            else contextlib.nullcontext()
        with cwd_ctx:
            erc, _ = _run_cli_capture(["check", "--dir", escdir,
                                       "--details-out", os.path.join("..", "..", "pp-escape.json")])
        r.check("NEGATIVE CONTROL relative --details-out cannot escape cwd",
                erc == 3, "rc=%d" % erc)

        # idempotency of L1 serialisation
        a = json.dumps(_run_site(clean), sort_keys=True, ensure_ascii=False)
        b = json.dumps(_run_site(clean), sort_keys=True, ensure_ascii=False)
        r.check("L1 output is byte-stable", a == b)

    # contract checks
    r.check("--help <= 300 chars", len(cli.HELP) <= 300, "len=%d" % len(cli.HELP))
    try:
        parsed = json.loads(json.dumps(cli.SCHEMA))
        schema_ok = parsed.get("$schema", "").startswith("https://json-schema.org/") \
            and parsed.get("type") == "object"
    except Exception as exc:  # noqa: BLE001
        schema_ok = False
        parsed = exc
    r.check("--schema is valid JSON schema", schema_ok, str(parsed)[:80])
    r.check("exit code table", cli.EXIT_BY_VERDICT == {
        "ok": 0, "findings": 1, "indeterminate": 2, "usage": 3, "internal": 4})
    return r.report()
