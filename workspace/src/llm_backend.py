"""Single owner of "how we talk to a model".

Two responsibilities, deliberately in one module because they share one invariant (a role
maps to exactly one endpoint, alive or borrowed):

  * `ManagedServer` — lifecycle of an owned `llama-server` process: lazy spawn, health
    gate, restart with backoff, shutdown on exit.
  * `Provider` — the wire. Native `/completion`, not `/v1/chat/completions`: the prompt
    templates already emit raw ChatML, so going through the OpenAI endpoint would apply
    the chat template a second time. `/completion` also returns `timings` (including
    `cache_n`, the prefix-cache hit) and accepts `json_schema`, which llama.cpp compiles
    to a GBNF grammar and enforces during sampling.

Grammar-constrained decoding is the point. It moves "is this JSON well-formed" from the
model's reasoning into the decoder's transition function: malformed JSON becomes
unrepresentable rather than repaired after the fact. That deleted ~130 lines of regex
repair (unclosed strings, raw newlines, Python-style assignments, brace balancing).

stdlib only — no new dependency, and no `llama_cpp` import anywhere in the tree.
"""

from __future__ import annotations

import atexit
import http.client
import json
import signal
import subprocess
import sys
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field

from .config import LLAMA_SERVER_BIN, REQUEST_TIMEOUT_S

_CONTEXT_HINTS = ("context", "exceed", "too large", "too long", "n_ctx", "kv cache")


class ProviderError(RuntimeError):
    """llama-server refused or is unreachable."""


class ProviderContextError(ProviderError):
    """prompt + requested output exceed the context window."""


@dataclass
class Completion:
    text: str
    prompt_n: int = 0
    predicted_n: int = 0
    cache_n: int = 0
    prefill_ms: float = 0.0
    decode_tps: float = 0.0
    stop_type: str = ""

    @property
    def prefix_cache_hit(self) -> bool:
        return self.cache_n > 0

    @property
    def truncated(self) -> bool:
        """Generation stopped because it ran out of budget, not because it was finished.

        This is the one hole in grammar-constrained decoding: GBNF constrains every token
        it emits, so a COMPLETED object is always well-formed — but a run that hits
        `n_predict` is cut mid-object, and no grammar can close the braces retroactively.
        Observed in the wild (T43): the planner looped enumerating event IDs, burned all
        4096 tokens, and returned an unparsable prefix."""
        return self.stop_type == "limit"


class Provider:
    """HTTP client for one llama-server endpoint."""

    def __init__(self, name: str, base_url: str, *, token: str = "") -> None:
        self.name = name
        self.base_url = base_url.rstrip("/")
        # Built once. The header set used to be `{"Content-Type": "application/json"}` and
        # nothing else — no credential on any request, to an endpoint whose URL comes from an
        # environment variable and whose reply is executed as shell commands. `config` decides
        # WHICH endpoints may be reached (see `_assert_oracle_transport_is_safe`); this carries
        # the credential when one is required.
        self._headers = {"Content-Type": "application/json"}
        if token:
            self._headers["Authorization"] = f"Bearer {token}"

    def health(self, timeout: float = 3.0) -> bool:
        try:
            req = urllib.request.Request(self.base_url + "/health", headers=self._headers)
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return json.load(r).get("status") == "ok"
        except Exception:
            return False

    def complete(
        self,
        prompt: str,
        *,
        n_predict: int,
        stop: list[str] | None = None,
        json_schema: dict | None = None,
        temperature: float = 0.0,
        top_k: int = 1,
        top_p: float = 1.0,
        min_p: float = 0.0,
        repeat_penalty: float = 1.0,
        seed: int | None = None,
        cache_prompt: bool = True,
        timeout: float = REQUEST_TIMEOUT_S,
    ) -> Completion:
        body: dict = {
            "prompt": _sanitize(prompt),
            "n_predict": n_predict,
            "stop": stop or [],
            "temperature": temperature,
            "top_k": top_k,
            "top_p": top_p,
            "min_p": min_p,
            "repeat_penalty": repeat_penalty,
            # Keep the slot's KV so the fixed instruction prefix survives between calls.
            # MEASURED: this is also the reason a fixed seed alone does NOT make a run
            # reproducible. A cache hit changes the prefill batch shape, the batch shape
            # changes the floating-point reduction order, and the logits move. Three greedy
            # calls with seed=42 gave 2 distinct outputs (`cache_n` [0, 7, 7]); with
            # `cache_prompt: false` they gave 1 (`cache_n` [0, 0, 0]).
            "cache_prompt": cache_prompt,
        }
        # Pinning the RNG is what makes a benchmark a measurement rather than a draw.
        if seed is not None:
            body["seed"] = seed
        if json_schema is not None:
            body["json_schema"] = json_schema

        data = self._post("/completion", body, timeout)
        t = data.get("timings", {}) or {}
        return Completion(
            text=(data.get("content") or "").strip(),
            prompt_n=int(t.get("prompt_n") or 0),
            predicted_n=int(t.get("predicted_n") or 0),
            cache_n=int(t.get("cache_n") or 0),
            prefill_ms=float(t.get("prompt_ms") or 0.0),
            decode_tps=float(t.get("predicted_per_second") or 0.0),
            stop_type=str(data.get("stop_type") or ""),
        )

    def _post(self, path: str, body: dict, timeout: float) -> dict:
        payload = json.dumps(body).encode("utf-8")
        req = urllib.request.Request(
            self.base_url + path,
            data=payload,
            headers=self._headers,
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return json.load(r)
        except urllib.error.HTTPError as exc:
            detail = ""
            try:
                detail = exc.read().decode("utf-8", "ignore")
            except Exception:
                pass
            if exc.code == 400 and any(h in detail.lower() for h in _CONTEXT_HINTS):
                raise ProviderContextError(detail or "context exceeded") from exc
            raise ProviderError(f"{self.name}: HTTP {exc.code}: {detail[:300]}") from exc
        except urllib.error.URLError as exc:
            raise ProviderError(
                f"{self.name} unreachable at {self.base_url}: {exc.reason}"
            ) from exc
        except (OSError, http.client.HTTPException) as exc:
            # A connection RESET mid-response (WinError 10054), a timeout, or an incomplete read
            # surfaces here as a raw OSError/HTTPException — NOT a URLError, because it happens
            # while reading the body, after urlopen connected. Left unnormalized it propagates
            # uncaught and crashes the whole run (measured: it killed a benchmark case during
            # planning against the borrowed oracle). This IS the single HTTP boundary: turn every
            # transport failure into a typed ProviderError so the router can degrade, not die.
            raise ProviderError(f"{self.name} connection failed at {self.base_url}: {exc}") from exc


def _sanitize(text: str) -> str:
    """Drop lone surrogates: they survive pyte transcripts and break utf-8 encoding."""
    return "".join(ch for ch in str(text or "") if not 0xD800 <= ord(ch) <= 0xDFFF)


@dataclass
class ManagedServer:
    """An owned llama-server process. Lazy: nothing spawns until a role is first used."""

    name: str
    port: int
    args: list[str]
    boot_timeout_s: float = 180.0
    max_restarts: int = 3
    _proc: subprocess.Popen | None = field(default=None, repr=False)
    _restarts: int = 0
    _stopping: bool = False

    @property
    def provider(self) -> Provider:
        return Provider(self.name, f"http://127.0.0.1:{self.port}")

    def _spawn(self) -> None:
        if not LLAMA_SERVER_BIN.exists():
            raise ProviderError(
                f"llama-server not found at {LLAMA_SERVER_BIN}. "
                f"Set SISTEMISTA_LLAMA_SERVER_BIN or vendor it under workspace/bin/."
            )
        # cwd = the binary's folder so Windows resolves the CUDA DLLs sitting next to it.
        self._proc = subprocess.Popen(
            [str(LLAMA_SERVER_BIN)] + self.args,
            cwd=str(LLAMA_SERVER_BIN.parent),
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        _REGISTRY.add(self)

    def ensure_ready(self) -> Provider:
        p = self.provider
        if self._proc is not None and self._proc.poll() is None and p.health():
            return p
        if self._proc is None or self._proc.poll() is not None:
            if self._restarts > self.max_restarts:
                raise ProviderError(
                    f"{self.name}: llama-server crashed {self._restarts}x. Check VRAM/config."
                )
            self._restarts += 1
            self._spawn()

        deadline = time.time() + self.boot_timeout_s
        while time.time() < deadline:
            if self._proc is not None and self._proc.poll() is not None:
                raise ProviderError(
                    f"{self.name}: llama-server exited during boot (code {self._proc.returncode}). "
                    f"Most likely VRAM: check that the model + KV fit."
                )
            if p.health():
                return p
            time.sleep(0.4)
        raise ProviderError(f"{self.name}: llama-server not healthy within {self.boot_timeout_s}s")

    def stop(self) -> None:
        self._stopping = True
        if self._proc is not None and self._proc.poll() is None:
            self._proc.kill()
            try:
                self._proc.wait(timeout=15)
            except Exception:
                pass
        self._proc = None


class _Registry:
    """Owns teardown for every spawned server, whichever role spawned it."""

    def __init__(self) -> None:
        self._servers: list[ManagedServer] = []
        self._hooked = False

    def add(self, server: ManagedServer) -> None:
        if server not in self._servers:
            self._servers.append(server)
        if not self._hooked:
            atexit.register(self.stop_all)
            for sig in (signal.SIGINT, signal.SIGTERM):
                try:
                    prev = signal.getsignal(sig)
                    signal.signal(
                        sig,
                        lambda s, f, _p=prev: (
                            self.stop_all(),
                            _p(s, f) if callable(_p) else sys.exit(130),
                        ),
                    )
                except (ValueError, OSError):
                    pass  # not on the main thread — atexit still covers us
            self._hooked = True

    def stop_all(self) -> None:
        for s in self._servers:
            s.stop()


_REGISTRY = _Registry()
