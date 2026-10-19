# SnapRAID role

This role installs SnapRAID from the upstream release tarball, configures the
array, and sets up weekly sync/scrub runs.

## Current design

- **SnapRAID version:** latest upstream release (currently v15.x).
- **Snapshots:** external `snapraid-btrfs` + `snapper` integration, driven by
  `snapraid-btrfs-runner.py`.
- **Scheduling:** `snapraid-btrfs-runner.timer` (weekly, Sunday 03:00 with a
  randomized delay).
- **Healthchecks:** the runner pings `/start`, the success URL, or `/fail`.
  Failure reporting is required so a failed run does not stay stuck in the
  “started” state.
- **Configuration:** `templates/snapraid.j2` generates
  `/etc/snapraid.conf`. It supports 1–6 parity disks and validates the count.

## Read-only status access (MCP)

`get_snapraid_status` runs `sudo -n /usr/local/bin/snapraid status` as the MCP
executor user. SnapRAID creates `snapraid.content` and its `<content>.lock` as
`root:root 0600`, so an unprivileged user cannot read them (`status` also
creates the lock, then reads the content file).

The role therefore installs `/etc/sudoers.d/snapraid-status` with:

```text
<admin user> ALL=(root) NOPASSWD: /usr/local/bin/snapraid status
```

ACLs are deliberately **not** used. SnapRAID writes the content file through a
`0600` `<content>.tmp` and renames it into place, so the inode changes on every
sync and the explicit ACL is lost. A default ACL on the directory does not help
either: POSIX masks inherited named-user entries with the new file's group bits,
which are `0` for a `0600` file, so the entry is stored but ineffective.

Consequences:

- `sudo -n` (non-interactive) is required: it fails instead of prompting.
- On a host with blanket passwordless sudo (catafalco gets it from
  `security_sudoers_passwordless`) this entry is redundant. On a host with
  narrower sudo it is what makes the command work, and its exact-argument match
  limits the grant to `snapraid status` alone.
- The disk-health MCP command policy accepts only this exact argv
  (`SNAPRAID_STATUS_SUDO_ARGV`) and keeps `sudo` blocked for everything else.
- Moving the snapraid binary away from `/usr/local/bin` means updating both this
  sudoers line and `SNAPRAID_STATUS_SUDO_ARGV` in the MCP.
- The lock file is never deleted by SnapRAID (only `flock`ed), so a leftover
  lock is normal. Delete it only if a run was killed, and never while a SnapRAID
  process is active.

`snapraid_cleanup_legacy_acl` (default `true`) revokes the ACL grant an earlier
revision of this role added; it can be removed after every host has run this
version.

## SnapRAID v15 content migration (important)

SnapRAID 15 no longer reads content files written by versions older than 14.x.
An existing array must first run a sync with a 14.x binary:

```bash
# Build/install 14.10 temporarily, then:
sudo snapraid sync
# Then install v15+
```

For the catafalco host this migration was performed with v14.10. A backup of
the pre-migration content file is at:

```text
/var/local/snapraid/snapraid.content.v12.bak
```

## TODO: evaluate v15 native snapshot support

SnapRAID v15 added a native `snapshot` configuration option. When enabled,
SnapRAID creates and manages read-only filesystem snapshots itself for
`sync`, `scrub`, `check`, and `fix`.

Supported filesystems:

- Btrfs
- Bcachefs
- ZFS
- NTFS (Windows)

Notes:

- Enabled with a bare `snapshot` line in `snapraid.conf`.
- Snapshots live under `.snapraid/` at the root of the data subvolume
  (ZFS uses the standard `.zfs/snapshot/`).
- Snapshot creation/deletion requires root privileges.
- It is intended to remove the need for external snapshot orchestration such
  as `snapraid-btrfs` and the `snapraid-btrfs-runner` service.
- SnapRAID keeps `stable` and `pending` snapshots so `scrub`, `check`, and
  `fix` can read data matching the last successful sync.

Before switching:

1. Test on a non-critical array.
2. Confirm the `.snapraid/` directory is excluded from the array (the current
   `nohidden` + `exclude /.snapshots/` rules already keep hidden snapshot data
   out, but the interaction should be verified).
3. Decide whether `snapper` configs `data01`/`data02` are still needed. They
   currently exist only to support `snapraid-btrfs`.
4. Replace the `snapraid-btrfs-runner` systemd service/timer with a plain
   SnapRAID runner (`snapraid sync`, optionally `scrub`/`fix`) and keep the
   Healthchecks success/failure pings.
5. Keep the current `snapraid-btrfs` path until the native route has been
   validated; do not migrate during a scrub or an incomplete sync.

## Operational notes

- `snapraid_deletethreshold: -1` disables protection against mass deletions.
  A finite value such as `1000` is recommended; use
  `--ignore-deletethreshold` for intentional large deletions.
- On I/O errors SnapRAID marks the affected 256 KiB block as bad and exits
  non-zero. It does not silently skip the block. Check SMART, isolate or
  restore the affected file, then run a clean `sync`.
- `snapraid fix` can rebuild bad blocks from parity, but only if the content
  is not left in a partially synced state.
- Self-test logs can keep reporting a single pending sector at the same LBA
  even after the affected file has been moved/restored. Monitor pending and
  reallocated sector counts; a stable single bad sector is not by itself a
  reason to replace the disk.
