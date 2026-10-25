"""Pinned real extractor process. Fixture extractor implementation hashes unchanged."""
import json
import os
from pathlib import Path
import subprocess
import threading

from .assets import parse_json, parse_json_block
from .extractor import extractor_input

#: The product's extraction command, relative to the directory it runs from
#: (``evaluation/harness``; the descriptor's ``backend``).
COMMAND = "agent/extract_command.py"
MODULE = "agent.extract_command"
#: The most extraction calls one run may make: one per agent turn and configuration.
MAX_CALLS = 4096


class ModelExtractor:
    def __init__(self, assets, ref, manifest, recorder):
        if ref not in manifest["sources"]:raise ValueError("Extractor descriptor not pinned before Agent run")
        descriptor=assets.resolve(ref)
        if set(descriptor)!={"kind","version","python","backend","code","files","config","prompt","max_calls"} or descriptor["kind"]!="command_model":
            raise ValueError("Invalid real extractor descriptor")
        if descriptor["version"]!=manifest["configuration"]["extractor_version"]:raise ValueError("Extractor version mismatch")
        if type(descriptor["max_calls"]) is not int or not 1<=descriptor["max_calls"]<=MAX_CALLS:
            raise ValueError(f"Extractor requires explicit pinned budget 1–{MAX_CALLS}; no unbounded permission")
        for source in [descriptor["code"],descriptor["prompt"],*descriptor["files"]]:
            if source not in manifest["sources"]:raise ValueError("Extractor dependencies/prompt must be pinned")
            assets.resolve(source,json_content=False)
        # The command runs from the product's backend; the run pins a copy, and
        # the live file must be that copy byte for byte.
        backend=Path(descriptor["backend"])
        live=backend/COMMAND
        if (not backend.is_absolute() or not live.is_file()
                or live.read_bytes()!=assets.path(descriptor["code"]["path"]).read_bytes()):
            raise ValueError("Extractor command differs from the pinned copy, or the backend path is wrong")
        self.assets,self.descriptor,self.descriptor_ref,self.version=assets,descriptor,ref,descriptor["version"]
        self.backend,self.recorder,self.calls=backend,recorder,0
        # replay runs from several threads (collector); each attempt reserves its own number.
        self._lock=threading.Lock()

    def replay(self, document):
        with self._lock:
            if self.calls>=self.descriptor["max_calls"]:raise ValueError("Real extractor model budget exhausted")
            self.calls+=1
            attempt=self.calls
        instructions=self.assets.resolve(self.descriptor["prompt"],json_content=False).read_text(encoding="utf-8")
        payload={"config":self.descriptor["config"],"prompt":instructions+"\n[INPUT DATA]\n"+json.dumps(extractor_input(document),ensure_ascii=False)}
        # No GT/scenario/memory is transmitted to the extractor.
        try:
            env=dict(os.environ);env.pop("EVALUATION_APPROVAL_HMAC_KEY",None)
            # The command loads the repository's .env itself (agent/launch.py), inside the evaluator child.
            env["PYTHONUTF8"]="1"
            result=subprocess.run([self.descriptor["python"],"-B","-m",MODULE],cwd=self.backend,
                                  input=json.dumps(payload,ensure_ascii=False),text=True,encoding="utf-8",
                                  capture_output=True,timeout=150,env=env)  # room for the command's pacing under the provider's minute
            raw={"returncode":result.returncode,"stdout":result.stdout,"stderr":result.stderr}
            self.recorder(attempt,raw)
            obj=parse_json(result.stdout)
            if result.returncode!=0 or obj.get("raw") is None:raise ValueError("Extractor provider/format error; raw attempt retained")
            parsed=parse_json_block(obj["raw"])
            if set(parsed)!={"items"} or not isinstance(parsed["items"],list):raise ValueError("Extractor needs items array")
            return parsed["items"]
        except subprocess.TimeoutExpired as exc:
            self.recorder(attempt,{"returncode":None,"stdout":str(exc.stdout or ""),"stderr":"timeout; provider billing unreconciled"})
            raise ValueError("Extractor timeout; no retry") from exc
