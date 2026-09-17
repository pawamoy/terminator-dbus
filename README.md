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


The client uses the current X11 or Wayland display by default. Pass `display` if the current environment does not identify the correct display:


```python
terminator = Terminator(display=":1")
```


Pass `bus_name` when you already know the complete D-Bus service name:


```python
terminator = Terminator(bus_name="net.tenshu.Terminator2...")
```


`dbus.DBusException` reports connection and remote method failures. Terminator itself returns strings that start with `ERROR:` for some tab and split failures.


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
| `new_window()` | empty | Create a window. | New terminal UUID or error string |
| `new_tab(uuid)` | `v` | Create a tab in a terminal's window. | New terminal UUID or error string |
| `reload_configuration()` | empty | Reload configuration for all terminals. | `None` |
| `bg_img_all(options)` | `v` | Set all background images from the `file` option. | `None` |
| `bg_img(uuid, options)` | `vv` | Set one background image from the `file` option. | `None` |
| `hsplit(uuid, options=None)` | `vv` | Split a terminal horizontally. | New terminal UUID or error string |
| `vsplit(uuid, options=None)` | `vv` | Split a terminal vertically. | New terminal UUID or error string |
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
