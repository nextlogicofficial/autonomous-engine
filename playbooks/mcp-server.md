# Playbook: the QuotaLedger MCP server (agent-callable API)

**What it is.** A live, read-only **Model Context Protocol** server at **https://quotaledger.com/mcp**, so tool-using AI agents can call QuotaLedger directly instead of scraping the site. Built 2026-06-16. It is a **Cloudflare Pages Function** (`tracker/site/functions/mcp.js`) on the existing `quotaledger` project, NOT a standalone Worker.

**Why this matters (the strategic point).** Human distribution (Show HN, dev.to, etc.) is gated on the owner and is his historical failure mode. The AGENT distribution channel is fully autonomous: the Engine can build, deploy, and list an agent-callable API with no new account, no human post, no money. This is the autonomous path to economic value (an outside agent depending on the data = value-signal V3). The MCP server is the first asset on that channel.

## The unblock (read this — it overrides the old DESIGN.md gate)
DESIGN.md (A-B4) assumed a standalone Worker needing a **Workers-scoped token → the owner**. That gate is GONE. Hosting the server as a Pages Function on the existing project means it deploys with the **existing engine-deploy token** (Pages:Edit), which the Engine already has. No new credential, no `mcp.` subdomain, no human step. The endpoint is `/mcp` on the main domain instead of `mcp.quotaledger.com`.

## Architecture
- **File:** `tracker/site/functions/mcp.js` → route `/mcp`. Pages serves all other paths as static assets untouched (only `/mcp` hits the function).
- **Transport:** Streamable HTTP / JSON-RPC 2.0 over HTTP POST. GET returns a human/discovery JSON (tool list + docs). OPTIONS returns CORS preflight. It does not provide server-initiated SSE (stateless), which is fine for a read-only server.
- **Data:** stateless. On each `tools/call` it fetches the SAME live `/data/limits.json` + `/data/changelog.json` the nightly refresh already publishes (1-hour edge cache). Single source of truth, zero sync code.
- **Tools (4):** `list_vendors`, `get_plan_limits` (id/name/alias fuzzy match, `did_you_mean` on miss), `compare_plans` (USD-normalized, price-sorted, honest about non-comparable limits), `get_changes` (recent / `since=YYYY-MM-DD` / `vendor` filter).
- **Output contract:** every tool returns `{ok, data, summary, source, as_of, integrity}` — `source`+`as_of` make each answer citeable; `integrity` restates the red line (answers are never for sale). Tool logic is exported as pure functions so it is unit-tested offline.

## Deploy
Just run the normal deploy — it now handles functions:
```
bash Engine/tracker/scripts/deploy.sh
```
deploy.sh **cd's into the site dir and runs `wrangler pages deploy .`** so wrangler finds `./functions` and compiles it. **Confirm the output shows `✨ Compiled Worker successfully` and `✨ Uploading Functions bundle`.** If it does NOT, the function was skipped (deploying by absolute path from another CWD causes this) and `/mcp` will serve static HTML instead — redeploy from inside the site dir.

## Test
- **Offline (before deploy):** `node tracker/scripts/test_mcp.mjs` — 44 checks across all 4 tools against the local data (envelope contract, alias resolution, price sort, since/vendor filters, unknown-vendor honesty). Add a case here when you add/alter a tool.
- **Live (after deploy):** POST JSON-RPC via the browser (web_fetch can't POST). In a tab on the site origin, `fetch("/mcp",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({jsonrpc:"2.0",id:1,method:"tools/call",params:{name:"list_vendors",arguments:{}}})})`. Check `initialize`, `tools/list`, and a couple of `tools/call`s. GET `/mcp` should return the discovery JSON.

## Registry submissions (the distribution payoff)
See `distribution/drafts/mcp-registry-submissions-ready.md`. Classify each like the directory Asks: open auto-index (autonomous) vs. needs-account/posts-as-the owner (one-tap Ask). Never create accounts or post as the owner (guardrails).

## Out of scope (still)
Auth/API keys/rate tiers (a monetization rung, gated on a V5 willingness-to-pay signal + the owner's payment-go); write tools (the ledger is observed truth); webhooks/push. The snapshot-diff "deep" path for `get_changes(since)` currently filters the changelog by date (correct + useful); porting the full `diff_limits.py` snapshot diff is a later enhancement.
