# -*- coding: utf-8 -*-
"""LLM providers.

One internal message format, three wire formats.

Internal messages::

    {"role": "user",      "content": "..."}
    {"role": "assistant", "content": "...", "tool_calls": [ToolCall, ...]}
    {"role": "tool",      "tool_call_id": "...", "name": "...", "content": "..."}

Every provider is reached with ``QgsBlockingNetworkRequest``, so the user's
proxy settings apply and no third-party HTTP library is needed.  All of these
functions run inside a ``QgsTask`` -- never call them on the GUI thread.
"""

import json
import uuid

from ..core import net, settings


class ProviderError(Exception):
    """Something went wrong talking to the model, phrased for the user."""


class ToolCall:
    __slots__ = ("id", "name", "arguments")

    def __init__(self, call_id, name, arguments):
        self.id = call_id or uuid.uuid4().hex[:12]
        self.name = name
        self.arguments = arguments if isinstance(arguments, dict) else {}

    def as_dict(self):
        return {"id": self.id, "name": self.name, "arguments": self.arguments}

    def __repr__(self):  # pragma: no cover
        return "<ToolCall {0}({1})>".format(self.name, self.arguments)


class Completion:
    __slots__ = ("text", "tool_calls", "raw", "usage")

    def __init__(self, text, tool_calls, raw=None, usage=None):
        self.text = text or ""
        self.tool_calls = tool_calls or []
        self.raw = raw
        self.usage = usage or {}


# ---------------------------------------------------------------------------


def complete(messages, tools, system_prompt, feedback=None):
    """Dispatch to the configured provider."""
    provider = settings.provider_id()
    model = settings.model_name()
    base = settings.base_url()
    api_key = settings.llm_api_key()

    if not model:
        raise ProviderError(
            "No model is configured. Open the Srot settings and pick one."
        )
    if settings.provider_spec()["needs_key"] and not api_key:
        raise ProviderError(
            "No API key found for {0}. Add one in the plugin settings, or set the "
            "{1} environment variable. Alternatively switch to Ollama, which runs "
            "locally and needs no key.".format(
                settings.provider_spec()["label"], settings.provider_spec().get("env")
            )
        )

    if provider == settings.PROVIDER_ANTHROPIC:
        return _anthropic(base, model, api_key, messages, tools, system_prompt, feedback)
    if provider == settings.PROVIDER_OLLAMA:
        return _ollama(base, model, messages, tools, system_prompt, feedback)
    return _openai(base, model, api_key, messages, tools, system_prompt, feedback)


# ---------------------------------------------------------------------------
# Anthropic
# ---------------------------------------------------------------------------


def _anthropic(base, model, api_key, messages, tools, system_prompt, feedback):
    wire = []
    for message in messages:
        role = message["role"]
        if role == "user":
            wire.append({"role": "user", "content": message["content"]})
        elif role == "assistant":
            blocks = []
            if message.get("content"):
                blocks.append({"type": "text", "text": message["content"]})
            for call in message.get("tool_calls", []):
                blocks.append(
                    {
                        "type": "tool_use",
                        "id": call.id,
                        "name": call.name,
                        "input": call.arguments,
                    }
                )
            if blocks:
                wire.append({"role": "assistant", "content": blocks})
        elif role == "tool":
            wire.append(
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "tool_result",
                            "tool_use_id": message["tool_call_id"],
                            "content": message["content"],
                        }
                    ],
                }
            )

    payload = {
        "model": model,
        "max_tokens": 4096,
        "system": system_prompt,
        "messages": wire,
        "tools": [
            {
                "name": tool["name"],
                "description": tool["description"],
                "input_schema": tool["parameters"],
            }
            for tool in tools
        ],
    }

    headers = {
        "x-api-key": api_key,
        "anthropic-version": "2023-06-01",
        "content-type": "application/json",
    }
    data = _post(base + "/v1/messages", payload, headers, feedback, "Anthropic")

    text_parts, calls = [], []
    for block in data.get("content", []):
        if block.get("type") == "text":
            text_parts.append(block.get("text", ""))
        elif block.get("type") == "tool_use":
            calls.append(ToolCall(block.get("id"), block.get("name"), block.get("input")))
    return Completion("\n".join(text_parts).strip(), calls, data, data.get("usage"))


# ---------------------------------------------------------------------------
# OpenAI and OpenAI-compatible
# ---------------------------------------------------------------------------


def _openai(base, model, api_key, messages, tools, system_prompt, feedback):
    wire = [{"role": "system", "content": system_prompt}]
    for message in messages:
        role = message["role"]
        if role == "user":
            wire.append({"role": "user", "content": message["content"]})
        elif role == "assistant":
            entry = {"role": "assistant", "content": message.get("content") or None}
            if message.get("tool_calls"):
                entry["tool_calls"] = [
                    {
                        "id": call.id,
                        "type": "function",
                        "function": {
                            "name": call.name,
                            "arguments": json.dumps(call.arguments),
                        },
                    }
                    for call in message["tool_calls"]
                ]
            wire.append(entry)
        elif role == "tool":
            wire.append(
                {
                    "role": "tool",
                    "tool_call_id": message["tool_call_id"],
                    "content": message["content"],
                }
            )

    payload = {
        "model": model,
        "messages": wire,
        "tools": [
            {
                "type": "function",
                "function": {
                    "name": tool["name"],
                    "description": tool["description"],
                    "parameters": tool["parameters"],
                },
            }
            for tool in tools
        ],
    }

    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["Authorization"] = "Bearer " + api_key

    data = _post(base + "/v1/chat/completions", payload, headers, feedback, "the model")

    choices = data.get("choices") or []
    if not choices:
        raise ProviderError("The model returned no choices. Raw response: {0}".format(
            json.dumps(data)[:500]))
    message = choices[0].get("message") or {}

    calls = []
    for raw_call in message.get("tool_calls") or []:
        function = raw_call.get("function") or {}
        calls.append(
            ToolCall(
                raw_call.get("id"),
                function.get("name"),
                _loads(function.get("arguments")),
            )
        )
    return Completion(message.get("content") or "", calls, data, data.get("usage"))


# ---------------------------------------------------------------------------
# Ollama
# ---------------------------------------------------------------------------


def _ollama(base, model, messages, tools, system_prompt, feedback):
    wire = [{"role": "system", "content": system_prompt}]
    for message in messages:
        role = message["role"]
        if role == "user":
            wire.append({"role": "user", "content": message["content"]})
        elif role == "assistant":
            entry = {"role": "assistant", "content": message.get("content") or ""}
            if message.get("tool_calls"):
                entry["tool_calls"] = [
                    {
                        "function": {
                            "name": call.name,
                            "arguments": call.arguments,
                        }
                    }
                    for call in message["tool_calls"]
                ]
            wire.append(entry)
        elif role == "tool":
            wire.append(
                {
                    "role": "tool",
                    "content": message["content"],
                    "name": message.get("name", ""),
                }
            )

    payload = {
        "model": model,
        "messages": wire,
        "stream": False,
        "tools": [
            {
                "type": "function",
                "function": {
                    "name": tool["name"],
                    "description": tool["description"],
                    "parameters": tool["parameters"],
                },
            }
            for tool in tools
        ],
        "options": {"temperature": 0.1},
    }

    try:
        data = _post(base + "/api/chat", payload, {"Content-Type": "application/json"},
                     feedback, "Ollama")
    except ProviderError as exc:
        raise ProviderError(
            "{0}\n\nIs Ollama running? Start it with `ollama serve`, then pull a "
            "tool-capable model, for example `ollama pull qwen3:8b`.".format(exc)
        )

    message = data.get("message") or {}
    calls = []
    for raw_call in message.get("tool_calls") or []:
        function = raw_call.get("function") or {}
        calls.append(ToolCall(None, function.get("name"), _loads(function.get("arguments"))))
    return Completion(message.get("content") or "", calls, data)


# ---------------------------------------------------------------------------


def _post(url, payload, headers, feedback, who):
    try:
        return net.post_json(url, payload, headers, feedback=feedback)
    except net.HttpError as exc:
        detail = (exc.body or "")[:600]
        if exc.status == 401:
            raise ProviderError(
                "{0} rejected the API key (HTTP 401). Check it in the plugin "
                "settings.\n{1}".format(who, detail)
            )
        if exc.status == 404:
            raise ProviderError(
                "{0} has no endpoint at {1} (HTTP 404). If you are using a "
                "self-hosted or compatible service, check the base URL in the "
                "plugin settings -- it should be the host root, without "
                "/v1.\n{2}".format(who, url, detail)
            )
        if exc.status == 429:
            raise ProviderError("{0} rate-limited the request. Wait and retry.\n{1}".format(who, detail))
        raise ProviderError("{0} returned an error: {1}\n{2}".format(who, exc, detail))
    except Exception as exc:
        raise ProviderError("Could not reach {0}: {1}".format(who, exc))


def _loads(value):
    if isinstance(value, dict):
        return value
    if not value:
        return {}
    try:
        parsed = json.loads(value)
        return parsed if isinstance(parsed, dict) else {}
    except (TypeError, ValueError):
        return {}


def test_connection(feedback=None):
    """Cheap round-trip used by the settings dialog."""
    completion = complete(
        [{"role": "user", "content": "Reply with exactly: OK"}],
        [],
        "You are a connection test. Reply with exactly: OK",
        feedback=feedback,
    )
    return completion.text.strip()
