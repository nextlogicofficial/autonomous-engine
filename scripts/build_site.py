#!/usr/bin/env python3
"""
build_site.py — regenerate sitemap.xml from the files on disk.

Why this exists: adding a vendor or a new page used to mean remembering to
hand-add its URL to sitemap.xml. The selftest gate (selftest.py) catches a
forgotten add, but catching it still means a human/agent then has to go fix it
by hand. This script closes the loop the never-twice law asks for: it derives
the sitemap from the filesystem so there is nothing left to forget — every
directory that has an index.html becomes a <url>, automatically, with an
honest <lastmod> taken from the file's own modification date.

Integrity & safety:
  * It only ever lists URLs that resolve to a real file on disk, so it cannot
    invent a page. (selftest.py independently re-verifies this after.)
  * <lastmod> = the page file's mtime (date only) — honest, monotonic, and it
    matches the dates the sitemap was previously curated with by hand.
  * Deterministic & idempotent: same filesystem in → byte-identical sitemap out.

Usage:
    python3 scripts/build_site.py            # rewrite site/sitemap.xml
    python3 scripts/build_site.py --check    # report whether it WOULD change,
                                             # exit 1 if so, write nothing
    python3 scripts/build_site.py --quiet    # write, print only a one-line summary

It does NOT run the content generators (gen_compare / gen_feed / gen_changes /
archive_snapshot) — those own their own outputs and run earlier in the nightly
refresh. build_site.py runs last, after the pages exist, and indexes them.
"""
import os
import sys
import glob
import datetime

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SITE = os.path.join(ROOT, "site")
SITEMAP = os.path.join(SITE, "sitemap.xml")
DOMAIN = "https://quotaledger.com"

# Per-URL crawl hints. Exact-match paths first; the two generated families
# (/compare/<slug>/ and /limits/<id>/) fall through to PREFIX_RULES; anything
# genuinely new with no rule gets DEFAULT (conservative, still indexed).
EXACT_RULES = {
    "/": ("1.0", "daily"),
    "/compare/": ("0.9", "weekly"),
    "/changes/": ("0.9", "daily"),
    "/limits/": ("0.9", "daily"),
    "/api/": ("0.8", "monthly"),
    "/cite/": ("0.7", "monthly"),
    "/buildlog/": ("0.6", "weekly"),
    "/support/": ("0.5", "monthly"),
}
# longest-prefix wins
PREFIX_RULES = [
    ("/limits/", ("0.7", "daily")),     # per-vendor reference pages
    ("/compare/", ("0.8", "weekly")),   # comparison / explainer essays
]
DEFAULT = ("0.5", "weekly")

# Stable display order so the file diffs cleanly between runs. Pages are sorted
# by (section_rank, url): the section hub appears before its children, and
# unranked new sections sort to the end alphabetically.
SECTION_ORDER = ["/", "/compare/", "/changes/", "/limits/", "/api/",
                 "/cite/", "/buildlog/", "/support/"]


def url_for(index_path):
    """site/foo/bar/index.html -> /foo/bar/  (and site/index.html -> /)."""
    rel = os.path.relpath(os.path.dirname(index_path), SITE)
    if rel in (".", ""):
        return "/"
    return "/" + rel.replace(os.sep, "/") + "/"


def rules_for(url):
    if url in EXACT_RULES:
        return EXACT_RULES[url]
    best = None
    for prefix, rule in PREFIX_RULES:
        if url.startswith(prefix) and url != prefix:
            if best is None or len(prefix) > len(best[0]):
                best = (prefix, rule)
    return best[1] if best else DEFAULT


def lastmod_for(index_path):
    ts = os.path.getmtime(index_path)
    return datetime.datetime.utcfromtimestamp(ts).strftime("%Y-%m-%d")


def sort_key(url):
    # section the url belongs to = longest SECTION_ORDER entry that prefixes it
    section = "/"
    for s in SECTION_ORDER:
        if url == s or (s != "/" and url.startswith(s)):
            if len(s) >= len(section):
                section = s
    rank = SECTION_ORDER.index(section) if section in SECTION_ORDER else len(SECTION_ORDER)
    # hub (== section) sorts before its children; then alpha within the section
    is_child = 0 if url == section else 1
    return (rank, is_child, url)


# Non-public directories that must NEVER appear in the sitemap even if they
# happen to contain an index.html: any path segment starting with "_" or "."
# (scratch/test/build fixtures, e.g. a _buildtest/ probe), plus an explicit
# belt-and-braces denylist. This is the never-twice fix for the run that left a
# site/_buildtest/index.html behind and saw it indexed into the sitemap — a
# resetting worker cannot be trusted to remember to delete its scratch files,
# so the indexer refuses to publish them in the first place.
EXCLUDE_SEGMENTS = {"_buildtest"}


def is_public(url):
    """A URL is public iff no path segment is a scratch/test/hidden segment."""
    for seg in url.strip("/").split("/"):
        if seg and (seg[0] in ("_", ".") or seg in EXCLUDE_SEGMENTS):
            return False
    return True


def build():
    pages = glob.glob(os.path.join(SITE, "**", "index.html"), recursive=True)
    entries = []
    for p in pages:
        url = url_for(p)
        if not is_public(url):
            continue
        prio, freq = rules_for(url)
        entries.append((url, lastmod_for(p), freq, prio))
    entries.sort(key=lambda e: sort_key(e[0]))

    lines = ['<?xml version="1.0" encoding="UTF-8"?>',
             '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">']
    for url, lastmod, freq, prio in entries:
        lines.append("  <url>")
        lines.append(f"    <loc>{DOMAIN}{url}</loc>")
        lines.append(f"    <lastmod>{lastmod}</lastmod>")
        lines.append(f"    <changefreq>{freq}</changefreq>")
        lines.append(f"    <priority>{prio}</priority>")
        lines.append("  </url>")
    lines.append("</urlset>")
    return "\n".join(lines) + "\n", entries


def main():
    check = "--check" in sys.argv
    quiet = "--quiet" in sys.argv
    new_xml, entries = build()
    old_xml = ""
    if os.path.isfile(SITEMAP):
        with open(SITEMAP, encoding="utf-8") as f:
            old_xml = f.read()

    changed = (new_xml != old_xml)

    if check:
        if changed:
            print(f"build_site --check: sitemap.xml is STALE "
                  f"({len(entries)} pages on disk). Run build_site.py to refresh.")
            sys.exit(1)
        print(f"build_site --check: sitemap.xml is up to date ({len(entries)} URLs).")
        sys.exit(0)

    with open(SITEMAP, "w", encoding="utf-8") as f:
        f.write(new_xml)

    if quiet:
        print(f"build_site: sitemap.xml = {len(entries)} URLs"
              f"{' (changed)' if changed else ' (no change)'}")
    else:
        print(f"build_site: wrote sitemap.xml with {len(entries)} URLs "
              f"{'(changed)' if changed else '(no change)'}")
        for url, lastmod, freq, prio in entries:
            print(f"  {prio}  {freq:8}  {lastmod}  {url}")


if __name__ == "__main__":
    main()
