#!/usr/bin/env python3
"""One place that talks to a language model, for every step that needs one.

Default: an OpenAI-compatible chat endpoint, configured by three lines in
`.env` (or the same names as environment variables / GitHub secrets):

    OPENAI_BASE_URL=https://.../v1
    OPENAI_API_KEY=...
    OPENAI_MODEL=gpt-6.1-terra
    OPENAI_MAX_TOKENS=24000        # optional: room for the reply, for models that reason at length
    OPENAI_THINKING=off            # optional: ask such a model to skip its long reasoning

If the first two are not set, the local `claude` command is used instead
(Sonnet 5.5), so the pipeline still runs on a laptop without a key.

    python3 scripts/llm.py            # check the endpoint: list its models, send one test message
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CLAUDE_MODEL = "claude-sonnet-5-5"
EFFORT = "medium"
_workdir: list[str] = []


def load_env(path: Path = ROOT / ".env") -> None:
    """KEY=value lines from .env into the environment, without overriding it."""
    if not path.exists():
        return
    for line in path.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            key, value = line.split("=", 1)
            value = value.strip().strip("'\"")
            if value:
                os.environ.setdefault(key.strip(), value)


def base_url() -> str:
    """The endpoint's address. A bare host gets the usual /v1 added."""
    from urllib.parse import urlparse
    base = os.environ["OPENAI_BASE_URL"].strip().rstrip("/")
    return base if urlparse(base).path.strip("/") else base + "/v1"


def backend() -> str:
    load_env()
    return "openai" if os.environ.get("OPENAI_BASE_URL") and os.environ.get("OPENAI_API_KEY") else "claude"


def model() -> str:
    """The model a call made now would use; stored with every answer."""
    if backend() == "openai":
        name = os.environ.get("OPENAI_MODEL")
        if not name:
            raise SystemExit("OPENAI_MODEL is not set: add the model's name to .env (python3 scripts/llm.py lists them)")
        return name
    return CLAUDE_MODEL


RETRY_WAITS = (15, 45, 120, 300, 300)      # seconds; an overloaded endpoint is waited out, not skipped


def _openai(prompt: str, system: str, name: str, effort: str, timeout: int) -> str:
    base, key = base_url(), os.environ["OPENAI_API_KEY"]
    body = {"model": name, "reasoning_effort": effort,
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": prompt}]}
    if os.environ.get("OPENAI_THINKING", "").strip().lower() in ("off", "false", "0", "no"):
        body["enable_thinking"] = False                 # reasoning models: answer without the long preamble
    if os.environ.get("OPENAI_MAX_TOKENS"):          # some models think at length and need room to answer after
        body["max_tokens"] = int(os.environ["OPENAI_MAX_TOKENS"])
    waits = list(RETRY_WAITS)
    while True:
        req = urllib.request.Request(base + "/chat/completions", data=json.dumps(body).encode(),
                                     headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return json.loads(resp.read())["choices"][0]["message"]["content"] or ""
        except urllib.error.HTTPError as err:
            detail = err.read().decode("utf-8", "replace")[:300]
            if err.code == 400 and "reasoning" in detail.lower() and "reasoning_effort" in body:
                body.pop("reasoning_effort")            # this model takes no effort setting
                continue
            # Rate limits and overloads pass; wait and ask again. Anything else is a real error.
            if "model_not_found" in detail or "no available channel" in detail:
                raise RuntimeError(f"the endpoint has no model named {name!r} for this key: {detail}") from None
            if err.code in (401, 403):
                raise RuntimeError(f"the endpoint rejected the key ({err.code}): {detail}") from None
            if err.code in (429, 500, 502, 503, 504, 529) and waits:
                time.sleep(waits.pop(0))
                continue
            raise RuntimeError(f"endpoint answered {err.code}: {detail}") from None
        except (urllib.error.URLError, TimeoutError, ConnectionError) as err:
            if waits:
                time.sleep(waits.pop(0))
                continue
            raise RuntimeError(f"endpoint not reachable: {err}") from None


def _claude(prompt: str, system: str, name: str, effort: str, timeout: int) -> str:
    if not _workdir:
        _workdir.append(tempfile.mkdtemp(prefix="bench-pool-llm-"))
    # The flags switch off tools, MCP servers, skills and session files: this is a plain
    # text-in, text-out call, and without them each call is about ten times slower.
    proc = subprocess.run(
        ["claude", "-p", "--model", name, "--effort", effort, "--output-format", "json", "--tools", "",
         "--strict-mcp-config", "--disable-slash-commands", "--no-session-persistence", "--system-prompt", system],
        input=prompt, capture_output=True, text=True, timeout=timeout, cwd=_workdir[0],
    )
    if proc.returncode != 0:
        raise RuntimeError(f"claude exited {proc.returncode}: {proc.stderr[:300]}")
    return json.loads(proc.stdout).get("result") or ""


def complete(prompt: str, system: str, effort: str = EFFORT, timeout: int = 900) -> str:
    """The model's reply as text."""
    name = model()
    return (_openai if backend() == "openai" else _claude)(prompt, system, name, effort, timeout)


def main() -> int:
    kind = backend()
    if kind != "openai":
        print("OPENAI_BASE_URL / OPENAI_API_KEY are not set in .env: the local `claude` command would be used.")
        return 0
    base = base_url()
    print("endpoint:", base)
    req = urllib.request.Request(base + "/models", headers={"Authorization": "Bearer " + os.environ["OPENAI_API_KEY"]})
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            names = sorted(m["id"] for m in json.loads(resp.read()).get("data", []))
        print(f"endpoint reachable; {len(names)} models:", ", ".join(names))
    except Exception as err:  # noqa: BLE001 - some endpoints have no model list
        print(f"could not list models ({err}); trying a message anyway")
    try:
        reply = complete("Reply with the single word: ready", "You follow instructions exactly.", timeout=120)
        print(f"model {model()} answered: {reply.strip()[:60]!r}")
    except Exception as err:  # noqa: BLE001
        print(f"model {os.environ.get('OPENAI_MODEL')!r} did not answer: {err}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
