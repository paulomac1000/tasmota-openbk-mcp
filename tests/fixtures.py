"""
Mock data constants for Local Home Devices MCP tests.

All mock devices use generic names (Tasmota_Test, OpenBK_Test).
No real device names, IPs, or credentials.
"""

MOCK_TASMOTA_DEVICE = {
    "ip": "192.168.1.100",
    "type": "tasmota",
    "name": "Tasmota_Test",
    "mac": "AA:BB:CC:DD:EE:FF",
}

MOCK_OPENBK_DEVICE = {
    "ip": "192.168.1.101",
    "type": "openbk",
    "name": "OpenBK_Test",
}

MOCK_DEVICE_STATUS_RESPONSE = {
    "Status": {
        "DeviceName": "Tasmota_Test",
        "FriendlyName": ["Test_Light"],
        "POWER": "ON",
        "Wifi": {"RSSI": 85, "Signal": -45},
    }
}

MOCK_POWER_RESPONSE = {"POWER": "ON"}

MOCK_BRIGHTNESS_RESPONSE = {"POWER": "ON", "Dimmer": 75}

MOCK_DISCOVERED_DEVICES = [
    {
        "ip": "192.168.1.100",
        "type": "tasmota",
        "name": "Tasmota_Test",
        "mac": "AA:BB:CC:DD:EE:FF",
        "channels": 4,
    },
    {
        "ip": "192.168.1.101",
        "type": "openbk",
        "name": "OpenBK_Test",
        "channels": 2,
    },
]

MOCK_CACHE_DATA = {
    "discovery_time": 1700000000,
    "network_range": "192.168.1.0/24",
    "devices": MOCK_DISCOVERED_DEVICES,
}

# Tasmota SetOption flags response (single option)
MOCK_TASMOTA_SETOPTION_ON = {"SetOption0": "ON"}
MOCK_TASMOTA_SETOPTION_OFF = {"SetOption0": "OFF"}

# Tasmota DeviceName/FriendlyName response
MOCK_TASMOTA_DEVICENAME = {"DeviceName": "Tasmota_Test"}
MOCK_TASMOTA_FRIENDLYNAME = {"FriendlyName1": "Tasmota_Test"}

# Tasmota MQTT config responses
MOCK_TASMOTA_MQTTHOST = "192.0.2.100"

# Backlog response (empty = success)
MOCK_TASMOTA_BACKLOG_OK = {}

# Timeout response
MOCK_DEVICE_TIMEOUT_RESPONSE = {"error": True, "response": "Connection timed out"}

# --------------------------------------------------------------------------- #
# OpenBK Status 0 response (anonymized real device data)
# Source: BK7231N v1.17.306 device, IP/MAC/SSID/names anonymized
# --------------------------------------------------------------------------- #

MOCK_OPENBK_STATUS_RESPONSE = {
    "Status": {
        "Module": 0,
        "DeviceName": "OpenBK_Test",
        "FriendlyName": ["OpenBK_Test_1", "OpenBK_Test_2"],
        "Topic": "BK7231N_OPENBK_TEST",
        "ButtonTopic": "0",
        "Power": 0,
        "PowerOnState": 3,
        "LedState": 1,
        "LedMask": "FFFF",
        "SaveData": 1,
        "SaveState": 1,
        "SwitchTopic": "0",
        "SwitchMode": [0, 0, 0, 0, 0, 0, 0, 0],
        "ButtonRetain": 0,
        "SwitchRetain": 0,
        "SensorRetain": 0,
        "PowerRetain": 0,
        "InfoRetain": 0,
        "StateRetain": 0,
    },
    "StatusPRM": {
        "Baudrate": 115200,
        "SerialConfig": "8N1",
        "GroupTopic": "",
        "OtaUrl": "https://github.com/openshwprojects/OpenBK7231T_App/releases/latest",
        "RestartReason": "HardwareWatchdog",
        "Uptime": 9300,
        "StartupUTC": "1969-12-31T21:24:50",
        "Sleep": 50,
        "CfgHolder": 4617,
        "BootCount": 22,
        "BCResetTime": "2022-01-27T16:10:56",
        "SaveCount": 1235,
        "SaveAddress": "F9000",
    },
    "StatusFWR": {
        "Version": "OpenBK7231N_1.17.306",
        "BuildDateTime": "Nov  5 2023 10:01:03",
        "Boot": 7,
        "Core": "0.0",
        "SDK": "obk",
        "CpuFrequency": 80,
        "Hardware": "BK7231N",
        "CR": "465/699",
    },
    "StatusLOG": {
        "SerialLog": 2,
        "WebLog": 2,
        "MqttLog": 0,
        "SysLog": 0,
        "LogHost": "",
        "LogPort": 514,
        "SSId1": "Test_SSID",
        "SSId2": "",
        "TelePeriod": 300,
        "Resolution": "558180C0",
        "SetOption": [
            "000A8009",
            "2805C80001000600003C5A0A000000000000",
            "00000280",
            "00006008",
            "00004000",
        ],
    },
    "StatusMEM": {
        "ProgramSize": 616,
        "Free": 384,
        "Heap": 25,
        "ProgramFlashSize": 1024,
        "FlashSize": 2048,
        "FlashChipId": "1540A1",
        "FlashFrequency": 40,
        "FlashMode": 3,
        "Features": [
            "00000809",
            "8FDAC787",
            "04368001",
            "000000CF",
            "010013C0",
            "C000F981",
            "00004004",
            "00001000",
            "00000020",
        ],
        "Drivers": "1,2,3,4,5,6,7,8,9,10,12,16,18,19,20,21,22,24,26,27,29,30,35,37,45",
        "Sensors": "1,2,3,4,5,6",
    },
    "StatusNET": {
        "Hostname": "OpenBK_Test",
        "IPAddress": "192.0.2.101",
        "Gateway": "192.0.2.1",
        "Subnetmask": "255.255.255.0",
        "DNSServer1": "192.0.2.1",
        "DNSServer2": "0.0.0.0",
        "Mac": "AA:BB:CC:DD:EE:11",
        "Webserver": 2,
        "HTTP_API": 1,
        "WifiConfig": 4,
        "WifiPower": 17.0,
    },
    "StatusMQT": {
        "MqttHost": "192.0.2.100",
        "MqttPort": 1883,
        "MqttClientMask": "core",
        "MqttClient": "BK7231N_OPENBK_TEST",
        "MqttUser": "",
        "MqttCount": 23,
        "MAX_PACKET_SIZE": 1200,
        "KEEPALIVE": 30,
        "SOCKET_TIMEOUT": 4,
    },
    "StatusTIM": {
        "UTC": "1970-01-01T00:00:00",
        "Local": "1970-01-01T00:00:00",
        "StartDST": "2022-03-27T02:00:00",
        "EndDST": "2022-10-30T03:00:00",
        "Timezone": "+01:00",
        "Sunrise": "07:50",
        "Sunset": "17:17",
    },
    "StatusSNS": {
        "Time": "1970-01-01T00:00:00",
    },
    "StatusSTS": {
        "Time": "1970-01-01T00:00:00",
        "Uptime": "0T02:35:00",
        "UptimeSec": 9300,
        "Heap": 25,
        "SleepMode": "Dynamic",
        "Sleep": 10,
        "LoadAvg": 99,
        "MqttCount": 23,
        "POWER1": "OFF",
        "POWER2": "OFF",
        "Wifi": {
            "AP": 1,
            "SSId": "Test_SSID",
            "BSSId": "AA:BB:CC:DD:EE:12",
            "Channel": 11,
            "Mode": "11n",
            "RSSI": 62,
            "Signal": -69,
            "LinkCount": 21,
            "Downtime": "0T06:13:34",
        },
    },
}

MOCK_OPENBK_FULL_INFO = {
    "device_type": "openbk",
    "ip": "192.0.2.101",
    "version": "OpenBK7231N_1.17.306",
    "device_name": "OpenBK_Test",
    "mac": "AA:BB:CC:DD:EE:11",
    "mqtt_host": "192.0.2.100",
    "wifi_ssid": "Test_SSID",
    "wifi_rssi": 62,
    "wifi_signal": -69,
    "uptime": "0T02:35:00",
    "flags": {"generic_flags": 0, "generic_flags_2": 0},
    "source": "Status 0",
}

MOCK_TASMOTA_STATUS_RESPONSE = {
    "Status": {
        "DeviceName": "Tasmota_Test",
        "FriendlyName": ["Tasmota_Test"],
        "Topic": "tasmota_test",
        "Power": 0,
        "Version": "Tasmota_14.2.0",
    },
    "StatusNET": {
        "Hostname": "Tasmota_Test",
        "IPAddress": "192.0.2.100",
        "Mac": "AA:BB:CC:DD:EE:FF",
    },
    "StatusMQT": {
        "MqttHost": "192.0.2.1",
        "MqttPort": 1883,
        "MqttClientMask": "DVES_%08X",
        "MqttClient": "tasmota_test",
    },
    "StatusSTS": {
        "Uptime": "0T01:00:00",
        "UptimeSec": 3600,
        "Wifi": {"AP": 1, "SSId": "Test_SSID", "RSSI": 80, "Signal": -50},
    },
}
