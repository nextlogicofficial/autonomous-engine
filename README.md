# Autonomous Engine

A working harness for running a small autonomous operation with an LLM agent: it researches, builds, ships real artifacts to production, checks its own work, writes its own playbooks, and reports to one human who reviews for a few minutes a day. The model resets every run; **the system** is what learns, through a set of plain-text files the agent reads and rewrites each time.

This repo is the scrubbed harness behind a live example: a continuously-updated public data site and an agent-callable API, built and operated end to end by an LLM agent on a schedule, with a human owner who holds veto power and provides resources but does no day-to-day work. Secrets, personal data, and the owner's private context are removed. What remains is the part that is reusable: the operating contract, the laws that keep an unattended agent honest, the run protocol, and the small scripts that let a forgetful worker ship safely.

## The core idea

An LLM agent has no memory between runs. So you cannot rely on it to "remember" anything. Instead, the durable state lives in files, and every run follows the same loop: read the contract, read the latest instructions, do one or two high-quality things, prove they work, and write down what happened so the next run inherits a finished thing rather than a mystery. The agent's competence compounds not because the model improves, but because the **playbooks, gates, and logs** accumulate.

Three properties make this work unattended:

1. **Everything important is a file.** The charter (values and rules), the queue (intentions), the run log (experience), the milestones (the staircase), and the playbooks (self-written how-tos). The agent edits these as it learns.
2. **The build checks its own work.** Pre-deploy gates refuse to ship a site whose published numbers disagree with the data, whose sitemap is stale, or whose generators break on an input they have never seen. A worker that forgets cannot be trusted to remember a checklist, so the checklist lives in the deploy.
3. **Hard limits are absolute and few.** No spending money, no creating accounts, no contacting any human but the owner, nothing the owner has walled off. Everything else, the agent is told to find an autonomous way to do.

## What's in here

```
charter-template.md      The operating contract: mission, guardrails, the laws, the autonomy ladder.
run-protocol.md          What every scheduled run does, in order. The dual-track + the value bar.
ARCHITECTURE.md          How the files relate and why the design survives a memory-less worker.
scripts/                 The self-checking build tooling (all dependency-light, no secrets):
  selftest.py            Pre-deploy gate: published counts / pages / sitemap / structured data must agree with the data.
  build_site.py          Regenerate the sitemap from the files on disk, so it can never go stale.
  test_generators.py     Feed the content generators one of every change type (incl. an unknown one) and assert valid output.
  mcp_server.js          A read-only MCP server (Cloudflare Pages Function) that serves a JSON dataset to tool-using agents.
playbooks/               Self-written, exact-enough-to-replay procedures (deploy, the gates, the MCP server).
```

## The laws (why an unattended agent stays trustworthy)

- **Never-twice law.** Every instruction or correction from the owner produces two things: the immediate action, and a permanent rule written into the right file, so the same instruction never has to be given again.
- **Skill-building law.** Before doing anything procedural, check for a playbook; after doing something new or better, write or update one. Capability compounds while the model resets.
- **Value bar (the anti-busywork rule).** No run may end in maintenance mode. Every run must ship at least one concrete artifact that moves a goal forward. "I refreshed things and updated logs" is not a valid outcome.
- **Autonomy-first.** Default posture is to find an autonomous way (an API, a scoped token, a script, the browser). The human steps in only for what genuinely requires their identity, account, or money, and the agent must prove no autonomous path exists before saying "blocked on the human."
- **Improvement-hunting law.** Every run ends by recording the biggest friction it hit, so the system always has a next thing to fix and is never allowed to consider itself finished.

## The autonomy ladder

Authority expands with track record, and one rung never unlocks:

- **Level 1:** the agent proposes; the human approves changes to its own rules and anything touching money, accounts, or other people.
- **Level 2 (after a run of clean unattended runs):** auto-apply improvements to its own prompts and queue strategy, reported for easy reversal.
- **Level 3:** the system watches for better models, tests them on real work, and switches if measurably better.
- **Level 4 (permanent ceiling, never unlocks):** spending money, creating accounts, contacting any human but the owner. Always the human. A system that can spend and email strangers unsupervised is a liability, not an asset.

## Using it

This is a harness, not a product you install. Adapt `charter-template.md` to your own goal, wire the run protocol into a scheduler that wakes an agent on a cadence, and let the agent maintain the queue, run log, and playbooks. The scripts are examples of the self-checking-build pattern; the point is not these specific checks but that the build refuses to ship work that disagrees with itself.

## License

MIT. See `LICENSE`.
