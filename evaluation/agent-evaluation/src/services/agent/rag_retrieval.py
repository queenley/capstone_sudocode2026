"""Run the product's actual kb_search with its own Python environment (``python -m src.services.agent.rag_retrieval``, from ``evaluation/agent-evaluation``)."""
import asyncio
import json
import sys

from src.services.agent import launch

launch.prepare()

from ai_agent_service.mcp.servers.knowledge import kb_search  # noqa: E402


async def main():
    questions = json.loads(sys.stdin.buffer.read().decode("utf-8"))
    results = {}
    for item in questions:
        response = await kb_search(query=item["question"], k=5, on=item["on"])
        results[item["qid"]] = [hit["chunk_id"] for hit in response["hits"]]
    sys.stdout.buffer.write(json.dumps(results, ensure_ascii=False).encode("utf-8"))


if __name__ == "__main__":
    asyncio.run(main())
