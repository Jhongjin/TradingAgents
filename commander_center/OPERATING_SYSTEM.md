# Commander Operating System

## Command Loop

1. Intake: capture the user request as one or more queue items.
2. Classify: assign each item to the relevant workstreams and risk level.
3. Dispatch: give each workstream a bounded brief with owner, files, and output.
4. Integrate: merge recommendations or code changes into one coherent result.
5. Verify: run the minimum required gates from `GATES.md`.
6. Ship: commit, push, verify deployment, and record the outcome.

## Queue States

- `intake`: not yet scoped
- `ready`: scoped with owner and acceptance criteria
- `active`: currently being implemented or researched
- `blocked`: waiting on user action, API approval, credentials, or external review
- `review`: implementation done, verification pending
- `shipped`: committed, pushed, and deployment checked when applicable
- `parked`: intentionally deferred

## Priority Scale

- `P0`: site down, data leak, live-trading boundary breach, misleading public output
- `P1`: auth failure, payment/ad readiness blocker, public accuracy regression
- `P2`: core UX, data quality, queue reliability, SEO, or trust improvements
- `P3`: polish, content expansion, refactors, internal tooling

## Dispatch Format

Every parallel team brief should include:

- goal
- context links or files
- exact owner scope
- constraints and red lines
- expected output
- verification required

Use `templates/task-brief.md` for larger work.

## Evidence Ladder

Use the strongest available evidence before trusting a claim:

1. local test or browser verification
2. production/preview API response
3. persisted database row or migration state
4. official vendor documentation or dashboard status
5. code inspection
6. inference, clearly labeled as inference

## Stop Rules

Stop and ask the user only when:

- a real credential, paid account action, legal decision, or external dashboard
  action is required
- continuing would require live trading or order placement work
- there is a conflict between safety and product goals
- an external API/vendor state cannot be verified from the workspace

## Closeout Standard

Each completed queue item should end with:

- files changed
- tests or verification performed
- deployment URL or readiness result, when relevant
- commit hash
- remaining risks or user-required next action

