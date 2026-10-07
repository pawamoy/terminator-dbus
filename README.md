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

## Plugin interfaces

Plugins can export additional D-Bus objects and interfaces in the running Terminator service. The client supports these interfaces through generic calls, dynamic proxies, and discovery.

The examples use `source_uuid` for an existing terminal's UUID, obtained with `terminator.get_focused_terminal()`.

To call a method directly, provide its interface, object path, and input signature:

```python
terminal = terminator.call(
    "project_split",
    source_uuid,
    "/home/user/dev/project",
    interface="net.tenshu.Terminator2.Devboard",
    object_path="/net/tenshu/Terminator2/Devboard",
    signature="ss",
)
```

The default interface and object path select Terminator's built-in API. An explicit signature skips introspection. If `signature` is unset, the proxy obtains input signatures through introspection. Use `signature=""` for methods with no inputs.

To call several methods on the same plugin, create a dynamic interface proxy:

```python
plugin = terminator.get_interface(
    "net.tenshu.Terminator2.Devboard",
    object_path="/net/tenshu/Terminator2/Devboard",
)
terminal = plugin.project_split(source_uuid, "/home/user/dev/project")
```

Proxy methods use introspection to obtain their signatures. Pass `introspect=False` to `get_interface` if each call supplies its own `signature`. The client reuses its bus connection and caches proxies by object path and introspection setting.

To find exported interfaces and create their proxies, inspect the running service:

```python
interfaces = terminator.discover_interfaces()
plugin = interfaces["/net/tenshu/Terminator2/Devboard"][
    "net.tenshu.Terminator2.Devboard"
]
terminal = plugin.project_split(source_uuid, "/home/user/dev/project")
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
