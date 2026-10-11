"""Compatibility module for the official worker source owner."""

from importlib import import_module
import sys

from miy_worker.runtime import ensure_official_worker_src_on_path

ensure_official_worker_src_on_path()
_owner = import_module("miy_official_worker.tasks.mail")
sys.modules[__name__] = _owner
