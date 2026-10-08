# Wi-Fi runtime fallback implementation plan

> Execute inline using executing-plans and test-driven-development. User approved implementation of the in-chat design on 2026-10-08.

Goal: Python → OS-native → Node, without installing runtime dependencies.

Architecture: keep the existing Python engine; add shared capture/parser/report contracts for fallback engines. macOS uses Bash for collection and system JXA for deterministic JSON/report processing. Windows uses PowerShell 5.1 for collection and reporting. Node uses the shared JavaScript report core and native commands. Select engines before collection; never retry a completed or permission-denied run with another engine.

Constraints: fixed five report sections, 18 core rows, schema 2.0, Chinese/English, masking, explicit exports, optional notification, no automatic runtime installation. Preserve unavailable values and explanations. No package-manager dependencies.

Review focus: spaces and Unicode in paths/SSID; missing/broken/hanging interpreters; command errors versus genuine packet loss; time budgets and cleanup; cross-engine scoring and masking parity.

## Tasks

- [x] 1. Add launcher selection tests; bounded Python discovery, native capability probes, Node override/discovery, explicit engine flag.
- [x] 2. Add shared report fixtures and JavaScript contract core with exact Python rendering/scoring parity; verify with Node and macOS JXA.
- [x] 3. Implement macOS bounded parallel native capture, common parsing, Node standalone collector, and PowerShell native engine; validate fixture paths and OS-specific limitations.
- [x] 4. Parallelize Python quality checks, distinguish failed commands from packet loss, bound DNS and total collection, add fast mode.
- [x] 5. Update manifests/docs, test launchers and contracts, perform independent review and fix significant findings.

Verification: Python unittest suite; fixture differential tests against Python; Bash syntax and native help; native no-Python execution on this Mac; Node fixture/CLI tests. Windows execution must be verified on Windows CI if no local PowerShell exists.

## Ledger

- Baseline: system /usr/bin/python3 fails with broken xcrun developer path, reproducing the class of runtime failure reported by the user. Use explicitly supplied desktop runtime for development tests only; production discovery stays host-independent.
- Ruling: macOS report processing uses OS-provided JXA instead of handwritten awk JSON encoding, reducing escaping and consistency risk. If JXA is unavailable, preflight falls back to Node.
- Ruling: retain no persistent interpreter-path cache: finite discovery avoids stale-path state and installation coupling. Cost: candidate checks run on each invocation.
- Ruling: native/Node detection does not invoke Python Bridge; the permitted notification degradation is explicit on stderr. Windows frequency width is unavailable when netsh lacks it. Costs: notifications and Native WLAN supplementation still require the Python path in this release.
- Independent review: reviewer identified native Windows encoding, subprocess descendants retaining pipes, operational Ping failures with loss summaries, and asynchronous stream draining. All four addressed; regression tests cover timeout descendants, Ping failure rejection and PowerShell process output/draining. Actual Windows OEM decoding remains a Windows CI/hardware check.
- Verified: 68 detector tests PASS with explicit development Python, Node and PowerShell runtimes; 237 Bridge tests run, 236 PASS and 1 environment-dependent skip. PowerShell 7.4.6 portable package downloaded to temporary storage and verified against official SHA256; no system installation. Native macOS live collection and Node live collection completed with bounded settings; syntax checks for shell, JavaScript and PowerShell pass.
- PowerShell differential tests exposed ISO timestamp auto-conversion; added string-preserving JSON import and verified exact Chinese/English, masking, scoring, Unicode and Windows capture fixtures against the other engines.
- Legacy Bridge producer versions 2.4/2.5 retain deterministic integral-float display compatibility; producer 2.6 uses canonical whole-number display. Regression test failed before the compatibility correction and passed afterward.
- Platform limitation: no physical Windows host was available. PowerShell 5.1 and actual Windows WLAN collection are covered by the added CI job but were not executed here. Hardware/enterprise-policy acceptance remains necessary.
- Delivery: user subsequently requested testing and local integration into the original checkout on `codex/vcenter-aiops-3`. The original checkout and isolated worktree share base `27e16df`; unrelated untracked files must remain untouched. No push or publication requested.
