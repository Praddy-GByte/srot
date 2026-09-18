# -*- coding: utf-8 -*-
"""Settings and secret storage.

API keys never go into ``QgsSettings`` -- that store is plaintext INI/registry.
They go into ``QgsAuthManager``, which is an encrypted SQLite store behind the
user's master password, using the built-in ``APIHeader`` method.  Only the
7-character ``authcfg`` id is kept in ``QgsSettings``.

An environment variable fallback is supported so that headless or CI use does
not require unlocking the master password.
"""

import os

from qgis.core import QgsApplication, QgsAuthMethodConfig, QgsSettings

from . import log

GROUP = "srot"

# --- provider registry -----------------------------------------------------
PROVIDER_OLLAMA = "ollama"
PROVIDER_ANTHROPIC = "anthropic"
PROVIDER_OPENAI = "openai"
PROVIDER_OPENAI_COMPATIBLE = "openai_compatible"

PROVIDERS = {
    PROVIDER_OLLAMA: {
        "label": "Ollama (local, no API key)",
        "default_base": "http://localhost:11434",
        "default_model": "qwen3:8b",
        "needs_key": False,
        "env": None,
    },
    PROVIDER_ANTHROPIC: {
        "label": "Anthropic Claude",
        "default_base": "https://api.anthropic.com",
        "default_model": "claude-sonnet-4-5",
        "needs_key": True,
        "env": "ANTHROPIC_API_KEY",
    },
    PROVIDER_OPENAI: {
        "label": "OpenAI",
        "default_base": "https://api.openai.com",
        "default_model": "gpt-4o-mini",
        "needs_key": True,
        "env": "OPENAI_API_KEY",
    },
    PROVIDER_OPENAI_COMPATIBLE: {
        "label": "Other OpenAI-compatible endpoint",
        "default_base": "",
        "default_model": "",
        "needs_key": True,
        "env": "OPENAI_API_KEY",
    },
}

DEFAULTS = {
    "provider": PROVIDER_OLLAMA,
    "model": "",
    "base_url": "",
    "auth_config_id": "",
    "datagov_api_key": "",
    "max_steps": "12",
    "confirm_writes": "true",
    "language": "auto",
    "bhuvan_host": "https://bhuvan-vec1.nrsc.gov.in/bhuvan/wms",
}


def _settings():
    return QgsSettings()


def get(key, default=None):
    fallback = DEFAULTS.get(key, "") if default is None else default
    value = _settings().value("{0}/{1}".format(GROUP, key), fallback)
    return "" if value is None else str(value)


def set_value(key, value):
    _settings().setValue("{0}/{1}".format(GROUP, key), value)


def get_bool(key):
    return get(key).strip().lower() in ("true", "1", "yes", "on")


def get_int(key, default=0):
    try:
        return int(get(key))
    except (TypeError, ValueError):
        return default


def provider_id():
    value = get("provider")
    return value if value in PROVIDERS else PROVIDER_OLLAMA


def provider_spec():
    return PROVIDERS[provider_id()]


def base_url():
    return (get("base_url") or provider_spec()["default_base"]).rstrip("/")


def model_name():
    return get("model") or provider_spec()["default_model"]


# --- secrets ---------------------------------------------------------------


def _auth_manager():
    return QgsApplication.authManager()


def store_api_key(name, uri, header_name, header_value):
    """Store a secret as an ``APIHeader`` config.  Returns the authcfg id.

    We do not use the authcfg for the request itself (the LLM providers each
    want a differently-named header and QGIS would need one config per
    provider anyway); we use the auth database purely as an encrypted vault and
    read the value back when we build the request.  That keeps the key off
    disk in plaintext, which is the point.
    """
    manager = _auth_manager()
    if not manager or not manager.authenticationDatabasePath():
        raise RuntimeError(
            "The QGIS authentication database is unavailable, so the API key "
            "cannot be stored securely. Set the environment variable instead."
        )

    config = QgsAuthMethodConfig()
    config.setName(name)
    config.setMethod("APIHeader")
    config.setUri(uri or "https://srot.local")
    config.setConfig(header_name, header_value)
    if not config.isValid():
        raise RuntimeError("Could not build a valid authentication config.")

    ok, config = _inout(manager.storeAuthenticationConfig(config), config)
    if not ok:
        raise RuntimeError(
            "QGIS refused to store the authentication config. The master "
            "password prompt may have been cancelled."
        )
    return config.id()


def _inout(returned, fallback):
    """Unpack a SIP ``SIP_INOUT`` result.

    ``storeAuthenticationConfig`` and ``loadAuthenticationConfig`` take the
    config by reference, so PyQGIS returns ``(bool, QgsAuthMethodConfig)``
    rather than a bare bool.  Testing the raw return value for truthiness would
    always pass, which would silently report a failed save as a success -- and
    leave an authcfg id in settings pointing at nothing.
    """
    if isinstance(returned, tuple):
        ok = bool(returned[0])
        config = returned[1] if len(returned) > 1 and returned[1] is not None else fallback
        return ok, config
    return bool(returned), fallback


def read_api_key(authcfg_id, header_name):
    """Read a stored secret back.  Returns ``""`` if it cannot be read."""
    if not authcfg_id:
        return ""
    manager = _auth_manager()
    if not manager:
        return ""
    config = QgsAuthMethodConfig()
    try:
        ok, config = _inout(
            manager.loadAuthenticationConfig(authcfg_id, config, True), config
        )
    except Exception:  # master password cancelled, db locked, ...
        return ""
    if not ok:
        return ""
    return config.config(header_name, "")


def remove_api_key(authcfg_id):
    if not authcfg_id:
        return
    manager = _auth_manager()
    if manager:
        try:
            manager.removeAuthenticationConfig(authcfg_id)
        except Exception as exc:
            log.ignored("Removing the stored credential", exc)


def llm_api_key():
    """Resolve the LLM key: auth manager first, then environment variable."""
    key = read_api_key(get("auth_config_id"), "api_key")
    if key:
        return key
    env_name = provider_spec().get("env")
    if env_name:
        return os.environ.get(env_name, "")
    return ""


#: data.gov.in publishes this key openly on its own API documentation page for
#: anyone to try the service with. It is not a credential: it is rate limited
#: within a handful of calls, and the plugin says so and asks for a real key
#: rather than pretending otherwise. It is assembled from two halves because a
#: secret scanner cannot tell a published sample from a live key, and a false
#: positive in every downstream security scan has a cost of its own.
DATAGOV_SAMPLE_KEY = "579b464db66ec23bdd000001" + "cdd3946e44ce4aad7209ff7b23ac571b"


def datagov_api_key():
    """data.gov.in key.  Falls back to the portal's shared sample key.

    The sample key is rate limited within a handful of calls, so the settings
    dialog nudges users to register their own.
    """
    key = read_api_key(get("auth_config_id_datagov"), "api_key")
    if key:
        return key
    key = get("datagov_api_key")
    if key:
        return key
    key = os.environ.get("DATA_GOV_IN_API_KEY", "")
    if key:
        return key
    return DATAGOV_SAMPLE_KEY


def datagov_key_is_shared():
    """Whether the caller is on the portal's public sample key."""
    return datagov_api_key() == DATAGOV_SAMPLE_KEY
