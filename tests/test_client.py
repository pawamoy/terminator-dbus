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

"""Tests for the Terminator D-Bus client."""

from __future__ import annotations

import inspect
from dataclasses import dataclass
from typing import Any

import dbus
import pytest

from terminator_dbus import BUS_BASE, BUS_PATH, Terminator, get_bus_name

INTERFACE = "net.tenshu.Terminator2.test"


@dataclass(frozen=True)
class RecordedCall:
    """A D-Bus method call received by the test proxy."""

    method: str
    interface: str | None
    args: tuple[object, ...]
    signature: str | None


class RecordingProxy:
    """Record proxy calls and return configured D-Bus values."""

    def __init__(self) -> None:
        """Initialize an empty call log and result mapping."""
        self.calls: list[RecordedCall] = []
        self.results: dict[str, object] = {}

    def get_dbus_method(self, method: str, dbus_interface: str | None = None) -> Any:
        """Return a callable that records one remote method call."""

        def call(*args: object, **kwargs: object) -> object:
            signature = kwargs.pop("signature", None)
            assert not kwargs

            self.calls.append(
                RecordedCall(method, dbus_interface, args, signature if isinstance(signature, str) else None),
            )
            return self.results.get(method)

        return call


class RecordingBus:
    """Return a recording proxy and save the requested object details."""

    def __init__(self, proxy: RecordingProxy) -> None:
        """Store the proxy returned by each object request."""
        self.proxy = proxy
        self.requests: list[tuple[str, str, bool]] = []

    def get_object(self, bus_name: str, object_path: str, *, introspect: bool = True) -> RecordingProxy:
        """Record an object request and return the test proxy."""
        self.requests.append((bus_name, object_path, introspect))
        return self.proxy


def test_get_bus_name_for_x11_display() -> None:
    """Use the same name for all screens on one X11 display."""
    expected_name = f"{BUS_BASE}1a9d5db22c73a993ff0b42f64b396873"

    assert get_bus_name(":0") == expected_name
    assert get_bus_name(":0.0") == expected_name


def test_get_bus_name_for_wayland_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    """Use the Wayland display when GDK runs on Wayland."""
    monkeypatch.setenv("DISPLAY", ":0")
    monkeypatch.setenv("WAYLAND_DISPLAY", "wayland-0")
    monkeypatch.setenv("XDG_SESSION_TYPE", "wayland")
    monkeypatch.delenv("GDK_BACKEND", raising=False)

    assert get_bus_name() == f"{BUS_BASE}5ef4b219e3b005583550f2b0f9f990c3"


def test_get_bus_name_without_a_display(monkeypatch: pytest.MonkeyPatch) -> None:
    """Use Terminator's base name when no desktop display is available."""
    for variable in ("DISPLAY", "WAYLAND_DISPLAY", "XDG_SESSION_TYPE", "GDK_BACKEND"):
        monkeypatch.delenv(variable, raising=False)

    assert get_bus_name() == BUS_BASE


def test_client_reuses_a_non_introspecting_proxy() -> None:
    """Open one proxy with the supplied connection and exact service name."""
    proxy = RecordingProxy()
    bus = RecordingBus(proxy)

    client = Terminator(bus=bus, bus_name=INTERFACE)  # ty: ignore[invalid-argument-type]

    assert client.bus_name == INTERFACE
    assert bus.requests == [(INTERFACE, BUS_PATH, False)]


def test_display_and_bus_name_are_mutually_exclusive() -> None:
    """Reject connection settings that select two different service names."""
    with pytest.raises(ValueError, match="display and bus_name"):
        Terminator(display=":0", bus_name=INTERFACE)


def test_exposes_every_terminator_dbus_method() -> None:
    """Expose each method decorated by Terminator's DBusService."""
    expected_methods = {
        "bg_img",
        "bg_img_all",
        "get_focused_terminal",
        "get_tab",
        "get_tab_title",
        "get_terminals",
        "get_window",
        "get_window_title",
        "hsplit",
        "new_tab",
        "new_tab_cmdline",
        "new_window",
        "new_window_cmdline",
        "reload_configuration",
        "set_tab_title",
        "switch_profile",
        "switch_profile_all",
        "toggle_visibility_cmdline",
        "unhide_cmdline",
        "vsplit",
    }
    public_methods = {
        name
        for name, member in inspect.getmembers(Terminator, predicate=inspect.isfunction)
        if not name.startswith("_")
    }

    assert public_methods == expected_methods


def test_all_methods_use_the_upstream_wire_signatures() -> None:
    """Call all methods with native values and preserve Terminator's wire API."""
    proxy = RecordingProxy()
    proxy.results.update(
        {
            "new_window": dbus.String("urn:uuid:new-window-terminal"),
            "new_tab": dbus.String("urn:uuid:new-tab-terminal"),
            "hsplit": dbus.String("urn:uuid:horizontal-terminal"),
            "vsplit": dbus.String("urn:uuid:vertical-terminal"),
            "get_terminals": dbus.Array(
                [dbus.String("urn:uuid:first"), dbus.String("urn:uuid:second")],
                signature="s",
            ),
            "get_focused_terminal": None,
            "get_window": dbus.String("urn:uuid:window"),
            "get_window_title": dbus.String("Development"),
            "get_tab": dbus.String(""),
            "get_tab_title": dbus.String("Editor"),
        },
    )
    bus = RecordingBus(proxy)
    client = Terminator(bus=bus, bus_name=INTERFACE)  # ty: ignore[invalid-argument-type]

    # Send all four command-line operations with their declared dictionary signature.
    assert client.new_window_cmdline({"layout": "default"}) is None
    assert client.new_tab_cmdline({"profile": "work"}) is None
    assert client.toggle_visibility_cmdline({}) is None
    assert client.unhide_cmdline({}) is None

    # Create windows, tabs, and splits. The empty split options select Terminator's basic split path.
    assert client.new_window() == "urn:uuid:new-window-terminal"
    assert client.new_tab("urn:uuid:target") == "urn:uuid:new-tab-terminal"
    assert client.reload_configuration() is None
    assert client.bg_img_all({"file": "/images/background.png"}) is None
    assert client.bg_img("urn:uuid:target", {"file": "/images/one.png"}) is None
    assert client.hsplit("urn:uuid:target") == "urn:uuid:horizontal-terminal"
    assert client.vsplit("urn:uuid:target", {"execute": "htop", "title": "Monitor"}) == "urn:uuid:vertical-terminal"

    # Read every terminal, window, and tab value as a native Python value.
    assert client.get_terminals() == ["urn:uuid:first", "urn:uuid:second"]
    assert client.get_focused_terminal() is None
    assert client.get_window("urn:uuid:target") == "urn:uuid:window"
    assert client.get_window_title("urn:uuid:target") == "Development"
    assert client.get_tab("urn:uuid:target") == ""
    assert client.get_tab_title("urn:uuid:target") == "Editor"

    # Change tab and profile settings with the option keys expected by Terminator.
    assert client.set_tab_title("urn:uuid:target", {"tab-title": "Shell"}) is None
    assert client.switch_profile("urn:uuid:target", {"profile": "work"}) is None
    assert client.switch_profile_all({"profile": "default"}) is None

    assert proxy.calls == [
        RecordedCall("new_window_cmdline", INTERFACE, ({"layout": "default"},), "a{ss}"),
        RecordedCall("new_tab_cmdline", INTERFACE, ({"profile": "work"},), "a{ss}"),
        RecordedCall("toggle_visibility_cmdline", INTERFACE, ({},), "a{ss}"),
        RecordedCall("unhide_cmdline", INTERFACE, ({},), "a{ss}"),
        RecordedCall("new_window", INTERFACE, (), ""),
        RecordedCall("new_tab", INTERFACE, ("urn:uuid:target",), "v"),
        RecordedCall("reload_configuration", INTERFACE, (), ""),
        RecordedCall("bg_img_all", INTERFACE, ({"file": "/images/background.png"},), "v"),
        RecordedCall("bg_img", INTERFACE, ("urn:uuid:target", {"file": "/images/one.png"}), "vv"),
        RecordedCall("hsplit", INTERFACE, ("urn:uuid:target", {}), "vv"),
        RecordedCall("vsplit", INTERFACE, ("urn:uuid:target", {"execute": "htop", "title": "Monitor"}), "vv"),
        RecordedCall("get_terminals", INTERFACE, (), ""),
        RecordedCall("get_focused_terminal", INTERFACE, (), ""),
        RecordedCall("get_window", INTERFACE, ("urn:uuid:target",), "v"),
        RecordedCall("get_window_title", INTERFACE, ("urn:uuid:target",), "v"),
        RecordedCall("get_tab", INTERFACE, ("urn:uuid:target",), "v"),
        RecordedCall("get_tab_title", INTERFACE, ("urn:uuid:target",), "v"),
        RecordedCall("set_tab_title", INTERFACE, ("urn:uuid:target", {"tab-title": "Shell"}), "vv"),
        RecordedCall("switch_profile", INTERFACE, ("urn:uuid:target", {"profile": "work"}), "vv"),
        RecordedCall("switch_profile_all", INTERFACE, ({"profile": "default"},), "v"),
    ]

    # Type empty and non-empty option dictionaries so dbus-python can marshal both forms.
    calls_with_options = [call for call in proxy.calls if any(isinstance(arg, dbus.Dictionary) for arg in call.args)]
    assert len(calls_with_options) == 11
    for call in calls_with_options:
        options = next(arg for arg in call.args if isinstance(arg, dbus.Dictionary))
        assert options.signature == "ss"
