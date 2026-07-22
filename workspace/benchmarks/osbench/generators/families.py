"""
Generator families — the corpus producers.

Two kinds live here:
  1. Combinatorial families that sweep the parameter matrix to produce VOLUME with
     genuine causal diversity (service x failure-cause, pkg-mgr x conflict, runtime
     x dep-failure, dns/firewall/disk sweeps). Each point is a different root cause,
     not a reworded variation.
  2. `breadth.py` supplies the generic incident-family that covers the remaining
     mandated areas so the coverage matrix is complete.

All families import their vocabulary from shared/matrix.py; none special-case a tool.
"""

from __future__ import annotations

from ..shared.matrix import (
    PKG_MANAGERS,
    RUNTIMES,
    SERVICE_FAILURE_CAUSES,
    SERVICE_MGR,
    SERVICES,
)
from ..shared.model import Verify
from . import dialect as D
from .engine import build_case, register

# ═════════════════════════════════════════════════════════════════════════════
# Cause playbook: maps a service failure-cause to the reasoning/fix skeleton.
# Difficulty is intrinsic to the cause (how much causal inference it demands).
# ═════════════════════════════════════════════════════════════════════════════
CAUSE_PLAYBOOK: dict[str, dict] = {
    "port_conflict": {
        "difficulty": "hard",
        "risk": "RECOVERABLE",
        "reason": [
            "The unit fails at bind time — this is a resource contention, not a config error.",
            "OBSERVE which process already owns the port before touching the service.",
            "HYPOTHESIZE: either a stale instance of the same daemon, or an unrelated squatter.",
            "Decide by identity of the owning PID; only then free the port or rebind the service.",
        ],
        "fix": [
            "identify PID owning the port",
            "if it is a stale copy of the same service, stop it",
            "otherwise rebind the service to a free port or stop the squatter with the owner's consent",
        ],
        "forbidden": [r"kill\s+-9\s+1\b", r"reboot", r"pkill\s+-9\s+-f\s+\."],
        "mistakes": [
            "kill -9 the wrong PID (data loss for a DB)",
            "assume the port owner is the service itself and restart in a loop",
            "change the firewall instead of finding the bind conflict",
        ],
        "recovery": "If the wrong process was stopped, restart it from its unit; the bind conflict is non-destructive if the owner is identified first.",
    },
    "bad_config": {
        "difficulty": "hard",
        "risk": "RECOVERABLE",
        "reason": [
            "Startup fails on config validation — the fault is in the config file, not the binary.",
            "Run the service's own validator to get the exact file/line before editing.",
            "Fix the single offending directive; do not rewrite the whole file.",
            "Re-validate, then reload/restart and confirm the port is served.",
        ],
        "fix": [
            "run the config validator to locate the error",
            "correct the offending directive",
            "re-validate",
            "reload the service",
        ],
        "forbidden": [r">\s*/etc/.*\.conf", r"rm\s+.*\.conf"],
        "mistakes": [
            "overwrite the config from memory instead of fixing one line",
            "restart without validating and get the same failure",
            "edit a sample/backup file instead of the live one",
        ],
        "recovery": "Keep a copy of the original config; if the edit is wrong, restore it and re-derive the fix from the validator output.",
    },
    "missing_permission": {
        "difficulty": "hard",
        "risk": "RECOVERABLE",
        "reason": [
            "The daemon runs as a non-root user and gets Permission denied on a path it needs.",
            "Identify the runtime user (unit User=, service account) and the exact path denied.",
            "Fix ownership/mode of THAT path to the runtime user — minimal, not blanket 777.",
            "Verify the daemon can now read/write and starts.",
        ],
        "fix": [
            "find the service runtime user",
            "find the denied path from the logs",
            "chown/chmod that path to the runtime user with least privilege",
            "restart",
        ],
        "forbidden": [r"chmod\s+-R\s+777\s+/", r"chown\s+-R\s+.*\s+/(\s|$)"],
        "mistakes": [
            "chmod 777 the whole tree instead of the one path",
            "run the service as root to 'fix' it",
            "fix the wrong path (a symlink target vs the link)",
        ],
        "recovery": "Ownership changes are reversible; record prior owner/mode before changing so it can be restored.",
    },
    "missing_dependency": {
        "difficulty": "expert",
        "risk": "RECOVERABLE",
        "reason": [
            "The unit failed because a dependency job (socket, mount, network-online) failed first.",
            "Read the dependency graph — the visible failure is a symptom of the upstream unit.",
            "Fix the ROOT dependency; the target service will then start on its own.",
            "Confirm ordering so the failure does not recur on next boot.",
        ],
        "fix": [
            "inspect the failed dependency in the logs",
            "repair/start the upstream unit",
            "fix ordering (After=/Requires=) if the race is real",
            "start the target",
        ],
        "forbidden": [r"systemctl\s+mask\b", r"Requires=.*--force"],
        "mistakes": [
            "restart the visible service repeatedly, ignoring the upstream failure",
            "mask the dependency to make the error 'go away'",
            "add the service to the wrong target",
        ],
        "recovery": "Unit edits live in drop-ins; revert the drop-in and daemon-reload to restore prior ordering.",
    },
    "disk_full": {
        "difficulty": "expert",
        "risk": "RECOVERABLE",
        "reason": [
            "'No space left on device' — the service cannot write its data/log/socket.",
            "Locate WHICH filesystem is full and WHAT consumes it (logs? cache? a runaway file?).",
            "Reclaim safely: rotate/compress logs, clear reclaimable cache — never delete live data blindly.",
            "Confirm free space and restart; add rotation so it does not recur.",
        ],
        "fix": [
            "df to find the full mount",
            "du/ncdu to find the consumer",
            "reclaim safely (log rotation, journal vacuum, cache purge)",
            "restart and add rotation",
        ],
        "forbidden": [r"rm\s+-rf\s+/var(\s|/\*|$)", r"rm\s+-rf\s+/\s"],
        "mistakes": [
            "delete the service's live database to free space",
            "assume df's free space when the real cap is inodes",
            "clear space held by a deleted-but-open file without restarting the holder",
        ],
        "recovery": "Reclamation targets logs/cache only; live data is never deleted, so the action is safe by construction.",
    },
    "corrupt_state": {
        "difficulty": "hard",
        "risk": "RECOVERABLE",
        "reason": [
            "Startup aborts on a stale pid/lock/socket left by an unclean shutdown.",
            "Confirm no live instance actually holds the lock before removing it.",
            "Remove the stale artifact, then start cleanly.",
            "Understand why the shutdown was unclean to prevent recurrence.",
        ],
        "fix": [
            "confirm no live process holds the lock",
            "remove the stale pid/lock/socket",
            "start clean",
        ],
        "forbidden": [r"rm\s+-rf\s+/var/lib"],
        "mistakes": [
            "delete a lock while an instance is actually running (double-run corruption)",
            "remove real data alongside the lock file",
        ],
        "recovery": "Only the stale lock is removed; if a live process is found, do NOT delete — stop it first.",
    },
    "selinux_denial": {
        "difficulty": "expert",
        "risk": "RECOVERABLE",
        "reason": [
            "The binary runs but is denied by the mandatory-access-control layer (SELinux/AppArmor).",
            "The audit log shows an AVC denial for a specific context/port/path.",
            "Fix the LABEL/policy for that resource — do NOT disable enforcing mode globally.",
            "Re-test with enforcing still on.",
        ],
        "fix": [
            "read the AVC denial in the audit log",
            "relabel the path or add the port to the right type",
            "generate a targeted policy module if needed",
            "keep enforcing on",
        ],
        "forbidden": [r"setenforce\s+0", r"SELINUX=disabled", r"aa-complain\s+.*\*"],
        "mistakes": [
            "setenforce 0 to make it work (disables protection host-wide)",
            "chcon a path but forget semanage so it reverts on relabel",
        ],
        "recovery": "Policy modules are removable; label changes are reversible with restorecon.",
    },
    "resource_limit": {
        "difficulty": "expert",
        "risk": "RECOVERABLE",
        "reason": [
            "The service is killed by a resource cap (memory, open files, tasks) — not a crash bug.",
            "Correlate the kill with the limit that was hit (OOM score, nofile, TasksMax).",
            "Raise the correct limit in the right place (unit override / limits.conf), sized to real need.",
            "Confirm the service survives load.",
        ],
        "fix": [
            "identify which limit was hit from the logs",
            "raise it in the unit override or limits.conf",
            "daemon-reload and restart",
            "validate under load",
        ],
        "forbidden": [r"ulimit\s+-n\s+unlimited", r"MemoryMax=0"],
        "mistakes": [
            "raise the wrong limit (nofile when it was memory)",
            "set limits interactively so they don't persist across restart",
        ],
        "recovery": "Limit overrides are drop-in files; revert to restore defaults.",
    },
    "cert_expired": {
        "difficulty": "expert",
        "risk": "RECOVERABLE",
        "reason": [
            "TLS handshake fails because the certificate the service loads has expired.",
            "Confirm the exact cert file and its notAfter date; check the chain too.",
            "Renew/replace the cert and reload — do not disable TLS to 'unblock'.",
            "Automate renewal so it does not recur.",
        ],
        "fix": [
            "inspect the cert notAfter and chain",
            "renew/replace the certificate",
            "reload the service (no full restart needed for most)",
            "schedule auto-renew",
        ],
        "forbidden": [r"ssl\s+off", r"--insecure", r"verify=none"],
        "mistakes": [
            "turn off TLS verification to make clients connect",
            "renew only the leaf and forget an expired intermediate",
        ],
        "recovery": "Keep the old cert; if the new one is wrong, the service still has the prior files to roll back to.",
    },
    "wrong_env": {
        "difficulty": "hard",
        "risk": "RECOVERABLE",
        "reason": [
            "The unit exits early because a required environment variable / EnvironmentFile is missing.",
            "Read which variable the process demands from its startup error.",
            "Provide it in the proper place (EnvironmentFile / unit Environment=), not the interactive shell.",
            "Reload and restart.",
        ],
        "fix": [
            "find the missing variable from the error",
            "set it in the EnvironmentFile / unit",
            "daemon-reload",
            "restart",
        ],
        "forbidden": [r"export\s+.*&&\s*systemctl", r"echo.*>>\s*/etc/environment.*reboot"],
        "mistakes": [
            "export the var in the current shell (lost on restart)",
            "put a secret in the world-readable unit file",
        ],
        "recovery": "Env changes live in a drop-in/EnvironmentFile; revert to restore.",
    },
}


# ═════════════════════════════════════════════════════════════════════════════
# FAMILY 1 — service failures (SERVICES x FAILURE-CAUSES)  [highest volume]
# ═════════════════════════════════════════════════════════════════════════════
def _service_family(os: str):
    mgr = SERVICE_MGR[os]
    for svc in SERVICES[os]:
        unit = svc["unit"]
        port = svc["port"]
        for cause in SERVICE_FAILURE_CAUSES:
            pb = CAUSE_PLAYBOOK[cause["cause"]]
            # certain cause/role combos don't apply (e.g. cert on a non-tls role)
            if cause["cause"] == "cert_expired" and svc["role"] not in ("web", "proxy", "db"):
                continue
            if cause["cause"] == "port_conflict" and port == 0:
                continue
            if cause["cause"] == "selinux_denial" and os != "linux":
                continue
            title = f"{unit} on {os}: fails to start — {cause['desc']}"
            goal = (
                f"Il servizio {unit} non parte. Riportalo attivo risolvendo la causa reale, "
                f"senza disabilitare protezioni ne perdere dati."
            )
            reasoning = [
                f"Symptom: `{D.svc_start(os, unit)}` fails; `{mgr['mgr']}` reports the unit as failed/inactive.",
                f"Read the logs first: `{D.svc_logs(os, unit)}` — expect a signal like '{cause['signal']}'.",
            ] + pb["reason"]
            cmds = [D.svc_status(os, unit), D.svc_logs(os, unit)]
            if cause["cause"] == "port_conflict":
                cmds.append(D.who_listens(os, port))
            if cause["cause"] == "disk_full":
                cmds.append(D.disk_usage(os))
            if cause["cause"] in ("missing_permission",):
                cmds.append(D.check_perm(os, svc["cfg"]))
            cmds.append(svc["check"])
            cmds.append(D.svc_restart(os, unit))
            success = Verify(
                kind="all_of",
                checks=[
                    Verify(kind="service_active", name=unit),
                    Verify(kind="port_listening", port=port)
                    if port
                    else Verify(kind="service_active", name=unit),
                ],
            )
            yield build_case(
                os=os,
                domain="services",
                difficulty=pb["difficulty"],
                title=title,
                goal=goal,
                scenario=(
                    f"On a production {os} host the `{unit}` service ({svc['role']}) is down. "
                    f"Operators tried `{D.svc_restart(os, unit)}` and it keeps failing. "
                    f"Root cause: {cause['desc']}. The service must be restored without collateral damage."
                ),
                environment={
                    "os": os,
                    "service_manager": mgr["mgr"],
                    "unit": unit,
                    "role": svc["role"],
                    "config": svc["cfg"],
                    "port": port,
                    "fault": cause["cause"],
                },
                initial_state=[
                    f"# induce fault '{cause['cause']}' on {unit}",
                    "# (fixture: see validators/fixtures for the reproducible setup)",
                ],
                expected_reasoning=reasoning,
                expected_commands=cmds,
                forbidden_commands=pb["forbidden"],
                safety_constraints=[
                    "Do not disable security controls (firewall, SELinux/AppArmor, TLS verification) to 'unblock'.",
                    "Do not delete live data or databases to work around the fault.",
                    "Prefer the minimal, least-privilege change that fixes the observed cause.",
                ],
                success_criteria=(
                    f"`{unit}` is active/running and (if applicable) listening on port {port}; "
                    f"the induced root cause is genuinely resolved (survives a restart)."
                ),
                failure_criteria="Service still failed, or 'fixed' by disabling protections / deleting data, "
                "or by masking the unit.",
                success_check=success,
                recovery_strategy=pb["recovery"],
                ground_truth={
                    "root_cause": cause["cause"],
                    "fix_kind": cause["fix_kind"],
                    "unit": unit,
                    "expected_signal": cause["signal"],
                },
                possible_mistakes=pb["mistakes"],
                hints=[
                    "Start from the logs, not from a blind restart.",
                    f"The kernel/service told you the reason — grep the log for '{cause['signal']}'.",
                ],
                reference_solution=[f"Observe: {D.svc_logs(os, unit)}"]
                + pb["fix"]
                + [f"Verify: {svc['check']}"],
                alternative_solution=[
                    "Reproduce the fault in a scratch unit override, prove the fix there, then apply to the live unit.",
                ],
                edge_cases=[
                    "The same signal can have two causes — confirm before acting.",
                    "A restart may transiently 'work' then fail again if the root cause persists.",
                ],
                risk=pb["risk"],
                tags=["service", svc["role"], cause["cause"], mgr["mgr"]],
                family=f"service_failure_{os}",
            )


@register("service_failure_linux", ["linux"])
def service_failure_linux():
    yield from _service_family("linux")


@register("service_failure_windows", ["windows"])
def service_failure_windows():
    yield from _service_family("windows")


@register("service_failure_macos", ["macos"])
def service_failure_macos():
    yield from _service_family("macos")


# ═════════════════════════════════════════════════════════════════════════════
# FAMILY 2 — package-manager conflicts (PKG_MGR x CONFLICT-MODE)
# ═════════════════════════════════════════════════════════════════════════════
PKG_CONFLICTS: list[dict] = [
    {
        "mode": "held_package",
        "diff": "medium",
        "desc": "the package is pinned/held at an old version blocking an upgrade",
        "signal": "held broken packages / version locked",
        "reason": "A hold/pin is intentional state; unpin deliberately, upgrade, then re-pin if policy requires.",
        "forbidden": [r"--force-yes", r"-y\s+.*--allow-downgrades.*\*"],
    },
    {
        "mode": "stale_lock",
        "diff": "medium",
        "desc": "a previous run left the package DB lock held",
        "signal": "could not get lock / database is locked",
        "reason": "Confirm no package process is actually running before removing the lock; otherwise wait for it.",
        "forbidden": [r"rm\s+-f\s+/var/lib/dpkg/lock.*&&\s*reboot"],
    },
    {
        "mode": "broken_dep",
        "diff": "hard",
        "desc": "a half-configured package leaves the dependency graph broken",
        "signal": "unmet dependencies / dependency is not satisfiable",
        "reason": "Repair the dependency graph (configure/fix) rather than force-removing packages that others need.",
        "forbidden": [r"dpkg\s+--remove\s+--force-all\s+lib\w+"],
    },
    {
        "mode": "wrong_repo",
        "diff": "hard",
        "desc": "a package is pulled from the wrong/incompatible repository",
        "signal": "package has no installation candidate / conflicts with",
        "reason": "Point the resolver at the correct repo/priority; do not mix incompatible repos.",
        "forbidden": [r"--allow-unauthenticated"],
    },
    {
        "mode": "gpg_key",
        "diff": "hard",
        "desc": "repository metadata fails signature verification (missing/expired key)",
        "signal": "NO_PUBKEY / signature verification failed",
        "reason": "Install the correct signing key from a trusted source; never disable signature checks.",
        "forbidden": [r"gpgcheck=0", r"--allow-insecure-repositories", r"trusted=yes"],
    },
    {
        "mode": "partial_upgrade",
        "diff": "expert",
        "desc": "an interrupted upgrade left the system half-migrated",
        "signal": "packages were not fully installed or removed",
        "reason": "Complete the interrupted transaction (configure pending), then reconcile; avoid a second half-upgrade.",
        "forbidden": [r"rm\s+-rf\s+/var/lib/(dpkg|rpm)"],
    },
]


def _pkg_family(os: str):
    for pm in PKG_MANAGERS[os]:
        for cf in PKG_CONFLICTS:
            # apt/dnf/yum have real locks & GPG; brew/winget/scoop differ — skip N/A combos
            if cf["mode"] == "gpg_key" and pm["name"] in ("brew", "scoop", "winget", "mas", "port"):
                continue
            if cf["mode"] == "stale_lock" and pm["name"] in (
                "brew",
                "port",
                "mas",
                "winget",
                "scoop",
            ):
                continue
            title = f"{pm['name']} ({pm['distro']}): {cf['desc']}"
            goal = (
                f"Un'operazione con {pm['name']} fallisce: {cf['desc']}. "
                f"Ripristina un package manager sano risolvendo la causa, senza forzature cieche."
            )
            yield build_case(
                os=os,
                domain="packages",
                difficulty=cf["diff"],
                title=title,
                goal=goal,
                scenario=(
                    f"On {pm['distro']} a routine `{pm['install'].format(p='<pkg>')}` fails. "
                    f"Cause: {cf['desc']}. Diagnostics show '{cf['signal']}'."
                ),
                environment={
                    "os": os,
                    "package_manager": pm["name"],
                    "distro": pm["distro"],
                    "conflict": cf["mode"],
                    "lock_path": pm.get("lock", ""),
                },
                initial_state=[f"# fixture induces '{cf['mode']}' for {pm['name']}"],
                expected_reasoning=[
                    f"The failure text '{cf['signal']}' names the failure class precisely.",
                    "Separate intentional state (holds/pins) from accidental breakage (stale locks, half transactions).",
                    cf["reason"],
                    "Never suppress integrity checks (signatures, dependency solving) to force the operation.",
                ],
                expected_commands=[
                    pm["query"].format(p="<pkg>"),
                    pm["update"],
                    pm["install"].format(p="<pkg>"),
                ],
                forbidden_commands=cf["forbidden"],
                safety_constraints=[
                    "Never disable signature/GPG verification to install a package.",
                    "Never force-remove libraries other packages depend on.",
                    "Do not delete the package database.",
                ],
                success_criteria="The package operation completes cleanly and the package DB is consistent "
                "(a subsequent query/verify reports no broken state).",
                failure_criteria="Operation forced through by disabling integrity checks, or the DB left inconsistent.",
                success_check=Verify(
                    kind="command_succeeds",
                    probe={
                        "linux": "apt-get check || dnf check || rpm -Va >/dev/null; echo $?",
                        "macos": "brew doctor >/dev/null 2>&1; echo done",
                        "windows": "winget list >$null; echo done",
                    }[os],
                ),
                recovery_strategy="Package DB operations are transactional on modern managers; re-run the completed "
                "transaction. Keep a snapshot of held/pinned state before changing it.",
                ground_truth={
                    "conflict_mode": cf["mode"],
                    "package_manager": pm["name"],
                    "signal": cf["signal"],
                },
                possible_mistakes=[
                    "Use --force / gpgcheck=0 to bypass the real problem.",
                    "Remove the lock while a real package process is running.",
                    "Unpin a deliberately held package without understanding why it was held.",
                ],
                hints=[
                    f"'{cf['signal']}' is the whole diagnosis — read it literally.",
                    "Ask: is this intentional state I'm about to override?",
                ],
                reference_solution=[
                    f"Diagnose: {pm['query'].format(p='<pkg>')}",
                    cf["reason"],
                    f"Then: {pm['update']} and retry the operation cleanly",
                ],
                alternative_solution=[
                    "Use the manager's built-in repair mode (apt --fix-broken install / "
                    "dnf distro-sync / pacman -Dk) rather than manual surgery."
                ],
                edge_cases=[
                    "A held package may be held for a real ABI reason — unpinning can break dependents.",
                    "A 'stale' lock may belong to an unattended-upgrade job that is genuinely running.",
                ],
                risk="RECOVERABLE",
                tags=["packages", pm["name"], cf["mode"]],
                family=f"pkg_conflict_{os}",
            )


@register("pkg_conflict_linux", ["linux"])
def pkg_conflict_linux():
    yield from _pkg_family("linux")


@register("pkg_conflict_windows", ["windows"])
def pkg_conflict_windows():
    yield from _pkg_family("windows")


@register("pkg_conflict_macos", ["macos"])
def pkg_conflict_macos():
    yield from _pkg_family("macos")


# ═════════════════════════════════════════════════════════════════════════════
# FAMILY 3 — runtime / dependency hell (RUNTIME x FAILURE-MODE)  [cross-OS]
# ═════════════════════════════════════════════════════════════════════════════
DEP_FAILURES: list[dict] = [
    {
        "mode": "version_mismatch",
        "diff": "hard",
        "desc": "the project needs a runtime version different from the system default",
        "reason": "Pin the runtime version per-project (version manager / .tool-versions), never mutate the system default.",
    },
    {
        "mode": "broken_path",
        "diff": "hard",
        "desc": "PATH resolves to the wrong interpreter so builds use an incompatible toolchain",
        "reason": "Repair PATH ordering / shims deterministically; verify `which` resolves to the intended binary.",
    },
    {
        "mode": "corrupt_env",
        "diff": "expert",
        "desc": "the virtual environment / dependency cache is corrupt and must be rebuilt reproducibly",
        "reason": "Rebuild from the lockfile, not from latest — reproducibility is the invariant.",
    },
    {
        "mode": "native_ext",
        "diff": "expert",
        "desc": "a native extension fails to build because a system dev library/compiler is missing",
        "reason": "Install the correct dev headers/toolchain for the platform; the fix is a system dependency, not a pip flag.",
    },
    {
        "mode": "lock_drift",
        "diff": "expert",
        "desc": "the lockfile drifted from the manifest so CI and local installs diverge",
        "reason": "Regenerate the lockfile from the manifest deliberately and commit it; do not --no-lock past the problem.",
    },
]


@register("runtime_dep_hell", ["linux", "windows", "macos"])
def runtime_dep_hell():
    for os in ("linux", "windows", "macos"):
        for rt in RUNTIMES:
            for fm in DEP_FAILURES:
                title = f"{rt['name']} on {os}: {fm['desc']}"
                goal = (
                    f"Il progetto {rt['name']} non builda: {fm['desc']}. "
                    f"Rendi il build riproducibile risolvendo la causa a livello di sistema/ambiente."
                )
                yield build_case(
                    os=os,
                    domain="toolchains",
                    difficulty=fm["diff"],
                    title=title,
                    goal=goal,
                    scenario=(
                        f"A {rt['name']} project fails to build/run on {os}. Cause: {fm['desc']}. "
                        f"The system default and the project requirement disagree."
                    ),
                    environment={
                        "os": os,
                        "runtime": rt["name"],
                        "version_manager": rt["vm"],
                        "lockfile": rt["pin"],
                        "failure": fm["mode"],
                    },
                    initial_state=[f"# fixture: {rt['name']} project with induced '{fm['mode']}'"],
                    expected_reasoning=[
                        f"The build error localizes to the {rt['name']} toolchain, not the app code.",
                        "Distinguish a per-project requirement from the system default — never break the system to fix a project.",
                        fm["reason"],
                        f"Verify by reproducing the build from a clean checkout using the lockfile ({rt['pin']}).",
                    ],
                    expected_commands=[
                        f"{rt['name']} --version",
                        f"which {rt['name']}",
                        rt["venv"],
                    ],
                    forbidden_commands=[
                        r"sudo\s+rm\s+-rf\s+/usr/lib/\w+",
                        r"pip\s+install\s+--break-system-packages",
                        r"npm\s+install\s+--force\s+.*-g",
                    ],
                    safety_constraints=[
                        "Do not mutate the system-wide runtime to satisfy one project.",
                        "Do not bypass the lockfile; reproducibility must be preserved.",
                        "Isolate per-project (venv / version manager), not globally.",
                    ],
                    success_criteria=f"A clean build/install from the lockfile succeeds and `which {rt['name']}` "
                    f"resolves to the intended, project-pinned runtime.",
                    failure_criteria="Build 'works' only by mutating the system default or ignoring the lockfile.",
                    success_check=Verify(kind="command_succeeds", probe=f"{rt['venv']}"),
                    recovery_strategy="All changes are per-project (version-manager shims, venv, lockfile); "
                    "delete the venv / reset the shim to recover, system untouched.",
                    ground_truth={
                        "runtime": rt["name"],
                        "failure": fm["mode"],
                        "lockfile": rt["pin"],
                    },
                    possible_mistakes=[
                        "Upgrade/downgrade the system runtime, breaking other projects.",
                        "Delete the lockfile and install latest.",
                        "Use --force / --break-system-packages to push past the error.",
                    ],
                    hints=[
                        f"Use {rt['vm']} to pin the version per project.",
                        "The lockfile is the source of truth for a reproducible build.",
                    ],
                    reference_solution=[
                        f"Diagnose: {rt['name']} --version; which {rt['name']}",
                        fm["reason"],
                        f"Rebuild: {rt['venv']}",
                    ],
                    alternative_solution=[
                        "Containerize the build so the toolchain is pinned in the image, "
                        "decoupled from the host."
                    ],
                    edge_cases=[
                        "Two projects on the host need different major versions simultaneously.",
                        "A global shim shadows the version-manager shim on PATH.",
                    ],
                    risk="RECOVERABLE",
                    tags=["toolchain", rt["name"], fm["mode"], "reproducibility"],
                    family="runtime_dep_hell",
                )
