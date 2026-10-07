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

"""Tests for arbitrary calls and plugin interface discovery."""

from __future__ import annotations

import xml.etree.ElementTree as ET
from functools import partial

import dbus
import pytest

from terminator_dbus import BUS_PATH, Terminator, TerminatorError
from tests.test_client import INTERFACE, RecordedCall, RecordingBus, RecordingProxy

PLUGIN_INTERFACE = "net.tenshu.Terminator2.Devboard"
PLUGIN_PATH = f"{BUS_PATH}/Devboard"
INTROSPECTABLE = "org.freedesktop.DBus.Introspectable"


class RoutingBus(RecordingBus):
    """Route each object path to the proxy configured for that object."""

    def __init__(self, proxies: dict[str, RecordingProxy]) -> None:
        """Keep the per-object proxies and the connection request log."""
        super().__init__(RecordingProxy())
        self.proxies = proxies

    def get_object(self, bus_name: str, object_path: str, *, introspect: bool = True) -> RecordingProxy:
        """Record an object request and return that object's test proxy."""
        self.requests.append((bus_name, object_path, introspect))
        return self.proxies.get(object_path, self.proxy)


def test_generic_plugin_call_preserves_typed_results() -> None:
    """Send an explicit signature to a plugin and keep its original D-Bus result."""
    proxy = RecordingProxy()
    result = dbus.Struct((dbus.String("created"), dbus.Boolean(1)))
    proxy.results["create"] = result
    bus = RoutingBus({PLUGIN_PATH: proxy})
    client = Terminator(bus=bus, bus_name=INTERFACE)  # ty: ignore[invalid-argument-type]
    identifier = dbus.UInt64(2**40)

    returned = client.call(
        "create",
        identifier,
        {},
        interface=PLUGIN_INTERFACE,
        object_path=PLUGIN_PATH,
        signature="ta{ss}",
    )

    assert returned is result
    assert proxy.calls == [RecordedCall("create", PLUGIN_INTERFACE, (identifier, {}), "ta{ss}")]
    assert bus.requests[-1] == (INTERFACE, PLUGIN_PATH, False)


def test_generic_call_uses_the_builtin_interface_by_default() -> None:
    """Route an arbitrary call to the built-in object unless another target is supplied."""
    proxy = RecordingProxy()
    proxy.results["get_window"] = dbus.String("urn:uuid:window")
    bus = RecordingBus(proxy)
    client = Terminator(bus=bus, bus_name=INTERFACE)  # ty: ignore[invalid-argument-type]

    result = client.call("get_window", "urn:uuid:source", signature="v")

    assert result == "urn:uuid:window"
    assert proxy.calls == [RecordedCall("get_window", INTERFACE, ("urn:uuid:source",), "v")]
    assert bus.requests == [(INTERFACE, BUS_PATH, False)]


def test_generic_call_without_a_signature_enables_introspection() -> None:
    """Let the proxy obtain a plugin method's signature through introspection."""
    proxy = RecordingProxy()
    proxy.results["project_split"] = dbus.String("urn:uuid:created")
    bus = RoutingBus({PLUGIN_PATH: proxy})
    client = Terminator(bus=bus, bus_name=INTERFACE)  # ty: ignore[invalid-argument-type]

    result = client.call(
        "project_split",
        "urn:uuid:source",
        "/repo",
        interface=PLUGIN_INTERFACE,
        object_path=PLUGIN_PATH,
    )

    assert result == "urn:uuid:created"
    assert proxy.calls == [RecordedCall("project_split", PLUGIN_INTERFACE, ("urn:uuid:source", "/repo"), None)]
    assert bus.requests[-1] == (INTERFACE, PLUGIN_PATH, True)


def test_generic_builtin_creation_errors_are_normalized() -> None:
    """Keep the built-in creation error behavior when using a generic call."""
    proxy = RecordingProxy()
    proxy.results["new_tab"] = dbus.String("ERROR: No UUID specified")
    bus = RecordingBus(proxy)
    client = Terminator(bus=bus, bus_name=INTERFACE)  # ty: ignore[invalid-argument-type]

    with pytest.raises(TerminatorError, match="new_tab: ERROR: No UUID specified"):
        client.call("new_tab", "", signature="v")


@pytest.mark.parametrize(("object_path", "interface"), [(BUS_PATH, PLUGIN_INTERFACE), (PLUGIN_PATH, INTERFACE)])
def test_plugin_methods_with_builtin_names_preserve_error_text(object_path: str, interface: str) -> None:
    """Keep plugin results even when a method name and result resemble a built-in error."""
    proxy = RecordingProxy()
    text = dbus.String("ERROR: a plugin's display text")
    proxy.results["new_tab"] = text
    bus = RoutingBus({object_path: proxy})
    client = Terminator(bus=bus, bus_name=INTERFACE)  # ty: ignore[invalid-argument-type]

    returned = client.call("new_tab", interface=interface, object_path=object_path, signature="")

    assert returned is text


def test_dynamic_interface_methods_share_a_proxy() -> None:
    """Use attribute calls on different interfaces at one object without reopening the proxy."""
    proxy = RecordingProxy()
    proxy.results.update({"project_split": "urn:uuid:created", "ping": "ready"})
    bus = RoutingBus({PLUGIN_PATH: proxy})
    client = Terminator(bus=bus, bus_name=INTERFACE)  # ty: ignore[invalid-argument-type]

    plugin = client.get_interface(PLUGIN_INTERFACE, object_path=PLUGIN_PATH)
    another_interface = client.get_interface(f"{PLUGIN_INTERFACE}.Status", object_path=PLUGIN_PATH)
    created = plugin.project_split("urn:uuid:source", "/repo")
    status = another_interface.ping()

    assert created == "urn:uuid:created"
    assert status == "ready"
    assert proxy.calls == [
        RecordedCall("project_split", PLUGIN_INTERFACE, ("urn:uuid:source", "/repo"), None),
        RecordedCall("ping", f"{PLUGIN_INTERFACE}.Status", (), None),
    ]
    assert bus.requests.count((INTERFACE, PLUGIN_PATH, True)) == 1


def test_dynamic_interface_can_skip_introspection() -> None:
    """Call a plugin with an explicit signature when its object cannot be introspected."""
    proxy = RecordingProxy()
    proxy.results["project_split"] = "urn:uuid:created"
    bus = RoutingBus({PLUGIN_PATH: proxy})
    client = Terminator(bus=bus, bus_name=INTERFACE)  # ty: ignore[invalid-argument-type]

    plugin = client.get_interface(PLUGIN_INTERFACE, object_path=PLUGIN_PATH, introspect=False)
    assert plugin.project_split("urn:uuid:source", "/repo", signature="ss") == "urn:uuid:created"

    assert bus.requests[-1] == (INTERFACE, PLUGIN_PATH, False)
    assert proxy.calls == [RecordedCall("project_split", PLUGIN_INTERFACE, ("urn:uuid:source", "/repo"), "ss")]


def test_discovery_finds_plugin_objects_and_returns_callable_interfaces() -> None:
    """Follow child paths and find a plugin alongside the built-in Terminator interface."""
    root = RecordingProxy()
    root.results["Introspect"] = '<node><node name="net/tenshu/Terminator2"/></node>'
    builtin = RecordingProxy()
    builtin.results["Introspect"] = f'<node><interface name="{INTERFACE}"/><node name="Devboard"/></node>'
    plugin = RecordingProxy()
    plugin.results["Introspect"] = (
        f'<node><interface name="{INTROSPECTABLE}"/><interface name="{PLUGIN_INTERFACE}"/></node>'
    )
    plugin.results["project_split"] = "urn:uuid:created"
    bus = RoutingBus({"/": root, BUS_PATH: builtin, PLUGIN_PATH: plugin})
    client = Terminator(bus=bus, bus_name=INTERFACE)  # ty: ignore[invalid-argument-type]

    discovered = client.discover_interfaces()
    created = discovered[PLUGIN_PATH][PLUGIN_INTERFACE].project_split("urn:uuid:source", "/repo")

    assert {path: set(interfaces) for path, interfaces in discovered.items()} == {
        BUS_PATH: {INTERFACE},
        PLUGIN_PATH: {INTROSPECTABLE, PLUGIN_INTERFACE},
    }
    assert created == "urn:uuid:created"
    assert plugin.calls[-1] == RecordedCall("project_split", PLUGIN_INTERFACE, ("urn:uuid:source", "/repo"), None)


def test_discovery_uses_inline_child_introspection() -> None:
    """Use complete child descriptions without requiring another Introspect call."""
    root = RecordingProxy()
    root.results["Introspect"] = f'<node><node name="plugin"><interface name="{PLUGIN_INTERFACE}"/></node></node>'
    plugin = RecordingProxy()
    plugin.results["ping"] = "ready"
    bus = RoutingBus({"/": root, "/plugin": plugin})
    client = Terminator(bus=bus, bus_name=INTERFACE)  # ty: ignore[invalid-argument-type]

    discovered = client.discover_interfaces()

    assert set(discovered) == {"/plugin"}
    assert set(discovered["/plugin"]) == {PLUGIN_INTERFACE}
    assert root.calls == [RecordedCall("Introspect", INTROSPECTABLE, (), "")]
    assert plugin.calls == []


def test_discovery_can_inspect_one_object_without_visiting_children() -> None:
    """Limit discovery to the requested object when recursive traversal is disabled."""
    proxy = RecordingProxy()
    proxy.results["Introspect"] = f'<node><interface name="{PLUGIN_INTERFACE}"/><node name="child"/></node>'
    bus = RoutingBus({PLUGIN_PATH: proxy})
    client = Terminator(bus=bus, bus_name=INTERFACE)  # ty: ignore[invalid-argument-type]

    discovered = client.discover_interfaces(PLUGIN_PATH, recursive=False)

    assert set(discovered) == {PLUGIN_PATH}
    assert set(discovered[PLUGIN_PATH]) == {PLUGIN_INTERFACE}
    assert all(path in {BUS_PATH, PLUGIN_PATH} for _, path, _ in bus.requests)


def test_discovery_rejects_invalid_introspection_xml() -> None:
    """Report a malformed remote description instead of returning incomplete discovery data."""
    proxy = RecordingProxy()
    proxy.results["Introspect"] = "not XML"
    bus = RoutingBus({"/": proxy})
    client = Terminator(bus=bus, bus_name=INTERFACE)  # ty: ignore[invalid-argument-type]

    with pytest.raises(ET.ParseError):
        client.discover_interfaces()


@pytest.mark.parametrize("operation", ["call", "proxy", "discover"])
def test_plugin_dbus_exceptions_propagate(operation: str) -> None:
    """Keep remote exceptions intact through generic calls, dynamic methods, and discovery."""
    failure = dbus.DBusException("Plugin unavailable")
    proxy = RecordingProxy()
    proxy.results.update({"project_split": failure, "Introspect": failure})
    bus = RoutingBus({PLUGIN_PATH: proxy})
    client = Terminator(bus=bus, bus_name=INTERFACE)  # ty: ignore[invalid-argument-type]

    if operation == "call":
        action = partial(
            client.call,
            "project_split",
            interface=PLUGIN_INTERFACE,
            object_path=PLUGIN_PATH,
            signature="",
        )
    elif operation == "proxy":
        action = client.get_interface(PLUGIN_INTERFACE, object_path=PLUGIN_PATH).project_split
    else:
        action = partial(client.discover_interfaces, PLUGIN_PATH)

    with pytest.raises(dbus.DBusException) as caught:
        action()

    assert caught.value is failure
