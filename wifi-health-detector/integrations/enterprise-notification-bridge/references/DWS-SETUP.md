# DWS Conditional Setup and Live-Test Runbook

Use this reference only when DingTalk delivery cannot use a host-native
capability and the configured Provider is `dws-cli` (or `auto` has resolved to
that fallback). DWS is not a dependency of Wi-Fi detection, Feishu, WeCom, or a
native DingTalk Provider.

## Provider decision

1. Start with `provider=auto` and pass the host capability bundle when the Agent
   supplies one. Codex, Claude Code, WorkBuddy, OpenClaw, and company-specific
   Agents use the same semantic capability contract.
2. If native DingTalk is declared, use it and do not discover or install DWS.
3. If native is unavailable, inspect DWS. Version 1.0.63 or newer must pass
   either the JSON version response or DWS's complete official text version
   banner (`dws version v<SemVer> (<commit>, <UTC build time>)`), followed by
   the per-leaf JSON-format help gates (`auth status`, `auth login`,
   `profile list`). Arbitrary text containing a version number is not accepted.
4. Missing or outdated DWS returns `dependency_install_required` or
   `dws_upgrade_required`. This is a proposal, not approval.

## Fast install for ordinary users in mainland China

The bridge never downloads the DWS binary itself. It downloads only the small
official installer script, and that upstream script then fetches the DWS release
binary (about 17.6 MB tar.gz / 47 MB installed on macOS).

Why a plain `curl … | sh` from GitHub hangs for an ordinary user without an
agent proxy/VPN:

- The release binary is served from the GitHub release-assets CDN. On a normal
  mainland network that endpoint frequently fails with `SSL connection timeout`,
  a 0-byte body, or HTTP 502.
- The upstream installer's auto-probe only checks the lightweight
  `…/releases/latest` HTML redirect (observed reachable, HTTP 302 in ~0.6 s).
  Because that probe succeeds while the asset CDN is unreachable, the installer
  wrongly concludes GitHub is usable, stays on GitHub to pull the binary, and
  never falls back. This is a probe blind spot, not a Gitee outage.

The fix is to force the official Gitee mirror, which hosts the identical release
assets and checksums. Measured on this machine on a normal network: the full
17,627,332-byte macOS archive downloads from Gitee in ~8.5 s (~2.0 MB/s,
HTTP 200); GitHub asset CDN returned `curl: (28) SSL connection timeout` with
0 bytes. Full Gitee install (download + SHA-256 verify + extract) takes ~18 s.

Two supported ways to use it:

```text
# Preferred: through the detector bridge. The first install candidate is the
# official Gitee mirror and exports DWS_GITEE_REPO, so the upstream script pulls
# both the version list and the binary from Gitee; --china-mirror pins Gitee only.
./run.sh setup --platform dingtalk --provider dws-cli --china-mirror --install-dws --yes

# Remote / headless / SSH host (no local browser for the OAuth loopback):
./run.sh setup --platform dingtalk --provider dws-cli --china-mirror --install-dws --device-login --yes
```

Or the upstream installer directly (the bridge-independent equivalent). The
`DWS_GITEE_REPO` variable is what makes the script resolve both tags and asset
URLs through Gitee. Download the script to a file and inspect/run it rather
than piping a network stream straight into a shell:

```sh
tmp=$(mktemp -d) && \
curl -fsSL -o "$tmp/install.sh" \
  https://gitee.com/dingtalk-real-ai/dingtalk-workspace-cli/raw/main/scripts/install.sh && \
DWS_GITEE_REPO=DingTalk-Real-AI/dingtalk-workspace-cli DWS_NO_SKILLS=1 \
  sh "$tmp/install.sh"
```

After the binary is ready, setup proceeds to authorization. On a desktop it
opens the DingTalk QR/OAuth page in a browser; on a headless host it otherwise
blocks on `Waiting for authorization...` until the process timeout, which the
bridge reports as `unavailable / dws_command_failed`. Use `--device-login` there.
A successful Gitee install followed by an un-scanned login in a headless shell is
therefore an authorization pause, not a download failure — confirm with
`dws --version` (expect `v1.0.63` or newer).

## Approved installation

Review the returned action with the user, including platform, minimum version,
source, and whether the China mirror was requested. Then run the matching setup
command with `--yes` (the legacy `--install-dws` gate is still accepted):

```text
# macOS or Linux — default order is official Gitee first, then GitHub fallback
./run.sh setup --platform dingtalk --provider dws-cli --install-dws --yes

# macOS or Linux — pin the official Gitee China mirror only (recommended in CN)
./run.sh setup --platform dingtalk --provider dws-cli --china-mirror --install-dws --yes

# Windows PowerShell launcher
./run.ps1 setup --platform dingtalk --provider dws-cli --china-mirror --install-dws --yes

# Windows batch launcher
run.bat setup --platform dingtalk --provider dws-cli --china-mirror --install-dws --yes
```

The installer accepts only official DingTalk installer scripts fetched over
HTTPS from the official Gitee mirror first and the official GitHub source as
fallback. No commit or installer-script digest is pinned: the newest stable
release is resolved dynamically, and the upstream installer verifies every
release binary against the checksum published in that same release. (`--china-mirror`
restricts execution to Gitee only.) The version floor is resolved live from the
Gitee/GitHub release APIs with a time-based cache; if both APIs are unreachable
it falls back to the constant `TRUSTED_VERSION_FLOOR = 1.0.63`.

Installation uses a private 0700 temporary directory, a 20-second download
timeout for the small script, a 2 MiB script limit, a 180-second process
timeout, `shell=False`, and an explicit OS/proxy environment allowlist (agent
tokens are never passed through). `DWS_NO_SKILLS=1` limits the official
installer to the CLI; it does not add unrelated agent skills. The upstream
installer verifies the CLI release archive against its published checksum
before use. The installer still has the user's filesystem permissions: approval
is required, and the environment allowlist is not a sandbox. Temporary material
is removed on success and failure; the installed CLI is discovered and verified
again before use.

## Authorization, organization, and recipients

After DWS verification, setup checks authorization. A DingTalk login window,
device code, or QR scan is requested only on first use or when saved
authorization has expired. A currently authorized user must not be prompted on
every report.

Use `--device-login` (or MCP `deviceLogin: true`) to select the documented
`dws auth login --device` flow for remote/headless environments. The flag is
forwarded only when DWS login is required; it does not trigger a new login when
the current Profile is already authorized. Native setup is considered available
only when the host declares `auth_status`, `login`, and `list_profiles`; partial
or send-only native capability falls back to DWS under `provider=auto`.

Organization binding uses only Profiles returned by the Provider. A stable
Profile has the shape `corpId:userId`. If exactly one Profile is returned, it
may be persisted. If several are returned, stop and have the user select the
exact Profile; never choose the current/default organization or construct an
identifier.

Fixed recipients are configured after Profile binding and may be decided later:

```text
./run.sh recipients --platform dingtalk --profile corpId:userId --recipient <exact-configured-selector>
```

An empty recipient list means no send on the configured-channel (MCP/continuation)
path; never infer `self`, the current user, or a similarly named person there.
The detector's unattended `deliver --auto` path is separate: it resolves the
recipient from `--notify-to`, then the `ENTERPRISE_NOTIFICATION_RECIPIENT`
variable, falling back to the fixed default 杨华, and sends on first authorized
run without an extra confirmation step.

## Independent upgrade and uninstall

The Bridge reports `dws_upgrade_required` when the discovered version is below
1.0.63. Repeat the approved setup flow (prefer `--china-mirror` in mainland
China) to upgrade from an official source, or follow the official DWS upgrade
procedure outside the detector. To uninstall,
use the official DWS uninstall procedure for the installed platform, then switch
the channel to a native Provider or disable it. These lifecycle operations do
not remove or modify `wifi-health-detector`.

## Gated real-environment test

The automated suite uses fakes and does not download DWS, open DingTalk, query
an organization, or send a message. A real preflight requires explicit approval
for each external side effect.

1. With approval to inspect an existing installation, run `dws --version` and
   require 1.0.63 or newer.
2. With approval to inspect account state, run the documented JSON capability
   gates and then `dws auth status --format json`.
3. Only if authorization is absent or expired, ask approval to open the DingTalk
   login/QR flow. Do not reset valid credentials.
4. With approval to query organization state, run `dws profile list --format
   json`. Stop if multiple Profiles exist until the user selects one.
5. Configure an exact fixed recipient only after that selection.
6. Stop before sending. A real message requires a separate approval that names
   the selected Profile and fixed recipient. Without that approval, the expected
   result of the live test is verified setup only and zero messages sent.

At every stage, a failure remains outside the standardized Wi-Fi report. The
detector's stdout and exit status are preserved, and setup can be resumed later
without rerunning Wi-Fi collection.
