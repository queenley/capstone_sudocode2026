"""P2 hook adapter for the team's agent.

The harness binds this file and calls its five hooks. No product code is imported
here: the agent runs in its own process, ``agent/bridge.py`` (``python -m
agent.bridge`` from ``evaluation/harness``) under ``apps/ai-agent-service``'s
virtualenv, and the two talk JSON lines over a pipe.

Every business tool the agent calls comes back through this adapter to the
harness's ``call_tool``, the harness's own copy of the organisers' mock, which
records the call and the state it changed. Nothing is retried, here or in the
agent (``retry`` below is what the harness checks; the bridge builds the agent
with retries off).

``product-bundle.json``, written by ``product.prepare`` beside this file,
names the agent's interpreter, the bridge module and the folders that make
the agent, with a hash of their code: a run refuses to start if the code
changed after preparation. Works on Windows and POSIX: the pipe is read by a
thread, not by ``selectors``, which only takes sockets on Windows.
"""
import hashlib
import json
import os
from pathlib import Path
import queue
import signal
import subprocess
import sys
import threading
import time

#: Source files hashed at preparation and checked at every start.
SUFFIXES = (".py", ".yaml", ".yml", ".json", ".md", ".txt")  # .md, .txt: the prompts
LIMIT = 4 * 1024 * 1024


def tree_sha256(folders):
    """One hash over every source file under *folders* (``{label: path}``)."""
    digest = hashlib.sha256()
    for label, folder in sorted(folders.items()):
        folder = Path(folder)
        for path in sorted(folder.rglob("*")):
            if path.is_file() and path.suffix in SUFFIXES and "__pycache__" not in path.parts:
                digest.update((label + "/" + path.relative_to(folder).as_posix()).encode())
                digest.update(hashlib.sha256(path.read_bytes()).digest())
    return digest.hexdigest()


def start_reader(process):
    """A thread that queues each line the child writes; ``None`` at EOF."""
    lines = queue.Queue()

    def pump():
        try:
            while True:
                line = process.stdout.readline(LIMIT + 1)
                if not line:
                    break
                lines.put(line)
        finally:
            lines.put(None)

    threading.Thread(target=pump, name="product-reader", daemon=True).start()
    process._evaluation_lines = lines


def read_message(process, deadline):
    try:
        line = process._evaluation_lines.get(timeout=max(0, deadline - time.monotonic()))
    except queue.Empty:
        raise TimeoutError("Product message deadline exceeded; no retry") from None
    if line is None or not line.endswith(b"\n"):
        raise RuntimeError("Product child exited with missing/partial message")
    if len(line) > LIMIT:
        raise ValueError("Product message exceeds 4MiB")
    return json.loads(line.decode("utf-8"))


def stop_process(process):
    if process is None:
        return
    try:
        process.wait(timeout=5)
    except subprocess.TimeoutExpired:
        process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=5)
    for stream in (process.stdin, process.stdout):
        if stream:
            stream.close()


def model_environment():
    env = dict(os.environ)
    env.pop("EVALUATION_APPROVAL_HMAC_KEY", None)
    env["MCP_TRANSPORT"] = "stdio"
    env["PYTHONUTF8"] = "1"
    return env


class ProductAdapter:
    capabilities = ("business_tools", "memory_isolation", "memory_read_gate", "after_call_barrier",
                    "snapshots", "briefs", "timestamps", "usage")
    retry = {"agent": 0, "tool": 0}

    #: Seconds a hook may take: starting five MCP servers, or a turn waiting on the provider's rate limit.
    TIMEOUT = 300

    def __init__(self):
        self.process = None
        self.runtime = None

        def stop(signum, frame):
            stop_process(self.process)
            raise SystemExit("Product adapter interrupted")
        signal.signal(signal.SIGTERM, stop)

    def send(self, obj):
        self.process.stdin.write((json.dumps(obj, ensure_ascii=False) + "\n").encode("utf-8"))
        self.process.stdin.flush()

    def receive(self):
        deadline = time.monotonic() + self.TIMEOUT
        while True:
            message = read_message(self.process, deadline)
            kind = message.get("type")
            if kind == "tool":
                try:
                    result = self.runtime["call_tool"](message["name"], message["args"])
                    self.send({"type": "tool_result", "result": result})
                except Exception as exception:
                    self.send({"type": "tool_result", "error": f"{type(exception).__name__}: {exception}",
                               "reconciliation_required": type(exception).__name__ == "ToolOutcomeUnknown"})
            elif kind == "event":
                self.runtime["emit"](message["event"])
            elif kind == "error":
                raise RuntimeError(f"Product failed: {message.get('error_type')}: {message.get('message')}")
            else:
                return message

    def open_scenario(self, context):
        self.runtime = context
        bundle = json.loads((Path(__file__).resolve().parent / "product-bundle.json").read_text(encoding="utf-8"))
        if tree_sha256(bundle["tree"]) != bundle["tree_sha256"]:
            raise ValueError("The agent's code changed after preparation; prepare a new run")
        self.process = subprocess.Popen(
            [bundle["python"], "-B", "-m", bundle["module"]], cwd=bundle["cwd"],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=sys.stderr, bufsize=0, env=model_environment(),
        )
        start_reader(self.process)
        safe = {k: context[k] for k in ("run_id", "config", "scenario_id", "namespace", "seed_history")}
        self.send({"mode": "lifecycle", "context": safe, "llm": bundle["llm"]})
        ready = self.receive()
        if ready.get("type") != "ready":
            raise ValueError("Product handshake failed")
        expected = context["configuration"]
        if ready["model"] != expected["model"] or ready["parameters"] != expected["parameters"]:
            raise ValueError("Loaded model or parameters differ from the manifest")

    def start_call(self, context):
        self.send({"type": "start_call", "context": context})
        return self.receive()["result"]

    def run_turn(self, text):
        self.send({"type": "turn", "text": text})
        return self.receive()["result"]

    def end_call(self):
        self.send({"type": "end_call"})
        return self.receive()["result"]

    def close_scenario(self):
        if self.process:
            if self.process.poll() is None:
                try:
                    self.send({"type": "close"})
                except OSError:
                    pass
            stop_process(self.process)


def factory():
    return ProductAdapter()
