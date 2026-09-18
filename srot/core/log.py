# -*- coding: utf-8 -*-
"""Where the plugin says what it decided not to fail on.

Several operations are best-effort by design: putting a network timeout back
the way it was, attaching an optional piece of metadata, tidying up a task on
unload. Failing any of those should not take the user's session down with it.

Swallowing the exception silently is the wrong way to express that, though.
It hides real bugs and leaves nobody anything to read when behaviour surprises
them. Every such site records what it skipped and why, in the plugin's own tab
of the QGIS log panel, where a curious user or a bug report can find it.
"""

from qgis.core import QgsMessageLog

from .compat import MSG_WARNING

LOG_TAG = "Srot"


def ignored(context, exc):
    """Record an exception that was deliberately not allowed to propagate.

    :param context: what was being attempted, in the user's terms.
    :param exc: the exception that was caught.
    """
    QgsMessageLog.logMessage(
        "{0} did not complete: {1}".format(context, exc), LOG_TAG, MSG_WARNING
    )
