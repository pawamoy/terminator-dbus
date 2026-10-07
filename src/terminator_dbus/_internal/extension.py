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

from __future__ import annotations

import json
import os
from importlib.resources import files
from pathlib import Path
from typing import TYPE_CHECKING, Any

from terminator_dbus._internal.tree import LayoutTree as _LayoutTree

if TYPE_CHECKING:
    from collections.abc import Mapping

    from terminator_dbus._internal.client import Terminator

EXTENSION_INTERFACE = "net.tenshu.Terminator2.Extension"
"""D-Bus interface exported by the bundled Terminator plugin."""
EXTENSION_PATH = "/net/tenshu/Terminator2/Extension"
"""Object path exported by the bundled Terminator plugin."""


def install_plugin(directory: str | Path | None = None) -> Path:
    """Install the bundled plugin in Terminator's plugin directory.

    Enable `TerminatorDBusExtension` in Terminator's preferences after installation.
    The installed file is independent of the Python environment that installs it.
    Repeated calls update the installed plugin to the bundled version.

    Parameters:
        directory: Plugin directory. Defaults to `$XDG_CONFIG_HOME/terminator/plugins`,
            or `~/.config/terminator/plugins` when the variable is absent or empty.

    Returns:
        The installed plugin path.

    Raises:
        OSError: If the plugin directory or file cannot be written.
    """
    if directory is None:
        configuration = Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config")
        directory = configuration / "terminator" / "plugins"
    destination = Path(directory).expanduser() / "terminator_dbus_extension.py"
    destination.parent.mkdir(parents=True, exist_ok=True)
    resource = files("terminator_dbus").joinpath("plugin", destination.name)
    destination.write_bytes(resource.read_bytes())
    return destination


class TerminalExtension:
    """Call the bundled plugin and decode its layout queries into Python objects.

    Access this client through `Terminator.extension`. Remote operations act on
    the live layout. Methods on a returned `LayoutTree` use its local snapshot.

    Parameters:
        client: Terminator client whose connection the extension will reuse.
    """

    def __init__(self, client: Terminator) -> None:
        self._client = client

    def _call(self, method: str, *args: object, signature: str) -> Any:
        return self._client.call(
            method,
            *args,
            interface=EXTENSION_INTERFACE,
            object_path=EXTENSION_PATH,
            signature=signature,
        )

    def _query(self, method: str, *args: str, signature: str = "s") -> Any:
        return json.loads(str(self._call(method, *args, signature=signature)))

    def get_tree(self, uuid: str) -> _LayoutTree:
        """Return a local layout snapshot for the window containing this node."""
        return _LayoutTree(self._query("get_tree", uuid))

    def get_node(self, node_id: str) -> dict[str, Any]:
        """Inspect a node in the current layout."""
        return self._query("get_node", node_id)

    def get_parent(self, node_id: str) -> dict[str, Any] | None:
        """Inspect the current parent, or return `None` for a window root."""
        return self._query("get_parent", node_id)

    def get_children(self, node_id: str) -> list[dict[str, Any]]:
        """Inspect current children in display order."""
        return self._query("get_children", node_id)

    def get_ancestors(self, node_id: str) -> list[dict[str, Any]]:
        """Inspect current ancestors from the nearest parent through the window."""
        return self._query("get_ancestors", node_id)

    def get_sibling(self, node_id: str) -> dict[str, Any] | None:
        """Inspect the other branch of the current parent split, if any."""
        return self._query("get_sibling", node_id)

    def get_neighbors(self, uuid: str, direction: str) -> list[dict[str, Any]]:
        """Inspect all terminals sharing the requested edge in the current tab."""
        return self._query("get_neighbors", uuid, direction, signature="ss")

    def new_tab(self, uuid: str, options: Mapping[str, str] | None = None) -> str:
        """Create a tab with optional `command` and `directory` settings."""
        return str(self._call("new_tab", uuid, dict(options or {}), signature="sa{ss}"))

    def split(self, uuid: str, direction: str, options: Mapping[str, str] | None = None) -> str:
        """Create a terminal `right`, `left`, `above`, or `below` the source."""
        return str(self._call("split", uuid, direction, dict(options or {}), signature="ssa{ss}"))

    def set_split_ratio(self, node_id: str, ratio: float) -> None:
        """Set the first branch's share of space, strictly between zero and one."""
        self._call("set_split_ratio", node_id, ratio, signature="sd")

    def swap_children(self, node_id: str) -> None:
        """Exchange both branches while keeping the split's divider ratio."""
        self._call("swap_children", node_id, signature="s")

    def split_node(self, node_id: str, direction: str, options: Mapping[str, str] | None = None) -> str:
        """Add a terminal beside an existing terminal or entire split subtree.

        Omitted launch options inherit from the subtree's first terminal in
        display order, subject to Terminator's profile inheritance setting.
        """
        return str(self._call("split_node", node_id, direction, dict(options or {}), signature="ssa{ss}"))

    def rotate_subtree(self, node_id: str, direction: str = "clockwise") -> str:
        """Rotate a split `clockwise` or `counterclockwise`, preserving node IDs."""
        return str(self._call("rotate_subtree", node_id, direction, signature="ss"))

    def move_node(self, node_id: str, target_id: str, direction: str) -> str:
        """Move a terminal or subtree beside another node without restarting shells.

        Nodes may belong to different tabs or windows. The returned ID denotes
        the new split enclosing the target and moved node. Empty source splits,
        tabs, and windows are removed. Moving into one's own subtree is invalid.
        """
        return str(self._call("move_node", node_id, target_id, direction, signature="sss"))

    def focus(self, uuid: str) -> None:
        """Select a terminal's tab and focus its window and shell."""
        self._call("focus", uuid, signature="s")
