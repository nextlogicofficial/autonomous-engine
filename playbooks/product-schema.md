# Playbook: Product structured data (Merchant listings compliance)

`scripts/check_product_schema.py` is the pre-deploy gate for every page that
carries Product JSON-LD. It exists because on 2026-07-05 Search Console flagged
the product pages with a **critical** `Missing field "image"` (which excludes a
page from Merchant listings rich results entirely) plus four recommended-field
gaps (`shippingDetails`, `hasMerchantReturnPolicy`, no global identifier,
`aggregateRating`/`review`). Per the never-twice law, the fix lives in the
deploy: the build now refuses to ship a Product block Google would reject.

## What it checks
Every `<script type="application/ld+json">` block whose `@type` is (or
includes) `Product`, on every page:

- **Critical (FAIL, blocks deploy):** `name`; `image`; `offers` with
  `price`/`priceSpecification` and `priceCurrency`. Without these Google drops
  the rich result.
- **Recommended (warn):** a global identifier (`brand` is the practical one for
  first-party digital products — `gtin`/`mpn`/`sku` also count);
  `offers.shippingDetails`; `offers.hasMerchantReturnPolicy`;
  `aggregateRating`/`review`.

Read-only, no network, same contract as `selftest.py`: exit 0 = safe to ship.

## How to run
```
python3 scripts/check_product_schema.py <site-dir>            # gate
python3 scripts/check_product_schema.py <site-dir> --strict   # warnings also fail
```
Wire it into `deploy.sh` next to `selftest.py` so it runs on every deploy.

## Known-good template for a digital product (CAD, instant delivery)
Digital downloads have no shipping and Google still wants `shippingDetails`;
the accepted pattern is a zero-cost, zero-day shipping block. Adapt per
product; keep price/name in sync with the payment link:

```json
{
  "@context": "https://schema.org",
  "@type": "Product",
  "name": "Year-End Tax Prep Kit",
  "description": "Everything a Canadian freelancer needs to close the year.",
  "image": "https://freelancertax.ca/img/products/year-end-kit.png",
  "brand": {"@type": "Brand", "name": "FreelancerTax"},
  "sku": "FT-YEK-1",
  "offers": {
    "@type": "Offer",
    "price": "39.00",
    "priceCurrency": "CAD",
    "availability": "https://schema.org/InStock",
    "shippingDetails": {
      "@type": "OfferShippingDetails",
      "shippingRate": {"@type": "MonetaryAmount", "value": 0, "currency": "CAD"},
      "shippingDestination": {"@type": "DefinedRegion", "addressCountry": "CA"},
      "deliveryTime": {
        "@type": "ShippingDeliveryTime",
        "handlingTime": {"@type": "QuantitativeValue", "minValue": 0, "maxValue": 0, "unitCode": "DAY"},
        "transitTime": {"@type": "QuantitativeValue", "minValue": 0, "maxValue": 0, "unitCode": "DAY"}
      }
    },
    "hasMerchantReturnPolicy": {
      "@type": "MerchantReturnPolicy",
      "applicableCountry": "CA",
      "returnPolicyCategory": "https://schema.org/MerchantReturnFiniteReturnWindow",
      "merchantReturnDays": 30,
      "returnMethod": "https://schema.org/ReturnByMail",
      "returnFees": "https://schema.org/FreeReturn"
    }
  }
}
```
The `image` must be a real, publicly reachable asset (a product screenshot is
fine); a URL that 404s is as bad as a missing field. The return-policy values
must match what the site's actual refund policy says — if there is no written
refund policy yet, write one first, then mark it up.

## Ratings and reviews: the hard rule
**Never fabricate `aggregateRating` or `review`.** Fake review markup is a
Google policy violation that risks a manual action against the whole site —
strictly worse than a missing recommended field. The gate only warns on this,
and the warning stays until real reviews exist. The autonomous path to real
reviews: after each Stripe sale, the post-purchase email asks for a one-line
review; collected reviews are stored with the product data and rendered both
as visible page content and as `review`/`aggregateRating` markup (Google
requires the marked-up reviews to be visible on the page).

## After fixing pages
1. Re-run the gate; it must PASS.
2. Spot-check one product page in Google's Rich Results Test.
3. In Search Console, open each affected report (Merchant listings, Product
   snippets) and click **Validate fix** so Google re-crawls and clears the
   report; validation takes days, note the date started in the run log.
