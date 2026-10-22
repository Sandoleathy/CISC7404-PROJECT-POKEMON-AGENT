"""pi-knowledge bridge and the ``search_knowledge`` model tool.

pi-knowledge is a Node extension, so a small persistent Node process hosts its
official extension entry and speaks JSON lines with this module.  The Python
side never imports Node internals; it only calls the registered
``knowledge_search`` / ``knowledge_show`` / ``knowledge_status`` tools.
"""

from __future__ import annotations

import atexit
import json
import os
import queue
import shutil
import subprocess
import threading
from pathlib import Path
from typing import Literal

from pi_python import tool

from config import PI_AGENT_DIR

BRIDGE_SCRIPT = PI_AGENT_DIR / "knowledge_bridge.mjs"
DEFAULT_PACKAGE = Path.home() / ".pi" / "agent" / "npm" / "node_modules" / "pi-knowledge" / "extension.js"
SEARCH_MODES = ("auto", "fast", "semantic", "hybrid", "semantic_hybrid", "deep", "adaptive")


class KnowledgeUnavailable(RuntimeError):
    """Raised when the Node side cannot be started or stops responding."""


class KnowledgeBridge:
    """Lazy, thread-safe owner of one persistent pi-knowledge Node process."""

    def __init__(
        self,
        *,
        enabled: bool = True,
        knowledge_dir: Path | None = None,
        package: Path | None = None,
        node: str | None = None,
        timeout: float = 60.0,
    ) -> None:
        self.enabled = enabled
        self.knowledge_dir = knowledge_dir
        self.package = package
        self.node = node
        self.timeout = timeout
        self._lock = threading.Lock()
        self._proc: subprocess.Popen | None = None
        self._stdout_queue: queue.Queue[dict] = queue.Queue()
        self._ready_queue: queue.Queue[dict] = queue.Queue()
        self._stderr_lines: list[str] = []
        self._request_id = 0
        self._threads: list[threading.Thread] = []
        atexit.register(self.close)

    # ------------------------------------------------------------------ process
    def _node_executable(self) -> str:
        candidate = self.node or shutil.which("node")
        if not candidate:
            raise KnowledgeUnavailable(
                "Node.js was not found on PATH; set PI_KNOWLEDGE_NODE_PATH to node.exe"
            )
        return candidate

    def _package_entry(self) -> Path:
        if self.package is not None:
            return Path(self.package).expanduser().resolve()
        return DEFAULT_PACKAGE.resolve()

    def _read_stdout(self) -> None:
        assert self._proc is not None and self._proc.stdout is not None
        for line in self._proc.stdout:
            text = line.strip()
            if not text:
                continue
            try:
                payload = json.loads(text)
            except json.JSONDecodeError:
                self._stderr_lines.append(f"non-JSON bridge stdout: {text[:500]}")
                continue
            if not isinstance(payload, dict):
                continue
            if "ready" in payload:
                self._ready_queue.put(payload)
            elif "id" in payload:
                self._stdout_queue.put(payload)
        self._stdout_queue.put({"__eof__": True})

    def _read_stderr(self) -> None:
        assert self._proc is not None and self._proc.stderr is not None
        for line in self._proc.stderr:
            text = line.rstrip()
            if not text:
                continue
            self._stderr_lines.append(text)
            if len(self._stderr_lines) > 40:
                del self._stderr_lines[:20]

    def _stderr_tail(self, limit: int = 6) -> str:
        return " | ".join(self._stderr_lines[-limit:])

    def _start(self) -> None:
        if self._proc is not None and self._proc.poll() is None:
            return
        if not BRIDGE_SCRIPT.exists():
            raise KnowledgeUnavailable(f"missing bridge script: {BRIDGE_SCRIPT}")
        package = self._package_entry()
        if not package.exists():
            raise KnowledgeUnavailable(
                f"pi-knowledge extension not found at {package}; set PI_KNOWLEDGE_PACKAGE"
            )

        env = os.environ.copy()
        env["PI_KNOWLEDGE_PACKAGE"] = str(package)
        if self.knowledge_dir is not None:
            env["PI_KNOWLEDGE_DIR"] = str(Path(self.knowledge_dir).expanduser().resolve())

        creationflags = 0
        if os.name == "nt":
            creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)

        self._stderr_lines = []
        self._stdout_queue = queue.Queue()
        self._ready_queue = queue.Queue()
        self._proc = subprocess.Popen(
            [self._node_executable(), str(BRIDGE_SCRIPT)],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
            bufsize=1,
            cwd=str(PI_AGENT_DIR),
            env=env,
            creationflags=creationflags,
        )
        self._threads = [
            threading.Thread(target=self._read_stdout, name="pi-knowledge-stdout", daemon=True),
            threading.Thread(target=self._read_stderr, name="pi-knowledge-stderr", daemon=True),
        ]
        for thread in self._threads:
            thread.start()

        try:
            ready = self._ready_queue.get(timeout=min(30.0, self.timeout))
        except queue.Empty as exc:
            self._terminate()
            raise KnowledgeUnavailable(
                f"pi-knowledge bridge did not become ready: {self._stderr_tail()}"
            ) from exc
        if not ready.get("ready"):
            self._terminate()
            raise KnowledgeUnavailable(
                f"pi-knowledge bridge failed: {ready.get('error') or self._stderr_tail()}"
            )

    def _terminate(self) -> None:
        proc = self._proc
        self._proc = None
        if proc is None:
            return
        try:
            if proc.poll() is None:
                proc.terminate()
                try:
                    proc.wait(timeout=2)
                except subprocess.TimeoutExpired:
                    proc.kill()
        except OSError:
            pass

    # ------------------------------------------------------------------ requests
    def _request(self, action: str, params: dict) -> dict:
        with self._lock:
            self._start()
            assert self._proc is not None and self._proc.stdin is not None
            self._request_id += 1
            request_id = self._request_id
            try:
                self._proc.stdin.write(json.dumps({"id": request_id, "action": action, "params": params}) + "\n")
                self._proc.stdin.flush()
            except (BrokenPipeError, OSError) as exc:
                self._terminate()
                raise KnowledgeUnavailable(f"could not write to pi-knowledge: {exc}") from exc

            try:
                while True:
                    response = self._stdout_queue.get(timeout=self.timeout)
                    if response.get("__eof__"):
                        self._terminate()
                        raise KnowledgeUnavailable(
                            f"pi-knowledge process exited: {self._stderr_tail()}"
                        )
                    if response.get("id") == request_id:
                        return response
            except queue.Empty as exc:
                self._terminate()
                raise KnowledgeUnavailable(
                    f"pi-knowledge request timed out after {self.timeout:.0f}s: {self._stderr_tail()}"
                ) from exc

    # ------------------------------------------------------------------ public API
    def search(
        self,
        query: str,
        *,
        mode: str = "hybrid",
        limit: int = 5,
        kb_id: str = "",
    ) -> str:
        if not self.enabled:
            return "Knowledge search is disabled (PI_AGENT_KNOWLEDGE=0)."
        query = (query or "").strip()
        if not query:
            return "Knowledge search needs a non-empty query."
        if mode not in SEARCH_MODES:
            mode = "hybrid"
        limit = max(1, min(10, int(limit)))
        params: dict = {"query": query, "mode": mode, "limit": limit}
        if kb_id and kb_id.strip():
            params["kb_id"] = kb_id.strip()
        try:
            response = self._request("search", params)
        except KnowledgeUnavailable as exc:
            return f"Knowledge search is unavailable: {exc}. Continue without RAG."
        if response.get("ok"):
            return response.get("text") or "No results found."
        return f"Knowledge search failed: {response.get('error', 'unknown error')}. Continue without RAG."

    def show(self) -> str:
        if not self.enabled:
            return "Knowledge search is disabled (PI_AGENT_KNOWLEDGE=0)."
        try:
            response = self._request("show", {})
        except KnowledgeUnavailable as exc:
            return f"Knowledge tool is unavailable: {exc}"
        return response.get("text") or response.get("error") or "No knowledge bases."

    def close(self) -> None:
        with self._lock:
            proc = self._proc
            if proc is None:
                return
            try:
                if proc.poll() is None and proc.stdin is not None:
                    proc.stdin.write(json.dumps({"id": 0, "action": "close"}) + "\n")
                    proc.stdin.flush()
                    proc.wait(timeout=2)
            except (OSError, subprocess.TimeoutExpired):
                pass
            finally:
                self._terminate()


def build_knowledge_tool(bridge: KnowledgeBridge | None):
    """Return a pi-agent tool that searches the pi-knowledge base.

    The tool returns readable text (including a graceful "unavailable" result),
    so a missing Node install or an empty knowledge base never aborts a battle.
    """

    @tool(name="search_knowledge")
    def search_knowledge(
        query: str,
        mode: Literal["auto", "fast", "semantic", "hybrid", "semantic_hybrid", "deep", "adaptive"] = "hybrid",
        limit: int = 5,
        kb_id: str = "",
    ) -> str:
        """Search the local Pokemon knowledge base built with pi-knowledge.

        Use this for strategy, matchup, move/ability/item, format or team
        questions that are not already answered by the battle state. Results
        include source file paths and snippets.

        Args:
            query: Natural-language question or keywords, for example
                "how to beat Garganacl with Garchomp".
            mode: Retrieval mode. "hybrid" combines BM25 and embeddings and is
                the default; "fast" is lexical-only for exact names; "semantic"
                is vector-only; "deep" enables reranking.
            limit: Maximum number of chunks to return (1-10).
            kb_id: Optional knowledge-base name or ID; empty searches all bases.
        """
        if bridge is None:
            return "Knowledge search is not configured for this player."
        return bridge.search(query, mode=mode, limit=limit, kb_id=kb_id)

    return search_knowledge
