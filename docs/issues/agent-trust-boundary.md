# Agent trust boundary and MCP privilege scope — assessment & TODO

**Status:** OPEN · **Last updated:** 2026-10-24 01:00 CEST
**Hosts:** laptop (`alessio`, UID 1000) and `catafalco` (`192.168.178.3`)
**Track:** **S** — new. The **T-01 … T-21** disk/MCP track is closed (git history `8f348cf`).
**Scope:** the `pi` harness, `remote-server-mcp`, `disk-health-mcp`, the Ansible/vault
credential plane, the deploy plane (S-17/S-18), and the privilege model of `catafalco`.

> **Assessment only.** No host, repository or MCP change was made while producing this
> document. Every credential named below is treated as exposed: rotate it before, or while,
> implementing the fixes. The document deliberately records secret *key names* and file
> *paths/modes*, never secret values.
>
> The assessment process itself ran with UID 1000 and therefore had the access described in
> S-01. No secret value was copied into this document, but the fact that it could have been
> is the finding.

---

## Verdict

The MCP whitelist is well designed, but **it is not the only path to the server**. The agent
runs as `alessio`, with a shell, the unencrypted SSH keys, the Ansible vault password, and
write access to the MCP's own source and configuration. On `catafalco`, the SSH user
(`funkysloth`) is in the `docker` group, which is root-equivalent.

An agent therefore does not need to defeat the MCP at all: it can bypass it with
`ssh` or `ansible` and obtain root. The whitelist protects against accidental misuse of the
MCP tools; it does not protect against a hostile or prompt-injected model. The fix is
architectural: **the process that holds the credentials must not be the process that runs
model-generated code**, and the MCP must be the only reachable path to the host.

Removing the credential must not remove the capability. The agent keeps the
`deploy → collect output → fix → redeploy` loop through a broker that owns the vault and
streams redacted results back; otherwise the sandbox trades one critical risk for the loss
of the agent's primary task class and will be bypassed to get it back (S-17, Phase 1.5).

---

## Current state (2026-10-23)

| Area | State | Consequence |
|---|---|---|
| MCP command policy | **Sound:** fixed catalog, canonical `shlex.join` argv allowlist, no generic execution, no `docker run`/`exec` | The MCP tools cannot be turned into a shell through input alone |
| MCP file policy | **Mostly sound:** SFTP `realpath` confinement, sensitive-name blocks, `.env`/config redaction | Content reads are constrained; redaction has two gaps (S-08) and `get_service_file` is broad (S-09) |
| Agent isolation | **None:** `pi` runs as `alessio` with the host home, SSH agent, vault and Ansible | The MCP is bypassable; host credentials are readable/writable (S-01, S-05, S-06) |
| Remote privilege model | **Root-equivalent:** `funkysloth` is in `docker` and `sudo`; the MCP uses the same user | A stolen SSH key or a direct `ssh` is root on `catafalco` (S-02) |
| Vault | **Effectively unlocked:** 9-byte password in `~/.vault_pass` (0644) and `.vaults` (0600) | The admin password, `ansible_ssh_pass` and every app/API secret are decryptable by the agent (S-03) |
| Ansible | **Arbitrary root executor** available to the agent | `ansible-playbook` with `become: true` is a root shell (S-04) |
| Agent deploy loop | **Exists only by holding the credential:** the same shell, key and vault | Isolating the agent removes it unless a broker replaces it (S-17); the pressure to bypass the sandbox comes back with it |
| SSH transport | **Keys without passphrase**, loaded in `ssh-agent`; host-key verification enabled in the MCP | The MCP verifies the host; the agent can authenticate directly (S-06) |
| SSH hardening | **Not applied:** `geerlingguy.security` is in `requirements.yml` but not in `catafalco.yml`; no `sshd_config` role | Password auth/root login may still be enabled; `security_ssh_port` is dead config (S-11) |
| Telegraf | **Root-equivalent:** `docker` group + `NOPASSWD: smartctl, nvme` with arbitrary args | A compromised telegraf can format/sanitize NVMe and reach the Docker API (S-07) |
| Destructive MCP actions | **Model-controlled `confirm=true`**, no human gate | A prompt-injected model can stop services or `compose down` (S-12) |
| Audit | **Local, 0600, owned by the agent** | The agent can delete or rewrite its own audit trail (S-13) |
| InfluxDB token | **Readable by the agent** in `~/.config/*-mcp/.env` | The MCP's SELECT-only check is bypassed by using the token directly (S-10) |

**Standing rule for this track:** a control is only a control if the agent cannot
read, write or bypass its enforcement point. Anything owned by UID 1000 on the laptop is
inside the agent's trust domain.

---

## Threat model

### Assets

1. **Host credentials:** SSH private keys, `ssh-agent`, Ansible vault password, admin password,
   `ansible_ssh_pass`.
2. **Secret material:** every key in `host_vars/*/secret.yml` and `group_vars/*/secret.yml`
   (cloud/DNS tokens, backup keys, mail password, app admin passwords, DB passwords,
   monitoring tokens, AI tokens, Samba passwords).
3. **Laptop data:** browser and mail profiles, `~/.config/gh`, `~/.pi/agent` sessions,
   shell history, the MCP audit log.
4. **Remote data:** `/srv` service configs and `.env` files, container logs and health output,
   Docker configuration, SnapRAID content, the InfluxDB store.
5. **Availability:** the media server, the NAS array, and the containers.

### Adversaries

- A **prompt-injected model** steered by repo content, logs, file contents or tool output.
- A **malicious or compromised dependency** loaded by the MCP or by `pi`.
- A **curious or over-eager agent** that is not adversarial but takes a shortcut.
- An **attacker with code execution on the laptop** as `alessio` (the agent is one such
  execution context).
- An **attacker on the LAN** who can reach SSH or the reverse proxy.

### Trust boundaries — today

```
model ──► pi (UID 1000, full home) ──► MCP (UID 1000, SSH key) ──► funkysloth@catafalco
                    │                        │                         │
                    └── ssh / ansible ───────┴─────────────────────────┘
                              (bypasses the MCP entirely; funkysloth ∈ docker, sudo)
```

There is effectively **one** trust domain: the laptop user. The MCP is a convenience layer
inside it, not a boundary around it.

### Trust boundaries — target

```
model ──► pi sandbox (no host home, no keys, no vault, no ansible, egress allowlist)
                    │
                    ▼  MCP endpoint + token (agent cannot read the MCP's files)
          MCP service (separate user/container; owns the SSH key or local Docker access;
                       root-owned read-only code; audit → remote sink)
                    │
                    ▼  forced command / broker / narrow Docker proxy
          catafalco: dedicated `mcp` user (no docker, no sudo)
                     root-owned broker validates exact argv
                     telegraf via read-only socket-proxy
                     no password auth, no root login
```

The invariant: **credentials live in a process the agent cannot read or write; the agent can
only call the MCP.** The MCP's whitelist then becomes the real enforcement point.

---

## Attack paths

| # | Path | Preconditions | Impact | Severity |
|---|---|---|---|---|
| A | `ssh catafalco` → `docker run --privileged -v /:/host …` | Unencrypted key (present) + `docker` group (present) | Root on `catafalco` | Critical |
| B | Read vault → `password` → `sudo -S` | Vault password on disk (present) | Root on `catafalco` | Critical |
| C | `ansible-playbook … -K` with vault password | Ansible + vault password + `become` (present) | Arbitrary root tasks | Critical |
| D | Edit `security.py` / `config.yaml` / `mcp.json` | MCP tree writable (present) | Whitelist bypass on next start | Critical |
| E | Read `~/.ssh`, vault, `.env`, browser/mail, `gh` | Agent runs as `alessio` (present) | Full laptop secret exfiltration | Critical |
| F | `search_service_logs` / `get_container_health` / `get_service_file` | MCP reachable (present) | Secret leakage from `/srv` and logs | Medium–High |
| G | Compromise `telegraf` → `nvme format` / Docker API | Telegraf docker + broad sudo (present) | Disk destruction / root | High |
| H | Password SSH or root login | No sshd hardening applied (likely) | Direct login, bypasses key controls | Medium |
| I | Deploy broker used as a root launcher | Broker reachable from the sandbox (Phase 1.5 present) | A role under an allowed tag runs as root on `catafalco` | High |

### Path A — SSH + docker group (no MCP involvement)

The agent shell can run:

```bash
ssh catafalco 'docker run --rm --privileged -v /:/host alpine chroot /host sh -c "id"'
```

`funkysloth` is added to `docker` by `roles/docker/tasks/main.yml`; the MCP config uses the
same user. Docker group membership is equivalent to root: the container can mount the host
root, load kernel modules, or `nsenter` into PID 1.

### Path B — Vault → admin password

`~/.vault_pass` is mode `0644`, 9 bytes. `.vaults` is mode `0600`, 9 bytes, in the repo. Both
are readable by the agent. The vault contains `password` (the admin user's password, hashed
into the account by `roles/system/tasks/user.yml`), `ansible_ssh_pass`, and every application
secret. Decrypting it gives a working `sudo` password and, if password SSH is enabled, a
direct login.

### Path C — Ansible as a root executor

`ansible-playbook` is on the agent's `PATH`. `hosts` sets `ansible_user: funkysloth`;
`catafalco.yml` uses `become: true` with `sudo`; the vault supplies the password. The agent
can run any task as root without touching the MCP.

### Path D — Rewriting the policy

`~/code/server-mcp` and `~/.config/remote-server-mcp` are owned by `alessio`. The agent can
edit `packages/server-management-lib/src/server_management_lib/security.py`, the MCP config
(`known_hosts: none`, `services_path: /`, additional `allowed_containers`), or
`~/.pi/agent/mcp.json`. The next MCP process uses the modified policy. The audit log is also
owned by `alessio`.

### Path E — Laptop exfiltration

The agent can read `~/.ssh/*`, the vault, `~/.config/*-mcp/.env`, `~/.config/gh`,
`~/.mozilla`, `~/.thunderbird`, `~/.pi/agent` sessions, and the audit log. The model API is
itself an exfiltration channel: anything the agent can read can be sent to the provider in a
prompt. Redaction in the MCP reduces the data available, but it cannot protect files the
agent reads directly.

### Path F — MCP data leak

`search_service_logs()` filters lines locally and returns them without `redact_secrets()`;
`get_container_health()` returns raw health-probe output. `get_service_file()` can read any
non-sensitive file below `/srv`, and the redactor is heuristic. Logs, health probes, SQL
dumps and archives are realistic leak vectors.

### Path G — Telegraf

`telegraf` is in `docker` and has `NOPASSWD: /usr/sbin/smartctl, /usr/sbin/nvme` with
arbitrary arguments. `nvme format`, `nvme sanitize`, `nvme admin-passthru` and
`nvme set-feature` are reachable. The `docker` group already makes telegraf root-equivalent,
so the sudoers grant is an additional, unnecessary risk.

### Path H — Missing SSH hardening

`geerlingguy.security` is listed in `requirements.yml` but is **not** in `catafalco.yml`, and
no role writes `sshd_config`. The `security_*` variables (including
`security_ssh_port: 69`) are dead. `hosts_example` even defaults to `ansible_user=root`. The
actual SSH policy depends on the base image and may allow password authentication.

### Path I — the deploy broker launders root

The deploy broker (S-17) is a **credential** boundary, not an authority boundary. Ansible is
Turing-complete root execution over a tree the agent can edit: any task in any role may write
`/etc/sudoers.d`, change `authorized_keys` or mount over a disk. A tag allowlist bounds the
*class* of change, not its authority. So a prompt-injected model with deploy access can still
imprint arbitrary damage, bounded only by the pre-deploy snapshot, the health gate, the
auto-rollback and the deploy budget.

This is accepted deliberately, because the alternative — no deploy capability — does not
survive contact with the actual task class. It is recorded in Appendix E and mitigated by:
destructive tags stay human-gated; every run is anchored to a read-only tree copy whose hash
is recorded off-box; a snapshot precedes every write; rollback is automatic; the deploy
budget stops a looping or injected agent.

---

## Findings

### S-01 — The agent runs with the credentials it is meant to be constrained from

- **Severity:** Critical · **Status:** open
- **Evidence:** `pi` documentation (`docs/security.md` in the pi package): tools run with the
  permissions of the OS user and there is no approval before every call. `id` → `uid=1000(alessio)`.
  `~/.pi/agent/mcp.json` launches the MCP with `uv run --project /home/alessio/code/server-mcp`,
  inheriting `SSH_AUTH_SOCK` and the rest of the environment. `~/.ssh`, `~/.vault_pass`,
  `.vaults`, `~/.config/*-mcp/.env`, `~/code/server-mcp` and the audit log are all owned or
  readable by `alessio`.
- **Why:** a whitelist the caller can bypass is not a security control.
- **Do:** run `pi` in a container/VM with only the workspace (or a copy), a tmpfs home, no
  `~/.ssh`, no `~/.config`, no vault, no `ansible`, no `ssh-agent`. Use a dedicated OS user at
  minimum; a container is the real boundary. Restrict egress to the model API and the MCP.
- **Done when:** inside the agent environment, `ls ~/.ssh` fails, `ansible-playbook` is absent,
  `SSH_AUTH_SOCK` is unset, `ssh catafalco` fails, and the only route to `catafalco` is the MCP.

---

### S-02 — `funkysloth` is root-equivalent via the `docker` group

- **Severity:** Critical · **Status:** open
- **Evidence:** `roles/docker/tasks/main.yml:39` adds `ansible_user` to `docker`;
  `hosts:6` sets `ansible_user: funkysloth`; `~/.config/remote-server-mcp/config.yaml` uses
  `username: funkysloth`; `roles/system/tasks/user.yml` also puts the user in `sudo`.
  `catafalco.yml` runs the main play with `become: true`.
- **Why:** any write access to the Docker API is root-equivalent (`docker run -v /:/host`,
  `--privileged`, `nsenter`). The MCP's whitelist is the only thing standing between the
  agent and `docker run`, and the agent can bypass the MCP with SSH.
- **Do:** remove `funkysloth` from `docker`; create a dedicated `mcp` user with no `docker`
  and no `sudo`; run privileged catalog operations through a root-owned broker that validates
  the exact argv (see S-05 and the target architecture). Do **not** rely on a write-capable
  Docker socket proxy as "least privilege": it can create containers and is therefore also
  root-equivalent. A read-only proxy is fine for telegraf, not for `restart`/`compose`.
- **Done when:** `id funkysloth` has no `docker`; `docker ps` as `funkysloth` fails; the MCP
  still works through the broker; `sudo -l -U funkysloth` is the expected passworded admin rule.

---

### S-03 — The Ansible vault is effectively unlocked

- **Severity:** Critical · **Status:** open
- **Evidence:** `~/.vault_pass` is `0644`, 9 bytes; `.vaults` is `0600`, 9 bytes, in the repo.
  `ansible-vault view` with either file lists `password`, `ansible_ssh_pass`,
  `influxdb_token`, `cloudflare_api_token`, `duckdns_token`, `duplicati_b2_*`,
  `email_password`, `hugging_face_token`, `prometheus_api_token`, `samba_users`, and many
  application admin passwords.
- **Why:** encryption at rest is moot when the key sits next to the ciphertext and is readable
  by the agent. The vault is the single place the admin password and the application secrets
  live.
- **Do:** rotate the vault password and every secret it protects; move the vault password to a
  hardware-backed mechanism (age/YubiKey, GPG with a hardware token, or `secret-tool` with a
  user-presence prompt). Delete the on-disk copies. Use `--vault-password-file` pointing at a
  FIFO or an agent-backed script, never a plain file in the home or repo.
- **Done when:** no vault password file is readable by the agent; `ansible-vault view` requires
  user presence; all pre-rotation secrets fail; the rotation is recorded in Appendix D.

---

### S-04 — Ansible is an arbitrary root executor for the agent

- **Severity:** High (Critical in combination with S-03) · **Status:** open
- **Evidence:** `ansible`, `ansible-playbook` and `ansible-vault` are on the agent's `PATH`;
  `hosts` sets `ansible_user: funkysloth`; `catafalco.yml` uses `become: true`; the vault
  supplies the become password and `ansible_ssh_pass`.
- **Why:** even a read-only MCP is meaningless if the agent can run an Ansible task with
  `become: true`. Note that *possession* of the credential and the *capability* to deploy are
  two different things: only the first one has to leave the sandbox. Removing both is what
  makes the sandbox unpalatable and gets it bypassed (S-17).
- **Do:** remove Ansible from the agent sandbox and keep the admin plane on a separate
  account/workstation. Replace the vault with a **deploy broker** outside the sandbox
  (Phase 1.5, S-17): the agent submits a playbook from a fixed list, an allowlisted tag set
  and a tree hash; the broker owns the vault key, the become password and the SSH key, runs
  `ansible-runner` there, and streams redacted events back. Do not give the agent `become`
  credentials, and do not let it request `-e`/`--extra-vars`, connection overrides or `--diff`.
- **Done when:** the agent cannot invoke `ansible-playbook` and holds no `ansible_ssh_pass`
  or become password; every agent-initiated deploy goes through the broker and appears in
  the append-only audit with a tree hash and a snapshot id; the agent can still complete
  deploy → observe → fix unattended through that broker.

---

### S-05 — The MCP policy is writable by the agent

- **Severity:** Critical · **Status:** open
- **Evidence:** `/home/alessio/code/server-mcp` is owned by `alessio`; `security.py` is `0644`;
  `~/.config/remote-server-mcp/config.yaml` and `.env` are owned by `alessio`;
  `~/.pi/agent/mcp.json` is `0644`; the audit log is `~/.local/state/remote-server-mcp/audit.jsonl`,
  `0600`, owned by `alessio`.
- **Why:** the policy must be immutable to the subject it constrains. Today the agent can
  change the allowlist, disable host-key verification, point `services_path` at `/`, or add
  containers, then restart/reconnect the MCP.
- **Do:** deploy the MCP from a root-owned (or dedicated-user-owned) read-only checkout, run
  it as a separate user/container, and keep its config and secrets outside the agent's
  readable paths. Use `uv run --frozen` with pinned dependencies. Move the audit log to an
  append-only remote sink. Add a startup integrity check (hash of the policy/config) and log
  it.
- **Done when:** the agent cannot write the MCP tree, config, `.env` or audit log; a startup
  hash is recorded; deleting the local audit file does not erase the remote record.

---

### S-06 — Unencrypted SSH keys and a live `ssh-agent`

- **Severity:** Critical · **Status:** open
- **Evidence:** `ssh-keygen -y -P "" -f ~/.ssh/id_ed25519_catafalco.key` and
  `~/.ssh/id_rsa_catafalco.key` both succeed → **no passphrase**. `ssh-add -l` lists multiple
  keys. `ssh -G catafalco` → `user funkysloth`, `hostname 192.168.178.3`, `port 22`.
- **Why:** the key is both a file the agent can copy and a live agent socket it can use. A
  passphrase would not help against the socket, but it would help against file exfiltration;
  neither is present.
- **Do:** generate a new keypair for the MCP only; protect it with a passphrase or a hardware
  token; put it in a separate user/service; remove the `catafalco` keys from the agent's home.
  On the host, restrict the key with `restrict,from="<laptop>",command="/usr/local/sbin/mcp-broker"`
  (and a separate SFTP key if needed). Rotate the old keys out of `authorized_keys`.
- **Done when:** the agent home contains no key that authenticates to `catafalco`; the MCP key
  is not readable by the agent; `ssh catafalco` from the agent fails; the host key is restricted
  to the broker.

---

### S-07 — `telegraf` has broad sudo and the `docker` group

- **Severity:** High · **Status:** open
- **Evidence:** `roles/telegraf/tasks/main.yml:203` adds `telegraf` to `docker`;
  `:225` writes `telegraf ALL=(root) NOPASSWD: /usr/sbin/smartctl, /usr/sbin/nvme`.
  (`:164` is the separate admin-user `systemd-journal` grant, not a telegraf grant.)
- **Why:** the `docker` group is root-equivalent; the sudoers rule allows every `nvme`
  subcommand, including `format`, `sanitize`, `admin-passthru`, `fw-download` and
  `set-feature`. A compromised telegraf can destroy disks or reach the Docker API.
- **Do:** remove `telegraf` from `docker` and point `[[inputs.docker]]` at a read-only
  socket-proxy (`CONTAINERS: 1`, `IMAGES: 1`, `POST: 0`; the existing `roles/socket_proxy`
  is already configured this way for SWAG). Scope the sudoers rule to a wrapper or to exact
  read-only subcommands; do not grant the whole `nvme` binary.
- **Done when:** `id -nG telegraf` has no `docker`; `sudo -l -U telegraf` shows only the
  wrapper/exact commands; SMART polling still succeeds; Docker metrics still arrive.

---

### S-08 — MCP redaction gaps in log search and container health

- **Severity:** Medium–High · **Status:** open (upstream `server-mcp`)
- **Evidence:** `apps/remote-server-mcp/src/remote_server_mcp/server.py`:
  `search_service_logs()` (around line 1489) returns `matches` without `redact_secrets()`;
  `_format_container_health()` (around line 921) returns raw probe output.
  `get_service_logs()` (around line 769) does apply `redact_secrets()`, so the behavior is
  inconsistent.
- **Why:** logs and health probes routinely contain tokens, DSNs and passwords. An agent can
  search for `=` or `password` and receive the raw line, bypassing the redaction applied to
  the normal log tool.
- **Do:** apply `redact_secrets()` to every matched line in `search_service_logs()` and to
  the rendered probe output in `_format_container_health()`; add regression tests with a
  `DB_PASSWORD=...` log line and a token in a health probe.
- **Done when:** both tools return `***` for the test values; the tests run in CI; the
  security model document mentions logs and health output explicitly.

---

### S-09 — `get_service_file` reads any non-sensitive file below `/srv`

- **Severity:** Medium · **Status:** open (upstream `server-mcp`)
- **Evidence:** `security.check_service_file_path()` blocks sensitive names/suffixes and
  marks `.env` for redaction, but there is no per-service allowlist. Any other regular file
  below `/srv/<service>/` is read and passed through the heuristic `redact_secrets()`.
- **Why:** backups, SQL dumps, tarballs and application configs can contain secrets in shapes
  the redactor does not recognize. The tool is useful for compose debugging, but it is a
  general file reader for `/srv`.
- **Do:** add a per-service file allowlist (compose files, known configs, logs) and deny
  archives/dumps by extension (`.sql`, `.dump`, `.tar`, `.gz`, `.zip`, `.bak`, `.old`).
  Consider a `security.file_read_allowlist` config key with a safe default. Add tests.
- **Done when:** a `.sql` or `.tar.gz` under `/srv` is refused or fully redacted; the
  allowlist is configurable and documented.

---

### S-10 — The InfluxDB token is readable and the SELECT-only check is not a token boundary

- **Severity:** High · **Status:** open
- **Evidence:** `~/.config/remote-server-mcp/.env` and `~/.config/disk-health-mcp/.env` are
  `0600`, owned by `alessio`, each containing `INFLUXDB_TOKEN`. The MCP validates SQL as
  `SELECT`-only, but the agent can read the token and use `curl` directly against
  `https://influxdb.catafal.co`.
- **Why:** authorization belongs at the database, not in the MCP's SQL parser. A token with
  write access makes the MCP's read-only validation irrelevant.
- **Do:** create a read-only token scoped to the `system-monitor` database; use separate
  tokens per MCP; rotate the current token; keep `.env` out of the agent sandbox; consider a
  local proxy that injects the token so the agent never sees it.
- **Done when:** the token cannot write or delete; it is not readable by the agent; the
  rotation is recorded; the MCP still queries.

---

### S-11 — SSH hardening is not actually applied

- **Severity:** Medium · **Status:** open
- **Evidence:** `geerlingguy.security` is in `requirements.yml` but not in `catafalco.yml`;
  no role writes `sshd_config`; `security_ssh_port: 69` is unused; `hosts_example` defaults
  to `ansible_user=root`.
- **Why:** the repository claims a hardened SSH posture that the playbook does not enforce.
  The actual policy depends on the base image. `ansible_ssh_pass` in the vault suggests
  password authentication may be in use.
- **Do:** add a real SSH hardening role (or include `geerlingguy.security`) and apply it:
  `PermitRootLogin no`, `PasswordAuthentication no`, `KbdInteractiveAuthentication no`,
  `AllowUsers funkysloth`, `AllowAgentForwarding no`, `X11Forwarding no`, sensible
  `MaxAuthTries`/`ClientAlive*`. Test in a second session before closing the first.
- **Done when:** `sshd -T` shows the expected values; password login fails; root login fails;
  key-based login works; `hosts_example` no longer suggests root.

---

### S-12 — `confirm=true` is not human approval

- **Severity:** Medium · **Status:** open
- **Evidence:** `restart_service`, `stop_service`, `compose_down`, `compose_up` and
  `compose_pull` require `confirm=true`, but the model supplies the argument. The MCP is
  exposed with `"exposure": "direct"` in `~/.pi/agent/mcp.json`; no `tool_call` permission
  extension is installed.
- **Why:** `confirm` prevents accidental calls, not a prompt-injected model. A malicious log
  line or repo file can instruct the model to pass `confirm=true`.
- **Do:** add a `pi` permission-gate extension for `destructiveHint`/non-`readOnlyHint` tools
  (the pi docs ship `examples/extensions/permission-gate.ts`). Split the MCP into a read-only
  server (auto-approved) and an admin server (human approval or a separate short-lived token).
- **Done when:** destructive MCP calls require an interactive confirmation or are blocked in
  non-interactive runs; read-only calls remain frictionless.

---

### S-13 — The audit log is local and agent-writable

- **Severity:** Medium · **Status:** open
- **Evidence:** `~/.local/state/remote-server-mcp/audit.jsonl` is `0600`, owned by `alessio`;
  `~/.config/remote-server-mcp/config.yaml` sets `audit.path` there.
- **Why:** the subject of the audit can delete or rewrite it. It is useful for debugging, not
  for accountability.
- **Do:** ship audit records to a remote append-only sink (rsyslog/journald forward, a
  write-only HTTP endpoint, or a syslog server). Add a hash chain or periodic signed digest.
  Alert on gaps or a restart that resets the file.
- **Done when:** deleting the local file does not erase the remote record; a verifier detects
  tampering; the sink is documented.

---

### S-14 — `ls`/`test` path checks are lexical and can follow symlinks

- **Severity:** Low · **Status:** open (upstream `server-mcp`)
- **Evidence:** `SecurityValidator._path_below_services()` is lexical; the `ls -1` and
  `test -d` shapes use it. `ls` follows a command-line symlink to a directory, and `test -d`
  follows symlinks. Content reads use SFTP `realpath`, so this is a listing leak, not a file
  read.
- **Why:** an agent can learn the names of directories outside `/srv` through a symlink placed
  below `/srv` (or an existing one).
- **Do:** use SFTP `readdir`/`stat` with a `realpath` check instead of `ls`/`test`, or remove
  those two operations from the catalog. `check_service_exists()` can use SFTP `stat`.
- **Done when:** a symlink under `/srv` pointing at `/etc` is refused by `ls`/`test`; the
  directory listing tools use the same realpath confinement as file reads.

---

### S-15 — `echo` is unnecessary in the command allowlist

- **Severity:** Low · **Status:** open (upstream `server-mcp`)
- **Evidence:** `ALLOWED_ARGV_PREFIXES` includes `("echo",)`; `ECHO_CONNECTION` renders
  `echo "Connection successful"`.
- **Why:** every allowed executable is surface area. `echo` is not needed for a connectivity
  check; a direct tool response is enough.
- **Do:** remove `("echo",)` and `ECHO_CONNECTION`; return a normal `ToolResponse` for the
  connection check.
- **Done when:** no catalog operation renders `echo`; the command-policy tests are updated.

---

### S-16 — The security documentation describes a different deployment

- **Severity:** Low (but it creates false confidence) · **Status:** open
- **Evidence:** `server-mcp/docs/security-model.md` says the catafalco deployment uses a
  blanket `security_sudoers_passwordless` and the `geerlingguy.security` role, and recommends
  running the MCP as a dedicated unprivileged user. The catafalco repo does none of those: it
  removes blanket NOPASSWD, does not run `geerlingguy.security`, and the MCP runs as
  `alessio` with `funkysloth` in `docker`.
- **Why:** a threat model that does not match the deployment hides exactly the gaps this
  track is about.
- **Do:** update `server-mcp/docs/security-model.md` to state the actual catafalco model:
  the MCP user is root-equivalent through `docker`, the host is not SSH-hardened by this
  playbook, and the MCP is not a boundary when the caller shares the credentials. Link this
  track from `AGENTS.md`.
- **Done when:** the document matches the repo and the host; the link is in `AGENTS.md`.

---

### S-17 — No deploy path exists for a sandboxed agent

- **Severity:** High · **Status:** open
- **Evidence:** S-04 removes `ansible-playbook` from the agent and, as originally written,
  replaced it with “the human runs it”. Phases 0–3 contain no replacement, so a sandboxed
  agent can propose a change but cannot apply it or read the result. The primary task class
  on this repository is “server X is not working → fix it”, which is by definition
  `deploy → collect per-task stdout/stderr → fix → redeploy`. The MCP closes that loop for
  container-level faults (`compose_up`, `restart_service`, `get_service_logs`,
  `get_container_health`) but not for host-level config (systemd units, `/etc`, sudoers,
  mounts, cron).
- **Why:** withdrawing *possession* of the vault and withdrawing the *capability* to deploy
  are different changes, and only the first one is required by the invariant. Trading a
  credential risk for a diff-and-wait workflow loses the reason to run the agent at all, and
  the predictable response is to re-attach the vault to the sandbox — reopening S-01/S-03/S-04.
- **Do:** run deploys in a **deploy plane** outside the sandbox that owns the credential
  (Phase 1.5). The agent sends a *request*, never a secret:

  | Operation | Input | Output |
  |---|---|---|
  | `deploy` | playbook from a fixed list, allowlisted `tags`, `limit`, `tree_hash`, `check`, `diff=false` | `run_id` |
  | `deploy_logs` | `run_id`, `offset` | redacted per-task events (S-18) |
  | `deploy_status` | `run_id` | `rc`, failed tasks, recap, snapshot id, rollback state |
  | `deploy_cancel` | `run_id` | cancellation result |
  | `deploy_list` | — | recent runs with tree hash, tags, `rc` |

  Implement it on `ansible-runner` (structured job events, one private data dir and artifact
  set per run), not on a shell-out to `ansible-playbook`. Refuse `-e`/`--extra-vars`,
  `-c`/connection overrides, inventory overrides, `--ask-pass`, `--vault-password-file` and
  any path-valued playbook argument: tags plus a tree hash are the whole input surface.
- **Done when:** from inside the sandbox, `ansible-playbook` and `ansible-vault` are absent and
  the vault is unreadable, yet a full `deploy → deploy_logs → fix → deploy` cycle completes
  unattended; each run appears in the append-only audit with its tree hash, tag set, `rc` and
  snapshot id; a deliberate failure triggers the health gate and an automatic rollback.

---

### S-18 — Ansible output is an unredacted secret channel

- **Severity:** Medium–High · **Status:** open
- **Evidence:** a deploy that streams its output to the agent streams everything an Ansible
  run prints: `debug` tasks rendering a vaulted variable, `--diff` printing whole templated
  files, connection failures echoing `ansible_ssh_pass`/become variables, and any task whose
  `no_log` is missing. Most of the ~64 roles here render `.env` files, configs and compose
  manifests through `template`/`copy`, and `no_log` is opt-in and rarely present. This is the
  same class as S-08, but the deploy plane is a much wider channel than MCP log search.
- **Why:** the agent only needs the *outcome* of a deploy (which task failed, what it
  reported), not the rendered secret material. Unredacted event streaming re-exposes exactly
  what the vault hygiene work in S-03 is meant to contain.
- **Do:** default `diff` off and refuse it from the sandbox; use a structured stdout callback
  instead of the default human callback; run every event line through `redact_secrets()`
  before it leaves the broker; audit the roles for missing `no_log` on tasks that reference
  `*_password`, `*_token`, `*_key`; add a regression task that deliberately prints a vaulted
  variable.
- **Done when:** a leaking test task returns `***` through `deploy_logs`; `diff=true` is
  refused from the sandbox; the callback and redaction are covered by tests; the deploy log
  format is documented in the deploy plane section.

---

## Target architecture

### The invariant

> The process that holds the credentials must not be the process that runs model-generated
> code. The agent can only call the MCP and the deploy plane; it cannot read their keys,
> edit their policy, or reach the host by another route.

### Shape

```
┌──────────────────────────────────────────────────────────────┐
│ Agent plane (untrusted)                                      │
│  pi in a container/VM, workspace only, tmpfs home            │
│  no ~/.ssh, no ~/.config, no vault, no ansible, no agent     │
│  egress: model API + MCP endpoint only                       │
└───────────────────────────┬──────────────────────────────────┘
                            │ MCP + deploy plane (HTTP + token)
┌───────────────────────────▼──────────────────────────────────┐
│ MCP plane (trusted, minimal)                                 │
│  separate user/container; owns the SSH key or local Docker   │
│  root-owned read-only code; read-only Influx token           │
│  audit → remote append-only sink                             │
│  read-only tools auto-approved; admin tools human-gated      │
└───────────────────────────┬──────────────────────────────────┘
                            │ forced command / broker / proxy
┌───────────────────────────▼──────────────────────────────────┐
│ catafalco (least privilege)                                  │
│  dedicated `mcp` user: no docker, no sudo                    │
│  root-owned broker: exact argv allowlist, realpath checks    │
│  telegraf: read-only socket-proxy, scoped sudoers            │
│  sshd: no password auth, no root login, no agent forwarding  │
└──────────────────────────────────────────────────────────────┘

Admin plane (human only): manual Ansible + vault from a separate account
for the human-gated tags, hardware-backed vault password, no access from
the agent sandbox. The deploy plane holds the same credentials for the
allowlisted tags.
```

### Deploy plane (Phase 1.5)

```
sandbox (untrusted)            deploy plane (trusted, outside sandbox)         catafalco

deploy(tags, tree_hash, ─────► owns vault key, become password, SSH key
       check, diff=false)      fixed playbook list, tag allowlist
                               ansible-runner → per-run data dir + artifacts
◄── events, redacted ────────  records tree hash, snapshot id, rc
◄── deploy_status(run_id) ───  health gate → auto-rollback on failure
```

The agent never holds the vault, the become password or the SSH key. It holds a *request*:
a playbook from a fixed list, an allowlisted tag set, and the tree hash it believes it is
deploying. The broker answers with redacted events and an exit code — the whole loop the
agent needs, minus the credential.

First step: the broker runs on the laptop as its own user/service, reachable over HTTP from
the sandbox (same shape as the MCP in Option A). End state: it moves to `catafalco` next to
the MCP in Phase 2, so no laptop process owns a server credential at all.

### Two ways to build the MCP plane

**Option A — keep the MCP on the laptop, separate it (easier, first step).**
Run the MCP as a dedicated `mcp` OS user or a container. It owns its own SSH key and `.env`;
the agent only gets a socket or an HTTP endpoint. The agent cannot read the MCP's key or edit
its code. The host key is `restrict,command="/usr/local/sbin/mcp-broker"`, so a stolen MCP key
only allows the catalog.

**Option B — move the MCP onto `catafalco` (end state, strongest).**
Run the MCP as a systemd service with root-owned, read-only code. It talks to Docker locally
through a narrow broker/proxy; there is no SSH key on the laptop at all. The agent connects
through an authenticated endpoint (loopback tunnel or HTTPS with a token). The agent can only
call the MCP; it has no route to SSH or the Docker socket. This removes the laptop-to-server
credential entirely.

**Docker is special.** Any write access to the Docker API is root-equivalent: `POST
/containers/create` with a host mount is enough. A "limited" write proxy is therefore not a
least-privilege control. Use a root-owned broker that validates the exact argv, or accept that
the MCP service is root-equivalent and protect its code/key at the OS level.

**The model API is an exfiltration channel.** Even a perfect sandbox can send anything it
reads to the provider. The only real mitigation is to keep secrets out of the sandbox and to
use a zero-retention provider or a local model for sensitive sessions. Do not rely on MCP
redaction alone.

---

## Rollout plan

### Phase 0 — stop the bleeding (today)

Order matters: rotate first (it depends on nothing and is irreversible to postpone); sandbox
`pi` **and** move the MCP out of it together (either alone leaves a broken or unprotected
setup); move the vault key last (S-03 is moot until S-01/S-04 are in place).

- [ ] Rotate every secret in `host_vars/*/secret.yml`, `group_vars/*/secret.yml` and the two
      MCP `.env` files. Use Appendix D as the checklist. Assume all values are exposed.
- [ ] Move the vault password off disk; delete `~/.vault_pass` and `.vaults`; switch to a
      hardware-backed mechanism with user presence.
- [ ] Run `pi` in a container/VM with only the workspace; no host home, no `~/.ssh`, no
      `~/.config`, no vault, no `ansible`, no `ssh-agent`.
- [ ] Remove `funkysloth` from `docker` (after the MCP has a broker or a dedicated user), and
      keep the admin `sudo` password out of the agent's reach.
- [ ] Add the `pi` permission gate for destructive MCP tools.
- [ ] Fix the two redaction gaps in `server-mcp` (S-08) and ship the tests.

### Phase 1 — make the MCP a boundary (this week)

- [ ] Create a dedicated `mcp` user on `catafalco`; no `docker`, no `sudo`.
- [ ] Install a root-owned `mcp-broker`; SSH key restricted with
      `restrict,from="<laptop>",command="/usr/local/sbin/mcp-broker"`.
- [ ] Add a second restricted SFTP key (or broker-served file reads) with `realpath`
      confinement below `/srv`.
- [ ] Point `telegraf` at a read-only socket-proxy; remove it from `docker`; scope its
      sudoers rule.
- [ ] Create a read-only InfluxDB token scoped to `system-monitor`; separate tokens per MCP.
- [ ] Apply SSH hardening; verify from a second session before closing the first.
- [ ] Move the MCP audit log to a remote append-only sink.
- [ ] Deploy the MCP from a root-owned read-only checkout with `uv run --frozen`.

### Phase 1.5 — give the agent a deploy plane (this week, with Phase 1)

Without this phase the sandboxed agent can propose but not apply, and the loop that justifies
running it is lost (S-17, Path I). It is listed separately because it is the one deliverable
the original plan was missing, not because it is optional.

- [ ] Create a `deploy` service account (laptop first, `catafalco` in Phase 2) that owns the
      vault key, the become password and the `catafalco` SSH key; its home is not readable by
      the agent user.
- [ ] Run `ansible-runner` as a systemd service; one private data dir and artifact set per
      run, written under the service account, with `uv run --frozen`-style pinned deps.
- [ ] Expose only `deploy`, `deploy_logs`, `deploy_status`, `deploy_cancel`, `deploy_list`
      (shape in S-17). No shell, no argv passthrough, no playbook path from the caller.
- [ ] Validate `tags` and `limit` against an allowlist; refuse `-e`/`--extra-vars`,
      `-c`/connection overrides, inventory overrides, `--ask-pass`, `--vault-password-file`,
      and `diff=true`.
- [ ] Tag allowlist: per-service roles (`jellyfin`, `grafana`, `swarm`, …) and `containers`.
      Human-gated (refused from the sandbox): `bootstrap`, `system`, `security`, `sshd`,
      `mounts`, `mergerfs`, `snapraid`, `hd_idle`, and anything writing `/etc/sudoers.d`.
- [ ] Copy the workspace tree into a read-only per-run directory, record its hash, and run
      Ansible from that copy so post-hoc edits cannot re-explain a run.
- [ ] Take a pre-deploy snapshot of `/srv` (restic run or btrfs/LVM snapshot) and record the
      snapshot id in the audit record.
- [ ] Add a post-deploy health gate for the affected services (`compose ps`, container health,
      an HTTP probe) and auto-rollback to the previous tree hash + snapshot on failure.
- [ ] Run with `serial: 1` and `any_errors_fatal: true`; one tag per run by default.
- [ ] Add a deploy budget: N runs/hour, stop after M consecutive failures, refuse while a run
      is active.
- [ ] Write one append-only audit record per run to the remote sink (S-13): requester, tree
      hash, tags, limit, `check`/`diff`, `rc`, task counts, snapshot id, rollback outcome.
- [ ] Notify the human on every non-`check` deploy — after-the-fact review replaces the
      blocking approval prompt (D6).
- [ ] Redact every event line before it leaves the broker (S-18); default the structured
      stdout callback and keep `diff` off.
- [ ] Verify the loop from inside the sandbox: break a service, `deploy(tags=[…])`, read
      `deploy_logs`, fix, redeploy — unattended, with no vault and no SSH key present.

### Phase 2 — remove the laptop credential (end state)

- [ ] Move the MCP onto `catafalco` as a systemd service; delete the laptop's SSH key for
      `catafalco`.
- [ ] Move the deploy plane onto `catafalco` next to the MCP (same endpoint, same token);
      delete the laptop's deploy key and its vault access.
- [ ] Expose the MCP over an authenticated endpoint (loopback tunnel or HTTPS + token).
- [ ] Add an egress allowlist to the agent sandbox (model API + MCP only).
- [ ] Use a provider proxy with a placeholder credential, or a local model, so the real model
      key is not inside the sandbox.
- [ ] Add monitoring/alerting: `docker run`/`exec`, new privileged containers, new
      `authorized_keys`, `sudoers.d` changes, unusual SSH logins, audit-log gaps.

### Phase 3 — keep it true

- [ ] Rotate the MCP key and tokens on a schedule; rotate after any agent session that had
      broader access.
- [ ] Re-run the verification checklist in Appendix A after every change to the MCP or host.
- [ ] Review the MCP tool catalog and the `allowed_containers`/`host_units` lists quarterly.
- [ ] Update this document rather than opening a second security track.

---

## Decision log

| ID | Decision | Recommendation |
|---|---|---|
| D1 | Which MCP plane? | **Option B** (MCP on `catafalco`) as the end state; **Option A** (separate user on the laptop) as the first step if Phase 2 is too large right now. |
| D2 | Keep `funkysloth` in `docker` for convenience? | **No.** Use a dedicated `mcp` user + broker. If you keep it, treat the MCP key as a root credential and protect it accordingly. |
| D3 | Keep `get_service_file` broad? | **No.** Add a per-service allowlist and deny archives/dumps. |
| D4 | Use a local model for sensitive sessions? | **Yes, if feasible.** Otherwise use a zero-retention provider and keep secrets out of the sandbox. |
| D5 | Is `confirm=true` enough for destructive tools? | **No.** Add a human approval gate or a separate admin token. |
| D6 | Where does agent autonomy end? | **Tag allowlist + rollback envelope, not per-call approval.** The agent deploys an allowlisted tag unattended; the controls are the pre-deploy snapshot, the health gate, auto-rollback, the deploy budget and the append-only audit. Destructive tags (disks, mounts, sshd, auth, `snapraid`) stay human-gated (S-17, Path I). |
| D7 | Who applies an agent change? | **A deploy plane outside the sandbox** that owns the vault/SSH key and streams redacted events (S-17). Laptop-side broker with the MCP in Phase 1.5; host-side in Phase 2. Never: the agent holding the vault, and never “the human re-runs it by hand” as the only path. |
| D8 | How is the vault password unlocked? | **No on-disk key.** An executable `--vault-password-file` that unwraps a GPG secret through `pinentry` with user/hardware presence, kept at a root-owned path outside the home; delete `~/.vault_pass` and `.vaults`. This is only meaningful once Ansible is off the agent plane (S-01/S-04) — a warm `gpg-agent` cache, a writable `gpg-agent.conf` and a fuzzel prompt the requester controls are all bypasses while `pi` runs as `alessio`. |
| D9 | Does the MCP have to live on `catafalco`? | **No — Option A is an acceptable end state.** Keeping the MCP local is fine provided it runs as its own user/service reached over streamable HTTP, from a path the agent cannot write, and the sandbox mounts none of the host home or runtime sockets. Option B is still preferred because it deletes the laptop→server credential. |

---

## Appendix A — Verification commands

Run these **outside the agent sandbox** (as the human admin), and record the output in
Appendix B.

### Laptop

```bash
# Vault password exposure
stat -c '%a %U %n' ~/.vault_pass .vaults
ansible-vault view --vault-password-file .vaults host_vars/catafalco/secret.yml \
  | grep -oE '^[A-Za-z_][A-Za-z0-9_]*:' | sort

# SSH key exposure
for k in ~/.ssh/id_ed25519_catafalco.key ~/.ssh/id_rsa_catafalco.key; do
  printf '%s: ' "$(basename "$k")"
  ssh-keygen -y -P "" -f "$k" >/dev/null 2>&1 && echo "NO PASSPHRASE" || echo "protected"
done
ssh -G catafalco | grep -E '^(user|hostname|port) '

# MCP ownership
stat -c '%U %a %n' ~/code/server-mcp/packages/server-management-lib/src/server_management_lib/security.py \
  ~/.config/remote-server-mcp/config.yaml ~/.config/remote-server-mcp/.env \
  ~/.local/state/remote-server-mcp/audit.jsonl
```

### `catafalco` (admin shell, not the agent)

```bash
id funkysloth
getent group docker
sudo -l -U funkysloth
id -nG telegraf
sudo -l -U telegraf
sshd -T | grep -E 'permitrootlogin|passwordauthentication|kbdinteractiveauthentication|allowagentforwarding|x11forwarding'
```

### Agent sandbox (expected to fail after Phase 0, except the deploy loop)

```bash
ls ~/.ssh
ssh -o BatchMode=yes catafalco id
command -v ansible-playbook
command -v ansible-vault
ansible-vault view host_vars/catafalco/secret.yml          # must fail
ssh -G catafalco >/dev/null 2>&1                          # no route if egress is cut
echo "${SSH_AUTH_SOCK:-unset}"                            # must be unset

# The loop must still work (Phase 1.5): check + deploy + logs, unattended
deploy(check=true, tags=["grafana"])                       # rc 0, reports changes
deploy(tags=["grafana"])                                  # run_id
deploy_status(run_id)                                     # rc, tree hash, snapshot id
deploy_logs(run_id)                                       # redacted events
```

### Deploy plane (admin shell)

```bash
# Policy inputs cannot carry a secret or an override
curl -s --unix-socket /run/deploy.sock -X POST /deploy \
  -d '{"tags":["grafana"],"extra_vars":{"ansible_become_pass":"x"}}'   # refused
curl -s --unix-socket /run/deploy.sock -X POST /deploy \
  -d '{"tags":["bootstrap"]}'                                         # refused (not allowlisted)

# Every run is anchored and recorded
jq -r '[.time,.tree_hash,(.tags|join(",")),.rc,.snapshot_id]|@tsv' /var/log/deploy/audit.jsonl | tail
# The snapshot the broker took before writing still exists
restic -r <repo> snapshots --tag pre-deploy | tail -3
# Redaction on the event stream
deploy(tags=["grafana"], diff=true)                       # refused from the sandbox
```

---

## Appendix B — Evidence log

| Time | Observation | Source |
|---|---|---|
| 2026-10-23 01:0x | `~/.vault_pass` is `0644`, 9 bytes; `.vaults` is `0600`, 9 bytes | `stat`, `wc -c` |
| 2026-10-23 01:0x | Vault contains `password`, `ansible_ssh_pass`, `influxdb_token`, `cloudflare_api_token`, `duckdns_token`, `duplicati_b2_*`, `email_password`, `hugging_face_token`, `prometheus_api_token`, `samba_users`, … | `ansible-vault view` key listing |
| 2026-10-23 01:0x | `id_ed25519_catafalco.key` and `id_rsa_catafalco.key` have no passphrase | `ssh-keygen -y -P ""` |
| 2026-10-23 01:0x | `ssh-add -l` lists multiple keys; `ssh -G catafalco` → `user funkysloth`, `192.168.178.3:22` | `ssh-add`, `ssh -G` |
| 2026-10-23 01:0x | `ansible`, `ansible-playbook`, `ansible-vault` are on `PATH`; `ssh` is available | `command -v` |
| 2026-10-23 01:0x | `~/code/server-mcp`, `security.py`, MCP config, `.env` and audit log are owned by `alessio` | `ls -l`, `stat` |
| 2026-10-23 01:0x | `roles/docker/tasks/main.yml:39` adds `ansible_user` to `docker`; `roles/system/tasks/user.yml` adds the user to `sudo`; `hosts:6` uses `funkysloth` | repository |
| 2026-10-23 01:0x | `roles/telegraf/tasks/main.yml:203` adds `telegraf` to `docker`; `:225` grants `NOPASSWD: /usr/sbin/smartctl, /usr/sbin/nvme` | repository |
| 2026-10-23 01:0x | `search_service_logs()` and `_format_container_health()` do not call `redact_secrets()`; `get_service_logs()` does | `server.py` |
| 2026-10-23 01:0x | `geerlingguy.security` is in `requirements.yml` but not in `catafalco.yml`; no `sshd_config` role | repository |
| 2026-10-23 01:0x | `snapraid-status` sudoers is exact (`snapraid status`), which is the correct pattern | `roles/snapraid/tasks/configure_snapraid.yml` |

The `docker`/`sudo` membership is the configured state in the repo and the MCP uses the same
user; confirm it on the host with `id funkysloth` before treating S-02 as closed.

---

## Appendix C — What the MCP already gets right

This track is not a rewrite request. The core design is sound and should be preserved:

- **Fixed tool catalog.** No `exec`, no `run_shell`, no generic command path.
- **Typed argv construction.** `shlex.join` round-trip; shell chaining, redirection and
  substitution are rejected.
- **No `docker run`/`exec`/`build`.** Container operations are list/inspect/logs/stats/port
  plus start/stop/restart and a bounded compose surface.
- **Fixed `docker inspect` format.** `.Config`, `.Args`, `.Mounts`, `.HostConfig` and
  `.NetworkSettings` are not exposed.
- **SFTP `realpath` confinement.** The requested path and the base are resolved on the target;
  the file must be a regular file.
- **Host-key verification.** A missing `known_hosts` is an error, not a silent fallback.
- **Read-only data access.** Single `SELECT`, write keywords and comments rejected, `LIMIT`
  enforced; PromQL goes to the read-only endpoint.
- **Redaction.** `.env` and config files are masked by key name; `get_service_logs()` and the
  host-service tools apply `redact_secrets()`.
- **Audit, rate limit and output caps.** JSONL records, a sliding window for state-changing
  calls, and a 64 KiB cap.
- **`security.allow_generic_commands` is a no-op.** There is no hidden escape hatch.

The gaps are deployment (S-01–S-07, S-10–S-13, S-17, S-18) and a small set of MCP defects
(S-08, S-09, S-14, S-15). Fix the deployment first; the MCP defects are then worth fixing
upstream.

The deploy plane (S-17) should follow the same shape: a fixed operation catalog, typed
inputs, an allowlist the caller cannot read or edit, and an append-only record — the MCP's
design is the right template for it.

---

## Appendix D — Secret rotation checklist

Treat every key in `secret.yml` as exposed. Rotate by family; do not re-use the old value
anywhere.

| Family | Representative keys | Where to rotate |
|---|---|---|
| OS / Ansible | `password`, `ansible_ssh_pass` | `passwd` / `chpasswd` on `catafalco`; update the vault |
| SSH | `id_ed25519_catafalco`, `id_rsa_catafalco`, `authorized_keys` | New keypair; replace the host entry; remove the old key |
| DNS / tunnel | `cloudflare_api_token`, `cloudflare_tunnel_password`, `duckdns_token` | Cloudflare / DuckDNS dashboards |
| Backups | `duplicati_b2_applicationkey`, `duplicati_b2_keyid`, `duplicati_settings_encryption_key` | Backblaze / Duplicati |
| Mail | `email_password` | Mail provider; update `msmtp` |
| Monitoring | `influxdb_token`, `prometheus_api_token`, `healthchecks_api_key`, `uptime_kuma_key` | InfluxDB / Prometheus / Healthchecks / Uptime Kuma |
| Apps | `authelia_password`, `nextcloud_password`, `vaultwarden_admin_token`, `seafile_*`, `invidious_*`, `cypht_*`, `dawarich_*` | Each application's admin UI |
| AI | `hugging_face_token` | Hugging Face |
| Samba | `samba_users` | `smbpasswd` on the host |
| MCP | `INFLUXDB_TOKEN` in both `.env` files | InfluxDB; issue read-only tokens |

Record the rotation date and the verification command in Appendix B. If a secret cannot be
rotated, document the compensating control and the expiry date.

---

## Appendix E — Out of scope / accepted risks

- A compromised `catafalco` host or Docker daemon: if the host is root, the MCP cannot save it.
- A malicious container image or a compromised upstream dependency: pin images and review
  updates; the MCP's `compose pull` is a supply-chain action.
- Prompt injection from logs/files: mitigated by redaction and output caps, not eliminated.
  The real control is limiting what the agent can read.
- Model-provider data handling: the API is an exfiltration channel by design. Use a
  zero-retention provider or a local model for sensitive sessions.
- Physical access to the laptop or the server.
- The agent's own provider credentials: if the real model key is inside the sandbox, it can be
  exfiltrated. Use a provider proxy or a local model.
- **Unsupervised deploys are root by proxy.** The deploy broker holds the vault and runs
  Ansible as root on `catafalco`; a prompt-injected model with deploy access can imprint
  damage between a deploy and its rollback. Compensating controls are the tag allowlist, the
  pre-deploy snapshot, the health gate, auto-rollback, the deploy budget and the append-only
  audit — not approval (S-17, Path I, D6). Tags that cannot be rolled back (disk layout,
  `snapraid`, `sshd`/auth) stay human-gated.
- **The deploy log stream is a secret channel.** Redaction (S-18) reduces it; it does not
  eliminate it. A missed `no_log` on a role that templates a `.env` file is a secret read
  until the role is fixed.
- **The agent's workspace is writable, and it is the deploy input.** The broker deploys code
  the model wrote. The tree-hash anchor and the audit record give forensics, not prevention.

---

## Related documents

- `AGENTS.md` — deployment invariants and the standing rule for disk identity (T-09/T-10).
- `server-mcp/docs/security-model.md` — the MCP's own model; needs the S-16 correction.
- `server-mcp/SECURITY.md` — reporting scope and safe defaults.
- Retired `docs/disk-and-mcp-assessment.md` — T-01 … T-21, in git history (`8f348cf`).
