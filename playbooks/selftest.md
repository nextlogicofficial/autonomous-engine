# Playbook: Pre-deploy selftest (the build checks its own work)

`scripts/selftest.py` is the QA gate that runs before every deploy. It exists to
kill two recurring frictions (never-twice law): (1) hand-hunting stale
"`<N> vendors / <M> plans`" strings scattered across meta tags, callouts, and
explainer copy after a vendor add, and (2) forgetting to add a new
`/limits/<id>/` URL to `sitemap.xml`. It derives the canonical counts from
`data/limits.json` (single source of truth) and fails loudly on any disagreement.

## What it checks
1. **Per-vendor pages** — every vendor id in limits.json has `site/limits/<id>/index.html`, and there are no orphan dirs (a vendor page with no matching data).
2. **Total-count strings** — every `"<V> vendors and <P> plans"` and standalone `"<V> vendors"` (V≥6) in HTML/txt must equal the canonical counts. Historical mentions are allow-listed by the substring `baseline` (e.g. the v0 baseline changelog line). Per-vendor `"4 plans"` cells and `"$20 plans"` are intentionally NOT flagged. The `buildlog/` and `changes/` directories are exempt from this check entirely (`COUNT_SKIP_DIRS`): they are historical narratives that legitimately quote old counts as illustration (e.g. a Build Log entry saying "back when it said 14 vendors"). They carry no live "current total" claim, so enforcing the count there only produces false positives. Every other check still applies to them.
3. **Sitemap** — `sitemap.xml` parses, every `<loc>` resolves to a real file (no 404s listed), and every vendor page is present in the sitemap.
4. **Data artifacts** — every `site/data/**/*.json` parses, and `feed.xml` is valid XML.
5. **JSON-LD** — every `<script type="application/ld+json">` block on every page parses (a malformed block silently kills SEO rich results), AND every `ItemList` with a declared `numberOfItems` has that number equal to the actual count of `itemListElement` entries. (Added 2026-06-16 after a run added a new /compare/ essay to the index ItemList but left `numberOfItems` at the old value — a block that parses fine yet tells search engines a lie. The check walks JSON-LD recursively so it catches nested ItemLists too.)

Read-only: it inspects and reports, never edits the site or data. No network.

## How to run
```
python3 scripts/selftest.py            # full report; exit 0 = safe, non-zero = stop
python3 scripts/selftest.py --counts   # just print "V vendors / P plans" (handy for copy)
```

## Where it's wired in
- **deploy.sh** runs it automatically as a pre-deploy gate and ABORTS on any FAIL. Bypass only in an emergency with `bash deploy.sh --no-gate`.
- **vendor-snapshot.md** step 5b runs it after the refresh, before deploy, so issues surface early.

## When a vendor is added (the friction this removes)
Old way: add the vendor, then manually grep every page for stale counts and the sitemap for the missing URL. New way: add the vendor + run `gen_compare.py` + add the `<url>` block, then run `selftest.py` — it tells you exactly which files still say the old count and whether the sitemap entry is missing. Fix what it flags; when it says `PASS`, the site is internally consistent.

## Extending it
Add new structural invariants here as the site grows (e.g. "every /compare/ essay is in the sitemap", "every llms.txt link resolves"). Keep every assertion derived from data or files on disk — never hard-code a count.
