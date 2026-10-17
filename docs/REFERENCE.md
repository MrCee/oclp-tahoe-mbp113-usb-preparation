# Technical reference

[Return to the four-step installation guide](../README.md)

Use the README for the normal workflow. This page explains the scripts, prerequisites, logs and less common options. It supports **MacBookPro11,3 / Tahoe 26.7.1 (25G241) / OCLP 3.0.0 RC3**.

## What the scripts change

| Tool | Run it where | What it does |
| :--- | :--- | :--- |
| `prepare_usb.py` | Working preparation Mac | Validates the same external USB/EFI, stages verified installer packages, corrects USB boot settings, includes the finishing tools and saves backups/logs. |
| `MBP113-Finish/finish-install.command` | MacBook’s installed Tahoe desktop | Starts manually, establishes USB logging, uses existing Python or installs Apple’s offered stable Command Line Tools when needed, verifies the bundled files and invokes the EFI helper. |
| `finish_install.py` | MacBook’s installed Tahoe desktop | Finds the internal EFI belonging to the currently running APFS system, checks model/build/OpenCore files, backs up its config and applies the same model/normal-boot settings. |

OCLP performs the actual OpenCore build/installation and macOS root patching. These preparation/finishing scripts do not erase disks, install macOS or install graphics patches. The normal route uses no experimental Recovery service or USB-mount/login watcher.

### Installer packages

The preparation command downloads the pinned official RC3 `AutoPkg-Assets.pkg` and matching KDK image when needed. It mounts the image read-only, verifies the contained package, and places:

```text
Library/Packages/AutoPkg-Assets.pkg
Library/Packages/KDK.pkg
```

Both use pinned SHA-256 checks and `644` file permissions. Correct copies already on the USB are reused. A fresh USB lacking `Library/Packages` is expected; preparation creates the folder. You do not double-click these packages on the preparation Mac.

The normal command copies original installer packages. It does not expand Recovery archives or compile tools. Old optional Recovery files are retained but are not audited in default mode.

### Exact EFI settings

Both USB preparation and the internal finishing helper apply these scoped changes to their respective `EFI/OC/config.plist`:

| Setting | Result |
| :--- | :--- |
| `PlatformInfo/DataHub/SystemProductName` | `MacBookPro11,3` |
| `PlatformInfo/DataHub/BoardProduct` | `Mac-2BD1B31983FE1663` |
| `PlatformInfo/UpdateDataHub` | `true` |
| Apple NVRAM `Add` → `boot-args` | Remove temporary `-x` Safe Boot; retain other arguments. |
| Apple NVRAM `Delete` list | Include `boot-args`, so OpenCore replaces a saved value with the configured arguments on its next boot. |

Settings already correct are left unchanged. A changed config is backed up before an atomic replacement, then read back and checked. The scripts also check the bootstrap, OpenCore binary and enabled driver/kext file references. OCLP’s Apple bootstrap (`System/Library/CoreServices/boot.efi`), UEFI fallback (`EFI/BOOT/BOOTx64.efi`) and combined layouts are recognised; a second loader is not invented to satisfy a check.

The board ID above belongs to MacBookPro11,3. Do not apply these model-specific values to another Mac model. An OCLP rebuild can replace the config edits: rerun USB preparation after a USB rebuild, and the finishing helper after an internal rebuild.

## Automatic developer-tools setup

The USB launcher checks for an existing **Python 3.9+** first. A suitable Python avoids the tools download. Recent macOS versions expose `/usr/bin/python3` through Apple’s developer tools; the command’s presence alone does not prove a usable Python installation.

If Python is unavailable, the launcher:

1. Checks that it is running on the intended MacBook/Tahoe build and requests administrator access.
2. Saves setup output to the USB and asks Apple’s `softwareupdate` for available packages.
3. Extracts the exact **Command Line Tools for Xcode** label and selects the newest stable offered version numerically. It excludes macOS upgrades and beta/preview tools.
4. Installs only that tools package with Apple’s download/install progress, selects `/Library/Developer/CommandLineTools`, and checks Python again.
5. Verifies the bundled source files before running the EFI helper.

No Git clone is required on the MacBook. The bundle is a snapshot from preparation time; it does not update itself from GitHub. The original Python EFI helper has an owner-confirmed USB-free boot result. The newer launcher/tools-download route has fixture tests and still needs a fresh MacBook hardware test.

If discovery/download fails or Python is still unavailable, the launcher stops before editing internal EFI and retains its log. Install compatible tools from [Apple Developer Downloads](https://developer.apple.com/download/all/) or Python from [python.org](https://www.python.org/downloads/macos/), then rerun. `xcode-select --install` is another manual route: complete its installation window before checking `python3 --version`. The “install requested” message alone is not completion.

## Logs and backups

| Location | Contents |
| :--- | :--- |
| Preparation Mac: `build/runs/<timestamp>/` | Preparation log/report and backups of replaced packages/finishing tools. |
| USB: `Repair-Logs/prepare-<timestamp>/` | Preparation log/report; the same USB’s EFI is the logging fallback. |
| USB: `MBP113-Finish/build/bootstrap/` | Finishing launcher and developer-tools setup/download output. |
| USB: `MBP113-Finish/build/internal-efi/<timestamp>/` | Original internal config copy and the EFI helper’s report. |
| Beside the affected `EFI/OC/config.plist` | Original config backup before a change. |

Keep the USB connected and writable through the finishing command. Review logs before sharing: they can contain private paths and identifiers. A failed multi-file USB deployment may be partial; retain backups, resolve the cause and rerun until the final audit passes.

A helper PASS verifies files/settings, not a firmware boot. Its report initially records `usb_free_boot_verified: false` because the USB-free restart happens afterward. Judge that physical test separately, using the README’s final checkpoint.

## If something stops

| Symptom | Next step |
| :--- | :--- |
| USB preparation reports missing OpenCore/bootstrap files | Build/install OCLP for 11,3 onto that USB’s EFI, then rerun preparation. Preserve the installer. |
| Read-only/busy EFI | Close windows/tools using that EFI and unmount it normally before a write run. The scripts do not force-unmount it. |
| Internal OpenCore missing | In OCLP RC3, build/install to the internal physical drive’s EFI, then run the finishing tool before rebooting. |
| Tools cannot be downloaded | Check Internet access/free space, keep the USB setup log and use the manual tools/Python options above. |
| A bundled file fails verification | Rerun current USB preparation on the working Mac. |
| Installed Tahoe works through USB but fails without it | Complete README step 4 and verify internal EFI settings; keep the installed OS. |
| Boot fails after the finishing step | Reconnect USB, choose USB EFI Boot → Macintosh HD and retain the exact error and helper report. |

If no internal EFI entry appears in Apple’s Option picker, recheck OCLP’s internal installation. If the Lilu model-information error returns, recheck the internal DataHub fixes. Preserve the working USB as a fallback.

## Existing clones and older USBs

The owner’s successful original route remains available from an existing clone on the MacBook:

```bash
git pull --ff-only
sudo python3 finish_install.py
```

This route needs Python 3.9+ already available, and saves the helper backup/report under the clone’s `build/internal-efi/`. Use `sudo python3 finish_install.py --check` to audit internal files/settings without changing files; an unmounted internal EFI may be mounted read-only.

For an older USB lacking `MBP113-Finish`, update the clone on the preparation Mac with `git pull --ff-only`, then rerun `prepare_usb.py`. Matching assets/KDK packages are reused; the small finishing bundle is added or updated with backups of replaced managed files. Existing bundle logs are retained.

## Manual packages and other options

To supply the exact pinned packages locally, mount the matching KDK DMG read-only and pass its `KernelDebugKit.pkg`:

```bash
sudo python3 prepare_usb.py \
  --usb "/Volumes/Install macOS Tahoe" \
  --assets-pkg "/path/to/AutoPkg-Assets.pkg" \
  --kdk-pkg "/Volumes/Kernel Debug Kit/KernelDebugKit.pkg"
```

The same checksum checks apply. Optional flags:

- `--cache "/path/on/working-Mac/cache"`: choose a host download cache outside the USB.
- `--config "/Volumes/EFI/EFI/OC/config.plist"`: select the existing same-USB EFI config explicitly; its disk identity is still checked.
- `--check`: audit USB packages, finishing tools, permissions and EFI settings without changing their files/modes. An unmounted EFI may be mounted read-only.
- `--with-recovery-kit`: include the separate experimental [Recovery fallback](RECOVERY.md). It requires Command Line Tools, at least 15 GiB host space and additional USB space. It is outside the normal route; `repair.sh` is not a substitute for completing preparation or the internal handover.

## Sources and credits

- [Official OCLP RC3 release](https://github.com/dortania/OpenCore-Legacy-Patcher/releases/tag/3.0.0-rc.3)
- [Matching KDK](https://github.com/dortania/KdkSupportPkg/releases/tag/25G241)
- [RC3 installer package placement](https://github.com/dortania/OpenCore-Legacy-Patcher/blob/3.0.0-rc.3/opencore_legacy_patcher/wx_gui/gui_macos_installer_flash.py#L443-L481)
- [RC3 manual assets guidance](https://discord.com/channels/417165963327176704/1389230559674368062/1557563105897226298)
- [OCLP: booting without USB](https://dortania.github.io/OpenCore-Legacy-Patcher/POST-INSTALL.html#booting-without-usb-drive)
- [OCLP: post-install patches](https://dortania.github.io/OpenCore-Legacy-Patcher/POST-INSTALL.html#applying-post-install-volume-patches)
- [Apple: installing Command Line Tools](https://developer.apple.com/documentation/xcode/installing-the-command-line-tools)
- [Python on macOS](https://docs.python.org/3/using/mac.html)
- [Homebrew’s tools-discovery implementation](https://github.com/Homebrew/install/blob/HEAD/install.sh) — also uses Apple’s install-on-demand discovery marker and exact software-update labels.

OpenCore, OCLP and the actual patches belong to their upstream contributors; the KDK is Apple’s work. This repo contains custom source/documentation, not installer binaries, personal EFI configs or private logs. Upstream endorsement is not implied. See [NOTICE.md](../NOTICE.md) and [LICENSE](../LICENSE).
