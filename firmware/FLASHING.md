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

`platformio.ini` names the platform file `default_8MB.csv`. That file is
not in the repo, so this checkout does not list the partition offsets.
Do not pass an erase. The project has no `read_flash` backup and no saved
copy of the binary currently on either board.

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

Build, without writing the chip: `pio run -e quad`. The image is under
`.pio/build/quad/`. This cloud checkout has not produced that image yet
when `FLASHING.md` was added.

## Large board, E1003

Evidence: `E1003.md` "Build / flash", env `quad-e1003` in
`firmware/platformio.ini`.

- Same ESP32-S3 board id, different panel: ED103TC2 behind the TCON,
  1872×1404, Seeed_GFX setup 522. USB bridge is a WCH CH343, not the
  E1001's CH340.
- On macOS the documented driver is WCH's CH343SER, and the port is
  `/dev/cu.wchusbserial*`.
- If upload will not start, `E1003.md` says hold KEY0/BOOT while plugging
  in. That sentence is only in the E1003 section. KEY0 in `board.h` is
  GPIO3 on both boards. GPIO0 is the ESP32-S3 strap pin. The doc names
  them together; this file does not add a second combo.
- From `firmware/`:

```sh
pio run -e quad-e1003                 # build only
pio run -e quad-e1003 -t upload --upload-port /dev/cu.wchusbserialXXXX
pio device monitor -b 115200
```

## Both

`board_upload.flash_size` is 32MB. `ARDUINO_USB_CDC_ON_BOOT` is 0, so the
log is the UART bridge, not the native USB-CDC port. Monitor speed is
115200. There is no documented rollback binary. To go back you need an
older image you built yourself and the same USB command with the matching
`-e`. Server rollback (`e1003-thirds`) does not restore a chip.
