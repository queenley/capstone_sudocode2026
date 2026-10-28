"""The two configurations every scenario runs in: the system (``full``) and the baseline without memory.

BTC compares the agent with itself minus memory (``reference_eval.py --baseline``). The baseline is the same agent,
the same scenarios and the same mock; only what it may know of earlier calls differs:

| | ``full`` | ``baseline_no_memory`` |
|---|---|---|
| Reads memory of earlier calls (``memory_read_previous``) | yes | no |
| ``seed_history`` (earlier sessions, orders) | written before the call | written too, never read back |
| ``crm.get_customer`` from the mock | as BTC returns it | ``sessions`` emptied (:func:`hide_history`) |
| Call Brief expected from call 2 on | yes (:func:`expects_call_brief`) | no |
| Trace file for BTC's scorer | ``full.jsonl`` | ``baseline.jsonl`` |

Every step asks this module instead of comparing config names itself.
"""
import copy

FULL = "full"
BASELINE = "baseline_no_memory"
CONFIGS = (FULL, BASELINE)
#: The file each configuration's trace is written to, as ``reference_eval.py --trace/--baseline`` reads it.
TRACE_FILE = {FULL: "full.jsonl", BASELINE: "baseline.jsonl"}


def reads_memory(config):
    """Whether the agent may read what earlier calls wrote (``memory_read_previous``)."""
    return config == FULL


def hide_history(result, config):
    """A business tool's *result* as *config* may see it: the baseline gets no earlier sessions from the CRM."""
    result = copy.deepcopy(result)
    if config == BASELINE and isinstance(result, dict):
        if "sessions" in result:
            result["sessions"] = []
        for candidate in result.get("candidates", []):
            if "sessions" in candidate:
                candidate["sessions"] = []
    return result


def expects_call_brief(context, result):
    """A Call Brief is due when memory is read, the call is not the first, and the caller was identified."""
    return (reads_memory(context["config"]) and context["call"] != "call_1"
            and result.get("customer_id") not in (None, "unidentified"))
