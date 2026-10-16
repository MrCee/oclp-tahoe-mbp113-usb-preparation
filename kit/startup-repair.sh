#!/bin/bash
# Custom unattended launcher, not an upstream OCLP service. Runs only once.
set -eE -o pipefail
export PATH=/usr/bin:/bin:/usr/sbin:/sbin
ROOT='/Library/Application Support/MBP113-Repair'
. "$ROOT/common.sh"
/bin/mkdir -p "$ROOT/logs"
RUN=$(/bin/date '+%Y%m%d-%H%M%S')-$$
LOCAL="$ROOT/logs/$RUN-startup"
/bin/mkdir -p "$LOCAL"
exec >> "$LOCAL/startup.log" 2>&1
trap 'r=$?; say "STOP: command failed, line $LINENO, status $r. No automatic retry or reboot."; /bin/sync; exit "$r"' ERR
say 'Startup repair started; waiting for the prepared USB before changing the system.'
[ "$EUID" = 0 ] || die 'Startup repair must run as root.'
[ "$(model)" = "$EXPECTED_MODEL" ] || die 'Wrong model.'
[ ! -e /System/Library/BaseSystem ] || die 'Do not root-patch the Recovery system.'
[ "$(value /System/Library/CoreServices/SystemVersion.plist ProductBuildVersion)" = "$EXPECTED_BUILD" ] || die 'Wrong installed build.'
[ "$(disk_value / APFSVolumeGroupID)" = "$(value "$ROOT/state.plist" VolumeGroup)" ] || die 'Wrong booted volume group.'
[ "$(value "$ROOT/state.plist" USBPartition)" = "$USB_PARTITION_UUID" ] || die 'USB partition identity configuration changed.'

# Disk Arbitration may start after this daemon. Wait at most 3 minutes, never
# patch without the USB log destination. Local logs cover an absent/failed USB.
USB=''; LOG_VOLUME=''; i=0
while [ "$i" -lt 36 ]; do
    candidate=$(find_usb || true)
    if [ -n "$candidate" ]; then
        LOG_VOLUME=$(log_volume "$candidate" || true)
        if [ -n "$LOG_VOLUME" ]; then USB="$candidate"; break; fi
    fi
    /bin/sleep 5
    i=$((i + 1))
done
[ -n "$USB" ] || die 'Prepared USB absent or not writable. No root patches attempted. See local startup log.'
LOGDIR="$LOG_VOLUME/Repair-Logs/$RUN-startup"
/bin/mkdir -p "$LOGDIR"
/bin/cp "$LOCAL/startup.log" "$LOGDIR/startup.log"
exec > >(/usr/bin/tee -a "$LOCAL/startup.log" "$LOGDIR/startup.log" > /dev/null) 2>&1
say "USB logging active: $LOGDIR"
[ ! -e "$ROOT/completed" ] || { say 'Already completed; exiting.'; exit 0; }
[ ! -e "$ROOT/attempted" ] || die 'An attempt already ran. Retaining its result; no automatic retry.'
/bin/mkdir "$ROOT/.running" || die 'A repair is already running.'
trap '/bin/rmdir "$ROOT/.running" 2>/dev/null || true' EXIT
case " $(/usr/sbin/sysctl -n kern.bootargs) " in *' -x '*) die 'Safe mode is active; use normal boot through the prepared USB EFI.';; esac
/usr/sbin/diskutil list > "$LOGDIR/disks.txt"
/usr/sbin/sysctl kern.bootargs > "$LOGDIR/bootargs.txt"
/usr/bin/csrutil status > "$LOGDIR/sip.txt" 2>&1 || true
/usr/sbin/ioreg -rd1 -c IOPlatformExpertDevice > "$LOGDIR/platform.txt"
/usr/bin/pmset -g batt > "$LOGDIR/power.txt" 2>&1 || true
say 'Allowing 20 seconds for normal startup services and hardware discovery.'
/bin/sleep 20
KDK="/Library/Developer/KDKs/$KDK_NAME"
kdk_valid "$KDK" || die 'Matching KDK is missing/incomplete. Re-run the Recovery preparation.'
info="/$APP/Contents/Info.plist"
[ "$(value "$info" Github.Branch)" = refs/tags/3.0.0-rc.3 ] || die 'Installed app is not RC3.'
/usr/bin/codesign --verify --deep --strict "/$APP"
[ -u "/$HELPER" ] && [ -x "/$HELPER" ] || die 'OCLP privileged helper is missing or lacks its expected setuid bit.'
record=/System/Library/CoreServices/OpenCore-Legacy-Patcher.plist
[ ! -f "$record" ] || /bin/cp -p "$record" "$LOGDIR/patch-record-before.plist"
say 'Starting the official RC3 --patch_sys_vol command. No GUI or user account is required by this launcher.'
say 'The display may remain broken while the kernel collections are rebuilt. Leave charger and USB connected.'
/bin/date > "$ROOT/attempted"
/bin/cp "$ROOT/attempted" "$LOGDIR/attempted.txt"
/bin/sync
# Keep awake during kernel collection/snapshot work, without force-killing it.
set +e
HOME=/var/root /usr/bin/caffeinate -dims "/$APP/Contents/MacOS/OpenCore-Patcher" --patch_sys_vol 2>&1 | /usr/bin/tee "$LOCAL/oclp-cli.log" "$LOGDIR/oclp-cli.log"
statuses=("${PIPESTATUS[@]}")
set -e
say "Patcher exit status ${statuses[0]}; USB/local tee status ${statuses[1]}"
/bin/sync
for f in /Users/Shared/*OpenCore*log /Users/Shared/.OCLP*; do
    [ ! -f "$f" ] || /bin/cp -p "$f" "$LOGDIR/"
done
[ ! -f "$record" ] || /bin/cp -p "$record" "$LOGDIR/booted-patch-record.plist"
if [ -f /System/Volumes/Update/mnt1/System/Library/CoreServices/OpenCore-Legacy-Patcher.plist ]; then
    /bin/cp -p /System/Volumes/Update/mnt1/System/Library/CoreServices/OpenCore-Legacy-Patcher.plist "$LOGDIR/mounted-patch-record.plist"
fi
# OCLP can return zero after declining to patch. Require its completion message
# AND execution of both model-specific graphics patchsets, plus an intact log.
if [ "${statuses[0]}" = 0 ] && [ "${statuses[1]}" = 0 ] &&
   /usr/bin/grep -Fq -- '- Patching complete' "$LOGDIR/oclp-cli.log" &&
   /usr/bin/grep -Fq -- '- Installing Patchset: Intel Haswell' "$LOGDIR/oclp-cli.log" &&
   /usr/bin/grep -Fq -- '- Installing Patchset: Nvidia Kepler' "$LOGDIR/oclp-cli.log"; then
    say 'OCLP reports completion after both Haswell and Kepler patchsets. This still needs a successful boot to confirm the result.'
    /bin/date > "$ROOT/completed"
    /bin/cp "$ROOT/completed" "$LOGDIR/COMPLETED.txt"
    /bin/cp "/Library/LaunchDaemons/$LABEL.plist" "$LOGDIR/disabled-after-completion.plist"
    /bin/rm -f "/Library/LaunchDaemons/$LABEL.plist"
    say 'Custom startup job disabled. Rebooting in 15 seconds. Continue through USB EFI Boot to internal MacIntosh.'
    /bin/sync
    /bin/sleep 15
    /sbin/reboot
else
    say 'PATCH NOT CONFIRMED: retaining evidence, no automatic reboot or retry.'
    say 'Return the USB to the iMac. Inspect Repair-Logs and oclp-cli.log for the exact blocker.'
    /bin/sync
    exit 1
fi
