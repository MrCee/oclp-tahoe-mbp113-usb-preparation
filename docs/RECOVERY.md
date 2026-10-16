# Experimental Recovery fallback

**Status:** this custom helper was not demonstrated to recover the earlier installation by itself. The normal USB preparation route does not use it.

If Tahoe works with the USB inserted but will not boot without it, use [the internal OpenCore handover in README step 4](../README.md#4-finish-opencore-on-the-internal-drive), not this Recovery helper. Keep the completed installation.

Prepare the optional files on the working Mac **before** using the Recovery commands below:

```bash
sudo python3 prepare_usb.py --usb "/Volumes/Install macOS Tahoe" --with-recovery-kit
```

This includes the normal package/EFI preparation and additionally unpacks the RC3 runtime and matching KDK, including its SDK, compiles the x86_64 utility and copies the Recovery scripts. It requires **Xcode Command Line Tools**, at least **15 GiB free host space**, and enough USB space for the additional archives. An Apple silicon preparation Mac must be able to execute the Intel utility during verification. It does not activate the internal repair service until you explicitly run `repair.sh --repair` in installer Recovery.

To check the optional kit too, use:

```bash
sudo python3 prepare_usb.py --usb "/Volumes/Install macOS Tahoe" --with-recovery-kit --check
```


**Use only if the prepared installer still leaves an unusable installed system.** These script steps require Tahoe **26.7.1 / 25G241 to be installed on the internal disk already**. They describe how to stage dependencies and invoke OCLP when a graphical session is unavailable. The helper does not erase the disk or install macOS. This fallback is separate from the default installer preparation.

Connect the laptop's charger and leave the USB inserted.

1. Hold **Option** at startup; choose **USB EFI Boot**, then **Install macOS Tahoe**.
2. In Recovery, open **Utilities → Terminal**.
3. Run the script from its exact mounted location:

   ```bash
   /bin/bash "/Volumes/Install macOS Tahoe/repair.sh" --repair
   ```

   If Recovery mounted the current USB as `Image Volume`, use:

   ```bash
   /bin/bash "/Volumes/Image Volume/repair.sh" --repair
   ```

4. The script stages its files and restarts after a short notice. Choose **USB EFI Boot → internal MacIntosh** (or your internal volume's actual name). Use a **normal boot**, without Shift.
5. The startup job invokes the official RC3 `--patch_sys_vol` command before login. A user account, Dock, Spotlight and Terminal on the broken setup screen are not required.
6. The custom job automatically disables itself and restarts once only after a zero patcher exit, successful logging, OCLP's completion message, and execution of **both Intel Haswell and NVIDIA Kepler patchsets**.
7. Choose **USB EFI Boot → internal MacIntosh** again and check whether Setup Assistant and the desktop are usable. Script completion alone does not establish recovery.

Use one exact, quoted path to the current USB script. Inspect the USB logs for patching progress; the job makes no automatic repeated patch attempts.

## Logs and rollback

| Location | Contents |
| :--- | :--- |
| Working Mac: `build/runs/<timestamp>/` | USB preparation log/report and backups of replaced managed files |
| USB installer volume: `Repair-Logs/` | USB preparation log/report, Recovery staging and live startup/patcher logs, when writable |
| Same USB's EFI: `Repair-Logs/` | Fallback logging if the installer stays read-only |
| Internal Data: `Library/Application Support/MBP113-Repair/logs/` | Local startup output and a copy of preparation evidence |
| Internal Data: `Library/Application Support/MBP113-Repair/backups/` | Preserved app/helper and previous custom-job configuration |

The log records which USB location was used. An absent or unwritable USB prevents root patching; early startup failures are retained internally. **A zero OCLP exit alone is not treated as success.** Logs can contain serial numbers, paths and identifiers—review them before sharing.

To disable only the custom startup job, boot the USB installer Recovery and run the matching exact path:

```bash
/bin/bash "/Volumes/Install macOS Tahoe/repair.sh" --disable
```

This does not undo OCLP root patches. For root-patch rollback, use the appropriate [upstream OCLP unpatch guidance](https://github.com/dortania/OpenCore-Legacy-Patcher/blob/3.0.0-rc.3/docs/TROUBLESHOOT-APP.md). The original config backup can restore the small EFI change. This helper does not erase disks, create user accounts, skip Setup Assistant or install OpenCore to the internal EFI.


[Return to the installation guide](../README.md) · [Troubleshooting history](CASE-STUDY.md)
