"""Test ZHA binary sensor."""

from collections.abc import Callable
from typing import Any
from unittest.mock import patch

import pytest
import zigpy.profiles.zha
from zigpy.zcl.clusters import general, measurement, security

from homeassistant.const import STATE_OFF, STATE_ON, STATE_UNAVAILABLE, Platform
from homeassistant.core import HomeAssistant

from .common import (
    async_enable_traffic,
    async_test_rejoin,
    find_entity_id,
    send_attributes_report,
)
from .conftest import SIG_EP_INPUT, SIG_EP_OUTPUT, SIG_EP_PROFILE, SIG_EP_TYPE

from tests.common import async_mock_load_restore_state_from_storage

DEVICE_IAS = {
    1: {
        SIG_EP_PROFILE: zigpy.profiles.zha.PROFILE_ID,
        SIG_EP_TYPE: zigpy.profiles.zha.DeviceType.IAS_ZONE,
        SIG_EP_INPUT: [security.IasZone.cluster_id],
        SIG_EP_OUTPUT: [],
    }
}


DEVICE_OCCUPANCY = {
    1: {
        SIG_EP_PROFILE: zigpy.profiles.zha.PROFILE_ID,
        SIG_EP_TYPE: zigpy.profiles.zha.DeviceType.OCCUPANCY_SENSOR,
        SIG_EP_INPUT: [measurement.OccupancySensing.cluster_id],
        SIG_EP_OUTPUT: [],
    }
}


DEVICE_ONOFF = {
    1: {
        SIG_EP_PROFILE: zigpy.profiles.zha.PROFILE_ID,
        SIG_EP_TYPE: zigpy.profiles.zha.DeviceType.ON_OFF_SENSOR,
        SIG_EP_INPUT: [],
        SIG_EP_OUTPUT: [general.OnOff.cluster_id],
    }
}


@pytest.fixture(autouse=True)
def binary_sensor_platform_only():
    """Only set up the binary_sensor and required base platforms to speed up tests."""
    with patch(
        "homeassistant.components.zha.PLATFORMS",
        (
            Platform.BINARY_SENSOR,
            Platform.DEVICE_TRACKER,
            Platform.NUMBER,
            Platform.SELECT,
        ),
    ):
        yield


async def async_test_binary_sensor_on_off(hass, cluster, entity_id):
    """Test getting on and off messages for binary sensors."""
    # binary sensor on
    await send_attributes_report(hass, cluster, {1: 0, 0: 1, 2: 2})
    assert hass.states.get(entity_id).state == STATE_ON

    # binary sensor off
    await send_attributes_report(hass, cluster, {1: 1, 0: 0, 2: 2})
    assert hass.states.get(entity_id).state == STATE_OFF


async def async_test_iaszone_on_off(hass, cluster, entity_id):
    """Test getting on and off messages for iaszone binary sensors."""
    # binary sensor on
    cluster.listener_event("cluster_command", 1, 0, [1])
    await hass.async_block_till_done()
    assert hass.states.get(entity_id).state == STATE_ON

    # binary sensor off
    cluster.listener_event("cluster_command", 1, 0, [0])
    await hass.async_block_till_done()
    assert hass.states.get(entity_id).state == STATE_OFF

    # check that binary sensor remains off when non-alarm bits change
    cluster.listener_event("cluster_command", 1, 0, [0b1111111100])
    await hass.async_block_till_done()
    assert hass.states.get(entity_id).state == STATE_OFF


@pytest.mark.parametrize(
    ("device", "on_off_test", "cluster_name", "reporting", "name"),
    [
        (
            DEVICE_IAS,
            async_test_iaszone_on_off,
            "ias_zone",
            (0,),
            "FakeManufacturer FakeModel IAS zone",
        ),
        (
            DEVICE_OCCUPANCY,
            async_test_binary_sensor_on_off,
            "occupancy",
            (1,),
            "FakeManufacturer FakeModel Occupancy",
        ),
    ],
)
async def test_binary_sensor(
    hass: HomeAssistant,
    zigpy_device_mock,
    zha_device_joined_restored,
    device,
    on_off_test,
    cluster_name,
    reporting,
    name,
) -> None:
    """Test ZHA binary_sensor platform."""
    zigpy_device = zigpy_device_mock(device)
    zha_device = await zha_device_joined_restored(zigpy_device)
    entity_id = find_entity_id(Platform.BINARY_SENSOR, zha_device, hass)
    assert entity_id is not None

    assert hass.states.get(entity_id).name == name
    assert hass.states.get(entity_id).state == STATE_OFF
    await async_enable_traffic(hass, [zha_device], enabled=False)
    # test that the sensors exist and are in the unavailable state
    assert hass.states.get(entity_id).state == STATE_UNAVAILABLE

    await async_enable_traffic(hass, [zha_device])

    # test that the sensors exist and are in the off state
    assert hass.states.get(entity_id).state == STATE_OFF

    # test getting messages that trigger and reset the sensors
    cluster = getattr(zigpy_device.endpoints[1], cluster_name)
    await on_off_test(hass, cluster, entity_id)

    # test rejoin
    await async_test_rejoin(hass, zigpy_device, [cluster], reporting)
    assert hass.states.get(entity_id).state == STATE_OFF


@pytest.mark.parametrize(
    "restored_state",
    [
        STATE_ON,
        STATE_OFF,
    ],
)
async def test_onoff_binary_sensor_restore_state(
    hass: HomeAssistant,
    zigpy_device_mock,
    core_rs: Callable[[str, Any, dict[str, Any]], None],
    zha_device_restored,
    restored_state: str,
) -> None:
    """Test ZHA OnOff binary_sensor restores last state from HA."""

    entity_id = "binary_sensor.fakemanufacturer_fakemodel_opening"
    core_rs(entity_id, state=restored_state, attributes={})
    await async_mock_load_restore_state_from_storage(hass)

    zigpy_device = zigpy_device_mock(DEVICE_ONOFF)
    zha_device = await zha_device_restored(zigpy_device)
    entity_id = find_entity_id(Platform.BINARY_SENSOR, zha_device, hass)

    assert entity_id is not None
    assert hass.states.get(entity_id).state == restored_state
