# SPDX-License-Identifier: ISC
#
# ISC License
#
# Copyright (c) 2026, Timothée Mazzucotelli and contributors
#
# Permission to use, copy, modify, and/or distribute this software for any
# purpose with or without fee is hereby granted, provided that the above
# copyright notice and this permission notice appear in all copies.
#
# THE SOFTWARE IS PROVIDED "AS IS" AND THE AUTHOR DISCLAIMS ALL WARRANTIES
# WITH REGARD TO THIS SOFTWARE INCLUDING ALL IMPLIED WARRANTIES OF
# MERCHANTABILITY AND FITNESS. IN NO EVENT SHALL THE AUTHOR BE LIABLE FOR
# ANY SPECIAL, DIRECT, INDIRECT, OR CONSEQUENTIAL DAMAGES OR ANY DAMAGES
# WHATSOEVER RESULTING FROM LOSS OF USE, DATA OR PROFITS, WHETHER IN AN
# ACTION OF CONTRACT, NEGLIGENCE OR OTHER TORTIOUS ACTION, ARISING OUT OF
# OR IN CONNECTION WITH THE USE OR PERFORMANCE OF THIS SOFTWARE.

"""Tests for installing and using the bundled terminal extension."""

from __future__ import annotations

import importlib.util
import sys
from types import ModuleType, SimpleNamespace
from typing import TYPE_CHECKING, Any
from unittest.mock import Mock

import dbus.service
import pytest

from terminator_dbus import EXTENSION_INTERFACE, EXTENSION_PATH, install_plugin, main

if TYPE_CHECKING:
    from pathlib import Path


def test_install_plugin(tmp_path: Path) -> None:
    """Install a standalone plugin and update an existing installation."""
    destination = install_plugin(tmp_path / "plugins")
    source = destination.read_text()

    assert f'_INTERFACE = "{EXTENSION_INTERFACE}"' in source
    assert f'_PATH = "{EXTENSION_PATH}"' in source
    assert 'AVAILABLE = ["TerminatorDBusExtension"]' in source
    assert "import terminator_dbus" not in source

    destination.write_text("old plugin")
    assert install_plugin(destination.parent).read_text() == source


@pytest.mark.parametrize("configuration", ["custom", ""])
def test_default_plugin_directory(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, configuration: str) -> None:
    """Use XDG_CONFIG_HOME when set, and the home configuration otherwise."""
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / configuration) if configuration else "")

    destination = install_plugin()

    expected = tmp_path / (configuration or ".config") / "terminator" / "plugins"
    assert destination.parent == expected


def test_install_plugin_cli(tmp_path: Path, capsys: pytest.CaptureFixture) -> None:
    """The command installs the plugin and explains how to enable it."""
    result = main(["install-plugin", "--directory", str(tmp_path)])

    assert result == 0
    assert (tmp_path / "terminator_dbus_extension.py").is_file()
    assert "Enable TerminatorDBusExtension" in capsys.readouterr().out


def test_install_plugin_cli_error(tmp_path: Path, capsys: pytest.CaptureFixture) -> None:
    """Report a filesystem failure through stderr and the exit status."""
    blocked_directory = tmp_path / "file"
    blocked_directory.touch()

    result = main(["install-plugin", "--directory", str(blocked_directory)])

    assert result == 1
    assert "Could not install Terminator plugin" in capsys.readouterr().err


class _Widget:
    def __init__(self, *children: _Widget) -> None:
        self.children = list(children)
        self.parent: _Widget | None = None
        for child in children:
            child.parent = self

    def get_parent(self) -> _Widget | None:
        return self.parent

    def get_children(self) -> list[_Widget]:
        return self.children


class _Terminal(_Widget):
    def __init__(self, uuid: str) -> None:
        super().__init__()
        self.uuid = SimpleNamespace(urn=uuid)


@pytest.fixture
def extension(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Any:
    """Load the installed plugin with a small GTK substitute and no session bus."""
    modules = {
        "gi.repository": {
            "Gtk": SimpleNamespace(Notebook=type("Notebook", (_Widget,), {}), Window=type("Window", (_Widget,), {})),
        },
        "terminatorlib.factory": {"Factory": Mock()},
        "terminatorlib.paned": {"HPaned": type("HPaned", (_Widget,), {}), "VPaned": type("VPaned", (_Widget,), {})},
        "terminatorlib.plugin": {"Plugin": object},
        "terminatorlib.terminal": {"Terminal": _Terminal},
        "terminatorlib.terminator": {"Terminator": Mock()},
    }
    for name, attributes in modules.items():
        module = ModuleType(name)
        vars(module).update(attributes)
        monkeypatch.setitem(sys.modules, name, module)

    monkeypatch.setattr(dbus.service, "Object", object)
    monkeypatch.setattr(dbus.service, "method", lambda *args, **kwargs: lambda function: function)

    path = install_plugin(tmp_path)
    spec = importlib.util.spec_from_file_location("test_terminal_extension", path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def launch(extension: Any, tmp_path: Path) -> Any:
    """Provide a source terminal and record the settings seen by its new sibling."""
    original = SimpleNamespace(command="saved command", execute=["saved"], working_directory="saved directory")
    config = Mock()
    config.options_get.return_value = original
    config.__getitem__ = Mock(return_value=True)
    source = Mock(uuid=SimpleNamespace(urn="source"))
    source.get_cwd.return_value = str(tmp_path)
    source.get_profile.return_value = "work"
    source.get_toplevel.return_value.is_zoomed.return_value = False
    sibling = Mock(uuid=SimpleNamespace(urn="created"))
    seen = []
    sibling.spawn_child.side_effect = lambda: seen.append(vars(original).copy())
    extension.Factory.return_value.make.return_value = sibling
    service = extension._ExtensionService.__new__(extension._ExtensionService)
    service.terminator = SimpleNamespace(
        config=config,
        windows=[source.get_toplevel.return_value],
        terminals=[source],
        find_terminal_by_uuid=Mock(return_value=source),
    )
    return SimpleNamespace(service=service, source=source, sibling=sibling, original=original, config=config, seen=seen)


@pytest.mark.parametrize("direction", ["right", "left", "above", "below"])
def test_split_direction_and_launch_options(launch: Any, tmp_path: Path, direction: str) -> None:
    """Place the new terminal on the requested side with the supplied launch settings."""
    directory = tmp_path / "directory with spaces"
    directory.mkdir()
    command = "printf '%s' '$HOME'; sleep 20"

    result = launch.service.split("source", direction, {"directory": str(directory), "command": command})

    assert result == "created"
    assert launch.seen == [{"command": command, "execute": None, "working_directory": str(directory)}]
    launch.sibling.set_cwd.assert_called_once_with(str(directory))
    launch.sibling.force_set_profile.assert_called_once_with(None, "work")
    launch.source.get_parent.return_value.split_axis.assert_called_once_with(
        launch.source,
        vertical=direction in {"above", "below"},
        cwd=str(directory),
        sibling=launch.sibling,
        widgetfirst=direction in {"right", "below"},
    )
    assert vars(launch.original) == {
        "command": "saved command",
        "execute": ["saved"],
        "working_directory": "saved directory",
    }


def test_split_inherits_directory_and_default_shell(launch: Any, tmp_path: Path) -> None:
    """Omitted options inherit the source directory and allow Terminator's shell defaults."""
    launch.config.__getitem__.return_value = False

    launch.service.split("source", "below", {})

    launch.sibling.set_cwd.assert_called_once_with(str(tmp_path))
    launch.sibling.force_set_profile.assert_not_called()
    assert launch.seen == [{"command": None, "execute": None, "working_directory": None}]


def test_tab_targets_source_window_and_restores_options(launch: Any, tmp_path: Path) -> None:
    """Open the tab in the source window and restore options consumed during creation."""
    seen = []

    def create_tab(source: Any) -> None:
        assert source is launch.source
        seen.append(vars(launch.original).copy())
        launch.original.command = None
        launch.original.working_directory = ""
        launch.service.terminator.terminals.append(launch.sibling)

    launch.source.get_toplevel.return_value.tab_new.side_effect = create_tab

    result = launch.service.new_tab("source", {"directory": str(tmp_path), "command": "my-command"})

    assert result == "created"
    assert seen == [{"command": "my-command", "execute": None, "working_directory": str(tmp_path)}]
    assert vars(launch.original) == {
        "command": "saved command",
        "execute": ["saved"],
        "working_directory": "saved directory",
    }


def test_tab_defaults(launch: Any) -> None:
    """Clear stale command-line options when opening a default shell tab."""
    launch.source.get_toplevel.return_value.tab_new.side_effect = lambda source: (
        launch.service.terminator.terminals.append(launch.sibling)
    )

    launch.service.new_tab("source", {})

    launch.source.get_toplevel.return_value.tab_new.assert_called_once_with(launch.source)
    assert vars(launch.original) == {
        "command": "saved command",
        "execute": ["saved"],
        "working_directory": "saved directory",
    }


def test_restore_options_after_spawn_failure(launch: Any) -> None:
    """Restore shared options even when a child cannot be created."""
    launch.sibling.spawn_child.side_effect = RuntimeError("spawn failed")

    with pytest.raises(RuntimeError, match="spawn failed"):
        launch.service.split("source", "right", {"command": "temporary"})

    assert vars(launch.original) == {
        "command": "saved command",
        "execute": ["saved"],
        "working_directory": "saved directory",
    }


@pytest.mark.parametrize("method", ["new_tab", "split"])
@pytest.mark.parametrize("options", [{"directory": "/this-directory-does-not-exist"}, {"unsupported": "value"}])
def test_invalid_options_do_not_create_terminals(launch: Any, method: str, options: dict[str, str]) -> None:
    """Reject invalid launch options before changing the layout or creating widgets."""
    arguments = ["source", "right", options] if method == "split" else ["source", options]

    with pytest.raises(ValueError, match=r"Working directory does not exist|Unknown launch options"):
        getattr(launch.service, method)(*arguments)

    launch.sibling.spawn_child.assert_not_called()
    launch.source.get_toplevel.assert_not_called()


def test_missing_source(launch: Any) -> None:
    """A closed source terminal produces a clear error."""
    launch.service.terminator.find_terminal_by_uuid.return_value = None

    with pytest.raises(ValueError, match="Terminator terminal does not exist"):
        launch.service.new_tab("closed", {})


def test_invalid_direction(launch: Any) -> None:
    """Reject an unknown direction before creating a terminal."""
    with pytest.raises(ValueError, match="Unknown split direction"):
        launch.service.split("source", "diagonal", {})

    launch.sibling.spawn_child.assert_not_called()


@pytest.mark.parametrize("side", [0, 1])
def test_snapshot_collapses_single_child_pane(extension: Any, side: int) -> None:
    """An incomplete split is represented by its surviving terminal without GUI changes."""
    source: Any = _Terminal("source")
    source.get_cwd = Mock(return_value="/repository")
    source.get_profile = Mock(return_value="default")
    source.vte = Mock()
    source.vte.has_focus.return_value = False
    pane = extension.HPaned()
    pane.ratio = 0.5
    pane.children = [source, None] if side == 0 else [None, source]
    source.parent = pane
    window = extension.Gtk.Window(pane)
    window.uuid = SimpleNamespace(urn="window")
    window.get_child = Mock(return_value=pane)
    window.is_zoomed = Mock(return_value=False)
    window.get_title = Mock(return_value="Test")
    service = extension._ExtensionService.__new__(extension._ExtensionService)

    tree, _ = service._layout(window)

    node = tree["nodes"]["source"]
    assert node["rect"] == [0.0, 0.0, 1.0, 1.0]
    assert tree["nodes"][node["parent"]]["type"] == "tab"
    assert not any(node["type"] == "split" for node in tree["nodes"].values())
    assert source.get_parent() is pane
    assert pane.get_children()[side] is source
