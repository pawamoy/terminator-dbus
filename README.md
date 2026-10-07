# Terminator D-Bus

[![ci](https://github.com/pawamoy/terminator-dbus/workflows/ci/badge.svg)](https://github.com/pawamoy/terminator-dbus/actions?query=workflow%3Aci)
[![documentation](https://img.shields.io/badge/docs-zensical-FF9100.svg?style=flat)](https://pawamoy.github.io/terminator-dbus/)
[![pypi version](https://img.shields.io/pypi/v/terminator-dbus.svg)](https://pypi.org/project/terminator-dbus/)
[![gitter](https://img.shields.io/badge/matrix-chat-4DB798.svg?style=flat)](https://app.gitter.im/#/room/#terminator-dbus:gitter.im)

Python library to interact with Terminator through D-Bus.

## Installation

```bash
pip install terminator-dbus
```

With [`uv`](https://docs.astral.sh/uv/):

```bash
uv tool install terminator-dbus
```

`dbus-python` needs the D-Bus development files when no system package or wheel is available.

## Usage

Create one client and reuse it for all calls:

```python
from terminator_dbus import Terminator

terminator = Terminator()
terminal = terminator.get_focused_terminal()

if terminal is not None:
    new_terminal = terminator.vsplit(
        terminal,
        {"execute": "htop", "title": "Processes"},
    )
    terminator.switch_profile(new_terminal, {"profile": "work"})
```

The client uses a non-empty `TERMINATOR_DBUS_NAME` by default. If it is absent or empty, the client uses the current X11 or Wayland display. Pass `display` to select a different display:

```python
terminator = Terminator(display=":1")
```

Pass `bus_name` when you already know the complete D-Bus service name. Both `bus_name` and `display` override `TERMINATOR_DBUS_NAME`:

```python
terminator = Terminator(bus_name="net.tenshu.Terminator2...")
```

Terminal creation methods raise `TerminatorError` when Terminator returns a response that starts with `ERROR:`. Import it from `terminator_dbus`. Its `method` and `message` attributes contain the failed method and original response.

`TerminatorError` is a subclass of `dbus.DBusException`. Catch `dbus.DBusException` to handle connection failures, remote exceptions, and terminal creation errors together.

## Bundled terminal extension

The package includes a reusable Terminator plugin for targeted tabs and splits. It runs inside Terminator and exports an additional D-Bus interface.

Install the plugin:

```bash
terminator-dbus install-plugin
```

Enable `TerminatorDBusExtension` in Terminator's **Preferences > Plugins**. Open a terminal to load a newly enabled plugin. After updating an already loaded plugin, restart Terminator.

The command installs a standalone file in `$XDG_CONFIG_HOME/terminator/plugins`, or `~/.config/terminator/plugins` by default. Terminator's Python environment does not need this package. Run the command again after upgrading the package to update the installed plugin.

For a custom plugin directory, use `terminator-dbus install-plugin --directory /path/to/plugins`. Python callers can use `install_plugin(directory=None)`.

Create a proxy for the extension:

```python
import os
import shlex

from terminator_dbus import EXTENSION_INTERFACE, EXTENSION_PATH, Terminator

terminator = Terminator()
source_uuid = os.environ.get("TERMINATOR_UUID") or terminator.get_focused_terminal()
extension = terminator.get_interface(
    EXTENSION_INTERFACE,
    object_path=EXTENSION_PATH,
)

if source_uuid is not None:
    terminal = extension.new_tab(
        source_uuid,
        {"command": shlex.join(["my-program", "an argument with spaces"])},
    )
    terminator.set_tab_title(str(terminal), {"tab-title": "My task"})
    extension.split(source_uuid, "right", {"directory": "/home/user/dev/project"})
```

The interface is `net.tenshu.Terminator2.Extension`, at `/net/tenshu/Terminator2/Extension`. Each method returns the new terminal's UUID.

| Method | Input signature | Behavior |
| --- | --- | --- |
| `new_tab(uuid, options)` | `sa{ss}` | Open a tab in the source terminal's window. |
| `split(uuid, direction, options)` | `ssa{ss}` | Create a terminal `right`, `left`, `above`, or `below` the source. |

`options` is a string-to-string dictionary. An empty dictionary selects the defaults.

| Option | Behavior when set | Default |
| --- | --- | --- |
| `directory` | Use this existing directory, with `~` expanded. Relative paths resolve in Terminator's process. | Inherit the terminal being split, or the source terminal for a new tab. |
| `command` | Run this shell command when the terminal starts. Quote arguments with `shlex.join`. | Use Terminator's configured shell or profile command. |

Terminator's `always_split_with_profile` setting controls profile inheritance. The extension restores a zoomed terminal's layout before creating a tab or split. Invalid UUIDs, directories, directions, or option names raise remote D-Bus exceptions.

### Layout trees and traversal

Use `terminator.extension` for a typed client that decodes layout queries into Python objects:

```python
import os

from terminator_dbus import Terminator

terminator = Terminator()
extension = terminator.extension
source = os.environ.get("TERMINATOR_UUID") or terminator.get_focused_terminal()

if source is not None:
    tree = extension.get_tree(source)
    node = tree.get_node(source)
    parent = tree.get_parent(source)
    ancestors = tree.get_ancestors(source)
    neighbors = tree.get_neighbors(source, "right")
    print(node["directory"], node["tab"], neighbors)
```

`get_tree` returns a `LayoutTree` snapshot of the node's entire window, including inactive tabs. Its `root` is the window ID. Its `nodes` dictionary maps IDs to node records. Its `focused_uuid` identifies the focused terminal in that window, or is `None`.

A window contains tab nodes. Each tab contains one terminal or split subtree. Each split has two ordered children. Queries report the logical layout while zoomed and preserve zoom, focus, and tab selection. Snapshots omit empty branches and flatten splits with one surviving branch.

| Node fields | Meaning |
| --- | --- |
| `id`, `type`, `parent`, `children` | Node ID, type, parent ID, and ordered child IDs. The root's parent is `None`. |
| `direction` | Position within a parent split: `left`, `right`, `above`, or `below`. Otherwise `None`. |
| `axis`, `ratio` | Split axis: `x` for left/right or `y` for above/below. Ratio is the first child's share of available space. |
| `tab`, `rect` | Containing tab ID and normalized `[x, y, width, height]` rectangle for a terminal or split. Rectangles ignore divider widths. |
| `uuid`, `directory`, `profile`, `focused` | Terminal UUID, current working directory, profile name, and focus state. |
| `index`, `title`, `active` | Tab position, displayed title, and whether the tab is selected. |
| `zoomed` | Whether the window currently shows a zoomed terminal. |

Terminal and window IDs are their existing UUIDs. Split and tab IDs are opaque strings. IDs remain stable through extension reloads, resizing, swaps, rotation, and moves. Collapsing a split or removing a tab or window invalidates its ID.

| Query | Result |
| --- | --- |
| `get_tree(node_id)` | A `LayoutTree` containing the node's window. |
| `get_node(node_id)` | One node record. |
| `get_parent(node_id)` | Parent record, or `None` for a window. |
| `get_children(node_id)` | Child records in display order. Terminals have no children. |
| `get_ancestors(node_id)` | Parent records from the nearest parent through the window. |
| `get_sibling(node_id)` | The other branch of a split, or `None` outside a split. |
| `get_neighbors(uuid, direction)` | All terminals sharing the requested edge, ordered along that edge. |

Call traversal methods on `tree` to use the local snapshot without additional D-Bus calls. Call them on `extension` to query the current layout. Neighbor queries accept `right`, `left`, `above`, and `below`. They exclude corner contacts, other tabs, and wrapping at tab edges.

A sibling can be an entire subtree. For example, a terminal beside a stack of two terminals has one sibling subtree and two right-hand neighbors.

### Layout manipulation

The typed extension client provides these operations:

| Method | Behavior | Result |
| --- | --- | --- |
| `set_split_ratio(node_id, ratio)` | Resize a split. The finite ratio must be strictly between zero and one. | `None` |
| `swap_children(node_id)` | Exchange a split's branches and keep its divider ratio. | `None` |
| `split_node(node_id, direction, options=None)` | Add a terminal beside a terminal or entire split subtree. | New terminal UUID |
| `rotate_subtree(node_id, direction="clockwise")` | Rotate a split subtree `clockwise` or `counterclockwise`. Preserve its node IDs. | Rotated split ID |
| `move_node(node_id, target_id, direction)` | Move a terminal or split subtree beside another node, including across tabs and windows. | New enclosing split ID |
| `focus(uuid)` | Select the terminal's tab and focus its window and shell. | `None` |

Split and move directions are `right`, `left`, `above`, and `below`. `split_node` accepts the same launch options as `split`. For a subtree, omitted settings inherit from its first terminal in display order.

```python
parent = tree.get_parent(source)
if parent is not None and parent["type"] == "split":
    extension.set_split_ratio(parent["id"], 0.3)
    extension.swap_children(parent["id"])
    extension.rotate_subtree(parent["id"])
    created = extension.split_node(parent["id"], "below", {"directory": "/home/user/dev/project"})
    extension.move_node(created, source, "right")
    extension.focus(created)
```

Moving and rotating existing nodes preserve their running shell processes. Moves preserve tab titles and order, and remove empty source splits, tabs, and windows. A node cannot move beside itself or into its own descendants.

Mutations restore zoomed layouts before editing. Fetch another snapshot after a mutation to inspect the updated tree. Remote queries and mutations raise `dbus.DBusException` for invalid IDs or arguments. Local traversal raises `KeyError` for missing IDs and `ValueError` for invalid neighbor queries.

Dynamic D-Bus proxies remain available. Their tree queries return JSON strings; the typed client decodes those strings. Tree queries use input signature `s`, except `get_neighbors`, which uses `ss`. Their output signature is `s`.

Mutation input signatures are `sd` for `set_split_ratio`, `s` for `swap_children` and `focus`, `ssa{ss}` for `split_node`, `ss` for `rotate_subtree`, and `sss` for `move_node`. Creation, rotation, and move methods return strings; other mutations have no output.

### Testing with Terminator

The default test suite uses local snapshots and mocked connections. Run the integration tests with real Terminator, `dbus-daemon`, and `Xvfb` installed:

```bash
TERMINATOR_DBUS_INTEGRATION=1 pytest tests/test_layout_integration.py
```

The tests create a private D-Bus service, display, and configuration. They check layout topology, direction, sizing, focus, zoom, tab identity, and shell process preservation.

## Plugin interfaces

Plugins can export additional D-Bus objects and interfaces in the running Terminator service. The client supports these interfaces through generic calls, dynamic proxies, and discovery.

The examples use `source_uuid` for an existing terminal's UUID, obtained with `terminator.get_focused_terminal()`.

To call a method directly, provide its interface, object path, and input signature:

```python
terminal = terminator.call(
    "split",
    source_uuid,
    "right",
    {"directory": "/home/user/dev/project"},
    interface="net.tenshu.Terminator2.Extension",
    object_path="/net/tenshu/Terminator2/Extension",
    signature="ssa{ss}",
)
```

The default interface and object path select Terminator's built-in API. An explicit signature skips introspection. If `signature` is unset, the proxy obtains input signatures through introspection. Use `signature=""` for methods with no inputs.

To call several methods on the same plugin, create a dynamic interface proxy:

```python
plugin = terminator.get_interface(
    "net.tenshu.Terminator2.Extension",
    object_path="/net/tenshu/Terminator2/Extension",
)
terminal = plugin.split(source_uuid, "right", {"directory": "/home/user/dev/project"})
```

Proxy methods use introspection to obtain their signatures. Pass `introspect=False` to `get_interface` if each call supplies its own `signature`. The client reuses its bus connection and caches proxies by object path and introspection setting.

To find exported interfaces and create their proxies, inspect the running service:

```python
interfaces = terminator.discover_interfaces()
plugin = interfaces["/net/tenshu/Terminator2/Extension"][
    "net.tenshu.Terminator2.Extension"
]
terminal = plugin.split(source_uuid, "right", {"directory": "/home/user/dev/project"})
```

Discovery starts at `/` and follows child objects. Provide an object path to limit its scope, or use `recursive=False` to inspect one object. Results include standard D-Bus interfaces and Terminator's built-in interface.

Discovery finds exported D-Bus interfaces; it does not list installed, enabled, or disabled Python plugins. Terminator's built-in D-Bus API does not expose that plugin metadata. Plugins must be enabled and export an interface for their methods to be callable.

Generic calls preserve plugin results, including strings that start with `ERROR:`. Calls to built-in terminal creation methods still raise `TerminatorError`. Methods called directly on a dynamic proxy return raw D-Bus results. Remote D-Bus exceptions propagate in all three APIs.

## D-Bus interface

This package follows the interface in [Terminator 2.1.6 `ipc.py`](https://github.com/gnome-terminator/terminator/blob/v2.1.6/terminatorlib/ipc.py).

- Base service and interface name: `net.tenshu.Terminator2`
- Object path: `/net/tenshu/Terminator2`
- Display-specific name: the base name followed by the MD5 digest of the GDK display name

Terminator removes the screen suffix before it creates the digest. Thus, `:0` and `:0.0` use the same service name.

The `Terminator` class exposes every method in the service:

| Python method | D-Bus input | Purpose | Result |
| --- | --- | --- | --- |
| `new_window_cmdline(options)` | `a{ss}` | Create a window from serialized command-line options. | `None` |
| `new_tab_cmdline(options)` | `a{ss}` | Create a tab from serialized command-line options. | `None` |
| `toggle_visibility_cmdline(options)` | `a{ss}` | Toggle all window visibility. | `None` |
| `unhide_cmdline(options)` | `a{ss}` | Show all hidden windows. | `None` |
| `new_window()` | empty | Create a window. | New terminal UUID |
| `new_tab(uuid)` | `v` | Create a tab in a terminal's window. | New terminal UUID |
| `reload_configuration()` | empty | Reload configuration for all terminals. | `None` |
| `bg_img_all(options)` | `v` | Set all background images from the `file` option. | `None` |
| `bg_img(uuid, options)` | `vv` | Set one background image from the `file` option. | `None` |
| `hsplit(uuid, options=None)` | `vv` | Split a terminal horizontally. | New terminal UUID |
| `vsplit(uuid, options=None)` | `vv` | Split a terminal vertically. | New terminal UUID |
| `get_terminals()` | empty | Get all terminal UUIDs. | `list[str]` |
| `get_focused_terminal()` | empty | Get the focused terminal UUID. | `str \| None` |
| `get_window(uuid)` | `v` | Get a terminal's window UUID. | `str` |
| `get_window_title(uuid)` | `v` | Get a terminal's window title. | `str` |
| `get_tab(uuid)` | `v` | Get a terminal's tab identifier. | `str \| None` |
| `get_tab_title(uuid)` | `v` | Get a terminal's tab title. | `str \| None` |
| `set_tab_title(uuid, options)` | `vv` | Set a tab title from the `tab-title` option. | `None` |
| `switch_profile(uuid, options)` | `vv` | Set one profile from the `profile` option. | `None` |
| `switch_profile_all(options)` | `v` | Set all profiles from the `profile` option. | `None` |

Terminator does not assign identifiers to tabs. Its `get_tab` method returns an empty string for a terminal in a notebook.

The four `*_cmdline` methods require string-to-string dictionaries. The window and tab creation methods require the complete option mapping from Terminator's command-line parser.

Terminator does not declare D-Bus output signatures. `dbus-python` infers each output signature from the value returned by the service method.

## Sponsors

<!-- sponsors-start -->
<!-- sponsors-end -->
