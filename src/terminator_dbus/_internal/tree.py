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

import math
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Mapping


_EPSILON = 1e-9


class LayoutTree:
    """Inspect one window's layout without making further D-Bus calls.

    Snapshots remain unchanged when the live layout changes. Fetch a new tree
    after a mutation to see the current parents, children, ratios, and focus.
    Terminal node IDs are their UUIDs. Other node IDs are opaque strings.

    Parameters:
        data: Decoded result of the extension's `get_tree` method.
    """

    root: str
    """ID of the window node."""

    nodes: dict[str, dict[str, Any]]
    """Node IDs mapped to their layout records."""

    focused_uuid: str | None
    """UUID of the focused terminal in this window, if any."""

    def __init__(self, data: Mapping[str, Any]) -> None:
        self.root = data["root"]
        self.nodes = {name: dict(node) for name, node in data["nodes"].items()}
        self.focused_uuid = data["focused_uuid"]

    def get_node(self, node_id: str) -> dict[str, Any]:
        """Return a node record; raise `KeyError` if the ID is absent."""
        return self.nodes[node_id]

    def get_parent(self, node_id: str) -> dict[str, Any] | None:
        """Return a node's parent, or `None` for the window root."""
        parent = self.get_node(node_id)["parent"]
        return None if parent is None else self.get_node(parent)

    def get_children(self, node_id: str) -> list[dict[str, Any]]:
        """Return children in tab order, left/right order, or above/below order."""
        return [self.get_node(child) for child in self.get_node(node_id)["children"]]

    def get_ancestors(self, node_id: str) -> list[dict[str, Any]]:
        """Return parents from the nearest split or tab through the window."""
        ancestors = []
        parent = self.get_parent(node_id)
        while parent is not None:
            ancestors.append(parent)
            parent = self.get_parent(parent["id"])
        return ancestors

    def get_sibling(self, node_id: str) -> dict[str, Any] | None:
        """Return the other branch of a split, or `None` outside a split."""
        parent = self.get_parent(node_id)
        if parent is None or parent["type"] != "split":
            return None
        return next(child for child in self.get_children(parent["id"]) if child["id"] != node_id)

    def get_neighbors(self, uuid: str, direction: str) -> list[dict[str, Any]]:
        """Return all terminals sharing the requested edge in the same tab.

        Directions are `right`, `left`, `above`, and `below`. Results follow
        display order along the shared edge. There is no wrapping at tab edges.
        Rectangles use normalized tab coordinates and ignore separator widths.

        Raises:
            KeyError: The UUID is absent from the snapshot.
            ValueError: The node is not a terminal, or the direction is invalid.
        """
        if direction not in {"right", "left", "above", "below"}:
            raise ValueError(f"Unknown neighbor direction: {direction}")
        source = self.get_node(uuid)
        if source["type"] != "terminal":
            raise ValueError("Neighbors require a terminal UUID")
        x, y, width, height = source["rect"]
        matches = []
        for node in self.nodes.values():
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
        return [node for _, node in sorted(matches, key=lambda item: item[0])]
