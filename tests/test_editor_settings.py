"""The repository's editor and the installed RetLens share one QSettings store: the window layout is
kept per layout (dev/ keys from the repository), the Isaac EULA consent is shared."""

import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

QtCore = pytest.importorskip("PySide6.QtCore")


def test_layout_keys_are_per_layout(tmp_path, monkeypatch):
    from khumanoid.app import editor

    s = QtCore.QSettings(str(tmp_path / "retlens.ini"), QtCore.QSettings.IniFormat)  # never the user's registry
    s.setValue("window/state", b"shared-before")
    s.setValue("dialog/dir", "C:/motions")
    s.setValue("isaac/eula_accepted", True)

    monkeypatch.setattr(editor.app_paths, "INSTALLED", False)
    editor.split_layout_settings(s)  # the repository's editor starts from what both used so far
    assert editor.layout_key("window/state") == "dev/window/state"
    assert s.value("dev/window/state") == b"shared-before" and s.value("dev/dialog/dir") == "C:/motions"
    assert not s.contains("dev/setup/checked")  # nothing to copy for keys neither program wrote yet
    s.setValue(editor.layout_key("window/state"), b"dev-layout")
    s.setValue("setup/checked", True)  # the installed program's first-run check, after the split
    editor.split_layout_settings(s)  # once only: nothing more is copied over later
    assert s.value("dev/window/state") == b"dev-layout" and not s.contains("dev/setup/checked")

    monkeypatch.setattr(editor.app_paths, "INSTALLED", True)
    assert editor.layout_key("window/state") == "window/state"
    assert s.value(editor.layout_key("window/state")) == b"shared-before"  # the installed layout is untouched
    assert "isaac/eula_accepted" not in editor.LAYOUT_KEYS  # consent stays shared
