"""
tests/conftest.py

Session-level stubs that prevent heavy optional dependencies (Dash, Gradio,
Plotly) from being imported when tests only exercise isolated utility modules.

The webui package's __init__.py immediately imports webui.app_dash, which
pulls in Gradio, Dash, and Plotly.  Under certain environment configurations
(mismatched pydantic versions) this chain raises a KeyError before any test
code runs.  Since the utility modules under test (e.g. webui/utils/) do NOT
themselves depend on Gradio or Dash, we stub the top-level webui package in
sys.modules before pytest's collection phase imports anything from webui.
"""

import os
import sys
import types

# Absolute path to the repository root (one level up from this file).
_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_WEBUI_DIR = os.path.join(_REPO_ROOT, "webui")
_WEBUI_UTILS_DIR = os.path.join(_WEBUI_DIR, "utils")


def _stub_webui_package():
    """
    Insert lightweight stubs for webui and its heavy sub-packages so that
    `from webui.utils.market_hours import ...` works without triggering
    the Dash/Gradio import chain in webui/__init__.py.

    The webui and webui.utils stubs carry the real __path__ so Python's
    import machinery can still find real source files underneath them
    (e.g. webui/utils/market_hours.py).  Only the heavy app-level packages
    (app_dash, components, layout) get fully opaque stubs.
    """
    if "webui" in sys.modules and getattr(sys.modules["webui"], "_real_package", False):
        # Real webui already imported — nothing to do.
        return

    # Stub the `webui` package: real __path__ so sub-modules resolve on disk,
    # but NO __init__ code runs (avoids the Gradio/Dash cascade).
    webui_stub = types.ModuleType("webui")
    webui_stub.__path__ = [_WEBUI_DIR]
    webui_stub.__package__ = "webui"
    webui_stub.__spec__ = None
    sys.modules["webui"] = webui_stub

    # Stub `webui.utils` with its real __path__ so market_hours.py is found.
    utils_stub = types.ModuleType("webui.utils")
    utils_stub.__path__ = [_WEBUI_UTILS_DIR]
    utils_stub.__package__ = "webui.utils"
    utils_stub.__spec__ = None
    sys.modules["webui.utils"] = utils_stub
    webui_stub.utils = utils_stub

    # Fully opaque stubs for heavy sub-packages we never test directly.
    for sub in ("webui.app_dash", "webui.components", "webui.layout"):
        sub_stub = types.ModuleType(sub)
        sub_stub.__package__ = sub.rsplit(".", 1)[0]
        sys.modules[sub] = sub_stub


# Apply stubs immediately at import time so they are in place before pytest
# begins collecting test modules.
_stub_webui_package()
