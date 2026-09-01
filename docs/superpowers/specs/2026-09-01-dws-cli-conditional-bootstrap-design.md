# DWS CLI Conditional Bootstrap Design

**Date:** 2026-09-01

## Goal

Make DWS CLI `>=1.0.15` a conditionally managed dependency of
`enterprise-notification-bridge` so a DingTalk fallback can install, verify,
authorize, and bind DWS without conflicting with host-native DingTalk
integrations or blocking `wifi-health-detector` report generation.

## Scope

This change owns dependency discovery, install planning, approved installation,
version verification, first-use authorization, and transition into the existing
Profile-binding workflow. It does not invent a DWS message-send command, store
DingTalk credentials, infer a recipient, or change the standardized Wi-Fi
report.

## Provider-selection boundary

- `provider=native`: never install or upgrade DWS.
- `provider=dws-cli`: DWS `>=1.0.15` is required.
- `provider=auto`: use a declared host-native DingTalk Provider first. Request
  DWS installation only after native capability is absent or unavailable.
- Feishu and WeCom never install DWS.

This preserves compatibility with Codex, Claude Code, WorkBuddy, OpenClaw, and
enterprise Agents that already expose native DingTalk operations.

## Security and authorization boundary

Ordinary detector or delivery execution must never silently download or execute
software. A missing or outdated DWS dependency produces a correlated
`dependency_install_required` action. The action contains only public install
metadata: dependency name, minimum version, detected version, operating system,
official source, mirror selection, and install command identity.

The host must show that action to the user. Installation proceeds only through
an explicit `setup` command with `--install-dws --yes`, or through a correlated
continuation result that records the user's approval. Declining installation is
non-blocking and leaves the Wi-Fi report unchanged.

Only the official DingTalk DWS project may be used:

- GitHub: `DingTalk-Real-AI/dingtalk-workspace-cli`
- Explicit mainland-China mirror: the matching official Gitee project

The installer is downloaded to a private temporary directory, executed from a
local file, and removed afterward. The Bridge must not implement `curl | sh` or
`irm | iex`. If the selected upstream publishes a checksum for the fetched
artifact, it must be verified before execution. Otherwise the install result is
not trusted until the installed binary passes executable, version, and leaf
capability verification.

## Dependency model

`manifest.json` and `skill.yaml` retain Python as an unconditional runtime
requirement and declare DWS as a conditional DingTalk fallback requirement:

```yaml
requirements:
  - python>=3.7
conditional_requirements:
  dingtalk:dws-cli:
    - dws>=1.0.15
```

The runtime dependency record contains no credential or organization data:

```json
{
  "schema_version": "1",
  "dependencies": {
    "dws": {
      "executable": "/absolute/path/to/dws",
      "version": "1.0.15",
      "minimum_version": "1.0.15",
      "install_source": "official-github"
    }
  }
}
```

The path is revalidated on use. Environment variable `DWS_EXE` overrides
discovery for a single host installation.

## Discovery and verification

Discovery order:

1. Absolute path in `DWS_EXE`.
2. `dws` resolved through the current process PATH.
3. documented user-local install locations.
4. Homebrew locations on macOS.
5. npm global executable locations when they are already discoverable.

Verification requires:

1. the resolved path is an executable regular file or a platform-resolved
   executable command;
2. DWS reports a parseable semantic version of at least `1.0.15`;
3. `dws auth status --help` advertises JSON output before it is used;
4. `dws auth login --help` advertises JSON output before it is used;
5. `dws profile list --help` advertises JSON output before it is used.

Every business leaf keeps the existing per-leaf `--help` gate. No undocumented
DWS leaf may be invented.

## CLI and continuation contract

Add:

```text
run.sh setup --platform dingtalk --provider auto|native|dws-cli
             [--install-dws] [--china-mirror] [--device-login] [--yes]
```

`setup` is idempotent. It returns exactly one JSON document.

Important statuses:

- `dependency_ready`
- `dependency_install_required`
- `dependency_install_declined`
- `dependency_download_failed`
- `dependency_integrity_failed`
- `dependency_install_failed`
- `dependency_version_unsupported`
- `dependency_verification_failed`
- `dws_upgrade_required`
- `dws_authorization_required`
- `dws_admin_authorization_required`

After dependency verification, setup calls the existing authorization/Profile
binding workflow. `dws auth login` runs only on first use or when authorization
is expired. Multiple Profiles still require explicit selection. A recipient is
never selected during dependency setup.

MCP exposes the same behavior through `setup_notification_dependency`; it must
delegate to the same service and continuation store as the CLI.

## Wi-Fi detector behavior

`wifi-health-detector` remains zero-dependency and report-first:

1. collect and validate the report;
2. print only the standardized Markdown report;
3. trigger the Bridge when notification is enabled;
4. if the Bridge returns `dependency_install_required`, keep it outside stdout
   and preserve detector exit success;
5. never install DWS from the detector process itself.

The host Agent may then ask for installation approval and invoke Bridge setup.

## Failure policy and privacy

- Dependency, installation, authorization, Profile, recipient, and delivery
  failures are non-blocking for Wi-Fi detection.
- Installer stdout/stderr is not copied into the standard report or Provider
  result. Stable reason codes are used by default.
- Tokens, cookies, Profiles, organization IDs, recipient IDs, and report
  contents are not written to install logs.
- Temporary installer files and directories are private and removed on success
  or failure.
- Bridge configuration, dependency state, continuation state, and ledger files
  remain user-only where the operating system supports permissions.

## Testing

Tests must prove:

- native and non-DingTalk Providers never install DWS;
- `auto` installs only after native capability is unavailable;
- compliant DWS is reused without installation;
- missing and outdated DWS produce the correct action/status;
- installation cannot execute without explicit approval;
- only official source identifiers and platform installers are accepted;
- download, integrity, execution, and post-install verification failures are
  distinct;
- successful installation is followed by version and leaf verification;
- authorized users do not log in again;
- expired users enter login and then Profile binding;
- multiple Profiles require explicit selection;
- detector stdout and exit status never change;
- macOS, Linux, and Windows command construction is covered without executing
  a live remote installer in unit tests;
- a gated manual integration test can use a real DWS installation and test
  organization.

## Out of scope

- silently installing DWS during a detector run;
- installing DWS for native DingTalk, Feishu, or WeCom;
- guessing package managers or falling back to unofficial mirrors;
- resetting DWS credentials automatically;
- sending to `self`, a default recipient, or an inferred person;
- bypassing DWS through direct DingTalk HTTP APIs;
- inventing an undocumented DWS send leaf.
