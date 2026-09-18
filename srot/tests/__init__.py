# -*- coding: utf-8 -*-
"""Offline tests.

These run without QGIS by installing a small stub of the PyQGIS API into
``sys.modules`` first.  They cover the parts that carry the real logic: the
India catalogue and gazetteer, the tool registry and its schemas, the journal,
the provider wire formats, and a full dry run of the agent loop against a
scripted model.

Run them with::

    python3 -m srot.tests.run
"""
