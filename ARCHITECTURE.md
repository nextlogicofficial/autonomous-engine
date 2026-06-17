# Architecture

The design problem: an LLM agent that forgets everything between runs has to operate a real thing, unattended, without drifting, lying to itself, or breaking production. The solution is to put all durable state in plain-text files and to make the build refuse work that disagrees with itself.

## The files (durable state)

| File | Role | Who writes it |
|---|---|---|
| `charter` | Values, mission, hard guardrails, the laws, the autonomy ladder. The constitution. | The human (the agent proposes edits). |
| `queue` | Intentions. The ordered list of what to do next, one item per run, per track. | The agent. |
| `run log` | Experience. What each run did, what shipped, what's next. Newest first. The ground truth of "what last happened." | The agent. |
| `milestones` | The staircase. Small rungs, each attainable in a run or two, each making the next easier. | The agent. |
| `digest` | A under-two-minute summary for the human, rewritten every run, with a "notes from the owner" section the agent reads first. | The agent. |
| `improvements` | One line per run: the biggest friction observed. Ranked and worked down on a schedule. | The agent. |
| `playbooks/` | Self-written, replay-exact procedures for anything done more than once. | The agent. |

The agent reads the charter, then the digest (owner notes first), then the queue, then the top of the run log, and only then decides what to do. The run log's top entry, not the human-facing digest, is treated as the authoritative record of what last shipped, because a digest can lag a run.

## The run loop

Every scheduled run:

1. **Orient.** Read charter, digest (owner notes), queue, run-log top.
2. **Poll for instructions.** Check the owner's inbound channel; log anything new where the next run will see it.
3. **Do the work.** Take the top unblocked item(s). The discipline is one or two high-quality artifacts, never four sloppy ones. A "dual track" split (one distribution action + one build action) keeps both the reach and the substance of the project moving each run.
4. **Prove it.** Run the gates. Deploy. Verify the change is actually live, citing the deploy id and the specific live check. A run may only claim "shipped" after a gated deploy that passed.
5. **Close out.** Update the run log, the queue, the milestones; rewrite the digest; record the run's biggest friction. Leave a finished thing, not a half-finished one.

## Why the build checks itself

The recurring failure of an unattended agent is not a dramatic error; it is a quiet one. A published count drifts from the data. A new page is forgotten in the sitemap. A code path that only runs on a rare event runs for the first time, in production, and runs wrong. None of these are caught by "being careful," because there is no one between runs to be careful.

So the checks live in the deploy, as gates that fail the deploy:

- **Count / structure integrity** (`selftest.py`): the published "N items" strings, the per-item pages, the sitemap entries, and every embedded structured-data block must agree with the canonical data file. A block that merely parses is not enough; its claimed counts must be true.
- **Derived-not-remembered** (`build_site.py`): the sitemap is regenerated from the files that actually exist, so there is nothing for a forgetful worker to forget. The gate then validates the freshly-derived result.
- **Exercise the rare path** (`test_generators.py`): the content generators are fed one of every input type, including one they have never seen, so the branch that would otherwise debut in production has already run a hundred times in a test.

The principle generalizes beyond these scripts: **the most dangerous part of an unattended system is whatever is supposed to run but rarely does.** Manufacture the occasion in a test, today.

## Distribution under an owner who will not distribute

A common and honest constraint: the owner funds the operation but will not do its marketing (no posting as themselves, no outreach). This splits distribution into two channels, and the agent must lean on the one it can own:

- **Human channel** (social posts, forums, cold outreach): needs accounts and posting as the owner. Permanent human gate. The agent drafts; the human fires, or never does.
- **Agent / algorithmic channel** (a machine-callable API or MCP server, structured data, `llms.txt`, search-engine SEO, open auto-indexing registries): the agent builds, deploys, and lists all of it end to end. This is the autonomous route to reach, and the agent treats it as the lead lever rather than waiting on the human.

The honest corollary: a project whose only viable distribution is the human channel, under an owner who will not work that channel, does not have a path, and the system should say so plainly rather than build forever.
