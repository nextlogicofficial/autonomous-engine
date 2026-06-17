/**
 * QuotaLedger MCP server — Cloudflare Pages Function at /mcp (route: quotaledger.com/mcp).
 *
 * A-B4. Stateless, read-only, unauthenticated MCP server (Streamable HTTP / JSON-RPC 2.0
 * over HTTP POST) that serves the SAME live JSON the nightly refresh already publishes, so
 * there is no second database and no sync code. Hosted as a Pages Function on the existing
 * `quotaledger` project — deploys with the existing engine-deploy (Pages:Edit) token, so it
 * needed no new credential and no human step (the original DESIGN assumed a standalone Worker
 * + a Workers-scoped token; the Pages-Function path removes that gate entirely).
 *
 * Five tools: list_vendors, get_plan_limits, compare_plans, find_plans, get_changes. Every answer carries
 * source + as_of + an integrity line, per the charter's cite-worthy contract and integrity red
 * line (QuotaLedger reports observed data; it never sells or skews the answer).
 *
 * The tool logic (TOOLS, callTool) is exported as pure functions that take already-parsed data,
 * so it is unit-tested in the sandbox (scripts/test_mcp.py drives them via node) before deploy.
 */

const PROTOCOL_VERSION = "2025-06-18";
const SERVER_INFO = { name: "quotaledger", version: "1.0.0" };
const INTEGRITY =
  "QuotaLedger reports observed vendor data; it never accepts payment to change what the data says.";

// ---------------------------------------------------------------------------
// Tool schemas (the surface agents call)
// ---------------------------------------------------------------------------
const TOOLS = [
  {
    name: "list_vendors",
    description:
      "List every AI vendor QuotaLedger tracks, with plan count, cheapest paid USD plan, and source. Use this first to map a vendor name to the id the other tools take.",
    inputSchema: { type: "object", properties: {}, additionalProperties: false },
  },
  {
    name: "get_plan_limits",
    description:
      "Get every plan, price (USD), and the verbatim published limit wording for one vendor. Accepts a vendor id or name (case-insensitive; e.g. 'anthropic' or 'claude' both resolve to claude).",
    inputSchema: {
      type: "object",
      properties: { vendor: { type: "string", description: "Vendor id or name." } },
      required: ["vendor"],
      additionalProperties: false,
    },
  },
  {
    name: "compare_plans",
    description:
      "Compare plans across 2-6 vendors as one USD-normalized, price-sorted table. Honestly states what is comparable (price) and what is not (most vendors publish no numeric usage quota). Optional price_max_usd filters by monthly price.",
    inputSchema: {
      type: "object",
      properties: {
        vendors: {
          type: "array",
          items: { type: "string" },
          minItems: 2,
          maxItems: 6,
          description: "2-6 vendor ids or names.",
        },
        price_max_usd: { type: "number", description: "Optional: only plans at or below this monthly USD price." },
      },
      required: ["vendors"],
      additionalProperties: false,
    },
  },
  {
    name: "find_plans",
    description:
      "Search plans across ALL tracked vendors at once by objective criteria — a price range and/or a keyword matched against plan name, vendor name, and the published limit wording. Returns every matching plan, USD, sorted cheapest-first. Answers 'what's the cheapest plan under $X' or 'which plans mention <feature>' in one call without having to name vendors. Honest caveat: cheapest is not 'best' — usage limits differ and are mostly vendor-relative.",
    inputSchema: {
      type: "object",
      properties: {
        price_max_usd: { type: "number", description: "Optional: only plans at or below this monthly USD price." },
        price_min_usd: { type: "number", description: "Optional: only plans at or above this monthly USD price." },
        query: { type: "string", description: "Optional keyword; case-insensitive substring matched against plan name, vendor name, and limit wording." },
        include_free: { type: "boolean", description: "Include $0 plans (default true)." },
        limit: { type: "number", description: "Max plans to return (default 50)." },
      },
      additionalProperties: false,
    },
  },
  {
    name: "get_changes",
    description:
      "Recent observed changes to AI plan limits and prices (price changes, plan/vendor added or removed, limit-wording changes), newest first. Optional since=YYYY-MM-DD returns only changes on/after that date; optional vendor narrows to one vendor; optional limit caps the count (default 20).",
    inputSchema: {
      type: "object",
      properties: {
        since: { type: "string", description: "YYYY-MM-DD; only changes on/after this date." },
        vendor: { type: "string", description: "Vendor id or name to filter to." },
        limit: { type: "number", description: "Max entries (default 20)." },
      },
      additionalProperties: false,
    },
  },
];

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------
function norm(s) {
  return String(s == null ? "" : s).toLowerCase().replace(/[^a-z0-9]/g, "");
}

// resolve a vendor query (id or name, fuzzy) to a vendor object, or null
function resolveVendor(limits, query) {
  const q = norm(query);
  if (!q) return null;
  const vendors = limits.vendors || [];
  // exact id, then exact normalized name
  let v = vendors.find((x) => norm(x.id) === q) || vendors.find((x) => norm(x.name) === q);
  if (v) return v;
  // substring either way (handles "anthropic"->claude only if name/id contains; add known aliases)
  const ALIASES = { anthropic: "claude", openai: "chatgpt", google: "gemini", xai: "grok", quora: "poe", vercel: "v0", stackblitz: "bolt" };
  if (ALIASES[q]) {
    v = vendors.find((x) => norm(x.id) === norm(ALIASES[q]));
    if (v) return v;
  }
  v = vendors.find((x) => norm(x.id).includes(q) || q.includes(norm(x.id)) || norm(x.name).includes(q));
  return v || null;
}

function didYouMean(limits, query) {
  const q = norm(query);
  const scored = (limits.vendors || []).map((x) => {
    const a = norm(x.id), b = norm(x.name);
    let score = 0;
    if (a.startsWith(q) || b.startsWith(q)) score = 3;
    else if (a.includes(q) || b.includes(q)) score = 2;
    else if (q && (q.includes(a) || q.includes(b))) score = 1;
    return { id: x.id, name: x.name, score };
  });
  return scored.filter((s) => s.score > 0).sort((a, b) => b.score - a.score).slice(0, 4).map((s) => s.id);
}

function cheapestPaid(plans) {
  const paid = (plans || []).map((p) => p.price_month).filter((p) => typeof p === "number" && p > 0);
  return paid.length ? Math.min(...paid) : null;
}

function limitSummary(plan) {
  const notes = plan.limit_notes || [];
  if (!notes.length) return "No published limit detail.";
  return notes.join(" ");
}

function envelope(data, summary, source, asOf) {
  return { ok: true, data, summary, source, as_of: asOf, integrity: INTEGRITY };
}

// ---------------------------------------------------------------------------
// Tool implementations (pure: take parsed {limits, changelog, origin})
// ---------------------------------------------------------------------------
function tool_list_vendors({ limits, origin }) {
  const vendors = (limits.vendors || []).map((v) => ({
    id: v.id,
    name: v.name,
    plan_count: (v.plans || []).length,
    cheapest_paid_usd: cheapestPaid(v.plans),
    source_url: v.source_url,
    retrieved_at: v.retrieved_at,
  }));
  const summary =
    `QuotaLedger tracks ${vendors.length} AI vendors (${vendors.reduce((n, v) => n + v.plan_count, 0)} plans total): ` +
    vendors.map((v) => v.name.replace(/\s*\(.*?\)\s*/, "")).join(", ") + ". All prices are canonical USD.";
  return envelope({ vendors, generated_at: limits.generated_at }, summary, `${origin}/limits/`, limits.generated_at);
}

function tool_get_plan_limits({ limits, origin }, args) {
  const v = resolveVendor(limits, args && args.vendor);
  if (!v) {
    return {
      ok: false,
      error: `Unknown vendor: ${args && args.vendor}`,
      did_you_mean: didYouMean(limits, args && args.vendor),
      integrity: INTEGRITY,
    };
  }
  const plans = (v.plans || []).map((p) => ({
    id: p.id, name: p.name,
    price_month_usd: typeof p.price_month === "number" ? p.price_month : null,
    price_detail: p.price_detail || null,
    limit_notes: p.limit_notes || [],
  }));
  const cheapest = cheapestPaid(v.plans);
  const summary =
    `${v.name}: ${plans.length} plans (USD). ` +
    (cheapest != null ? `Cheapest paid plan $${cheapest}/mo. ` : "") +
    plans.map((p) => `${p.name} ${p.price_month_usd != null ? "$" + p.price_month_usd + "/mo" : (p.price_detail || "custom")}`).join("; ") +
    `. Limit wording is published verbatim; most vendors do not state a numeric quota.`;
  return envelope(
    { id: v.id, name: v.name, currency: v.currency || "USD", plans, observations: v.observations || null, currency_note: v.currency_note || null },
    summary, `${origin}/limits/${v.id}/`, v.retrieved_at || limits.generated_at
  );
}

function tool_compare_plans({ limits, origin }, args) {
  const queries = (args && args.vendors) || [];
  const resolved = [], missing = [];
  for (const q of queries) {
    const v = resolveVendor(limits, q);
    if (v && !resolved.find((r) => r.id === v.id)) resolved.push(v);
    else if (!v) missing.push(q);
  }
  if (resolved.length < 2) {
    return { ok: false, error: `Need at least 2 known vendors. Unresolved: ${missing.join(", ") || "(too few)"}.`, did_you_mean: missing.length ? didYouMean(limits, missing[0]) : [], integrity: INTEGRITY };
  }
  const max = args && typeof args.price_max_usd === "number" ? args.price_max_usd : null;
  let rows = [];
  for (const v of resolved) {
    for (const p of v.plans || []) {
      const price = typeof p.price_month === "number" ? p.price_month : null;
      if (max != null && (price == null || price > max)) continue;
      rows.push({
        vendor: v.name.replace(/\s*\(.*?\)\s*/, ""), vendor_id: v.id, plan: p.name,
        price_month_usd: price, limit_note_summary: limitSummary(p),
      });
    }
  }
  rows.sort((a, b) => (a.price_month_usd == null ? 1e9 : a.price_month_usd) - (b.price_month_usd == null ? 1e9 : b.price_month_usd));
  const summary =
    `Comparing ${resolved.map((v) => v.name.replace(/\s*\(.*?\)\s*/, "")).join(", ")}${max != null ? ` (plans up to $${max}/mo)` : ""}: ` +
    `${rows.length} plans, all USD, sorted by price. Prices are directly comparable; usage limits are mostly vendor-relative (multipliers of an unstated base) and NOT directly comparable across vendors — QuotaLedger states each vendor's published wording rather than inventing a common number.` +
    (missing.length ? ` Unresolved inputs ignored: ${missing.join(", ")}.` : "");
  return envelope({ currency: "USD", vendors: resolved.map((v) => v.id), rows }, summary, `${origin}/compare/`, limits.generated_at);
}

function planMatchesQuery(vendorName, plan, q) {
  if (!q) return true;
  const hay = norm(vendorName) + " " + norm(plan.name) + " " + norm((plan.limit_notes || []).join(" "));
  return hay.includes(q);
}

function tool_find_plans({ limits, origin }, args) {
  const a = args || {};
  const priceMax = typeof a.price_max_usd === "number" ? a.price_max_usd : null;
  const priceMin = typeof a.price_min_usd === "number" ? a.price_min_usd : null;
  const includeFree = a.include_free === undefined ? true : !!a.include_free;
  const q = a.query ? norm(a.query) : null;
  const limit = typeof a.limit === "number" && a.limit > 0 ? Math.min(a.limit, 200) : 50;
  const hasPriceFilter = priceMax != null || priceMin != null;

  let rows = [];
  for (const v of limits.vendors || []) {
    const vendorName = v.name.replace(/\s*\(.*?\)\s*/, "");
    for (const p of v.plans || []) {
      const price = typeof p.price_month === "number" ? p.price_month : null;
      if (!includeFree && price === 0) continue;
      if (hasPriceFilter && price == null) continue; // custom/enterprise can't satisfy a numeric range
      if (priceMax != null && price > priceMax) continue;
      if (priceMin != null && price < priceMin) continue;
      if (!planMatchesQuery(v.name, p, q)) continue;
      rows.push({
        vendor: vendorName, vendor_id: v.id, plan: p.name,
        price_month_usd: price, price_detail: p.price_detail || null,
        limit_note_summary: limitSummary(p), source_url: `${origin}/limits/${v.id}/`,
      });
    }
  }
  rows.sort((x, y) => (x.price_month_usd == null ? 1e9 : x.price_month_usd) - (y.price_month_usd == null ? 1e9 : y.price_month_usd));
  const total = rows.length;
  rows = rows.slice(0, limit);
  const crit = [];
  if (priceMin != null) crit.push(`>= $${priceMin}`);
  if (priceMax != null) crit.push(`<= $${priceMax}`);
  if (q) crit.push(`matching "${a.query}"`);
  if (!includeFree) crit.push("paid only");
  const summary =
    `${total} plan${total === 1 ? "" : "s"} across ${(limits.vendors || []).length} vendors` +
    (crit.length ? ` (${crit.join(", ")})` : "") +
    `${total > rows.length ? `, showing cheapest ${rows.length}` : ""}, USD, sorted cheapest-first. ` +
    (rows.length
      ? rows.slice(0, 5).map((x) => `${x.vendor} ${x.plan} ${x.price_month_usd != null ? "$" + x.price_month_usd + "/mo" : (x.price_detail || "custom")}`).join("; ") + ". "
      : "No plans match. ") +
    `Price is directly comparable; usage limits are mostly vendor-relative and not — cheapest is not necessarily best.`;
  return envelope({ currency: "USD", count: total, returned: rows.length, plans: rows }, summary, `${origin}/limits/`, limits.generated_at);
}

function tool_get_changes({ changelog, limits, origin }, args) {
  let entries = (changelog || []).slice();
  const since = args && args.since ? String(args.since) : null;
  const vendorQ = args && args.vendor ? norm(args.vendor) : null;
  let vendorId = null;
  if (vendorQ) {
    const v = resolveVendor(limits, args.vendor);
    vendorId = v ? v.id : args.vendor;
  }
  const limit = args && typeof args.limit === "number" && args.limit > 0 ? Math.min(args.limit, 100) : 20;
  entries.sort((a, b) => String(b.ts).localeCompare(String(a.ts)));
  if (since) entries = entries.filter((e) => String(e.ts).slice(0, 10) >= since);
  if (vendorId) entries = entries.filter((e) => norm(e.vendor) === norm(vendorId));
  const total = entries.length;
  entries = entries.slice(0, limit);
  const out = entries.map((e) => ({
    date: String(e.ts).slice(0, 10), ts: e.ts, vendor: e.vendor, plan: e.plan || null,
    change: e.change, old: e.old == null ? null : e.old, new: e.new == null ? null : e.new,
  }));
  const summary =
    `${total} change${total === 1 ? "" : "s"}${since ? ` since ${since}` : ""}${vendorId ? ` for ${vendorId}` : ""}` +
    `${total > out.length ? ` (showing newest ${out.length})` : ""}. ` +
    (out.length ? out.slice(0, 5).map((e) => `${e.date} ${e.vendor} ${e.change}${e.new ? " -> " + e.new : ""}`).join("; ") + "." : "No changes match.");
  return envelope({ count: total, returned: out.length, changes: out }, summary, `${origin}/changes/`, limits.generated_at);
}

const DISPATCH = {
  list_vendors: tool_list_vendors,
  get_plan_limits: tool_get_plan_limits,
  compare_plans: tool_compare_plans,
  find_plans: tool_find_plans,
  get_changes: tool_get_changes,
};

// pure entry point used by the unit test
export function callTool(name, args, ctx) {
  const fn = DISPATCH[name];
  if (!fn) return { ok: false, error: `Unknown tool: ${name}`, integrity: INTEGRITY };
  return fn(ctx, args || {});
}

export { TOOLS, resolveVendor };

// ---------------------------------------------------------------------------
// JSON-RPC / Streamable HTTP transport
// ---------------------------------------------------------------------------
function rpcResult(id, result) {
  return { jsonrpc: "2.0", id, result };
}
function rpcError(id, code, message) {
  return { jsonrpc: "2.0", id, error: { code, message } };
}

async function loadData(origin) {
  const opts = { cf: { cacheTtl: 3600, cacheEverything: true } };
  const [l, c] = await Promise.all([
    fetch(`${origin}/data/limits.json`, opts).then((r) => r.json()),
    fetch(`${origin}/data/changelog.json`, opts).then((r) => r.json()),
  ]);
  return { limits: l, changelog: c, origin };
}

async function handleMessage(msg, origin) {
  const { id, method, params } = msg || {};
  const isNotification = id === undefined || id === null;

  if (method === "initialize") {
    const clientVer = params && params.protocolVersion;
    return rpcResult(id, {
      protocolVersion: clientVer || PROTOCOL_VERSION,
      capabilities: { tools: { listChanged: false } },
      serverInfo: SERVER_INFO,
      instructions:
        "QuotaLedger: a free, continuously updated ledger of AI subscription plan limits and prices. Call list_vendors first, then get_plan_limits / compare_plans / get_changes. Every answer includes a source URL and as_of date for citation. The data is observed and neutral; it is never paid-for.",
    });
  }
  if (method === "ping") return rpcResult(id, {});
  if (method === "notifications/initialized" || (method && method.startsWith("notifications/"))) return null;
  if (method === "tools/list") return rpcResult(id, { tools: TOOLS });
  if (method === "tools/call") {
    const name = params && params.name;
    const args = (params && params.arguments) || {};
    let ctx;
    try {
      ctx = await loadData(origin);
    } catch (e) {
      return rpcError(id, -32603, "Failed to load ledger data: " + (e && e.message));
    }
    const result = callTool(name, args, ctx);
    const text = result && result.summary ? result.summary : JSON.stringify(result);
    return rpcResult(id, {
      content: [
        { type: "text", text },
        { type: "text", text: JSON.stringify(result) },
      ],
      structuredContent: result,
      isError: result && result.ok === false,
    });
  }
  if (isNotification) return null;
  return rpcError(id, -32601, `Method not found: ${method}`);
}

const CORS = {
  "Access-Control-Allow-Origin": "*",
  "Access-Control-Allow-Methods": "GET, POST, OPTIONS",
  "Access-Control-Allow-Headers": "Content-Type, MCP-Protocol-Version, Authorization",
};

export async function onRequest(context) {
  const { request } = context;
  const origin = new URL(request.url).origin;

  if (request.method === "OPTIONS") return new Response(null, { status: 204, headers: CORS });

  if (request.method === "GET") {
    // Human/discovery view — Streamable HTTP uses GET for server-initiated SSE, which this
    // stateless server does not provide, so return a friendly JSON description instead.
    const info = {
      server: SERVER_INFO,
      protocol: "Model Context Protocol over Streamable HTTP (JSON-RPC 2.0). POST JSON-RPC to this URL.",
      transport: "POST " + origin + "/mcp",
      tools: TOOLS.map((t) => ({ name: t.name, description: t.description })),
      docs: origin + "/api/",
      integrity: INTEGRITY,
    };
    return new Response(JSON.stringify(info, null, 2), {
      status: 200,
      headers: { "Content-Type": "application/json", ...CORS },
    });
  }

  if (request.method !== "POST") {
    return new Response(JSON.stringify(rpcError(null, -32600, "Use POST for MCP JSON-RPC.")), {
      status: 405, headers: { "Content-Type": "application/json", ...CORS },
    });
  }

  let body;
  try {
    body = await request.json();
  } catch (e) {
    return new Response(JSON.stringify(rpcError(null, -32700, "Parse error")), {
      status: 400, headers: { "Content-Type": "application/json", ...CORS },
    });
  }

  // Single message or batch
  if (Array.isArray(body)) {
    const responses = [];
    for (const m of body) {
      const r = await handleMessage(m, origin);
      if (r) responses.push(r);
    }
    return new Response(responses.length ? JSON.stringify(responses) : "", {
      status: responses.length ? 200 : 202,
      headers: { "Content-Type": "application/json", ...CORS },
    });
  }

  const r = await handleMessage(body, origin);
  if (!r) return new Response("", { status: 202, headers: CORS });
  return new Response(JSON.stringify(r), {
    status: 200,
    headers: { "Content-Type": "application/json", ...CORS },
  });
}
