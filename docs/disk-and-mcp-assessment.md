# Disk identity, privilege model and MCP tooling — fused assessment & TODO

**Status:** OPEN · **Last updated:** 2026-10-21 23:55 CEST · **Host:** `catafalco`
**Supersedes:** `docs/disk-identity-investigation.md` and
`docs/mcp-tool-audit-2026-10-20.md` (both merged here and deleted).

This is the single working document for the 2026-10-20 assessment. It starts with the
current state and a prioritized, fused TODO list; the evidence and verification commands
are in the appendices. Keep it current rather than opening a second findings document.

---

## Current state (2026-10-21)

| Area | State | Consequence |
|---|---|---|
| Disk identity | **Fixed, deployed and reboot-proven twice (T-06/T-12):** the SMART `device` tag is a static label and every poll now carries a static `serial_no` tag. Re-proven on boot #4 (23:30 CEST), where a third kernel-name permutation left every label, serial and mount unchanged | Telegraf, Grafana and the disk-health MCP select/filter by `serial_no`; a reboot can no longer retarget a panel, and standby/failed rows stay attributable |
| Poll attribution | **Serial tag deployed 01:10 CEST, verified 01:15 CEST:** standby rows carry `serial_no` even when smartctl reports no serial | `get_disk_health` attributes the newest Parity1 standby poll; the overview still groups failures by the old label (MCP follow-up T-20) |
| Mounts / filesystems | **Safe:** every filesystem came back on the intended disk | `LABEL=` mounts did their job; no data loss |
| SMART collection | **Restored 23:35 CEST:** first successful poll after the fix; five disks `exit_status = 0`, one standby `exit_status = 2` | Dashboards and MCP are current again; stale/mismatch warnings are now implemented (T-05 done) |
| Privilege model | **Scoped grants verified 23:35 CEST:** admin has passworded sudo, telegraf has only `docker` + `smartctl`/`nvme` NOPASSWD | Blanket grant is gone and the repo no longer restores it (T-02/T-03 done) |
| MCP SSH channel | **Working after the operator reloaded the MCP (verified 2026-10-21 23:45 CEST):** `list_disks`, `get_mount_status`, `get_io_stats`, `get_host_service_*`, `get_snapraid_status` and the disk-health per-disk calls all answer | The post-boot capture checklist can run through the MCP again; the reload/reconnect step after a host reboot is the standing procedure (T-04) |
| InfluxDB persistence | **Broken (T-21), found 2026-10-21 23:45 CEST:** the running container writes outside the bind mount (`/srv/influxdb/data` untouched since 2026-07-31 01:36, live store replaying `wal_file_number` 1–128) and only 20 minutes of data is queryable | Every container recreate silently discards all metrics since 2026-07-31; dashboards and the disk-health MCP have no history to trend or to compare against |
| Credential handling | **Fixed and verified 2026-10-21 01:12 CEST:** rclone password rotated and masking live; the two local Samba accounts (`alessio`, `sara`) were rotated and verified with `smbclient` | `rclone.conf` returns `redacted: true` / `pass = ***`; deployed rclone password matches the vault; leaked Samba values no longer work (T-01 done) |
| Key hypothesis | **H1 confirmed and closed by T-06:** kernel-name tags were baked at deploy time | The tag is now a static label and identity comes from the serial (T-07 superseded) |
| Open hypotheses | **H2 resolved; H3 narrowed** by the T-12 hwmon capture | smartd's 58 °C is the KINGSTON (`NVMe2`) secondary sensor, not a different disk; only the KINGSTON exposes per-sensor hwmon entries, the CT1000 exposes composite only |

**Standing rule:** join on `serial_no` (SMART) or `ID_SERIAL_SHORT` (`diskio`), never on
`device` / `name`. Since 2026-10-21 the `device` tag is a static label and the kernel name is
runtime-only, but history written before that change still carries kernel-name tags — serial
joins are what keep those rows attached to the right physical disk. The disk-health MCP
refuses to call a stale or mismatched sample healthy (T-05).

**Caveat (2026-10-21 23:55 CEST):** that pre-change history is no longer queryable — the
InfluxDB store was reset when the container was recreated today (T-21). Rows older than
2026-07-31 still sit in the orphaned `/srv/influxdb/data` store; rows from 2026-07-31 to
2026-10-21T21:29Z were in the container's writable layer and are gone. Until T-21 is fixed
the serial rule protects future rows, not old ones.

**Priority legend**

- **P0** — security, restore observability, prevent silent wrong answers.
- **P1** — root-cause fixes for disk identity and MCP correctness.
- **P2** — MCP bugs and usability defects that do not block the investigation.
- **P3** — deployment/host hygiene found during the same pass.

---

## P0 — Security and restore observability

### T-01 — Rotate the leaked SMB password and fix credential masking

- [x] Rotate the leaked password and fix the masking policy.

**Status (2026-10-21 00:15 CEST): verified.** `get_service_file(service="rclone",
file_path="rclone.conf")` now returns `redacted: true` with `pass = ***` (server-mcp commit
`ad75f9a`, word-based key matching). The vault's `rclone_password` changed and the deployed
`/srv/rclone/rclone.conf` (mtime 23:59) reveals to the same SHA-256 as the vault value;
`rclone lsd julia:` succeeds with that config, so the julia-side password was rotated too.
`packages/server-management-lib/tests/test_redaction.py` covers the INI shape reported here
plus `.env` and `*-credentials` (41 passed).

**Follow-up found while verifying.** `host_vars/catafalco/secret.yml` still keeps the local
Samba passwords (`samba_users`) in clear text inside the vault — fine at rest, but those two
accounts are worth rotating in the same hygiene pass, and the rclone leak shows the vault is
the single place they live.

**Samba rotation (2026-10-21 01:12 CEST): done.** Both accounts (`alessio`, `sara`) received
new 32-character alphanumeric passwords in the vault; `smbpasswd` was run on the host and each
new credential was verified with `smbclient -L localhost` using a temporary `-A` auth file
(deleted afterwards). The old values no longer authenticate. These are SMB-only accounts
(`/sbin/nologin`), so no OS login password change was needed.

**Why.** `get_service_file(service="rclone", file_path="rclone.conf")` returned
`redacted: false` and the SMB `pass` value in clear text for the `[julia]` share. The same
tool masked `immich/.env` and `swag/letsencrypt/cli.ini` (`dns-cloudflare-credentials`) and
refused `*.pem`, so the policy matches specific key names but not INI keys such as `pass`,
`password`, `token`, `secret`, `apikey`.

**Do.**

- Rotate the SMB password on `192.168.178.4` for user `catafalco`; update the vault and the
  rclone configuration.
- Treat `rclone.conf` and any INI/TOML/YAML config as a credential store.
- Extend value masking to `pass|password|passwd|token|secret|key|apikey|credentials`.
- Add a regression test covering `rclone.conf` plus the already-working `.env` and
  `*-credentials` cases.

**Done when.** The same `get_service_file` call masks or refuses the value; no secret appears
in tool output/logs; a test asserts it.

---

### T-02 — Replace blanket sudo with scoped grants, and stop the repo restoring it

- [x] Remove blanket sudo from the repo and add the repo-side scoped grants.
- [x] Apply to the host and verify that a playbook re-run keeps the blanket grant gone.

**Status (2026-10-20 23:35 CEST): host-verified.** `roles/system/tasks/user.yml` now removes
the legacy `%sudo`/user `NOPASSWD` lines, `host_vars/catafalco/vars.yml` sets
`security_sudoers_passwordless: []` and a passworded admin entry, and `roles/telegraf`
installs `/etc/sudoers.d/telegraf-smart` while removing `telegraf` from the `sudo` group.
Host checks: `sudo -n true` now fails with "a password is required", `id -nG telegraf`
returns `telegraf docker` (no `sudo`), and both scoped sudoers files are present
(`root:root 0440`). To converge another existing host, run the bootstrap/system role once
(`--tags bootstrap`) so the legacy `/etc/sudoers` lines are removed; the telegraf role can
then be applied with `--tags telegraf`.

**Why.** The operator removed `%sudo ALL=(ALL) NOPASSWD: ALL` on purpose. The repo still
wrote it back, so the next playbook run would silently undo the hardening. Several consumers
depended on it without declaring a scoped rule.

| Consumer | How it had root | State after removal |
|---|---|---|
| Telegraf `[[inputs.smart]]` | `%sudo` blanket grant; `telegraf` added to `sudo` group | **broken** — all six disks `exit_status = 1` |
| remote-server MCP | presumed `sudo -n` escalation | **broken** — every SSH tool reports "connection closed" |
| disk-health MCP `run_smart_test` | presumed `sudo -n smartctl` | **broken** — reports "standby" for any non-zero exit |
| disk-health MCP `snapraid status` | own `/etc/sudoers.d/snapraid-status` | expected to work — verify |
| `get_host_service_logs` / journald | `systemd-journal` group, no sudo | expected to work — verify |

**Repo places that restored blanket sudo (changed 2026-10-20):**

1. `roles/system/tasks/user.yml:20-26` — previously wrote
   `%{{ system_sudo_group }} ALL=(ALL) NOPASSWD: ALL` into `/etc/sudoers`; now removes the
   legacy `%sudo` and user-specific `NOPASSWD` lines.
2. `host_vars/catafalco/vars.yml` — previously
   `security_sudoers_passwordless: ["{{ username }}"]`, consumed by
   `geerlingguy.security`; now empty with a passworded admin entry.
3. `roles/telegraf/tasks/main.yml:172-176` — previously added `telegraf` to the `sudo`
   group with the comment *"this is required for SMART"* and created no sudoers rule; now
   installs the scoped rule and removes only that group membership.

**Do.**

- Add the narrow rules first (T-03, T-04), then remove the blanket writes in the same change.
- Keep `snapraid-status`; confirm `get_host_service_logs` works via group membership.
- Re-run the relevant tags only after the repo no longer writes the blanket line.

**Done when.** The repo contains no blanket `NOPASSWD: ALL` for the admin/sudo group; each
root-needing consumer has a minimal `/etc/sudoers.d/` entry; a playbook re-run does not
restore the blanket grant; `sudo -l -U <consumer>` shows only the intended commands.

---

### T-03 — Restore Telegraf SMART collection with a scoped sudoers rule

- [x] Add the scoped `telegraf-smart` rule to the role and remove `telegraf` from `sudo`.
- [x] Apply to the host and verify fresh SMART rows (non-standby disks `exit_status = 0`).

**Why.** Last `smart_device` row with `exit_status = 0` was **20:15:00 UTC (22:15 CEST)**.
Every poll after that (20:20, 20:25, 20:30 on boot #1; 20:35, 20:40 on boot #2) has
`exit_status = 1` for **all six devices** and no other fields. That is not a sleeping-disk
artefact: standby normally produces `exit_status = 2` with `power = STANDBY`. The passwordless
sudo grant was removed at ~22:19 CEST; `[[inputs.smart]]` uses `use_sudo = true` and had no
dedicated sudoers rule. Every other input needs no root, which is why the outage is invisible
outside S.M.A.R.T.

**Recommended fix (option 1).**

- Add `/etc/sudoers.d/telegraf-smart` with
  `telegraf ALL=(root) NOPASSWD: /usr/sbin/smartctl, /usr/sbin/nvme` (the plugin calls both),
  keep `use_sudo = true`, and manage the file from the `telegraf` role.
- Add `Defaults:telegraf !pam_session` to stop six `pam_unix(sudo:session)` pairs every five
  minutes from drowning the journal, while keeping sudo's command logging in the journal for
  auditability. (The earlier draft also proposed `!syslog`; that would hide command and error
  lines too, so the implementation keeps syslog.)
- Remove `telegraf` from the `sudo` group once the scoped rule is in place.
- Validate with `visudo -cf` before reloading. **Status (2026-10-20 23:35 CEST): host-verified**
  — Telegraf restarted at 23:29:57 and the first poll at 23:35:00 returned fresh data for all
  six disks (five `exit_status = 0`, `sdc` standby `exit_status = 2`); no `a password is
  required` lines after the restart, and no `pam_unix(sudo:session)` noise, while sudo command
  logging remains.

**Alternatives considered:** run Telegraf as root (broader than needed); put `telegraf` in
the `disk` group and set `use_sudo = false` (works for most devices, but some controllers/USB
bridges and older-kernel NVMe smart-log access still need root). Pick one during review; do
not combine with the blanket grant.

**Done when.**

```bash
sudo -u telegraf sudo -n /usr/sbin/smartctl --version   # succeeds
journalctl -u telegraf -n 200 | grep -iE 'smart|sudo'   # no password prompts / pam noise
```

Fresh `smart_device` rows exist for all six disks and are less than two poll intervals old:
non-standby disks report `exit_status = 0` with model/serial/temperature; a sleeping HDD may
report `exit_status = 2` / `power = STANDBY` (expected).

---

### T-04 — Restore the remote-server MCP SSH channel

- [x] Restore the SSH channel and verify the main tool families.
- [x] Audit the MCP command templates for any remaining `sudo -n` paths and add matching
      MCP-side allowlisting.

**Command-template audit (2026-10-21 00:20 CEST): clean.** The only escalation path left in
`apps/disk-health-mcp` and `packages/server-management-lib` is the literal
`sudo -n /usr/local/bin/snapraid status` (documented in `operations.py`, allowlisted in
`security.py`, backed by `/etc/sudoers.d/snapraid-status`). SMART reads go through InfluxDB or
an unprivileged `smartctl`; the MCP explicitly states it does not escalate with sudo for
SMART (`server.py:509-553`). No `sudo -n` remains in the SSH command templates.

**Status (2026-10-20 23:35 CEST): working.** `get_server_health`, `list_disks`,
`get_mount_status`, `get_io_stats`, `get_host_service_{status,logs}`, `list_containers`,
`get_service_status` and `get_service_logs` all answer again. The scoped
`get_snapraid_status` (`sudo -n /usr/local/bin/snapraid status`) also works. Recovery after a
likely MCP restart/stale pooled connection fits better than a permanent `sudo -n` dependency;
the command-template audit above is now complete.

**Recurrence after the T-12 reboot (2026-10-21 01:13 CEST).** Every SSH-backed tool is back to
`SSH error: SSH connection closed`, while InfluxDB-backed tools answer normally. This is the
same stale pooled connection, not a credential or sudo regression: Ansible over the same host
succeeds with the vault password, and the reboot itself completed through Ansible. A
`/mcp` reconnect (or agent-session restart) is required before the SSH-backed capture steps
are trusted again; the disk-health code itself is current (it returns the 0.2.2 parallel-list
payload, with `devices` empty only because live resolution is unavailable).

**Verified after the boot #4 reload (2026-10-21 23:45 CEST).** The operator rebooted the host
and reloaded the MCP; `list_disks`, `get_mount_status`, `get_io_stats`,
`get_host_service_{status,logs}`, `get_service_status`, `list_services` and
`get_snapraid_status` all answer on the first call, with no reconnect loop and no `sudo -n`
regression (`snapraid status` still works through the scoped rule). Reloading/reconnecting the
MCP after a host reboot is the standing procedure, not a workaround for a defect.

**Why.** Since the 2026-10-20 22:30 CEST reboot, every SSH-backed tool returned
`SSH error: SSH connection closed`: `get_server_health`, `list_disks`, `get_mount_status`,
`get_io_stats`, all `get_host_service_*`, and all container/compose/log tools. Only the
InfluxDB-backed tools answered. The failures persisted from ~5 to ~11 minutes after boot,
so this was not a boot transient. The operator's sudo change was one hypothesis if the MCP
escalated via `sudo -n`; a stale pooled connection was the other.

**Do.**

- Inspect the MCP's SSH command templates and escalation path.
- Check host auth/journal logs for denied `sudo` attempts.
- Restart the MCP process to rule out a dead pooled connection.
- Replace `sudo -n` with narrow `/etc/sudoers.d/` entries for exactly the commands that need
  root; journald already works through group membership.
- Add MCP-side command allowlisting that matches the scoped rules.

**Done when.** All SSH tools work; the post-reboot capture checklist can run on the host; no
tool relies on blanket sudo.

---

### T-05 — Never present stale or mismatched SMART data as current health

- [x] Add freshness and identity checks to the disk-health MCP.

**Status (2026-10-21 00:25 CEST): implemented and verified live** (server-mcp commit
`e9ec82f`, 149 tests pass). `get_disk_health("sdc")` against a 3-hour-old row now returns
`Identity: MISMATCH sample serial ZVTFE2SL != live serial ZVTFF3JB`, `Freshness: STALE`, and
`Health: UNKNOWN — sample belongs to a different disk` with `severity: critical`. Reports echo
model, serial, sample timestamp and the live lsblk identity, and list recent non-success polls.

**Open nit (P2-sized):** standby polls (`exit_status = 2`) are counted and printed as "failed
polls", which floods the report with 100+ identical entries for an idle HDD. They should be
summarised separately from real failures (`exit_status = 1`).

**Why.** `get_disk_health`, `get_nvme_health` and `get_full_disk_report` pick the newest row
with `exit_status = 0` from the last 24 h, render it with a green ✅ and a relative age
("Sample: 26 minutes ago"), and do not mention that every recent poll failed. During this
audit SMART had been down for 20+ minutes and the tools still looked healthy; up to 24 h of
staleness would pass unnoticed. After the reboot the tags also contradict live names, so
`get_disk_health("nvme0n1")` returned the KINGSTON while live `nvme0n1` is the CT1000P2SSD8.

**Do.**

- Warn/refuse green when the newest successful sample is older than two poll intervals
  (SMART polls every 5 min).
- Echo `serial_no`, model, sample timestamp, and (when resolvable) the live device in the
  summary so the caller can compare.
- Report recent failed polls (`exit_status != 0`) instead of hiding them.
- If the requested device's serial cannot be matched to the sample, say so and do not claim
  "healthy".
- Apply the same rule to `get_full_disk_report` and `get_nvme_health`.

**Done when.** With SMART down, reports are red/amber and explain why; with a tag/device
mismatch, the report names both identities and refuses to call the requested disk healthy;
tests cover fresh, stale, failed and mismatched cases.

---

### T-21 — InfluxDB is not writing to its bind mount, so every recreate wipes the metrics

- [ ] Make the container persist to `/srv/influxdb/data` and prove it survives a recreate.

**Found 2026-10-21 23:45 CEST while verifying T-06 after boot #4.** The hosted InfluxDB has no
history left and is not using its bind mount:

- `list_service_files("influxdb", "data/catafalco")` → `wal` mtime **Jul 31 01:36**, `dbs`
  May 9, `catalog` Jun 18, newest WAL file `00000730637.wal`. The mounted store has not been
  written for ~3 months.
- The live process flushes to a *different* store: `influxdb3_wal::object_store: flushing WAL
  buffer ... wal_file_number=116` and, on restart, `replaying WAL file ... wal_file_number=1..128`
  with `self.node_id="catafalco"`. A fresh store numbering from 1 cannot be the on-disk one.
- Every measurement is truncated at the container start: `SELECT min(time) FROM smart_device`
  → `2026-10-21T21:30Z` (24 rows total over 60 days), `cpu` → 1 495 rows from 21:30Z, `mem` →
  from 21:29:50Z. Query plans for those windows report `partitions=0 parquet_files=0`, i.e. no
  parquet files exist on the mounted store for any recent range.
- The container was (re)created at 22:55 CEST (image `influxdb:3-core` is pulled on every run,
  `pull: true`), which is the point where the previous container layer — and with it every row
  from 2026-07-31 to 2026-10-21T21:29Z — disappeared.

**Impact.** Dashboards show a ~20-minute window that restarts empty after each recreate; the
disk-health MCP cannot trend S.M.A.R.T. and cannot fall back to history; the T-06 appendices
that tell a reader to disambiguate old rows by serial have nothing to disambiguate. Rows are
lost silently — no error is logged, InfluxDB just starts from an empty store.

**Likely causes (must be distinguished on the host, do not guess).**

1. `INFLUXDB3_DB_DIR` is no longer honoured by the current image, so the process falls back to
   an in-container default and writes to the writable layer. The store stopped at
   **2026-07-31 01:36**, minutes after the `table-index-conversion-completed` marker dated
   **2026-07-30 05:00** — i.e. right after an image upgrade.
2. The deployed container lost the bind mount when it was recreated (ansible `docker_container`
   volume change, or a recreate that did not re-apply volumes).

**Diagnose.**

```bash
docker inspect influxdb --format '{{json .Mounts}}'          # is /srv/influxdb/data mounted?
docker inspect influxdb --format '{{.Config.Image}} {{.Image}}'
docker exec influxdb influxdb3 serve --help | grep -i -A2 'data.dir'
ls -l --time-style=full-iso /srv/influxdb/data/catafalco/wal | tail -3
```

**Do.**

- Pin the image (`influxdb:3.x.y`) instead of floating `3-core` with `pull: true`; an
  unattended major update is how the format/flag contract changed under the role.
- Set the data-directory variable the pinned version actually reads, and mount the host path at
  the parent (`/var/lib/influxdb3`) so a future rename cannot silently land outside the mount.
- Recover what is recoverable: the pre-2026-07-31 rows are still in `/srv/influxdb/data`; the
  Jul 31 → Oct 21 rows are gone and should be documented as such, not re-queried.

**Done when.** A marker row written today is still returned after `restart_service`/recreate of
`influxdb`, `SELECT min(time)` reaches back past the recreate, and
`/srv/influxdb/data/catafalco/wal` mtime advances during normal operation.

---

## P1 — Disk identity (root cause)

---

### T-06 — Adopt the serial number as the canonical disk identity

- [x] Make serial-based joins the default across Telegraf, Grafana and the MCPs.
      Code complete in all three layers; deployment + reboot verification complete (T-12).

**Implementation (2026-10-21, deployed 00:23 CEST).** The model is now explicit in all
three layers:

- **Telegraf** — the by-id tag is rewritten to the disk's *static label* from
  `host_vars` (`Data1`, `Data2`, `Parity1`, `Cache1`, `System`, `NVMe2`) instead of the
  kernel name resolved at deploy time. The regex processor keeps working, but the value
  it writes is semantic (role), not positional. `telegraf_kernel_devices` is gone.
- **Telegraf, static serial tag (2026-10-21 01:10 CEST).** A second processor,
  `[[processors.template]]`, writes the configured serial into a static `serial_no` tag
  on every `smart_device` / `smart_attribute` poll of that disk. It matches the label
  written by the regex block and the by-id basename as a fallback, so it is independent
  of a label change and of the regex ordering. This closes the last attribution gap:
  standby and failed polls carry no serial *field*, so without it a row written after a
  label change could not be tied back to the disk. Verified on the first poll after the
  role run (23:10 UTC): all six rows, including the three standby HDDs, carried
  `serial_no`; `get_disk_health("sdc")` then listed the newest standby poll (23:10,
  `device=Parity1`) instead of stopping at the last legacy-tag failure (21:25). The
  overview path still groups failures by `device` (T-20).
- **Grafana** — the `device` variable is replaced by `serial` (`SELECT DISTINCT
  serial_no ...`), every panel filters with `serial_no IN (${serial:sqlstring})`, the
  Disk column is ordered by serial, and the two hard-coded gauges (`'sdd'`, `'nvme0'`)
  now use serials rendered from `system_disks` / `cache_disks` plus their labels.
  `device` is only selected for the legend.
- **disk-health MCP** — `get_disk_health`, `get_smart_attributes` and `get_nvme_health`
  resolve the live serial (lsblk) and select `serial_no = '<serial>'`; the tag is a
  fallback only when the live serial cannot be resolved. The overview partitions by
  `serial_no`, so one physical disk is one line even if its label changes. Failed polls
  can now be matched by `serial_no` too (the static tag above); the per-disk path already
  does this. The overview's failure summary still groups by `device` (T-20).

**Verification.** The scoped playbook run (`--tags telegraf,grafana`) rendered the new tag
map and restarted Telegraf; the first poll (22:25 UTC) wrote `Cache1`/`Data1`/`Data2`/
`NVMe2`/`Parity1`/`System` instead of `sda`/`nvme0`. Grafana restarted and provisioned the
dashboard with the `serial` variable and `serial_no IN (...)` panels (no provisioning
errors). Running `get_full_disk_report()` against the new code returned one line per serial
(6 disks, not 11) with `Identity: verified` for every disk whose live serial matched, and it
named the live device even for the sleeping parity disk whose newest sample predates the tag
change. server-mcp tests: 152 + 454 pass; `ruff check` clean.

**Reboot proof (T-12, 2026-10-21 01:13 CEST).** A deliberate reboot re-enumerated three
SATA disks: Data2 `sdb -> sdd`, Parity1 `sdc -> sdb`, System `sdd -> sdc` (Data1 stayed
`sda`; both NVMe names stayed). The Telegraf config did not change, the first post-reboot
poll (23:15 UTC) still wrote the same serial↔label pairs, and the `LABEL=` mounts and
`/dev/disk/by-id` links followed the serials to the new kernel names. Details and evidence
are in T-12.

**MCP payload contract (server-mcp `12e38f9`, release v0.2.2, tag not yet pushed).** Use the structured
payload, not the text: `get_full_disk_report().data` returns three parallel lists —
`devices` (live kernel names, each a valid `get_disk_health` argument, `""` when the disk
has no live match), `labels` (the static role label, `""` for a legacy tag) and `serials`.
Index them together; the text rendering may change. `devices` no longer contains tag
values. `get_smart_attributes` now reads NVMe wear from InfluxDB instead of falling back
to an unprivileged `smartctl` that gets `Permission denied`. The active MCP process was
already serving this payload during the T-12 check; it still needs a reload after a
server-mcp change, and after the reboot its pooled SSH connection was stale (T-04), so
`devices` was empty until a reconnect.

Two follow-ups found here: (1) `_resolve_live_device` now prefers a serial match over an
exact name match, because a legacy kernel-name tag can name a different disk today; (2) the
`NVMe2` label is now published as a tag, so T-10's "what does NVMe2 mean" decision is
load-bearing for dashboards instead of cosmetic.

**Live re-check after the MCP reload (00:52 CEST, server-mcp `a6cc08c` + `7b5d606`).**
`get_full_disk_report()` now returns six disks, one per serial, each rendered as
`Data1 (/dev/sda)` / `Cache1 (/dev/nvme0n1)` with `Identity: verified`; kernel names remain
valid input (`get_disk_health("sda")` reports the disk labelled `Data1`), and failed polls are
summarised as `seen: 2 x4` instead of one token per row. Two defects surfaced in that check:

- `get_smart_attributes` failed for NVMe: the query filtered `smart_attribute` on
  `exit_status = 0`, but Telegraf writes that field only on SATA `smartctl` rows, so all NVMe
  attributes were dropped and the tool fell back to an unprivileged `smartctl` that gets
  "Permission denied". Fixed in `7b5d606` (selector only; standby rows have no attribute rows).
- The reports showed the label and the live device in separate fields rather than together;
  `7b5d606` adds the `Label (/dev/kernel_name)` form. A legacy tag that still holds a kernel
  name is not shown as a label, so a pre-migration row (the sleeping parity disk) shows only
  `/dev/sdc`.

**Transition note.** History written before the change is tagged with kernel names, so a
24 h dashboard range shows one extra series per affected disk until it ages out; serial
selection means the data itself is never misattributed. Reload the MCP after any
`server-mcp` change: the running process keeps serving the code it started with. The NVMe
attribute fix and the label/live-device display landed in `7b5d606`, i.e. after the reload
described above, so one more reload is required.

**Still open here:** T-11 (`get_smart_attributes("nvme0")` is still rejected as an invalid
device name while `"nvme0n1"` works) and T-20 (the overview still attributes failed polls
by the mutable `device` label; the per-disk path already uses the serial tag). T-12 is done.

**T-07 is superseded.** With the tag no longer carrying a kernel name there is nothing to
derive at runtime: the label is static and the kernel name is read at runtime by lsblk /
`diskio.name`. Keep the by-id resolution + assert in the role (it catches a wrong serial),
but do not reintroduce a deploy-time kernel-name tag.

**Why.** The serial is the only stable identity on this host. `smart_device.serial_no` and
`diskio.ID_SERIAL_SHORT` are already published. The `device` tag is serial-stable (it keeps
pointing at the same physical disk), but it follows the **last Ansible run**, not the current
kernel order; after a reorder it contradicts `lsblk`, `diskio` and smartd. Re-running the
telegraf role flips the tag to the new name, and then history under one `device` value spans
two physical disks.

**Recommended model.**

- Use `serial_no` (SMART) / `ID_SERIAL_SHORT` (`diskio`) for identity and all joins.
- Keep the kernel name only as a non-identity attribute, or drop it after migrating panels.
- Update the Telegraf tag/processor configuration, Grafana variables/panels, and MCP
  device→serial resolution together.
- Document the migration so old `device`-keyed history is treated as mixed.

**Done when.** A reboot/shuffle does not change which physical disk a panel or report
describes; no join uses `device` / `name`; dashboards still resolve.

---

### T-07 — If kernel names must remain, derive them at runtime

- [x] Superseded by T-06 — there is no kernel name in the tag any more.

> Historical note: this section describes the pre-T-06 code and is retained for context.
> The current template has no `telegraf_kernel_devices` mapping; it writes a static label
> and a static `serial_no` tag.

**Why.** `roles/telegraf/tasks/main.yml:134-141` resolves the *current* kernel name per serial
into `telegraf_kernel_devices`, and `roles/telegraf/templates/telegraf.conf.j2:362-381`
renders a `processors.regex` block that rewrites the by-id tag into that hard-coded string.
Collection stays correct (the by-id path hits the right disk), but the tag follows the last
Ansible run, not the live order.

**Do (only if T-06 cannot drop `device` yet).**

- Add a small `ExecStartPre`/systemd unit or `[[inputs.exec]]` mapping that resolves
  serial → live kernel name on every Telegraf start.
- Keep the assert that exactly one `ata-*_<serial>` / `nvme-*_<serial>` link matches.
- Document that history under a `device` value still mixes physical disks across a reorder.

**Done when.** A reboot with a different enumeration updates the tags before the first poll,
with no manual Ansible run, and missing/ambiguous serials fail loudly.

---

### T-08 — Move smartd to by-id paths and fix NVMe temperature thresholds

- [ ] Stop smartd from watching `/dev/sdX` / `/dev/nvmeX`, and stop the false 58 °C alarm.

**Why.** The **deployed** `/etc/smartd.conf` is one `DEVICESCAN` line, not a list of
`/dev/sdX` entries, and smartd's state files are named by model-serial. So the historical
"smartd follows stale kernel paths" worry does not apply to this host. The remaining issue is
the false NVMe temperature alarm: every 30 min,
`Device: /dev/nvme0, Temperature 58 Celsius reached critical limit of 50 Celsius
(Min/Max 58/75)`, while per-serial composites stay at 32–41 °C. 58 °C matches hwmon
`nvme_sensor_2 = 57.85 °C`; the composite on the same sample is 35.85 °C. The T-12 hwmon
capture resolves which drive owns that sensor: `hwmon1` = KINGSTON (`NVMe2`), so the alarm
is about the KINGSTON's Sensor 2, not a misattributed disk (H2).

**Do.**

- If smartd ever pins explicit devices, use `/dev/disk/by-id/...` entries.
- Set NVMe-aware `-W` thresholds (or disable the warning if the composite is the intended
  metric); compare `smartctl -a` by-id output for `Temperature:` vs
  `Temperature Sensor 1/2/3`.
- Preserve the expected standby behaviour and skipped-check messages.

**Done when.** No false critical-temperature mail; smartd log lines identify a stable serial;
a reboot/shuffle does not retarget a threshold.

---

### T-09 — Fix per-drive hwmon attribution (or drop NVMe hwmon)

- [ ] Make every NVMe temperature series attributable to exactly one serial.

**Why.** `inputs.temp` has no disk identity: the schema is only `host, sensor, temp, time`,
with sensors named `nvme_composite`, `nvme_sensor_1..3`. Two NVMe drives emit identical tag
sets, so their series collide. At capture time only **4** NVMe sensor series existed for 2
drives, and values were identical before and after the reboot (`sensor_1 = 51.85`,
`sensor_2 = 57.85`, `sensor_3 = 37.85/38.85`, `composite = 34.85–35.85`). The T-12 hwmon map
shows the extra sensors belong to the KINGSTON (`hwmon1`), while the CT1000 (`hwmon2`) only
has Composite; the collision is the shared `sensor=Composite` tag. This does not block H2
(now resolved), but it still blocks per-drive hwmon attribution.

**Do (pick one).**

- Map `/sys/class/hwmon/hwmon*/device` to the PCI device/serial and emit a per-device
  label/tag (`tagpass` / `name_override` or a `[[inputs.exec]]` wrapper), or
- Drop NVMe hwmon temperatures and use `smart_device.temp_c`, which is already per-serial.

**Done when.** Each NVMe temperature series maps to one serial; the series count matches the
number of drives; H2 can be answered without ambiguity.

---

### T-10 — Decide what the `NVMe2` label means

- [ ] Give `NVMe2` a documented invariant.

**Why.** `system_disks` calls the Kingston `NVMe2`. It sat on `nvme0n1` before the reboot and
now sits on `nvme1n1`. Either the label means "second slot" (making boot #2 correct) or it is
documentation drift; it is the only place that still implies a fixed position.

**Do.** Decide slot vs enumeration order vs role; rename to a serial/role-based label if
needed; update `host_vars` and documentation.

**Done when.** The label has a stated invariant and matches the hardware after a reboot.

---

### T-11 — Normalize MCP device names and validate device type

- [ ] Use one canonical device vocabulary across the disk-health tools.

**Why.**

- `list_disks` speaks `nvme0n1`; reports print `/dev/nvme0`; InfluxDB tags are `nvme0`;
  `get_full_disk_report("nvme1")` is rejected while `get_full_disk_report("nvme1n1")` works.
- `get_smart_attributes("nvme0n1")` queries the literal tag and finds nothing; `"nvme0"` is
  rejected by the validator. `smart_attribute` rows also carry no `exit_status` field (it
  exists only on `smart_device`), so a filter on it cannot be satisfied there.
- `get_nvme_health("sda")` returns a green SATA report instead of rejecting the device type.

**Do.**

- Pick one canonical internal form (serial preferred; otherwise `sdX` / `nvmeXnY`) and
  normalize inputs (`nvmeX`, `nvmeXnY`, `/dev/...`, by-id).
- Resolve to the right InfluxDB tag; do not require `exit_status` on `smart_attribute`.
- Reject non-NVMe devices in `get_nvme_health` (or clearly label the ATA report).
- Add a matrix test for both spellings and wrong device types.

**Done when.** `get_smart_attributes("nvme0n1")` and `("nvme0")` both work;
`get_nvme_health("sda")` is rejected; all tools agree on one name for one disk.

---

### T-12 — Acceptance test: shuffle and reboot

- [x] Prove the fixes survive re-enumeration.

**Done 2026-10-21 01:13–01:15 CEST.** `catafalco` was rebooted deliberately through
Ansible (`ansible.builtin.reboot`), the checklist below was captured before and after, and
the host came back with three SATA disks re-enumerated:

| Role | Serial | Kernel before | Kernel after | Influx label (23:15 UTC) | Mount after |
|---|---|---|---|---|---|
| Data1 | `ZVTFF270` | `sda` | `sda` | `Data1` | `/dev/sda1[/data]` → `/mnt/data1` |
| Data2 | `ZVTFE2SL` | `sdb` | **`sdd`** | `Data2` | `/dev/sdd1[/data]` → `/mnt/data2` |
| Parity1 | `ZVTFF3JB` | `sdc` | **`sdb`** | `Parity1` | `/dev/sdb1` → `/mnt/parity1` |
| System | `2421E8B28A83` | `sdd` | **`sdc`** | `System` | `/dev/sdc2` → `/`, `/dev/sdc1` → `/boot/efi` |
| Cache1 | `2146E5E54409` | `nvme0n1` | `nvme0n1` | `Cache1` | `/dev/nvme0n1` → `/mnt/cache1` |
| NVMe2 | `50026B7383E4529D` | `nvme1n1` | `nvme1n1` | `NVMe2` | monitor-only |

What agreed after the reboot:

- `lsblk`, `/dev/disk/by-id` and `findmnt` all followed the serials; no filesystem moved to
  another physical disk. `LABEL=` mounts resolved to the new kernel names.
- The first post-reboot Telegraf poll (23:15 UTC) wrote all six disks with the same
  serial↔label pairs as before, each `exit_status = 0`. The static `serial_no` tag from the
  new processor was present on the 23:10 standby rows as well, so the label change cannot
  strand a poll.
- `smartd.conf` is one `DEVICESCAN` line; the per-device state files are named by
  model-serial (`smartd.CT1000P2SSD8-2146E5E54409.nvme.state`), and the post-boot log names
  `/dev/nvme0` / `/dev/nvme1`, which did not move. No stale kernel path was found.
- hwmon mapping is stable: `hwmon1` is the KINGSTON (`NVMe2`, `nvme1`) with Composite +
  Sensors 1–3, `hwmon2` is the CT1000 (`Cache1`, `nvme0`) with Composite only. That explains
  H2/H3 (see Appendix D).
- Grafana restarted at 01:13:49 and logged `finished to provision dashboards` with no
  provisioning errors. The dashboard template already filters on `serial_no` and uses the
  `device` label only for the legend, so the reboot did not retarget a panel.
- The disk-health MCP returned the new parallel-list payload with the correct `labels` and
  `serials` after the reboot; `devices` was all `""` only because its SSH channel was stale
  (T-04), not because the identity pairing was lost. Reload/reconnect the MCP before using
  the SSH-backed live-device fields.

**Done when.** Every source agrees after a reorder; no tag goes stale; dashboards and
disk-health MCP report the requested physical disk. **Met:** source-level identity and
mounts are proven after re-enumeration, and the InfluxDB side of the MCP reports the same
serial↔label pairs. The remaining MCP caveat is the post-reboot SSH channel (T-04), not
identity. The only source that still cannot name the disk is `inputs.temp`/hwmon (T-09), a
pre-existing attribution gap rather than a stale tag. The full bash and MCP capture commands
are in Appendix D; the raw before/after evidence is reproducible with them.

**Second reboot proof (boot #4, 2026-10-21 22:10 CEST boot, captured 23:45 CEST).** The host
was rebooted once more and the kernel re-enumerated the three SATA disks into a *third*
permutation — none of the kernel names match the T-12 table above:

| Role | Serial | Kernel at boot #3 (T-12) | Kernel now (boot #4) | Influx `device` label (21:45 UTC) | Mount now |
|---|---|---|---|---|---|
| Data1 | `ZVTFF270` | `sda` | **`sdc`** | `Data1` | `/mnt/data1` ← `/dev/sdc1` |
| Data2 | `ZVTFE2SL` | `sdd` | **`sdb`** | `Data2` | `/mnt/data2` ← `/dev/sdb1` |
| Parity1 | `ZVTFF3JB` | `sdb` | **`sda`** | `Parity1` | `/mnt/parity1` ← `/dev/sda1` |
| System | `2421E8B28A83` | `sdc` | **`sdd`** | `System` | `/` ← `/dev/sdd2`, `/boot/efi` ← `/dev/sdd1` |
| Cache1 | `2146E5E54409` | `nvme0n1` | `nvme0n1` | `Cache1` | `/mnt/cache1` |
| NVMe2 | `50026B7383E4529D` | `nvme1n1` | `nvme1n1` | `NVMe2` | — (monitor-only) |

Verified through the MCP after the operator reloaded it:

- `list_disks` returned all six disks with their serials and the new kernel names; every one
  of those names is a valid `get_disk_health` argument.
- `get_mount_status` showed `LABEL=`/by-uuid mounts on the new names: `data1`→`sdc1`,
  `data2`→`sdb1`, `parity1`→`sda1`, root→`sdd2`, cache→`nvme0n1`. No filesystem moved.
- The 21:45 UTC Telegraf poll wrote the same serial↔label pairs as before the reboot. The
  three HDDs are already spun down again, so all four polls so far carry
  `exit_status = 2` **with** the static `serial_no` tag (`Data1`=`ZVTFF270`,
  `Data2`=`ZVTFE2SL`, `Parity1`=`ZVTFF3JB`) — exactly the attribution the static tag exists
  for. The SSDs report `exit_status = 0`.
- `get_full_disk_report()` returned the parallel-list payload with `devices`,
  `labels` and `serials` aligned and `Identity: verified` for the three disks with a valid
  sample (the HDDs have no valid sample while asleep, by design: `nocheck = standby`).
- T-06's done-when still holds: `get_smart_attributes("nvme0n1")` resolves by serial
  (`Cache1`, `2146E5E54409`, 8 % wear, 35 °C) and `get_nvme_health("sda")` is rejected.
- `get_snapraid_status()` works again over the scoped `sudo -n /usr/local/bin/snapraid
  status` (no sync in progress, no errors), confirming the T-02/T-03 privilege model survived
  the reboot.

**T-06 verdict: holds.** A second independent re-enumeration under the new code (and the fourth boot in the investigation) left every static label, serial
and mount pair unchanged, and nothing in Telegraf, Grafana, the disk-health MCP or the mount
layout depends on a kernel name any more.

---

## P2 — MCP tool defects

### T-13 — `run_smart_test` must report the real failure and actually start tests

- [ ] Stop folding every non-zero smartctl exit into "standby", and make tests start.

**Why.** `run_smart_test` claimed both `/dev/nvme1n1` (cache disk at ~3 reads/s) and `/dev/sdb`
(the mounted root disk) were "in standby mode"; no self-test ever started. Smartctl exit
status 2 / `-n standby` semantics do not map to NVMe; after the sudo change, a failing `sudo`
whose non-zero exit is folded into the same message is the more likely cause.

**Do.** Surface smartctl's own stderr; distinguish sudo failure, unsupported device and true
standby; skip `-n standby` for NVMe; check device state before claiming standby; return the
actual test initiation result and where to read the log.

**Done when.** A short test starts on the root disk and the busy cache disk; a permission
failure is reported as such, never as "standby".

---

### T-14 — `start_service` must not report success when nothing happened

- [ ] Check state before starting and gate the mutating call consistently.

**Why.** `start_service("grafana")` on an already-running container returned
`"✅ Service 'grafana' started"` because Docker's `start` is a no-op that echoes the name with
exit 0. `start_service` is also the only mutating tool without a `confirm` gate.

**Do.** Check running state first and report "already running"; add the same `confirm`/dry-run
contract as the other mutating tools.

**Done when.** Starting a running container reports "already running"; an unconfirmed call
does not mutate.

---

### T-15 — Parsing and formatting fixes

- [ ] Fix the small output defects that mislead or hide information.

**Items.**

- [ ] `get_snapraid_status` — `data.fields` is `{"SnapRAID status report": ""}`; nothing is
      parsed. Parse the report (or expose the raw text explicitly).
- [ ] `list_disks` — returns raw JSON in `text` while every other tool formats text.
- [ ] `list_service_files` — a missing subdirectory returns
      `"❌ Error listing files: No such file"` with no path; include the path.
- [ ] `.env` masking — every value is redacted (`TZ`, `IMMICH_VERSION`, `DB_HOSTNAME`), so
      harmless config cannot be verified. Mask secrets only.
- [ ] NVMe `Error Log Entries: 685` — displayed inside a green ✅ with no severity
      interpretation; add a warning/explanation.
- [ ] `query_influxdb` `GROUP BY device` — aggregate rows come back without the grouping
      column, so per-device results are unattributed; document the gotcha or include the key.

**Done when.** Each case produces useful, accurate output and the tests cover it.

---

### T-16 — Tool-routing gaps

- [ ] Route host units and file-based logs correctly, and detect Ansible-managed services.

**Items.**

- [ ] `search_service_logs("telegraf")` → "Unknown service": host units are invisible to the
      container tools. Add a hint pointing at `get_host_service_logs`.
- [ ] `search_service_logs("swag", "error")` → "No matches" is misleading: nginx
      access/error logs are files inside the container, not on stdout.
- [ ] `compose_*` on Ansible-managed service directories (`grafana`, `influxdb`, `rclone`, …)
      returns raw Docker `"no configuration file provided: not found"`. Detect the ~15
      `docker_container`-managed services and say so.
- [ ] Host logs have no `since`/pattern support, and `lines=1000` overflows the 64 KB
      transport. Add `since` and `search_host_service_logs`, and truncate explicitly.

**Done when.** Each call returns an actionable message instead of a misleading empty/raw
error; host-log search works.

---

### T-20 — Attribute overview failed polls by serial

- [ ] Make `get_full_disk_report()` attach failed polls by serial, not just by label.

**Why.** Telegraf now writes a static `serial_no` tag on standby/failed rows
(2026-10-21 01:10 CEST), so `_failed_poll_selector()` in `get_disk_health()` already finds
the newest standby row after a label change. The overview path does not:
`_influxdb_recent_failures_by_device()` selects only `device, exit_status, time` and groups
by `device`; `_influxdb_latest_device_rows()` then attaches failures with
`failures_by_device.get(label, [])`, where `label` is the `device` tag of the newest *valid*
sample. For Parity1 that sample still carries the pre-reboot legacy tag `sdc`, so the
overview reports failures only up to 21:25 and omits the 22:30+ `Parity1` standby rows. The
per-disk report on the same data lists the 23:10 `Parity1` row correctly.

**Do (server-mcp, not this repo).**

- Select `serial_no` in `_influxdb_recent_failures_by_device()` and key the grouped result
  by serial when present, keeping a label key for legacy rows with no serial.
- Attach failures by the valid sample's `serial_no` first, falling back to `device` only
  when the serial is empty.
- Add a regression test with a legacy-`device` valid sample and newer standby rows carrying
  only `serial_no`; assert the newest standby row appears in the overview summary.

**Status note (2026-10-21 23:55 CEST).** Deprioritised by two changes: the `device` tag is now
a static label, so a reboot no longer makes the overview disagree with the per-disk path, and
the InfluxDB store reset (T-21) removed the legacy-tag rows this item was written against.
Still worth fixing before the next relabel, since the two paths should not rely on the label
being stable.

**Done when.** The overview for Parity1 includes the latest standby poll and a label change
does not hide failures; the per-disk and overview summaries agree.

---

## P3 — Deployment and host hygiene

### T-17 — Restore Invidious

- [ ] Find out why the main container is missing and bring it back.

**Why.** `invidious-companion` and `invidious-db` are up (44 h), but no `invidious`
container exists; `/srv/invidious` contains only `db/`. The role creates db → companion →
invidious and references `invidious_postgres_password`, `invidious_companion_key`,
`invidious_hmac`, `invidious_po_token`; none are defined in `host_vars/catafalco/vars.yml`, so
a missing vault variable is the prime suspect for the play failing on the main-container task.

**Done when.** The `invidious` container exists and is healthy after a clean role run.

---

### T-18 — Trim or correct the allowlisted host units

- [ ] Stop pointing the MCP at units that do not exist.

**Why.** `snapraid.service` and `mergerfs.service` return "could not be found"; only `docker`,
`smartd`, `smbd` and `telegraf` exist. SnapRAID is timer/cron driven.

**Done when.** `security.host_units` lists only real units, or points at the relevant timers.

---

### T-19 — Clean up service-directory leftovers

- [ ] Decide whether the empty service directories are intentional.

**Why.** `/srv/openwebui` and `/srv/rclone` have no containers (openwebui is not in
`containers`); non-compose containers show `PROJECT = -` / `service = (allowlisted)`.

**Done when.** Each leftover is removed, added to the deployment, or documented as expected.

---

## Suggested execution order

0. **T-21** — stop InfluxDB from discarding its store on every recreate. It is losing data
   every time the container is recreated (silently), which blocks any trend-based disk
   analysis and hides the migration of the `device` tag described above.
1. **T-01** — rotate the leaked password (security first). ✅ 2026-10-21
2. **T-02 + T-03 + T-04** as one privilege change: add scoped rules, remove blanket writes,
   restore SMART and the MCP SSH channel. Do not run the playbook in between in a way that
   restores the blanket grant. ✅ 2026-10-20/21
3. **T-05** — make stale/mismatched health impossible to misread before using the tools again.
   ✅ 2026-10-21
4. **T-06 / T-07 / T-08 / T-09 / T-11** — fix identity at the source, then the consumers.
   T-06 and T-07 are done; T-08, T-09 and T-11 remain open. See the T-06 implementation note.
5. **T-12** — prove it with a shuffle/reboot. ✅ 2026-10-21 01:15 CEST, see T-12.
6. **P2 and P3** — remaining tool and host hygiene. T-20 is the MCP-side follow-up found
   while verifying the serial tag; it does not block the source-level identity proof.

---

## Appendix A — Disk order before and after the reboot

### Boot #1 (started 2026-10-19 00:28, kernel `6.12.113+deb13-amd64`)

| Kernel name | Model | Serial | Size | Bus | Role (`host_vars`) | Mounted at |
|---|---|---|---|---|---|---|
| `sda` | ST18000NT001-3NF101 | `ZVTFF270` | 16.4T | sata | `data_disks[1]` **Data1** | `/mnt/data1`, `/mnt/snapraid-content/disk1` |
| `sdb` | CT480BX500SSD1 | `2421E8B28A83` | 447.1G | sata | `system_disks` **System** | `/` (`sdb2`), `/boot/efi` (`sdb1`) |
| `sdc` | ST18000NT001-3NF101 | `ZVTFE2SL` | 16.4T | sata | `data_disks[2]` **Data2** | `/mnt/data2`, `/mnt/snapraid-content/disk2` |
| `sdd` | ST18000NT001-3NF101 | `ZVTFF3JB` | 16.4T | sata | `parity_disks[1]` **Parity1** | `/mnt/parity1` |
| `nvme0n1` | KINGSTON SNV3S1000G | `50026B7383E4529D` | 931.5G | nvme | `system_disks` **NVMe2** | — (monitor-only) |
| `nvme1n1` | CT1000P2SSD8 | `2146E5E54409` | 931.5G | nvme | `cache_disks[1]` **Cache1** | `/mnt/cache1`, pool `mergerfs_cache` |

InfluxDB SMART snapshot at capture time (max over 24 h, from `smart_device`):

| Tag `device` | Serial | Model | Temp | POH | Life | Spare | Error log | Unsafe shutdowns |
|---|---|---|---|---|---|---|---|---|
| `nvme0` | 50026B7383E4529D | KINGSTON SNV3S1000G | 35–40 °C | 4 164 | 4 % | 98 % | 0 | 105 |
| `nvme1` | 2146E5E54409 | CT1000P2SSD8 | 32–41 °C | 37 381 | 8 % | 100 % | 685 | 199 |
| `sda` | ZVTFF270 | ST18000NT001-3NF101 | 25–31 °C | 15 013 | — | — | 0 | — |
| `sdb` | 2421E8B28A83 | CT480BX500SSD1 | 26–31 °C | 8 424 | — | — | 0 | — |
| `sdc` | ZVTFE2SL | ST18000NT001-3NF101 | 25–31 °C | 15 010 | — | — | 0 | — |
| `sdd` | ZVTFF3JB | ST18000NT001-3NF101 | 28–33 °C | 14 931 | — | — | 0 | — |

The SATA order is role-mixed: Data1 (`sda`), *system SSD* (`sdb`), Data2 (`sdc`),
Parity1 (`sdd`). Nothing guarantees that layout survives a reboot; probe order is
per-controller/per-port and changes when disks are added, moved, or a controller is
re-enumerated.

### Boot #2 (started 2026-10-20 22:30:53 CEST)

Source: `diskio` udev tags (`name`, `ID_SERIAL_SHORT`, `ID_MODEL`) sampled at 20:35:50 UTC;
the SSH-backed tools were unavailable, so this was reconstructed from InfluxDB.

| Serial | Model | Role | Kernel name **boot #1** | Kernel name **boot #2** | Changed? |
|---|---|---|---|---|---|
| `ZVTFF270` | ST18000NT001-3NF101 | Data1 | `sda` | `sda` | — |
| `ZVTFE2SL` | ST18000NT001-3NF101 | Data2 | `sdc` | **`sdb`** | yes |
| `ZVTFF3JB` | ST18000NT001-3NF101 | Parity1 | `sdd` | **`sdc`** | yes |
| `2421E8B28A83` | CT480BX500SSD1 | System (root) | `sdb` | **`sdd`** | yes |
| `2146E5E54409` | CT1000P2SSD8 | Cache1 | `nvme1n1` | **`nvme0n1`** | yes |
| `50026B7383E4529D` | KINGSTON SNV3S1000G | NVMe2 (monitor-only) | `nvme0n1` | **`nvme1n1`** | yes |

**5 of 6 disks changed kernel name across one reboot**, and the two NVMe drives swapped
positions. The console `lsblk` after the reboot agrees with the udev view: `nvme0n1` is mounted
at `/mnt/cache1` (CT1000P2SSD8, ext4 `LABEL=Cache1`), while `nvme1n1` (KINGSTON) carries an
`nvme1n1p1` partition and is not mounted — only one of the two NVMe drives is in use, matching
the design (`system_disks` entry `NVMe2` is monitor-only).

Same instant, two different answers from the MCP:

```text
get_disk_health("nvme0n1") -> KINGSTON SNV3S1000G, serial 50026B7383E4529D   # stale tag
live nvme0n1 (diskio)      -> CT1000P2SSD8,       serial 2146E5E54409        # /mnt/cache1
get_disk_health("sdb")     -> CT480BX500SSD1,     serial 2421E8B28A83        # root disk
get_disk_health live sdb   -> ZVTFE2SL, ST18000NT001-3NF101                 # Data2
```

Both MCP answers were green ✅ with "Sample: 20 minutes ago". Before the reboot they described
the right disk; after one reboot they confidently describe a different one.

### Boot #3 (started 2026-10-21 01:13:10 CEST)

The T-12 reboot moved three SATA disks again: Data2 `sdb -> sdd`, Parity1 `sdc -> sdb`,
System `sdd -> sdc`; Data1 stayed `sda`, and both NVMe names stayed `nvme0n1` / `nvme1n1`.
The static `device` label and the new static `serial_no` tag kept the serial↔label pairing
unchanged (23:15 UTC poll), and the `LABEL=` mounts followed the serials to the new kernel
names. The full before/after table and evidence are in T-12.

### Boot #4 (started 2026-10-21 22:10 CEST)

Captured 23:45–23:50 CEST through the MCP after the operator reloaded it. The SATA disks
landed in a **third** order — every one differs from both the pre-T-12 and the post-T-12
layout, while both NVMe names stayed put:

| Serial | Model | Role | Boot #1 | Boot #2 | Boot #3 | **Boot #4** |
|---|---|---|---|---|---|---|
| `ZVTFF270` | ST18000NT001-3NF101 | Data1 | `sda` | `sda` | `sda` | **`sdc`** |
| `ZVTFE2SL` | ST18000NT001-3NF101 | Data2 | `sdc` | `sdb` | `sdd` | **`sdb`** |
| `ZVTFF3JB` | ST18000NT001-3NF101 | Parity1 | `sdd` | `sdc` | `sdb` | **`sda`** |
| `2421E8B28A83` | CT480BX500SSD1 | System (root) | `sdb` | `sdd` | `sdc` | **`sdd`** |
| `2146E5E54409` | CT1000P2SSD8 | Cache1 | `nvme1n1` | `nvme0n1` | `nvme0n1` | `nvme0n1` |
| `50026B7383E4529D` | KINGSTON SNV3S1000G | NVMe2 (monitor-only) | `nvme0n1` | `nvme1n1` | `nvme1n1` | `nvme1n1` |

Nothing under the new code cared: the 21:45 UTC Telegraf poll wrote `Data1`/`Data2`/`Parity1`/
`System`/`Cache1`/`NVMe2` with the same serials, and `findmnt` shows `/mnt/data1`→`sdc1`,
`/mnt/data2`→`sdb1`, `/mnt/parity1`→`sda1`, `/`→`sdd2`, `/mnt/cache1`→`nvme0n1`. The three
HDDs were already asleep again, so their rows carry `exit_status = 2` and only the static
`serial_no` tag — the case the tag was added for. See T-12 for the full verification list.

Post-reboot `get_full_disk_report()` (extract):

```text
Cache1 (/dev/nvme0n1) - CT1000P2SSD8     | Health: PASSED | Serial: 2146E5E54409 | Identity: verified
System (/dev/sdd)     - CT480BX500SSD1   | Health: PASSED | Serial: 2421E8B28A83 | Identity: verified
NVMe2  (/dev/nvme1n1) - KINGSTON SNV3S1000G | Health: PASSED | Serial: 50026B7383E4529D | Identity: verified
```

The three HDDs are absent from that list because they have no valid sample while asleep
(`nocheck = standby` keeps them asleep on purpose); T-05's rule is what stops the tool from
calling them healthy.

**Storage is not at risk.** Every filesystem came back on the right disk. The `disk`
measurement at 20:35 UTC shows `/`, `/boot/efi`, `/mnt/data1`, `/mnt/data2`, `/mnt/parity1`,
`/mnt/cache1`, `/mnt/storage`, `/mnt/storage_slow`, `/mnt/storage_cache` and both
`/mnt/snapraid-content/diskN` mounts present, with the same usage as before the reboot.

---

## Appendix B — What is already order-independent (do not regress)

- **Mounts** — `roles/mounts/tasks/main.yml` uses `src: LABEL=<label>` for data, content,
  cache and parity mounts; fstab pins filesystems by label, not `sdX`.
- **mergerFS** — pool branches are globs (`/mnt/data*`, `/mnt/cache*`), not device names.
- **SnapRAID** — configured against mount points (`/mnt/data1`,
  `/mnt/snapraid-content/diskN`) and content files, never against devices.
- **Telegraf `[[inputs.smart]]` device list** — built from by-id paths resolved by serial at
  deploy time (`roles/telegraf/tasks/main.yml:97-129`, with an assert that exactly one
  `ata-*_<serial>` / `nvme-*_<serial>` link matches). smartctl always talks to the intended
  physical disk, and `-n standby` keeps sleeping HDDs asleep.
- **`[[inputs.diskio]]`** — carries `device_tags = ["ID_SERIAL_SHORT", "ID_MODEL"]` next to
  the kernel-name `name` tag (`roles/telegraf/templates/telegraf.conf.j2:217-219`).

---

## Appendix C — What is still kernel-name dependent

Most of this appendix is now historical. The 2026-10-21 T-06/T-12 change removed the
kernel name from the SMART identity path. The remaining dependencies are:

1. **SMART identity is fixed.** `roles/telegraf/tasks/main.yml` resolves the by-id path by
   serial (and asserts exactly one match); the template writes a static label to `device`
   and a static `serial_no` tag on every poll, including standby/failed rows. No kernel
   name is baked into Telegraf. History written before 2026-10-21 still carries kernel names
   under `device`; join that history on `serial_no`.
2. **`inputs.temp` (hwmon) has no disk identity.** Schema is still only
   `host, sensor, temp, time`, and the two NVMe drives both emit an `nvme` sensor named
   `Composite`. The T-12 hwmon map shows `hwmon1` = KINGSTON (`NVMe2`, `nvme1`) with
   Composite + Sensors 1–3 and `hwmon2` = CT1000 (`Cache1`, `nvme0`) with Composite only,
   so the series are not interchangeable. Per-drive attribution still needs a PCI/by-id
   mapping, or hwmon should be dropped in favour of `smart_device.temp_c` (T-09).
3. **smartd is no longer kernel-path dependent in this deployment.** `/etc/smartd.conf` is
   one `DEVICESCAN` line and the state files are named by model-serial; the
   `Device: /dev/nvmeX` text in the journal is informational. If explicit devices are ever pinned,
   use `/dev/disk/by-id/*` rather than `/dev/sdX` (T-08).
4. **disk-health MCP is serial-first now.** `get_disk_health`, `get_nvme_health` and
   `get_smart_attributes` resolve the live serial and select `serial_no = '<serial>'`; the
   device tag is only a fallback. `get_full_disk_report` partitions by `serial_no`. The
   remaining exceptions are the overview's failed-poll grouping by `device` (T-20) and the
   need for a live SSH channel to resolve kernel names (T-04).
5. **Grafana S.M.A.R.T. panels key on `serial_no`; `diskio` keeps the kernel-name `name`
   tag** (plus `ID_SERIAL_SHORT` / `ID_MODEL` device tags). `diskio.name` is runtime-only;
   use the serial tags for any join or long-lived panel.

The stable identity published is `smart_device.serial_no` and `diskio.ID_SERIAL_SHORT`.
The `device` tag is a static, human-readable label and the static `serial_no` tag keeps
standby/failed rows attributable, but the live serial field remains the primary identity.
Rows can always be re-joined correctly on those values.

---

## Appendix D — Evidence, open hypotheses and capture checklist

### SMART outage evidence

Last `smart_device` row with `exit_status = 0`: **20:15:00 UTC (22:15 CEST)**. Every poll after
that — 20:20, 20:25, 20:30 (still boot #1) and 20:35, 20:40 (boot #2) — carries
`exit_status = 1` for **all six devices** and no other field (no model, serial, temperature or
power state). Standby rows used to look different (`exit_status = 2`, `power = STANDBY`), so
this is not a sleeping-disk artefact.

Root cause: the passwordless sudo grant was removed at ~22:19 CEST. `[[inputs.smart]]` runs
with `use_sudo = true`, and the `telegraf` user was added to the `sudo` group by the role with
no dedicated sudoers rule; the grant came implicitly from the blanket line. With that line
gone, `sudo smartctl` cannot run non-interactively, so no device is readable. Every other input
(cpu, mem, system, disk, diskio) needs no root and kept working, which is why the outage is
invisible outside S.M.A.R.T.; `system.uptime = 237 s` at 20:34:50 proves Telegraf restarted
cleanly after the reboot. The timestamp matches the `run_smart_test` calls at 20:19–20:20 UTC,
which returned "standby" — almost certainly the same sudo failure, misread by the MCP.

Impact at the time: every SMART consumer was frozen on the 20:15 sample — Grafana S.M.A.R.T.
panels and all disk-health MCP tools, which would keep showing it as green for up to 24 h
(`get_full_disk_report` printed "Sample: 26 minutes ago" with no warning). Collection was
restored at 23:35 CEST; see "Host verification" below. The stale-sample warning itself is
still T-05.

### Other evidence

- **smartd false critical temperature:** every 30 min on `/dev/nvme0`,
  `Temperature 58 Celsius reached critical limit of 50 Celsius (Min/Max 58/75)`, against
  per-serial composites of 32–41 °C. 58 °C matches hwmon `nvme_sensor_2 = 57.85 °C` (composite
  on the same sample: 35.85 °C). Either smartd checks a secondary NVMe sensor rather than the
  composite, or its `/dev/nvme0` is not the disk Telegraf tags `nvme0`. The colliding hwmon
  series prevent telling which drive owns sensor 1/2, so the 58 °C cannot be attributed yet.
- **smartd skipped checks:** `Device: /dev/sda [SAT], is back in IDLE_A mode, resuming checks
  (9 checks skipped)`, `sdc … (7 checks skipped)` — expected `nocheck=standby` behaviour.
- **Sparse SATA rows:** `sda` and `sdc` are sampled every ~60 min while `sdd` is sampled every
  5 min; the two spend most of their time in standby. Not a bug, but "sample age" is a poor
  liveness signal for HDDs.

### Host verification (2026-10-20 23:35 CEST)

- `sudo -n true` → `sudo: a password is required` (rc 1): the admin user no longer has
  passwordless sudo.
- `id -nG telegraf` → `telegraf docker`: the service account is no longer in `sudo`.
- `/etc/sudoers.d/telegraf-smart` and `/etc/sudoers.d/snapraid-status` exist as
  `root:root 0440`.
- Telegraf restarted at 23:29:57; the first poll at 23:35:00 returned fresh data for all six
  disks: `nvme0` = CT1000P2SSD8, `nvme1` = KINGSTON, `sda` = ZVTFF270, `sdb` = ZVTFE2SL,
  `sdd` = CT480BX500SSD1; `sdc` was in standby (`exit_status = 2`, expected).
- After the restart the journal has no `a password is required` and no
  `pam_unix(sudo:session)` lines; sudo command lines remain for audit.
- `get_snapraid_status` works through its scoped rule; all tested SSH-backed MCP tools
  (`get_server_health`, `list_disks`, `get_mount_status`, `get_io_stats`,
  `get_host_service_*`, `list_containers`, `get_service_status`, `get_service_logs`) answer.

### Hypotheses

- **H1 — CONFIRMED 2026-10-20 22:35 CEST.** The baked kernel-name mapping is stale vs. the
  live order: 5 of 6 devices moved (Appendix A), and `get_disk_health()` still answers from the
  old tag ↔ serial pairing (`nvme0n1` → KINGSTON, `sdb` → CT480). Proven with `diskio`'s
  `name` ↔ `ID_SERIAL_SHORT` vs `smart_device`'s `device` ↔ `serial_no` (SSH was down, so
  `lsblk` came from the console).
- **H2 — RESOLVED 2026-10-21 01:13 CEST.** smartd watches the **KINGSTON** (`NVMe2`), not
  the CT1000. Pre-reboot the same warning named `/dev/nvme0` when that was the KINGSTON;
  post-reboot it names `/dev/nvme1`, which is still the KINGSTON, and logs
  `initial Temperature is 58 Celsius` at startup. `hwmon1` maps to the KINGSTON (`nvme1`)
  and exposes Sensor 2; the composite is ~38 °C. So smartd reads a secondary sensor, not a
  different disk. The false critical alarm is a threshold/monitoring choice (T-08/T-09),
  not misattribution.
- **H3 — RESOLVED / NARROWED 2026-10-21 01:13 CEST.** The hwmon map is explicit: `hwmon1`
  is the KINGSTON (`NVMe2`, `nvme1`) with Composite + Sensors 1–3; `hwmon2` is the CT1000
  (`Cache1`, `nvme0`) with Composite only. The previous "4 series for 2 drives" was one
  drive exposing the extra sensors, not two drives colliding on a full set. The remaining
  collision is the shared `sensor=Composite` tag in `inputs.temp`, so per-drive attribution
  still needs a PCI/by-id mapping or should use `smart_device.temp_c` (T-09).

H1 is settled by T-06, H2 is settled, and H3 is narrowed to the `inputs.temp` tag
collision. The T-12 capture was taken with Ansible while the MCP SSH channel was stale
(T-04), so the host-side evidence is complete even though the agent view is not.

### Post-reboot / post-fix capture checklist

Run these on the host (and the MCP calls in brackets), and diff against Appendix A. The
checklist was run for T-12 on 2026-10-21 01:13–01:15 CEST; the host block was executed
through Ansible because the MCP SSH channel was stale after the reboot. The before/after
results are in T-12.

```bash
uname -r; uptime -s
lsblk -o NAME,MODEL,SERIAL,SIZE,TRAN,TYPE                 # [list_disks]
ls -l /dev/disk/by-id/ | grep -vE -- '-part[0-9]+$'        # serial -> live kernel name
for t in /mnt/data1 /mnt/data2 /mnt/parity1 /mnt/cache1 /mnt/storage; do
  echo "-- $t"; findmnt -no SOURCE,LABEL,TARGET "$t" || true
done
cat /etc/smartd.conf                                      # DEVICESCAN, state files by model-serial
# hwmon -> PCI/device attribution for the NVMe sensors:
for h in /sys/class/hwmon/hwmon*; do
  echo "== $h $(cat $h/name 2>/dev/null) -> $(readlink -f $h/device 2>/dev/null)"
  for f in $h/temp*_label; do [ -e "$f" ] && echo "   ${f##*/}: $(cat $f)";
  done
done
```

MCP side (use the structured payload, not the text lines):

```text
list_disks()                                   # live names
get_mount_status()                             # labels still on the intended disks
get_full_disk_report()                         # .data = {devices, labels, serials} parallel lists
query_influxdb("SELECT time, device, serial_no, model, temp_c FROM smart_device
                WHERE time > now() - INTERVAL 15 MINUTE ORDER BY time DESC")
get_host_service_logs(unit="smartd", lines=50) # which /dev/nvmeX smartd watches
```

The earlier boot-#2 attempt (22:35 CEST) could not run the host block because the MCP SSH
channel was dead; Appendix A's boot-#2 table was reconstructed from `diskio` udev tags. The
T-12 run repeated the host block successfully through Ansible and confirmed the hwmon map.

**Decision rule:** if the serial↔label pairing in InfluxDB changes, or a `device` label no
longer points at the configured serial, the deployment is stale. Re-run
`ansible-playbook catafalco.yml --tags telegraf` only *after* T-02/T-06/T-07 so it does not
reintroduce a kernel-name identity, and treat all pre-2026-10-21 history under `device` as
mixed (join it on `serial_no`).

---

## Appendix E — Verified working (do not regress)

`get_server_health`, `list_services`, `list_containers`,
`get_host_service_{status,logs}`, `get_service_status` (multi-container + per-container-name
resolution), `get_service_logs` (`since`/`until`/`container` scoping, clear cross-project
rejection), `get_container_health` (including the "no healthcheck" case), `get_service_file`
traversal/absolute-path rejection and `.pem` refusal, `list_service_files` traversal
rejection, `compose_ps/pull/up/down` confirm gate and dry-run preview,
`restart_service`/`stop_service` dry runs, InfluxDB write-injection rejection, InfluxDB real
error surfacing (HTTP 500 schema errors and 404 unknown database are now visible instead of
SWAG's HTML error page), `get_mount_status`, `get_snapraid_status`, `get_io_stats`, and
`get_disk_health`/`get_nvme_health` for correctly named devices.

Re-verified end to end right after boot #4 (2026-10-21 23:45 CEST, post-MCP-reload): the
SSH-backed tools listed above, `get_full_disk_report()` with the parallel
`devices`/`labels`/`serials` payload, `get_smart_attributes("nvme0n1")` resolving by serial,
and `get_snapraid_status()` over the scoped sudo rule.

---

## Appendix F — Source history

This document merges and supersedes:

- `docs/disk-identity-investigation.md` — disk ordering/naming evidence, H1/H2/H3, SMART
  outage root cause, candidate identity fixes.
- `docs/mcp-tool-audit-2026-10-20.md` — MCP defect inventory, deployment findings, verified
  working list, privilege-model change.

Both source files were deleted to keep one document. Update this file with new evidence,
status changes and completed items; do not recreate separate findings files unless the scope
genuinely diverges.
