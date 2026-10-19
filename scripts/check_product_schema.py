#!/usr/bin/env python3
"""
check_product_schema.py — pre-deploy gate for Product structured data.

Why this exists: on 2026-07-05 Search Console flagged the product pages with
"Missing field 'image'" (critical — the pages were dropped from Merchant
listings rich results entirely) plus four recommended-field gaps
(shippingDetails, hasMerchantReturnPolicy, a global identifier such as brand,
and aggregateRating/review). Per the never-twice law, the fix is not just to
patch the pages but to make the build refuse to ship a Product JSON-LD block
that Google would reject. This script encodes Google's Merchant listings
requirements as a gate, so the failure mode can never silently return.

What it checks, for every JSON-LD block whose @type is (or includes) Product:
  CRITICAL (exit non-zero — Google drops the rich result without these):
    - name
    - image (non-empty string or list)
    - offers with price (or priceSpecification) and priceCurrency
  RECOMMENDED (warn — Google nags but still serves the result):
    - brand (or gtin/mpn/sku as a global identifier)
    - offers.shippingDetails      (digital goods: a 0-cost, 0-day
                                   OfferShippingDetails block satisfies it)
    - offers.hasMerchantReturnPolicy
    - aggregateRating / review    (NEVER fabricate these; wire them to real
                                   collected reviews or leave them absent.
                                   Fake review markup risks a manual action,
                                   which is far worse than a missing field.)

Usage:
    python3 scripts/check_product_schema.py <site-dir>
    python3 scripts/check_product_schema.py <site-dir> --strict   # warnings also fail

Integrity: read-only, no network. It only inspects files on disk and reports.
Exit code 0 = safe to ship, non-zero = stop.
"""
import json
import glob
import os
import re
import sys

LDJSON = re.compile(
    r'<script[^>]*type=["\']application/ld\+json["\'][^>]*>(.*?)</script>',
    re.I | re.S)

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


def is_nonempty(value):
    """A field counts as present only if it carries actual content."""
    if value is None:
        return False
    if isinstance(value, str):
        return bool(value.strip())
    if isinstance(value, (list, dict)):
        return len(value) > 0
    return True


def iter_products(obj):
    """Yield every dict in the JSON-LD graph whose @type is/includes Product."""
    if isinstance(obj, dict):
        t = obj.get("@type")
        types = t if isinstance(t, list) else [t]
        if "Product" in types:
            yield obj
        for v in obj.values():
            yield from iter_products(v)
    elif isinstance(obj, list):
        for v in obj:
            yield from iter_products(v)


def as_list(value):
    return value if isinstance(value, list) else [value]


def check_product(product, where):
    name = product.get("name") or "(unnamed)"
    label = f"{where} Product '{name}'"

    if is_nonempty(product.get("name")):
        ok(f"{label}: name present")
    else:
        fail(f"{where}: Product is missing 'name'")

    if is_nonempty(product.get("image")):
        ok(f"{label}: image present")
    else:
        fail(f"{label}: missing 'image' — CRITICAL, page is excluded from "
             f"Merchant listings rich results without it")

    identifier = next((k for k in ("brand", "gtin", "gtin8", "gtin12",
                                   "gtin13", "gtin14", "mpn", "sku")
                       if is_nonempty(product.get(k))), None)
    if identifier:
        ok(f"{label}: global identifier present ({identifier})")
    else:
        warn(f"{label}: no global identifier (add 'brand', e.g. "
             f'{{"@type": "Brand", "name": "FreelancerTax"}})')

    offers = product.get("offers")
    if not is_nonempty(offers):
        fail(f"{label}: missing 'offers' — CRITICAL")
        return
    for offer in as_list(offers):
        if not isinstance(offer, dict):
            fail(f"{label}: offer is not an object: {offer!r}")
            continue
        has_price = (is_nonempty(offer.get("price"))
                     or offer.get("price") == 0
                     or is_nonempty(offer.get("priceSpecification")))
        if has_price:
            ok(f"{label}: offer has a price")
        else:
            fail(f"{label}: offer missing 'price'/'priceSpecification' — CRITICAL")
        if is_nonempty(offer.get("priceCurrency")) or \
                is_nonempty(offer.get("priceSpecification")):
            ok(f"{label}: offer has priceCurrency")
        else:
            fail(f"{label}: offer missing 'priceCurrency' — CRITICAL")
        if is_nonempty(offer.get("shippingDetails")):
            ok(f"{label}: offer has shippingDetails")
        else:
            warn(f"{label}: offer missing 'shippingDetails' (digital goods: "
                 f"declare a 0-cost, 0-day OfferShippingDetails — see "
                 f"playbooks/product-schema.md)")
        if is_nonempty(offer.get("hasMerchantReturnPolicy")):
            ok(f"{label}: offer has hasMerchantReturnPolicy")
        else:
            warn(f"{label}: offer missing 'hasMerchantReturnPolicy'")

    # Ratings/reviews: recommended by Google, but only ever from real data.
    if is_nonempty(product.get("aggregateRating")) or \
            is_nonempty(product.get("review")):
        ok(f"{label}: rating/review markup present (must reflect real reviews)")
    else:
        warn(f"{label}: no aggregateRating/review — do NOT fabricate; "
             f"collect real reviews first, then wire them in")


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    strict = "--strict" in sys.argv
    if not args:
        print(__doc__)
        sys.exit(2)
    site = args[0]
    if not os.path.isdir(site):
        print(f"error: {site} is not a directory")
        sys.exit(2)

    pages = glob.glob(os.path.join(site, "**", "*.html"), recursive=True)
    products = 0
    print(f"product-schema gate — scanning {len(pages)} pages under {site}\n")
    for path in pages:
        rel = os.path.relpath(path, site)
        with open(path, encoding="utf-8") as f:
            html = f.read()
        for m in LDJSON.finditer(html):
            try:
                parsed = json.loads(m.group(1))
            except Exception:
                continue  # malformed JSON-LD is selftest.py's job to flag
            for product in iter_products(parsed):
                products += 1
                check_product(product, rel)

    print(f"\n{'=' * 60}")
    print(f"product-schema: {products} Product blocks, {checks} checks, "
          f"{len(fails)} failed, {len(warns)} warnings")
    if fails:
        print("FAILURES:")
        for x in fails:
            print(f"  - {x}")
    if warns:
        print("WARNINGS:")
        for x in warns:
            print(f"  - {x}")
    if fails or (strict and warns):
        print("RESULT: FAIL — do not deploy")
        sys.exit(1)
    print("RESULT: PASS — safe to deploy")
    sys.exit(0)


if __name__ == "__main__":
    main()
