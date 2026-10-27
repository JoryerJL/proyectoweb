"""Helpers to read configuration from environment variables."""

import os

from django.core.exceptions import ImproperlyConfigured

# Fallback used only for local development. Production must override it.
INSECURE_SECRET_KEY = 'django-insecure-4bm14dim+pt9*yg3ugyi^fyjk#7858z8riq+%de00+3i_0$7rk'

_TRUE_VALUES = {'1', 'true', 'yes', 'on'}


def env_bool(name, default=False):
    """Return an env var as a boolean; unset falls back to ``default``."""
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() in _TRUE_VALUES


def env_list(name, default=None):
    """Return a comma-separated env var as a list; unset or empty falls back to ``default``."""
    items = [item.strip() for item in os.environ.get(name, '').split(',') if item.strip()]
    if items:
        return items
    return list(default) if default else []


def validate_production(debug, secret_key):
    """Refuse to run with DEBUG off and a missing or publicly known secret key."""
    if not debug and (not secret_key or secret_key == INSECURE_SECRET_KEY):
        raise ImproperlyConfigured(
            'DJANGO_SECRET_KEY must be set to a unique secret value when DJANGO_DEBUG is off.'
        )
