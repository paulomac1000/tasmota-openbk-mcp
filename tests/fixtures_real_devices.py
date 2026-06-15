"""Real anonymized device responses for integration/e2e tests.

Anonymization strategy (per .omo/plans/v1.6.0-real-integration.md):
- IPs: replace last octet with .100-.109 (per AGENTS.md convention)
- MACs: replace with aa:bb:cc:dd:ee:XX pattern
- Tasmota Topic: replace with generic tasmota_XXXXXXXX
- BSSID: replace with 11:22:33:44:55:XX
- Device friendly names: preserved (semantic)
- Firmware versions: preserved (12.5.0, 1.17.306)
- Build dates: replaced with 2024-01-01 placeholder

These fixtures are used by integration tests that need realistic device
response shapes WITHOUT depending on actual network devices.
"""

# =============================================================================
# Tasmota anonymized responses (from 192.168.0.109 capture)
# =============================================================================

# FriendlyName=["Tasmota", ""], 2 channels, basic on/off
MOCK_TASMOTA_BASIC_STATUS_0: dict = {
    "Status": {
        "Module": 0,
        "DeviceName": "Tasmota",
        "FriendlyName": ["Tasmota", ""],
        "Topic": "tasmota_12345678",
        "ButtonTopic": "0",
        "Power": 0,
        "PowerOnState": 3,
        "LedState": 1,
        "LedMask": "FFFF",
        "SaveData": 1,
        "SaveState": 1,
        "SwitchTopic": "0",
        "SwitchMode": [0] * 8,
        "ButtonRetain": 0,
        "SwitchRetain": 0,
        "SensorRetain": 0,
        "PowerRetain": 0,
        "InfoRetain": 0,
        "StateRetain": 0,
        "StatusRetain": 0,
    },
    "StatusPRM": {
        "Baudrate": 115200,
        "SerialConfig": "8N1",
        "GroupTopic": "tasmotas",
        "OtaUrl": "http://ota.tasmota.com/tasmota/release/tasmota.bin.gz",
        "RestartReason": "Software/System restart",
        "Uptime": "7T12:40:29",
        "StartupUTC": "2024-01-01T00:00:00",
        "Sleep": 50,
        "CfgHolder": 4617,
        "BootCount": 101,
        "BCResetTime": "2024-01-01T18:55:31",
        "SaveCount": 10934,
        "SaveAddress": "F6000",
    },
    "StatusFWR": {
        "Version": "12.5.0(tasmota)",
        "BuildDateTime": "2023-04-17 08:03:54",
        "Boot": 31,
        "Core": "2_7_4_9",
        "SDK": "2.2.2-dev(38a443e)",
        "CpuFrequency": 80,
        "Hardware": "ESP8285N08",
        "CR": "405/699",
    },
    "StatusLOG": {
        "SerialLog": 2,
        "WebLog": 2,
        "MqttLog": 0,
        "SysLog": 0,
        "LogHost": "",
        "LogPort": 514,
        "SSId": ["TestWiFi", "TestWiFi_5G"],
        "TelePeriod": 300,
        "Resolution": "558180C0",
        "SetOption": [
            "00008009",
            "2805C80001000600003C5A0A192800000000",
            "00008080",
            "00006000",
            "00004000",
            "00000000",
        ],
    },
    "StatusMEM": {
        "ProgramSize": 632,
        "Free": 368,
        "Heap": 21,
        "ProgramFlashSize": 1024,
        "FlashSize": 1024,
        "FlashChipId": "144051",
        "FlashFrequency": 40,
        "FlashMode": "DOUT",
        "Features": [
            "00000809",
            "8F9AC787",
            "04368001",
            "000000CF",
            "010013C0",
            "C000F981",
            "00004004",
            "00001000",
            "54000020",
            "00000080",
        ],
        "Drivers": "1,2,3,4,5,6,7,8,9,10,12,16,18,19,20,21,22,24,26,27,29,30,35,37,45,62",
        "Sensors": "1,2,3,4,5,6",
        "I2CDriver": "7",
    },
    "StatusNET": {
        "Hostname": "tasmota-test-100",
        "IPAddress": "192.168.1.100",
        "Gateway": "192.168.1.1",
        "Subnetmask": "255.255.255.0",
        "DNSServer1": "192.168.1.1",
        "DNSServer2": "0.0.0.0",
        "Mac": "aa:bb:cc:dd:ee:01",
        "Webserver": 2,
        "HTTP_API": 1,
        "WifiConfig": 4,
        "WifiPower": 17.0,
    },
    "StatusMQT": {
        "MqttHost": "192.168.1.1",
        "MqttPort": 1883,
        "MqttClientMask": "DVES_%06X",
        "MqttClient": "DVES_12345678",
        "MqttUser": "DVES_USER",
        "MqttCount": 1,
        "MAX_PACKET_SIZE": 1200,
        "KEEPALIVE": 30,
        "SOCKET_TIMEOUT": 4,
    },
    "StatusTIM": {
        "UTC": "2024-01-01T00:00:00",
        "Local": "2024-01-01T00:00:00",
        "StartDST": "2024-03-31T02:00:00",
        "EndDST": "2024-10-27T03:00:00",
        "Timezone": "+00:00",
        "Sunrise": "07:00",
        "Sunset": "17:00",
    },
    "StatusSNS": {"Time": "2024-01-01T00:00:00"},
    "StatusSTS": {
        "Time": "2024-01-01T00:00:00",
        "Uptime": "7T12:40:29",
        "UptimeSec": 650429,
        "Heap": 21,
        "SleepMode": "Dynamic",
        "Sleep": 50,
        "LoadAvg": 19,
        "MqttCount": 1,
        "POWER1": "OFF",
        "POWER2": "OFF",
        "Wifi": {
            "AP": 1,
            "SSId": "TestWiFi",
            "BSSId": "11:22:33:44:55:01",
            "Channel": 1,
            "Mode": "11n",
            "RSSI": 72,
            "Signal": -64,
            "LinkCount": 4,
            "Downtime": "0T00:00:22",
        },
    },
}

# Multi-channel curtain controller (Tasmota-compatible API on OpenBK)
MOCK_TASMOTA_CURTAINS_STATUS_0: dict = {
    "Status": {
        "Module": 0,
        "DeviceName": "Curtains_Test",
        "FriendlyName": ["Curtains_Test_1", "Curtains_Test_3"],
        "Topic": "tasmota_ABCDEF01",
        "Power": 0,
        "PowerOnState": 3,
    },
    "StatusFWR": {"Version": "12.5.0(tasmota)", "Hardware": "ESP8285N08"},
    "StatusNET": {
        "Hostname": "curtains-test-100",
        "IPAddress": "192.168.1.101",
        "Mac": "aa:bb:cc:dd:ee:02",
    },
    "StatusSTS": {
        "Time": "2024-01-01T00:00:00",
        "POWER1": "OFF",
        "POWER2": "OFF",
        "POWER3": "OFF",
    },
}

# =============================================================================
# OpenBK anonymized responses (from 192.168.0.115 Light_Bedroom capture)
# =============================================================================

MOCK_OPENBK_LIGHT_API_INFO: dict = {
    "uptime_s": 573028,
    "build": "Build on Nov  5 2023 10:01:04 version 1.17.306",
    "ip": "192.168.1.102",
    "mac": "aa:bb:cc:dd:ee:10",
    "flags": "0",
    "mqtthost": "192.168.1.1:1883",
    "mqtttopic": "BK7231N_10000010",
    "chipset": "BK7231N",
    "webapp": "https://openbekeniot.github.io/webapp/",
    "shortName": "Light_Bedroom",
    "startcmd": "SetPinRole 6 1; SetPinChannel 6 1",
    "supportsSSDP": 0,
    "supportsClientDeviceDB": True,
}

MOCK_OPENBK_LIGHT_HTML: str = """<!DOCTYPE html>
<html><head><title>Light_Bedroom</title></head>
<body><div id="main">
<h1>Light_Bedroom</h1>
<div id="state">
<table><tr><td class="off">OFF</td><td class="on">ON</td></tr></table>
<table><tr><td><form action="index"><input type="hidden" name="tgl" value="1">
<input class="bred" type="submit" value="Toggle 1"/></form></td>
<td><form action="index"><input type="hidden" name="tgl" value="2">
<input class="bgrn" type="submit" value="Toggle 2"/></form></td></tr></table>
</div>
<form action="cfg"><input type="submit" value="Config"/></form>
<form action="/index"><input type="hidden" name="restart" value="1">
<input class="bred" type="submit" value="Restart"/></form>
<h5>0 drivers active, total 36</h5>
<h5>Channel 0 = 0.00, Channel 1 = 0.00, Channel 2 = 1.00</h5>
<h5>Cfg size: 3584, change counter: 21, ota counter: 0</h5>
<h5>Wifi RSSI: Excellent (-43dBm)</h5>
<h5>Reboot reason: 0 - Pwr</h5>
<h5>MQTT State: <span style="color:green">connected</span></h5>
Build on Nov  5 2023 10:01:04 version 1.17.306<br>
Device MAC: aa:bb:cc:dd:ee:10<br>
Short name: Light_Bedroom, Chipset BK7231N
</div></body></html>"""

MOCK_OPENBK_LIGHT_STATE: str = (
    "<table><tr><td class='off'>OFF</td><td class='on'>ON</td></tr></table>\n"
    '<table><tr><td><form action="index"><input type="hidden" name="tgl" value="1">\n'
    '<input class="bred" type="submit" value="Toggle 1"/></form></td></tr></table>\n'
    "<table></table>\n"
    "<h5>0 drivers active, total 36</h5>\n"
    "<h5>Channel 0 = 0.00, Channel 1 = 0.00, Channel 2 = 1.00</h5>\n"
    "<h5>Wifi RSSI: Excellent (-43dBm)</h5>"
)

# OpenBK Curtains
MOCK_OPENBK_CURTAINS_API_INFO: dict = {
    "uptime_s": 573028,
    "build": "Build on Nov  5 2023 10:01:04 version 1.17.306",
    "ip": "192.168.1.103",
    "mac": "aa:bb:cc:dd:ee:11",
    "flags": "0",
    "mqtthost": "192.168.1.1:1883",
    "mqtttopic": "BK7231N_10000011",
    "chipset": "BK7231N",
    "webapp": "https://openbekeniot.github.io/webapp/",
    "shortName": "Curtains_LivingRoom",
    "startcmd": "SetPinRole 6 1; SetPinChannel 6 1",
    "supportsSSDP": 0,
    "supportsClientDeviceDB": True,
}

MOCK_OPENBK_CURTAINS_HTML: str = MOCK_OPENBK_LIGHT_HTML.replace(
    "Light_Bedroom", "Curtains LivingRoom"
)

MOCK_OPENBK_CURTAINS_STATE: str = (
    "<table><tr><td class='off'>OFF</td>"
    "<td class='off'>OFF</td>"
    "<td class='off'>OFF</td></tr></table>\n"
    '<table><tr><td><form action="index"><input type="hidden" name="tgl" value="1">\n'
    '<input class="bred" type="submit" value="Toggle Close"/></form></td>\n'
    '<td><form action="index"><input type="hidden" name="tgl" value="2">\n'
    '<input class="bred" type="submit" value="Toggle Stop"/></form></td>\n'
    '<td><form action="index"><input type="hidden" name="tgl" value="3">\n'
    '<input class="bred" type="submit" value="Toggle Open"/></form></td></tr></table>\n'
    "<table></table>\n"
    "<h5>0 drivers active, total 36</h5>\n"
    "<h5>Channel 0 = 0.00, Channel 1 = 0.00, Channel 2 = 1.00</h5>\n"
    "<h5>Wifi RSSI: Excellent (-43dBm)</h5>"
)

# OpenBK Socket
MOCK_OPENBK_SOCKET_API_INFO: dict = {
    "uptime_s": 100000,
    "build": "Build on Nov  5 2023 10:01:04 version 1.17.306",
    "ip": "192.168.1.104",
    "mac": "aa:bb:cc:dd:ee:12",
    "flags": "0",
    "mqtthost": "192.168.1.1:1883",
    "mqtttopic": "BK7231N_10000012",
    "chipset": "BK7231N",
    "webapp": "https://openbekeniot.github.io/webapp/",
    "shortName": "Socket_Kitchen",
    "startcmd": "SetPinRole 7 1; SetPinChannel 7 1",
    "supportsSSDP": 0,
    "supportsClientDeviceDB": True,
}

# =============================================================================
# Test device inventory (cached, anonymized)
# =============================================================================

MOCK_DISCOVERED_DEVICES: list[dict] = [
    {
        "ip": "192.168.1.100",
        "name": "Tasmota",
        "device_type": "tasmota",
        "mac": "aa:bb:cc:dd:ee:01",
    },
    {
        "ip": "192.168.1.101",
        "name": "Curtains_Test",
        "device_type": "tasmota",
        "mac": "aa:bb:cc:dd:ee:02",
    },
    {
        "ip": "192.168.1.102",
        "name": "Light_Bedroom",
        "device_type": "openbk",
        "mac": "aa:bb:cc:dd:ee:10",
    },
    {
        "ip": "192.168.1.103",
        "name": "Curtains_LivingRoom",
        "device_type": "openbk",
        "mac": "aa:bb:cc:dd:ee:11",
    },
    {
        "ip": "192.168.1.104",
        "name": "Socket_Kitchen",
        "device_type": "openbk",
        "mac": "aa:bb:cc:dd:ee:12",
    },
]
