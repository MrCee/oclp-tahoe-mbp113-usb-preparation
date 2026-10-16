# Tahoe USB fix for MacBookPro11,3

![Model: MacBookPro11,3](https://img.shields.io/badge/model-MacBookPro11%2C3-2563eb)
![macOS: 26.7.1](https://img.shields.io/badge/macOS-26.7.1%20%2825G241%29-111827)
![OCLP: RC3](https://img.shields.io/badge/OCLP-3.0.0--rc.3-f59e0b)

**Prepare your USB, then install Tahoe. One preparation command handles the installer packages and EFI corrections.**

For the **mid-2014 15-inch MacBook Pro, MacBookPro11,3**, with Intel Iris Pro and NVIDIA GT 750M. This unofficial helper supports **Tahoe 26.7.1 / build 25G241 and OCLP 3.0.0 RC3 only**. A different model or installer build stops preparation.

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

## 2. Run the USB fix

On the working Mac, open Terminal and run:

```bash
git clone https://github.com/MrCee/oclp-tahoe-mbp113-recovery.git
cd oclp-tahoe-mbp113-recovery
sudo python3 prepare_usb.py --usb "/Volumes/Install macOS Tahoe"
```

If you already cloned the repo, open that folder and run `git pull --ff-only` instead of cloning it again. Then run the same preparation command. Replace the USB volume name if yours is different.

**The command automatically:**

- Finds the EFI on that same external USB and checks the existing OpenCore target and referenced boot files.
- Downloads and verifies the pinned official **RC3 `AutoPkg-Assets.pkg`** and matching **`KDK.pkg`**, then copies them into the USB's **`Library/Packages/`**. Correct copies are reused; changed managed files are backed up before replacement.
- Backs up `config.plist`, sets DataHub `SystemProductName` to `MacBookPro11,3`, `BoardProduct` to `Mac-2BD1B31983FE1663`, and `UpdateDataHub` to `true`.
- Removes temporary `-x` Safe Boot and ensures OpenCore replaces saved `boot-args`; other boot arguments are retained.
- Sets package permissions, verifies the result, and saves a log/report on both the working Mac and USB.

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

**There is no `repair.sh` step in this main route.** The command prepares the USB; it does not erase the internal disk, install macOS or prove a successful boot. The owner reported success with these USB changes followed by a clean reinstall; this simplified preparation path still needs a fresh physical-machine test.

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

Only if the installed system remains unusable, see [the separate Recovery guide](docs/RECOVERY.md). Add `--with-recovery-kit` to the preparation command to build its archives and tools. This optional path requires Xcode Command Line Tools and at least 15 GiB free host space. It is not required for the main installer preparation above.

## Sources and validation

[Official RC3 release](https://github.com/dortania/OpenCore-Legacy-Patcher/releases/tag/3.0.0-rc.3) · [Matching KDK](https://github.com/dortania/KdkSupportPkg/releases/tag/25G241) · [RC3 installer package placement](https://github.com/dortania/OpenCore-Legacy-Patcher/blob/3.0.0-rc.3/opencore_legacy_patcher/wx_gui/gui_macos_installer_flash.py#L443-L481) · [RC3 manual assets guidance](https://discord.com/channels/417165963327176704/1389230559674368062/1557563105897226298)

[OCLP post-install patch guidance](https://dortania.github.io/OpenCore-Legacy-Patcher/POST-INSTALL.html#applying-post-install-volume-patches) · [Testing and limitations](docs/TESTING.md) · [Separate troubleshooting history](docs/CASE-STUDY.md)

OpenCore, OCLP and the actual patches belong to their upstream contributors; the KDK is Apple's work. This repo supplies custom preparation code and documentation, developed with AI assistance. No upstream endorsement is implied. The repo contains source, not installer binaries, personal EFI configs or private logs. See [NOTICE.md](NOTICE.md) and [LICENSE](LICENSE).
