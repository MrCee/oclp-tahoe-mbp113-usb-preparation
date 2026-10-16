#!/bin/bash
# Entry point: /bin/bash "/Volumes/Image Volume/repair.sh"
# Recovery stages a one-attempt, pre-login OCLP CLI job on the installed Data volume.
set -eE -o pipefail
export PATH=/usr/bin:/bin:/usr/sbin:/sbin
USB=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)
KIT="$USB/MBP113-Repair"
[ -f "$KIT/common.sh" ] || { echo 'Repair kit missing beside this script.'; exit 1; }
. "$KIT/common.sh"
MODE=${1:---repair}
case "$MODE" in --repair|--check|--disable) ;; *) echo 'Options: --repair (default), --check, --disable'; exit 2;; esac
[ -x "$RECOVERY_TOOL" ] || die 'The bundled Recovery helper is missing or cannot execute.'
"$RECOVERY_TOOL" lint "$KIT/$LABEL.plist" >/dev/null || die 'The bundled Recovery helper cannot run or the service plist is damaged.'
if ! prepared_usb "$USB"; then
    /usr/sbin/diskutil info "$USB" || true
    die "USB identity check failed: expected GPT partition $USB_PARTITION_UUID; found $(disk_value "$USB" DiskUUID || true). No target changes made."
fi

LOG_VOLUME=$(log_volume "$USB") || die 'Neither the installer volume nor its own EFI partition is writable. Cannot log to USB; no target changes made.'
RUN=$(/bin/date '+%Y%m%d-%H%M%S')-$$
LOGDIR="$LOG_VOLUME/Repair-Logs/$RUN-recovery"
/bin/mkdir -p "$LOGDIR"
exec > >(/usr/bin/tee -a "$LOGDIR/repair.log") 2>&1
trap 'r=$?; say "Command failed (status $r), line $LINENO. Logs: $LOGDIR"; /bin/sync; exit "$r"' ERR
say "MBP11,3 repair kit v2; mode $MODE; model $(model)"
say "USB log directory: $LOGDIR"
/usr/sbin/diskutil info -plist "$USB" > "$LOGDIR/usb-info.plist"
say "Verified USB GPT partition $USB_PARTITION_UUID (filesystem UUID is optional)."
/usr/sbin/diskutil list > "$LOGDIR/disks.txt"
/usr/sbin/diskutil apfs listVolumeGroups -plist > "$LOGDIR/volume-groups.plist"
/usr/sbin/sysctl kern.bootargs > "$LOGDIR/bootargs.txt" 2>&1 || true

if [ "$MODE" = --check ]; then
    say 'Checking prepared USB files only. Internal disks will not be changed.'
    (cd "$USB" && "$RECOVERY_TOOL" sha-check MBP113-Repair/SHA256SUMS)
    "$RECOVERY_TOOL" lint "$KIT/$LABEL.plist"
    /bin/bash -n "$USB/repair.sh" "$KIT/common.sh" "$KIT/startup-repair.sh"
    say 'USB checks passed.'
    exit 0
fi
[ "$EUID" = 0 ] || die 'Use the USB installer Recovery Terminal, which runs as root.'
[ "$(model)" = "$EXPECTED_MODEL" ] || die 'Wrong computer: repair is restricted to MacBookPro11,3.'
[ -e /System/Library/BaseSystem ] || die 'Run staging from USB installer Recovery, not from an installed macOS desktop.'

# Find exactly one internal installation of this build. Names and disk numbers
# may change; choose its Data volume using the APFS volume-group relationship.
SYSTEM=''; COUNT=0
for v in /Volumes/*; do
    [ -d "$v" ] || continue
    p="$v/System/Library/CoreServices/SystemVersion.plist"
    [ "$(value "$p" ProductBuildVersion)" = "$EXPECTED_BUILD" ] || continue
    [ "$(value "$p" ProductVersion)" = "$EXPECTED_VERSION" ] || continue
    [ "$(disk_value "$v" Internal)" = true ] || continue
    [ "$(disk_value "$v" FilesystemType)" = apfs ] || continue
    SYSTEM="$v"; COUNT=$((COUNT + 1))
done
[ "$COUNT" = 1 ] || die "Found $COUNT mounted internal Tahoe $EXPECTED_BUILD systems; mount/unlock the intended installation in Disk Utility first."
GROUP=$(disk_value "$SYSTEM" APFSVolumeGroupID)
[ -n "$GROUP" ] || die 'System volume group is missing.'
GROUPS_PLIST="$LOGDIR/volume-groups.plist"
DATA_DEVICE=''; DATA_COUNT=0; ci=0
while value "$GROUPS_PLIST" "Containers.$ci.ContainerReference" >/dev/null; do
    gi=0
    while value "$GROUPS_PLIST" "Containers.$ci.VolumeGroups.$gi.APFSVolumeGroupUUID" >/dev/null; do
        if [ "$(value "$GROUPS_PLIST" "Containers.$ci.VolumeGroups.$gi.APFSVolumeGroupUUID")" = "$GROUP" ]; then
            vi=0
            while value "$GROUPS_PLIST" "Containers.$ci.VolumeGroups.$gi.Volumes.$vi.DeviceIdentifier" >/dev/null; do
                if [ "$(value "$GROUPS_PLIST" "Containers.$ci.VolumeGroups.$gi.Volumes.$vi.Role")" = Data ]; then
                    DATA_DEVICE=$(value "$GROUPS_PLIST" "Containers.$ci.VolumeGroups.$gi.Volumes.$vi.DeviceIdentifier")
                    DATA_COUNT=$((DATA_COUNT + 1))
                fi
                vi=$((vi + 1))
            done
        fi
        gi=$((gi + 1))
    done
    ci=$((ci + 1))
done
[ "$DATA_COUNT" = 1 ] || die 'Could not identify a unique paired Data volume.'
/usr/sbin/diskutil mount "$DATA_DEVICE"
DATA=$(disk_value "$DATA_DEVICE" MountPoint)
[ -n "$DATA" ] && [ "$DATA" != / ] || die 'Unsafe Data mount point.'
[ "$(disk_value "$DATA" Internal)" = true ] || die 'Paired Data volume is not internal.'
[ "$(disk_value "$DATA" APFSVolumeGroupID)" = "$GROUP" ] || die 'Volume group mismatch.'
[ -d "$DATA/Library" ] && [ -d "$DATA/Users" ] || die 'Target Data structure is incomplete.'
writable "$DATA" || die 'Data is not writable; unlock/mount it in Disk Utility first.'
ROOT="$DATA/$RELATIVE_ROOT"
DAEMON="$DATA/Library/LaunchDaemons/$LABEL.plist"
say "Matched System: $SYSTEM; Data: $DATA; volume group: $GROUP"
/usr/sbin/diskutil info -plist "$SYSTEM" > "$LOGDIR/system-info.plist"
/usr/sbin/diskutil info -plist "$DATA" > "$LOGDIR/data-info.plist"

# Collect evidence before replacing files. Private logs remain on this USB.
/bin/mkdir -p "$LOGDIR/before" "$LOGDIR/before/OCLP"
record="$SYSTEM/System/Library/CoreServices/OpenCore-Legacy-Patcher.plist"
[ ! -f "$record" ] || /bin/cp -p "$record" "$LOGDIR/before/patch-record.plist"
for f in "$DATA"/Users/Shared/*OpenCore*log "$DATA"/Users/Shared/.OCLP* "$DATA"/Users/Shared/.com.dortania.opencore-legacy-patcher.plist; do
    [ ! -f "$f" ] || /bin/cp -p "$f" "$LOGDIR/before/OCLP/"
done
if [ -f "$DATA/private/var/log/install.log" ]; then
    /usr/bin/tail -n 3000 "$DATA/private/var/log/install.log" > "$LOGDIR/before/install-log-tail.txt"
fi
if [ "$MODE" = --disable ]; then
    [ ! -f "$DAEMON" ] || /bin/mv "$DAEMON" "$LOGDIR/disabled-daemon.plist"
    say 'Custom startup repair disabled. Logs, original files and OCLP patches are retained.'
    /bin/sync
    exit 0
fi

say 'Verifying kit and offline payload hashes. This can take several minutes.'
(cd "$USB" && "$RECOVERY_TOOL" sha-check MBP113-Repair/SHA256SUMS)
FREE_KB=$("$RECOVERY_TOOL" free-kb "$DATA")
[ "$FREE_KB" -gt 15728640 ] || die 'At least 15 GiB free space is required on the target.'
# Refuse symlinked destinations before privileged extraction or service setup.
for p in "$DATA/Library" "$DATA/Library/Application Support" "$DATA/Library/Application Support/Dortania" "$DATA/$APP" "$DATA/Library/PrivilegedHelperTools" "$DATA/$HELPER" "$DATA/Library/LaunchDaemons" "$DAEMON" "$DATA/Library/Developer" "$DATA/Library/Developer/KDKs" "$DATA/Library/Developer/KDKs/$KDK_NAME" "$ROOT"; do
    [ ! -L "$p" ] || die "Unexpected symbolic link at $p"
done
/bin/mkdir -p "$ROOT" "$DATA/Library/LaunchDaemons" "$DATA/Library/PrivilegedHelperTools" "$DATA/Library/Developer/KDKs" "$DATA/Library/Application Support/Dortania"
/bin/mkdir "$ROOT/.staging-lock" || die 'A previous staging session is incomplete; retain its logs before proceeding.'
trap '/bin/rmdir "$ROOT/.staging-lock" 2>/dev/null || true' EXIT
BACKUP="$ROOT/backups/$RUN"
/bin/mkdir -p "$BACKUP"
for f in common.sh startup-repair.sh recovery-tool state.plist attempted completed; do
    [ ! -e "$ROOT/$f" ] || /bin/cp -p "$ROOT/$f" "$BACKUP/"
done
[ ! -f "$DAEMON" ] || /bin/cp -p "$DAEMON" "$BACKUP/previous-daemon.plist"
# Disable any earlier custom job until staging completes successfully.
[ ! -f "$DAEMON" ] || /bin/rm -f "$DAEMON"
say 'Installing the verified RC3 app and its helper from the authentic AutoPkg payload.'
if [ -e "$DATA/$APP" ]; then /bin/mv "$DATA/$APP" "$BACKUP/OpenCore-Patcher.app"; fi
if [ -e "$DATA/$HELPER" ]; then /bin/cp -p "$DATA/$HELPER" "$BACKUP/original-privileged-helper"; fi
/usr/bin/tar -xzf "$KIT/RC3-runtime.tar.gz" -C "$DATA"
/usr/sbin/chown -R 0:0 "$DATA/$APP"
/bin/chmod -R go-w "$DATA/$APP"
/usr/sbin/chown 0:0 "$DATA/$HELPER"
/bin/chmod 4755 "$DATA/$HELPER"
info="$DATA/$APP/Contents/Info.plist"
[ "$(value "$info" Github.Branch)" = refs/tags/3.0.0-rc.3 ] || die 'Extracted runtime is not RC3.'
[ -x "$DATA/$APP/Contents/MacOS/OpenCore-Patcher" ] || die 'Runtime executable missing.'
if [ -x /usr/bin/codesign ]; then /usr/bin/codesign --verify --deep --strict "$DATA/$APP"; fi

KDK="$DATA/Library/Developer/KDKs/$KDK_NAME"
if kdk_valid "$KDK"; then
    say 'Matching KDK already passes RC3 legacy validation; using it.'
else
    if [ -e "$KDK" ]; then /bin/mv "$KDK" "$BACKUP/$KDK_NAME"; fi
    say 'Extracting the matching Apple KDK onto the writable Data volume.'
    /usr/bin/tar -xzf "$USB/KDK-25G241.tar.gz" -C "$DATA/Library/Developer/KDKs"
    kdk_valid "$KDK" || die 'Extracted KDK failed validation.'
fi
/usr/sbin/chown -R 0:0 "$KDK"
/bin/cp "$KIT/common.sh" "$KIT/startup-repair.sh" "$KIT/recovery-tool" "$ROOT/"
/usr/sbin/chown 0:0 "$ROOT" "$ROOT/common.sh" "$ROOT/startup-repair.sh" "$ROOT/recovery-tool"
/bin/chmod 755 "$ROOT" "$ROOT/startup-repair.sh" "$ROOT/recovery-tool"
/bin/chmod 644 "$ROOT/common.sh"
# Values originate from diskutil, not user-controlled shell code.
/bin/cat > "$ROOT/state.plist" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict><key>VolumeGroup</key><string>$GROUP</string><key>USBPartition</key><string>$USB_PARTITION_UUID</string></dict></plist>
EOF
/usr/sbin/chown 0:0 "$ROOT/state.plist"
/bin/chmod 644 "$ROOT/state.plist"
"$RECOVERY_TOOL" lint "$ROOT/state.plist"
/bin/cp "$KIT/$LABEL.plist" "$DAEMON"
/usr/sbin/chown 0:0 "$DAEMON"
/bin/chmod 644 "$DAEMON"
"$RECOVERY_TOOL" lint "$DAEMON"
/bin/rm -f "$ROOT/attempted" "$ROOT/completed"
[ ! -d "$ROOT/.running" ] || /bin/rmdir "$ROOT/.running"
/bin/mkdir -p "$ROOT/logs"
/bin/cp -R "$LOGDIR" "$ROOT/logs/"
/bin/sync
say 'ARMED: one RC3 root-patch attempt will run before login on the next NORMAL internal-system boot.'
say 'Keep USB inserted and connect the charger. Cache rebuilding can take time; use the USB logs to check progress.'
say 'The job records live USB logs. On verified patch completion it reboots once and disables itself.'
say 'At startup: hold Option, choose USB EFI Boot, then choose the internal MacIntosh (not Install macOS Tahoe).'
say 'Recovery will restart in 20 seconds. Ctrl-C cancels this restart; the repair remains armed.'
/bin/sleep 20
/bin/sync
/sbin/reboot
