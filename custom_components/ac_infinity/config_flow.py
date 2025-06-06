"""Config flow for ac_infinity."""
from __future__ import annotations

import logging
from typing import Any

from ac_infinity_ble import ACInfinityController, DeviceInfo
from ac_infinity_ble.protocol import parse_manufacturer_data
from ac_infinity_ble.const import MANUFACTURER_ID
import voluptuous as vol

from homeassistant import config_entries
from homeassistant.components.bluetooth import (
    BluetoothServiceInfoBleak,
    async_discovered_service_info,
)
from homeassistant.const import CONF_ADDRESS, CONF_SERVICE_DATA
from homeassistant.data_entry_flow import FlowResult

from .const import BLEAK_EXCEPTIONS, DOMAIN


_LOGGER = logging.getLogger(__name__)


class ConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for AC Infinity Bluetooth."""

    VERSION = 1

    def __init__(self) -> None:
        """Initialize the config flow."""
        self._discovery_info: BluetoothServiceInfoBleak | None = None
        self._discovered_devices: dict[str, BluetoothServiceInfoBleak] = {}

    async def async_step_bluetooth(
        self, discovery_info: BluetoothServiceInfoBleak
    ) -> FlowResult:
        """Handle the bluetooth discovery step."""
        await self.async_set_unique_id(discovery_info.address)
        self._abort_if_unique_id_configured()
        self._discovery_info = discovery_info
        device: DeviceInfo = parse_manufacturer_data(
            discovery_info.advertisement.manufacturer_data[MANUFACTURER_ID]
        )
        self.context["title_placeholders"] = {"name": device.name}
        return await self.async_step_user()

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Handle the user step to pick discovered device."""
        errors: dict[str, str] = {}

        if user_input is not None:
            address = user_input[CONF_ADDRESS]
            discovery_info = self._discovered_devices[address]
            await self.async_set_unique_id(
                discovery_info.address, raise_on_progress=False
            )
            self._abort_if_unique_id_configured()
            controller = ACInfinityController(
                discovery_info.device, advertisement_data=discovery_info.advertisement
            )
            try:
                await controller.update()
            except BLEAK_EXCEPTIONS:
                errors["base"] = "cannot_connect"
            except Exception:  # pylint: disable=broad-except
                _LOGGER.exception("Unexpected error")
                errors["base"] = "unknown"
            else:
                await controller.stop()
                return self.async_create_entry(
                    title=controller.name,
                    data={
                        CONF_ADDRESS: discovery_info.address,
                        CONF_SERVICE_DATA: parse_manufacturer_data(
                            discovery_info.advertisement.manufacturer_data[
                                MANUFACTURER_ID
                            ]
                        ),
                    },
                )

        if discovery := self._discovery_info:
            self._discovered_devices[discovery.address] = discovery
        else:
            current_addresses = self._async_current_ids()
            for discovery in async_discovered_service_info(self.hass):
                if (
                    discovery.address in current_addresses
                    or discovery.address in self._discovered_devices
                ):
                    continue
                self._discovered_devices[discovery.address] = discovery

        if not self._discovered_devices:
            return self.async_abort(reason="no_devices_found")

        devices = {}
        _LOGGER.debug(f"self._discovered_devices: {self._discovered_devices}")
        for service_info in self._discovered_devices.values():
            _LOGGER.debug(f"service_info: {service_info.advertisement.manufacturer_data}")
            try:
                device = parse_manufacturer_data(
                    service_info.advertisement.manufacturer_data[MANUFACTURER_ID]
                )
                devices[service_info.address] = f"{device.name} ({service_info.address})"
            except KeyError:
                # Discovered device is not an AC Infinity device
                pass

        data_schema = vol.Schema(
            {
                vol.Required(CONF_ADDRESS): vol.In(devices),
            }
        )
        return self.async_show_form(
            step_id="user",
            data_schema=data_schema,
            errors=errors,
        )
