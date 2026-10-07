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

import hashlib
import os
import xml.etree.ElementTree as ET
from typing import TYPE_CHECKING, Any, Final

import dbus

from terminator_dbus._internal.extension import TerminalExtension as _TerminalExtension

if TYPE_CHECKING:
    from collections.abc import Mapping

    from dbus.bus import BusConnection
    from dbus.proxies import ProxyObject


BUS_BASE: Final = "net.tenshu.Terminator2"
"""Base name of Terminator's D-Bus service and interface."""

BUS_PATH: Final = "/net/tenshu/Terminator2"
"""Object path of Terminator's D-Bus service."""


def _default_display() -> str | None:
    backend = os.environ.get("GDK_BACKEND", "").split(",", maxsplit=1)[0]
    if backend == "wayland":
        return os.environ.get("WAYLAND_DISPLAY") or os.environ.get("DISPLAY")
    if backend == "x11":
        return os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY")
    if os.environ.get("XDG_SESSION_TYPE") == "wayland":
        return os.environ.get("WAYLAND_DISPLAY") or os.environ.get("DISPLAY")
    return os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY")


def get_bus_name(display: str | None = None) -> str:
    """Return the D-Bus service and interface name for a display.

    Terminator appends the MD5 digest of its GDK display name to
    `net.tenshu.Terminator2`. It removes the screen suffix before it creates
    the digest. For example, `:0` and `:0.0` use the same D-Bus name.

    Parameters:
        display: GDK display name. When unset, `TERMINATOR_DBUS_NAME` is used
            if non-empty, followed by the current desktop display.

    Returns:
        The environment's service name, the display-specific name, or the
        base name when no display is known.
    """
    if display is None:
        if bus_name := os.environ.get("TERMINATOR_DBUS_NAME"):
            return bus_name
        display = _default_display()
    if not display:
        return BUS_BASE

    display_without_screen = display.partition(".")[0]
    display_digest = hashlib.md5(display_without_screen.encode(), usedforsecurity=False).hexdigest()
    return f"{BUS_BASE}{display_digest}"


def _options(values: Mapping[str, str] | None = None) -> dbus.Dictionary:
    return dbus.Dictionary({} if values is None else values, signature="ss")


def _optional_string(value: object) -> str | None:
    if value is None:
        return None
    return str(value)


class TerminatorError(dbus.DBusException):
    """Report a terminal creation failure returned by Terminator.

    This exception is also caught by handlers for `dbus.DBusException`.

    Parameters:
        method: D-Bus method that failed.
        message: Original response from Terminator, including the `ERROR:` prefix.

    """

    method: str
    """D-Bus method that failed."""

    message: str
    """Original response from Terminator, including the `ERROR:` prefix."""

    def __init__(self, method: str, message: str) -> None:
        """Keep the failed method and original response with the exception."""
        super().__init__(f"{method}: {message}")
        self.method = method
        self.message = message


class Terminator:
    """Provide Python methods for Terminator's complete D-Bus interface.

    The client keeps one session-bus connection and reuses proxies. Built-in
    methods send known signatures directly, so they do not need introspection.
    Plugin interfaces can be discovered and called through dynamic proxies
    or the generic `call` method.

    Parameters:
        bus: An existing D-Bus connection. A session-bus connection is created
            when this argument is not set.
        display: GDK display name used to calculate Terminator's D-Bus name.
            Overrides `TERMINATOR_DBUS_NAME` when specified.
        bus_name: Exact D-Bus service name. Overrides `TERMINATOR_DBUS_NAME`
            when specified. When both connection settings are unset, a
            non-empty `TERMINATOR_DBUS_NAME` selects the service before the
            current desktop display.

    Raises:
        ValueError: Both `display` and `bus_name` were specified.
        dbus.DBusException: The session bus or Terminator service is not
            available.
    """

    def __init__(
        self,
        *,
        bus: BusConnection | None = None,
        display: str | None = None,
        bus_name: str | None = None,
    ) -> None:
        if display is not None and bus_name is not None:
            raise ValueError("display and bus_name cannot both be specified")

        self._bus_name = get_bus_name(display) if bus_name is None else bus_name
        self._bus = dbus.SessionBus() if bus is None else bus
        proxy = self._bus.get_object(self.bus_name, BUS_PATH, introspect=False)
        self._proxies: dict[tuple[str, bool], ProxyObject] = {(BUS_PATH, False): proxy}
        self._interface = dbus.Interface(proxy, self.bus_name)

    @property
    def bus_name(self) -> str:
        """Return the D-Bus service and interface name used by this client."""
        return self._bus_name

    @property
    def extension(self) -> _TerminalExtension:
        """Return a typed client for the bundled terminal and layout extension."""
        return _TerminalExtension(self)

    def _call(self, method_name: str, *args: object, signature: str) -> Any:
        return self.call(method_name, *args, signature=signature)

    def call(
        self,
        method_name: str,
        *args: object,
        interface: str | None = None,
        object_path: str = BUS_PATH,
        signature: str | None = None,
    ) -> Any:
        """Call an arbitrary method on Terminator or a plugin's D-Bus interface.

        Parameters:
            method_name: D-Bus method to call.
            *args: Positional arguments sent to the method.
            interface: D-Bus interface name. Defaults to Terminator's built-in interface.
            object_path: D-Bus object path exported by the selected Terminator service.
            signature: Input signature. When unset, the proxy uses introspection
                to find the signature. An empty string declares a method with no inputs.

        Returns:
            The original D-Bus result. Plugin results are not converted or
            checked for error strings.

        Raises:
            dbus.DBusException: The object, interface, or method is unavailable,
                or the remote method raises an exception.
            TerminatorError: A built-in terminal creation method returned an
                `ERROR:` response.
        """
        interface_name = self.bus_name if interface is None else interface
        builtin = object_path == BUS_PATH and interface_name == self.bus_name
        if builtin and signature is not None:
            target = self._interface
        else:
            target = self.get_interface(interface_name, object_path=object_path, introspect=signature is None)
        method = target.get_dbus_method(method_name)
        result = method(*args, signature=signature)
        if (
            builtin
            and method_name in {"new_window", "new_tab", "hsplit", "vsplit"}
            and isinstance(result, str)
            and result.startswith("ERROR:")
        ):
            raise TerminatorError(method_name, result)
        return result

    def get_interface(self, interface: str, *, object_path: str = BUS_PATH, introspect: bool = True) -> dbus.Interface:
        """Create a dynamic proxy for an interface exported by Terminator or a plugin.

        Methods are available as attributes on the returned interface. For
        example, a plugin that exports `new_tab` can be called with
        `plugin.new_tab(uuid, command)`. These calls return raw D-Bus results.

        Parameters:
            interface: D-Bus interface name.
            object_path: D-Bus object path exported by the selected Terminator service.
            introspect: Use introspection to find method signatures. Disable
                this when every call supplies its own signature.

        Returns:
            A `dbus.Interface` using the client's existing bus connection.
            Proxies for the same path and introspection setting are reused.

        Raises:
            dbus.DBusException: The Terminator service is unavailable.
        """
        key = object_path, introspect
        if key not in self._proxies:
            self._proxies[key] = self._bus.get_object(self.bus_name, object_path, introspect=introspect)
        return dbus.Interface(self._proxies[key], interface)

    def discover_interfaces(
        self,
        object_path: str = "/",
        *,
        recursive: bool = True,
    ) -> dict[str, dict[str, dbus.Interface]]:
        """Discover exported D-Bus interfaces and create their dynamic proxies.

        Discovery reports interfaces exported by the running Terminator
        process. It does not list installed or disabled Python plugins.
        Standard D-Bus and built-in Terminator interfaces are included.

        Parameters:
            object_path: Object path where discovery starts. The root path
                finds plugin objects anywhere in the selected service.
            recursive: Follow child objects described by introspection.

        Returns:
            Object paths mapped to interface names and their dynamic proxies.
            Nodes with no interfaces are omitted.

        Raises:
            dbus.DBusException: An object cannot be introspected, or the
                Terminator service is unavailable.
            xml.etree.ElementTree.ParseError: An object returns invalid XML.
        """
        discovered: dict[str, dict[str, dbus.Interface]] = {}
        pending: list[tuple[str, ET.Element | None]] = [(object_path, None)]
        visited: set[str] = set()
        while pending:
            path, node = pending.pop()
            if path in visited:
                continue
            visited.add(path)
            if node is None:
                description = self.call(
                    "Introspect",
                    interface="org.freedesktop.DBus.Introspectable",
                    object_path=path,
                    signature="",
                )
                # The selected Terminator process supplies the introspection XML.
                node = ET.fromstring(str(description))  # noqa: S314
            interfaces = {
                element.attrib["name"]: self.get_interface(element.attrib["name"], object_path=path)
                for element in node.findall("interface")
            }
            if interfaces:
                discovered[path] = interfaces
            if recursive:
                for child in reversed(node.findall("node")):
                    child_path = f"{path.rstrip('/')}/{child.attrib['name']}"
                    # A child with contents includes its full introspection description.
                    pending.append((child_path, child if len(child) else None))
        return discovered

    def new_window_cmdline(self, options: Mapping[str, str]) -> None:
        """Create a window from serialized Terminator command-line options.

        Parameters:
            options: Complete option mapping produced by Terminator's command
                line parser. Keys and values must be strings.
        """
        self._call("new_window_cmdline", _options(options), signature="a{ss}")

    def new_tab_cmdline(self, options: Mapping[str, str]) -> None:
        """Create a tab from serialized Terminator command-line options.

        Parameters:
            options: Complete option mapping produced by Terminator's command
                line parser. Keys and values must be strings.
        """
        self._call("new_tab_cmdline", _options(options), signature="a{ss}")

    def toggle_visibility_cmdline(self, options: Mapping[str, str]) -> None:
        """Toggle the visibility of every Terminator window.

        Parameters:
            options: Serialized command-line options. Terminator currently
                ignores the values.
        """
        self._call("toggle_visibility_cmdline", _options(options), signature="a{ss}")

    def unhide_cmdline(self, options: Mapping[str, str]) -> None:
        """Show every hidden Terminator window.

        Parameters:
            options: Serialized command-line options. Terminator currently
                ignores the values.
        """
        self._call("unhide_cmdline", _options(options), signature="a{ss}")

    def new_window(self) -> str:
        """Create a window and return its first terminal UUID.

        Raises:
            TerminatorError: Terminator returned an `ERROR:` response.
        """
        return str(self._call("new_window", signature=""))

    def new_tab(self, uuid: str) -> str:
        """Create a tab beside a terminal and return the new terminal UUID.

        Parameters:
            uuid: UUID of a terminal in the target window.

        Returns:
            The new terminal UUID.

        Raises:
            TerminatorError: Terminator returned an `ERROR:` response.
        """
        return str(self._call("new_tab", uuid, signature="v"))

    def reload_configuration(self) -> None:
        """Reload the configuration of all terminals."""
        self._call("reload_configuration", signature="")

    def bg_img_all(self, options: Mapping[str, str]) -> None:
        """Set the background image of all terminals.

        Parameters:
            options: Mapping with the image path in the `file` key.
        """
        self._call("bg_img_all", _options(options), signature="v")

    def bg_img(self, uuid: str, options: Mapping[str, str]) -> None:
        """Set the background image of one terminal.

        Parameters:
            uuid: Target terminal UUID.
            options: Mapping with the image path in the `file` key.
        """
        self._call("bg_img", uuid, _options(options), signature="vv")

    def hsplit(self, uuid: str, options: Mapping[str, str] | None = None) -> str:
        """Split a terminal horizontally and return the new terminal UUID.

        Parameters:
            uuid: Target terminal UUID.
            options: Optional `execute` command and `title` for the new
                terminal.

        Returns:
            The new terminal UUID.

        Raises:
            TerminatorError: Terminator returned an `ERROR:` response.
        """
        return str(self._call("hsplit", uuid, _options(options), signature="vv"))

    def vsplit(self, uuid: str, options: Mapping[str, str] | None = None) -> str:
        """Split a terminal vertically and return the new terminal UUID.

        Parameters:
            uuid: Target terminal UUID.
            options: Optional `execute` command and `title` for the new
                terminal.

        Returns:
            The new terminal UUID.

        Raises:
            TerminatorError: Terminator returned an `ERROR:` response.
        """
        return str(self._call("vsplit", uuid, _options(options), signature="vv"))

    def get_terminals(self) -> list[str]:
        """Return the UUID of every terminal."""
        return [str(uuid) for uuid in self._call("get_terminals", signature="")]

    def get_focused_terminal(self) -> str | None:
        """Return the focused terminal UUID, if a terminal has focus."""
        return _optional_string(self._call("get_focused_terminal", signature=""))

    def get_window(self, uuid: str) -> str:
        """Return the parent window UUID of a terminal.

        Parameters:
            uuid: Target terminal UUID.
        """
        return str(self._call("get_window", uuid, signature="v"))

    def get_window_title(self, uuid: str) -> str:
        """Return the parent window title of a terminal.

        Parameters:
            uuid: Target terminal UUID.
        """
        return str(self._call("get_window_title", uuid, signature="v"))

    def get_tab(self, uuid: str) -> str | None:
        """Return the parent tab identifier of a terminal.

        Terminator does not assign UUIDs to tabs. It currently returns an
        empty string for a terminal in a notebook and no value otherwise.

        Parameters:
            uuid: Target terminal UUID.
        """
        return _optional_string(self._call("get_tab", uuid, signature="v"))

    def get_tab_title(self, uuid: str) -> str | None:
        """Return the parent tab title of a terminal, if it has one.

        Parameters:
            uuid: Target terminal UUID.
        """
        return _optional_string(self._call("get_tab_title", uuid, signature="v"))

    def set_tab_title(self, uuid: str, options: Mapping[str, str]) -> None:
        """Set a terminal's parent tab title.

        Parameters:
            uuid: Target terminal UUID.
            options: Mapping with the new title in the `tab-title` key.
        """
        self._call("set_tab_title", uuid, _options(options), signature="vv")

    def switch_profile(self, uuid: str, options: Mapping[str, str]) -> None:
        """Switch one terminal to a profile.

        Parameters:
            uuid: Target terminal UUID.
            options: Mapping with the profile name in the `profile` key.
        """
        self._call("switch_profile", uuid, _options(options), signature="vv")

    def switch_profile_all(self, options: Mapping[str, str]) -> None:
        """Switch all terminals to a profile.

        Parameters:
            options: Mapping with the profile name in the `profile` key.
        """
        self._call("switch_profile_all", _options(options), signature="v")
