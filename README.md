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

<div id="premium-sponsors" style="text-align: center;">

<div id="silver-sponsors"><b>Silver sponsors</b><p>
<a href="https://fastapi.tiangolo.com/"><img alt="FastAPI" src="https://raw.githubusercontent.com/tiangolo/fastapi/master/docs/en/docs/img/logo-margin/logo-teal.png" style="height: 200px; "></a><br>
</p></div>

<div id="bronze-sponsors"><b>Bronze sponsors</b><p>
<a href="https://www.nixtla.io/"><picture><source media="(prefers-color-scheme: light)" srcset="https://www.nixtla.io/img/logo/full-black.svg"><source media="(prefers-color-scheme: dark)" srcset="https://www.nixtla.io/img/logo/full-white.svg"><img alt="Nixtla" src="https://www.nixtla.io/img/logo/full-black.svg" style="height: 60px; "></picture></a><br>
</p></div>
</div>

---

<div id="sponsors"><p>
<a href="https://github.com/ofek"><img alt="ofek" src="https://avatars.githubusercontent.com/u/9677399?u=386c330f212ce467ce7119d9615c75d0e9b9f1ce&v=4" style="height: 32px; border-radius: 100%;"></a>
<a href="https://github.com/samuelcolvin"><img alt="samuelcolvin" src="https://avatars.githubusercontent.com/u/4039449?u=42eb3b833047c8c4b4f647a031eaef148c16d93f&v=4" style="height: 32px; border-radius: 100%;"></a>
<a href="https://github.com/tlambert03"><img alt="tlambert03" src="https://avatars.githubusercontent.com/u/1609449?u=922abf0524b47739b37095e553c99488814b05db&v=4" style="height: 32px; border-radius: 100%;"></a>
<a href="https://github.com/ssbarnea"><img alt="ssbarnea" src="https://avatars.githubusercontent.com/u/102495?u=c7bd9ddf127785286fc939dd18cb02db0a453bce&v=4" style="height: 32px; border-radius: 100%;"></a>
<a href="https://github.com/femtomc"><img alt="femtomc" src="https://avatars.githubusercontent.com/u/34410036?u=f13a71daf2a9f0d2da189beaa94250daa629e2d8&v=4" style="height: 32px; border-radius: 100%;"></a>
<a href="https://github.com/cmarqu"><img alt="cmarqu" src="https://avatars.githubusercontent.com/u/360986?v=4" style="height: 32px; border-radius: 100%;"></a>
<a href="https://github.com/kolenaIO"><img alt="kolenaIO" src="https://avatars.githubusercontent.com/u/77010818?v=4" style="height: 32px; border-radius: 100%;"></a>
<a href="https://github.com/ramnes"><img alt="ramnes" src="https://avatars.githubusercontent.com/u/835072?u=3fca03c3ba0051e2eb652b1def2188a94d1e1dc2&v=4" style="height: 32px; border-radius: 100%;"></a>
<a href="https://github.com/machow"><img alt="machow" src="https://avatars.githubusercontent.com/u/2574498?u=c41e3d2f758a05102d8075e38d67b9c17d4189d7&v=4" style="height: 32px; border-radius: 100%;"></a>
<a href="https://github.com/BenHammersley"><img alt="BenHammersley" src="https://avatars.githubusercontent.com/u/99436?u=4499a7b507541045222ee28ae122dbe3c8d08ab5&v=4" style="height: 32px; border-radius: 100%;"></a>
<a href="https://github.com/trevorWieland"><img alt="trevorWieland" src="https://avatars.githubusercontent.com/u/28811461?u=74cc0e3756c1d4e3d66b5c396e1d131ea8a10472&v=4" style="height: 32px; border-radius: 100%;"></a>
<a href="https://github.com/MarcoGorelli"><img alt="MarcoGorelli" src="https://avatars.githubusercontent.com/u/33491632?u=7de3a749cac76a60baca9777baf71d043a4f884d&v=4" style="height: 32px; border-radius: 100%;"></a>
<a href="https://github.com/analog-cbarber"><img alt="analog-cbarber" src="https://avatars.githubusercontent.com/u/7408243?u=fe0e7bf2882d1c9c901a341c2502e1518466527a&v=4" style="height: 32px; border-radius: 100%;"></a>
<a href="https://github.com/OdinManiac"><img alt="OdinManiac" src="https://avatars.githubusercontent.com/u/22727172?u=36ab20970f7f52ae8e7eb67b7fcf491fee01ac22&v=4" style="height: 32px; border-radius: 100%;"></a>
<a href="https://github.com/rstudio-sponsorship"><img alt="rstudio-sponsorship" src="https://avatars.githubusercontent.com/u/58949051?u=0c471515dd18111be30dfb7669ed5e778970959b&v=4" style="height: 32px; border-radius: 100%;"></a>
<a href="https://github.com/schlich"><img alt="schlich" src="https://avatars.githubusercontent.com/u/21191435?u=6f1240adb68f21614d809ae52d66509f46b1e877&v=4" style="height: 32px; border-radius: 100%;"></a>
<a href="https://github.com/butterlyn"><img alt="butterlyn" src="https://avatars.githubusercontent.com/u/53323535?v=4" style="height: 32px; border-radius: 100%;"></a>
<a href="https://github.com/livingbio"><img alt="livingbio" src="https://avatars.githubusercontent.com/u/10329983?v=4" style="height: 32px; border-radius: 100%;"></a>
<a href="https://github.com/NemetschekAllplan"><img alt="NemetschekAllplan" src="https://avatars.githubusercontent.com/u/912034?v=4" style="height: 32px; border-radius: 100%;"></a>
<a href="https://github.com/EricJayHartman"><img alt="EricJayHartman" src="https://avatars.githubusercontent.com/u/9259499?u=7e58cc7ec0cd3e85b27aec33656aa0f6612706dd&v=4" style="height: 32px; border-radius: 100%;"></a>
<a href="https://github.com/15r10nk"><img alt="15r10nk" src="https://avatars.githubusercontent.com/u/44680962?u=f04826446ff165742efa81e314bd03bf1724d50e&v=4" style="height: 32px; border-radius: 100%;"></a>
<a href="https://github.com/activeloopai"><img alt="activeloopai" src="https://avatars.githubusercontent.com/u/34816118?v=4" style="height: 32px; border-radius: 100%;"></a>
<a href="https://github.com/roboflow"><img alt="roboflow" src="https://avatars.githubusercontent.com/u/53104118?v=4" style="height: 32px; border-radius: 100%;"></a>
<a href="https://github.com/cmclaughlin"><img alt="cmclaughlin" src="https://avatars.githubusercontent.com/u/1061109?u=ddf6eec0edd2d11c980f8c3aa96e3d044d4e0468&v=4" style="height: 32px; border-radius: 100%;"></a>
<a href="https://github.com/RapidataAI"><img alt="RapidataAI" src="https://avatars.githubusercontent.com/u/104209891?v=4" style="height: 32px; border-radius: 100%;"></a>
<a href="https://github.com/rodolphebarbanneau"><img alt="rodolphebarbanneau" src="https://avatars.githubusercontent.com/u/46493454?u=6c405452a40c231cdf0b68e97544e07ee956a733&v=4" style="height: 32px; border-radius: 100%;"></a>
<a href="https://github.com/theSymbolSyndicate"><img alt="theSymbolSyndicate" src="https://avatars.githubusercontent.com/u/111542255?v=4" style="height: 32px; border-radius: 100%;"></a>
<a href="https://github.com/blakeNaccarato"><img alt="blakeNaccarato" src="https://avatars.githubusercontent.com/u/20692450?u=bb919218be30cfa994514f4cf39bb2f7cf952df4&v=4" style="height: 32px; border-radius: 100%;"></a>
<a href="https://github.com/ChargeStorm"><img alt="ChargeStorm" src="https://avatars.githubusercontent.com/u/26000165?v=4" style="height: 32px; border-radius: 100%;"></a>
<a href="https://github.com/Cusp-AI"><img alt="Cusp-AI" src="https://avatars.githubusercontent.com/u/178170649?v=4" style="height: 32px; border-radius: 100%;"></a>
</p></div>


*And 4 more private sponsor(s).*

<!-- sponsors-end -->
