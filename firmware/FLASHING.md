# Flashing the two boards

Nothing in this checkout flashes a device. There is no remote update path.
Building is `pio run`. Writing the chip is a USB upload from the computer
the board is plugged into, and only after you mean to do it.

The two boards are not the same target. `firmware/upload.bat` does not pass
`-e`, so it uploads the first env in `firmware/platformio.ini`, which is
`quad` (the E1001). Pointing that script at the E1003 would write the small
panel's firmware onto the large one.

## What is not available

Searched `firmware/` for `ArduinoOTA`, `HTTPUpdate`, `esp_ota`, and
`Update.begin`. None of them are there. The poll handler in
`server/app.py` serves a screen image, not a firmware image. Deploying the
Python server does not change what is on either chip. A future OTA client
would be new work. This tree cannot tell whether some older binary on a
board had one; the source here does not.

The partition file resolved from the installed Arduino package
(`framework-arduinoespressif32/tools/partitions/default_8MB.csv`) is:

| Name | Offset | Size |
|---|---|---|
| nvs | 0x9000 | 0x5000 |
| otadata | 0xe000 | 0x2000 |
| app0 | 0x10000 | 0x330000 |
| app1 | 0x340000 | 0x330000 |
| spiffs | 0x670000 | 0x180000 |
| coredump | 0x7F0000 | 0x10000 |

That map ends at 8 MiB. `platformio.ini` sets `board_upload.flash_size` to
32MB, and the built bootloader and app headers say 32MB. The XIAO board
JSON's own default is 8MB; the ini override wins. The top 24MB is not in
the table. A normal esptool `write-flash` of the app starts at 0x10000 and
does not cover the NVS at 0x9000. `erase_flash` does, and it is not
approved. The `app1` slot does not make this firmware able to take an OTA
update. Nothing calls the OTA API.

Before any future USB write, and only with the board in front of you, save
the mapped 8MB and keep that file. This was not run here:

```sh
esptool --chip esp32s3 --port PORT read-flash 0x0 0x800000 board-backup.bin
```

Putting that file back is `write-flash 0x0 board-backup.bin`. Do not erase
first. There is still no copy of the binary that is on either board today.

Wi-Fi name and password live in NVS under the namespace `einknotes`
(`firmware/src/wifisetup.cpp`). The server host and device token are
compiled in from `firmware/src/secrets.h`, which is gitignored. A normal
upload replaces the app. It is not documented to wipe NVS. Holding the
right button (KEY2, GPIO5) for 600 ms at boot does call `forget()` and
drops the stored network (`firmware/src/main.cpp`). The README's "hold
right and tap left" is that portal, but the code only checks the hold.

## Small board, E1001

Evidence: `firmware/platformio.ini` env `quad`, `firmware/upload.bat`,
`firmware/serial.ps1`, `README.md`.

- Chip: ESP32-S3. Board id `seeed_xiao_esp32s3`. Panel UC8179, 800×480.
- USB: CH340, UART0 on GPIO43/44. RTS pulses EN. `serial.ps1` says IO0 is
  left high, so that reset enters the app, not the bootloader. The repo
  does not document a button hold to force the E1001 bootloader.
- Tool: PlatformIO, which calls esptool. Not a browser flasher.
- From `firmware/`:

```sh
pio run -e quad -t upload --upload-port COMn
```

`upload.bat COMn` is the same upload without `-e`, which is safe only
while `quad` stays the first env. `README.md` shows `COM9`.
`serial.ps1` defaults to `COM8` and only listens; it does not write flash.

Build, without writing the chip: `pio run -e quad`. A dummy build of
`5min-1` exists only as a compile check. Its host is
`invalid.example.invalid` and its token is `dummy-not-a-real-token`.
Do not install that file.

## Large board, E1003

Evidence: `E1003.md` "Build / flash", env `quad-e1003` in
`firmware/platformio.ini`.

- Same ESP32-S3 board id, different panel: ED103TC2 behind the TCON,
  1872×1404, Seeed_GFX setup 522. USB bridge is a WCH CH343, not the
  E1001's CH340.
- On macOS the documented driver is WCH's CH343SER, and the port is
  `/dev/cu.wchusbserial*`.
- Do not hold the green refresh button to enter the bootloader. Seeed's
  Arduino cookbook maps KEY0 to GPIO3, the right-hand green button, on
  E1001, E1002, and E1003. The Zephyr board file for the E1003 lists that
  same GPIO3 refresh key and no button on GPIO0. ESP32-S3 download mode
  is GPIO0 held low at reset, which is a different pin. `E1003.md` says
  "hold KEY0/BOOT" if upload will not start. That sentence mixes the two.
  Holding the green button does not pull the strap pin, and this repo
  does not document a separate boot button. If esptool cannot reset the
  chip on its own, stop. Do not invent a hold.
- From `firmware/`:

```sh
pio run -e quad-e1003                 # build only
pio run -e quad-e1003 -t upload --upload-port /dev/cu.wchusbserialXXXX
pio device monitor -b 115200
```

The matching dummy image is `.pio/build/quad-e1003/firmware.bin`. Same
rule: it is not installable. The two partition tables are identical.

## Both

`board_upload.flash_size` is 32MB. `ARDUINO_USB_CDC_ON_BOOT` is 0, so the
log is the UART bridge, not the native USB-CDC port. Monitor speed is
115200. There is no documented rollback binary. To go back you need an
older image you built yourself and the same USB command with the matching
`-e`. Server rollback (`e1003-thirds`) does not restore a chip.
