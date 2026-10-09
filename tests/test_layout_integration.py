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

"""Exercise the extension with real Terminator in a private D-Bus and Xvfb session."""

from __future__ import annotations

import json
import os
import shlex
import shutil
import signal
import subprocess
import time
from contextlib import suppress
from pathlib import Path
from typing import TYPE_CHECKING, Any

import dbus
import pytest
from dbus.bus import BusConnection

from terminator_dbus import Terminator

if TYPE_CHECKING:
    from collections.abc import Iterator

pytestmark = pytest.mark.skipif(
    os.environ.get("TERMINATOR_DBUS_INTEGRATION") != "1",
    reason="Set TERMINATOR_DBUS_INTEGRATION=1 to run the real Terminator tests",
)

_INSPECTOR = """
import json
import dbus.service
from terminatorlib.plugin import Plugin
from terminatorlib.terminator import Terminator

AVAILABLE = ["LayoutInspector"]

class Service(dbus.service.Object):
    def __init__(self):
        super().__init__(dbus.SessionBus(), "/layout_test")

    @dbus.service.method("layout.test", in_signature="", out_signature="s")
    def snapshot(self):
        manager = Terminator()
        return json.dumps({
            "terminals": {terminal.uuid.urn: {"pid": terminal.pid, "cwd": terminal.get_cwd()} for terminal in manager.terminals},
            "windows": {window.uuid.urn: bool(window.is_zoomed()) for window in manager.windows},
        })

    @dbus.service.method("layout.test", in_signature="s", out_signature="")
    def zoom(self, uuid):
        terminal = Terminator().find_terminal_by_uuid(uuid)
        terminal.get_toplevel().zoom(terminal)

class LayoutInspector(Plugin):
    capabilities = []
    def __init__(self):
        self.service = Service()
    def unload(self):
        self.service.remove_from_connection()
"""


def _wait(callback: Any) -> Any:
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        try:
            result = callback()
            if result:
                return result
        except dbus.DBusException:
            pass
        time.sleep(0.05)
    raise AssertionError("Terminator did not become ready")


@pytest.fixture(scope="module")
def session(tmp_path_factory: pytest.TempPathFactory) -> Iterator[Any]:
    """Keep the user's desktop, configuration, and running terminals untouched."""
    executables = {}
    for executable in ("dbus-daemon", "Xvfb", "terminator"):
        path = shutil.which(executable)
        if path is None:
            pytest.skip(f"{executable} is not installed")
        executables[executable] = path

    root = tmp_path_factory.mktemp("terminator-layout")
    configuration = root / "terminator"
    plugins = configuration / "plugins"
    plugins.mkdir(parents=True)
    resource = Path(__file__).parent.parent / "src/terminator_dbus/plugin/terminator_dbus_extension.py"
    (plugins / resource.name).symlink_to(resource)
    (plugins / "layout_inspector.py").write_text(_INSPECTOR)
    config = configuration / "config"
    config.write_text(
        "[global_config]\n  enabled_plugins = TerminatorDBusExtension, LayoutInspector\n  always_split_with_profile = True\n[profiles]\n  [[default]]\n    scrollback_lines = 100\n[keybindings]\n[layouts]\n[plugins]\n",
    )

    bus_process = subprocess.Popen(  # noqa: S603
        [executables["dbus-daemon"], "--session", "--nofork", "--print-address=1"],
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        text=True,
    )
    display = None
    terminal_process = None
    inspector = None
    try:
        assert bus_process.stdout is not None
        address = bus_process.stdout.readline().strip()
        assert address
        display = subprocess.Popen(  # noqa: S603
            [executables["Xvfb"], "-displayfd", "1", "-screen", "0", "1024x768x24", "-nolisten", "tcp"],
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
        )
        assert display.stdout is not None
        display_number = display.stdout.readline().strip()
        assert display_number
        environment = dict(
            os.environ,
            DBUS_SESSION_BUS_ADDRESS=address,
            DISPLAY=f":{display_number}",
            XDG_CONFIG_HOME=str(root),
            ZDOTDIR=str(root),
        )
        environment.pop("TERMINATOR_DBUS_NAME", None)
        environment.pop("TERMINATOR_UUID", None)
        environment.pop("WAYLAND_DISPLAY", None)
        connection = BusConnection(address)
        with (root / "terminator.log").open("w") as log:
            terminal_process = subprocess.Popen(  # noqa: S603
                [executables["terminator"], "--config", str(config)],
                env=environment,
                stdout=log,
                stderr=log,
            )
            client = _wait(lambda: Terminator(bus=connection, display=environment["DISPLAY"]))
            _wait(client.get_terminals)
            inspector = client.get_interface("layout.test", object_path="/layout_test", introspect=False)
            _wait(lambda: json.loads(str(inspector.snapshot(signature="")))["terminals"])
            yield client, inspector, root
    finally:
        if inspector is not None:
            try:
                for terminal in json.loads(str(inspector.snapshot(signature="")))["terminals"].values():
                    with suppress(ProcessLookupError):
                        os.kill(terminal["pid"], signal.SIGHUP)
            except dbus.DBusException:
                pass
        for process in (terminal_process, display, bus_process):
            if process is not None:
                process.terminate()
                process.wait(timeout=10)


def _snapshot(inspector: Any) -> dict[str, Any]:
    return json.loads(str(inspector.snapshot(signature="")))


def _three_terminals(client: Terminator) -> tuple[str, str, str]:
    source = client.new_window()
    right = client.extension.split(source, "right")
    below = client.extension.split(right, "below")
    return source, right, below


def test_layout_queries_and_focus(session: Any) -> None:
    """Distinguish a sibling subtree from several neighbors, and select hidden tabs."""
    client, inspector, _ = session
    source, right, below = _three_terminals(client)
    extension = client.extension
    tree = extension.get_tree(source)
    right_branch = tree.get_sibling(source)
    assert right_branch is not None
    branch_id = right_branch["id"]
    tab_id = tree.get_node(source)["tab"]

    assert right_branch["type"] == "split"
    assert right_branch["axis"] == "y"
    assert [node["id"] for node in tree.get_neighbors(source, "right")] == [right, below]
    assert [node["id"] for node in extension.get_neighbors(source, "right")] == [right, below]
    assert tree.get_neighbors(source, "left") == []
    assert tree.get_parent(tree.root) is None
    assert tree.get_children(source) == []
    assert tree.get_parent(source)["id"] == extension.get_parent(source)["id"]
    assert [node["id"] for node in tree.get_ancestors(below)] == [node["id"] for node in extension.get_ancestors(below)]
    assert tree.get_sibling(source)["id"] == extension.get_sibling(source)["id"]
    assert [node["id"] for node in tree.get_children(branch_id)] == [
        node["id"] for node in extension.get_children(branch_id)
    ]
    assert tree.get_node(right)["direction"] == "above"
    assert tree.get_node(below)["direction"] == "below"

    other_tab = extension.new_tab(source)
    client.set_tab_title(other_tab, {"tab-title": "Second tab"})
    updated = extension.get_tree(source)

    assert updated.get_node(source)["tab"] == tab_id
    assert updated.get_node(branch_id)["axis"] == "y"
    assert len(updated.get_children(updated.root)) == 2
    assert updated.get_parent(other_tab)["title"] == "Second tab"
    assert [node["id"] for node in updated.get_neighbors(source, "right")] == [right, below]
    assert len(tree.get_children(tree.root)) == 1

    extension.focus(source)
    focused = _wait(lambda: extension.get_tree(source).focused_uuid == source)
    assert focused
    assert extension.get_tree(source).get_node(tab_id)["active"]
    assert len(_snapshot(inspector)["terminals"]) >= 4


def test_resize_swap_and_rotate_subtree(session: Any) -> None:
    """Keep terminal processes and split IDs through resizing, swapping, and rotation."""
    client, inspector, _ = session
    source, right, below = _three_terminals(client)
    extension = client.extension
    tree = extension.get_tree(source)
    branch = tree.get_sibling(source)["id"]
    root_split = tree.get_parent(source)["id"]
    pids = _snapshot(inspector)["terminals"]

    extension.set_split_ratio(branch, 0.3)
    assert extension.get_node(branch)["ratio"] == pytest.approx(0.3, abs=0.01)
    extension.swap_children(branch)
    assert [node["id"] for node in extension.get_children(branch)] == [below, right]
    assert extension.get_node(branch)["ratio"] == pytest.approx(0.3, abs=0.01)

    extension.rotate_subtree(root_split)
    rotated = extension.get_tree(source)
    assert rotated.get_node(root_split)["axis"] == "y"
    assert rotated.get_node(branch)["axis"] == "x"
    assert [node["id"] for node in rotated.get_children(branch)] == [right, below]
    assert rotated.get_node(branch)["ratio"] == pytest.approx(0.7, abs=0.01)

    extension.rotate_subtree(root_split, "counterclockwise")
    restored = extension.get_tree(source)
    assert restored.get_node(root_split)["axis"] == "x"
    assert restored.get_node(branch)["axis"] == "y"
    assert [node["id"] for node in restored.get_children(branch)] == [below, right]
    assert {uuid: _snapshot(inspector)["terminals"][uuid]["pid"] for uuid in (source, right, below)} == {
        uuid: pids[uuid]["pid"] for uuid in (source, right, below)
    }


@pytest.mark.parametrize("direction", ["right", "left", "above", "below"])
def test_split_entire_subtree(session: Any, direction: str) -> None:
    """Wrap a whole subtree while honoring the new shell's cwd and command."""
    client, inspector, root = session
    source, right, below = _three_terminals(client)
    extension = client.extension
    old_root = extension.get_parent(source)["id"]
    directory = root / "directory with spaces"
    directory.mkdir(exist_ok=True)
    result_file = root / f"command-result-{direction}"
    literal = "literal ' \" $HOME ; $(example)"
    code = "import sys,time; from pathlib import Path; Path(sys.argv[1]).write_text(sys.argv[2]); time.sleep(60)"
    command = shlex.join(["/usr/bin/python", "-c", code, str(result_file), literal])

    created = extension.split_node(old_root, direction, {"directory": str(directory), "command": command})

    tree = extension.get_tree(source)
    new_root = tree.get_parent(old_root)
    assert new_root["axis"] == ("y" if direction in {"above", "below"} else "x")
    expected = [old_root, created] if direction in {"right", "below"} else [created, old_root]
    assert [node["id"] for node in tree.get_children(new_root["id"])] == expected
    assert {node["uuid"] for node in tree.nodes.values() if node["type"] == "terminal"} == {
        source,
        right,
        below,
        created,
    }
    _wait(result_file.exists)
    assert result_file.read_text() == literal
    pid = _snapshot(inspector)["terminals"][created]["pid"]
    assert Path(f"/proc/{pid}/cwd").resolve() == directory


def test_move_nodes_between_splits_tabs_and_windows(session: Any) -> None:
    """Move live terminals and subtrees, collapsing empty source containers."""
    client, inspector, _ = session
    source, right, below = _three_terminals(client)
    extension = client.extension
    pids = _snapshot(inspector)["terminals"]
    old_branch = extension.get_sibling(source)["id"]
    tab = extension.get_tree(source).get_node(source)["tab"]

    moved_branch = extension.move_node(below, source, "left")
    tree = extension.get_tree(source)
    assert [node["id"] for node in tree.get_children(moved_branch)] == [below, source]
    assert old_branch not in tree.nodes
    assert tree.get_node(source)["tab"] == tab

    other_tab = extension.new_tab(source)
    extension.focus(source)
    client.set_tab_title(source, {"tab-title": "Original tab"})
    extension.focus(other_tab)
    client.set_tab_title(other_tab, {"tab-title": "Destination"})
    extension.move_node(moved_branch, other_tab, "below")
    tree = extension.get_tree(other_tab)
    assert tree.get_node(source)["tab"] == tree.get_node(other_tab)["tab"]
    assert tree.get_parent(right)["title"] == "Original tab"
    assert tree.get_node(tree.get_node(other_tab)["tab"])["title"] == "Destination"

    # Moving the final terminal out of its tab removes that empty tab.
    extension.move_node(right, other_tab, "right")
    tree = extension.get_tree(other_tab)
    assert len(tree.get_children(tree.root)) == 1
    assert tree.get_node(tree.get_node(other_tab)["tab"])["title"] == "Destination"

    destination_window = client.new_window()
    extension.move_node(moved_branch, destination_window, "left")
    destination = extension.get_tree(destination_window)
    assert moved_branch in destination.nodes
    assert source in destination.nodes
    assert below in destination.nodes

    # Moving an entire remaining tab into another window closes the empty window.
    remaining_tree = extension.get_tree(other_tab)
    empty_window = remaining_tree.root
    remaining_root = remaining_tree.get_parent(other_tab)["id"]
    extension.move_node(remaining_root, destination_window, "below")
    assert empty_window not in _snapshot(inspector)["windows"]
    assert {uuid: _snapshot(inspector)["terminals"][uuid]["pid"] for uuid in (source, right, below)} == {
        uuid: pids[uuid]["pid"] for uuid in (source, right, below)
    }


def test_queries_preserve_zoom_and_mutations_restore_layout(session: Any) -> None:
    """Read the logical tree without unzooming or moving focus."""
    client, inspector, _ = session
    source, right, below = _three_terminals(client)
    extension = client.extension
    original = extension.get_tree(source)
    branch = original.get_sibling(source)["id"]

    extension.focus(right)
    _wait(lambda: extension.get_tree(source).focused_uuid == right)
    inspector.zoom(right, signature="s")
    _wait(lambda: extension.get_tree(source).focused_uuid == right)
    zoomed = extension.get_tree(source)

    assert _snapshot(inspector)["windows"][original.root]
    assert set(zoomed.nodes) == set(original.nodes)
    assert zoomed.focused_uuid == right
    assert [node["id"] for node in extension.get_neighbors(source, "right")] == [right, below]
    assert _snapshot(inspector)["windows"][original.root]

    extension.swap_children(branch)
    assert not _snapshot(inspector)["windows"][original.root]
    assert [node["id"] for node in extension.get_children(branch)] == [below, right]

    # A zoomed tab containing one terminal is detached from its notebook.
    detached_tab = extension.new_tab(source)
    inspector.zoom(detached_tab, signature="s")
    snapshot = extension.get_tree(source)
    assert detached_tab in snapshot.nodes
    assert snapshot.get_parent(detached_tab)["active"]
    assert _snapshot(inspector)["windows"][original.root]
    extension.focus(source)
    assert not _snapshot(inspector)["windows"][original.root]


def test_invalid_mutations_leave_layout_unchanged(session: Any) -> None:
    """Validate IDs, node types, directions, ratios, and move cycles before editing."""
    client, inspector, _ = session
    source, right, below = _three_terminals(client)
    extension = client.extension
    tree = extension.get_tree(source)
    branch = tree.get_sibling(source)["id"]
    before = _snapshot(inspector)
    invalid_actions = [
        lambda: extension.get_node("missing"),
        lambda: extension.get_neighbors(branch, "right"),
        lambda: extension.get_neighbors(source, "diagonal"),
        lambda: extension.set_split_ratio(source, 0.5),
        lambda: extension.swap_children(source),
        lambda: extension.split_node(branch, "right", {"directory": "/this-directory-does-not-exist"}),
        lambda: extension.split_node(tree.root, "right"),
        lambda: extension.rotate_subtree(branch, "invalid"),
        lambda: extension.rotate_subtree(source),
        lambda: extension.move_node(branch, below, "right"),
        lambda: extension.move_node(source, source, "right"),
        lambda: extension.move_node(source, right, "invalid"),
        lambda: extension.focus(branch),
    ]
    invalid_actions.extend(
        lambda ratio=ratio: extension.set_split_ratio(branch, ratio)
        for ratio in (0, 1, -0.1, float("nan"), float("inf"))
    )

    for action in invalid_actions:
        with pytest.raises(dbus.DBusException):
            action()

    assert _snapshot(inspector) == before
    current = extension.get_tree(source)
    assert set(current.nodes) == set(tree.nodes)
    for node_id, node in tree.nodes.items():
        for field in ("parent", "children", "type", "axis", "direction"):
            assert current.nodes[node_id].get(field) == node.get(field)
        if node["type"] == "split":
            assert current.nodes[node_id]["ratio"] == pytest.approx(node["ratio"], abs=0.01)


@pytest.mark.parametrize("direction", ["right", "left", "above", "below"])
def test_move_sibling_and_beside_ancestor(session: Any, direction: str) -> None:
    """Move between sibling slots and pull a terminal out beside its ancestor."""
    client, inspector, _ = session
    source = client.new_window()
    target = client.extension.split(source, "right")
    pids = _snapshot(inspector)["terminals"]

    enclosing = client.extension.move_node(source, target, direction)
    tree = client.extension.get_tree(source)
    expected = [target, source] if direction in {"right", "below"} else [source, target]
    assert [node["id"] for node in tree.get_children(enclosing)] == expected
    assert tree.get_node(enclosing)["axis"] == ("y" if direction in {"above", "below"} else "x")

    # The target ancestor becomes the remaining branch after the source is detached.
    client.extension.move_node(source, enclosing, direction)
    updated = client.extension.get_tree(source)
    assert {node["uuid"] for node in updated.nodes.values() if node["type"] == "terminal"} == {source, target}
    assert _snapshot(inspector)["terminals"][source]["pid"] == pids[source]["pid"]
    assert _snapshot(inspector)["terminals"][target]["pid"] == pids[target]["pid"]


def test_tab_ids_survive_moving_into_earlier_tab(session: Any) -> None:
    """Keep both tab identities when the moved subtree dominates the earlier tab."""
    client, _, _ = session
    earlier = client.new_window()
    extension = client.extension
    later = extension.new_tab(earlier)
    upper = extension.split(later, "right")
    lower = extension.split(upper, "below")
    before = extension.get_tree(earlier)
    earlier_tab = before.get_node(earlier)["tab"]
    later_tab = before.get_node(later)["tab"]
    branch = before.get_sibling(later)["id"]

    extension.move_node(branch, earlier, "right")
    after = extension.get_tree(earlier)

    assert after.get_node(earlier)["tab"] == earlier_tab
    assert after.get_node(upper)["tab"] == earlier_tab
    assert after.get_node(lower)["tab"] == earlier_tab
    assert after.get_node(later)["tab"] == later_tab
