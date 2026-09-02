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
3. If native is unavailable, inspect DWS. Version 1.0.15 or newer must pass the
   JSON version check and the per-leaf JSON-format help gates.
4. Missing or outdated DWS returns `dependency_install_required` or
   `dws_upgrade_required`. This is a proposal, not approval.

## Approved installation

Review the returned action with the user, including platform, minimum version,
source, and whether the China mirror was requested. Only then run the matching
setup command with both `--install-dws` and `--yes`:

```text
# macOS or Linux, official GitHub source
./run.sh setup --platform dingtalk --provider dws-cli --install-dws --yes

# macOS or Linux, explicitly selected official Gitee China mirror
./run.sh setup --platform dingtalk --provider dws-cli --china-mirror --install-dws --yes

# Windows PowerShell launcher, official GitHub source
run.ps1 setup --platform dingtalk --provider dws-cli --install-dws --yes

# Windows batch launcher
run.bat setup --platform dingtalk --provider dws-cli --install-dws --yes
```

The installer accepts only the official DingTalk GitHub release source or the
explicit official Gitee China mirror. It downloads into a private temporary
directory, validates the planned artifact, executes it locally without a shell
pipeline, removes temporary material on success or failure, and verifies the
installed binary again. Never replace these sources with a package-manager
guess, an unofficial mirror, `curl | sh`, or `irm | iex`.

## Authorization, organization, and recipients

After DWS verification, setup checks authorization. A DingTalk login window,
device code, or QR scan is requested only on first use or when saved
authorization has expired. A currently authorized user must not be prompted on
every report.

Organization binding uses only Profiles returned by the Provider. A stable
Profile has the shape `corpId:userId`. If exactly one Profile is returned, it
may be persisted. If several are returned, stop and have the user select the
exact Profile; never choose the current/default organization or construct an
identifier.

Fixed recipients are configured after Profile binding and may be decided later:

```text
./run.sh recipients --platform dingtalk --profile corpId:userId --recipient <exact-configured-selector>
```

An empty recipient list means no send. Never infer `self`, the current user, a
default contact, or a similarly named person. First delivery still requires its
separate correlated confirmation.

## Independent upgrade and uninstall

The Bridge reports `dws_upgrade_required` when the discovered version is below
1.0.15. Repeat the approved setup flow to upgrade from an official source, or
follow the official DWS release procedure outside the detector. To uninstall,
use the official DWS uninstall procedure for the installed platform, then switch
the channel to a native Provider or disable it. These lifecycle operations do
not remove or modify `wifi-health-detector`.

## Gated real-environment test

The automated suite uses fakes and does not download DWS, open DingTalk, query
an organization, or send a message. A real preflight requires explicit approval
for each external side effect.

1. With approval to inspect an existing installation, run `dws --version` and
   require 1.0.15 or newer.
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
