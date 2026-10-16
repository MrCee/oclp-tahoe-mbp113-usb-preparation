# From a Lilu loop to completed Tahoe setup

**Final outcome reported by the owner:** Tahoe is working and first-user setup is complete **after erasing the internal drive again and doing a full reinstall from the fully modified USB**. The earlier installation remained unusable despite KDK staging and repair attempts. The final clean reinstall is an essential part of the reported sequence.

This record describes one mid-2014 15-inch **MacBookPro11,3**, with Intel Iris Pro (Haswell) and NVIDIA GeForce GT 750M (Kepler), using **OCLP 3.0.0 RC3** and **Tahoe 26.7.1, build 25G241**. The internal disk had been wiped. The USB supplied the working OpenCore EFI during recovery. No working user session existed when the repair was prepared.

This is a troubleshooting sequence, not a controlled experiment. The final outcome confirms the combined workflow worked on this machine. It does not establish that every intermediate step was necessary, nor that this is an upstream bug affecting all examples of this model.

## 1. The installer was built on two computers

The owner built the USB on the target MacBook Pro and separately on an iMac, explicitly selecting MacBookPro11,3. Both attempts produced the same early boot symptom. That makes a simple wrong-host selection an inadequate explanation; the upstream cause has not been established.

The observed error text was:

```text
Lilu dev: failed to obtain model information, retrying...
```

The original reports varied on whether the prefix included an `@`. The repeated model-information failure is the reliable part of the report.

## 2. Explicit DataHub values cleared the loop

The USB's OpenCore configuration already targeted the correct model, but these DataHub settings were empty or disabled:

| OpenCore setting | Before | After |
| :--- | :--- | :--- |
| `PlatformInfo/DataHub/SystemProductName` | Empty | `MacBookPro11,3` |
| `PlatformInfo/DataHub/BoardProduct` | Empty | `Mac-2BD1B31983FE1663` |
| `PlatformInfo/UpdateDataHub` | `false` | `true` |

The board ID belongs to the target model. It was not copied from the iMac. The owner confirmed that applying these values allowed boot to pass the Lilu loop. This is the clearest independently observed before/after result in the sequence.

These values should not be copied to other models. A later OpenCore rebuild may replace the manual correction. The public `fix_efi.py` checks the OCLP target and same-USB EFI relationship, then preserves a config backup before writing the three fields.

## 3. Reaching wallpaper was not a completed installation

The machine next displayed water-and-rocks wallpaper without a usable Dock, menu bar or Spotlight. Setup had never asked the owner to create a user. Treating this as a normal logged-in desktop made graphical launch instructions unhelpful.

Shift/Safe Boot was tried. The wallpaper did not establish whether Safe Boot was active. A temporary `-x` boot argument was subsequently removed so the staged OCLP patcher would run during a normal boot. The helper explicitly refuses to patch with `-x` active.

Dedicated graphics may have contributed to the difficulty reaching usable setup, but that is not a demonstrated explanation for every symptom. The model-information failure, offline dependencies and custom helper errors are separate observations.

## 4. Logs identified a missing matching KDK

Recovery Terminal and photographs of multi-screen output were used to inspect the patch record and installer logs. The RC3 patch record showed **Modern Wireless Common**, without the required Haswell and Kepler graphics patchsets. Dependency acquisition had failed, including DNS/network errors and failure to find the matching KDK.

The matching Apple **KDK_26.7.1_25G241.kdk** was supplied offline. OCLP's RC3 app, privileged helper and bundled patch resources were supplied from the official **AutoPkg-Assets.pkg**.

| Question | Finding |
| :--- | :--- |
| Was the KDK missing? | The diagnostic record specifically showed a missing matching KDK and a wireless-only patch result. |
| Does the assets package replace the KDK? | No. It supplies the patcher runtime/resources; the KDK supplies matching kernel resources. |
| Was manually copying the assets package alone sufficient? | No such result was demonstrated. The custom workflow extracts and stages its runtime explicitly. |
| Was every manually copied package essential? | Not established. An already available complete RC3 runtime could potentially supply the same app/resources. |
| Was `Universal-Binaries.dmg` unmounting an error? | The unmount line was cleanup; the missing dependency and skipped graphics were the useful evidence. |
| Was a separate MetallibSupportPkg added? | No. The RC3 source predicates for Haswell/Kepler do not require that package on Tahoe; do not generalize Sequoia advice to this case. |

RC3's [installer creation code](https://github.com/dortania/OpenCore-Legacy-Patcher/blob/3.0.0-rc.3/opencore_legacy_patcher/wx_gui/gui_macos_installer_flash.py#L443-L481) supplies the assets package and chainloads `KDK.pkg` under the USB's `Library/Packages/`. The [official RC3 announcement](https://discord.com/channels/417165963327176704/1389230559674368062/1557563105897226298) separately documents broken auto patching and manual assets placement. These corroborate the offline installer-package workaround; they do not isolate what caused this machine's eventual success. The public `prepare_usb.py` now coordinates package placement, Recovery kit preparation, EFI correction and final audit in one working-Mac command.

Sources: [RC3 release](https://github.com/dortania/OpenCore-Legacy-Patcher/releases/tag/3.0.0-rc.3), [matching KDK](https://github.com/dortania/KdkSupportPkg/releases/tag/25G241), [Haswell patch definition](https://github.com/dortania/OpenCore-Legacy-Patcher/blob/3.0.0-rc.3/opencore_legacy_patcher/sys_patch/patchsets/hardware/graphics/intel_haswell.py), [Kepler patch definition](https://github.com/dortania/OpenCore-Legacy-Patcher/blob/3.0.0-rc.3/opencore_legacy_patcher/sys_patch/patchsets/hardware/graphics/nvidia_kepler.py).

## 5. Recovery needed an offline staging route

Recovery lacked `sudo` and `pkgutil`; it already ran a root shell. Trying to install the KDK package against the read-only System volume did not provide a usable route. These failed commands are not required steps.

The offline staging approach prepared verified archives on the functioning iMac, then extracted the KDK into the installation's paired, writable **Data volume** under `Library/Developer/KDKs/`. The RC3 runtime was staged on that same Data volume. Both KDK and SDK payloads are included in the public builder. This staging did not by itself make the earlier installation usable; the later clean reinstall still mattered.

A small native C utility replaced assumptions about Python, Perl or modern plist command options being available in Recovery. It reads XML/binary plists, calculates SHA-256 and reports free space. The actual patching still belongs to OCLP.

## 6. Two custom-helper issues were corrected

The first helper said **“This is not a prepared USB volume”** because it required an HFS filesystem UUID that Recovery's `diskutil info` output omitted. Recovery did report the GPT partition UUID. Version 2 used that partition identity, verified the external HFS source, and located the EFI on the same physical USB for logging when the installer mount stayed read-only.

This was a bug in the custom helper, not evidence of an OCLP USB-permissions bug.

Removing and reattaching the USB without restarting Recovery also left both an older `Image Volume` mount and the newer installer mount visible. Running a wildcard script path supplied the second script as an argument to the first, so the options screen kept appearing. An exact quoted path to the updated script fixed that invocation mistake.

## 7. A pre-login root-patch launcher was staged

The final staging script validated the model, installed build, target APFS volume group and USB identity. It preserved relevant logs and previous app/helper files, staged the matching KDK and authentic RC3 runtime, then installed a one-attempt startup job.

The job was configured to invoke RC3's `--patch_sys_vol` command on the next **normal** internal-system boot through **USB EFI Boot**, without depending on a user account, Dock or Spotlight. It records local and live USB logs, falling back to the same USB's EFI if necessary. This describes the launcher's design; it is not evidence that this step alone fixed the owner's existing installation.

Automatic completion required all of:

- A zero OCLP exit status and successful log writing.
- OCLP's `- Patching complete` message.
- Execution of the **Intel Haswell** patchset.
- Execution of the **Nvidia Kepler** patchset.

Only then would the job disable itself and restart once. Failures retained evidence without an automatic patch/reboot loop. It did not create an account, bypass Setup Assistant, erase the disk, install an internal OpenCore EFI, or invent additional root patches.

## 8. Final successful step: erase and reinstall from the modified USB

The owner clarified that **the earlier installation still showed the unusable desktop after the KDK was installed and the USB/recovery changes were made**. They initially expected those changes to be enough, but they were not.

The successful order was:

1. Finish the USB EFI changes and offline dependency preparation.
2. Erase the internal drive again.
3. Run a full Tahoe installation from that fully modified USB.
4. Complete first-user setup and reach a working desktop.

The reported result must therefore include the clean reinstall. It should not be summarized as “copy the KDK, run the script and the original installation is fixed.” Erasing removes existing data, so a reader reproducing that route must preserve a backup first. This is the owner's observed result, not a universal requirement for every Mac or proof of exactly how the installer used each staged component.

No post-success performance benchmark, GPU-switching test, sleep/wake qualification or update test has been claimed.

## What to reproduce, and what to leave as history

The [README](../README.md) presents USB preparation followed by the successful clean-reinstall sequence, with the custom Recovery helper documented separately. The failed Recovery package installation, duplicate mounts, original UUID assumption and repeated attempts to launch tools from the unusable setup screen are history, not additional repairs to repeat.

There is no established “wait exactly 30 minutes” requirement. Progress should be judged from logs and a successful user session, not wallpaper or an arbitrary delay.

The public source uses a neutral service name and stamps a new USB's partition identity during preparation. These packaging changes have automated coverage; they are not a claim of a second physical-machine validation. Upstream OCLP deserves credit for the patches and boot support. This repository documents and automates the surrounding recovery work.
