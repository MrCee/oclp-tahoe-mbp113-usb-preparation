#!/bin/bash
# Compatible with Apple's Bash 3.2 and Recovery's limited tool set.
export PATH=/usr/bin:/bin:/usr/sbin:/sbin
export LC_ALL=C
EXPECTED_MODEL=MacBookPro11,3
EXPECTED_BUILD=25G241
EXPECTED_VERSION=26.7.1
USB_PARTITION_UUID=__USB_PARTITION_UUID__
RECOVERY_TOOL="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)/recovery-tool"
LABEL=local.mbp113-repair
RELATIVE_ROOT='Library/Application Support/MBP113-Repair'
HELPER='Library/PrivilegedHelperTools/com.dortania.opencore-legacy-patcher.privileged-helper'
APP='Library/Application Support/Dortania/OpenCore-Patcher.app'
KDK_NAME=KDK_26.7.1_25G241.kdk

value() { "$RECOVERY_TOOL" value "$1" "$2" 2>/dev/null; }
disk_value() { /usr/sbin/diskutil info -plist "$1" 2>/dev/null | "$RECOVERY_TOOL" value - "$2" 2>/dev/null; }
model() { /usr/sbin/sysctl -n hw.model; }
say() { printf '%s %s\n' "$(/bin/date '+%Y-%m-%d %H:%M:%S')" "$*"; }
die() { say "STOP: $*"; exit 1; }
hash_file() { "$RECOVERY_TOOL" sha256 "$1"; }
check_hash() { [ -f "$1" ] && [ "$(hash_file "$1")" = "$2" ]; }
kdk_valid() {
    local k="$1" f
    [ "$(value "$k/System/Library/CoreServices/SystemVersion.plist" ProductBuildVersion)" = "$EXPECTED_BUILD" ] || return 1
    for f in System.kext/PlugIns/Libkern.kext/Libkern apfs.kext/Contents/MacOS/apfs IOUSBHostFamily.kext/Contents/MacOS/IOUSBHostFamily AMDRadeonX6000.kext/Contents/MacOS/AMDRadeonX6000; do
        [ -s "$k/System/Library/Extensions/$f" ] || return 1
    done
}
writable() {
    local p="$1/.mbp113-write-test-$$"
    (umask 077; : > "$p") 2>/dev/null || return 1
    /bin/rm -f "$p"
}

prepared_usb() {
    # GPT partition identity is present in the user's Recovery output even
    # when HFS filesystem name and VolumeUUID are unavailable.
    [ "$(disk_value "$1" DiskUUID)" = "$USB_PARTITION_UUID" ] || return 1
    [ "$(disk_value "$1" Internal)" != true ] || return 1
    [ "$(disk_value "$1" FilesystemType)" = hfs ]
}

find_usb() {
    local candidate
    candidate=$(disk_value "$USB_PARTITION_UUID" MountPoint || true)
    if [ -z "$candidate" ]; then
        /usr/sbin/diskutil mount "$USB_PARTITION_UUID" >/dev/null 2>&1 || true
        candidate=$(disk_value "$USB_PARTITION_UUID" MountPoint || true)
    fi
    if [ -n "$candidate" ] && prepared_usb "$candidate"; then printf '%s\n' "$candidate"; return 0; fi
    # A mounted source may be named Image Volume in Recovery. Never rely on
    # this display name or the Mac's current disk numbering for identity.
    for candidate in /Volumes/*; do
        [ -d "$candidate" ] || continue
        if prepared_usb "$candidate"; then printf '%s\n' "$candidate"; return 0; fi
    done
    return 1
}

log_volume() {
    local source="$1" parent device i=0 info mountpoint
    prepared_usb "$source" || return 1
    if writable "$source"; then printf '%s\n' "$source"; return 0; fi
    if [ "$EUID" = 0 ]; then /sbin/mount -uw "$source" >/dev/null 2>&1 || true; fi
    if writable "$source"; then printf '%s\n' "$source"; return 0; fi
    # If the installer source stays read-only, use only the EFI partition on
    # this SAME verified physical USB. No repartitioning or formatting.
    parent=$(disk_value "$source" ParentWholeDisk) || return 1
    [ -n "$parent" ] || return 1
    info=$(/usr/sbin/diskutil list -plist "$parent") || return 1
    while device=$(printf '%s' "$info" | "$RECOVERY_TOOL" value - "AllDisksAndPartitions.0.Partitions.$i.DeviceIdentifier" 2>/dev/null); do
        if [ "$(disk_value "$device" Content)" = EFI ] && [ "$(disk_value "$device" ParentWholeDisk)" = "$parent" ]; then
            /usr/sbin/diskutil mount "$device" >/dev/null 2>&1 || true
            mountpoint=$(disk_value "$device" MountPoint || true)
            if [ -n "$mountpoint" ] && writable "$mountpoint"; then printf '%s\n' "$mountpoint"; return 0; fi
        fi
        i=$((i + 1))
    done
    return 1
}
