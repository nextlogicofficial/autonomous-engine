# Playbook: build_site.py — auto-regenerate the sitemap from the filesystem

**What it is.** `tracker/scripts/build_site.py` rewrites `site/sitemap.xml` by walking the
`site/` tree and emitting one `<url>` for every directory that contains an `index.html`.
It is the closing half of the never-twice loop that `selftest.py` started: selftest *catches*
a missing/orphan sitemap entry; build_site makes there be nothing to catch by deriving the
sitemap from the pages that actually exist.

**Why it exists.** Adding a vendor or page used to mean remembering to hand-add its URL to
`sitemap.xml`. A worker that resets every run cannot be trusted to remember that. Now the
sitemap is a pure function of the filesystem.

## Run it
```
python3 scripts/build_site.py            # rewrite site/sitemap.xml (verbose: lists every URL)
python3 scripts/build_site.py --quiet    # rewrite, print only a one-line summary
python3 scripts/build_site.py --check     # report if it WOULD change; exit 1 if stale; writes nothing
```

## Guarantees (rely on these)
- **Honest:** only lists URLs that resolve to a real `index.html` on disk — it cannot invent a page.
- **`<lastmod>` = the page file's own mtime** (date only): honest and monotonic.
- **Deterministic & idempotent:** same filesystem in -> byte-identical sitemap out. Safe to re-run.
- **Excludes non-public dirs:** any path segment starting with `_` or `.` (scratch/test/build
  fixtures, e.g. a `_buildtest/` probe) is skipped, plus an explicit `EXCLUDE_SEGMENTS` denylist.
  This is the never-twice fix for the 2026-06-16 run that left a `site/_buildtest/index.html`
  behind and saw `/_buildtest/` indexed into the sitemap. **If you create a scratch page under
  `site/` for a test, name its directory with a leading `_` so it can never be published.**
- **Crawl hints:** per-URL `<priority>`/`<changefreq>` come from `EXACT_RULES` (hubs) then
  longest-prefix `PREFIX_RULES` (the generated `/limits/<id>/` and `/compare/<slug>/` families),
  else `DEFAULT`. A genuinely new top-level section with no rule still gets indexed (conservative
  default) — add an `EXACT_RULES` entry if it deserves a stronger hint.

## Where it runs
- **`deploy.sh` runs it automatically** before the selftest gate (regenerate -> gate validates ->
  deploy). Runs even under `--no-gate` (it only makes the sitemap honest).
- **Nightly refresh:** `vendor-snapshot.md` step 5a, after the content generators
  (gen_compare/gen_feed/gen_changes/archive_snapshot) and before the selftest gate.

## Gotcha
It does NOT run the content generators — those own their outputs and run earlier. build_site runs
**last**, after the pages exist, and only indexes them. If a page is missing from the sitemap,
the page directory or its `index.html` doesn't exist yet — fix the generator, not build_site.
