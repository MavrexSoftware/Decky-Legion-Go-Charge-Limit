Legion Go Charge Limit

A [Decky Loader](https://decky.xyz) plugin that toggles the Lenovo Legion Go's
firmware 80% battery charge limit on SteamOS, from the Quick Access menu.

SteamOS has no built-in control for this on the Legion Go. The limit is
exposed only through a Lenovo ACPI/WMI method, which this plugin calls
through the `acpi_call` kernel module.

Features

- One-toggle 80% charge limit, with a read-back of what the firmware reports
- Saved setting is re-applied at boot, after resume from sleep, and every
  5 minutes while enabled
- Built-in installer for `acpi_call` (SteamOS doesn't ship it)
- Toggle to lock/unlock the SteamOS read-only system partition

Compatibility

- Lenovo Legion Go (1st gen, 83E1) on SteamOS
- Not tested on Legion Go S / Go 2, Bazzite, or other distros
- Decky Loader; the frontend uses the older plugin format

Install

1. Download the latest zip from Releases.
2. In Decky: Settings → Developer → Install plugin from ZIP file.
3. Open the plugin from the Quick Access menu (see Usage below).

Manual install:

```
sudo unzip legion-go-charge-limit.zip -d ~/homebrew/plugins/
sudo systemctl restart plugin_loader
```

Usage

1. Open the Quick Access menu (the `...` button) and find **Charge Limit**.
2. If you see an **acpi_call module** section, press **Install acpi_call**,
   confirm, and wait for it to finish (needs internet, takes a few minutes).
   The panel shows live progress. When it says "Done", the section
   disappears.
3. Switch on **Limit charge to 80%**.
4. Check the line under the toggle. It should say
   "Firmware reports: limit ON".
5. Plug the Go in while the battery is below 80%. It should stop charging at
   80% and show as plugged in, not charging.

The setting is saved. It is re-applied at boot, after waking from sleep, and
every 5 minutes while enabled.

Unlock system partition toggle

The **System** section has a switch that runs `steamos-readonly disable` /
`enable`. Leave it locked unless you are installing something by hand. You
don't need it for the acpi_call installer, which unlocks and re-locks the
partition by itself.

After a SteamOS update

Updates remove the `acpi_call` module. Your saved setting is kept. Open the
plugin and press **Install acpi_call** again.

About the acpi_call installer

The button temporarily unlocks the system partition, installs kernel headers,
`dkms`, `gcc`, `make` and `acpi_call-dkms` with pacman, builds the module,
and locks the partition again (even if the install fails). It aborts if less
than 300 MiB is free on the system partition. The full log is saved as
`install.log` in the plugin's log folder.

Troubleshooting

| What you see | What to do |
| --- | --- |
| No **Charge Limit** entry in the menu | `sudo systemctl restart plugin_loader`, wait ~10 seconds, reopen the menu |
| Panel looks like an old version | Check `grep version ~/homebrew/plugins/*/package.json`. If it's old, delete the old plugin folder, restart `plugin_loader` and reinstall the zip |
| `acpi_call kernel module not available` | Press **Install acpi_call**, or install the module yourself and check that `/proc/acpi/call` exists |
| Install fails | Read the log lines in the panel. The full log is `install.log` in the plugin's log folder under `~/homebrew/logs/` |
| "Firmware state: unknown" | The ACPI call failed or the read-back couldn't be parsed. Read the error text under the toggle |
| Toggle works but the battery charges past 80% | Open an issue with your BIOS version and the output of `uname -r` |
| Limit stops working while hhd is running | Turn off hhd's charge-limit setting. Two programs shouldn't control it |
| System toggle says "State unknown" | Open an issue with the output of `steamos-readonly status` |

Uninstall

1. Switch Limit charge to 80% off first, so the firmware goes back to
   normal charging.
2. Remove the plugin:
   `sudo rm -rf ~/homebrew/plugins/legion-go-charge-limit`, then
   `sudo systemctl restart plugin_loader`.
3. Optional, to remove the module: unlock the system partition, run
   `sudo pacman -R acpi_call-dkms`, then lock it again.

Caveats

- The ACPI call comes from reading Handheld Daemon's source and has had
  limited testing.
- Don't use this together with hhd's charge-limit setting; they will fight.
- The installer runs `pacman -Sy` against SteamOS's pinned repos and modifies
  the system partition. Read the code before running it.
- The limit is a firmware on/off 80% cap, not an adjustable percentage.


The ACPI method (`\_SB.GZFD.WMAE`, feature `0x03010001`) was identified from
[Handheld Daemon](https://github.com/hhd-dev/hhd)
(`src/adjustor/core/lenovo.py`).
License

GPL-3.0-or-later.
