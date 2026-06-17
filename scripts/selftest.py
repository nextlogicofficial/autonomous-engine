#!/usr/bin/env python3
"""
selftest.py — pre-deploy QA gate for the QuotaLedger site.

Why this exists: every vendor add has historically forced a manual hunt for
stale "<N> vendors / <M> plans" strings scattered across meta tags, callouts,
and explainer copy, plus a manual "remember to add the new /limits/<id>/ URL
to sitemap.xml" step. Both are exactly the kind of recurring friction the
never-twice law says to automate. This script makes the build check its own
work: it derives the canonical counts from data/limits.json (the single source
of truth) and fails loudly if anything on the site disagrees, if a vendor page
or sitemap entry is missing, or if any JSON/XML/JSON-LD artifact is malformed.

Run it before every deploy (deploy.sh calls it automatically; pass --no-gate to
deploy without it in an emergency). Exit code 0 = safe to ship, non-zero = stop.

    python3 scripts/selftest.py            # full report, exits non-zero on any FAIL
    python3 scripts/selftest.py --counts   # just print canonical "V vendors / P plans"

Integrity: read-only. It never edits the site or the data; it only inspects and
reports. No network. No invented numbers — every assertion is derived from
data/limits.json or from the files on disk.
"""
import json, os, re, sys, glob
import xml.etree.ElementTree as ET

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(ROOT, "data", "limits.json")
SITE = os.path.join(ROOT, "site")
DOMAIN = "https://quotaledger.com"

# Lines that legitimately mention a NON-current vendor/plan count (history).
# Matched as a substring against the source line, case-insensitive.
COUNT_ALLOW = ["baseline", "v0 baseline"]

# Directories that are inherently HISTORICAL narratives — the Build Log and the
# change-history timeline describe past states and legitimately quote old counts
# ("back when it said 14 vendors..."). They carry no live "current total" claim,
# so the stale-count guard skips them. Every other check (sitemap, JSON-LD,
# JSON/XML validity) still applies to them.
COUNT_SKIP_DIRS = ("buildlog/", "changes/")

fails = []
warns = []
checks = 0


def ok(msg):
    global checks
    checks += 1
    print(f"  PASS  {msg}")


def fail(msg):
    global checks
    checks += 1
    fails.append(msg)
    print(f"  FAIL  {msg}")


def warn(msg):
    warns.append(msg)
    print(f"  warn  {msg}")


# ---- canonical counts from the single source of truth -----------------------
with open(DATA) as f:
    limits = json.load(f)
vendors = limits["vendors"]
V = len(vendors)
P = sum(len(v.get("plans", [])) for v in vendors)
vendor_ids = [v["id"] for v in vendors]

if "--counts" in sys.argv:
    print(f"{V} vendors / {P} plans")
    sys.exit(0)

print(f"QuotaLedger selftest — canonical: {V} vendors / {P} plans "
      f"(generated_at {limits.get('generated_at','?')})\n")

# ---- 1. every vendor has a /limits/<id>/ page, no orphans -------------------
print("[1] per-vendor reference pages")
limits_dir = os.path.join(SITE, "limits")
for vid in vendor_ids:
    page = os.path.join(limits_dir, vid, "index.html")
    if os.path.isfile(page):
        ok(f"/limits/{vid}/ exists")
    else:
        fail(f"/limits/{vid}/ MISSING (run gen_compare.py)")
present_dirs = [d for d in os.listdir(limits_dir)
                if os.path.isdir(os.path.join(limits_dir, d))]
for d in present_dirs:
    if d not in vendor_ids:
        fail(f"/limits/{d}/ is an ORPHAN (no such vendor id in limits.json)")

# ---- 2. stale total-count strings in static copy ---------------------------
print("\n[2] total-count strings match canonical")
text_files = (glob.glob(os.path.join(SITE, "**", "*.html"), recursive=True)
              + glob.glob(os.path.join(SITE, "**", "*.txt"), recursive=True))
# combined "V vendors and P plans" (the form that actually goes stale)
combined = re.compile(r"(\d+)\s+vendors?\s*(?:and|,|&middot;|·|/)\s*(\d+)\s+plans?",
                      re.I)
# standalone "V vendors"
vendors_only = re.compile(r"(\d+)\s+vendors?", re.I)
combo_hits = 0
solo_hits = 0
for path in text_files:
    rel = os.path.relpath(path, SITE)
    if rel.replace(os.sep, "/").startswith(COUNT_SKIP_DIRS):
        continue
    with open(path, encoding="utf-8") as f:
        for ln, line in enumerate(f, 1):
            low = line.lower()
            allowed = any(a in low for a in COUNT_ALLOW)
            for m in combined.finditer(line):
                cv, cp = int(m.group(1)), int(m.group(2))
                if allowed:
                    continue
                combo_hits += 1
                if (cv, cp) != (V, P):
                    fail(f"{rel}:{ln} says '{m.group(0).strip()}' "
                         f"(expected {V} vendors / {P} plans)")
            for m in vendors_only.finditer(line):
                cv = int(m.group(1))
                # skip the ones already covered by the combined check on this line
                if combined.search(line):
                    continue
                if allowed:
                    continue
                if cv < 6:  # per-vendor / contextual small numbers, not the site total
                    continue
                solo_hits += 1
                if cv != V:
                    fail(f"{rel}:{ln} says '{m.group(0).strip()}' "
                         f"(expected {V} vendors)")
ok(f"checked {combo_hits} combined + {solo_hits} standalone vendor-total mentions")

# ---- 3. sitemap: well-formed, every loc resolves, every vendor listed -------
print("\n[3] sitemap.xml integrity")
sitemap = os.path.join(SITE, "sitemap.xml")
locs = []
try:
    tree = ET.parse(sitemap)
    ns = {"sm": "http://www.sitemaps.org/schemas/sitemap/0.9"}
    locs = [e.text.strip() for e in tree.iter("{http://www.sitemaps.org/schemas/sitemap/0.9}loc")]
    ok(f"sitemap.xml parses, {len(locs)} URLs")
except Exception as e:
    fail(f"sitemap.xml does not parse: {e}")


def url_to_path(u):
    p = u[len(DOMAIN):] if u.startswith(DOMAIN) else u
    p = p.split("?")[0].split("#")[0]
    if p.endswith("/"):
        p = p + "index.html"
    if p.startswith("/"):
        p = p[1:]
    return os.path.join(SITE, p) if p else os.path.join(SITE, "index.html")


for u in locs:
    fp = url_to_path(u)
    if not os.path.isfile(fp):
        fail(f"sitemap lists {u} but file is missing ({os.path.relpath(fp, SITE)})")
if locs and not fails:
    ok("every sitemap URL resolves to a file")
# every vendor page must be in the sitemap (catches the forgotten-add friction)
loc_set = set(locs)
for vid in vendor_ids:
    want = f"{DOMAIN}/limits/{vid}/"
    if want not in loc_set:
        fail(f"/limits/{vid}/ exists but is NOT in sitemap.xml")
if all(f"{DOMAIN}/limits/{v}/" in loc_set for v in vendor_ids):
    ok("all vendor pages are in the sitemap")

# ---- 4. JSON + XML artifacts parse -----------------------------------------
print("\n[4] data artifacts parse")
for jf in glob.glob(os.path.join(SITE, "data", "**", "*.json"), recursive=True):
    try:
        json.load(open(jf))
        ok(f"{os.path.relpath(jf, SITE)} valid JSON")
    except Exception as e:
        fail(f"{os.path.relpath(jf, SITE)} invalid JSON: {e}")
feed = os.path.join(SITE, "feed.xml")
if os.path.isfile(feed):
    try:
        ET.parse(feed)
        ok("feed.xml valid XML")
    except Exception as e:
        fail(f"feed.xml invalid XML: {e}")
else:
    warn("feed.xml not found")

# ---- 5. every JSON-LD block parses -----------------------------------------
print("\n[5] JSON-LD structured data parses")
ldjson = re.compile(
    r'<script[^>]*type=["\']application/ld\+json["\'][^>]*>(.*?)</script>',
    re.I | re.S)
bad = 0
blocks = 0
ilbad = 0
ilchecked = 0


def _check_itemlists(obj, rel):
    """Recursively verify every ItemList's numberOfItems matches the actual
    count of itemListElement. Catches the never-twice defect where a page was
    added to the list but the declared count wasn't bumped (compare/ index,
    2026-06-16) — a silent structured-data lie selftest used to miss because
    the block still parsed."""
    global ilbad, ilchecked
    if isinstance(obj, dict):
        if obj.get("@type") == "ItemList":
            items = obj.get("itemListElement", [])
            if isinstance(items, list):
                declared = obj.get("numberOfItems")
                if declared is not None:
                    ilchecked += 1
                    if declared != len(items):
                        ilbad += 1
                        fail(f"{rel}: ItemList numberOfItems={declared} but "
                             f"{len(items)} itemListElement entries present")
        for v in obj.values():
            _check_itemlists(v, rel)
    elif isinstance(obj, list):
        for v in obj:
            _check_itemlists(v, rel)


for path in glob.glob(os.path.join(SITE, "**", "*.html"), recursive=True):
    rel = os.path.relpath(path, SITE)
    with open(path, encoding="utf-8") as f:
        for m in ldjson.finditer(f.read()):
            blocks += 1
            try:
                parsed = json.loads(m.group(1))
            except Exception as e:
                bad += 1
                fail(f"{rel}: malformed JSON-LD block: {e}")
            else:
                _check_itemlists(parsed, rel)
if bad == 0:
    ok(f"all {blocks} JSON-LD blocks parse")
if ilbad == 0:
    ok(f"all {ilchecked} ItemList numberOfItems counts match")

# ---- summary ----------------------------------------------------------------
print(f"\n{'='*60}")
print(f"selftest: {checks} checks, {len(fails)} failed, {len(warns)} warnings")
if fails:
    print("FAILURES:")
    for x in fails:
        print(f"  - {x}")
    print("RESULT: FAIL — do not deploy")
    sys.exit(1)
print("RESULT: PASS — safe to deploy")
sys.exit(0)
