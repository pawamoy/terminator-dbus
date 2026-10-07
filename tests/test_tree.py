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

"""Tests for local layout traversal and typed extension results."""

from __future__ import annotations

import json
from typing import Any
from unittest.mock import Mock

import pytest

from terminator_dbus import EXTENSION_INTERFACE, EXTENSION_PATH, LayoutTree, TerminalExtension, Terminator


@pytest.fixture
def tree_data() -> dict[str, Any]:
    """Describe A beside a B/C stack, with D isolated in another tab."""
    return {
        "root": "window",
        "focused_uuid": "B",
        "nodes": {
            "window": {"id": "window", "type": "window", "parent": None, "children": ["tab1", "tab2"]},
            "tab1": {"id": "tab1", "type": "tab", "parent": "window", "children": ["outer"]},
            "tab2": {"id": "tab2", "type": "tab", "parent": "window", "children": ["D"]},
            "outer": {
                "id": "outer",
                "type": "split",
                "parent": "tab1",
                "children": ["A", "stack"],
                "axis": "x",
                "ratio": 0.4,
            },
            "stack": {
                "id": "stack",
                "type": "split",
                "parent": "outer",
                "children": ["B", "C"],
                "axis": "y",
                "ratio": 0.5,
            },
            "A": {
                "id": "A",
                "type": "terminal",
                "parent": "outer",
                "children": [],
                "tab": "tab1",
                "rect": [0, 0, 0.4, 1],
            },
            "B": {
                "id": "B",
                "type": "terminal",
                "parent": "stack",
                "children": [],
                "tab": "tab1",
                "rect": [0.4, 0, 0.6, 0.5],
            },
            "C": {
                "id": "C",
                "type": "terminal",
                "parent": "stack",
                "children": [],
                "tab": "tab1",
                "rect": [0.4, 0.5, 0.6, 0.5],
            },
            "D": {"id": "D", "type": "terminal", "parent": "tab2", "children": [], "tab": "tab2", "rect": [0, 0, 1, 1]},
        },
    }


def test_traverse_local_tree(tree_data: dict[str, Any]) -> None:
    """Expose parent, ordered children, ancestor paths, and sibling subtrees."""
    tree = LayoutTree(tree_data)

    assert tree.root == "window"
    assert tree.focused_uuid == "B"
    assert tree.get_parent("window") is None
    parent = tree.get_parent("B")
    assert parent is not None
    assert parent["id"] == "stack"
    assert [node["id"] for node in tree.get_children("outer")] == ["A", "stack"]
    assert [node["id"] for node in tree.get_ancestors("C")] == ["stack", "outer", "tab1", "window"]
    sibling_a = tree.get_sibling("A")
    sibling_b = tree.get_sibling("B")
    assert sibling_a is not None
    assert sibling_b is not None
    assert sibling_a["id"] == "stack"
    assert sibling_b["id"] == "C"
    assert tree.get_sibling("tab1") is None
    assert tree.get_sibling("D") is None
    assert tree.get_children("A") == []


@pytest.mark.parametrize(
    ("source", "direction", "expected"),
    [
        ("A", "right", ["B", "C"]),
        ("A", "left", []),
        ("A", "above", []),
        ("B", "left", ["A"]),
        ("B", "below", ["C"]),
        ("C", "above", ["B"]),
        ("C", "right", []),
        ("D", "left", []),
    ],
)
def test_find_edge_neighbors(tree_data: dict[str, Any], source: str, direction: str, expected: list[str]) -> None:
    """Return every shared-edge neighbor without crossing tabs or wrapping."""
    tree = LayoutTree(tree_data)

    neighbors = tree.get_neighbors(source, direction)

    assert [node["id"] for node in neighbors] == expected


def test_neighbors_ignore_corner_contacts(tree_data: dict[str, Any]) -> None:
    """Touching one corner does not make two terminals edge neighbors."""
    tree_data["nodes"]["A"]["rect"] = [0, 0, 0.4, 0.5]
    tree = LayoutTree(tree_data)

    assert [node["id"] for node in tree.get_neighbors("A", "right")] == ["B"]


def test_reject_invalid_local_queries(tree_data: dict[str, Any]) -> None:
    """Report missing nodes, invalid directions, and nonterminal neighbor queries."""
    tree = LayoutTree(tree_data)

    with pytest.raises(KeyError, match="missing"):
        tree.get_node("missing")

    with pytest.raises(ValueError, match="Unknown neighbor direction"):
        tree.get_neighbors("A", "diagonal")

    with pytest.raises(ValueError, match="Neighbors require a terminal UUID"):
        tree.get_neighbors("stack", "left")


def test_typed_snapshot_reuses_connection_and_traverses_locally(tree_data: dict[str, Any]) -> None:
    """Fetch one decoded snapshot, then inspect it without more remote calls."""
    client = Mock(spec=Terminator)
    client.call.return_value = json.dumps(tree_data)
    extension = TerminalExtension(client)

    tree = extension.get_tree("A")
    tree.get_ancestors("C")
    tree.get_sibling("A")
    tree.get_neighbors("A", "right")

    client.call.assert_called_once_with(
        "get_tree",
        "A",
        interface=EXTENSION_INTERFACE,
        object_path=EXTENSION_PATH,
        signature="s",
    )
    assert tree.get_node("A")["id"] == "A"

    # A new snapshot sees remote changes; the earlier snapshot keeps its parent.
    tree_data["nodes"]["A"]["parent"] = "new-parent"
    client.call.return_value = json.dumps(tree_data)
    updated = extension.get_tree("A")

    assert tree.get_node("A")["parent"] == "outer"
    assert updated.get_node("A")["parent"] == "new-parent"


@pytest.mark.parametrize(("method", "result"), [("get_parent", None), ("get_children", [])])
def test_decode_empty_query_results(method: str, result: Any) -> None:
    """Decode JSON null and empty lists without treating them as errors."""
    client = Mock(spec=Terminator)
    client.call.return_value = json.dumps(result)
    extension = TerminalExtension(client)

    assert getattr(extension, method)("node") == result


def test_remote_error_propagates_from_typed_client() -> None:
    """Keep the original exception when the plugin rejects a mutation."""
    client = Mock(spec=Terminator)
    failure = ValueError("Unknown node")
    client.call.side_effect = failure

    with pytest.raises(ValueError, match="Unknown node") as error:
        TerminalExtension(client).move_node("source", "target", "right")

    assert error.value is failure
