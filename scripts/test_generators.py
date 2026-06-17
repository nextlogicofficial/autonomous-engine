#!/usr/bin/env python3
"""
test_generators.py — synthetic-change regression test for gen_feed.py and
gen_changes.py.

Why this exists (the bug it would have caught): on the 2026-06-16 nightly the
FIRST real price change in the changelog exposed a latent precedence bug in
gen_feed.py and gen_changes.py — the generic-change code path had simply never
run in five zero-change nights, so it shipped broken and unnoticed. A generator
that only ever sees "vendor_added" in production is untested on every other
change type until the day one occurs live. This test feeds BOTH generators a
synthetic changelog containing one entry of every change type they claim to
handle — plus a deliberately-unknown type to force the generic fallback — and
asserts the output is well-formed and complete, BEFORE a real change ever hits.

It runs the real generators against synthetic data in a temp dir (by pointing
their module-level path constants at fixtures), so it never touches the live
site/ or data/ files.

Usage:
    python3 scripts/test_generators.py          # run all checks, exit 1 on any failure
    python3 scripts/test_generators.py -q        # quiet: only the final PASS/FAIL line

Wire as a gate the same way selftest.py is — but this guards the GENERATORS
(do they render every change type?), where selftest guards the DEPLOYED SITE
(do the published counts/pages/feeds agree?). Run it after editing any
generator's label/describe logic.
"""
import json
import os
import sys
import tempfile
import importlib.util
from xml.dom import minidom
from html.parser import HTMLParser

SCRIPTS = os.path.dirname(os.path.abspath(__file__))

# Every change type the generators special-case, plus an UNKNOWN type to force
# the generic fallback path (the one that shipped broken on 2026-06-16). Each
# becomes one changelog entry with a distinct timestamp.
CHANGE_CASES = [
    ("baseline_created", {"vendor": "*", "new": "Initial snapshot of tracked vendors."}),
    ("vendor_added",     {"vendor": "acme", "new": "Acme AI"}),
    ("vendor_removed",   {"vendor": "acme", "old": "Acme AI"}),
    ("plan_added",       {"vendor": "acme", "plan": "Pro", "new": "Pro"}),
    ("plan_removed",     {"vendor": "acme", "plan": "Legacy", "old": "Legacy"}),
    ("price_change",     {"vendor": "acme", "plan": "Pro", "old": "$20", "new": "$25"}),
    ("price_month_changed", {"vendor": "beta", "plan": "Plus", "old": 7.99, "new": 4.99}),
    ("price_detail_changed", {"vendor": "beta", "plan": "Plus", "old": "200GB", "new": "400GB"}),
    ("limit_note_changed", {"vendor": "beta", "plan": "Plus", "old": "40/3h", "new": "80/3h"}),
    ("renamed",          {"vendor": "beta", "old": "Le Chat", "new": "Vibe"}),
    # Deliberately unknown — exercises the generic fallback in BOTH generators.
    ("frobnicated",      {"vendor": "acme", "plan": "Pro", "old": "x", "new": "y"}),
]

# A couple of synthetic vendors so vendor_names() resolves ids to display names.
SYNTH_LIMITS = {
    "generated_at": "2026-06-16T00:00:00Z",
    "vendors": [
        {"id": "acme", "name": "Acme AI (Test)", "plans": [
            {"id": "pro", "name": "Pro", "price_month": 25, "limit_notes": "synthetic"}]},
        {"id": "beta", "name": "Beta Labs", "plans": [
            {"id": "plus", "name": "Plus", "price_month": 4.99, "limit_notes": "synthetic"}]},
    ],
}

SYNTH_SNAP_INDEX = [
    {"file": "limits-2026-06-15.json", "date": "2026-06-15", "vendors": 2, "plans": 2},
    {"file": "limits-2026-06-16.json", "date": "2026-06-16", "vendors": 2, "plans": 2},
]


def build_changelog():
    entries = []
    for i, (change, fields) in enumerate(CHANGE_CASES):
        e = {"ts": "2026-06-1%dT0%d:00:00Z" % (5 + (i // 9), i % 9 + 1), "change": change}
        e.update(fields)
        entries.append(e)
    return entries


def load_module(name):
    spec = importlib.util.spec_from_file_location(name, os.path.join(SCRIPTS, name + ".py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class _WellFormed(HTMLParser):
    """Minimal well-formedness check: tags balance, parser doesn't choke."""
    def __init__(self):
        super().__init__()
        self.stack = []
        self.void = {"meta", "link", "br", "hr", "img", "input", "source", "area",
                     "base", "col", "embed", "param", "track", "wbr"}
    def handle_starttag(self, tag, attrs):
        if tag not in self.void:
            self.stack.append(tag)
    def handle_endtag(self, tag):
        if tag in self.void:
            return
        # pop to the matching open tag (tolerant of optional-close tags like <p>,<li>)
        if tag in self.stack:
            while self.stack and self.stack.pop() != tag:
                pass


class Results:
    def __init__(self):
        self.fails = []
        self.checks = 0
    def check(self, cond, msg):
        self.checks += 1
        if not cond:
            self.fails.append(msg)


def run_feed(tmp, changelog, R, quiet):
    data = os.path.join(tmp, "data"); site = os.path.join(tmp, "site")
    os.makedirs(data, exist_ok=True); os.makedirs(site, exist_ok=True)
    json.dump(changelog, open(os.path.join(data, "changelog.json"), "w"))
    json.dump(SYNTH_LIMITS, open(os.path.join(data, "limits.json"), "w"))

    gf = load_module("gen_feed")
    gf.CHANGELOG = os.path.join(data, "changelog.json")
    gf.LIMITS = os.path.join(data, "limits.json")
    gf.OUT = os.path.join(site, "feed.xml")
    _silence(gf.main, quiet)
    xml = open(gf.OUT).read()

    # 1. well-formed XML
    try:
        dom = minidom.parseString(xml)
        R.check(True, "")
    except Exception as ex:
        R.check(False, "gen_feed: feed.xml is NOT well-formed XML: %s" % ex)
        return xml
    # 2. one <item> per change
    n_items = len(dom.getElementsByTagName("item"))
    R.check(n_items == len(changelog),
            "gen_feed: expected %d <item>s, got %d" % (len(changelog), n_items))
    # 3. every item has non-empty title + description, and no literal "None" leaked
    for it in dom.getElementsByTagName("item"):
        title = _text(it, "title"); desc = _text(it, "description")
        R.check(bool(title.strip()), "gen_feed: an <item> has an empty <title>")
        R.check(bool(desc.strip()), "gen_feed: <item> '%s' has empty <description>" % title)
        R.check("None" not in title and "None" not in desc,
                "gen_feed: literal 'None' leaked into item '%s' (null not handled)" % title)
    # 4. the generic-fallback change rendered something sensible
    R.check(any("frobnicated" in _text(it, "title").lower() or
                "frobnicated" in _text(it, "description").lower()
                for it in dom.getElementsByTagName("item")),
            "gen_feed: unknown change type 'frobnicated' did not render via the generic fallback")
    return xml


def run_changes(tmp, changelog, R, quiet):
    data = os.path.join(tmp, "data"); site = os.path.join(tmp, "site")
    snap = os.path.join(data, "snapshots"); os.makedirs(snap, exist_ok=True)
    json.dump(changelog, open(os.path.join(data, "changelog.json"), "w"))
    json.dump(SYNTH_LIMITS, open(os.path.join(data, "limits.json"), "w"))
    json.dump(SYNTH_SNAP_INDEX, open(os.path.join(snap, "index.json"), "w"))

    gc = load_module("gen_changes")
    gc.CHANGELOG = os.path.join(data, "changelog.json")
    gc.LIMITS = os.path.join(data, "limits.json")
    gc.SNAP_INDEX = os.path.join(snap, "index.json")
    gc.OUT_DIR = os.path.join(site, "changes")
    _silence(gc.main, quiet)
    htmlout = open(os.path.join(gc.OUT_DIR, "index.html")).read()

    # 1. parses without choking + tags balance
    try:
        p = _WellFormed(); p.feed(htmlout); p.close()
        R.check(not p.stack, "gen_changes: unbalanced tags remain open: %s" % p.stack[:5])
    except Exception as ex:
        R.check(False, "gen_changes: index.html failed to parse: %s" % ex)
        return htmlout
    # 2. JSON-LD block is valid JSON
    try:
        ld = htmlout.split('application/ld+json">', 1)[1].split("</script>", 1)[0]
        json.loads(ld)
        R.check(True, "")
    except Exception as ex:
        R.check(False, "gen_changes: JSON-LD block is not valid JSON: %s" % ex)
    # 3. one <li> per change (each change is rendered)
    n_li = htmlout.count('<li><span class="tag')
    R.check(n_li == len(changelog),
            "gen_changes: expected %d change <li>s, got %d" % (len(changelog), n_li))
    # 4. no literal "None" leaked into the rendered body
    R.check("None" not in htmlout.replace("none", ""),
            "gen_changes: literal 'None' leaked into the page (null not handled)")
    # 5. the unknown change type rendered
    R.check("frobnicated" in htmlout.lower(),
            "gen_changes: unknown change type 'frobnicated' did not render via the generic fallback")
    return htmlout


def _text(node, tag):
    els = node.getElementsByTagName(tag)
    if not els or not els[0].childNodes:
        return ""
    return "".join(c.data for c in els[0].childNodes if c.nodeType == c.TEXT_NODE)


def _silence(fn, quiet):
    if not quiet:
        fn(); return
    import io, contextlib
    with contextlib.redirect_stdout(io.StringIO()):
        fn()


def main():
    quiet = "-q" in sys.argv or "--quiet" in sys.argv
    R = Results()
    changelog = build_changelog()

    with tempfile.TemporaryDirectory() as tmp:
        feed1 = run_feed(tmp, changelog, R, quiet)
    with tempfile.TemporaryDirectory() as tmp:
        feed2 = run_feed(tmp, changelog, R, quiet)
    R.check(feed1 == feed2, "gen_feed: NOT idempotent — two runs produced different feed.xml")

    with tempfile.TemporaryDirectory() as tmp:
        ch1 = run_changes(tmp, changelog, R, quiet)
    with tempfile.TemporaryDirectory() as tmp:
        ch2 = run_changes(tmp, changelog, R, quiet)
    R.check(ch1 == ch2, "gen_changes: NOT idempotent — two runs produced different index.html")

    if R.fails:
        print("\ntest_generators: FAIL (%d/%d checks failed)" % (len(R.fails), R.checks))
        for f in R.fails:
            print("  ✗ " + f)
        sys.exit(1)
    print("test_generators: PASS (%d checks, %d change types incl. generic fallback)"
          % (R.checks, len(CHANGE_CASES)))


if __name__ == "__main__":
    main()
