# Tahoe recovery for MacBookPro11,3

![Model: MacBookPro11,3](https://img.shields.io/badge/model-MacBookPro11%2C3-2563eb)
![macOS: 26.7.1](https://img.shields.io/badge/macOS-26.7.1%20%2825G241%29-111827)
![OCLP: RC3](https://img.shields.io/badge/OCLP-3.0.0--rc.3-f59e0b)
![Scope: single model](https://img.shields.io/badge/scope-single%20model-64748b)

**A documented recovery workflow for a mid-2014, 15-inch MacBook Pro with Intel Iris Pro and NVIDIA GT 750M graphics.**

The original clean installation stopped at a repeating Lilu model-information message. After the EFI correction, it reached a wallpaper-only screen before a user account could be created. This project records the changes, supplies an offline preparation tool, and stages OCLP's own root patcher to run before login.

**Reported outcome:** Tahoe works and first-user setup is complete **after a clean reinstall from the fully modified USB**. The owner confirmed that the internal drive was erased again first. Supplying the KDK and attempting repairs on the earlier installation had left the unusable setup screen in place. The erase and reinstall were the final successful step in this case.

> [!IMPORTANT]
> **The final reinstall matters:** complete the USB changes and offline dependency preparation **before** reinstalling. This case did not succeed merely by adding KDK files and rebooting the existing installation. Erasing the internal drive deletes its data; preserve a backup first. This is one machine's observed recovery sequence, not proof that every affected Mac requires an erase.

[What fixed what](#what-fixed-what) · [Prepare the USB](#prepare-the-usb) · [Clean reinstall from the modified USB](#clean-reinstall-from-the-modified-usb) · [Recovery helper](#run-in-recovery) · [Logs and rollback](#logs-and-rollback) · [Full troubleshooting record](docs/CASE-STUDY.md)

> [!IMPORTANT]
> This is an **unofficial, model-specific helper**, not an OCLP fork or an official Dortania release. It modifies the installed system through OCLP's root-patching process. Its guards intentionally accept **MacBookPro11,3 + Tahoe 26.7.1 build 25G241 + OCLP 3.0.0 RC3** only. Review the source and preserve a backup before using it.

## What fixed what

| Observed problem | Change used in this case | What the evidence establishes |
| :--- | :--- | :--- |
| Repeating `Lilu dev: failed to obtain model information, retrying...` | Set explicit DataHub model and board ID; enable `UpdateDataHub` | The owner reported that this cleared the Lilu boot loop. Exact prefix punctuation was not captured reliably. |
| Installer patch log could not find a matching KDK and selected wireless-only patches | Supply the exact **25G241 KDK** offline | The log showed a real missing dependency. Offline availability removes that network dependency. |
| Wallpaper appears, but no usable Setup Assistant, Dock, or menu bar | Finish the USB changes, then **erase the internal drive again and reinstall Tahoe from that USB** | The owner confirms the existing installation stayed unusable despite KDK staging/repair attempts. Working setup followed the clean reinstall. |
| Need to invoke OCLP without a working user session | Stage a one-attempt startup job to invoke RC3 `--patch_sys_vol` before login | This is the custom helper's function. It was not demonstrated to recover the original installation by itself. |
| Custom helper rejects the correct USB in Recovery | Match the **GPT partition UUID**, rather than requiring an HFS filesystem UUID | Recovery reported the partition identity while omitting filesystem identity. This was a bug in the custom helper. |
| Installer volume is mounted read-only | Try a writable source mount; otherwise log to the **same USB's EFI** | No formatting or repartitioning is involved. The target system is not force-remounted by the helper. |
| A wildcard command prints the options instead of running | Use one exact, quoted script path | Both an old `Image Volume` mount and an updated installer mount were visible. The wildcard passed the second script path as an argument. |

### Assets package versus KDK

These are different dependencies, not competing fixes:

| File | Purpose in this workflow | How it is supplied |
| :--- | :--- | :--- |
| `AutoPkg-Assets.pkg` | Provides the authentic RC3 app, privileged helper and bundled patch resources. The preparation tool extracts its app/helper without running its installer scripts. | Downloaded from the pinned official RC3 release, or supplied locally. |
| `KernelDebugKit.pkg` | Provides Apple's kernel resources for the matching OS build. The original log specifically reported this dependency missing. | Taken from the matching official KDK DMG, or supplied locally. |
| `KDK-25G241.tar.gz` | Lets Recovery stage that KDK on the writable Data volume without `pkgutil`. | Built locally from the verified Apple package, including its SDK payload. |
| `RC3-runtime.tar.gz` | Lets Recovery stage the verified RC3 app/helper without executing the AutoPkg postinstall in Recovery. | Built locally from the verified assets package. |
| `recovery-tool` | Small native utility for plist values, SHA-256, and free-space checks, without Python, Perl or newer `plutil` options in Recovery. | Compiled locally for x86_64 from the C source in this repository. |

The assets file does not itself fix graphics. The KDK does not contain OCLP's graphics patches. **The patcher resources and a usable matching KDK work together.** With working networking, OCLP can normally acquire dependencies itself; this case required offline staging. An already installed RC3 app could be another way to supply the app, but this helper deliberately uses a pinned, complete runtime.

**Why put both packages in `Library/Packages`?** RC3's [installer creation code](https://github.com/dortania/OpenCore-Legacy-Patcher/blob/3.0.0-rc.3/opencore_legacy_patcher/wx_gui/gui_macos_installer_flash.py#L443-L481) copies the assets package there and chainloads a matching KDK as `KDK.pkg`. The [official RC3 community announcement](https://discord.com/channels/417165963327176704/1389230559674368062/1557563105897226298) also identifies broken auto patching and directs users to place `AutoPkg-Assets.pkg` in that folder manually. This entry point checks both packages rather than assuming the normal USB creation step supplied them.

**Did `repair.sh` do nothing?** That is not established. It explicitly stages the runtime/KDK onto an existing installation and arms a pre-login patch attempt; it is not the USB preparation tool. The earlier installation remained unusable after those attempts. A successful clean reinstall with both installer packages available is consistent with the installer route helping, but no controlled test isolated the KDK, assets package or script individually.

The owner had already supplied the KDK during the unsuccessful repair attempts. Success came only after erasing and reinstalling from the fully modified USB. This does **not** establish the exact installer/root-patcher mechanism, or that every manual copy was individually necessary.

## Reported path to working setup

```mermaid
flowchart TD
    A[Working Mac: build OCLP installer for MacBookPro11,3] --> B[Verify and prepare offline files]
    B --> C[Apply the documented USB DataHub correction]
    C --> D[KDK staging and recovery attempts on old install still left unusable setup]
    D --> E[Back up, then erase the internal installation again]
    E --> F[Run full Tahoe installation from the fully modified USB]
    F --> G[Continue installation through USB OpenCore EFI]
    G --> H[Complete first-user setup and verify working desktop]
```

## Prepare the USB

Do this on a **working Mac**, which can be a different computer from the target laptop.

### 1. Start with an OCLP installer

Use **OCLP 3.0.0 RC3** to create a **Tahoe 26.7.1 / 25G241** installer and build OpenCore explicitly for **MacBookPro11,3**. This project does not download macOS, erase a USB, or build OpenCore for you.

Preparation requires Python **3.9 or newer**, Xcode Command Line Tools (`xcrun clang`), and approximately **15 GiB of free host storage**. The expanded packages and generated archives stay on the host while being built. A 32 GB installer USB was used in the original case; available space is checked before deployment.

Internet access is required to download any missing official packages; verified local packages can be supplied instead. Python and Xcode Command Line Tools are prerequisites on the working Mac and are not installed automatically by this script.

The native Recovery utility targets Intel x86_64. An Apple silicon preparation Mac also needs the ability to execute that Intel utility during verification; the original preparation host was an Intel iMac.

### 2. Complete the USB with one command

Download or clone this repo on the working Mac, open Terminal in its folder, and run:

```bash
git clone https://github.com/MrCee/oclp-tahoe-mbp113-recovery.git
cd oclp-tahoe-mbp113-recovery
sudo python3 prepare_usb.py --usb "/Volumes/Install macOS Tahoe"
```

For a previously cloned copy, run `git pull --ff-only` first. Substitute the installer volume's actual name. **This is the complete USB preparation command:** no separate `build_kit.py`, `fix_efi.py` or `repair.sh` invocation is needed on the working Mac. Administrator access lets it mount and update the USB's EFI and write protected installer folders.

| Automatic step | What the command does |
| :--- | :--- |
| Identify the target | Require an external HFS+ installer for **26.7.1 / 25G241** and its existing OpenCore configuration targeting **MacBookPro11,3**. |
| Locate its EFI | Discover and mount the EFI on the **same physical USB**, regardless of its current disk number or volume name. |
| Check boot files | Check the OpenCore boot files and every enabled ACPI, driver and kext file referenced by the config. Missing boot files stop preparation; rebuild OpenCore with RC3 rather than mixing arbitrary kext versions. |
| Supply installer packages | Download missing pinned official packages and place verified **`AutoPkg-Assets.pkg` and `KDK.pkg` in `Library/Packages/`**. Reuse existing packages only after checksum verification. |
| Prepare the offline fallback | Extract and validate the RC3 runtime and matching KDK including its SDK payload, build the Intel utility, and bind the Recovery kit to this USB's GPT partition identity. Package installer scripts are not run on the working Mac. |
| Repair an incomplete kit | Replace changed managed files with verified copies; preserve the old files under the host run's `usb-backups/` directory first. Unrelated installer files are retained. |
| Apply the EFI correction | Back up `config.plist`, set the three DataHub values below, remove temporary `-x`, and ensure OpenCore replaces saved `boot-args` on its next boot. Other boot arguments are retained. |
| Verify and record | Normalize the managed file modes, recheck hashes, paths, model and normal-boot settings; save `prepare.log` and `report.json` on both the working Mac and the USB. An incomplete preparation exits with an error. |

The command can be run again: a complete matching kit is reused, and an already correct EFI is not rewritten. Multi-file deployment is not a single transaction; an interrupted run can leave a partial kit. Retain the logs and host backups, then rerun the preparation command. A fresh final audit must pass before using it.

**The EFI changes:**

| Setting | Originally observed | Value used |
| :--- | :--- | :--- |
| `PlatformInfo → DataHub → SystemProductName` | Empty | `MacBookPro11,3` |
| `PlatformInfo → DataHub → BoardProduct` | Empty | `Mac-2BD1B31983FE1663` |
| `PlatformInfo → UpdateDataHub` | `false` | `true` |
| Apple NVRAM `Add → boot-args` | Temporary `-x` during testing | Remove only `-x`; retain other arguments |
| Apple NVRAM `Delete` list | May already include `boot-args` | Ensure it includes `boot-args`, so the configured normal-boot arguments replace the saved value |

The board ID belongs to **MacBookPro11,3**, not the preparation Mac. Rebuilding OpenCore later may replace these changes; rerun this command after rebuilding. The original bootloader binaries are retained. These checks verify referenced files exist; they do not certify every OpenCore setting, firmware state or future boot.

### 3. Confirm the final audit and eject

Preparation finishes with a `PASS` message after the audit. An independent repeat audit is optional:

```bash
sudo python3 prepare_usb.py --usb "/Volumes/Install macOS Tahoe" --check
```

`--check` changes no USB/EFI files or permissions; it may mount an unmounted EFI read-only. It reports a failure if anything still needs preparation. Safely eject both USB volumes before moving the USB to the MacBook.

> [!NOTE]
> This repo contains source and documentation, not macOS installers, OCLP packages, KDK payloads, personal EFI configurations or private logs. Downloads, archives, run logs and backups stay in the ignored host `build/` folder. USB-bound identifiers are generated locally.

<details>
<summary><strong>Local packages, custom EFI path and separate advanced tools</strong></summary>

The same all-in-one command accepts local packages if already downloaded. Mount the matching KDK DMG read-only to access its `KernelDebugKit.pkg`:

```bash
sudo python3 prepare_usb.py \
  --usb "/Volumes/Install macOS Tahoe" \
  --assets-pkg "/path/to/AutoPkg-Assets.pkg" \
  --kdk-pkg "/Volumes/Kernel Debug Kit/KernelDebugKit.pkg"
```

Use `--config "/Volumes/EFI/EFI/OC/config.plist"` only to explicitly select the existing config; same-USB checks still apply. Use `--cache "/path/on/working-Mac/cache"` to choose a host download cache. All supplied and cached packages must pass the pinned checksums; there is no skip-verification option.

The lower-level `build_kit.py --download --deploy` and `fix_efi.py --normal-boot` remain available for developers. They perform separate parts of preparation and are **not** the recommended from-scratch path. The all-in-one entry point coordinates both and adds guarded repair, backups and final checks.

Official packages: [OCLP RC3](https://github.com/dortania/OpenCore-Legacy-Patcher/releases/tag/3.0.0-rc.3) · [KDK 25G241](https://github.com/dortania/KdkSupportPkg/releases/tag/25G241).

</details>

## Clean reinstall from the modified USB

**This was the final step that succeeded on the owner's Mac.** The earlier installation remained unusable after the offline KDK had been supplied and the repair attempts had run. Rebooting that same installation was not sufficient.

1. Complete **all USB preparation first**: the correct OCLP model target, DataHub correction, offline RC3/KDK files, removal of temporary `-x`, and the prepared-kit checks above.
2. Back up any data to preserve. The owner then **erased the internal drive again** in Disk Utility. This is destructive; identify the intended internal target carefully and retain the prepared USB.
3. Boot **Option → USB EFI Boot → Install macOS Tahoe** and run a **full Tahoe installation onto the erased internal target**, using the fully modified USB.
4. During installation restarts, continue through the USB's OpenCore EFI. Select the continuing installation entry when present, then the internal macOS entry once installation is complete. Keep the USB connected while it supplies OpenCore.
5. Boot normally, complete first-user setup and confirm a usable desktop. This was the owner's successful result after the clean reinstall.

This records the sequence that worked on one machine. It does not prove every affected Mac needs an erase, or that a KDK copied to the USB is automatically consumed by every installer path. The helper's explicit staging route is described below; its presence alone was not sufficient to rescue the owner's earlier installation.

## Run in Recovery

**Additional helper route, not a replacement for the clean reinstall reported above.** These script steps require Tahoe **26.7.1 / 25G241 to be installed on the internal disk already**. They describe how to stage dependencies and invoke OCLP when a graphical session is unavailable. The helper does not erase the disk or install macOS. Running it on the owner's previous installation did not, by itself, produce the working result.

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
7. Choose **USB EFI Boot → internal MacIntosh** again and check whether Setup Assistant and the desktop are usable. Script completion alone does not establish recovery. In the owner's case, a subsequent erase and full reinstall from the modified USB was still required.

> [!TIP]
> If the USB was removed and reattached while Recovery stayed open, an old mount may remain visible. Before running anything, identify the copies:
>
> ```bash
> grep 'repair kit v' /Volumes/*/repair.sh
> ```
>
> Then use **one exact quoted path**. Do not run `/bin/bash /Volumes/*/repair.sh`: multiple matches become extra script arguments. Restarting Recovery with the updated USB inserted also avoids stale mounts.

There is no reliable "wait exactly 30 minutes" rule. Cache rebuilding can take time and the screen may stay unusable during it. Inspect the logs to establish whether the job started or finished; the script has no timed force-kill and makes no automatic repeated patch attempts.

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

## Scope and evidence

**Why this laptop?** MacBookPro11,3 combines Haswell Iris Pro and Kepler dedicated graphics. The supplied root-patch checks expect both. Dedicated graphics plausibly contributed to the graphics difficulty, but were not proven to cause the model-information error or every setup failure.

**Could this help other Macs?** Offline dependencies, robust partition identification and pre-login CLI patching are useful ideas elsewhere. Model IDs, board IDs, required packages and graphics patchsets are not interchangeable. Other machines remain **unsupported by this helper** until separately reviewed and tested.

**What was unnecessary to repeat?** See the [case study](docs/CASE-STUDY.md) for safe-mode trials, failed Recovery package commands, the original helper UUID assumption and duplicate-mount mistakes. They are documented as troubleshooting history, not required installation steps.

The public packaging layer binds a new USB identity and uses a neutral service label. These packaging changes are tested separately from the owner's original hardware success; they have not been re-tested on a second physical Mac.

## Repeating the test from scratch

To compare with the normal RC3 path, first create a fresh standard installer and test it **before** running this tool. Record the installer/OCLP versions, failure stage and relevant logs. Then run the one-command preparation on that same USB, retain its log/report, and retry the complete installation path. The owner's successful retry included erasing the internal target again; running the tool on the USB does not modify or repair an already installed system automatically.

Do not also run `repair.sh` during the initial comparison unless the fallback is needed. That keeps the installer-path test separate from the custom pre-login repair route. A successful retry still tests the combined USB changes; it does not prove which individual package or EFI value was necessary.

## Development and validation

Build the native utility on macOS, then run the tests:

```bash
./scripts/test.sh
```

The suite exercises disposable filesystem fixtures with disk, reboot and patcher commands replaced by stubs. It covers completed and incomplete patch attempts, wrong model/build/volume group, missing USB, read-only installer logging to EFI, damaged payloads, preparation and EFI changes. It never root-patches the development Mac. Details and results are in [TESTING.md](docs/TESTING.md).

## Credits and project boundaries

The actual OpenCore bootloader, OCLP app, dependency handling and graphics patches are the work of **Dortania, OpenCore Legacy Patcher contributors, Acidanthera and their upstream projects**. Apple's KDK remains Apple's work. This project supplies orchestration, native diagnostic helpers and a documented troubleshooting record.

The custom code and documentation were developed with **AI assistance**, then checked with automated tests and the hardware outcome reported above. No upstream endorsement is implied. See [NOTICE.md](NOTICE.md) and [LICENSE](LICENSE).

For an upstream bug, first check existing reports and discuss the evidence in the [OpenCore Patcher Paradise community](https://github.com/dortania/OpenCore-Legacy-Patcher#support), as requested by [OCLP's issue template](https://github.com/dortania/OpenCore-Legacy-Patcher/blob/main/.github/ISSUE_TEMPLATE/bug_report.yml). This repo's issues are for the custom helper and its documentation.
