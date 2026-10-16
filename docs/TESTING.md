# Validation and limits

The original hardware result and the public packaging tests answer different questions.

## Physical-machine result

The owner confirmed a working Tahoe installation and completed user setup on a **mid-2014 MacBookPro11,3 only after erasing the internal drive again and reinstalling Tahoe from the fully modified USB**. KDK staging and repair attempts on the earlier installation had left it unusable. The public source preserves the recovery/staging logic, replaces the private USB identity with a creator-time binding, and uses the neutral service label `local.mbp113-repair`.

The automated launcher/staging checks below verify script behavior. They do not demonstrate that the script alone repaired the original installation, or that a clean reinstall is universally required.

The public packaging has not been run on a second physical Mac. There are no claimed performance, sleep/wake, GPU switching or future-update results. The sequence was not repeated with each dependency removed individually.

## Automated fixture checks

**2026-10-17 result:** all 56 checks passed on the preparation iMac. Generated test output remains local and ignored.

Run on a working macOS development machine:

```bash
./scripts/test.sh
```

The script builds and ad-hoc signs the x86_64 native utility, checks the Bash scripts' syntax, and runs these suites:

| Suite | Checks | Method |
| :--- | ---: | :--- |
| Creator, EFI and native utility | 10 | Temporary files; mocked disk metadata; native XML/binary plist and SHA-256 operations |
| Optional Recovery preparation and EFI discovery | 19 | Disposable USB/EFI fixtures; package building mocked, native deployment hashes executed; no real disks |
| Default installer-only preparation | 9 | Package/EFI fixtures and real Python deployment; automatic KDK image acquisition mocked; compiler/extraction prohibited |
| Normal-boot startup job | 13 | Disposable filesystem; disk, patcher, power, signature and reboot commands stubbed |
| Recovery staging | 5 | Disposable System/Data/USB/EFI fixtures; destructive or hardware commands stubbed |

The checks cover correct patch completion, incomplete graphics output despite exit zero, patcher failure, prior attempt, wrong model/build/volume group, absent or incorrect USB, read-only installer logging to EFI, missing filesystem UUID, wrong filesystem, payload corruption, paired Data staging and rejection of symlinked deployment destinations.

The EFI tests verify that only the three documented DataHub fields change by default, that the source object remains unchanged, that an explicit normal-boot request removes only `-x`, and that a conflicting model is rejected. The native checks cover nested arrays, Unicode, booleans, integers, XML/binary plists, stdin, missing keys, valid/corrupted manifests and path traversal rejection.

The optional Recovery preparation checks exercise a fresh kit, incomplete kit repair with backups, reuse and idempotence, normal-boot NVRAM replacement, audit-only operation without file/mode changes, permission repair, same-USB EFI discovery and read-only mounting. They also reject missing enabled kexts, conflicting models, an internal/wrong EFI, nested backup configs, symlink destinations, corrupt/duplicate manifests, download caches on the USB, and disk/config changes during preparation. The package-builder subprocess is replaced with tiny fixtures in these orchestration tests; actual extraction/layout is covered by the real-package check below.

The default installer-only checks verify that only the two pinned packages and scoped EFI settings are prepared; no Recovery archive, helper or daemon is created. They cover local and downloaded packages, read-only KDK mounting and detachment, repair with backups, repeat runs, audit-only operation, and preservation of old optional kit files. Tests fail if package expansion or compilation is invoked by the installer-only builder. The default audit checks packages and EFI, while `--with-recovery-kit --check` also requires the optional kit.

**These fixtures do not invoke OCLP or root-patch the development Mac.** Stubbing signature and disk commands allows testing the orchestration; it does not replace signature verification and real disk validation during actual preparation.

## Real-package assembly check

**2026-10-16 result:** assembly and the complete generated manifest passed using the pinned official packages. The download asset hashes were also compared with GitHub's release-asset digests.

On 2026-10-17 the payload verifier also accepted that existing real-package assembly without changing its files. The simplified installer-only builder then copied the actual pinned assets/KDK packages into a disposable host output, deployed them into another disposable host directory and verified both hashes. Extraction and compilation were prohibited during that check. It passed with exactly the two expected package files and no Recovery files; no physical USB was changed.

The public builder is also checked against the actual pinned RC3 assets package and matching Apple KDK package: expand both, verify the RC3 app signature and version, merge the KDK SDK payload, compile the utility, generate the runtime/KDK archives and verify the resulting complete manifest.

This check uses a disposable test partition identifier and a host output directory. It does not deploy to a USB, modify the host EFI, run package installation scripts or patch an installed OS.

## What remains outside these tests

- Live download availability and macOS disk metadata can change; checksums/build guards deliberately fail closed.
- A different macOS build, OCLP revision, model or graphics configuration needs separate review.
- The fixture files contain placeholders in place of actual app/kernel binaries. Only the real-package assembly check validates the authentic payload layout.
- A correct package manifest does not prove a future boot or root patch will succeed. Inspect the generated logs and verify a working user session.

No private machine identifiers or raw owner logs are used as public test fixtures.
