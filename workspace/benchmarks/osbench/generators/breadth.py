"""
Breadth families — data-driven coverage of the remaining mandated areas.

Each entry in `BREADTH` is a family = (domain, os-applicability, resource, faults[]).
A single driver expands every (family, fault, os) point into a fully-populated Case.
The fault dict carries the DISTINGUISHING content (root cause, reasoning, commands,
forbidden set, success predicate); the driver supplies the consistent scaffolding
(title/goal/scenario templates, generic-but-real safety framing) so authoring a new
area is adding data, not code — mirroring the matrix-driven discipline.

Every fault below is a real, distinct root cause an on-call engineer meets. None are
reworded duplicates: the `signature()` in the model would drop those anyway.
"""

from __future__ import annotations

from typing import Iterator

from ..shared.model import Case, Verify
from .engine import build_case, register


def _v(kind: str, **kw) -> Verify:
    return Verify(kind=kind, **kw)  # small constructor alias for compact fault data


# A fault: mode, diff, desc, signal, reason[], cmds[], forbidden[], success(Verify),
# mistakes[], hints[], reference[], alternative[], edge[], and optional risk/safety/recovery.
def _drive(
    family: str,
    domain: str,
    os_list: list[str],
    resource: str,
    faults: list[dict],
    goal_tpl: str,
    scen_tpl: str,
) -> Iterator[Case]:
    for os in os_list:
        for f in faults:
            if "os_only" in f and os not in f["os_only"]:
                continue
            desc = f["desc"]
            title = f"{resource} on {os}: {desc}"
            goal = goal_tpl.format(resource=resource, desc=desc)
            scenario = scen_tpl.format(
                resource=resource, desc=desc, os=os, signal=f.get("signal", "")
            )
            safety = f.get(
                "safety",
                [
                    "Fix the observed root cause; do not mask the symptom.",
                    "Prefer the least-privilege, reversible change.",
                    "Do not disable security controls or delete live data to 'unblock'.",
                ],
            )
            recovery = f.get(
                "recovery",
                "Record prior state before changing it; every step here is reversible if the "
                "change is captured (config backup / snapshot) first.",
            )
            success_criteria = f.get(
                "success_criteria",
                f"The '{desc}' condition is genuinely resolved: the observed root cause "
                f"('{f['mode']}') no longer holds and the affected function works, verified by the success check.",
            )
            yield build_case(
                os=os,
                domain=domain,
                difficulty=f["diff"],
                title=title,
                goal=goal,
                scenario=scenario,
                environment={
                    "os": os,
                    "resource": resource,
                    "fault": f["mode"],
                    **f.get("env", {}),
                },
                initial_state=[f"# fixture induces '{f['mode']}' for {resource} on {os}"],
                expected_reasoning=f["reason"],
                expected_commands=f["cmds"],
                forbidden_commands=f["forbidden"],
                safety_constraints=safety,
                success_criteria=success_criteria,
                failure_criteria=f.get(
                    "failure_criteria",
                    "The symptom persists, or it was 'resolved' by masking, disabling protections, "
                    "or destroying data.",
                ),
                success_check=f["success"],
                recovery_strategy=recovery,
                ground_truth={
                    "root_cause": f["mode"],
                    "resource": resource,
                    "signal": f.get("signal", ""),
                    **f.get("gt", {}),
                },
                possible_mistakes=f["mistakes"],
                hints=f["hints"],
                reference_solution=f["reference"],
                alternative_solution=f["alternative"],
                edge_cases=f["edge"],
                risk=f.get("risk", "RECOVERABLE"),
                tags=[domain, resource, f["mode"]] + f.get("tags", []),
                family=family,
            )


# ═════════════════════════════════════════════════════════════════════════════
# The breadth dataset. Grouped by area; driven uniformly.
# ═════════════════════════════════════════════════════════════════════════════

CONTAINER_FAULTS = [
    {
        "mode": "image_pull",
        "diff": "medium",
        "desc": "image pull fails (auth/registry/tag)",
        "signal": "pull access denied / manifest unknown",
        "reason": [
            "Distinguish an auth failure from a wrong tag from an unreachable registry.",
            "Read the exact pull error; check `docker login` state and the tag's existence.",
            "Fix the specific cause (login, correct tag, registry mirror), then re-pull.",
        ],
        "cmds": [
            "docker pull <img>:<tag>",
            "docker login <registry>",
            "docker manifest inspect <img>:<tag>",
        ],
        "forbidden": [r"--tls-verify=false", r"insecure-registries.*0\.0\.0\.0/0"],
        "success": _v("command_succeeds", probe="docker image inspect <img>:<tag>"),
        "mistakes": [
            "Add the registry to insecure-registries to bypass TLS.",
            "Assume 'manifest unknown' is an auth issue and re-login pointlessly.",
        ],
        "hints": [
            "`docker manifest inspect` tells you if the tag exists without pulling.",
            "Registry auth is per-registry; check ~/.docker/config.json.",
        ],
        "reference": [
            "Inspect the pull error",
            "Fix auth/tag/registry",
            "Re-pull and inspect locally",
        ],
        "alternative": [
            "Mirror the image through a trusted internal registry and pull from there."
        ],
        "edge": ["Rate-limited public registry returns 'toomanyrequests', not an auth error."],
    },
    {
        "mode": "container_exit",
        "diff": "hard",
        "desc": "container exits immediately (non-zero)",
        "signal": "exited (1) / CrashLoopBackOff at container level",
        "reason": [
            "The container's own logs carry the crash reason — read them before anything.",
            "Separate an app crash (bad config/env) from an entrypoint/permission problem.",
            "Fix the root cause in the image/config, not by adding `restart: always` to hide it.",
        ],
        "cmds": [
            "docker logs <ctr> --tail 100",
            "docker inspect <ctr> --format '{{.State.ExitCode}} {{.Config.Entrypoint}}'",
            "docker run --rm -it <img> sh",
        ],
        "forbidden": [r"restart:\s*always\s*#.*hide", r"--privileged\b"],
        "success": _v(
            "command_stdout", probe="docker inspect -f '{{.State.Running}}' <ctr>", pattern="true"
        ),
        "mistakes": [
            "Add restart:always to mask a crash loop.",
            "Run --privileged to sidestep a permission problem.",
        ],
        "hints": [
            "`docker logs` first; the exit code plus stderr is the diagnosis.",
            "Override the entrypoint with a shell to inspect the filesystem live.",
        ],
        "reference": [
            "Read container logs",
            "Reproduce interactively",
            "Fix config/env/permission in the image",
        ],
        "alternative": [
            "Rebuild the image with a healthcheck so orchestration surfaces the real failure."
        ],
        "edge": ["Exit 0 but 'stopped' because the main process forks and the PID1 exits."],
    },
    {
        "mode": "volume_perms",
        "diff": "hard",
        "desc": "bind-mount/volume permission mismatch (uid/gid)",
        "signal": "Permission denied on a mounted path",
        "reason": [
            "The container user's uid/gid does not match the host path owner on a bind mount.",
            "Align ownership (host or container user) or use a named volume with correct init.",
            "Do not chmod 777 the host path.",
        ],
        "cmds": [
            "docker inspect <ctr> --format '{{.Mounts}}'",
            "id -u; id -g",
            "ls -ln <hostpath>",
        ],
        "forbidden": [r"chmod\s+-R\s+777\s+<hostpath>", r"--user\s+0:0\s*#.*just to fix"],
        "success": _v(
            "command_succeeds",
            probe="docker exec <ctr> sh -c 'touch /data/.w && rm /data/.w && echo ok'",
        ),
        "mistakes": [
            "chmod 777 the host directory.",
            "Run the container as root to dodge the mismatch.",
        ],
        "hints": [
            "Compare host owner uid vs the container process uid.",
            "A named volume gets initialized with the image path's ownership.",
        ],
        "reference": [
            "Find container uid/gid",
            "Match host path ownership or use a named volume",
            "Verify a write",
        ],
        "alternative": [
            "Use user-namespace remapping (userns-remap) so container root maps to an unprivileged host uid."
        ],
        "edge": [
            "SELinux needs the :z/:Z mount label, not an ownership change, on RHEL-family hosts."
        ],
    },
    {
        "mode": "compose_network",
        "diff": "hard",
        "desc": "compose services cannot reach each other by name",
        "signal": "could not resolve host / connection refused between services",
        "reason": [
            "Compose puts services on a shared network resolvable by service name; a mismatch breaks DNS.",
            "Check they share a network and the client uses the SERVICE name and correct port, not localhost.",
            "Fix the network/depends_on/port, not by hardcoding IPs.",
        ],
        "cmds": [
            "docker compose config",
            "docker compose ps",
            "docker network inspect <proj>_default",
        ],
        "forbidden": [r"network_mode:\s*host\s*#.*workaround", r"links:\s*#.*deprecated"],
        "success": _v(
            "command_succeeds", probe="docker compose exec app sh -c 'getent hosts db && echo ok'"
        ),
        "mistakes": [
            "Use localhost between containers instead of the service name.",
            "Hardcode a container IP that changes on recreate.",
        ],
        "hints": [
            "Inter-service DNS uses the service name on the compose network.",
            "`docker compose config` shows the resolved networks.",
        ],
        "reference": [
            "Confirm shared network",
            "Use service-name:port from the client",
            "Verify name resolution",
        ],
        "alternative": ["Define an explicit named network and attach both services to it."],
        "edge": [
            "A service on a custom network but the client on the default network cannot see it."
        ],
    },
    {
        "mode": "podman_rootless",
        "diff": "expert",
        "desc": "rootless podman cannot bind a low port / map subuid",
        "signal": "rootlessport / permission denied binding :80",
        "os_only": ["linux"],
        "reason": [
            "Rootless containers cannot bind <1024 by default and depend on subuid/subgid ranges.",
            "Either publish to a high port + reverse proxy, or grant the capability deliberately.",
            "Verify /etc/subuid and /etc/subgid ranges exist for the user.",
        ],
        "cmds": [
            "podman info --format '{{.Host.Security.Rootless}}'",
            "cat /etc/subuid /etc/subgid",
            "sysctl net.ipv4.ip_unprivileged_port_start",
        ],
        "forbidden": [r"sudo\s+podman\s+.*#.*just run as root", r"setcap.*=eip\s+/usr/bin/podman"],
        "success": _v("command_succeeds", probe="podman ps --format '{{.Names}}'"),
        "mistakes": [
            "Fall back to running podman as root, defeating rootless isolation.",
            "Miss that /etc/subuid has no range for the user.",
        ],
        "hints": [
            "net.ipv4.ip_unprivileged_port_start lets rootless bind lower ports.",
            "subuid/subgid ranges are required for the user namespace mapping.",
        ],
        "reference": [
            "Verify subuid/subgid + rootless mode",
            "Publish high port + proxy, or lower unprivileged port start",
            "Verify the container runs and is reachable",
        ],
        "alternative": [
            "Run the container in a systemd user unit (podman generate systemd) with the right lingering setup."
        ],
        "edge": ["cgroups v1 host cannot do rootless resource limits; v2 is required."],
    },
]

DB_FAULTS = [
    {
        "mode": "conn_refused",
        "diff": "medium",
        "desc": "clients get connection refused",
        "signal": "connection refused / could not connect to server",
        "reason": [
            "Refused means nothing is listening where the client points — check the server is up and the bind address.",
            "Verify listen address/port and that the client targets the right host/port.",
            "Fix bind/listen or client target; do not open auth wide to 'test'.",
        ],
        "cmds": [
            "ss -ltnp | grep -E '5432|3306|6379|27017'",
            "grep -E 'listen|bind' <cfg>",
            "systemctl status <db>",
        ],
        "forbidden": [
            r"trust\s+all",
            r"bind\s+0\.0\.0\.0\s*#.*just to test",
            r"--skip-grant-tables",
        ],
        "success": _v("port_listening", port=5432),
        "mistakes": [
            "Set auth to trust/all to 'rule out auth' and forget to revert.",
            "Bind 0.0.0.0 exposing the DB publicly.",
        ],
        "hints": [
            "Refused vs timeout distinguishes 'not listening' from 'filtered'.",
            "Check listen_addresses / bind-address in the DB config.",
        ],
        "reference": [
            "Confirm the DB listens where expected",
            "Align client target / bind address",
            "Verify a connection",
        ],
        "alternative": ["Connect over the local socket to isolate a TCP-vs-auth problem."],
        "edge": ["The DB listens on IPv6 localhost only while the client uses IPv4 127.0.0.1."],
    },
    {
        "mode": "max_connections",
        "diff": "hard",
        "desc": "'too many connections' under load",
        "signal": "FATAL: sorry, too many clients already",
        "reason": [
            "The connection cap is hit — usually a leak/absent pooling, not a too-small cap.",
            "Investigate who holds connections (idle-in-transaction?) before raising max_connections.",
            "Add pooling / fix the leak; raise the cap only if the workload truly needs it and RAM allows.",
        ],
        "cmds": [
            "psql -c 'select state,count(*) from pg_stat_activity group by 1'",
            "grep max_connections <cfg>",
            "ss -tn state established | wc -l",
        ],
        "forbidden": [r"max_connections\s*=\s*100000", r"kill\s+-9\s+.*postgres.*#.*all"],
        "success": _v("command_succeeds", probe="psql -c 'select 1' >/dev/null && echo ok"),
        "mistakes": [
            "Blindly raise max_connections to a number the RAM cannot back.",
            "Kill -9 backends, risking recovery on restart.",
        ],
        "hints": [
            "Look for idle-in-transaction sessions leaking connections.",
            "A pooler (pgbouncer) fixes the cause; a bigger cap often just delays it.",
        ],
        "reference": [
            "Profile pg_stat_activity",
            "Fix the leak / add pooling",
            "Right-size the cap for the RAM",
        ],
        "alternative": [
            "Introduce a connection pooler in front of the DB and lower per-app pool sizes."
        ],
        "edge": [
            "Reserved superuser connections mask the real exhaustion until an admin also fails."
        ],
    },
    {
        "mode": "disk_wal",
        "diff": "expert",
        "desc": "DB stops writing because WAL/redo filled the disk",
        "signal": "could not write to file / No space left on device",
        "reason": [
            "The DB halted to protect integrity when its WAL/redo volume filled.",
            "Reclaim space safely (archive/checkpoint), never delete live WAL by hand.",
            "Then address why WAL grew (stuck replication slot / archiving failure).",
        ],
        "cmds": [
            "df -h <datadir>",
            "psql -c 'select * from pg_replication_slots'",
            "du -sh <datadir>/pg_wal",
        ],
        "forbidden": [r"rm\s+-f\s+.*pg_wal/\*", r"rm\s+.*ib_logfile"],
        "success": _v(
            "command_succeeds",
            probe="psql -c 'create table _bw(x int); drop table _bw;' && echo ok",
        ),
        "mistakes": [
            "Delete WAL/redo files manually, corrupting the DB.",
            "Free space but leave the stuck replication slot that will refill it.",
        ],
        "hints": [
            "An inactive replication slot pins WAL forever — that's often the real cause.",
            "Force a checkpoint / fix archiving before the volume refills.",
        ],
        "reference": [
            "Find the full volume + WAL growth cause",
            "Drop the stuck slot / fix archiving",
            "Checkpoint to reclaim; verify writes",
        ],
        "alternative": [
            "Temporarily add space to the WAL volume to recover, then fix the retention cause."
        ],
        "edge": [
            "Deleting the slot loses a downstream replica — confirm the replica is expendable first."
        ],
    },
    {
        "mode": "slow_query",
        "diff": "expert",
        "desc": "a query regressed to a full scan (missing/!used index)",
        "signal": "high latency / Seq Scan in EXPLAIN",
        "reason": [
            "Latency spiked on one query path — get the plan, don't guess.",
            "EXPLAIN ANALYZE shows the scan; decide index vs stats vs query rewrite from the plan.",
            "Add the right index or refresh stats; verify the plan flips and latency drops.",
        ],
        "cmds": [
            "psql -c 'explain (analyze,buffers) <query>'",
            "psql -c 'select * from pg_stat_user_tables'",
            "psql -c 'analyze <table>'",
        ],
        "forbidden": [r"enable_seqscan\s*=\s*off\s*#.*global", r"pg_terminate_backend.*all"],
        "success": _v("command_stdout", probe="psql -c 'explain <query>'", pattern="Index"),
        "mistakes": [
            "Disable seqscan globally instead of adding the index.",
            "Add a redundant index that duplicates an existing one.",
        ],
        "hints": [
            "Stale stats after a bulk load make the planner pick a seq scan — ANALYZE first.",
            "buffers in EXPLAIN reveals cache vs disk cost.",
        ],
        "reference": [
            "Capture the plan",
            "Add index / refresh stats / rewrite",
            "Confirm the plan and latency improve",
        ],
        "alternative": ["Add a partial or covering index if only a hot subset of rows is queried."],
        "edge": ["The index exists but is not used because of a type mismatch in the predicate."],
    },
]

PERF_FAULTS = [
    {
        "mode": "runaway_cpu",
        "diff": "hard",
        "desc": "one process pins CPU at 100%",
        "signal": "load average high, one PID at ~100% CPU",
        "reason": [
            "High load can be CPU, IO-wait, or run-queue — identify which from top/vmstat first.",
            "Attribute the CPU to a specific PID and thread; understand WHY before killing.",
            "Throttle/renice or fix the cause; kill only if it is genuinely stuck and safe.",
        ],
        "cmds": ["top -b -n1 -o %CPU | head", "pidstat 1 3", "cat /proc/<pid>/status"],
        "forbidden": [r"kill\s+-9\s+1\b", r"pkill\s+-9\s+-f\s+\.\*"],
        "success": _v("command_succeeds", probe="uptime"),
        "mistakes": [
            "kill -9 a process mid-write, corrupting its output.",
            "Blame CPU when the real bottleneck is IO-wait.",
        ],
        "hints": [
            "vmstat separates user/sys/iowait — don't assume CPU.",
            "renice / cpulimit throttles without killing.",
        ],
        "reference": [
            "Classify the load (CPU vs IO vs runqueue)",
            "Attribute to a PID/thread",
            "Throttle or fix the cause",
        ],
        "alternative": [
            "Put the process in a cgroup with a CPU quota to bound it without killing it."
        ],
        "edge": ["A short-lived storm of forks (fork bomb) shows as many PIDs, not one."],
    },
    {
        "mode": "oom_kill",
        "diff": "expert",
        "desc": "the OOM killer is reaping processes",
        "signal": "Out of memory: Killed process / oom-kill in dmesg",
        "reason": [
            "Confirm real memory pressure vs cache; read dmesg for the OOM victim and score.",
            "Find the memory leaker or the overcommit misconfig; size limits to reality.",
            "Add a bound (cgroup MemoryMax / swap) so the leaker is contained, not the innocent victim.",
        ],
        "cmds": ["dmesg -T | grep -i oom", "free -h", "ps -eo pid,rss,comm --sort=-rss | head"],
        "forbidden": [r"echo\s+1\s*>\s*/proc/sys/vm/panic_on_oom", r"swapoff\s+-a\s*#.*to force"],
        "success": _v("command_succeeds", probe="free -m"),
        "mistakes": [
            "Disable swap to 'save memory', making OOM more likely.",
            "Raise limits blindly instead of finding the leak.",
        ],
        "hints": [
            "The OOM report names the victim and the hog's RSS.",
            "cache is reclaimable; only anon/RSS pressure triggers OOM.",
        ],
        "reference": [
            "Read the OOM report",
            "Identify the true hog",
            "Bound it (cgroup/limit) and add swap headroom",
        ],
        "alternative": [
            "Set a systemd MemoryMax on the offending service so it is capped before the host OOMs."
        ],
        "edge": ["A memory cgroup limit (not host memory) triggered the kill inside a container."],
    },
    {
        "mode": "io_saturation",
        "diff": "expert",
        "desc": "disk IO saturated, everything stalls",
        "signal": "high %iowait, high await in iostat",
        "reason": [
            "High iowait points at storage, not CPU — measure per-device latency.",
            "Attribute IO to a process (iotop/pidstat -d); understand the workload pattern.",
            "Throttle the offender / fix the workload; escalate storage only if genuinely undersized.",
        ],
        "cmds": ["iostat -xz 1 3", "iotop -bo -n2", "pidstat -d 1 3"],
        "forbidden": [
            r"echo\s+3\s*>\s*/proc/sys/vm/drop_caches\s*#.*fix",
            r"mount.*-o\s+async,nobarrier",
        ],
        "success": _v("command_succeeds", probe="iostat -x 1 1"),
        "mistakes": [
            "Drop caches expecting it to fix IO (it doesn't).",
            "Disable write barriers, risking data integrity on power loss.",
        ],
        "hints": [
            "await + %util in iostat pinpoint the saturated device.",
            "A backup/rebuild job is a common hidden IO source.",
        ],
        "reference": [
            "Measure per-device IO",
            "Attribute to a process",
            "Throttle/reschedule the offender",
        ],
        "alternative": [
            "Use ionice/blkio cgroup to deprioritize the batch job during business hours."
        ],
        "edge": ["The saturation is a degraded RAID rebuilding, not a rogue process."],
    },
    {
        "mode": "fd_exhaustion",
        "diff": "expert",
        "desc": "process hits the open-file-descriptor limit",
        "signal": "Too many open files / EMFILE",
        "reason": [
            "EMFILE means the process (or system) fd limit is hit — often a leak, not a too-low limit.",
            "Count fds per process and check the effective ulimit; find the leak source.",
            "Fix the leak or raise nofile in the right place (unit LimitNOFILE), sized to need.",
        ],
        "cmds": [
            "ls /proc/<pid>/fd | wc -l",
            "cat /proc/<pid>/limits",
            "lsof -p <pid> | awk '{print $5}' | sort | uniq -c",
        ],
        "forbidden": [r"ulimit\s+-n\s+unlimited", r"fs.file-max\s*=\s*9999999999"],
        "success": _v("command_succeeds", probe="echo check-nofile"),
        "mistakes": [
            "Raise the limit to hide a socket/file leak.",
            "Set ulimit interactively so it doesn't persist for the service.",
        ],
        "hints": [
            "lsof grouped by type reveals whether sockets or files leak.",
            "systemd services need LimitNOFILE in the unit, not a login-shell ulimit.",
        ],
        "reference": [
            "Count fds + read the limit",
            "Find and fix the leak",
            "Raise LimitNOFILE if genuinely needed",
        ],
        "alternative": ["Add connection reuse/pooling so the fd count stops growing."],
        "edge": ["The system-wide file-max is fine but the per-process soft limit is the cap."],
    },
]

# Compact area families with 2-4 faults each, cross-OS where sensible.
LOG_FAULTS = [
    {
        "mode": "find_root_error",
        "diff": "medium",
        "desc": "correlate the first error across logs for an incident",
        "signal": "cascading errors; find the first cause",
        "reason": [
            "A cascade has one first cause; order events by time across sources.",
            "Filter to the incident window and the earliest ERROR/critical entry.",
            "Report the root event, not the loudest downstream symptom.",
        ],
        "cmds": [
            "journalctl --since '-30min' -p err --no-pager",
            "journalctl -u <svc> --since '-30min'",
            "grep -R -i error /var/log | tail",
        ],
        "forbidden": [r"rm\s+.*/var/log/", r"truncate\s+-s0"],
        "success": _v("artifact", path="incident_rootcause.txt"),
        "mistakes": [
            "Report the last error instead of the first.",
            "Delete/rotate logs during the investigation.",
        ],
        "hints": [
            "Sort by timestamp across sources; the earliest anomaly is usually causal.",
            "-p err limits journald to the priority you care about.",
        ],
        "reference": [
            "Bound the time window",
            "Merge sources by time",
            "Identify + write the first-cause",
        ],
        "alternative": ["Ship to a central store and use its query to time-align sources."],
        "edge": ["Clock skew between hosts reorders events — normalize to UTC first."],
    },
    {
        "mode": "log_flood",
        "diff": "hard",
        "desc": "a chatty service floods the journal and hides signal",
        "signal": "journal rate-limited / disk filling with logs",
        "reason": [
            "One noisy unit drowns others and can fill the journal volume.",
            "Identify the top talker and whether the messages indicate a real fault.",
            "Fix the underlying noise or rate-limit that unit; do not blanket-disable logging.",
        ],
        "cmds": [
            "journalctl --disk-usage",
            "journalctl -u <svc> --since '-10min' | wc -l",
            "systemctl show <svc> -p LogRateLimitIntervalSec",
        ],
        "forbidden": [r"Storage=none", r"SystemMaxUse=1K"],
        "success": _v("command_succeeds", probe="journalctl --disk-usage"),
        "mistakes": [
            "Disable logging entirely to stop the flood.",
            "Vacuum the journal but leave the flooding source running.",
        ],
        "hints": [
            "Rate-limit the specific unit, not the whole journald.",
            "The flood is often a real error firing in a tight loop.",
        ],
        "reference": [
            "Find the top talker",
            "Fix the real error or rate-limit that unit",
            "Confirm signal is visible again",
        ],
        "alternative": [
            "Route that unit to its own file with rotation, keeping the main journal clean."
        ],
        "edge": [
            "The 'flood' is audit logging of a brute-force attack — the fix is upstream, not logging."
        ],
    },
]

CRON_FAULTS = [
    {
        "mode": "not_firing",
        "diff": "medium",
        "desc": "a scheduled job never runs",
        "signal": "no output, job silently skipped",
        "reason": [
            "A job that 'never runs' is usually a schedule, environment, or permission issue — verify it is registered.",
            "Check the schedule syntax, the running user, and the job's PATH/env (cron has a minimal env).",
            "Confirm from the scheduler's own log that it fired; fix the specific gap.",
        ],
        "cmds": ["crontab -l", "systemctl status cron", "grep CRON /var/log/syslog | tail"],
        "forbidden": [r"\*\s+\*\s+\*\s+\*\s+\*\s+.*#.*brute force", r"chmod\s+777\s+/etc/cron"],
        "success": _v("artifact", path="/tmp/cronjob.ran"),
        "mistakes": [
            "Assume cron has your login PATH (it doesn't).",
            "Edit the wrong user's crontab.",
        ],
        "hints": [
            "cron runs with a minimal environment — set PATH inside the job.",
            "The scheduler log proves whether it fired at all.",
        ],
        "reference": [
            "Confirm registration + schedule",
            "Fix env/PATH/user",
            "Prove it fired via the scheduler log",
        ],
        "alternative": ["Convert to a systemd timer for better logging and dependency handling."],
        "edge": [
            "The job fires but writes to a relative path in a different CWD than expected.",
            "% in a crontab command must be escaped or it truncates the command.",
        ],
    },
    {
        "mode": "task_scheduler",
        "diff": "hard",
        "desc": "a Windows Scheduled Task fails or runs with wrong context",
        "signal": "last run result 0x1 / task ran but did nothing",
        "os_only": ["windows"],
        "reason": [
            "A task 'failing' is usually principal/context, working-directory, or 'run whether logged on' settings.",
            "Check the principal, Start-in directory, and the last-run result code.",
            "Fix the specific setting; test with the exact service account.",
        ],
        "cmds": [
            "Get-ScheduledTask -TaskName <t> | Get-ScheduledTaskInfo",
            "Export-ScheduledTask -TaskName <t>",
            "Get-WinEvent -LogName 'Microsoft-Windows-TaskScheduler/Operational'",
        ],
        "forbidden": [r"-RunLevel\s+Highest\s*#.*just to fix", r"SYSTEM\s*#.*escalate blindly"],
        "success": _v(
            "command_stdout",
            probe="(Get-ScheduledTaskInfo -TaskName <t>).LastTaskResult",
            pattern="^0$",
        ),
        "mistakes": [
            "Run everything as SYSTEM to dodge a permission/context issue.",
            "Forget 'Start in' so relative paths break.",
        ],
        "hints": [
            "LastTaskResult decodes the failure (0x1 generic, 0x41303 not registered).",
            "'Run whether user is logged on or not' changes the session/desktop context.",
        ],
        "reference": [
            "Read LastTaskResult + operational log",
            "Fix principal/Start-in/trigger",
            "Re-run under the real account",
        ],
        "alternative": ["Wrap the action in a script that logs its own environment for diagnosis."],
        "edge": [
            "The task needs 'Run with highest privileges' for a UAC-elevated action, legitimately."
        ],
    },
]

ENV_FAULTS = [
    {
        "mode": "path_order",
        "diff": "medium",
        "desc": "the wrong binary wins because of PATH order",
        "signal": "`which` resolves to an unexpected path",
        "reason": [
            "`command not found' or wrong version is a PATH ordering/shadowing problem.",
            "Inspect the effective PATH and where the intended binary lives; find the shadowing entry.",
            "Fix the order deterministically in the right rc/profile for the shell in use.",
        ],
        "cmds": ["which -a <bin>", "echo $PATH | tr ':' '\\n'", "type -a <bin>"],
        "forbidden": [r"export\s+PATH=/usr/bin\s*#.*nuke", r">\s*~/.bashrc"],
        "success": _v("command_stdout", probe="which <bin>", pattern="/"),
        "mistakes": [
            "Overwrite PATH entirely, losing needed entries.",
            "Edit .bashrc for a zsh login shell (wrong rc file).",
        ],
        "hints": [
            "`which -a` lists ALL matches in order — the first wins.",
            "Login vs interactive shells read different rc files.",
        ],
        "reference": [
            "List all matches + PATH",
            "Reorder in the correct rc file",
            "Open a fresh shell and verify",
        ],
        "alternative": [
            "Use a version manager's shim directory placed first on PATH instead of hand-editing."
        ],
        "edge": ["A per-directory .envrc (direnv) overrides PATH only inside that tree."],
    },
    {
        "mode": "broken_profile",
        "diff": "hard",
        "desc": "a syntax error in a shell rc breaks every new shell",
        "signal": "login shell errors / commands unavailable in new terminals",
        "reason": [
            "A bad line in an rc file runs on every shell start, breaking the environment globally for the user.",
            "Start a shell that skips rc files to regain a working prompt, then locate the offending line.",
            "Fix the single line; validate by opening a clean shell.",
        ],
        "cmds": ["bash --noprofile --norc", "bash -n ~/.bashrc", "tail -n 20 ~/.bashrc"],
        "forbidden": [r"rm\s+~/.bashrc\s*#.*nuke", r">\s*~/.zshrc"],
        "success": _v("command_succeeds", probe="bash -n ~/.bashrc && echo ok"),
        "mistakes": [
            "Delete the whole rc file, losing real configuration.",
            "Edit rc from inside a shell that itself fails to start.",
        ],
        "hints": [
            "`bash -n` syntax-checks without executing.",
            "--norc gives you a clean shell to do the repair.",
        ],
        "reference": [
            "Get a clean shell (--norc)",
            "Syntax-check + fix the offending line",
            "Open a fresh login shell to verify",
        ],
        "alternative": ["Bisect the rc by sourcing halves until the failing block is isolated."],
        "edge": ["The error is in a file the rc sources, not the rc itself."],
    },
]

BACKUP_FAULTS = [
    {
        "mode": "restore_test",
        "diff": "hard",
        "desc": "verify a backup actually restores (not just that it exists)",
        "signal": "backups run green but were never test-restored",
        "reason": [
            "A backup that has never been restored is a hypothesis, not a backup.",
            "Restore to an isolated location and verify integrity/consistency against a known checksum/row count.",
            "Only then declare the backup valid; document RPO/RTO observed.",
        ],
        "cmds": [
            "<restore-cmd> --target /restore/scratch",
            "sha256sum -c manifest.sha256",
            "<db> consistency check on the restored copy",
        ],
        "forbidden": [r"--target\s+/\s", r"restore.*over.*production"],
        "success": _v("artifact", path="restore_verification.txt"),
        "mistakes": [
            "Restore over production to 'test' it.",
            "Trust the backup job's exit code as proof of restorability.",
        ],
        "hints": [
            "Restore to scratch, not over the source.",
            "Verify content (checksums/row counts), not just that files appeared.",
        ],
        "reference": [
            "Restore to isolated scratch",
            "Verify integrity vs known-good",
            "Record RPO/RTO",
        ],
        "alternative": [
            "Automate a periodic restore-test in CI against the latest backup artifact."
        ],
        "edge": [
            "The backup restores but is logically inconsistent (taken without a quiesce/snapshot)."
        ],
    },
    {
        "mode": "dr_failover",
        "diff": "principal",
        "desc": "design + execute a disaster-recovery failover for a stateful service",
        "signal": "primary lost; must fail over with bounded data loss",
        "reason": [
            "A DR failover is a sequence with a data-loss budget (RPO) and a time budget (RTO) — plan before acting.",
            "Confirm replica health and lag, fence the dead primary, promote, and repoint clients atomically.",
            "Validate correctness end-to-end and prevent split-brain before reopening traffic.",
        ],
        "cmds": [
            "<replica> lag/health check",
            "<promote replica to primary>",
            "<repoint clients / update service discovery>",
        ],
        "forbidden": [r"promote.*without.*fence", r"repoint.*before.*promote.*verified"],
        "success": _v("artifact", path="failover_runbook_executed.txt"),
        "mistakes": [
            "Promote a lagging replica, exceeding the RPO.",
            "Fail to fence the old primary, causing split-brain.",
        ],
        "hints": [
            "Fence first, then promote, then repoint — order prevents split-brain.",
            "Quantify lag so the data-loss window is known, not assumed.",
        ],
        "reference": [
            "Assess replica lag/health",
            "Fence + promote + repoint atomically",
            "Validate + document RPO/RTO achieved",
        ],
        "alternative": [
            "If lag is unacceptable, recover the primary in place rather than accept data loss."
        ],
        "edge": ["Clients cache the old primary's IP; DNS TTL delays the cutover."],
    },
]

SECURITY_MAC_FAULTS = [
    {
        "mode": "selinux_confine",
        "diff": "expert",
        "desc": "keep SELinux enforcing while allowing a legitimate action",
        "signal": "avc: denied for a legitimate operation",
        "os_only": ["linux"],
        "reason": [
            "An AVC denial for a legitimate action means the policy needs a targeted allowance, not disabling.",
            "Read the audit denial, generate/apply a minimal policy or correct the label.",
            "Keep enforcing mode; verify the action now succeeds under enforcement.",
        ],
        "cmds": [
            "ausearch -m avc -ts recent",
            "sealert -a /var/log/audit/audit.log",
            "restorecon -Rv <path>",
        ],
        "forbidden": [
            r"setenforce\s+0",
            r"SELINUX=disabled",
            r"semanage.*permissive\s+-a\s+.*_t\s*#.*blanket",
        ],
        "success": _v("command_stdout", probe="getenforce", pattern="Enforcing"),
        "mistakes": ["setenforce 0 to make it work.", "Blanket-permissive a whole domain."],
        "hints": [
            "restorecon fixes a mislabel; semanage fcontext makes it persist.",
            "audit2allow builds a minimal module for a genuine new access.",
        ],
        "reference": [
            "Read the AVC",
            "Relabel or add a minimal policy module",
            "Verify under Enforcing",
        ],
        "alternative": [
            "Use the correct pre-existing boolean (setsebool) when one covers the case."
        ],
        "edge": ["The denial is dontaudit-suppressed elsewhere and only shows with full auditing."],
    },
    {
        "mode": "defender_exclusion",
        "diff": "hard",
        "desc": "Defender quarantines a legitimate build artifact",
        "signal": "Operation did not complete / file quarantined",
        "os_only": ["windows"],
        "reason": [
            "A false positive quarantine needs a SCOPED, justified exclusion — not disabling Defender.",
            "Confirm the detection and the file's provenance, add a narrow path/process exclusion.",
            "Keep real-time protection on; document the exclusion.",
        ],
        "cmds": [
            "Get-MpThreat",
            "Get-MpPreference | Select Exclusion*",
            "Add-MpPreference -ExclusionPath '<narrow path>'",
        ],
        "forbidden": [
            r"Set-MpPreference\s+-DisableRealtimeMonitoring\s+\$true",
            r"-ExclusionPath\s+'C:\\'",
        ],
        "success": _v(
            "command_stdout", probe="(Get-MpPreference).DisableRealtimeMonitoring", pattern="False"
        ),
        "mistakes": ["Disable real-time protection entirely.", "Exclude C:\\ or the whole drive."],
        "hints": [
            "Scope the exclusion to the exact build output path/process.",
            "Verify the file is genuinely benign before excluding.",
        ],
        "reference": [
            "Confirm the detection/provenance",
            "Add a narrow exclusion",
            "Keep protection on; document",
        ],
        "alternative": ["Sign the artifact / build in a trusted location Defender already trusts."],
        "edge": [
            "The 'false positive' is a real supply-chain compromise — do NOT exclude; investigate."
        ],
    },
    {
        "mode": "gatekeeper_quarantine",
        "diff": "hard",
        "desc": "Gatekeeper blocks a legitimately-obtained binary",
        "signal": "cannot be opened because the developer cannot be verified",
        "os_only": ["macos"],
        "reason": [
            "Gatekeeper blocks unsigned/unnotarized or quarantined binaries — verify provenance, then clear scoped.",
            "Confirm the source is trusted; remove the quarantine attribute on that file only.",
            "Do not globally disable Gatekeeper.",
        ],
        "cmds": [
            "xattr -p com.apple.quarantine <file>",
            "spctl -a -vv <file>",
            "xattr -d com.apple.quarantine <file>",
        ],
        "forbidden": [
            r"spctl\s+--master-disable",
            r"sudo\s+xattr\s+-dr\s+com.apple.quarantine\s+/",
        ],
        "success": _v(
            "command_succeeds", probe="spctl -a -vv <file> 2>&1 | grep -q accepted && echo ok"
        ),
        "mistakes": [
            "spctl --master-disable (turns Gatekeeper off globally).",
            "Strip quarantine recursively from the whole disk.",
        ],
        "hints": [
            "The quarantine xattr is per-file; remove it only after verifying provenance.",
            "spctl -a shows the assessment reason.",
        ],
        "reference": [
            "Verify provenance",
            "Remove quarantine on that file",
            "Confirm spctl accepts it",
        ],
        "alternative": [
            "Obtain a properly signed/notarized build from the vendor instead of overriding."
        ],
        "edge": ["The binary is genuinely unsigned malware — verification should stop you here."],
    },
]

GIT_FAULTS = [
    {
        "mode": "detached_head",
        "diff": "medium",
        "desc": "work committed on a detached HEAD looks 'lost'",
        "signal": "you are in detached HEAD state",
        "reason": [
            "Detached-HEAD commits are not lost — they are unreferenced, reachable via reflog.",
            "Find the dangling commit in the reflog and attach a branch to it.",
            "Never reset --hard before rescuing the work.",
        ],
        "cmds": ["git reflog", "git branch rescue <sha>", "git status"],
        "forbidden": [r"git\s+reset\s+--hard", r"git\s+gc\s+--prune=now\s*#.*before rescue"],
        "success": _v("command_succeeds", probe="git rev-parse --verify rescue"),
        "mistakes": [
            "reset --hard, discarding the detached work.",
            "gc --prune before creating a ref to the commit.",
        ],
        "hints": [
            "reflog remembers where HEAD has been.",
            "A branch is just a pointer — point one at the sha.",
        ],
        "reference": [
            "Find the sha in reflog",
            "Create a branch on it",
            "Verify the work is referenced",
        ],
        "alternative": ["cherry-pick the sha onto the intended branch."],
        "edge": ["The commit predates the reflog expiry window but is still in fsck --lost-found."],
    },
    {
        "mode": "corrupt_index",
        "diff": "hard",
        "desc": "a corrupt index/lock blocks all git operations",
        "signal": "index file corrupt / fatal: Unable to create '.git/index.lock'",
        "reason": [
            "A stale lock or corrupt index blocks git but the object store is usually intact.",
            "Confirm no git process is running, remove the stale lock, rebuild the index from HEAD.",
            "Verify the working tree and history are intact afterwards.",
        ],
        "cmds": [
            "ls -l .git/index.lock",
            "rm -f .git/index.lock",
            "git read-tree HEAD || git reset --mixed",
        ],
        "forbidden": [r"rm\s+-rf\s+\.git\b", r"git\s+reset\s+--hard\s*#.*before verifying"],
        "success": _v("command_succeeds", probe="git status >/dev/null && echo ok"),
        "mistakes": [
            "rm -rf .git (destroys all local history).",
            "Remove the lock while a real git process holds it.",
        ],
        "hints": [
            "The object database survives an index corruption — rebuild the index.",
            "index.lock is stale only if no git process is alive.",
        ],
        "reference": [
            "Confirm no live git process",
            "Remove stale lock",
            "Rebuild index from HEAD; verify status",
        ],
        "alternative": [
            "Re-clone and copy uncommitted changes if the object store is also damaged."
        ],
        "edge": [
            "Corruption in a packfile (not the index) needs git fsck + fetching the object from a remote."
        ],
    },
]

IAC_FAULTS = [
    {
        "mode": "tf_state_lock",
        "diff": "hard",
        "desc": "Terraform state is locked by a dead run",
        "signal": "Error acquiring the state lock",
        "reason": [
            "A stale lock from a crashed apply blocks new runs; confirm no apply is actually in flight.",
            "Verify with the backend (who/when) before force-unlocking to avoid concurrent corruption.",
            "Force-unlock with the exact lock ID, then re-plan.",
        ],
        "cmds": ["terraform plan", "terraform force-unlock <LOCK_ID>", "terraform state list"],
        "forbidden": [
            r"rm\s+.*terraform\.tfstate\b",
            r"terraform\s+force-unlock\s+-force\s*#.*blind",
        ],
        "success": _v(
            "command_succeeds", probe="terraform plan -lock=false -detailed-exitcode; echo done"
        ),
        "mistakes": [
            "Delete the state file to get past the lock.",
            "Force-unlock while a real apply is running elsewhere (corrupts state).",
        ],
        "hints": [
            "The lock info names the holder and time — check it's really dead.",
            "Never edit/delete tfstate by hand to escape a lock.",
        ],
        "reference": ["Confirm no live apply", "force-unlock with the lock ID", "Re-plan"],
        "alternative": [
            "If the backend supports it, inspect and clear the lock via the backend console."
        ],
        "edge": [
            "Two CI runners raced; the 'stale' lock is a live parallel apply — do not unlock."
        ],
    },
    {
        "mode": "ansible_idempotent",
        "diff": "expert",
        "desc": "an Ansible play is not idempotent (changed every run)",
        "signal": "changed=... on every converge for the same state",
        "reason": [
            "A converged play should report changed=0 on a no-op run; perpetual change means a non-idempotent task.",
            "Find the offending task (command/shell without creates/changed_when, or a templating churn).",
            "Make it idempotent (proper module, creates/changed_when), verify a second run is changed=0.",
        ],
        "cmds": [
            "ansible-playbook site.yml --check --diff",
            "ansible-playbook site.yml",
            "ansible-playbook site.yml",
        ],
        "forbidden": [r"changed_when:\s*false\s*#.*hide", r"shell:.*#.*instead of a module"],
        "success": _v("artifact", path="ansible_idempotence_proof.txt"),
        "mistakes": [
            "Slap changed_when: false to fake idempotence.",
            "Use shell/command where a proper module exists.",
        ],
        "hints": [
            "A second converge must be changed=0 — that's the definition.",
            "command/shell need creates/removes or changed_when to be idempotent.",
        ],
        "reference": [
            "Find the always-changed task",
            "Replace with an idempotent module / add creates/changed_when",
            "Prove run #2 is changed=0",
        ],
        "alternative": [
            "Gate the task with a fact/stat check so it only runs when the state truly differs."
        ],
        "edge": [
            "Template whitespace/ordering churn flags 'changed' though content is equivalent."
        ],
    },
]

FILESHARE_FAULTS = [
    {
        "mode": "nfs_stale",
        "diff": "hard",
        "desc": "NFS mount is stale after server restart",
        "signal": "Stale file handle",
        "os_only": ["linux", "macos"],
        "reason": [
            "A stale handle means the export changed under the client; the mount must be re-established.",
            "Confirm the server/export is healthy, then unmount (lazy if busy) and remount.",
            "Fix the root (export fsid stability / automount) so it does not recur.",
        ],
        "cmds": [
            "showmount -e <server>",
            "umount -l <mnt>",
            "mount -t nfs <server>:<export> <mnt>",
        ],
        "forbidden": [r"umount\s+-f.*&&.*rm\s+-rf", r"soft,nolock\s*#.*to hide"],
        "success": _v("command_succeeds", probe="stat <mnt> && echo ok"),
        "mistakes": [
            "Force-unmount and delete the mountpoint's data by mistake.",
            "Add soft mounts hiding a server stability problem (risking data corruption).",
        ],
        "hints": [
            "Lazy unmount detaches a busy mount safely.",
            "A stable fsid on the export prevents stale handles across server restarts.",
        ],
        "reference": [
            "Verify export health",
            "Lazy-unmount + remount",
            "Stabilize export/automount",
        ],
        "alternative": ["Use autofs so mounts recover automatically on access."],
        "edge": ["The client caches the old handle; only a full remount clears it."],
    },
    {
        "mode": "smb_auth",
        "diff": "hard",
        "desc": "SMB/CIFS share rejects credentials or protocol version",
        "signal": "mount error(13) permission denied / protocol negotiation failed",
        "reason": [
            "SMB failures are auth (domain/creds), protocol (SMBv1 disabled), or signing mismatches — read the exact error.",
            "Test with explicit credentials and a supported vers=; align to the server's requirements.",
            "Fix the specific mismatch without downgrading to insecure SMBv1.",
        ],
        "cmds": [
            "smbclient -L //<server> -U <user>",
            "mount -t cifs //<server>/<share> <mnt> -o vers=3.0,user=<u>",
            "Get-SmbClientConfiguration",
        ],
        "forbidden": [r"vers=1\.0", r"client\s+min\s+protocol\s*=\s*NT1"],
        "success": _v("command_succeeds", probe="ls <mnt> && echo ok"),
        "mistakes": [
            "Enable SMBv1 to connect (deprecated, insecure).",
            "Embed the password in plaintext in fstab world-readable.",
        ],
        "hints": [
            "Specify vers= explicitly; auto-negotiation may pick an unsupported version.",
            "Use a credentials file with 0600 perms, not inline password.",
        ],
        "reference": [
            "Identify auth vs protocol vs signing",
            "Mount with correct vers/creds",
            "Verify listing",
        ],
        "alternative": [
            "Use a Kerberos ticket (sec=krb5) instead of NTLM where the domain supports it."
        ],
        "edge": ["The share works but a per-file ACL denies the specific user."],
    },
]

VIRT_FAULTS = [
    {
        "mode": "nested_virt",
        "diff": "expert",
        "desc": "a VM/hypervisor won't start (nested virt / VT-x disabled)",
        "signal": "VT-x is not available / hypervisor error",
        "reason": [
            "A hypervisor that won't start usually lacks CPU virtualization (disabled in BIOS or nested-virt off).",
            "Confirm the capability at the CPU/host level before touching the guest config.",
            "Enable the correct layer (host nested virt / firmware) or pick a compatible accel.",
        ],
        "cmds": [
            {
                "linux": "egrep -c '(vmx|svm)' /proc/cpuinfo",
                "windows": "Get-ComputerInfo -Property Hyper*",
                "macos": "sysctl kern.hv_support",
            }.get("linux", ""),
            "kvm-ok || systool -m kvm_intel",
            "lsmod | grep kvm",
        ],
        "forbidden": [r"--enable-kvm\s*#.*without vmx", r"BIOS.*disable.*security"],
        "success": _v("command_succeeds", probe="egrep -q '(vmx|svm)' /proc/cpuinfo && echo ok"),
        "mistakes": [
            "Force KVM accel on a host without vmx/svm.",
            "Blame the guest image for a host capability gap.",
        ],
        "hints": [
            "vmx (Intel)/svm (AMD) in cpuinfo prove hardware virt is available to the host.",
            "Nested virt must be enabled on the parent hypervisor for a VM-in-VM.",
        ],
        "reference": [
            "Confirm CPU virt at host level",
            "Enable nested virt / firmware setting",
            "Retry the guest",
        ],
        "alternative": [
            "Fall back to a software/emulated accel (slower) if hardware virt truly isn't available."
        ],
        "edge": [
            "Hyper-V present steals VT-x from VirtualBox on Windows — they can't both use it."
        ],
    },
]

REMOTE_FAULTS = [
    {
        "mode": "vpn_split_dns",
        "diff": "expert",
        "desc": "VPN connects but internal names don't resolve (split DNS)",
        "signal": "connected but internal hosts unreachable by name",
        "reason": [
            "VPN up + IP reachable + names failing = the tunnel didn't install the internal DNS/search domains.",
            "Inspect the effective resolver and routes the VPN pushed; confirm the internal domain is routed to the internal DNS.",
            "Fix the split-DNS config so internal names use internal resolvers.",
        ],
        "cmds": [
            {
                "linux": "resolvectl status",
                "windows": "Get-DnsClientNrptPolicy",
                "macos": "scutil --dns",
            }.get("linux", ""),
            "ip route || route print",
            "nslookup <internal-host>",
        ],
        "forbidden": [
            r"nameserver\s+.*internal.*>\s*/etc/resolv\.conf\s*#.*all traffic",
            r"route\s+add\s+default.*vpn\s*#.*all",
        ],
        "success": _v("command_succeeds", probe="nslookup <internal-host> >/dev/null && echo ok"),
        "mistakes": [
            "Route ALL DNS to the internal resolver, breaking public resolution.",
            "Add a default route through the VPN when only split routes are wanted.",
        ],
        "hints": [
            "Per-domain (split) DNS sends only the internal zone to the internal resolver.",
            "Check what the tunnel actually pushed vs what's needed.",
        ],
        "reference": [
            "Inspect effective DNS + routes",
            "Configure split-DNS for the internal domain",
            "Verify resolution",
        ],
        "alternative": [
            "Use the VPN client's own split-tunnel/split-DNS profile rather than editing the OS resolver."
        ],
        "edge": ["Two active interfaces race on DNS priority; the metric decides who wins."],
    },
]

KERNEL_FAULTS = [
    {
        "mode": "module_load",
        "diff": "hard",
        "desc": "a kernel module fails to load (missing/signed/dep)",
        "signal": "modprobe: ERROR / Required key not available",
        "os_only": ["linux"],
        "reason": [
            "A module load failure is missing dependency, version mismatch, or Secure Boot signature.",
            "Read the exact modprobe/dmesg error; check the module exists for THIS kernel and is signed if SB is on.",
            "Install the matching module / enroll the signing key; do not disable Secure Boot casually.",
        ],
        "cmds": ["modprobe <mod>", "dmesg | tail", "modinfo <mod>; uname -r"],
        "forbidden": [r"mokutil\s+--disable-validation", r"module.sig_enforce=0\s*#.*permanent"],
        "success": _v("command_stdout", probe="lsmod | grep <mod>", pattern="<mod>"),
        "mistakes": [
            "Disable Secure Boot validation to load an unsigned module.",
            "Load a module built for a different kernel version.",
        ],
        "hints": [
            "modinfo vs uname -r reveals a kernel/module version mismatch.",
            "Under Secure Boot the module must be signed or the key enrolled (mokutil).",
        ],
        "reference": [
            "Read the load error",
            "Install matching/signed module or enroll key",
            "Verify with lsmod",
        ],
        "alternative": ["Rebuild the module via DKMS so it tracks the running kernel."],
        "edge": ["The module loads but a conflicting one already claimed the device."],
    },
]

ENCRYPTION_FAULTS = [
    {
        "mode": "luks_unlock",
        "diff": "expert",
        "desc": "an encrypted volume won't unlock at boot / mount",
        "signal": "cryptsetup: no key available / device busy",
        "os_only": ["linux"],
        "reason": [
            "An encrypted volume failing to open is a key/keyslot/crypttab issue — do NOT reformat.",
            "Confirm the correct key/keyfile and the crypttab mapping; test an unlock manually.",
            "Fix the mapping/keyslot; never run luksFormat on a volume with data.",
        ],
        "cmds": ["cryptsetup luksDump <dev>", "cryptsetup open <dev> <name>", "cat /etc/crypttab"],
        "forbidden": [r"cryptsetup\s+luksFormat", r"mkfs.*<dev>"],
        "success": _v(
            "command_succeeds", probe="cryptsetup status <name> | grep -q active && echo ok"
        ),
        "mistakes": [
            "Run luksFormat, destroying the master key and all data.",
            "Add the wrong keyfile path in crypttab.",
        ],
        "hints": [
            "luksDump shows which keyslots are populated.",
            "Test the unlock manually before trusting the boot path.",
        ],
        "reference": [
            "Inspect keyslots",
            "Unlock with the correct key/keyfile",
            "Fix crypttab; verify status",
        ],
        "alternative": ["Recover using a backed-up LUKS header if a keyslot was clobbered."],
        "edge": ["The passphrase is right but the header backup was restored to the wrong device."],
    },
    {
        "mode": "bitlocker_recovery",
        "diff": "hard",
        "desc": "BitLocker demands the recovery key after a change",
        "signal": "BitLocker recovery screen at boot",
        "os_only": ["windows"],
        "reason": [
            "A firmware/TPM/boot change invalidated the TPM seal, triggering recovery — this is expected, not corruption.",
            "Unlock with the escrowed recovery key, then re-seal to the TPM so it stops prompting.",
            "Do not disable BitLocker to avoid the prompt.",
        ],
        "cmds": [
            "manage-bde -status",
            "manage-bde -unlock C: -RecoveryPassword <key>",
            "manage-bde -protectors -enable C:",
        ],
        "forbidden": [r"manage-bde\s+-off\s+C:", r"Disable-BitLocker\s*#.*to avoid prompt"],
        "success": _v("command_stdout", probe="manage-bde -status C:", pattern="Protection On"),
        "mistakes": [
            "Decrypt the drive entirely to stop the prompt (loses protection).",
            "Not knowing where the recovery key is escrowed (AD/AAD/MSA).",
        ],
        "hints": [
            "The recovery key is escrowed in AD/Entra/Microsoft account — retrieve it there.",
            "Re-enable the TPM protector after a legitimate firmware change to re-seal.",
        ],
        "reference": [
            "Retrieve recovery key from escrow",
            "Unlock",
            "Re-seal to TPM; confirm Protection On",
        ],
        "alternative": [
            "Suspend BitLocker before a planned firmware update to avoid the prompt entirely."
        ],
        "edge": [
            "Secure Boot toggled off is the real trigger; turning it back on restores the seal."
        ],
    },
    {
        "mode": "filevault_unlock",
        "diff": "hard",
        "desc": "FileVault volume needs recovery / won't unlock",
        "signal": "FileVault recovery key required",
        "os_only": ["macos"],
        "reason": [
            "FileVault unlock failure needs the recovery key or an enabled user — not a wipe.",
            "Use the recovery key / an authorized user to unlock, then verify status.",
            "Do not erase the volume to 'fix' the prompt.",
        ],
        "cmds": ["fdesetup status", "fdesetup list", "diskutil apfs unlockVolume <vol>"],
        "forbidden": [r"diskutil\s+eraseVolume", r"fdesetup\s+disable\s*#.*to avoid"],
        "success": _v("command_stdout", probe="fdesetup status", pattern="On"),
        "mistakes": [
            "Erase the APFS volume, destroying data.",
            "Not knowing which users are FileVault-enabled.",
        ],
        "hints": [
            "fdesetup list shows enabled users; the recovery key is the fallback.",
            "The institutional/personal recovery key unlocks without a user.",
        ],
        "reference": [
            "Identify an enabled user / recovery key",
            "Unlock the volume",
            "Confirm FileVault On",
        ],
        "alternative": [
            "Boot to Recovery and unlock the APFS volume there if the login window can't."
        ],
        "edge": ["An MDM-escrowed key exists even when the user forgot theirs."],
    },
]

BOOT_FAULTS = [
    {
        "mode": "fstab_boot_fail",
        "diff": "expert",
        "desc": "a bad fstab entry drops the system to emergency mode",
        "signal": "emergency mode / dependency failed for /mnt",
        "os_only": ["linux"],
        "reason": [
            "A failed mount at boot halts into emergency mode; the fstab entry is the suspect, not the kernel.",
            "Boot to a recovery shell, identify the offending entry, make it nofail or fix the device/UUID.",
            "Verify a clean boot; never leave a required mount that can hang boot indefinitely.",
        ],
        "cmds": ["journalctl -xb | grep -i mount", "cat /etc/fstab", "findmnt --verify"],
        "forbidden": [r">\s*/etc/fstab", r"rm\s+/etc/fstab"],
        "success": _v("command_succeeds", probe="findmnt --verify --verbose >/dev/null && echo ok"),
        "mistakes": [
            "Empty /etc/fstab to boot, losing all mount definitions.",
            "Use a device name that changes across boots instead of a UUID.",
        ],
        "hints": [
            "`findmnt --verify` validates fstab without rebooting.",
            "`nofail` lets boot proceed when a non-critical mount is absent.",
        ],
        "reference": [
            "Recovery shell",
            "Fix/annotate the fstab entry (UUID/nofail)",
            "Verify with findmnt --verify",
        ],
        "alternative": [
            "Use a systemd .mount unit with the right dependencies for a complex mount."
        ],
        "edge": ["The device is fine but the UUID changed after a reformat."],
    },
    {
        "mode": "bootloader",
        "diff": "principal",
        "desc": "the bootloader is broken after a kernel/disk change",
        "signal": "grub rescue / no bootable device / BOOTMGR missing",
        "reason": [
            "A broken bootloader is recoverable from install/rescue media without reinstalling the OS.",
            "Boot rescue media, mount the root, reinstall/repair the bootloader for the correct disk & firmware mode (BIOS/UEFI).",
            "Verify a clean boot and that the ESP/boot entry is correct.",
        ],
        "cmds": [
            "# boot rescue media",
            "mount /dev/<root> /mnt && for d in dev sys proc; do mount --bind /$d /mnt/$d; done",
            "chroot /mnt <reinstall-bootloader>",
        ],
        "forbidden": [r"dd\s+if=.*of=/dev/sd[a-z]\s*#.*guess", r"format.*system"],
        "success": _v("artifact", path="boot_repair_log.txt"),
        "mistakes": [
            "Install the bootloader to the wrong disk.",
            "Mix BIOS and UEFI install modes.",
        ],
        "hints": [
            "Match the firmware mode: UEFI needs the ESP; BIOS needs the MBR gap.",
            "chroot into the mounted system so tools see the right /boot and fstab.",
        ],
        "reference": [
            "Rescue media + chroot",
            "Reinstall bootloader for the right disk/firmware",
            "Verify a clean boot",
        ],
        "alternative": [
            "Boot the kernel directly from rescue media, then repair from the running system."
        ],
        "edge": ["Multiple disks: the firmware boots a different disk than you repaired."],
    },
]

UPGRADE_FAULTS = [
    {
        "mode": "rollback_after_upgrade",
        "diff": "expert",
        "desc": "a system/package upgrade broke a service; safe rollback needed",
        "signal": "service regressed after upgrade",
        "reason": [
            "A regression after upgrade needs a controlled rollback to a known-good version, not a forward hack.",
            "Identify exactly what changed, pin/downgrade the offending package to the prior version, hold it.",
            "Verify the service recovers and document the incompatibility.",
        ],
        "cmds": [
            {
                "linux": "grep -E 'upgrade|install' /var/log/dpkg.log | tail",
                "windows": "Get-WinEvent -LogName Setup -MaxEvents 50",
                "macos": "brew list --versions",
            }.get("linux", ""),
            "<downgrade to prior version>",
            "<hold/pin the package>",
        ],
        "forbidden": [r"rm\s+-rf\s+/var/cache.*&&.*reboot\s*#.*hope", r"--force.*downgrade.*\*"],
        "success": _v("artifact", path="rollback_report.txt"),
        "mistakes": [
            "Keep patching forward instead of rolling back to green.",
            "Downgrade one package but not its dependencies, leaving an inconsistent set.",
        ],
        "hints": [
            "The package log shows exactly which versions changed and when.",
            "Pin after downgrade so the next update doesn't re-break it.",
        ],
        "reference": [
            "Identify the changed versions",
            "Downgrade + pin the offender",
            "Verify recovery; document",
        ],
        "alternative": [
            "Restore from a pre-upgrade snapshot if the change set is too tangled to unwind."
        ],
        "edge": [
            "A config-file migration ran on upgrade; rolling back the binary needs the old config too."
        ],
    },
]

WSL_FAULTS = [
    {
        "mode": "wsl_no_network",
        "diff": "hard",
        "desc": "WSL2 distro has no network / DNS after a host change",
        "signal": "Temporary failure in name resolution inside WSL",
        "os_only": ["windows"],
        "reason": [
            "WSL2 networking rides a virtual switch + generated resolv.conf; a host VPN/firewall change often breaks it.",
            "Check whether resolv.conf is auto-generated and whether a host VPN changed routing/MTU.",
            "Fix at the right layer (wsl.conf generateResolvConf / mirrored networking / MTU), not by hardcoding blindly.",
        ],
        "cmds": ["wsl.exe --status", "cat /etc/resolv.conf", "wsl.exe --shutdown"],
        "forbidden": [
            r"chattr\s+\+i\s+/etc/resolv\.conf\s*#.*forever",
            r"rm\s+-rf\s+/etc/wsl\.conf",
        ],
        "success": _v("command_succeeds", probe="getent hosts example.com >/dev/null && echo ok"),
        "mistakes": [
            "Immutably pin a hardcoded resolv.conf, breaking on the next network change.",
            "Restart the whole PC instead of `wsl --shutdown`.",
        ],
        "hints": [
            "`wsl --shutdown` cleanly resets the WSL VM's networking.",
            "Mirrored networking mode (recent Windows) avoids many VPN/DNS issues.",
        ],
        "reference": [
            "Check WSL network mode + resolv.conf",
            "Fix wsl.conf / networking mode / MTU",
            "Verify resolution",
        ],
        "alternative": ["Switch WSL to mirrored networking so it shares the host stack directly."],
        "edge": [
            "A corporate VPN sets an MTU that fragments WSL traffic; lowering MTU fixes stalls."
        ],
    },
    {
        "mode": "wsl_interop",
        "diff": "medium",
        "desc": "Windows<->Linux path/interop breaks a script",
        "signal": "cannot execute binary / path not found across the boundary",
        "os_only": ["windows"],
        "reason": [
            "WSL interop translates paths and PATH; a script assuming one OS's paths breaks at the boundary.",
            "Use the correct path form (wslpath) and be explicit about which interpreter runs.",
            "Fix the path translation, not by disabling interop.",
        ],
        "cmds": [
            "wslpath -w /home/u/file",
            "wslpath -u 'C:\\\\Users'",
            "wsl.exe -e bash -lc 'echo $PATH'",
        ],
        "forbidden": [
            r"appendWindowsPath\s*=\s*false\s*#.*just to hide",
            r"/etc/wsl\.conf.*interop.*enabled\s*=\s*false",
        ],
        "success": _v("command_succeeds", probe="wslpath -w / >/dev/null && echo ok"),
        "mistakes": [
            "Hardcode C:\\ paths inside Linux tools.",
            "Disable interop, breaking legitimate cross-calls.",
        ],
        "hints": [
            "wslpath converts between /mnt/c and C:\\ forms.",
            "Windows PATH is appended inside WSL unless configured otherwise.",
        ],
        "reference": [
            "Translate paths with wslpath",
            "Be explicit about the interpreter",
            "Verify the cross-call",
        ],
        "alternative": [
            "Keep the project entirely inside the Linux filesystem to avoid boundary crossings."
        ],
        "edge": ["Files under /mnt/c have Windows line endings/permissions that trip Linux tools."],
    },
]

GPU_FAULTS = [
    {
        "mode": "cuda_mismatch",
        "diff": "expert",
        "desc": "CUDA app fails: driver/toolkit/runtime version mismatch",
        "signal": "CUDA driver version is insufficient for CUDA runtime version",
        "reason": [
            "This error is a strict driver-vs-runtime compatibility gap, not an app bug.",
            "Read the installed driver and the runtime the app links; consult the compatibility matrix.",
            "Align them (upgrade driver or pin a compatible runtime); verify with a device query.",
        ],
        "cmds": [
            "nvidia-smi",
            "nvcc --version",
            {
                "linux": "cat /proc/driver/nvidia/version",
                "windows": "nvidia-smi -q | findstr Driver",
                "macos": "# NVIDIA CUDA unsupported on modern macOS",
            }.get("linux", ""),
        ],
        "forbidden": [r"LD_PRELOAD=.*libcuda\s*#.*fake", r"--allow-unsupported-driver\s*#.*blind"],
        "success": _v("command_succeeds", probe="nvidia-smi -L >/dev/null && echo ok"),
        "mistakes": [
            "Force an unsupported driver override.",
            "Upgrade the toolkit but not the driver (or vice versa).",
        ],
        "hints": [
            "nvidia-smi shows the max CUDA the driver supports.",
            "The runtime the app ships must be <= the driver's supported CUDA.",
        ],
        "reference": [
            "Read driver + runtime versions",
            "Align to the compatibility matrix",
            "Verify with a device query",
        ],
        "alternative": [
            "Use a CUDA container whose runtime matches the host driver, decoupling app from host toolkit."
        ],
        "edge": [
            "ROCm/AMD path is entirely different; the same symptom needs the ROCm stack, not CUDA."
        ],
    },
]

USERS_FAULTS = [
    {
        "mode": "locked_account",
        "diff": "medium",
        "desc": "a user cannot log in (locked/expired/no shell)",
        "signal": "account locked / password expired / this account is currently not available",
        "os_only": ["linux", "macos"],
        "reason": [
            "Login denial has distinct causes: locked password, expired account, nologin shell, or PAM.",
            "Inspect the account's status fields (passwd/shadow/chage) to find WHICH.",
            "Unlock/renew the specific attribute; do not grant more than needed.",
        ],
        "cmds": ["getent passwd <u>", "chage -l <u>", "passwd -S <u>"],
        "forbidden": [
            r"usermod\s+-s\s+/bin/bash\s+.*#.*blind",
            r"passwd\s+-d\s+<u>\s*#.*remove password",
        ],
        "success": _v("command_stdout", probe="passwd -S <u>", pattern="P "),
        "mistakes": [
            "Delete the password to 'unlock' (creates a passwordless account).",
            "Give a system account an interactive shell it shouldn't have.",
        ],
        "hints": [
            "passwd -S / chage -l show lock and expiry state precisely.",
            "/sbin/nologin as the shell blocks interactive login by design.",
        ],
        "reference": [
            "Inspect account status",
            "Fix the specific attribute (unlock/renew/shell)",
            "Verify a login",
        ],
        "alternative": [
            "For a service account, prefer key-based access over enabling password login."
        ],
        "edge": ["The account is fine but a PAM module (faillock) blocks after failed attempts."],
    },
]

LVM_FAULTS = [
    {
        "mode": "lv_extend",
        "diff": "hard",
        "desc": "a filesystem is full but the volume group has free extents",
        "signal": "df full while VG has free PE",
        "os_only": ["linux"],
        "reason": [
            "Full FS + free VG space = grow the LV and the filesystem online, no data move needed.",
            "Confirm free extents in the VG, extend the LV, then grow the filesystem to match.",
            "Verify the new size and that it survives remount.",
        ],
        "cmds": [
            "vgs; lvs; df -h",
            "lvextend -l +100%FREE <lv>",
            "resize2fs <lv>  # or xfs_growfs <mnt>",
        ],
        "forbidden": [r"mkfs.*<lv>", r"lvreduce\s*#.*to fix full"],
        "success": _v("command_succeeds", probe="df -h <mnt> | tail -1 && echo ok"),
        "mistakes": [
            "lvreduce a full volume (data loss).",
            "Extend the LV but forget to grow the filesystem, so df is unchanged.",
        ],
        "hints": [
            "ext4 uses resize2fs; xfs uses xfs_growfs and cannot shrink.",
            "vgs shows free PE available to extend into.",
        ],
        "reference": [
            "Confirm free VG extents",
            "lvextend then grow the FS",
            "Verify the new size",
        ],
        "alternative": ["Add a new PV to the VG first if there are no free extents."],
        "edge": ["xfs can only grow, never shrink — plan accordingly."],
    },
]

PROXY_FAULTS = [
    {
        "mode": "upstream_502",
        "diff": "hard",
        "desc": "reverse proxy returns 502/504 for a healthy backend",
        "signal": "502 Bad Gateway / upstream timed out",
        "reason": [
            "A 502/504 with a healthy backend is a proxy<->upstream problem: address, timeout, or protocol.",
            "Verify the proxy can reach the upstream (right host/port/socket) and the timeouts fit the backend.",
            "Fix the upstream definition/timeout; confirm end-to-end through the proxy.",
        ],
        "cmds": [
            "curl -sv http://127.0.0.1:<backend>/health",
            "nginx -T | grep -A3 upstream",
            "tail -f /var/log/nginx/error.log",
        ],
        "forbidden": [r"proxy_read_timeout\s+1d\s*#.*mask", r"ssl_verify\s+off\s*#.*to upstream"],
        "success": _v("http_ok", url="http://127.0.0.1/health"),
        "mistakes": [
            "Crank timeouts to hide a slow/broken upstream.",
            "Point the proxy at the wrong port or a stale socket path.",
        ],
        "hints": [
            "Curl the backend directly to prove it's healthy, then the proxy path.",
            "The proxy error log names the exact upstream failure.",
        ],
        "reference": [
            "Prove backend health directly",
            "Fix upstream address/timeout/protocol",
            "Verify through the proxy",
        ],
        "alternative": [
            "Add an active health check so the proxy ejects a bad upstream instead of 502-ing."
        ],
        "edge": ["The backend listens on IPv6/socket while the upstream config uses IPv4:port."],
    },
]

CLOUD_FAULTS = [
    {
        "mode": "cli_auth",
        "diff": "medium",
        "desc": "cloud CLI auth/credentials expired or wrong profile",
        "signal": "ExpiredToken / could not find credentials / wrong account",
        "reason": [
            "A cloud CLI failure is usually auth: expired token, wrong profile, or missing region.",
            "Identify the active identity/profile/region; refresh or select the correct one.",
            "Fix the credential source (SSO/refresh), not by embedding long-lived keys in scripts.",
        ],
        "cmds": [
            "aws sts get-caller-identity || az account show || gcloud auth list",
            "echo $AWS_PROFILE; aws configure list",
            "aws sso login || gcloud auth login",
        ],
        "forbidden": [r"aws_access_key_id\s*=\s*AKIA.*#.*hardcode in repo", r"--no-verify-ssl"],
        "success": _v(
            "command_succeeds",
            probe="aws sts get-caller-identity >/dev/null 2>&1 || az account show >/dev/null 2>&1; echo done",
        ),
        "mistakes": [
            "Hardcode long-lived keys into a script/repo.",
            "Operate against the wrong account/region without noticing.",
        ],
        "hints": [
            "get-caller-identity / account show reveal WHO you are before you act.",
            "Profiles + region are the usual mismatch.",
        ],
        "reference": [
            "Confirm active identity/profile/region",
            "Refresh/select correct credentials",
            "Re-verify identity",
        ],
        "alternative": ["Use short-lived SSO/OIDC federation instead of static keys."],
        "edge": ["Assumed-role session expired mid-task; re-assume rather than re-login."],
    },
]

SECRETS_FAULTS = [
    {
        "mode": "leaked_secret",
        "diff": "expert",
        "desc": "a secret was committed/exposed and must be rotated + purged",
        "signal": "secret found in git history / logs",
        "reason": [
            "An exposed secret is compromised the moment it's exposed — ROTATE first, then purge history.",
            "Rotate the credential at the source so the leaked value is worthless, then remove it from history/logs.",
            "Add prevention (pre-commit scanning, secret manager) so it can't recur.",
        ],
        "cmds": [
            "<rotate the credential at its provider>",
            "git log -p -S '<fragment>' | head",
            "<purge from history: filter-repo> ; <invalidate old value>",
        ],
        "forbidden": [
            r"git\s+commit.*#.*just delete the file",
            r"chmod\s+600.*#.*and call it done",
        ],
        "success": _v("artifact", path="secret_rotation_report.txt"),
        "mistakes": [
            "Delete the file in a new commit and think the secret is safe (it's in history).",
            "Purge history but never rotate the still-valid credential.",
        ],
        "hints": [
            "Rotation makes the leaked value useless — that's the real fix.",
            "History rewrite alone doesn't help if the value still works and was already cloned.",
        ],
        "reference": [
            "Rotate the credential first",
            "Purge from history/logs",
            "Add scanning + a secret manager",
        ],
        "alternative": [
            "Move the secret into a managed vault and inject at runtime so it never touches the repo."
        ],
        "edge": [
            "The secret is also in CI logs and forks — rotation is the only reliable containment."
        ],
    },
]

MONITORING_FAULTS = [
    {
        "mode": "exporter_down",
        "diff": "medium",
        "desc": "Prometheus target is DOWN though the node is up",
        "signal": "target DOWN / context deadline exceeded scraping :9100",
        "reason": [
            "A DOWN target with a live node is a scrape-path issue: exporter, port, firewall, or relabel.",
            "Curl the exporter endpoint from the Prometheus host to localize the break.",
            "Fix the specific hop (start exporter / open port / correct target) and confirm it scrapes.",
        ],
        "cmds": [
            "curl -s http://<node>:9100/metrics | head",
            "systemctl status node_exporter",
            "promtool check config /etc/prometheus/prometheus.yml",
        ],
        "forbidden": [
            r"scrape_interval:\s*1s\s*#.*hammer",
            r"tls_config.*insecure_skip_verify:\s*true\s*#.*blind",
        ],
        "success": _v("http_ok", url="http://<node>:9100/metrics"),
        "mistakes": [
            "Assume the app is down when only the exporter/scrape path is broken.",
            "Fix the config but never reload Prometheus.",
        ],
        "hints": [
            "Curl the exporter from the Prometheus host — that's the exact scrape path.",
            "promtool validates the config before you reload.",
        ],
        "reference": [
            "Curl the exporter from Prometheus",
            "Fix the broken hop",
            "Confirm the target is UP",
        ],
        "alternative": [
            "Use blackbox exporter probing if you need to monitor from Prometheus' vantage point."
        ],
        "edge": [
            "The exporter binds localhost only; Prometheus scrapes it from another host and times out."
        ],
    },
]


# Register each area as its own family (keeps provenance + coverage auditable).
@register("containers", ["linux", "windows", "macos"])
def containers():
    yield from _drive(
        "containers",
        "containers",
        ["linux", "windows", "macos"],
        "docker",
        CONTAINER_FAULTS,
        "Il container/servizio {resource} ha un problema: {desc}. Ripristina lo stato desiderato risolvendo la causa.",
        "On {os}, a {resource} workload is broken: {desc}. Diagnostics show '{signal}'.",
    )


@register("databases", ["linux", "windows", "macos"])
def databases():
    yield from _drive(
        "databases",
        "databases",
        ["linux", "windows", "macos"],
        "postgresql",
        DB_FAULTS,
        "Il database ha un problema: {desc}. Ripristina il servizio senza compromettere dati o sicurezza.",
        "On {os}, a database is affected: {desc}. Symptom: '{signal}'.",
    )


@register("performance", ["linux", "windows", "macos"])
def performance():
    yield from _drive(
        "performance",
        "performance",
        ["linux"],
        "host",
        PERF_FAULTS,
        "Il sistema ha un problema di performance: {desc}. Trova la causa e stabilizza il sistema.",
        "On {os}, a performance incident: {desc}. Symptom: '{signal}'.",
    )


@register("logs", ["linux", "windows", "macos"])
def logs():
    yield from _drive(
        "logs",
        "logs",
        ["linux", "windows", "macos"],
        "journald",
        LOG_FAULTS,
        "Problema di logging/diagnostica: {desc}. Estrai il segnale e risolvi la causa.",
        "On {os}, a logging/diagnosis task: {desc}. Symptom: '{signal}'.",
    )


@register("scheduler", ["linux", "windows", "macos"])
def scheduler():
    yield from _drive(
        "scheduler",
        "scheduler",
        ["linux", "windows", "macos"],
        "scheduler",
        CRON_FAULTS,
        "Un job schedulato ha un problema: {desc}. Fallo eseguire correttamente risolvendo la causa.",
        "On {os}, a scheduled job problem: {desc}. Symptom: '{signal}'.",
    )


@register("env_path", ["linux", "windows", "macos"])
def env_path():
    yield from _drive(
        "env_path",
        "env_path",
        ["linux", "windows", "macos"],
        "shell-env",
        ENV_FAULTS,
        "Problema di ambiente/PATH: {desc}. Ripristina un ambiente shell corretto.",
        "On {os}, an environment/PATH problem: {desc}. Symptom: '{signal}'.",
    )


@register("backup", ["linux", "windows", "macos"])
def backup():
    yield from _drive(
        "backup",
        "backup",
        ["linux", "windows", "macos"],
        "backup",
        BACKUP_FAULTS,
        "Backup/DR: {desc}. Garantisci ripristinabilita' e continuita' verificate.",
        "On {os}, a backup/recovery task: {desc}. Context: '{signal}'.",
    )


@register("security_mac", ["linux", "windows", "macos"])
def security_mac():
    yield from _drive(
        "security_mac",
        "selinux_apparmor",
        ["linux", "windows", "macos"],
        "mac-policy",
        SECURITY_MAC_FAULTS,
        "Sicurezza (MAC/AV): {desc}. Consenti l'azione legittima senza indebolire la protezione.",
        "On {os}, a security-control task: {desc}. Symptom: '{signal}'.",
    )


@register("git", ["linux", "windows", "macos"])
def git_area():
    yield from _drive(
        "git",
        "git",
        ["linux", "windows", "macos"],
        "git",
        GIT_FAULTS,
        "Problema Git: {desc}. Ripristina il repository senza perdere lavoro/cronologia.",
        "On {os}, a git problem: {desc}. Symptom: '{signal}'.",
    )


@register("iac", ["linux", "windows", "macos"])
def iac():
    yield from _drive(
        "iac",
        "iac",
        ["linux", "windows", "macos"],
        "iac",
        IAC_FAULTS,
        "Infrastructure-as-Code: {desc}. Ripristina uno stato coerente e riproducibile.",
        "On {os}, an IaC problem: {desc}. Symptom: '{signal}'.",
    )


@register("filesharing", ["linux", "windows", "macos"])
def filesharing():
    yield from _drive(
        "filesharing",
        "filesharing",
        ["linux", "windows", "macos"],
        "fileshare",
        FILESHARE_FAULTS,
        "File sharing (NFS/SMB): {desc}. Ripristina l'accesso in modo sicuro.",
        "On {os}, a file-sharing problem: {desc}. Symptom: '{signal}'.",
    )


@register("virtualization", ["linux", "windows", "macos"])
def virtualization():
    yield from _drive(
        "virtualization",
        "virtualization",
        ["linux", "windows", "macos"],
        "hypervisor",
        VIRT_FAULTS,
        "Virtualizzazione: {desc}. Rendi avviabile la VM risolvendo la causa a livello host.",
        "On {os}, a virtualization problem: {desc}. Symptom: '{signal}'.",
    )


@register("remote_access", ["linux", "windows", "macos"])
def remote_access():
    yield from _drive(
        "remote_access",
        "remote_access",
        ["linux", "windows", "macos"],
        "vpn",
        REMOTE_FAULTS,
        "Accesso remoto/VPN: {desc}. Ripristina la connettivita' senza rompere il resto della rete.",
        "On {os}, a remote-access/VPN problem: {desc}. Symptom: '{signal}'.",
    )


@register("kernel", ["linux"])
def kernel_area():
    yield from _drive(
        "kernel",
        "kernel",
        ["linux"],
        "kernel-module",
        KERNEL_FAULTS,
        "Kernel/moduli: {desc}. Carica il modulo correttamente senza indebolire Secure Boot.",
        "On {os}, a kernel/module problem: {desc}. Symptom: '{signal}'.",
    )


@register("encryption", ["linux", "windows", "macos"])
def encryption():
    yield from _drive(
        "encryption",
        "encryption",
        ["linux", "windows", "macos"],
        "disk-encryption",
        ENCRYPTION_FAULTS,
        "Cifratura disco: {desc}. Sblocca/ripristina il volume senza perdere dati.",
        "On {os}, a disk-encryption problem: {desc}. Symptom: '{signal}'.",
    )


@register("boot", ["linux", "windows", "macos"])
def boot_area():
    yield from _drive(
        "boot",
        "boot",
        ["linux"],
        "boot",
        BOOT_FAULTS,
        "Avvio di sistema: {desc}. Ripristina un boot pulito senza reinstallare.",
        "On {os}, a boot failure: {desc}. Symptom: '{signal}'.",
    )


@register("upgrade", ["linux", "windows", "macos"])
def upgrade_area():
    yield from _drive(
        "upgrade",
        "upgrade",
        ["linux", "windows", "macos"],
        "upgrade",
        UPGRADE_FAULTS,
        "Upgrade/rollback: {desc}. Torna a uno stato sano in modo controllato.",
        "On {os}, an upgrade regression: {desc}. Symptom: '{signal}'.",
    )


@register("wsl", ["windows"])
def wsl_area():
    yield from _drive(
        "wsl",
        "wsl",
        ["windows"],
        "wsl",
        WSL_FAULTS,
        "WSL: {desc}. Ripristina il funzionamento del sottosistema Linux.",
        "On {os}, a WSL problem: {desc}. Symptom: '{signal}'.",
    )


@register("gpu", ["linux", "windows"])
def gpu_area():
    yield from _drive(
        "gpu",
        "gpu",
        ["linux", "windows"],
        "gpu",
        GPU_FAULTS,
        "GPU/CUDA: {desc}. Allinea driver e runtime senza override non supportati.",
        "On {os}, a GPU/compute problem: {desc}. Symptom: '{signal}'.",
    )


@register("users_groups", ["linux", "macos"])
def users_groups():
    yield from _drive(
        "users_groups",
        "users",
        ["linux", "macos"],
        "account",
        USERS_FAULTS,
        "Account utente: {desc}. Ripristina l'accesso con privilegi minimi.",
        "On {os}, a user-account problem: {desc}. Symptom: '{signal}'.",
    )


@register("lvm_raid", ["linux"])
def lvm_raid():
    yield from _drive(
        "lvm_raid",
        "lvm_raid",
        ["linux"],
        "lvm",
        LVM_FAULTS,
        "LVM/RAID: {desc}. Recupera capacita'/ridondanza senza perdere dati.",
        "On {os}, an LVM/RAID problem: {desc}. Symptom: '{signal}'.",
    )


@register("proxy", ["linux", "windows", "macos"])
def proxy_area():
    yield from _drive(
        "proxy",
        "proxy",
        ["linux", "windows", "macos"],
        "reverse-proxy",
        PROXY_FAULTS,
        "Reverse proxy: {desc}. Ripristina il flusso verso il backend senza mascherare la causa.",
        "On {os}, a reverse-proxy problem: {desc}. Symptom: '{signal}'.",
    )


@register("cloud", ["linux", "windows", "macos"])
def cloud_area():
    yield from _drive(
        "cloud",
        "cloud",
        ["linux", "windows", "macos"],
        "cloud-cli",
        CLOUD_FAULTS,
        "Cloud CLI: {desc}. Ripristina l'accesso corretto senza credenziali long-lived nel codice.",
        "On {os}, a cloud-CLI problem: {desc}. Symptom: '{signal}'.",
    )


@register("secrets", ["linux", "windows", "macos"])
def secrets_area():
    yield from _drive(
        "secrets",
        "secrets",
        ["linux", "windows", "macos"],
        "secret",
        SECRETS_FAULTS,
        "Gestione segreti: {desc}. Contieni l'esposizione (ruota prima, poi ripulisci).",
        "On {os}, a secret-exposure problem: {desc}. Symptom: '{signal}'.",
    )


@register("monitoring", ["linux", "windows", "macos"])
def monitoring_area():
    yield from _drive(
        "monitoring",
        "monitoring",
        ["linux", "windows", "macos"],
        "prometheus",
        MONITORING_FAULTS,
        "Monitoring: {desc}. Ripristina la raccolta metriche risolvendo il vero hop rotto.",
        "On {os}, a monitoring problem: {desc}. Symptom: '{signal}'.",
    )
