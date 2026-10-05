"""Tests for specific ISAPI responses."""

import json

import respx
import httpx
from contextlib import suppress
from custom_components.hikvision_next.isapi import StorageInfo
from tests.conftest import mock_endpoint, load_fixture


@respx.mock
async def test_storage(mock_isapi):
    isapi = mock_isapi

    mock_endpoint("ContentMgmt/Storage", "hdd1")
    storage_list = await isapi.get_storage_devices()
    assert len(storage_list) == 1
    assert storage_list[0] == StorageInfo(
        id=1,
        name="hdd1",
        type="SATA",
        status="ok",
        capacity=1907729,
        freespace=0,
        property="RW",
        ip="",
    )

    mock_endpoint("ContentMgmt/Storage", "hdd1_nas1")
    storage_list = await isapi.get_storage_devices()
    assert len(storage_list) == 2
    assert storage_list[0].type == "SATA"
    assert storage_list[1].type == "NFS"
    assert storage_list[1].ip != ""

    mock_endpoint("ContentMgmt/Storage", status_code=500)
    with suppress(Exception):
        storage_list = await isapi.get_storage_devices()
        assert len(storage_list) == 0


@respx.mock
async def test_notification_hosts(mock_isapi):
    isapi = mock_isapi

    mock_endpoint("Event/notification/httpHosts", "nvr_single_item")
    host_nvr = await isapi.get_alarm_server()

    mock_endpoint("Event/notification/httpHosts", "ipc_list")
    host_ipc = await isapi.get_alarm_server()

    assert host_nvr == host_ipc


@respx.mock
async def test_update_notification_hosts(mock_isapi):
    isapi = mock_isapi

    def update_side_effect(request, route):
        payload = load_fixture("ISAPI/Event.notification.httpHosts", "set_alarm_server_payload")
        if request.content.decode("utf-8") != payload:
            raise AssertionError("Request content does not match expected payload")
        return httpx.Response(200)

    mock_endpoint("Event/notification/httpHosts", "nvr_single_item")
    url = f"{isapi.host}/ISAPI/Event/notification/httpHosts"
    endpoint = respx.put(url).mock(side_effect=update_side_effect)
    await isapi.set_alarm_server("http://1.0.0.11:8123", "/api/hikvision")

    assert endpoint.called


@respx.mock
async def test_update_notification_hosts_from_ipaddress_to_hostname(mock_isapi):
    isapi = mock_isapi

    def update_side_effect(request, route):
        payload = load_fixture("ISAPI/Event.notification.httpHosts", "set_alarm_server_outside_network_payload")
        if request.content.decode("utf-8") != payload:
            raise AssertionError("Request content does not match expected payload")
        return httpx.Response(200)

    mock_endpoint("Event/notification/httpHosts", "nvr_single_item")
    url = f"{isapi.host}/ISAPI/Event/notification/httpHosts"
    endpoint = respx.put(url).mock(side_effect=update_side_effect)
    await isapi.set_alarm_server("https://ha.hostname.domain", "/api/hikvision")

    assert endpoint.called


@respx.mock
async def test_audio_alarm_without_alert_audio_list(mock_isapi):
    """Use audioID on firmware that has no separate alertAudio sound list."""
    isapi = mock_isapi
    url = "http://1.0.0.255/ISAPI/Event/triggers/notifications/AudioAlarm"
    respx.get(f"{url}/capabilities?format=json").respond(
        json={
            "AudioAlarmCap": {
                "audioTypeListCap": [
                    {"audioID": 1, "audioDescription": "Siren"},
                    {"audioID": 2, "audioDescription": "Warning,this is restricted area"},
                ],
                "audioVolume": {"@min": 1, "@max": 10, "@def": 5},
            }
        }
    )
    respx.get(f"{url}?format=json").respond(json={"AudioAlarm": {"audioID": 1, "audioVolume": 5, "alarmTimes": 3}})
    put = respx.put(f"{url}?format=json").respond(json={"statusCode": 1})

    audio_alarm = await isapi.get_audio_alarm()
    assert [sound.name for sound in audio_alarm.capabilities.sounds] == ["Siren", "Warning,this is restricted area"]
    assert audio_alarm.capabilities.volume_max == 10
    assert audio_alarm.capabilities.alarm_times_max == 50
    assert not audio_alarm.capabilities.support_test
    assert audio_alarm.state.sound_id == 1

    state = await isapi.set_audio_alarm_state(sound_id=2)
    assert state.sound_id == 2
    payload = json.loads(put.calls.last.request.content)["AudioAlarm"]
    assert payload == {"audioID": 2, "audioVolume": 5, "alarmTimes": 3}
