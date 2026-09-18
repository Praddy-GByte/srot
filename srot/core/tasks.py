# -*- coding: utf-8 -*-
"""Running one piece of work off the GUI thread.

Downloads are slow and QGIS is single-threaded, so anything that touches the
network runs here and everything that touches a layer runs on the GUI thread
afterwards. Kept in ``core`` so that the catalogue browser can use it without
importing the agent, and therefore without needing a model configured.
"""

import traceback

from qgis.core import QgsTask

from .compat import TASK_CAN_CANCEL


class CallableTask(QgsTask):
    """Run one callable off the GUI thread and keep whatever it returned.

    The result is read from :attr:`value` by whoever connected to
    ``taskCompleted``; failures arrive as :attr:`error` on ``taskTerminated``.
    Nothing is done in :meth:`finished`, so that all follow-up work is explicit
    and stays where the caller put it.
    """

    def __init__(self, description, function):
        super().__init__(description, TASK_CAN_CANCEL)
        self._function = function
        self.value = None
        self.error = None
        self.traceback = ""

    def run(self):
        try:
            self.value = self._function()
            return not self.isCanceled()
        except Exception as exc:  # QgsTask.run must never raise
            self.error = exc
            self.traceback = traceback.format_exc()
            return False

    def finished(self, result):
        pass
