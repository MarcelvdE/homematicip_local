"""Test control_unit helper functions."""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from aiohomematic.const import SystemInformation
from aiohomematic.exceptions import NoConnectionException
from custom_components.homematicip_local.const import DOMAIN as HMIP_DOMAIN
from custom_components.homematicip_local.control_unit import (
    BaseControlUnit,
    ControlConfig,
    validate_config_and_get_system_information,
)
from homeassistant.core import HomeAssistant

from tests import const

# pylint: disable=protected-access


class TestValidateConfigAndGetSystemInformation:
    """Cover cleanup of the temporary control unit used for config validation."""

    async def test_validate_config_and_get_system_information_stops_temp_control_unit_on_success(self) -> None:
        """A successful validation call must still stop the temporary control unit."""
        system_information = SystemInformation(
            available_interfaces=[],
            auth_enabled=False,
            https_redirect_enabled=False,
            serial=const.SERIAL,
        )
        control_unit_temp = MagicMock()
        control_unit_temp.central.validate_config_and_get_system_information = AsyncMock(
            return_value=system_information
        )
        control_unit_temp.stop_central = AsyncMock()

        control_config = MagicMock(spec=ControlConfig)
        control_config.create_control_unit_temp = AsyncMock(return_value=control_unit_temp)

        result = await validate_config_and_get_system_information(control_config=control_config)

        assert result is system_information
        control_unit_temp.stop_central.assert_called_once()

    async def test_validate_config_and_get_system_information_stops_temp_control_unit_on_failure(self) -> None:
        """A failing validation call must not leak the temporary control unit either.

        Regression test: without a try/finally around the validation call, the
        temporary control unit's XML-RPC proxies and CommandThrottle worker tasks
        were never stopped, leaking them until Python's garbage collector happened
        to tear them down (surfacing as noisy "Task was destroyed but it is
        pending!" errors) - and keeping connections/sessions open against the CCU
        in the meantime.
        """
        control_unit_temp = MagicMock()
        control_unit_temp.central.validate_config_and_get_system_information = AsyncMock(
            side_effect=TimeoutError("CCU did not respond")
        )
        control_unit_temp.stop_central = AsyncMock()

        control_config = MagicMock(spec=ControlConfig)
        control_config.create_control_unit_temp = AsyncMock(return_value=control_unit_temp)

        with pytest.raises(TimeoutError):
            await validate_config_and_get_system_information(control_config=control_config)

        control_unit_temp.stop_central.assert_called_once()


class TestCheckInstanceNameIsUnique:
    """Cover the instance-name uniqueness check performed before creating a central."""

    def test_check_instance_name_is_unique_detects_duplicate_across_entries(
        self, hass: HomeAssistant, entry_data_v1: dict[str, Any]
    ) -> None:
        """A second config entry with the same instance_name must be detected as a duplicate.

        Regression test: the check used ``hasattr(entry.data, CONF_INSTANCE_NAME)`` to look
        for the key, but ``entry.data`` is a plain Mapping, not an object with that attribute
        as a Python attribute - ``hasattr`` was therefore always False, so a duplicate
        instance name across config entries was never detected.
        """
        other_entry = MockConfigEntry(
            entry_id="other_entry_id",
            domain=HMIP_DOMAIN,
            title=entry_data_v1["instance_name"],
            data=entry_data_v1,
        )
        other_entry.add_to_hass(hass)

        control_config = ControlConfig(hass=hass, entry_id=const.CONFIG_ENTRY_ID, data=entry_data_v1)

        assert control_config._check_instance_name_is_unique() is False

    def test_check_instance_name_is_unique_allows_distinct_names(
        self, hass: HomeAssistant, entry_data_v1: dict[str, Any]
    ) -> None:
        """A config entry with a different instance_name must not be flagged as a duplicate."""
        other_data = dict(entry_data_v1)
        other_data["instance_name"] = "some_other_instance"
        other_entry = MockConfigEntry(
            entry_id="other_entry_id",
            domain=HMIP_DOMAIN,
            title=other_data["instance_name"],
            data=other_data,
        )
        other_entry.add_to_hass(hass)

        control_config = ControlConfig(hass=hass, entry_id=const.CONFIG_ENTRY_ID, data=entry_data_v1)

        assert control_config._check_instance_name_is_unique() is True


class TestBaseControlUnitStartCentral:
    """Cover start_central()'s error propagation, which the background retry loop relies on."""

    async def test_start_central_propagates_base_homematic_exception(self) -> None:
        """A transient BaseHomematicException from central.start() must propagate to the caller.

        Regression test: start_central() used to catch BaseHomematicException itself and only
        log a warning, silently leaving the entry "loaded" with no devices and no retry. The
        background task in __init__.py now owns retry-with-backoff and needs the exception to
        surface.
        """
        control_config = MagicMock()
        control_config.instance_name = const.INSTANCE_NAME
        control_config.backup_directory = "backup_dir"
        control_config.disable_config_panel = False
        control_config.enable_light_last_brightness = False
        control_config.enable_mqtt = False
        control_config.enable_sub_devices = False
        control_config.mqtt_prefix = "homematicip"
        control_config.enable_system_notifications = True

        central = MagicMock()
        central.name = const.CENTRAL_NAME
        central.model = "CCU3"
        central.system_information.serial = const.SERIAL
        central.version = "1.0"
        central.start = AsyncMock(side_effect=NoConnectionException("CCU unreachable"))

        base_control_unit = BaseControlUnit(control_config=control_config, central=central)

        with pytest.raises(NoConnectionException):
            await base_control_unit.start_central()

        central.start.assert_awaited_once()
