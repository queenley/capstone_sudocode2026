---
name: ground-truth-review
description: Review, approve, or revise evaluation scenarios and ground-truth labels in this project's evaluation data. Use before adding a test case to model-backed evaluation, or changing success conditions, expected outcomes, facts, or grading labels; not for ordinary evaluator code fixes.
---

# Ground-truth review for evaluation data

> **Current dataset:** the run path is named in `evaluation/README.md` (`data/dev/scenarios`; labels revision r4 since 09/11/2026). A revision rewrites the labels of `data/dev` or `data/test` in place through its build script (below).

This is the single instruction file for creating, reviewing, and revising team evaluation data. Team data lives under `data/dev/` and `data/test/` (their current revisions are named in `evaluation/README.md`); the old `create-data-diagnostic-v<N>/` folders are in git history only. Treat the organisers' pack in `apps/ai-agent-service/data/btc/` as an immutable reference: a BTC schema defines the shape, not the truth of an answer. Verify prices, promotions, inventory, order state, and effective dates against that pack's catalog, policy, and `eval/mock_tools.py`. The seven BTC public samples (`test_set/public_sample/`) are development examples; they are not the future organiser golden set. Do not use frozen or hidden cases to teach FAQ, Reflection, or Exemplar Bank.

Before running a new case, check the BTC scenario format (`schemas/scenario_format.md`) and make sure every call has a reviewed grading method, expected tools for both the `full` and the `baseline_no_memory` configuration, a source/provenance and a PII decision. A structurally valid JSON file with a wrong business fact or an unsupported field is not ready. Keep new or corrected labels in a new revision; never overwrite a used revision.

Each revision of `data/dev` or `data/test` is a derived, BTC-compatible diagnostic revision of `evaluation/data-generation` output, not approved official GT. Its `conversion-report.json` records every changed field; `official_gt_approved: false` must remain truthful. `QaAgent` and model judgments can propose or flag labels, but cannot approve their own labels. A human reviewer makes the final decision.

## Before changing data

1. Read the source scenario, its conversation and judgment if relevant, the derived scenario and `conversion-report.json`. Check claims against the pinned BTC policy, catalog and mock data rather than model output alone.
2. For each changed `success_if`, `expected_outcome`, `must_carry_over`, `must_not_ask`, `ground_truth_facts`, or grading method/criterion, record source value, proposed value, evidence, reviewer, and decision: keep, revert, or revise. Distinguish a business outcome from a proxy tool call. Do not make a criterion easier solely to improve the score.
3. If evidence is missing or the reviewer has not decided, leave the label disputed/pending and the dataset diagnostic. Never turn missing GT, usage, or trace into zero or PASS. Disputed labels are listed beside the revision (`DISPUTES.md`).

## Publish a revision

- Build a revision with a script that can be rerun, not by hand. The script reads the previous labels from a pinned git commit (`SOURCE_REF`), builds under `data/.build/`, and replaces only the label folders of `data/dev` or `data/test` (`scenarios`, `metadata`, `asr_reference`, `tools`, `call_brief`, `handoff_brief`) with an updated `conversion-report.json` and source hashes. One folder per dataset, no `dev-r<N>` copies (the reviewer's choice, 09/11/2026): the revision a run used stays in git at its commit, so name that commit in the run's notes and never compare runs across revisions without saying the labels changed. Example: `build_dev_r4.py`, `build_test_r1.py`.
- After a revision changes customer words, write the reference conversations again with `regenerate_conversations.py --dataset <name>` (model money: `--list` first, then `--only <id>` as a trial) and the changed turns' audio with `synthesize_scenario_audio --changed-only` (ElevenLabs: `--dry-run` first). The builder keeps a re-spoken `asr_reference/<call>.json` and rewrites `ground_truth.json` from the clips.
- Keep reviewer evidence with the new revision. Mark approval only for the scope actually reviewed; one approved field or call does not approve the whole dataset.
- Run a model-backed evaluation only when requested or authorized, on the same pinned cohort, and report label changes separately from agent changes.

The result should tell the user which calls/fields were approved, which remain pending, why, and which dataset revision a future run should use.

## Gate before a model run on a new case

For **each new scenario/call**, even when the JSON already has a `success_if`:

1. Choose how task success is graded before the run: `assertion_only` when everything that decides success is checkable in code; a judge (BTC rubric J01 to J12) only when the quality of the wording is itself required, and then keep it a diagnostic beside the assertion. For each condition note the expected PASS/FAIL, the evidence needed, what happens when evidence is missing (`INCOMPLETE`), its source, reviewer and status. `must_say_any` is a phrase match, not a semantic judgment.
2. Set the expected tools from the source and the policy: required tools with their arguments, forbidden tools, tools required only under a condition, and whether auxiliary read-only tools are allowed. Do not turn a conditional tool into an unconditional one, and do not read a missing positive label as "all tools forbidden". Positive labels must match `success_if.tool_called` and `args_match`.
3. Check the scenarios load with the evaluation command (`run_eval.py --scenarios <dir> --only <id>` plans every call before it spends anything; `--no-extract` still runs the agent). Fix schema, GT or label errors in the input revision before running; keep the original file of a future BTC golden set for comparison and extend the planner if its schema has a field the planner does not support, never drop it silently.

This gate makes sure the labels are **complete and runnable**. It does not turn a diagnostic label into official ground truth.
