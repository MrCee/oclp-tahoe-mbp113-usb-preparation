# OCLP Tahoe USB Preparation for MacBookPro11,3

![Model: MacBookPro11,3](https://img.shields.io/badge/model-MacBookPro11%2C3-2563eb)
![macOS: 26.7.1](https://img.shields.io/badge/macOS-26.7.1%20%2825G241%29-111827)
![OCLP: RC3](https://img.shields.io/badge/OCLP-3.0.0--rc.3-f59e0b)

**Prepare your USB, install Tahoe, then finish the internal OpenCore setup. One preparation command handles the verified installer packages and model-specific EFI settings.**

> [!IMPORTANT]
> **Required final step: boot without the USB.**
> USB preparation alone does not finish the internal boot setup. Complete **[step 4](#4-finish-opencore-on-the-internal-drive)**: install OpenCore to the internal EFI, then run the finishing tool **on the MacBook before rebooting**. Skipping that handover leaves this workflow dependent on USB OpenCore. The finishing tool is now included on the prepared USB; another GitHub clone on the MacBook is unnecessary.

For the **mid-2014 15-inch MacBook Pro, MacBookPro11,3**, with Intel Iris Pro and NVIDIA GT 750M. This unofficial preparation tool supports **Tahoe 26.7.1 / build 25G241 and OCLP 3.0.0 RC3 only**. A different model or installer build stops preparation.

**Owner-confirmed hardware result — 2026-10-17:** Tahoe is installed, user setup is complete, and the MacBook now **boots without the USB after OCLP was installed internally and `finish_install.py` was run**. The final internal-EFI step matters: the completed installation still depended on USB OpenCore before it. This is a reported result on one MacBookPro11,3; keep the prepared USB as a fallback.

**Already installed and working with the USB? Go straight to [step 4](#4-finish-opencore-on-the-internal-drive). Do not erase or reinstall Tahoe to fix this boot dependency.**

## Before you start

Use a working Mac with:

- **Python 3.9 or newer** and approximately **8 GiB free host storage** for fresh preparation. Extra storage can be needed for backups of existing files.
- Internet access to download missing official packages, or verified local packages supplied as described below.
- An external installer USB; a **32 GB USB** was used for this workflow. Free space is checked before copying.

The default command does **not** require a compiler or Xcode Command Line Tools if Python is already available. It does not install Python automatically.

## 1. Create the OCLP USB

In **OCLP RC3**:

1. Set **Settings → Target Model → MacBookPro11,3**. Keep the other model defaults; Verbose Mode is optional.
2. Choose **Create macOS Installer** and write **Tahoe 26.7.1 / 25G241** to the USB. Creating installer media erases that USB.
3. Choose **Build and Install OpenCore**, build it, then install it onto **the USB's EFI partition**.

If the macOS installer was already written before you selected the target, select `MacBookPro11,3` before building and installing OpenCore. The next step checks and supplies the installer packages separately.

## 2. Prepare the USB

On the working Mac, open Terminal and run:

```bash
git clone https://github.com/MrCee/oclp-tahoe-mbp113-usb-preparation.git
cd oclp-tahoe-mbp113-usb-preparation
sudo python3 prepare_usb.py --usb "/Volumes/Install macOS Tahoe"
```

If you already cloned the repo, open that folder and run `git pull --ff-only` instead of cloning it again. Then run the same preparation command. Replace the USB volume name if yours is different.

**The command automatically:**

- Finds the EFI on that same external USB, recognises OCLP's Apple or UEFI boot layout, and checks the target model and referenced boot files. A read-only EFI is remounted normally when needed; a busy or protected volume stops with guidance.
- Downloads with a scrolling progress bar, percentage, speed and estimated time, and verifies the pinned official **RC3 `AutoPkg-Assets.pkg`** and matching **`KDK.pkg`**, then copies them into the USB's **`Library/Packages/`**. Correct copies are reused; changed managed files are backed up before replacement.
- Backs up `config.plist`, sets DataHub `SystemProductName` to `MacBookPro11,3`, `BoardProduct` to `Mac-2BD1B31983FE1663`, and `UpdateDataHub` to `true`.
- Removes temporary `-x` Safe Boot and ensures OpenCore replaces saved `boot-args`; other boot arguments are retained.
- Includes the small **`MBP113-Finish/`** folder with the finishing helper, its dependencies, a checksum manifest and **`finish-install.command`**. It is a snapshot of this repo version; rerun preparation to update it.
- Checks write access before downloading, shows four preparation stages and progress while copying and checking large files, sets package permissions and verifies the result. Logs and reports include the detected layout, backup locations, and the next step if preparation stops.

A missing `Library/Packages` folder on a fresh USB is expected: the command creates it and supplies the packages automatically.

**Wait for `PASS: supported USB preparation and report saving complete.`** If the command stops with an error, keep the logs and resolve that error before using the USB. It is safe to rerun; completed matching work is reused. Rebuilding OpenCore afterward may overwrite the EFI corrections, so run this step last.

You do **not** double-click/install these packages on the working Mac. The default command copies the original installer packages; it does not unpack repair archives, compile tools, install a repair service, or require `repair.sh`. Existing optional Recovery files are left alone and are not audited by the default command.

Safely eject the USB and its EFI volume when preparation passes.

## 3. Install Tahoe on the MacBook

This is the clean-install sequence used for the reported working result. **Erasing deletes the internal drive's contents: back up anything you need first.**

1. Connect the prepared USB and charger to the MacBook Pro.
2. Start while holding **Option**, choose **USB EFI Boot**, then **Install macOS Tahoe**.
3. In the installer, use Disk Utility to erase the intended **internal macOS target** for a clean installation using **APFS** (and **GUID Partition Map** if erasing the physical drive). Keep the prepared USB intact. Quit Disk Utility and install Tahoe onto the internal target.
4. During restarts, boot through **USB EFI Boot**. Select the continuing **macOS Installer** entry when present, then the internal macOS entry when installation is complete. Do not restart a new installation from the USB each time.
5. Boot normally and complete user setup. In OCLP, check **Post-Install Root Patch**; apply any required patches it reports, then reboot through USB EFI. Confirm a usable desktop and keep the USB available while it supplies OpenCore.

**There is no `repair.sh` step in this main route.** The command prepares the USB; it does not erase the internal disk, install macOS or install internal OpenCore. Reaching a desktop through USB EFI is an installation result, not proof the Mac can boot without the USB. Continue below.

## 4. Finish OpenCore on the internal drive

**Required to boot without the USB in this workflow.** Do this **on the MacBook Pro**, in its installed Tahoe desktop, while booted through the working USB EFI. Keep the USB as your rescue boot device. This is separate from **Post-Install Root Patch**: root patches do not install the internal bootloader.

1. Open **OCLP 3.0.0 RC3**, confirm **Target Model → MacBookPro11,3**, then choose **Build and Install OpenCore**.
2. Install to the **internal physical drive containing Tahoe**, then its **EFI partition**. Identify it by its name, capacity and internal status; do not assume a disk number. If OCLP offers a reboot, **wait until the next step is complete**.
3. On the MacBook, open **`MBP113-Finish` on the prepared USB** and double-click **`finish-install.command`**, or run:

   ```bash
   /bin/bash "/Volumes/Install macOS Tahoe/MBP113-Finish/finish-install.command"
   ```

   Replace the USB name if yours differs. Enter the MacBook administrator password when asked. **No Git or second repository clone is needed on the MacBook.** The launcher uses an existing **Python 3.9+** first. If none works, it automatically checks Apple's `softwareupdate` list, selects the newest stable offered **Command Line Tools for Xcode** by its exact label, and installs only that package with download progress. It then selects the tools directory and checks Python again. It does not select a macOS upgrade. Internet is needed only when tools must be downloaded. The presence of `/usr/bin/python3` alone does not guarantee the Apple developer-tools Python is installed.

   Setup/download output is saved on the USB under **`MBP113-Finish/build/bootstrap/`**. If Apple offers no compatible stable package, the download fails, or Python remains unavailable, the launcher stops before editing internal EFI and gives manual installation options. You can then install tools from [Apple Developer Downloads](https://developer.apple.com/download/all/) or Python from [python.org](https://www.python.org/downloads/macos/) and rerun. A large tools download is unnecessary when a suitable Python already works.

   The bundled helper verifies its files, identifies the internal EFI belonging to the **currently running APFS system**, checks the Mac model/build and existing OpenCore files, backs up the config, then reapplies the same DataHub and normal-boot settings as USB preparation. A fresh OCLP build can otherwise lose those fixes. The EFI helper does not copy a personal USB EFI, build/install OpenCore, erase data, install patch packages, root-patch or reboot. If internal OpenCore is absent, it stops with instructions to complete steps 1–2. The launcher adds prerequisite setup around the same `finish_install.py` used for the owner's successful boot; the new automatic-tools route has fixture tests and awaits a fresh hardware test.

   **Its exact changes to the internal `EFI/OC/config.plist` are:**

   | Setting | Result |
   | :--- | :--- |
   | `PlatformInfo/DataHub/SystemProductName` | `MacBookPro11,3` |
   | `PlatformInfo/DataHub/BoardProduct` | `Mac-2BD1B31983FE1663` |
   | `PlatformInfo/UpdateDataHub` | `true` |
   | Apple NVRAM `Add` → `boot-args` | Remove the temporary `-x` Safe Boot argument; retain other arguments |
   | Apple NVRAM `Delete` list | Include `boot-args`, so OpenCore replaces a previously saved value with the configured arguments on the next boot |

   Settings already correct are left unchanged. The original config is backed up before a change, then the written config and referenced boot files are checked again. This carries the model-information fix from the USB workflow into the internal OpenCore configuration.

4. Require `PASS: internal EFI configuration verified`. Shut down, unplug the USB, then start holding **Option**. Select the **internal EFI Boot**, then **Macintosh HD** in OpenCore. Once this works, hold **Control** while selecting the internal EFI entry in Apple's Option picker to make it the default, and test an ordinary restart without the USB.

**Success means a usable desktop after an ordinary restart with the USB disconnected.** The helper verifies files/settings, not firmware startup. Keep the USB writable and connected until it finishes. Its backup and report are under **`MBP113-Finish/build/internal-efi/<timestamp>/` on the USB**, with a config backup also beside the internal `EFI/OC/config.plist`.

Already using a clone on the MacBook? The original route still works: run `git pull --ff-only`, then `sudo python3 finish_install.py` from that folder with Python 3.9+ available. In that route the backup/report stays under the clone's `build/internal-efi/`. Add `--check` to the Python command to audit internal settings without changing files; it can mount an unmounted EFI read-only. Older USBs without `MBP113-Finish` can be upgraded by rerunning the current preparation command on the working Mac; valid packages are reused.

**If it fails:** shut down, reconnect the prepared USB and boot **USB EFI Boot → Macintosh HD**. Keep the error text and helper report. Do not erase the installed OS. If there is no internal EFI entry, recheck OCLP's internal-drive installation. If the Lilu model error returns, recheck the internal config fixes. Rebuilding internal OpenCore later requires rerunning `finish_install.py` before rebooting. A read-only internal EFI must be unmounted normally before a write run; no force-unmount is attempted.

## Checks and logs

To repeat the default audit without changing USB files or permissions:

```bash
sudo python3 prepare_usb.py --usb "/Volumes/Install macOS Tahoe" --check
```

An unmounted EFI may be mounted read-only for the check.

| Location | Contents |
| :--- | :--- |
| Working Mac: `build/runs/<timestamp>/` | `prepare.log`, `report.json`, and backups of replaced package files |
| USB: `Repair-Logs/prepare-<timestamp>/` | Preparation log/report; the same USB's EFI is the logging fallback |
| USB EFI: beside `EFI/OC/config.plist` | Original config backup |

Review logs before sharing; they can contain private paths and identifiers. A stopped multi-file copy can leave partial preparation: retain the backups, rerun the command, and require a passing final audit.

<details>
<summary><strong>Already downloaded the official packages?</strong></summary>

You can supply the exact pinned packages instead of downloading them. Mount the matching KDK DMG read-only to access its `KernelDebugKit.pkg`:

```bash
sudo python3 prepare_usb.py \
  --usb "/Volumes/Install macOS Tahoe" \
  --assets-pkg "/path/to/AutoPkg-Assets.pkg" \
  --kdk-pkg "/Volumes/Kernel Debug Kit/KernelDebugKit.pkg"
```

The same checksum checks apply. Use `--cache "/path/on/working-Mac/cache"` for a different host download cache, or `--config "/Volumes/EFI/EFI/OC/config.plist"` to explicitly select the existing same-USB EFI config.

</details>

## Optional Recovery fallback

**Experimental; not part of the normal preparation route.** Only if the installed system remains unusable, see [the separate Recovery guide](docs/RECOVERY.md). Add `--with-recovery-kit` to the preparation command to build its archives and tools. This optional path requires Xcode Command Line Tools and at least 15 GiB free host space. It is not required for the main installer preparation above.

## Sources and validation

[Official RC3 release](https://github.com/dortania/OpenCore-Legacy-Patcher/releases/tag/3.0.0-rc.3) · [Matching KDK](https://github.com/dortania/KdkSupportPkg/releases/tag/25G241) · [RC3 installer package placement](https://github.com/dortania/OpenCore-Legacy-Patcher/blob/3.0.0-rc.3/opencore_legacy_patcher/wx_gui/gui_macos_installer_flash.py#L443-L481) · [RC3 manual assets guidance](https://discord.com/channels/417165963327176704/1389230559674368062/1557563105897226298)

[OCLP booting without USB](https://dortania.github.io/OpenCore-Legacy-Patcher/POST-INSTALL.html#booting-without-usb-drive) · [OCLP post-install patch guidance](https://dortania.github.io/OpenCore-Legacy-Patcher/POST-INSTALL.html#applying-post-install-volume-patches) · [Testing and limitations](docs/TESTING.md) · [Separate troubleshooting history](docs/CASE-STUDY.md)

[Apple Command Line Tools installation](https://developer.apple.com/documentation/xcode/installing-the-command-line-tools) · [Python on macOS](https://docs.python.org/3/using/mac.html)

OpenCore, OCLP and the actual patches belong to their upstream contributors; the KDK is Apple's work. This repo supplies custom preparation code and documentation, developed with AI assistance. No upstream endorsement is implied. The repo contains source, not installer binaries, personal EFI configs or private logs. See [NOTICE.md](NOTICE.md) and [LICENSE](LICENSE).
