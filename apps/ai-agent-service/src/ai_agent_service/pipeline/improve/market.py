"""One market research run: search, keep the evidence, draft a battlecard per product, gate it. ``docs/plan/002``.

Code drives every step and the model writes one answer per product: the queries come from the catalogue and
``config/market.yaml``, the searches go through the ``market`` MCP server under the role ``researcher`` (the only role
it serves), and what was found is stored as internal evidence before the MarketResearchAgent sees it as data. Cards
wait in ``IMPROVEMENT_DIR/market/cards.json`` for a person (``components/improvement/market.py``); nothing here
changes what the advisor reads.

    python -m ai_agent_service.pipeline.improve market-research --category gia-dung/may-loc-khong-khi
    python -m ai_agent_service.pipeline.improve market-cards [--status pending]
    python -m ai_agent_service.pipeline.improve market-decide --card <id> --decision approved --reviewer <name>
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from typing import Any, AsyncIterator, Iterable, Mapping, Sequence

from ...agents.market import MarketResearchAgent
from ...components import market as market_text
from ...components.improvement import market as battlecards
from ...mcp.tools import ToolBox

logger = logging.getLogger(__name__)

ROLE = "researcher"
SEARCH = "market_web_search"


@asynccontextmanager
async def researcher_tools(*, timeout: float = 20.0) -> AsyncIterator[ToolBox]:
    """The ``researcher`` role's tools over stdio, for this run only: the market server is a small subprocess with
    no database, so a run needs no deployed server, whatever ``MCP_TRANSPORT`` the service runs with."""
    from langchain.mcp import MCPAdapter

    from ...mcp import client

    async with MCPAdapter(client.client_group(ROLE, mode="stdio")) as adapter:
        tools = [client._unprefixed(tool) for tool in await adapter.list_tools()]
        yield ToolBox([tool for tool in tools if tool.name != "health"], timeout=timeout)


def queries(product: Mapping[str, Any]) -> list[str]:
    research = market_text.settings()["research"]
    category = str(product.get("category") or "")
    kinds: Mapping[str, str] = research.get("kinds") or {}
    kind = next((words for prefix, words in sorted(kinds.items(), key=lambda kv: -len(kv[0]))
                 if category.startswith(prefix)), "")
    values = {"name": product.get("name") or "", "brand": product.get("brand") or "", "kind": kind}
    found = [" ".join(str(template).format(**values).split()) for template in research.get("queries") or ()]
    return [q for q in dict.fromkeys(found) if q]


async def research_gaps(*, round_name: str, limit: int | None = None, tools: ToolBox | None = None,
                        agent: MarketResearchAgent | None = None) -> dict[str, Any]:
    """Draft an answer, from the web, for each open knowledge gap without one; the consultant decides on each."""
    from ...components.improvement import market_gaps

    config = market_gaps.settings()
    pending = market_gaps.open_gaps(limit or int(config.get("max_gaps_per_run") or 20))
    report: dict[str, Any] = {"round": round_name, "queries": 0, "gaps": []}
    if not pending:
        return report
    agent = agent or MarketResearchAgent()
    if agent.llm is None:
        raise ValueError("No model for agents.market: set it in config/models.yaml and its provider's key")
    if tools is None:
        async with researcher_tools() as box:
            return await _research_gaps(pending, report, box, agent, config)
    return await _research_gaps(pending, report, tools, agent, config)


async def _research_gaps(pending: Sequence[Mapping[str, Any]], report: dict[str, Any], tools: ToolBox,
                         agent: MarketResearchAgent, config: Mapping[str, Any]) -> dict[str, Any]:
    from ...components.improvement import market_gaps

    for gap in pending:
        outcome: dict[str, Any] = {"gap_id": gap["id"]}
        report["gaps"].append(outcome)
        query, skipped = market_gaps.query_of(gap)
        if query is None:
            outcome["skipped"] = skipped
            continue
        report["queries"] += 1
        envelope = await tools.call(SEARCH, query=query, max_results=int(config.get("results_per_query") or 5))
        if not envelope.get("ok"):
            error = envelope.get("error") or {}
            if error.get("code") in ("NOT_CONFIGURED", "NO_TOOL"):
                raise ValueError(f"Web search unavailable: {error.get('message')}")
            outcome["error"] = error.get("code")
            continue
        data = envelope["data"]
        results = list(data.get("results") or [])
        evidence_ids = battlecards.add_evidence([{"gap_id": gap["id"], "query": query, "provider": data.get("provider"),
                                                  "fetched_at": data.get("fetched_at"), **r} for r in results])
        question = market_gaps.question_of(gap)
        about = market_gaps.products_in(question)
        rules = market_gaps.public_rules(about)
        draft = await agent.answer_gap(question, about, rules, results) if results else None
        if draft is None or not draft.get("answerable"):
            status, reasons = "no_answer", []
        else:
            reasons = list(market_gaps.gate(draft, question=question, result_urls=[r["url"] for r in results],
                                            rules=rules))
            status = "flagged" if reasons else "ready"
        saved = market_gaps.save(gap["id"], {
            "status": status, "gate": reasons, "question": question, "query": query,
            "answer": (draft or {}).get("answer") or "", "cites": (draft or {}).get("cites") or [],
            "sources": [s for s in (draft or {}).get("sources") or [] if s in {r["url"] for r in results}],
            "note": (draft or {}).get("note") or "", "evidence_ids": evidence_ids, "model": agent.model_name,
            "grounds": market_gaps.grounds(draft or {}, result_urls=[r["url"] for r in results], rules=rules),
            "round": report["round"]})
        outcome.update(status=saved["status"], grounds=saved["grounds"], gate=reasons)
    return report


async def research(*, category: str | None = None, skus: Iterable[str] = (), round_name: str,
                   tools: ToolBox | None = None, agent: MarketResearchAgent | None = None,
                   limit: int | None = None) -> dict[str, Any]:
    """Research the products of *category* (or *skus*); returns what happened to each."""
    chosen = battlecards.products(category=category, skus=skus)
    if limit:
        chosen = chosen[:limit]
    if not chosen:
        raise ValueError("No product on sale matches that category or those SKUs")
    agent = agent or MarketResearchAgent()
    if agent.llm is None:
        raise ValueError("No model for agents.market: set it in config/models.yaml and its provider's key")
    if tools is None:
        async with researcher_tools() as box:
            return await _research(chosen, round_name, box, agent)
    return await _research(chosen, round_name, tools, agent)


async def _research(chosen: Sequence[Mapping[str, Any]], round_name: str, tools: ToolBox,
                    agent: MarketResearchAgent) -> dict[str, Any]:
    budget = int(market_text.settings()["research"].get("max_queries_per_run") or 60)
    spent = 0
    report: dict[str, Any] = {"round": round_name, "queries": 0, "products": []}
    for product in chosen:
        outcome: dict[str, Any] = {"sku": product["sku"], "name": product.get("name")}
        report["products"].append(outcome)
        rows: list[dict[str, Any]] = []
        for query in queries(product):
            if spent >= budget:
                outcome["stopped"] = f"max_queries_per_run ({budget}) reached"
                break
            spent += 1
            envelope = await tools.call(SEARCH, query=query)
            if not envelope.get("ok"):
                error = envelope.get("error") or {}
                if error.get("code") in ("NOT_CONFIGURED", "NO_TOOL"):
                    raise ValueError(f"Web search unavailable: {error.get('message')}")
                outcome.setdefault("errors", []).append(f"{query}: {error.get('code')}")
                continue
            data = envelope["data"]
            rows += [{"sku": product["sku"], "query": query, "provider": data.get("provider"),
                      "fetched_at": data.get("fetched_at"), **result} for result in data.get("results") or []]
        report["queries"] = spent
        unique = list({row["url"]: row for row in rows}.values())
        evidence_ids = battlecards.add_evidence(unique)
        outcome["results"] = len(unique)
        if not unique:
            outcome["card"] = "no results"
            if spent >= budget:
                break
            continue
        cites = battlecards.citable(str(product.get("category") or ""))
        written = await agent.write(product, cites, unique)
        if written is None:
            outcome["card"] = "model failed"
        elif written.get("no_card"):
            outcome["card"] = "no card"
        else:
            competitors = written.get("competitors") or []
            record = battlecards.add_card(written, product=product, round_name=round_name, model=agent.model_name,
                                          evidence_ids=evidence_ids, competitors=competitors,
                                          foreign_brands=[str(c.get("brand") or "") for c in competitors])
            outcome.update(card=record["id"], status=record["status"], gate=record["gate"])
        if spent >= budget:
            break
    return report
