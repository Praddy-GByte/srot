# -*- coding: utf-8 -*-
"""Srot - an India-first AI GIS agent for QGIS.

This module only exposes the QGIS plugin entry point. All real work lives in
the sub-packages so that nothing heavy is imported at QGIS startup.
"""

__version__ = "0.1.2"
__author__ = "Srot contributors"
__license__ = "GPL-3.0-or-later"


def classFactory(iface):  # noqa: N802  (name mandated by QGIS)
    """Entry point required by QGIS.

    :param iface: a :class:`qgis.gui.QgisInterface` instance.
    """
    from .plugin import SrotPlugin

    return SrotPlugin(iface)
