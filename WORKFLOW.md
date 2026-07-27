---
tracker:
  kind: scratch
sandbox:
  image: symphony-agent:latest
  network: symphony-net
stages:
  implement:
    trigger:
      - ready-for-agent
    action: dispatch
    max_turns: 20
    timeout_ms: 3600000
    outcomes:
      complete:
        actions:
          - merge_pr
        transition: review
        retry: false
      escalate:
        actions:
          - set_label:ready-for-human
        retry: false
      fail:
        actions: []
        retry: true
        max_retries: 3
  review:
    trigger:
      - ready-for-review
    action: dispatch
    max_turns: 10
    timeout_ms: 1800000
    concurrency: 2
    outcomes:
      complete:
        actions:
          - merge_pr
        retry: false
      escalate:
        actions:
          - set_label:ready-for-human
        retry: false
      fail:
        actions:
          - set_label:ready-for-agent
        retry: true
        max_retries: 2
polling_interval_ms: 30000
workspace_root: /var/lib/symphony
agent_max_concurrent: 5
agent_max_retry_backoff_ms: 300000
---

# Symphony Orchestrator

Symphony is the autonomous dispatcher that continuously reads work from the issue tracker, creates isolated workspaces, runs coding agents per issue, and recovers from failures automatically.

## Workflow

Issues flow through stages based on their labels:

1. **implement** — triggered by `ready-for-agent` label. Runs a TDD coding agent that implements the issue. On success, creates a PR and transitions the issue to `ready-for-review`.
2. **review** — triggered by `ready-for-review` label. Runs a code review agent. On approval, merges the PR to `agents-main`.

Failures in any stage can either escalate to human (`ready-for-human`) or retry automatically.

## Agent Instructions

You are the Symphony coding agent. Your task is to implement the issue assigned to you using test-driven development (TDD). Follow these steps:

1. Read the issue body carefully
2. Understand the existing codebase
3. Write tests first, then implementation
4. Run all tests to verify
5. Commit your changes

Use the skills and documentation available in the repository. When in doubt, refer to AGENTS.md for guidance.