# -*- coding: utf-8 -*-
"""A stub of the PyQGIS API, just large enough to import and exercise the plugin.

This is not a QGIS emulator.  It implements the handful of classes the plugin
actually touches, with real behaviour where the tests depend on it (signals,
the task manager, the project's layer registry) and inert stubs everywhere else.

``install()`` must be called before importing any plugin module.
"""

import sys
import types


# --- signals ---------------------------------------------------------------


class _BoundSignal:
    def __init__(self):
        self._slots = []

    def connect(self, slot):
        self._slots.append(slot)

    def disconnect(self, slot=None):
        if slot is None:
            self._slots = []
        elif slot in self._slots:
            self._slots.remove(slot)

    def emit(self, *args):
        for slot in list(self._slots):
            slot(*args)

    def __call__(self, *args):
        self.emit(*args)


class pyqtSignal(object):  # noqa: N801 - mirrors the PyQt name
    def __init__(self, *types):
        self.types = types
        self._name = None

    def __set_name__(self, owner, name):
        self._name = name

    def __get__(self, instance, owner=None):
        if instance is None:
            return self
        store = instance.__dict__.setdefault("_srot_signals", {})
        key = self._name or id(self)
        if key not in store:
            store[key] = _BoundSignal()
        return store[key]


class QObject(object):
    def __init__(self, parent=None):
        self._parent = parent


# --- enums -----------------------------------------------------------------


class _Enum(object):
    def __init__(self, **values):
        for key, value in values.items():
            setattr(self, key, value)


class Qt(object):
    AlignmentFlag = _Enum(AlignLeft=1, AlignRight=2, AlignTop=32, AlignVCenter=128)
    Orientation = _Enum(Horizontal=1, Vertical=2)
    DockWidgetArea = _Enum(RightDockWidgetArea=2)
    Key = _Enum(Key_Return=0x01000004, Key_Enter=0x01000005)
    KeyboardModifier = _Enum(ControlModifier=0x04000000)
    TextInteractionFlag = _Enum(TextBrowserInteraction=13)
    CursorShape = _Enum(WaitCursor=3)
    ScrollBarPolicy = _Enum(ScrollBarAsNeeded=0)


# --- tiny value types ------------------------------------------------------


class QUrl(object):
    def __init__(self, url=""):
        self._url = url

    def toString(self):
        return self._url


class QByteArray(bytes):
    def size(self):
        return len(self)


class QNetworkRequest(object):
    KnownHeaders = _Enum(ContentTypeHeader=0)
    Attribute = _Enum(HttpStatusCodeAttribute=0, RedirectPolicyAttribute=1)
    RedirectPolicy = _Enum(NoLessSafeRedirectPolicy=1)

    def __init__(self, url=None):
        self.url = url
        self.headers = {}

    def setRawHeader(self, key, value):  # noqa: N802
        self.headers[bytes(key)] = bytes(value)

    def setHeader(self, key, value):  # noqa: N802
        self.headers[key] = value


class QgsBlockingNetworkRequest(object):
    NoError = 0

    def __init__(self):
        self._reply = None

    def setAuthCfg(self, cfg):  # noqa: N802
        pass

    def get(self, request, force=False, feedback=None):
        raise NotImplementedError("Tests must patch srot.core.net")

    def post(self, request, data, force=False, feedback=None):
        raise NotImplementedError("Tests must patch srot.core.net")

    def errorMessage(self):  # noqa: N802
        return "mock"

    def reply(self):
        return self._reply


# --- tasks -----------------------------------------------------------------


class QgsTask(QObject):
    Flag = _Enum(CanCancel=1)
    CanCancel = 1

    taskCompleted = pyqtSignal()
    taskTerminated = pyqtSignal()

    def __init__(self, description="", flags=0):
        QObject.__init__(self)
        self._description = description
        self._cancelled = False
        self._progress = 0.0

    def isCanceled(self):  # noqa: N802
        return self._cancelled

    def cancel(self):
        self._cancelled = True

    def setProgress(self, value):  # noqa: N802
        self._progress = value

    def run(self):  # pragma: no cover - subclasses override
        return True

    def finished(self, result):  # pragma: no cover
        pass


class _TaskManager(object):
    """Runs tasks synchronously so tests are deterministic."""

    def __init__(self):
        self.count = 0

    def addTask(self, task):  # noqa: N802
        self.count += 1
        ok = False
        try:
            ok = task.run()
        except Exception:  # a real QgsTask must never raise; mirror that
            ok = False
        try:
            task.finished(ok)
        except Exception:
            pass
        if ok:
            task.taskCompleted.emit()
        else:
            task.taskTerminated.emit()


# --- project ---------------------------------------------------------------


class QgsCoordinateReferenceSystem(object):
    def __init__(self, definition=""):
        self._authid = definition

    def authid(self):
        return self._authid

    def isValid(self):  # noqa: N802
        return bool(self._authid)

    def __eq__(self, other):
        return isinstance(other, QgsCoordinateReferenceSystem) and other._authid == self._authid


class QgsRectangle(object):
    def __init__(self, xmin=0.0, ymin=0.0, xmax=0.0, ymax=0.0):
        self._values = [xmin, ymin, xmax, ymax]

    def xMinimum(self):  # noqa: N802
        return self._values[0]

    def yMinimum(self):  # noqa: N802
        return self._values[1]

    def xMaximum(self):  # noqa: N802
        return self._values[2]

    def yMaximum(self):  # noqa: N802
        return self._values[3]

    def scale(self, factor):
        pass


class QgsBox3D(object):
    def __init__(self, xmin=0.0, ymin=0.0, zmin=0.0, xmax=0.0, ymax=0.0, zmax=0.0):
        self._values = [xmin, ymin, zmin, xmax, ymax, zmax]


class QDateTime(object):
    def __init__(self, *parts):
        self._parts = parts


class QgsDateTimeRange(object):
    def __init__(self, begin=None, end=None):
        self._begin = begin
        self._end = end


class QgsAbstractMetadataBase(object):
    class Contact(object):
        def __init__(self, name=""):
            self.name = name
            self.organization = ""
            self.role = ""

    class Link(object):
        def __init__(self, name=""):
            self.name = name
            self.type = ""
            self.url = ""
            self.description = ""

    def __init__(self):
        self._values = {
            "identifier": "",
            "title": "",
            "type": "",
            "language": "",
            "abstract": "",
            "licenses": [],
            "rights": [],
            "contacts": [],
            "links": [],
            "crs": None,
            "extent": None,
        }
        self._keywords = {}

    def keywords(self, vocabulary=None):
        if vocabulary is None:
            return dict(self._keywords)
        return list(self._keywords.get(vocabulary, []))

    def addKeywords(self, vocabulary, terms):  # noqa: N802
        self._keywords.setdefault(vocabulary, []).extend(terms)

    def identifier(self):
        return self._values["identifier"]

    def setIdentifier(self, value):  # noqa: N802
        self._values["identifier"] = value

    def title(self):
        return self._values["title"]

    def setTitle(self, value):  # noqa: N802
        self._values["title"] = value

    def type(self):
        return self._values["type"]

    def setType(self, value):  # noqa: N802
        self._values["type"] = value

    def language(self):
        return self._values["language"]

    def setLanguage(self, value):  # noqa: N802
        self._values["language"] = value

    def abstract(self):
        return self._values["abstract"]

    def setAbstract(self, value):  # noqa: N802
        self._values["abstract"] = value

    def licenses(self):
        return list(self._values["licenses"])

    def setLicenses(self, value):  # noqa: N802
        self._values["licenses"] = list(value)

    def rights(self):
        return list(self._values["rights"])

    def setRights(self, value):  # noqa: N802
        self._values["rights"] = list(value)

    def contacts(self):
        return list(self._values["contacts"])

    def setContacts(self, value):  # noqa: N802
        self._values["contacts"] = list(value)

    def links(self):
        return list(self._values["links"])

    def setLinks(self, value):  # noqa: N802
        self._values["links"] = list(value)


class QgsLayerMetadata(QgsAbstractMetadataBase):
    class SpatialExtent(object):
        def __init__(self):
            self.extentCrs = None
            self.bounds = None

    class Extent(object):
        def __init__(self):
            self._spatial = []
            self._temporal = []

        def setSpatialExtents(self, value):  # noqa: N802
            self._spatial = list(value)

        def spatialExtents(self):  # noqa: N802
            return list(self._spatial)

        def setTemporalExtents(self, value):  # noqa: N802
            self._temporal = list(value)

        def temporalExtents(self):  # noqa: N802
            return list(self._temporal)

    def crs(self):
        return self._values["crs"]

    def setCrs(self, value):  # noqa: N802
        self._values["crs"] = value

    def extent(self):
        return self._values["extent"]

    def setExtent(self, value):  # noqa: N802
        self._values["extent"] = value


class _Field(object):
    def __init__(self, name):
        self._name = name

    def name(self):
        return self._name

    def typeName(self):  # noqa: N802
        return "String"


class _Fields(list):
    def indexOf(self, name):  # noqa: N802
        for index, field in enumerate(self):
            if field.name() == name:
                return index
        return -1


class QgsMapLayer(object):
    _counter = [0]

    def __init__(self, source="", name="layer"):
        QgsMapLayer._counter[0] += 1
        self._id = "{0}_{1:03d}".format(name.replace(" ", "_"), QgsMapLayer._counter[0])
        self._name = name
        self._source = source
        self._valid = True
        self._crs = QgsCoordinateReferenceSystem("EPSG:4326")
        self._subset = ""
        self._metadata = QgsLayerMetadata()

    def id(self):
        return self._id

    def name(self):
        return self._name

    def setName(self, value):  # noqa: N802
        self._name = value

    def isValid(self):  # noqa: N802
        return self._valid

    def crs(self):
        return self._crs

    def extent(self):
        return QgsRectangle(68.0, 6.0, 97.5, 37.6)

    def publicSource(self):  # noqa: N802
        return self._source

    def triggerRepaint(self):  # noqa: N802
        pass

    def setOpacity(self, value):  # noqa: N802
        pass

    def error(self):
        return types.SimpleNamespace(summary=lambda: "")

    def metadata(self):
        return self._metadata

    def setMetadata(self, value):  # noqa: N802
        self._metadata = value


class QgsVectorLayer(QgsMapLayer):
    def __init__(self, source="", name="layer", provider="ogr"):
        QgsMapLayer.__init__(self, source, name)
        self._fields = _Fields(
            [_Field("name"), _Field("district"), _Field("st_nm"), _Field("avg_value")]
        )
        self._features = 10
        self._geom = 0  # 0 point, 1 line, 2 polygon, 4 null (geometryless)
        self._renderer = QgsSingleSymbolRenderer(QgsSymbol(0))

    def featureCount(self):  # noqa: N802
        return self._features

    def fields(self):
        return self._fields

    def geometryType(self):  # noqa: N802
        return self._geom

    def subsetString(self):  # noqa: N802
        return self._subset

    def setSubsetString(self, value):  # noqa: N802
        self._subset = value
        return True

    def uniqueValues(self, index, limit=0):  # noqa: N802
        return {"Pune", "Nagpur", "Nashik"}

    def dataProvider(self):  # noqa: N802
        return types.SimpleNamespace(addFeatures=lambda feats: True)

    def updateExtents(self):  # noqa: N802
        pass

    def renderer(self):
        return self._renderer

    def setRenderer(self, renderer):  # noqa: N802
        # The real setRenderer takes ownership and renderer() hands back the
        # same object, which the categorized path relies on.
        self._renderer = renderer


class QgsRasterLayer(QgsMapLayer):
    def __init__(self, source="", name="layer", provider=""):
        QgsMapLayer.__init__(self, source, name)


class _LayoutManager(object):
    def __init__(self):
        self._layouts = []

    def layouts(self):
        return list(self._layouts)

    def layoutByName(self, name):  # noqa: N802
        for layout in self._layouts:
            if layout.name() == name:
                return layout
        return None

    def addLayout(self, layout):  # noqa: N802
        self._layouts.append(layout)
        return True


class QgsProject(object):
    _instance = None

    def __init__(self):
        self._layers = {}
        self._layout_manager = _LayoutManager()

    @classmethod
    def instance(cls):
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    def addMapLayer(self, layer):  # noqa: N802
        self._layers[layer.id()] = layer
        return layer

    def removeMapLayer(self, layer_id):  # noqa: N802
        self._layers.pop(layer_id, None)

    def mapLayers(self):  # noqa: N802
        return dict(self._layers)

    def mapLayer(self, layer_id):  # noqa: N802
        return self._layers.get(layer_id)

    def layoutManager(self):  # noqa: N802
        return self._layout_manager

    def transformContext(self):  # noqa: N802
        return None


# --- processing registry ---------------------------------------------------


class _ParameterDefinition(object):
    FlagOptional = 1

    def __init__(self, name, description, optional=False, default=None):
        self._name = name
        self._description = description
        self._flags = self.FlagOptional if optional else 0
        self._default = default

    def name(self):
        return self._name

    def description(self):
        return self._description

    def type(self):
        return "generic"

    def flags(self):
        return self._flags

    def defaultValue(self):  # noqa: N802
        return self._default


class _Algorithm(object):
    def __init__(self, algorithm_id, display, params, tags=()):
        self._id = algorithm_id
        self._display = display
        self._params = params
        self._tags = list(tags)

    def id(self):
        return self._id

    def displayName(self):  # noqa: N802
        return self._display

    def group(self):
        return "Vector geometry"

    def tags(self):
        return self._tags

    def parameterDefinitions(self):  # noqa: N802
        return self._params

    def outputDefinitions(self):  # noqa: N802
        return [types.SimpleNamespace(name=lambda: "OUTPUT")]


class _ProcessingRegistry(object):
    def __init__(self):
        self._algorithms = [
            _Algorithm(
                "native:buffer",
                "Buffer",
                [
                    _ParameterDefinition("INPUT", "Input layer"),
                    _ParameterDefinition("DISTANCE", "Distance", default=10.0),
                    _ParameterDefinition("SEGMENTS", "Segments", optional=True, default=5),
                    _ParameterDefinition("DISSOLVE", "Dissolve", optional=True, default=False),
                    _ParameterDefinition("OUTPUT", "Buffered"),
                ],
                tags=["buffer", "distance"],
            ),
            _Algorithm(
                "native:clip",
                "Clip",
                [
                    _ParameterDefinition("INPUT", "Input layer"),
                    _ParameterDefinition("OVERLAY", "Overlay layer"),
                    _ParameterDefinition("OUTPUT", "Clipped"),
                ],
                tags=["clip", "cut"],
            ),
            _Algorithm(
                "native:centroids",
                "Centroids",
                [
                    _ParameterDefinition("INPUT", "Input layer"),
                    _ParameterDefinition("OUTPUT", "Centroids"),
                ],
                tags=["centroid"],
            ),
        ]

    def algorithms(self):
        return list(self._algorithms)

    def algorithmById(self, algorithm_id):  # noqa: N802
        for algorithm in self._algorithms:
            if algorithm.id() == algorithm_id:
                return algorithm
        return None


class QgsApplication(object):
    _tasks = _TaskManager()
    _registry = _ProcessingRegistry()
    _auth = None

    @classmethod
    def taskManager(cls):  # noqa: N802
        return cls._tasks

    @classmethod
    def processingRegistry(cls):  # noqa: N802
        return cls._registry

    @classmethod
    def authManager(cls):  # noqa: N802
        return cls._auth

    @classmethod
    def qgisSettingsDirPath(cls):  # noqa: N802
        return "/tmp/qgis-profile/"


class QgsNetworkAccessManager(object):
    """Just enough to exercise the scoped timeout override."""

    _instance = None
    _timeout = 60000
    history = []

    @classmethod
    def instance(cls):
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    def timeout(self):
        return QgsNetworkAccessManager._timeout

    def setTimeout(self, ms):  # noqa: N802
        QgsNetworkAccessManager._timeout = int(ms)
        QgsNetworkAccessManager.history.append(int(ms))


class QgsSettings(object):
    _store = {}

    def value(self, key, default=None):
        return self._store.get(key, default)

    def setValue(self, key, value):  # noqa: N802
        self._store[key] = value


class QgsAuthMethodConfig(object):
    def __init__(self):
        self._config = {}
        self._id = ""

    def setName(self, value):  # noqa: N802
        pass

    def setMethod(self, value):  # noqa: N802
        pass

    def setUri(self, value):  # noqa: N802
        pass

    def setConfig(self, key, value):  # noqa: N802
        self._config[key] = value

    def config(self, key, default=""):
        return self._config.get(key, default)

    def isValid(self):  # noqa: N802
        return True

    def id(self):
        return self._id


class MockAuthManager(object):
    """Mimics the SIP_INOUT return shape of the real auth manager.

    Both ``storeAuthenticationConfig`` and ``loadAuthenticationConfig`` take the
    config by reference in C++, so PyQGIS hands back ``(bool, config)``.  Code
    that tests the raw return value for truthiness always sees success -- the
    bug this mock exists to catch.
    """

    def __init__(self, available=True, succeed=True):
        self._store = {}
        self._counter = 0
        self.available = available
        self.succeed = succeed

    def authenticationDatabasePath(self):  # noqa: N802
        return "/tmp/qgis-authdb.db" if self.available else ""

    def storeAuthenticationConfig(self, config, overwrite=False):  # noqa: N802
        if not self.succeed:
            return False, config
        self._counter += 1
        config._id = "cfg{0:04d}".format(self._counter)
        self._store[config._id] = dict(config._config)
        return True, config

    def loadAuthenticationConfig(self, authcfg_id, config, full=False):  # noqa: N802
        stored = self._store.get(authcfg_id)
        if stored is None:
            return False, config
        for key, value in stored.items():
            config.setConfig(key, value)
        return True, config

    def removeAuthenticationConfig(self, authcfg_id):  # noqa: N802
        return self._store.pop(authcfg_id, None) is not None


class QColor(object):
    _NAMED = {"darkgreen": "#006400", "red": "#ff0000", "blue": "#0000ff"}

    def __init__(self, *args):
        if len(args) == 1 and isinstance(args[0], str):
            value = args[0].lower()
            self._name = self._NAMED.get(value, value if value.startswith("#") else "")
        elif len(args) >= 3:
            self._name = "#{0:02x}{1:02x}{2:02x}".format(*args[:3])
        else:
            self._name = ""

    def isValid(self):  # noqa: N802
        return bool(self._name)

    def name(self):
        return self._name


class QgsSymbol(object):
    def __init__(self, geometry_type=0):
        self._colour = None
        self.geometry_type = geometry_type

    @staticmethod
    def defaultSymbol(geometry_type):  # noqa: N802
        # The real QGIS returns None for a geometryless layer.
        if geometry_type in (4, None):
            return None
        return QgsSymbol(geometry_type)

    def setColor(self, colour):  # noqa: N802
        self._colour = colour

    def color(self):
        return self._colour


class QgsSingleSymbolRenderer(object):
    def __init__(self, symbol):
        self._symbol = symbol

    def symbol(self):
        return self._symbol

    def setSymbol(self, symbol):  # noqa: N802
        self._symbol = symbol


class QgsRendererCategory(object):
    def __init__(self, value, symbol, label):
        self.value = value
        self.symbol = symbol
        self.label = label


class QgsCategorizedSymbolRenderer(object):
    def __init__(self, attr="", categories=None):
        self.attr = attr
        self.categories = list(categories or [])

    def addCategory(self, category):  # noqa: N802
        self.categories.append(category)


class QgsGradientColorRamp(object):
    def __init__(self, start=None, end=None):
        self.start = start
        self.end = end


class QgsStyle(object):
    _default = None

    @classmethod
    def defaultStyle(cls):  # noqa: N802
        if cls._default is None:
            cls._default = cls()
        return cls._default

    def colorRamp(self, name):  # noqa: N802
        # Mirrors a style database that has Spectral but not Viridis.
        return QgsGradientColorRamp() if name == "Spectral" else None


class QgsGraduatedSymbolRenderer(object):
    Quantile = 2

    def __init__(self, attr="", ranges=None):
        self.attr = attr

    @staticmethod
    def createRenderer(layer, attr, classes, mode, symbol, ramp, *rest):  # noqa: N802
        # ramp is positional and required in the real API: leaving it out is a
        # TypeError, which is exactly what this signature reproduces.
        if ramp is None:
            raise TypeError("createRenderer() requires a colour ramp")
        renderer = QgsGraduatedSymbolRenderer(attr)
        renderer.classes = classes
        renderer.ramp = ramp
        return renderer


class QgsDataSourceUri(object):
    def __init__(self):
        self._params = {}

    def setParam(self, key, value):  # noqa: N802
        self._params[key] = value

    def encodedUri(self):  # noqa: N802
        from urllib.parse import quote

        return "&".join(
            "{0}={1}".format(k, quote(str(v), safe="")) for k, v in self._params.items()
        ).encode("utf-8")


class Qgis(object):
    MessageLevel = _Enum(Info=0, Warning=1, Critical=2, Success=3)
    Info, Warning, Critical, Success = 0, 1, 2, 3
    # QGIS 4 moved the Processing parameter flags here from
    # QgsProcessingParameterDefinition.Flag.
    ProcessingParameterFlag = _Enum(Optional=1, Hidden=2, Advanced=4)


class QgsMessageLog(object):
    records = []

    @classmethod
    def logMessage(cls, message, tag="", level=0):  # noqa: N802
        cls.records.append((tag, message, level))


def _stub(name):
    return type(name, (object,), {"__init__": lambda self, *a, **k: None})


# ---------------------------------------------------------------------------


def install():
    """Insert the stub modules into ``sys.modules``."""
    qgis = types.ModuleType("qgis")
    pyqt = types.ModuleType("qgis.PyQt")

    qtcore = types.ModuleType("qgis.PyQt.QtCore")
    qtcore.Qt = Qt
    qtcore.QObject = QObject
    qtcore.pyqtSignal = pyqtSignal
    qtcore.QUrl = QUrl
    qtcore.QByteArray = QByteArray
    qtcore.QSize = _stub("QSize")
    qtcore.QDateTime = QDateTime

    qtgui = types.ModuleType("qgis.PyQt.QtGui")
    for name in ("QIcon", "QFont", "QKeySequence", "QTextCursor", "QPixmap"):
        setattr(qtgui, name, _stub(name))
    qtgui.QColor = QColor

    qtwidgets = types.ModuleType("qgis.PyQt.QtWidgets")
    for name in (
        "QAction", "QShortcut", "QCheckBox", "QComboBox", "QDialog",
        "QDialogButtonBox", "QDockWidget", "QFileDialog", "QFormLayout",
        "QGroupBox", "QHBoxLayout", "QLabel", "QLineEdit", "QMessageBox",
        "QPlainTextEdit", "QProgressBar", "QPushButton", "QSpinBox",
        "QTextBrowser", "QVBoxLayout", "QWidget", "QListWidget",
        "QListWidgetItem", "QTabWidget",
    ):
        setattr(qtwidgets, name, _stub(name))

    qtnetwork = types.ModuleType("qgis.PyQt.QtNetwork")
    qtnetwork.QNetworkRequest = QNetworkRequest

    core = types.ModuleType("qgis.core")
    for name, value in {
        "Qgis": Qgis,
        "QgsAbstractMetadataBase": QgsAbstractMetadataBase,
        "QgsApplication": QgsApplication,
        "QgsBox3D": QgsBox3D,
        "QgsDateTimeRange": QgsDateTimeRange,
        "QgsLayerMetadata": QgsLayerMetadata,
        "QgsAuthMethodConfig": QgsAuthMethodConfig,
        "QgsBlockingNetworkRequest": QgsBlockingNetworkRequest,
        "QgsCoordinateReferenceSystem": QgsCoordinateReferenceSystem,
        "QgsDataSourceUri": QgsDataSourceUri,
        "QgsMapLayer": QgsMapLayer,
        "QgsMessageLog": QgsMessageLog,
        "QgsNetworkAccessManager": QgsNetworkAccessManager,
        "QgsProject": QgsProject,
        "QgsRasterLayer": QgsRasterLayer,
        "QgsRectangle": QgsRectangle,
        "QgsSettings": QgsSettings,
        "QgsTask": QgsTask,
        "QgsVectorLayer": QgsVectorLayer,
        "QgsCategorizedSymbolRenderer": QgsCategorizedSymbolRenderer,
        "QgsGradientColorRamp": QgsGradientColorRamp,
        "QgsGraduatedSymbolRenderer": QgsGraduatedSymbolRenderer,
        "QgsRendererCategory": QgsRendererCategory,
        "QgsSingleSymbolRenderer": QgsSingleSymbolRenderer,
        "QgsStyle": QgsStyle,
        "QgsSymbol": QgsSymbol,
    }.items():
        setattr(core, name, value)
    for name in (
        "QgsCoordinateTransform", "QgsFeature", "QgsLayoutExporter",
        "QgsLayoutItemLabel", "QgsLayoutItemLegend", "QgsLayoutItemMap",
        "QgsLayoutItemScaleBar", "QgsLayoutPoint", "QgsLayoutSize",
        "QgsPrintLayout", "QgsUnitTypes", "QgsVectorFileWriter",
        "QgsTextFormat",
    ):
        setattr(core, name, _stub(name))

    gui = types.ModuleType("qgis.gui")
    processing_module = types.ModuleType("qgis.processing")

    def _run(algorithm_id, parameters, *args, **kwargs):
        return {"OUTPUT": QgsVectorLayer("memory", "{0} output".format(algorithm_id))}

    processing_module.run = _run
    processing_module.runAndLoadResults = _run
    qgis.processing = processing_module

    qgis.PyQt = pyqt
    qgis.core = core
    qgis.gui = gui
    pyqt.QtCore = qtcore
    pyqt.QtGui = qtgui
    pyqt.QtWidgets = qtwidgets
    pyqt.QtNetwork = qtnetwork

    sys.modules.update(
        {
            "qgis": qgis,
            "qgis.PyQt": pyqt,
            "qgis.PyQt.QtCore": qtcore,
            "qgis.PyQt.QtGui": qtgui,
            "qgis.PyQt.QtWidgets": qtwidgets,
            "qgis.PyQt.QtNetwork": qtnetwork,
            "qgis.core": core,
            "qgis.gui": gui,
            "qgis.processing": processing_module,
        }
    )
    return qgis
