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
from typing import TYPE_CHECKING, Any, Final

import dbus

if TYPE_CHECKING:
    from collections.abc import Mapping

    from dbus.bus import BusConnection


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
        display: GDK display name. The current desktop display is used when
            this argument is not set.

    Returns:
        The display-specific name, or the base name when no display is known.
    """
    if display is None:
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


class Terminator:
    """Provide Python methods for Terminator's complete D-Bus interface.

    The client keeps one session-bus connection and one proxy. It sends known
    method signatures directly, so `dbus-python` does not need an
    introspection request before the first method call.

    Parameters:
        bus: An existing D-Bus connection. A session-bus connection is created
            when this argument is not set.
        display: GDK display name used to calculate Terminator's D-Bus name.
        bus_name: Exact D-Bus service name. Use this argument for a custom or
            already discovered Terminator service.

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
        self._interface = dbus.Interface(proxy, self.bus_name)

    @property
    def bus_name(self) -> str:
        """Return the D-Bus service and interface name used by this client."""
        return self._bus_name

    def _call(self, method_name: str, *args: object, signature: str) -> Any:
        method = self._interface.get_dbus_method(method_name)
        return method(*args, signature=signature)

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
        """Create a window and return its first terminal UUID."""
        return str(self._call("new_window", signature=""))

    def new_tab(self, uuid: str) -> str:
        """Create a tab beside a terminal and return the new terminal UUID.

        Parameters:
            uuid: UUID of a terminal in the target window.

        Returns:
            The new terminal UUID or an error string from Terminator.
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
            The new terminal UUID or an error string from Terminator.
        """
        return str(self._call("hsplit", uuid, _options(options), signature="vv"))

    def vsplit(self, uuid: str, options: Mapping[str, str] | None = None) -> str:
        """Split a terminal vertically and return the new terminal UUID.

        Parameters:
            uuid: Target terminal UUID.
            options: Optional `execute` command and `title` for the new
                terminal.

        Returns:
            The new terminal UUID or an error string from Terminator.
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
