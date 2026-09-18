# -*- coding: utf-8 -*-
"""The agent run loop.

This is a signal-driven state machine rather than a ``while`` loop, because
everything slow -- the LLM call, and any tool that downloads data -- has to run
on a ``QgsTask`` so QGIS stays responsive, while everything that touches
``QgsProject`` or a widget has to run on the GUI thread.

The cycle is::

    user text
      -> LlmTask (background)          model decides
      -> [tool.fetch] (background)     network, per tool call
      -> tool.apply   (GUI thread)     layers, canvas, project
      -> LlmTask (background)          ... until the model stops calling tools

A tool that raises :class:`~..agent.tools.ToolError` does not end the run: the
error text goes back to the model as the tool result so it can correct itself.
That is what makes it recover from a wrong field name instead of giving up.
"""

import json

from qgis.PyQt.QtCore import QObject, pyqtSignal
from qgis.core import QgsApplication

from ..core import settings
from ..core.tasks import CallableTask as _CallableTask
from ..core.journal import Journal
from . import prompts, providers, tools


class AgentRunner(QObject):
    """Drives one conversation."""

    #: (role, text) - role is "user", "assistant" or "system"
    message = pyqtSignal(str, str)
    #: (tool_name, arguments)
    tool_started = pyqtSignal(str, dict)
    #: (tool_name, result_or_error, ok)
    tool_finished = pyqtSignal(str, str, bool)
    #: (text) - status line updates
    status = pyqtSignal(str)
    busy_changed = pyqtSignal(bool)
    run_finished = pyqtSignal()
    failed = pyqtSignal(str)
    #: (tool_name, arguments) -> the UI must answer via :meth:`answer_confirmation`
    confirmation_requested = pyqtSignal(str, dict)

    def __init__(self, iface, parent=None):
        super().__init__(parent)
        self.iface = iface
        self.journal = Journal()
        self.context = tools.Context(iface, self.journal)
        self.messages = []
        self._queue = []
        self._steps = 0
        self._busy = False
        self._cancelled = False
        self._task = None
        self._pending_confirm = None

    # -- public API ---------------------------------------------------------

    def is_busy(self):
        return self._busy

    def reset(self):
        self.messages = []
        self._queue = []
        self._steps = 0
        self.journal.clear()
        self.context.notes = []

    def cancel(self):
        self._cancelled = True
        if self._task is not None:
            try:
                self._task.cancel()
            except Exception:
                pass
        self._set_busy(False)
        self.status.emit("Cancelled.")

    def send(self, text):
        """Start a turn.  Safe to call only when not busy."""
        if self._busy:
            self.failed.emit("The agent is still working. Wait for it, or press Stop.")
            return
        text = (text or "").strip()
        if not text:
            return

        self._cancelled = False
        self._steps = 0
        self.messages.append({"role": "user", "content": text})
        self.journal.add_prompt(text)
        self.message.emit("user", text)
        self._set_busy(True)
        self._ask_model()

    # -- model turn ---------------------------------------------------------

    def _ask_model(self):
        if self._cancelled:
            return self._set_busy(False)

        max_steps = max(1, settings.get_int("max_steps", 12))
        if self._steps >= max_steps:
            self.message.emit(
                "system",
                "Stopped after {0} steps. Ask me to continue if that was not "
                "enough -- you can raise the limit in the plugin settings.".format(max_steps),
            )
            return self._end_turn()
        self._steps += 1

        system_prompt = prompts.build(
            prompts.project_context(self.context.project, self.iface)
        )
        schemas = tools.schemas()
        history = list(self.messages)

        self.status.emit(
            "Thinking ({0}, step {1})...".format(settings.model_name(), self._steps)
        )

        def call():
            return providers.complete(history, schemas, system_prompt)

        self._run_task("Srot: model", call, self._on_model_reply)

    def _on_model_reply(self, task):
        if self._cancelled:
            return self._set_busy(False)
        if task.error is not None:
            return self._fail(str(task.error))

        completion = task.value
        if completion.text:
            self.message.emit("assistant", completion.text)
        self.messages.append(
            {
                "role": "assistant",
                "content": completion.text,
                "tool_calls": completion.tool_calls,
            }
        )

        if not completion.tool_calls:
            return self._end_turn()

        self._queue = list(completion.tool_calls)
        self._next_tool()

    # -- tool turn ----------------------------------------------------------

    def _next_tool(self):
        if self._cancelled:
            return self._set_busy(False)
        if not self._queue:
            return self._ask_model()

        call = self._queue.pop(0)
        try:
            tool = tools.get(call.name)
        except tools.ToolError as exc:
            return self._tool_result(call, str(exc), ok=False)

        self.tool_started.emit(call.name, dict(call.arguments))

        if tool.tier == tools.WRITE and settings.get_bool("confirm_writes"):
            self._pending_confirm = (call, tool)
            self.status.emit("Waiting for your confirmation...")
            self.confirmation_requested.emit(call.name, dict(call.arguments))
            return

        self._invoke(call, tool)

    def answer_confirmation(self, approved):
        """Called by the UI after :attr:`confirmation_requested`."""
        pending = self._pending_confirm
        self._pending_confirm = None
        if pending is None:
            return
        call, tool = pending
        if not approved:
            return self._tool_result(
                call,
                "The user declined this action. Do not retry it; ask them what "
                "they would prefer instead.",
                ok=False,
            )
        self._invoke(call, tool)

    def _invoke(self, call, tool):
        if tool.fetch is None:
            return self._apply(call, tool, None)

        self.status.emit("Fetching data for {0}...".format(call.name))
        arguments = dict(call.arguments)

        def fetch():
            return tool.fetch(arguments)

        def done(task):
            if self._cancelled:
                return self._set_busy(False)
            if task.error is not None:
                return self._tool_result(call, _describe(task.error), ok=False)
            self._apply(call, tool, task.value)

        self._run_task("Srot: {0}".format(call.name), fetch, done)

    def _apply(self, call, tool, payload):
        self.status.emit("Running {0}...".format(call.name))
        self.context.notes = []
        try:
            result = tool.apply(dict(call.arguments), self.context, payload)
        except Exception as exc:
            return self._tool_result(call, _describe(exc), ok=False)

        if self.context.notes:
            if isinstance(result, dict):
                result = dict(result)
                result.setdefault("notes", [])
                result["notes"] = list(result["notes"]) + list(self.context.notes)
            for note in self.context.notes:
                self.message.emit("system", note)

        self._tool_result(call, _stringify(result), ok=True)

    def _tool_result(self, call, content, ok):
        self.tool_finished.emit(call.name, content, ok)
        self.messages.append(
            {
                "role": "tool",
                "tool_call_id": call.id,
                "name": call.name,
                "content": content if ok else "ERROR: " + content,
            }
        )
        self._next_tool()

    # -- plumbing -----------------------------------------------------------

    def _run_task(self, description, function, on_done):
        task = _CallableTask(description, function)

        def completed():
            self._release(task)
            on_done(task)

        def terminated():
            self._release(task)
            if self._cancelled:
                self._set_busy(False)
                return
            on_done(task)

        task.taskCompleted.connect(completed)
        task.taskTerminated.connect(terminated)
        # Hold a Python reference for the whole life of the task. Without it
        # QGIS can collect the wrapper mid-run, which crashes the process.
        self._task = task
        QgsApplication.taskManager().addTask(task)

    def _release(self, task):
        if self._task is task:
            self._task = None

    def _end_turn(self):
        self._set_busy(False)
        self.status.emit("Ready.")
        self.run_finished.emit()

    def _fail(self, text):
        self._set_busy(False)
        self.status.emit("Failed.")
        self.failed.emit(text)

    def _set_busy(self, value):
        if value != self._busy:
            self._busy = value
            self.busy_changed.emit(value)


def _stringify(result):
    if isinstance(result, str):
        return result
    try:
        return json.dumps(result, ensure_ascii=False, default=str)[:20000]
    except Exception:
        return str(result)[:20000]


def _describe(exc):
    if isinstance(exc, tools.ToolError):
        return str(exc)
    name = type(exc).__name__
    return "{0}: {1}".format(name, exc)
