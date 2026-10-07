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

"""Extend Terminator's D-Bus interface with targeted tabs and splits."""

from __future__ import annotations

import json
import math
from contextlib import contextmanager
from pathlib import Path
from typing import TYPE_CHECKING, Any, ClassVar
from uuid import uuid4

import dbus.service
from gi.repository import Gtk  # ty: ignore[unresolved-import]
from terminatorlib.factory import Factory  # ty: ignore[unresolved-import]
from terminatorlib.paned import HPaned, VPaned  # ty: ignore[unresolved-import]
from terminatorlib.plugin import Plugin  # ty: ignore[unresolved-import]
from terminatorlib.terminal import Terminal  # ty: ignore[unresolved-import]
from terminatorlib.terminator import Terminator  # ty: ignore[unresolved-import]

if TYPE_CHECKING:
    from collections.abc import Iterator, Mapping

AVAILABLE = ["TerminatorDBusExtension"]
_INTERFACE = "net.tenshu.Terminator2.Extension"
_PATH = "/net/tenshu/Terminator2/Extension"


_EPSILON = 1e-9


class _ExtensionService(dbus.service.Object):
    """Expose terminal creation on Terminator's existing session-bus connection."""

    def __init__(self) -> None:
        """Register the extension without claiming another bus name."""
        super().__init__(dbus.SessionBus(), _PATH)
        self.terminator = Terminator()

    def _source(self, uuid: str) -> Any:
        source = self.terminator.find_terminal_by_uuid(uuid)
        if source is None:
            raise ValueError(f"Terminator terminal does not exist: {uuid}")
        return source

    @staticmethod
    def _options(options: Mapping[str, str]) -> dict[str, str]:
        unknown = options.keys() - {"command", "directory"}
        if unknown:
            raise ValueError(f"Unknown launch options: {', '.join(sorted(unknown))}")
        result = dict(options)
        if "directory" in result:
            directory = Path(result["directory"]).expanduser().resolve()
            if not directory.is_dir():
                raise ValueError(f"Working directory does not exist: {directory}")
            result["directory"] = str(directory)
        return result

    @contextmanager
    def _launch_options(self, options: Mapping[str, str]) -> Iterator[None]:
        config = self.terminator.config
        original = config.options_get()
        saved = {name: getattr(original, name) for name in ("command", "execute", "working_directory")}
        # New widgets reload this original object from Terminator's option parser.
        original.command = options.get("command") or None
        original.execute = None
        original.working_directory = options.get("directory")
        try:
            yield
        finally:
            for name, value in saved.items():
                setattr(original, name, value)
            config.options_set(original)

    def _window_of(self, source: Any) -> Any:
        window = source.get_toplevel()
        if window in self.terminator.windows:
            return window
        return self._find(source.uuid.urn)[0]

    def _unzoom(self, source: Any) -> None:
        window = self._window_of(source)
        if window.is_zoomed():
            window.unzoom()

    @dbus.service.method(_INTERFACE, in_signature="sa{ss}", out_signature="s")
    def new_tab(self, uuid: str, options: Mapping[str, str]) -> str:
        """Open a tab in the source window with an optional command and directory."""
        source = self._source(uuid)
        options = self._options(options)
        window = self._window_of(source)
        self._unzoom(source)
        terminals_before = {terminal.uuid.urn for terminal in self.terminator.terminals}
        with self._launch_options(options):
            window.tab_new(source)
        added = {terminal.uuid.urn for terminal in self.terminator.terminals} - terminals_before
        if len(added) != 1:
            raise RuntimeError("Could not identify the new Terminator tab")
        return added.pop()

    @dbus.service.method(_INTERFACE, in_signature="ssa{ss}", out_signature="s")
    def split(self, uuid: str, direction: str, options: Mapping[str, str]) -> str:
        """Create a terminal to the right, left, above, or below the source."""
        if direction not in {"right", "left", "above", "below"}:
            raise ValueError(f"Unknown split direction: {direction}")
        source = self._source(uuid)
        options = self._options(options)
        self._unzoom(source)
        directory = options.get("directory", source.get_cwd())
        with self._launch_options(options):
            sibling = Factory().make("Terminal")
            sibling.set_cwd(directory)
            if self.terminator.config["always_split_with_profile"]:
                sibling.force_set_profile(None, source.get_profile())
            sibling.spawn_child()
            source.get_parent().split_axis(
                source,
                vertical=direction in {"above", "below"},
                cwd=directory,
                sibling=sibling,
                widgetfirst=direction in {"right", "below"},
            )
        return sibling.uuid.urn

    @staticmethod
    def _node_id(widget: Any) -> str:
        if isinstance(widget, (Terminal, Gtk.Window)):
            return widget.uuid.urn
        if not hasattr(widget, "_terminator_dbus_node_id"):
            widget._terminator_dbus_node_id = f"split:{uuid4()}"
        return widget._terminator_dbus_node_id

    @staticmethod
    def _logical_children(widget: Any, window: Any) -> list[Any]:
        children = list(widget.get_children())
        zoom = window.zoom_data if window.is_zoomed() else None
        if zoom and widget is zoom["old_parent"]:
            if isinstance(widget, Gtk.Notebook):
                children.insert(zoom["notebook_tabnum"], zoom["widget"])
            else:
                children = [zoom["widget"] if child is None else child for child in children]
        return [child for child in children if child is not None]

    def _leaves(self, widget: Any, window: Any) -> list[Any]:
        if isinstance(widget, Terminal):
            return [widget]
        return [
            terminal for child in self._logical_children(widget, window) for terminal in self._leaves(child, window)
        ]

    def _layout(self, window: Any) -> tuple[dict[str, Any], dict[str, Any]]:
        window_id = self._node_id(window)
        window_node = {
            "id": window_id,
            "type": "window",
            "parent": None,
            "children": [],
            "direction": None,
            "zoomed": bool(window.is_zoomed()),
        }
        nodes = {window_id: window_node}
        widgets = {window_id: window}
        focused = None
        root = window.zoom_data["old_child"] if window.is_zoomed() else window.get_child()
        if isinstance(root, Gtk.Notebook):
            pages = self._logical_children(root, window)
            active_page = root.get_current_page()
            if window.is_zoomed():
                active_page = (
                    window.zoom_data["notebook_tabnum"] if window.zoom_data["old_parent"] is root else active_page
                )
        else:
            pages = [root] if root is not None else []
            active_page = 0
        previous_tabs = getattr(window, "_terminator_dbus_tabs", {})
        current_tabs = {}

        def visit(widget: Any, parent: str, tab: str, direction: str | None, rect: list[float]) -> str:
            nonlocal focused
            if not isinstance(widget, Terminal):
                children = [child for child in self._logical_children(widget, window) if self._leaves(child, window)]
                # GTK can retain an empty branch while a terminal or pane closes.
                # Represent a remaining branch at its full logical size.
                if len(children) == 1:
                    return visit(children[0], parent, tab, direction, rect)
            node_id = self._node_id(widget)
            node = {"id": node_id, "parent": parent, "children": [], "direction": direction, "tab": tab, "rect": rect}
            nodes[node_id] = node
            widgets[node_id] = widget
            if isinstance(widget, Terminal):
                node.update(
                    type="terminal",
                    uuid=node_id,
                    directory=widget.get_cwd(),
                    profile=widget.get_profile(),
                    focused=bool(widget.vte.has_focus()),
                )
                if node["focused"]:
                    focused = node_id
                return node_id
            axis = "x" if isinstance(widget, HPaned) else "y"
            ratio = float(widget.ratio)
            node.update(type="split", axis=axis, ratio=ratio)
            x, y, width, height = rect
            rectangles = (
                [[x, y, width * ratio, height], [x + width * ratio, y, width * (1 - ratio), height]]
                if axis == "x"
                else [[x, y, width, height * ratio], [x, y + height * ratio, width, height * (1 - ratio)]]
            )
            directions = ["left", "right"] if axis == "x" else ["above", "below"]
            for child, side, rectangle in zip(children, directions, rectangles, strict=True):
                node["children"].append(visit(child, node_id, tab, side, rectangle))
            return node_id

        for index, page in enumerate(pages):
            members = frozenset(terminal.uuid.urn for terminal in self._leaves(page, window))
            if not members:
                continue
            label = root.get_tab_label(page) if isinstance(root, Gtk.Notebook) and page.get_parent() is root else None
            tab_id = getattr(label, "_terminator_dbus_tab_id", None) or getattr(page, "_terminator_dbus_tab_id", None)
            if tab_id is None or tab_id in current_tabs:
                candidates = [
                    (len(members & old_members), previous_id)
                    for previous_id, old_members in previous_tabs.items()
                    if previous_id not in current_tabs
                ]
                score, tab_id = max(candidates, default=(0, ""))
                if not score:
                    tab_id = f"tab:{uuid4()}"
            page._terminator_dbus_tab_id = tab_id
            if label is not None:
                label._terminator_dbus_tab_id = tab_id
            current_tabs[tab_id] = members
            window_node["children"].append(tab_id)
            tab_node = {
                "id": tab_id,
                "type": "tab",
                "parent": window_id,
                "children": [],
                "direction": None,
                "active": index == active_page,
                "index": index,
            }
            nodes[tab_id] = tab_node
            widgets[tab_id] = page
            if isinstance(root, Gtk.Notebook) and page.get_parent() is root:
                tab_node["title"] = root.get_tab_label(page).get_label()
            elif window.is_zoomed() and window.zoom_data["old_parent"] is root:
                tab_node["title"] = window.zoom_data["notebook_label"]
            else:
                tab_node["title"] = window.get_title()
            tab_node["children"].append(visit(page, tab_id, tab_id, None, [0.0, 0.0, 1.0, 1.0]))
        window._terminator_dbus_tabs = current_tabs
        return {"version": 1, "root": window_id, "focused_uuid": focused, "nodes": nodes}, widgets

    def _find(self, node_id: str) -> tuple[Any, dict[str, Any], dict[str, Any], Any]:
        for window in self.terminator.windows:
            tree, widgets = self._layout(window)
            if node_id in tree["nodes"]:
                return window, tree, tree["nodes"][node_id], widgets[node_id]
        raise ValueError(f"Layout node does not exist: {node_id}")

    def _editable(self, node_id: str) -> tuple[Any, Any]:
        window, _, node, widget = self._find(node_id)
        if node["type"] not in {"terminal", "split"}:
            raise ValueError("This operation requires a terminal or split node")
        return window, widget

    @staticmethod
    def _restore_window(window: Any) -> None:
        if window.is_zoomed():
            window.unzoom()

    @staticmethod
    def _flush(window: Any) -> None:
        window.show_all()
        while Gtk.events_pending():
            Gtk.main_iteration_do(blocking=False)

    @contextmanager
    def _editing(self, *windows: Any) -> Iterator[None]:
        flags = {window: window.set_pos_by_ratio for window in windows}
        for window in flags:
            window.set_pos_by_ratio = True
        try:
            yield
        finally:
            for window, flag in flags.items():
                if window in self.terminator.windows:
                    self._flush(window)
                    window.set_pos_by_ratio = flag

    @staticmethod
    def _metadata(parent: Any, widget: Any) -> Any:
        metadata = dict(parent.get_child_metadata(widget) or {})
        if isinstance(parent, (Gtk.Window, Gtk.Notebook)) and hasattr(widget, "_terminator_dbus_tab_id"):
            metadata["_terminator_dbus_tab_id"] = widget._terminator_dbus_tab_id
        return metadata

    @staticmethod
    def _attach(parent: Any, widget: Any, metadata: Any) -> None:
        parent.add(widget, metadata=metadata)
        if "_terminator_dbus_tab_id" in metadata:
            widget._terminator_dbus_tab_id = metadata["_terminator_dbus_tab_id"]

    def _wrap(self, target: Any, sibling: Any, direction: str) -> Any:
        parent = target.get_parent()
        metadata = self._metadata(parent, target)
        container = Factory().make("HPaned" if direction in {"left", "right"} else "VPaned")
        parent.remove(target)
        self._attach(parent, container, metadata)
        children = [target, sibling] if direction in {"right", "below"} else [sibling, target]
        for child in children:
            container.add(child)
        return container

    @dbus.service.method(_INTERFACE, in_signature="s", out_signature="s")
    def get_tree(self, uuid: str) -> str:
        """Return a JSON layout snapshot for the window containing this node."""
        return json.dumps(self._find(uuid)[1])

    @dbus.service.method(_INTERFACE, in_signature="s", out_signature="s")
    def get_node(self, node_id: str) -> str:
        """Return a node record as JSON."""
        return json.dumps(self._find(node_id)[2])

    @dbus.service.method(_INTERFACE, in_signature="s", out_signature="s")
    def get_parent(self, node_id: str) -> str:
        """Return the parent record as JSON, or JSON null for a window."""
        _, tree, node, _ = self._find(node_id)
        return json.dumps(tree["nodes"].get(node["parent"]))

    @dbus.service.method(_INTERFACE, in_signature="s", out_signature="s")
    def get_children(self, node_id: str) -> str:
        """Return ordered child records as JSON."""
        _, tree, node, _ = self._find(node_id)
        return json.dumps([tree["nodes"][child] for child in node["children"]])

    @dbus.service.method(_INTERFACE, in_signature="s", out_signature="s")
    def get_ancestors(self, node_id: str) -> str:
        """Return ancestor records from the nearest parent through the window."""
        _, tree, node, _ = self._find(node_id)
        ancestors = []
        while node["parent"] is not None:
            node = tree["nodes"][node["parent"]]
            ancestors.append(node)
        return json.dumps(ancestors)

    @dbus.service.method(_INTERFACE, in_signature="s", out_signature="s")
    def get_sibling(self, node_id: str) -> str:
        """Return the other branch of a split, or JSON null outside a split."""
        _, tree, node, _ = self._find(node_id)
        parent = tree["nodes"].get(node["parent"])
        sibling = None
        if parent is not None and parent["type"] == "split":
            sibling = next(tree["nodes"][child] for child in parent["children"] if child != node_id)
        return json.dumps(sibling)

    @dbus.service.method(_INTERFACE, in_signature="ss", out_signature="s")
    def get_neighbors(self, uuid: str, direction: str) -> str:
        """Return all terminals sharing an edge, ordered along that edge."""
        if direction not in {"right", "left", "above", "below"}:
            raise ValueError(f"Unknown neighbor direction: {direction}")
        _, tree, source, _ = self._find(uuid)
        if source["type"] != "terminal":
            raise ValueError("Neighbors require a terminal UUID")
        x, y, width, height = source["rect"]
        matches = []
        for node in tree["nodes"].values():
            if node["type"] != "terminal" or node["tab"] != source["tab"] or node["id"] == uuid:
                continue
            nx, ny, nw, nh = node["rect"]
            if direction in {"left", "right"}:
                edge = nx + nw if direction == "left" else nx
                source_edge = x if direction == "left" else x + width
                overlap = min(y + height, ny + nh) - max(y, ny)
                order = ny
            else:
                edge = ny + nh if direction == "above" else ny
                source_edge = y if direction == "above" else y + height
                overlap = min(x + width, nx + nw) - max(x, nx)
                order = nx
            if overlap > _EPSILON and math.isclose(edge, source_edge, abs_tol=_EPSILON):
                matches.append((order, node))
        return json.dumps([node for _, node in sorted(matches, key=lambda item: item[0])])

    @dbus.service.method(_INTERFACE, in_signature="sd", out_signature="")
    def set_split_ratio(self, node_id: str, ratio: float) -> None:
        """Set the first branch's share of space, strictly between zero and one."""
        if not math.isfinite(ratio) or not 0 < ratio < 1:
            raise ValueError("Split ratio must be finite and strictly between zero and one")
        window, _, node, widget = self._find(node_id)
        if node["type"] != "split":
            raise ValueError("Ratio adjustment requires a split node")
        self._restore_window(window)
        widget.ratio = ratio
        widget.set_position_by_ratio()

    @dbus.service.method(_INTERFACE, in_signature="s", out_signature="")
    def swap_children(self, node_id: str) -> None:
        """Exchange both branches of a split while keeping its divider ratio."""
        window, _, node, widget = self._find(node_id)
        if node["type"] != "split":
            raise ValueError("Child swapping requires a split node")
        self._restore_window(window)
        children = widget.get_children()
        ratio = widget.ratio
        with self._editing(window):
            for child in children:
                widget.remove(child)
            for child in reversed(children):
                widget.add(child)
            widget.ratio = ratio
            widget.set_position_by_ratio()

    @dbus.service.method(_INTERFACE, in_signature="ssa{ss}", out_signature="s")
    def split_node(self, node_id: str, direction: str, options: Mapping[str, str]) -> str:
        """Add a terminal beside a terminal or an entire split subtree."""
        if direction not in {"right", "left", "above", "below"}:
            raise ValueError(f"Unknown split direction: {direction}")
        options = self._options(options)
        window, target = self._editable(node_id)
        self._restore_window(window)
        if isinstance(target, Terminal):
            return self.split(node_id, direction, options)
        source = self._leaves(target, window)[0]
        directory = options.get("directory", source.get_cwd())
        with self._editing(window), self._launch_options(options):
            sibling = Factory().make("Terminal")
            sibling.set_cwd(directory)
            if self.terminator.config["always_split_with_profile"]:
                sibling.force_set_profile(None, source.get_profile())
            sibling.spawn_child()
            self._wrap(target, sibling, direction)
        sibling.ensure_visible_and_focussed()
        return sibling.uuid.urn

    @dbus.service.method(_INTERFACE, in_signature="ss", out_signature="s")
    def rotate_subtree(self, node_id: str, direction: str) -> str:
        """Rotate a split subtree clockwise or counterclockwise, preserving IDs."""
        if direction not in {"clockwise", "counterclockwise"}:
            raise ValueError(f"Unknown rotation direction: {direction}")
        window, _, node, widget = self._find(node_id)
        if node["type"] != "split":
            raise ValueError("Rotation requires a split node")
        self._restore_window(window)
        identities = {}

        def remember(pane: Any) -> None:
            if isinstance(pane, Terminal):
                return
            identities[frozenset(terminal.uuid.urn for terminal in self._leaves(pane, window))] = self._node_id(pane)
            for child in pane.get_children():
                remember(child)

        remember(widget)
        parent = widget.get_parent()
        metadata = self._metadata(parent, widget)
        old_children = set(parent.get_children())
        allocation = widget.get_allocation()
        focused = next((terminal for terminal in self.terminator.terminals if terminal.vte.has_focus()), None)
        previous_flag = window.set_pos_by_ratio
        window.set_pos_by_ratio = True
        try:
            parent.remove(widget)
            widget.rotate_recursive(parent, allocation.width, allocation.height, direction == "clockwise", metadata)
            replacement = next(child for child in parent.get_children() if child not in old_children)

            def restore_ids(pane: Any) -> None:
                if isinstance(pane, Terminal):
                    return
                pane._terminator_dbus_node_id = identities[
                    frozenset(terminal.uuid.urn for terminal in self._leaves(pane, window))
                ]
                for child in pane.get_children():
                    restore_ids(child)

            restore_ids(replacement)
            if "_terminator_dbus_tab_id" in metadata:
                replacement._terminator_dbus_tab_id = metadata["_terminator_dbus_tab_id"]
            self._flush(window)
            if focused is not None:
                focused.grab_focus()
        finally:
            window.set_pos_by_ratio = previous_flag
        return node_id

    def _collapse(self, parent: Any) -> None:
        if isinstance(parent, (HPaned, VPaned)):
            remaining = [child for child in parent.get_children() if child is not None]
            if len(remaining) != 1:
                return
            child = remaining[0]
            grandparent = parent.get_parent()
            metadata = self._metadata(grandparent, parent)
            parent.remove(child)
            grandparent.remove(parent)
            parent.cnxids.remove_all()
            self._attach(grandparent, child, metadata)
        elif isinstance(parent, Gtk.Notebook) and parent.get_n_pages() == 0:
            window = parent.get_toplevel()
            window.remove(parent)
            parent.cnxids.remove_all()
            window.hoover()

        elif isinstance(parent, Gtk.Window):
            parent.hoover()

    @dbus.service.method(_INTERFACE, in_signature="sss", out_signature="s")
    def move_node(self, node_id: str, target_id: str, direction: str) -> str:
        """Move an existing terminal or split subtree beside another node."""
        if direction not in {"right", "left", "above", "below"}:
            raise ValueError(f"Unknown move direction: {direction}")
        source_window, source = self._editable(node_id)
        target_window, target = self._editable(target_id)
        if source is target or target in self._descendants(source, source_window):
            raise ValueError("Cannot move a node into itself or one of its descendants")
        self._restore_window(source_window)
        self._restore_window(target_window)
        with self._editing(source_window, target_window):
            old_parent = source.get_parent()
            old_parent.remove(source)
            container = self._wrap(target, source, direction)
            self._collapse(old_parent)
        self._leaves(source, target_window)[0].ensure_visible_and_focussed()
        return self._node_id(container)

    def _descendants(self, widget: Any, window: Any) -> list[Any]:
        if isinstance(widget, Terminal):
            return []
        children = self._logical_children(widget, window)
        return children + [descendant for child in children for descendant in self._descendants(child, window)]

    @dbus.service.method(_INTERFACE, in_signature="s", out_signature="")
    def focus(self, uuid: str) -> None:
        """Select the terminal's tab and focus its window and shell."""
        window, _, node, terminal = self._find(uuid)
        if node["type"] != "terminal":
            raise ValueError("Focus requires a terminal UUID")
        self._restore_window(window)
        terminal.ensure_visible_and_focussed()
        window.present()


class TerminatorDBusExtension(Plugin):
    """Keep the terminal extension available while the plugin is enabled."""

    capabilities: ClassVar[list[str]] = []

    def __init__(self) -> None:
        """Start the extension service."""
        self.service = _ExtensionService()

    def unload(self) -> None:
        """Remove the extension service when the plugin is disabled."""
        self.service.remove_from_connection()
