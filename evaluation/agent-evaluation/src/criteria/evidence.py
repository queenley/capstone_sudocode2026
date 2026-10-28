"""What every criterion reads about one call of one configuration, gathered once by the Score step."""
from dataclasses import dataclass
from typing import Any, Callable


@dataclass
class CallEvidence:
    call_id: str                    # <run_id>/<config>/<scenario_id>/<call>
    config: str
    scenario_id: str
    call: str
    scenario: dict                  # the pinned scenario (BTC format)
    spec: dict                      # scenario["calls"][call]: ground_truth_facts, success_if, memory_expectation...
    trace: list                     # the BTC trace rows of the call
    tools: list                     # ToolEvent: every business tool call, with the mock's state before/after
    memories: list                  # MemoryEvidence: before_call / after_call snapshots
    extractions: list               # Extraction: questions, claims, fact usage, each quoted from the turn
    briefs: list                    # BriefEvidence: Call Brief / Handoff Brief objects
    grader: dict | None             # the grading contract of the call
    complete: bool                  # every planned turn has exactly one trace row
    tool_complete: bool             # the trace's tool calls are exactly the logged tool events
    extraction_complete: bool       # every planned turn was extracted once
    disputed: bool                  # the ground truth is under dispute: nothing is judged against it
    issue: Callable[..., dict]      # issue(code, message, classification="missing_evidence", origin=None)
    ref: Callable[[dict], dict]     # an evidence AssetRef as seen from the scored folder
    src: Any                        # Assets of the snapshotted evidence
    inputs: Any                     # Assets of the pinned inputs
    manifest: dict

    @property
    def ground_truth(self):
        return self.spec.get("ground_truth_facts", {})

    @property
    def fact_usage(self):
        """The facts the agent (or a tool result it read out) used, as extracted from its turns."""
        return [i for e in self.extractions for i in e["items"] if i["kind"] == "fact_usage" and i["speaker"] in ("agent", "tool")]

    @property
    def after_call_memory(self):
        return [m for m in self.memories if m["phase"] == "after_call"]
