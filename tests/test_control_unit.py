"""Test control_unit helper functions."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from aiohomematic.const import SystemInformation
from custom_components.homematicip_local.control_unit import ControlConfig, validate_config_and_get_system_information

from tests import const


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
