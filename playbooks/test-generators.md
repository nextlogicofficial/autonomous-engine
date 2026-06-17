# Playbook: test_generators.py — synthetic-change regression test for the generators

**What it is.** `tracker/scripts/test_generators.py` feeds `gen_feed.py` and `gen_changes.py`
a synthetic changelog containing one entry of EVERY change type they special-case — plus a
deliberately-unknown type to force the generic fallback — and asserts both outputs are
well-formed and complete. It runs the real generators against fixtures in a temp dir (by
pointing their module-level path constants at synthetic files), so it never touches the live
`site/` or `data/`.

**Why it exists.** On 2026-06-16 the first real price change exposed a latent precedence bug
in both generators: the generic-change code path had never run in five zero-change nights, so
it shipped broken and unnoticed. A generator that only ever sees `vendor_added` in production
is untested on every other change type until the day one occurs live. This test exercises all
of them up front, so a generator can't break on a change type it has never happened to see.

## Run it
```
python3 scripts/test_generators.py        # all checks, exit 1 on any failure
python3 scripts/test_generators.py -q     # quiet: only the final PASS/FAIL line
```

## What it asserts (per generator)
- **gen_feed:** feed.xml is well-formed XML; exactly one `<item>` per change; every item has a
  non-empty `<title>` and `<description>`; no literal `"None"` leaks in (the null-render bug
  class); the unknown change type renders via the generic fallback.
- **gen_changes:** index.html parses with balanced tags; the embedded JSON-LD is valid JSON;
  one change `<li>` per change; no literal `"None"` leaks into the body; the unknown type renders.
- **Both:** idempotent — two runs produce byte-identical output.

As of 2026-06-16 it runs **84 checks across 11 change types** and the suite passes.

## Where it runs
- **`deploy.sh`** runs it (with `selftest.py`) as a pre-deploy gate; `--no-gate` skips both.
- **Nightly refresh:** `vendor-snapshot.md` step 5a2, after the generators regenerate.
- **After editing any generator's `label()`/`describe()`/`classify()` logic** — run it before deploy.

## Extending it
When you add a new change type to a generator's `label`/`describe`, add a matching case to
`CHANGE_CASES` at the top of the test (the change name + the fields it reads). When a generator
adds a special-cased field, make sure a case exercises it. The unknown-type case (`frobnicated`)
must always stay — it is the guard for the generic fallback path that caused the original bug.

## Difference from selftest.py
`selftest.py` validates the **deployed site** (published counts/pages/feeds agree with the data).
`test_generators.py` validates the **generator code** (does it render every change type?). They
are complementary gates: one guards the artifact, the other guards the machine that makes it.
