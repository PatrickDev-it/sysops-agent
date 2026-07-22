"""
Families, part 5: generic cross-OS HARD and EXPERT task families.

These are real senior/expert sysops scenarios framed so they apply on every OS
(the underlying reasoning is OS-independent; the concrete tooling differs per OS,
which the agent must know). They exist to give every OS broad, distinct coverage
at the hard/expert tiers rather than concentrating difficulty in Linux-only areas.

Driven by compact scenario data; the driver expands each across the OS list with
fully-populated fields.
"""

from __future__ import annotations

from ..shared.model import Verify
from .engine import build_case, register


def _task(
    os: str,
    domain: str,
    diff: str,
    short: str,
    goal: str,
    scenario: str,
    reasoning: list[str],
    cmds: list[str],
    forbidden: list[str],
    safety: list[str],
    success_criteria: str,
    success: Verify,
    recovery: str,
    mistakes: list[str],
    hints: list[str],
    reference: list[str],
    alternative: list[str],
    edge: list[str],
    gt: dict,
    tags: list[str],
    family: str,
    risk: str = "RECOVERABLE",
):
    return build_case(
        os=os,
        domain=domain,
        difficulty=diff,
        title=f"{os}: {short}",
        goal=goal,
        scenario=scenario,
        environment={"os": os, "domain": domain, **gt},
        initial_state=[f"# fixture: {os} host prepared for '{short}'"],
        expected_reasoning=reasoning,
        expected_commands=cmds,
        forbidden_commands=forbidden,
        safety_constraints=safety,
        success_criteria=success_criteria,
        failure_criteria="The objective is not genuinely met, or it was met by masking the problem, "
        "weakening security, or an irreversible shortcut.",
        success_check=success,
        recovery_strategy=recovery,
        ground_truth=gt,
        possible_mistakes=mistakes,
        hints=hints,
        reference_solution=reference,
        alternative_solution=alternative,
        edge_cases=edge,
        risk=risk,
        tags=tags,
        family=family,
    )


# (domain, short, goal_it, reasoning[], mistakes[], hints[], reference[], alternative[], edge[], tags[])
HARD_TASKS = [
    (
        "networking",
        "diagnose intermittent packet loss to one host",
        "Diagnostica una perdita di pacchetti intermittente verso un solo host e individua l'hop responsabile.",
        [
            "Intermittent loss to ONE host localizes the fault to a path segment, not the whole network.",
            "Use a hop-by-hop latency/loss tool over time to find where loss appears.",
            "Correlate with duplex/MTU/queue drops at that hop before concluding.",
        ],
        [
            "Blame the application for a network-layer loss.",
            "Run one ping and declare it fine/broken.",
        ],
        [
            "mtr/pathping over time beats a single ping.",
            "Loss that starts at a hop and persists downstream points at that hop.",
        ],
        [
            "Measure hop-by-hop loss over time",
            "Localize the hop",
            "Correlate with MTU/duplex/queue at that hop",
        ],
        ["Capture a packet trace at both ends to prove where drops occur."],
        ["Asymmetric routing makes the return path the real culprit."],
        ["net", "packetloss", "mtr"],
    ),
    (
        "processes",
        "trace a process stuck in uninterruptible sleep (D state)",
        "Un processo e' bloccato in stato D (uninterruptible sleep) e non risponde a kill. Trova la risorsa su cui e' bloccato.",
        [
            "D-state means the process waits on the kernel (usually IO/NFS) and can't be killed normally — killing is not the fix.",
            "Find WHAT it waits on (kernel stack / wchan / the mount or device).",
            "Fix the underlying blocker (revive the mount/device); the process unblocks itself.",
        ],
        [
            "kill -9 a D-state process expecting it to die.",
            "Reboot before finding the blocked resource.",
        ],
        [
            "/proc/<pid>/stack and wchan reveal the kernel wait.",
            "A hung NFS/blocked device is the classic cause.",
        ],
        [
            "Read the kernel wait (stack/wchan)",
            "Identify the blocking resource",
            "Restore it so the process unblocks",
        ],
        [
            "If the device is truly dead, a controlled reboot may be the only exit — after evidence capture."
        ],
        ["The process is fine; a dying disk is the real incident."],
        ["proc", "dstate", "io"],
    ),
    (
        "filesystem",
        "recover space from a large deleted-but-open file",
        "Il disco e' pieno ma 'du' non trova nulla: un file grande e' stato cancellato ma resta aperto da un processo. Recupera lo spazio senza perdere dati vivi.",
        [
            "df vs du mismatch = space held by a deleted-but-still-open file.",
            "Identify the holding process and whether the data is still needed.",
            "Reclaim by truncating via /proc/<pid>/fd or restarting the holder — never by deleting live data.",
        ],
        [
            "Delete random large files to free space.",
            "Miss that only restarting the holder frees the blocks.",
        ],
        [
            "lsof +L1 lists deleted-but-open files and their holders.",
            "Truncating the fd frees space without killing the process.",
        ],
        [
            "Find the holder with lsof +L1",
            "Decide truncate-fd vs restart",
            "Verify space is reclaimed",
        ],
        ["Rotate the writer's logging so it reopens a fresh file."],
        ["The holder is a critical daemon; restart timing matters."],
        ["fs", "lsof", "diskspace"],
    ),
    (
        "packages",
        "resolve a dependency conflict between two required packages",
        "Due pacchetti richiesti dipendono da versioni incompatibili di una stessa libreria. Trova una risoluzione che soddisfi entrambi senza rompere il sistema.",
        [
            "A version conflict needs a resolution that satisfies BOTH, not a forced install of one.",
            "Map the exact conflicting constraint from the resolver output.",
            "Find a compatible version set, or isolate one consumer (container/venv) — never force-break the graph.",
        ],
        [
            "--force one package, breaking the other.",
            "Remove a shared library other packages need.",
        ],
        [
            "The resolver output names the exact conflicting constraint.",
            "Isolation (container/venv) sidesteps a true incompatibility.",
        ],
        [
            "Read the conflict",
            "Find a compatible set or isolate a consumer",
            "Verify both work + DB consistent",
        ],
        ["Containerize one consumer so the two never share the library."],
        ["A transitive dependency, not the direct one, is the real conflict."],
        ["packages", "depconflict"],
    ),
    (
        "networking",
        "fix asymmetric MTU causing large transfers to hang",
        "I trasferimenti piccoli funzionano ma quelli grandi si bloccano (PMTU black hole). Individua e correggi il problema di MTU/MSS.",
        [
            "Small OK + large hangs = a path-MTU black hole (ICMP fragmentation-needed dropped).",
            "Probe the effective path MTU and where large packets die.",
            "Fix MTU/MSS clamping at the right hop; don't just lower MTU everywhere blindly.",
        ],
        [
            "Blame the application for a slow/hung transfer.",
            "Set MTU 1500 everywhere without measuring the path.",
        ],
        [
            "ping with DF and increasing size finds the black-hole size.",
            "MSS clamping fixes tunneled paths.",
        ],
        [
            "Probe path MTU with DF",
            "Clamp MSS / set correct MTU at the hop",
            "Verify large transfers complete",
        ],
        ["Enable PMTUD correctly by allowing the needed ICMP type."],
        ["A VPN/tunnel overhead is what shrinks the usable MTU."],
        ["net", "mtu", "pmtud"],
    ),
    (
        "services",
        "eliminate a start-up race between two dependent services",
        "Un servizio parte a volte si', a volte no, a seconda dell'ordine con un altro servizio (race non deterministica). Rendi l'avvio deterministico.",
        [
            "Nondeterministic start = an unexpressed ordering/readiness dependency, a race.",
            "Identify the real readiness condition (port open / socket / health), not just 'process started'.",
            "Express the dependency as readiness (socket activation / wait-for) so ordering is deterministic.",
        ],
        ["Add a fixed sleep and call it fixed.", "Assume 'started' means 'ready'."],
        [
            "A sleep is a race with a timer, not a fix.",
            "Socket activation removes ordering guesswork.",
        ],
        [
            "Find the true readiness condition",
            "Express it (socket/wait-for/After+condition)",
            "Prove determinism over repeated boots",
        ],
        ["Use a health-gated proxy so dependents only connect when ready."],
        ["The dependency is ready-ish but not fully warmed, so it flaps."],
        ["services", "race", "ordering"],
    ),
    (
        "logs",
        "reconstruct an incident timeline from unsynchronized logs",
        "Ricostruisci la timeline di un incidente da log di piu' host con orologi non sincronizzati.",
        [
            "Unsynced clocks make raw timestamps unreliable — normalize before correlating.",
            "Establish per-host offsets (from a common event / NTP records) and shift to a common timeline.",
            "Order the normalized events to find the true first cause.",
        ],
        [
            "Correlate raw timestamps across skewed hosts and draw wrong causality.",
            "Ignore timezone/DST differences.",
        ],
        [
            "Anchor on an event visible in multiple logs to compute offsets.",
            "Normalize everything to UTC.",
        ],
        [
            "Compute per-host clock offsets",
            "Normalize to a common timeline",
            "Order events; identify the first cause",
        ],
        ["Ingest into a store that records ingestion time as a secondary anchor."],
        ["A host's clock jumped mid-incident, splitting its own timeline."],
        ["logs", "timeline", "clockskew"],
    ),
    (
        "security",
        "audit and tighten an over-permissioned service account",
        "Un service account ha privilegi troppo ampi. Riducilo al minimo necessario senza interrompere il servizio.",
        [
            "Least privilege requires knowing what the account ACTUALLY uses before removing grants.",
            "Observe the account's real accesses (audit) to build the minimal required set.",
            "Reduce to that set incrementally, verifying the service after each cut.",
        ],
        ["Strip permissions blindly and break the service.", "Leave it broad because 'it works'."],
        [
            "Audit real usage before cutting.",
            "Cut incrementally with verification, not all at once.",
        ],
        [
            "Audit actual accesses",
            "Derive the minimal set",
            "Reduce incrementally + verify service each step",
        ],
        ["Move to a role/scoped token with only the observed permissions."],
        ["A rarely-used but critical permission only appears in a monthly job."],
        ["security", "leastprivilege", "audit"],
    ),
    (
        "storage",
        "safely resize a partition that is nearly full",
        "Ridimensiona una partizione quasi piena per un volume adiacente con spazio libero, senza perdita dati.",
        [
            "Partition resizing is destructive if mis-ordered — back up / snapshot first.",
            "Resize in the correct order (unmount/quiesce, resize partition, then filesystem, or grow-online where supported).",
            "Verify the new size and integrity before returning to service.",
        ],
        [
            "Resize the filesystem before/after the partition in the wrong order.",
            "Skip the backup on a destructive op.",
        ],
        [
            "Order matters: shrink FS before partition, grow partition before FS.",
            "Snapshot first on anything destructive.",
        ],
        ["Snapshot/backup", "Resize in the correct order", "Verify size + integrity"],
        ["Use LVM/APFS elasticity to avoid a raw partition resize entirely."],
        ["Grow-online works for some FS; others need the volume offline."],
        ["storage", "resize", "partition"],
    ),
    (
        "dns",
        "fix a wildcard/CNAME chain that resolves inconsistently",
        "Una catena CNAME/wildcard risolve in modo incoerente per alcuni nomi. Traccia la catena e correggi il record errato.",
        [
            "Inconsistent resolution in a CNAME/wildcard setup is a chain problem — trace it end to end.",
            "Follow each CNAME hop and the wildcard precedence to find the wrong link.",
            "Fix the specific record; verify the whole chain resolves consistently.",
        ],
        [
            "Fix the leaf while a mid-chain CNAME stays wrong.",
            "Assume the wildcard covers a name it doesn't.",
        ],
        [
            "dig +trace follows the full delegation/chain.",
            "An explicit record beats a wildcard at the same name.",
        ],
        [
            "Trace the CNAME/wildcard chain",
            "Fix the wrong link",
            "Verify consistent resolution end to end",
        ],
        ["Flatten a fragile CNAME chain to direct records where possible."],
        ["A CNAME at the zone apex is invalid and behaves oddly."],
        ["dns", "cname", "wildcard"],
    ),
    (
        "containers",
        "shrink a bloated image and fix a broken layer cache",
        "Un'immagine container e' enorme e la cache dei layer non funziona, rallentando ogni build. Riduci la dimensione e ripristina la cache.",
        [
            "Image bloat + cache misses come from build order and layer hygiene, not the base image alone.",
            "Analyze layer sizes and cache invalidation points; reorder so stable layers precede volatile ones.",
            "Use multi-stage / cleanup within a layer; verify size drop and cache hits.",
        ],
        [
            "Add a bigger disk instead of fixing the image.",
            "Delete files in a later layer (space stays in the earlier one).",
        ],
        [
            "A cleanup in a later layer doesn't shrink earlier layers.",
            "Order Dockerfile so dependencies cache before code.",
        ],
        [
            "Analyze layers + cache breaks",
            "Reorder + multi-stage + in-layer cleanup",
            "Verify size + cache hits",
        ],
        ["Use a distroless/minimal base and copy only artifacts in."],
        ["A secret baked into an early layer persists even if deleted later."],
        ["containers", "image", "cache"],
    ),
    (
        "performance",
        "tune a service hitting connection/thread pool exhaustion",
        "Un servizio esaurisce il pool di connessioni/thread sotto carico normale. Trova se e' un leak o un dimensionamento e correggi.",
        [
            "Pool exhaustion is a leak or an undersizing — measure which before changing numbers.",
            "Instrument pool usage and lifetimes; look for connections/threads not returned.",
            "Fix the leak or size to measured concurrency; verify headroom under load.",
        ],
        ["Just increase the pool size and mask a leak.", "Assume it's load when it's a leak."],
        [
            "Track checkout/return of pool objects to spot leaks.",
            "Size to measured concurrency, not a guess.",
        ],
        ["Instrument pool usage", "Fix leak or right-size", "Verify under representative load"],
        ["Add a timeout/reaper so leaked objects are reclaimed as defense-in-depth."],
        ["An external dependency's slowness holds pool objects longer, mimicking a leak."],
        ["perf", "pool", "concurrency"],
    ),
    (
        "remote_access",
        "fix a bastion/jump-host chain that drops long sessions",
        "Le sessioni via bastion cadono dopo qualche minuto di inattivita'. Diagnostica keepalive/timeout lungo la catena e rendi le sessioni stabili.",
        [
            "Idle-drop points at a keepalive/timeout somewhere in the chain (client, bastion, target, or a NAT).",
            "Identify which hop times out (NAT idle, ClientAlive, firewall) via the drop pattern.",
            "Set keepalives at the right layer; don't just crank one side.",
        ],
        [
            "Blame the target when a NAT idle timeout is the cause.",
            "Set an aggressive keepalive that hides the real timeout.",
        ],
        [
            "The drop interval hints at which timeout fires.",
            "ServerAlive/ClientAlive vs NAT idle are different layers.",
        ],
        [
            "Identify the timing/hop of the drop",
            "Set keepalive at the right layer",
            "Verify a long idle session survives",
        ],
        ["Use a session multiplexer (mosh/tmux) so a drop doesn't lose work."],
        ["A corporate NAT with a short UDP/TCP idle is the hidden culprit."],
        ["ssh", "bastion", "keepalive"],
    ),
    (
        "firewall",
        "reconcile host firewall with an upstream security group",
        "Un servizio e' irraggiungibile: sia il firewall host sia un security-group upstream filtrano. Apri il percorso completo in modo mirato senza spalancare nulla.",
        [
            "Two filtering layers mean local success can still be blocked upstream — check BOTH.",
            "Confirm the service listens, then verify each filtering layer allows the exact port/source.",
            "Open the specific path at both layers with least scope; verify end to end from a real client.",
        ],
        [
            "Fix only the host firewall and miss the upstream group.",
            "Open any->any at one layer to 'rule it out'.",
        ],
        [
            "Reachability needs every hop to allow it.",
            "Scope both layers to the exact port/source.",
        ],
        [
            "Confirm listen",
            "Allow the exact path at host + upstream layer",
            "Verify from a real remote client",
        ],
        ["Model the full path (client->SG->host fw->service) before changing anything."],
        ["The host is fine; only the upstream group blocks — or vice versa."],
        ["firewall", "securitygroup", "layers"],
    ),
    (
        "git",
        "recover a repository after a bad force-push",
        "Un force-push errato ha sovrascritto branch condivisi. Recupera lo stato perduto e ripristina i branch senza perdere il lavoro altrui.",
        [
            "A force-push overwrites refs but the old commits usually still exist (reflog / other clones).",
            "Recover the lost tip from the reflog or a teammate's clone; re-point the branch.",
            "Verify no one's work is lost; add protection (protected branches) to prevent recurrence.",
        ],
        [
            "Assume the overwritten commits are gone.",
            "Force-push again to 'fix' it, compounding the loss.",
        ],
        [
            "reflog / another clone still has the old tip.",
            "Protected branches prevent this class entirely.",
        ],
        [
            "Find the old tip (reflog/clone)",
            "Re-point the branch",
            "Protect the branch to prevent recurrence",
        ],
        ["Restore from a colleague's up-to-date clone if the server reflog is gone."],
        ["The server has no reflog; only a developer's local clone has the commits."],
        ["git", "forcepush", "recovery"],
    ),
    (
        "monitoring",
        "fix alerts that fire late or not at all",
        "Gli alert arrivano in ritardo o non arrivano durante un incidente. Trova dove si rompe la catena (scrape->rule->notify) e ripristina alerting affidabile.",
        [
            "Missing/late alerts are a chain failure: scrape gap, rule error, or notifier outage — localize which.",
            "Test each stage: is the metric present, does the rule evaluate, does the notifier deliver?",
            "Fix the broken stage and add a heartbeat/deadman alert so silence itself alerts.",
        ],
        [
            "Assume the alert rule is wrong when the scrape gapped.",
            "Have no deadman alert, so silence is invisible.",
        ],
        [
            "Walk scrape->rule->route->notify to find the break.",
            "A deadman/heartbeat alert catches total silence.",
        ],
        ["Test each alerting stage", "Fix the broken stage", "Add a deadman alert for silence"],
        ["Route a synthetic always-firing alert to prove the notify path continuously."],
        ["The notifier's own credential expired, so nothing delivers."],
        ["monitoring", "alerting", "deadman"],
    ),
    (
        "acl",
        "fix effective permissions capped by an ACL mask",
        "Un utente ha il permesso via gruppo ma non riesce ad accedere: una mask ACL limita il permesso effettivo. Correggi senza aprire troppo.",
        [
            "Base mode + group looks right but access fails => an ACL mask is capping the effective permission.",
            "Read the full ACL including the mask; the effective bits are min(entry, mask).",
            "Raise the mask/entry precisely for the needed access; verify effective permissions.",
        ],
        [
            "chmod the base bits and ignore the ACL mask.",
            "Remove the ACL entirely, losing intended grants.",
        ],
        ["getfacl shows the mask and effective bits.", "Effective = entry AND mask."],
        ["Read the full ACL + mask", "Adjust mask/entry minimally", "Verify effective access"],
        ["Recompute the mask with setfacl so it stops capping the group entry."],
        ["A default ACL on the parent silently caps new files too."],
        ["acl", "mask", "permissions"],
    ),
    (
        "signals",
        "fix a service that ignores SIGTERM and gets SIGKILLed on stop",
        "Un servizio non termina in modo pulito: ignora SIGTERM e viene ucciso con SIGKILL dopo il timeout, perdendo dati in volo. Rendi lo shutdown pulito.",
        [
            "A hard SIGKILL on stop means SIGTERM isn't handled or the grace period is too short.",
            "Confirm the process traps SIGTERM and flushes; check the manager's stop timeout.",
            "Fix signal handling or raise the grace period so shutdown is graceful.",
        ],
        [
            "Just raise the kill timeout without fixing the missing handler.",
            "Accept data loss on every stop.",
        ],
        [
            "The stop timeout + which signal killed it tells you the story.",
            "PID1 in a container must forward signals.",
        ],
        [
            "Confirm SIGTERM handling + grace period",
            "Fix handler or timeout",
            "Verify a clean stop with no data loss",
        ],
        ["Add a proper init (tini) in containers to forward signals to the app."],
        ["The app forks; the manager signals the wrapper, not the real worker."],
        ["signals", "sigterm", "shutdown"],
    ),
    (
        "drivers",
        "resolve a device that works then disappears after sleep/reload",
        "Un dispositivo funziona ma sparisce dopo sospensione o reload del driver. Individua la causa (power management / driver bind) e stabilizza.",
        [
            "Device-disappears-after-sleep is a driver power-management or re-bind issue, not hardware death.",
            "Correlate the loss with the sleep/reload event and the driver bind state.",
            "Fix the power-management/quirk or re-bind logic; verify persistence across sleep cycles.",
        ],
        [
            "Assume hardware failure and replace a working device.",
            "Reboot each time instead of fixing the bind.",
        ],
        [
            "The driver's power-management quirk is a common cause.",
            "Re-bind via the driver's sysfs/pnp interface.",
        ],
        [
            "Correlate loss with sleep/reload",
            "Fix PM quirk / re-bind",
            "Verify across sleep cycles",
        ],
        ["Blacklist the aggressive PM feature for that device class."],
        ["A USB autosuspend setting drops the device after idle."],
        ["drivers", "powermanagement", "usb"],
    ),
    (
        "filesharing",
        "fix Samba/SMB access that works for one client but not another",
        "Una share SMB funziona per un client e non per un altro. Isola se e' auth, versione protocollo o ACL per-utente e correggi.",
        [
            "Client-specific SMB failure isolates to auth/protocol/ACL differences between the two clients.",
            "Compare the two clients' negotiated protocol, credentials, and the per-user share ACL.",
            "Fix the specific difference (vers, domain creds, ACE) without downgrading protocol for all.",
        ],
        [
            "Enable SMBv1 for everyone to fix one client.",
            "Blame the server when one client uses stale creds.",
        ],
        [
            "Compare negotiated dialect + user between the two clients.",
            "A per-user ACE can block just one of them.",
        ],
        [
            "Compare the two clients",
            "Fix the specific auth/protocol/ACL difference",
            "Verify both clients",
        ],
        ["Standardize clients on SMB3 with Kerberos where the domain allows."],
        ["One client caches an old machine credential."],
        ["smb", "samba", "auth"],
    ),
    (
        "caching",
        "fix a cache returning stale data after a backend update",
        "Una cache (Redis/HTTP) serve dati stali dopo un aggiornamento del backend. Correggi l'invalidazione senza svuotare tutto ripetutamente.",
        [
            "Stale-after-update is a cache-invalidation bug: the write path doesn't invalidate/refresh the key.",
            "Trace which key serves stale data and why it isn't invalidated (TTL-only, missing bust, wrong key).",
            "Fix invalidation on write (or a correct TTL) so freshness holds without flushing everything.",
        ],
        [
            "Flush the entire cache on every update (kills hit rate).",
            "Rely on a long TTL and serve stale.",
        ],
        [
            "Invalidate on write, don't just wait for TTL.",
            "Key mismatch between read and write is common.",
        ],
        [
            "Trace the stale key",
            "Fix invalidation on the write path",
            "Verify freshness without full flush",
        ],
        ["Use versioned keys so a new version naturally supersedes the old."],
        ["Read and write compute the cache key differently, so busts miss."],
        ["cache", "redis", "invalidation"],
    ),
    (
        "cicd",
        "fix a pipeline that leaks build artifacts across concurrent runs",
        "Runs CI concorrenti si contaminano a vicenda (workspace/cache condivisi), causando fallimenti intermittenti. Isola i run.",
        [
            "Cross-run contamination means shared mutable state (workspace, cache key, global tool) between concurrent runs.",
            "Identify the shared resource and how runs collide on it.",
            "Isolate per-run (unique workspace, run-scoped cache key, ephemeral runner); verify parallel runs are clean.",
        ],
        ["Serialize the pipeline to hide the isolation bug.", "Share a cache key across branches."],
        [
            "Concurrent flakiness often means shared state.",
            "Scope caches by branch/commit, workspaces per run.",
        ],
        ["Find the shared resource", "Isolate per run", "Verify parallel runs don't interfere"],
        ["Use ephemeral runners/containers so no state survives a run."],
        ["A shared toolchain install races between two runs upgrading it."],
        ["cicd", "isolation", "concurrency"],
    ),
    (
        "iac",
        "reconcile drift between declared IaC and actual infrastructure",
        "L'infrastruttura reale e' andata in drift rispetto al codice IaC (modifiche manuali). Riconcilia senza distruggere risorse in uso.",
        [
            "Drift means manual changes diverged from code — reconcile deliberately, don't blind-apply and destroy.",
            "Diff declared vs actual (plan/refresh) and classify each drift as import, adopt, or revert.",
            "Reconcile safely (import legitimate resources, revert accidental ones); verify a clean plan.",
        ],
        [
            "Blind-apply and destroy manually-created but needed resources.",
            "Ignore drift so it compounds.",
        ],
        [
            "plan/refresh shows the exact drift set.",
            "Import legitimate manual resources instead of recreating.",
        ],
        [
            "Diff declared vs actual",
            "Classify + reconcile each drift",
            "Verify a clean (no-op) plan",
        ],
        ["Adopt manual resources into state via import, then codify them."],
        ["A drifted resource is referenced by others; destroying it cascades."],
        ["iac", "drift", "terraform"],
    ),
    (
        "kubernetes",
        "fix a HPA that won't scale despite high load",
        "Un HorizontalPodAutoscaler non scala nonostante il carico alto. Individua la causa (metrics server / requests mancanti / limiti) e ripristina l'autoscaling.",
        [
            "HPA needs a metrics source AND resource requests to compute utilization — a gap breaks scaling silently.",
            "Check the metrics pipeline, the pods' resource requests, and the HPA target/min/max.",
            "Fix the missing piece (metrics-server, requests) and verify it scales under load.",
        ],
        [
            "Raise min replicas to fake scaling.",
            "Miss that pods have no CPU requests, so utilization is undefined.",
        ],
        ["No requests => HPA can't compute % utilization.", "metrics-server down => HPA is blind."],
        [
            "Check metrics + requests + HPA config",
            "Fix the missing piece",
            "Verify it scales under load",
        ],
        ["Switch to a custom/external metric if CPU isn't the right signal."],
        ["The metric exists but the HPA targets the wrong one."],
        ["k8s", "hpa", "autoscaling"],
    ),
    (
        "gpu",
        "fix a GPU visible to the host but not to a container",
        "La GPU e' visibile all'host ma non al container. Ripristina l'accesso corretto (runtime/devices/driver) senza privilegi eccessivi.",
        [
            "Host-sees-GPU but container-doesn't is a runtime/device-passthrough gap, not a driver-on-host problem.",
            "Check the container runtime's GPU support (device requests, toolkit) and matching driver in the image.",
            "Enable the proper passthrough (device plugin / --gpus) with least privilege; verify the container sees it.",
        ],
        [
            "Run the container --privileged to force GPU access.",
            "Mismatch the in-container CUDA with the host driver.",
        ],
        [
            "The container runtime needs explicit GPU device requests.",
            "In-container userspace must match the host driver.",
        ],
        [
            "Verify runtime GPU support + image driver",
            "Enable proper passthrough",
            "Verify the container sees the GPU",
        ],
        ["Use the vendor's container toolkit/device plugin instead of manual device mounts."],
        ["The device nodes are passed but the container lacks the matching userspace libs."],
        ["gpu", "container", "passthrough"],
    ),
    (
        "networking",
        "fix intermittent connection resets behind a load balancer",
        "Connessioni resettate in modo intermittente dietro un load balancer. Individua idle-timeout/keepalive mismatch tra LB e backend e stabilizza.",
        [
            "Intermittent RSTs behind an LB usually mean an idle-timeout/keepalive mismatch between LB and backend.",
            "Compare the LB idle timeout with the backend keepalive; the shorter side silently drops idle conns.",
            "Align keepalive < LB idle timeout on the backend; verify no resets on long-lived connections.",
        ],
        ["Blame the app for RSTs caused by an LB idle timeout.", "Only tune one side."],
        [
            "Backend keepalive must be shorter than the LB idle timeout.",
            "The RST comes from whichever side times out first.",
        ],
        [
            "Compare LB idle vs backend keepalive",
            "Align keepalive < idle",
            "Verify no resets on idle-then-active conns",
        ],
        ["Enable TCP keepalives end to end so idle connections stay warm."],
        ["A stateful firewall between LB and backend has its own idle timeout."],
        ["net", "loadbalancer", "keepalive"],
    ),
    (
        "logs",
        "extract signal from a multi-gigabyte log without exhausting the host",
        "Devi analizzare un log da molti GB su un host con poca RAM/CPU. Estrai il segnale senza saturare risorse ne alterare le prove.",
        [
            "Naive tooling (loading the whole file) will OOM the host — stream, don't slurp.",
            "Use streaming/bounded tools (grep/awk/streaming parsers) and time/size windows to bound resource use.",
            "Extract the needed signal without modifying the source (preserve evidence).",
        ],
        [
            "Load the whole log into memory and OOM the host.",
            "Edit/rotate the log during analysis, destroying evidence.",
        ],
        [
            "Stream with grep/awk/sed; avoid tools that buffer the whole file.",
            "Bound by time window first.",
        ],
        [
            "Bound the window",
            "Stream-process within resource limits",
            "Extract signal without altering the source",
        ],
        ["Copy a bounded slice to scratch and analyze that, leaving the original intact."],
        ["Multiline stack traces need a windowed, not line-at-a-time, filter."],
        ["logs", "bigdata", "streaming"],
    ),
    (
        "boot",
        "recover a host stuck waiting on a network mount at boot",
        "Un host si blocca in boot in attesa di un mount di rete non disponibile. Rendi il boot resiliente senza rinunciare al mount quando disponibile.",
        [
            "A required network mount can hang boot indefinitely — make it non-blocking while still mounting when present.",
            "Identify the blocking mount and mark it nofail/automount so boot proceeds.",
            "Verify the host boots without the share and mounts it automatically once reachable.",
        ],
        [
            "Remove the mount entirely, losing it when the share IS available.",
            "Leave it hard-required, risking future hangs.",
        ],
        [
            "nofail + automount lets boot proceed and mount later.",
            "x-systemd.automount defers the mount to first access.",
        ],
        [
            "Identify the blocking mount",
            "Make it nofail/automount",
            "Verify boot without it + auto-mount when present",
        ],
        ["Move the dependency to a service that needs the share, gated on its readiness."],
        ["The share is up but slow; a mount timeout is needed, not removal."],
        ["boot", "netmount", "nofail"],
    ),
    (
        "performance",
        "reduce excessive context-switching degrading throughput",
        "Un carico soffre di context-switching eccessivo che degrada il throughput. Individua la causa (troppi thread / lock contention) e riduci lo switching.",
        [
            "High involuntary context switches point at oversubscription or lock contention, not raw CPU shortage.",
            "Measure voluntary vs involuntary switches and thread counts vs cores.",
            "Right-size concurrency / fix the contended lock; verify throughput improves as switching drops.",
        ],
        [
            "Add more threads, worsening oversubscription.",
            "Add CPUs when the wall is lock contention.",
        ],
        [
            "Involuntary switches ~ oversubscription; voluntary ~ blocking/locks.",
            "Threads >> cores is a red flag.",
        ],
        [
            "Measure switch types + thread/core ratio",
            "Right-size concurrency / fix contention",
            "Verify throughput up",
        ],
        ["Pin threads / use a thread pool sized to cores to cut switching."],
        ["A busy-wait spinlock burns CPU without showing as blocking."],
        ["perf", "contextswitch", "concurrency"],
    ),
    (
        "databases",
        "fix replication lag that keeps growing on a replica",
        "La lag di replica su un replica cresce senza sosta. Individua se e' IO, single-thread apply o una query lunga e ripristina la sincronia.",
        [
            "Growing lag has distinct causes: replica IO/CPU bound, single-threaded apply, or a long-running blocking query.",
            "Measure where the replica spends time (apply thread, IO wait, blocked by a reader).",
            "Fix the specific bottleneck (parallel apply, faster IO, kill the blocker); verify lag converges to zero.",
        ],
        [
            "Rebuild the replica for a fixable apply bottleneck.",
            "Assume network when it's disk-bound apply.",
        ],
        [
            "Lag source: apply thread vs IO vs a blocking long read.",
            "Parallel apply helps single-thread bottlenecks.",
        ],
        ["Measure the lag source", "Fix the specific bottleneck", "Verify lag converges to zero"],
        ["Offload long analytic reads to a separate replica so they don't block apply."],
        ["A long-running read on the replica blocks WAL apply (conflict)."],
        ["db", "replication", "lag"],
    ),
    (
        "secrets",
        "migrate hardcoded credentials to a secret store with zero downtime",
        "Migra credenziali hardcoded verso un secret store senza downtime e senza esporre i valori durante la transizione.",
        [
            "A zero-downtime secret migration runs old and new paths in parallel, cutting over per consumer.",
            "Inventory every consumer of the hardcoded secret before moving it.",
            "Inject from the store, roll consumers over, then remove the hardcoded value and rotate it.",
        ],
        [
            "Delete the hardcoded secret before all consumers read from the store (downtime).",
            "Log the secret while migrating.",
        ],
        [
            "Run both sources during cutover.",
            "Rotate after migration since the old value was exposed.",
        ],
        ["Inventory consumers", "Inject from store + roll over", "Remove hardcoded value + rotate"],
        ["Use an init-container/agent to fetch secrets so app code never embeds them."],
        ["A forgotten consumer (a cron job) still reads the old hardcoded value."],
        ["secrets", "migration", "vault"],
    ),
    (
        "virtualization",
        "fix time drift inside VMs causing auth failures",
        "Le VM su un host accumulano drift dell'orologio, rompendo auth e certificati. Correggi la sincronizzazione host-guest.",
        [
            "VM clock drift breaks time-sensitive auth (Kerberos/TLS) — fix the host-guest time sync, not each symptom.",
            "Decide the sync model (host-guest time sync vs in-guest NTP) and avoid double-syncing which fights itself.",
            "Configure one authoritative model consistently; verify guests stay within tolerance.",
        ],
        [
            "Run both host-sync and in-guest NTP, which conflict.",
            "Manually set each guest's clock repeatedly.",
        ],
        ["Pick ONE time-sync model for guests.", "Kerberos tolerates only small skew."],
        ["Choose one sync model", "Configure it consistently", "Verify guests stay in tolerance"],
        ["Disable host-guest sync and rely solely on chrony in the guest with good sources."],
        ["Live migration pauses the guest clock, causing a jump on resume."],
        ["virt", "clock", "ntp"],
    ),
    (
        "remote_access",
        "fix a VPN that breaks local LAN access when connected",
        "Quando la VPN e' connessa, l'accesso alla LAN locale (stampanti, NAS) si rompe per un full-tunnel/route troppo ampio. Ripristina l'accesso locale mantenendo la VPN.",
        [
            "Losing LAN access on VPN connect is a routing scope problem: the tunnel captured routes it shouldn't.",
            "Inspect the pushed routes; the local subnet is being sent through the tunnel.",
            "Configure split-tunnel/route exceptions for the local subnet; verify both LAN and VPN work.",
        ],
        [
            "Disconnect the VPN whenever local access is needed.",
            "Route everything locally, defeating the VPN.",
        ],
        [
            "The tunnel's route table shows the captured local subnet.",
            "Split-tunnel exempts the local subnet.",
        ],
        [
            "Inspect pushed routes",
            "Add split-tunnel exceptions for the local subnet",
            "Verify LAN + VPN both work",
        ],
        ["Use the VPN client's local-LAN-access option where policy permits."],
        ["Policy forces full-tunnel; the fix is a documented exception, not a silent override."],
        ["vpn", "splittunnel", "routing"],
    ),
    (
        "upgrade",
        "safely apply a breaking config-format migration on upgrade",
        "Un upgrade cambia il formato di configurazione (breaking). Applica la migrazione mantenendo un percorso di rollback e senza perdere impostazioni.",
        [
            "A breaking config-format change needs a migrate-with-rollback plan, not an in-place overwrite.",
            "Back up the old config, run the provided migration (or translate settings) into the new format.",
            "Validate the migrated config, keep the old for rollback, and verify the service on the new format.",
        ],
        [
            "Overwrite the config in the new format with no backup.",
            "Lose custom settings the migration didn't carry.",
        ],
        ["Keep the old config for rollback.", "Diff old vs migrated to catch dropped settings."],
        [
            "Back up + migrate the config",
            "Validate + keep rollback",
            "Verify service on the new format",
        ],
        ["Run old and new versions side by side to compare behavior before cutover."],
        ["The migration tool silently drops a deprecated-but-load-bearing option."],
        ["upgrade", "config", "migration"],
    ),
    (
        "filesystem",
        "fix a case-sensitivity mismatch breaking a cross-platform project",
        "Un progetto cross-platform si rompe per un mismatch di case-sensitivity del filesystem (due file che differiscono solo per maiuscole). Risolvi in modo portabile.",
        [
            "Case-sensitivity mismatch: a case-insensitive FS collapses two files a case-sensitive one keeps distinct.",
            "Identify the colliding paths and which side is authoritative.",
            "Rename to avoid case-only differences (or use a case-sensitive volume); verify on both platforms.",
        ],
        [
            "Fix it on one platform only, breaking the other.",
            "Ignore the collision until it silently drops a file.",
        ],
        [
            "git can track case-only renames that the FS won't distinguish.",
            "A case-sensitive volume avoids the class.",
        ],
        [
            "Identify the case collision",
            "Rename to remove case-only diffs",
            "Verify on both platforms",
        ],
        ["Create a dedicated case-sensitive volume for the checkout on macOS/Windows."],
        ["The collision only manifests on a coworker's case-insensitive machine."],
        ["fs", "casesensitivity", "crossplatform"],
    ),
    (
        "certificates",
        "fix a client that can't verify a certificate signed by an internal CA",
        "Un client non verifica un certificato firmato da una CA interna legittima (root mancante nel trust store). Aggiungi la fiducia in modo mirato e sicuro.",
        [
            "Verification failure against a legitimate internal CA means the client is missing the CA root, not a bad cert.",
            "Confirm the CA is trusted and add its root to the CLIENT trust store (system or app-specific), scoped correctly.",
            "Keep verification ON; verify the handshake now succeeds with trust in place.",
        ],
        [
            "Disable verification instead of trusting the internal CA.",
            "Import an untrusted/unknown CA blindly.",
        ],
        [
            "The fix is adding the internal ROOT to the trust store, not disabling verify.",
            "Scope to the right trust store.",
        ],
        [
            "Confirm the internal CA is legitimate",
            "Add its root to the client trust store",
            "Verify the handshake with trust on",
        ],
        ["Distribute the internal CA root via config management to all clients."],
        ["An app uses its own trust bundle, ignoring the system store."],
        ["tls", "internal-ca", "truststore"],
    ),
    (
        "shell",
        "fix a script that behaves differently across shells/versions",
        "Uno script si comporta diversamente tra shell/versioni (bashisms in sh, quoting, array). Rendilo portabile e robusto senza cambiarne la logica.",
        [
            "Cross-shell divergence is a portability bug: bashisms under sh, quoting, or word-splitting differences.",
            "Identify the non-portable constructs (arrays, [[ ]], process substitution) and the target shells.",
            "Make it portable (declare the interpreter, quote correctly, avoid unsupported features) or pin the interpreter.",
        ],
        ["Assume /bin/sh is bash (it often isn't).", "Fix on one shell and break another."],
        ["A shebang + shellcheck catch most portability issues.", "sh lacks arrays and [[ ]]."],
        [
            "Identify non-portable constructs",
            "Make portable or pin the interpreter",
            "Verify identical behavior across targets",
        ],
        [
            "Explicitly require and invoke the intended shell rather than relying on the ambient one."
        ],
        ["Word-splitting on an unquoted variable changes behavior between shells."],
        ["shell", "portability", "posix"],
    ),
]

EXPERT_TASKS = [
    (
        "performance",
        "root-cause a periodic latency spike correlated with a background job",
        "Un picco di latenza periodico degrada il servizio a intervalli regolari. Correla con job/cron/GC in background e elimina la contesa.",
        [
            "Periodic spikes correlate with a scheduled event — find the period and what runs then.",
            "Correlate the spike with cron/backup/GC/compaction using timestamps and resource counters.",
            "Decouple the contention (reschedule, throttle, isolate IO/CPU) and verify the spike is gone.",
        ],
        [
            "Chase the spike as random when it's a scheduled job.",
            "Move the job without measuring the contended resource.",
        ],
        [
            "Find the period, then what fires on that period.",
            "USE-method counters reveal the contended resource.",
        ],
        [
            "Correlate spike period with a background job",
            "Isolate/throttle/reschedule it",
            "Verify spikes disappear",
        ],
        ["Put the batch job in a low-priority cgroup during business hours."],
        ["The 'job' is log rotation compressing a huge file."],
        ["perf", "latency", "contention"],
    ),
    (
        "kernel",
        "diagnose and mitigate a resource leak in kernel space (slab/inode)",
        "La memoria kernel (slab/inode cache) cresce senza sosta fino alla pressione di sistema. Individua il consumatore e mitiga.",
        [
            "Growing kernel memory (slab) is a kernel/driver/fs leak, not user RSS — read slab accounting.",
            "Identify the growing slab cache and the subsystem behind it (dentries/inodes/a driver).",
            "Mitigate (tunable, reclaim, patch/driver update) and verify growth stops.",
        ],
        [
            "Look only at process RSS and miss kernel slab growth.",
            "Drop caches as a permanent fix.",
        ],
        [
            "slabtop / /proc/slabinfo show the growing cache.",
            "dentry/inode explosion often traces to a find/scan pattern.",
        ],
        [
            "Read slab accounting",
            "Identify the leaking subsystem",
            "Apply tunable/patch; verify growth halts",
        ],
        [
            "Constrain the workload pattern (e.g., cap concurrent open files) that drives the growth."
        ],
        ["A buggy driver leaks a custom slab cache invisible to RSS."],
        ["kernel", "slab", "leak"],
    ),
    (
        "databases",
        "recover a database from a corrupted index without data loss",
        "Un indice di database e' corrotto e alcune query falliscono o restituiscono risultati errati. Ripara senza perdere dati.",
        [
            "A corrupt index is recoverable by rebuild — the table data usually survives; do NOT restore-over blindly.",
            "Confirm the corruption is in the index (not the heap) and identify the affected index.",
            "Rebuild/reindex the specific index online where possible; verify query correctness.",
        ],
        [
            "Restore the whole DB from backup for an index-only issue (data loss window).",
            "Ignore that queries return wrong rows.",
        ],
        [
            "Reindex fixes index corruption without touching the heap.",
            "Wrong results (not just errors) signal index corruption.",
        ],
        [
            "Confirm index vs heap corruption",
            "Rebuild the affected index online",
            "Verify correctness",
        ],
        ["If the heap is also damaged, restore + replay WAL to a point before corruption."],
        ["Corruption is in a unique index, so rebuild reveals duplicate-key data to reconcile."],
        ["db", "index", "corruption"],
    ),
    (
        "networking",
        "eliminate intermittent DNS timeouts under load (conntrack/UDP)",
        "Sotto carico, alcune risoluzioni DNS vanno in timeout in modo intermittente. Individua la causa (conntrack/UDP/limiti) e stabilizza.",
        [
            "Intermittent DNS-under-load points at UDP/conntrack table limits or ephemeral-port/racy resolver behavior.",
            "Check conntrack saturation, UDP drops, and the resolver's concurrency/retry behavior under load.",
            "Fix the specific limit (conntrack size, single-request-reopen) and verify under load.",
        ],
        ["Blame the upstream DNS for a local conntrack overflow.", "Raise timeouts to mask drops."],
        [
            "conntrack -S shows table drops.",
            "The single-request-reopen resolver option fixes a classic UDP race.",
        ],
        [
            "Check conntrack/UDP drops under load",
            "Fix the limit / resolver option",
            "Verify no timeouts under load",
        ],
        ["Move hot lookups to a local caching resolver to cut UDP pressure."],
        ["A specific glibc getaddrinfo A+AAAA race causes the intermittent 5s stalls."],
        ["dns", "conntrack", "udp"],
    ),
    (
        "security",
        "contain and remediate a host with a persistence mechanism",
        "Un host mostra un meccanismo di persistenza sospetto (cron/servizio/chiave). Contieni, rimuovi la persistenza e ripristina fiducia senza distruggere le prove.",
        [
            "Persistence means the threat survives reboot — enumerate ALL persistence vectors, don't stop at the first.",
            "Preserve evidence, then remove every persistence mechanism (cron, units, run keys, authorized_keys, LD_PRELOAD).",
            "Rotate exposed credentials and prefer rebuild over clean; verify persistence is gone.",
        ],
        [
            "Remove one cron entry and declare it clean.",
            "Wipe the host, destroying evidence and root-cause.",
        ],
        [
            "Persistence hides in many places — enumerate them systematically.",
            "Rebuild beats 'cleaning' a compromised host.",
        ],
        [
            "Enumerate all persistence vectors",
            "Preserve evidence + remove persistence",
            "Rotate creds; rebuild; verify",
        ],
        ["Reimage from trusted media and restore only vetted data."],
        ["A persistence hook lives in a legit-looking service unit."],
        ["security", "persistence", "ir"],
    ),
    (
        "storage",
        "migrate a live filesystem to a new disk with zero data loss",
        "Migra un filesystem attivo su un nuovo disco piu' capiente senza perdita dati e con downtime minimo.",
        [
            "A live migration needs a consistent copy — snapshot or sync-then-quiesce to avoid losing in-flight writes.",
            "Copy at block or file level, then do a final quiesced delta sync before cutover.",
            "Cut over atomically (mount/label swap), verify integrity, keep the old disk until validated.",
        ],
        [
            "Copy a live filesystem without a final quiesced sync (misses last writes).",
            "Delete the source before validating.",
        ],
        [
            "A final quiesced delta sync captures in-flight writes.",
            "Keep the source until the target is proven.",
        ],
        [
            "Snapshot/sync live",
            "Quiesced final delta + atomic cutover",
            "Verify integrity; retire old disk after validation",
        ],
        ["Use LVM pvmove / filesystem-level replication for near-zero downtime."],
        [
            "Open files with unlinked inodes won't copy at file level — block copy or restart holders."
        ],
        ["storage", "migration", "zerodowntime"],
    ),
    (
        "services",
        "make a flaky health check reflect true service health",
        "Un health check da' verde mentre il servizio e' di fatto degradato (falso positivo). Rendilo veritiero senza causare falsi negativi.",
        [
            "A lying green check checks the wrong thing (process up != serving correctly).",
            "Define real health (dependency reachable + a representative request succeeds), not just 'port open'.",
            "Implement a deep-but-cheap check; verify it goes red on real degradation and stays green when healthy.",
        ],
        [
            "Deepen the check so much it flaps on transient blips (false negatives).",
            "Keep the shallow check that lies.",
        ],
        [
            "Health = serves a real request, not just 'process alive'.",
            "Balance depth against flakiness.",
        ],
        [
            "Define true health",
            "Implement a deep-but-cheap check",
            "Verify it reddens on real degradation only",
        ],
        ["Add a synthetic transaction probe from outside the host."],
        ["A dependency-down state should be a distinct 'degraded', not a hard fail."],
        ["services", "healthcheck", "observability"],
    ),
    (
        "upgrade",
        "perform a zero-downtime rolling upgrade of a stateful service",
        "Esegui un upgrade rolling a downtime zero di un servizio stateful con replica, senza perdere consistenza.",
        [
            "Stateful rolling upgrades must preserve consistency: upgrade replicas first, keep quorum, promote carefully.",
            "Verify compatibility across versions during the window (rolling implies mixed versions briefly).",
            "Upgrade node-by-node behind health gates, keeping quorum; verify data consistency throughout.",
        ],
        ["Upgrade all nodes at once (downtime + risk).", "Break quorum mid-upgrade."],
        ["Mixed-version compatibility must hold during the roll.", "Keep quorum at every step."],
        [
            "Verify cross-version compat",
            "Roll node-by-node behind health gates",
            "Maintain quorum; verify consistency",
        ],
        [
            "Use a read-replica cutover pattern if in-place rolling isn't safe for this version jump."
        ],
        ["A schema/protocol change between versions breaks the mixed-version window."],
        ["upgrade", "rolling", "stateful"],
    ),
    (
        "env_path",
        "fix a build that passes locally but fails in a clean environment",
        "Un build passa in locale ma fallisce in un ambiente pulito per uno stato implicito (env/tool/cache non dichiarato). Rendilo riproducibile.",
        [
            "'Passes locally' hides an undeclared dependency on local state (env var, global tool, cache).",
            "Reproduce in a clean, isolated environment to surface the implicit dependency.",
            "Declare it explicitly (pin tool, set env in the build def, no reliance on global state); verify from clean.",
        ],
        [
            "Add the missing state to the CI machine instead of declaring it.",
            "Rely on a globally-installed tool.",
        ],
        [
            "A clean container exposes implicit local dependencies.",
            "Declare, don't rely on ambient state.",
        ],
        [
            "Reproduce in a clean env",
            "Declare the hidden dependency explicitly",
            "Verify from a fresh checkout+env",
        ],
        ["Vendor the toolchain in the build image so nothing is ambient."],
        ["A cached credential/token makes it pass locally only."],
        ["env", "reproducibility", "hermetic"],
    ),
    (
        "recovery",
        "restore service after an accidental irreversible-looking change",
        "Una modifica sembra irreversibile (config sovrascritta, dato cancellato) e il servizio e' down. Trova ogni possibile fonte di recupero prima di ricostruire.",
        [
            "'Irreversible' is often not: check backups, snapshots, package-shipped defaults, caches, and open fds.",
            "Enumerate every recovery source before rebuilding from scratch.",
            "Restore from the best source, verify, and add the missing safety (backup/versioning) that made this scary.",
        ],
        [
            "Rebuild from scratch without checking for a recoverable copy.",
            "Panic-act and overwrite a recoverable state.",
        ],
        [
            "Deleted-but-open fds, package defaults, and snapshots are common rescue sources.",
            "Check before rebuilding.",
        ],
        [
            "Enumerate recovery sources",
            "Restore from the best one + verify",
            "Add the missing backup/versioning",
        ],
        [
            "Reconstruct config from the running process's loaded state (/proc, memory) if no file copy exists."
        ],
        ["The deleted config is still held open by the running process's fd."],
        ["recovery", "restore", "resilience"],
    ),
    (
        "virtualization",
        "fix a VM that boots but has no network after a host migration",
        "Dopo una migrazione host, una VM avvia ma non ha rete (interfaccia rinominata / bridge mancante / MAC cambiato). Ripristina la connettivita'.",
        [
            "VM-no-network post-migration is usually a changed NIC name/MAC or a missing host bridge, not a guest OS bug.",
            "Compare the guest's expected interface (name/MAC) with what the migrated host presents.",
            "Fix the mapping (bridge, MAC, predictable-iface-name) so the guest binds its network again.",
        ],
        [
            "Reinstall the guest network stack for a host-side mapping issue.",
            "Miss that the interface was renamed.",
        ],
        [
            "A changed MAC/NIC name breaks udev-based interface config in the guest.",
            "The host bridge may not exist on the new host.",
        ],
        [
            "Compare expected vs presented NIC",
            "Fix bridge/MAC/iface-name mapping",
            "Verify guest connectivity",
        ],
        ["Switch the guest to predictable-network-interface names to survive migrations."],
        ["The guest pins a MAC-based config that the migration changed."],
        ["virt", "migration", "network"],
    ),
    (
        "cloud",
        "diagnose cross-account/permission failure in a cloud pipeline",
        "Una pipeline cloud fallisce con un errore di permessi cross-account intermittente. Traccia la catena di ruoli/trust e concedi il minimo necessario.",
        [
            "Cross-account failures are trust-policy + permission-boundary problems — trace the assumed-role chain.",
            "Identify which role/step is denied and whether it's the trust policy, the permission, or a boundary/SCP.",
            "Grant the minimal missing permission at the right layer; verify the whole chain end to end.",
        ],
        [
            "Attach an over-broad policy to make it work.",
            "Fix the identity policy when an SCP/boundary is the blocker.",
        ],
        [
            "Trust policy vs identity policy vs SCP are different denials.",
            "Least privilege even when debugging.",
        ],
        [
            "Trace the role/trust chain",
            "Grant the minimal missing permission at the right layer",
            "Verify end to end",
        ],
        ["Use policy simulation/what-if tooling to pinpoint the denied action."],
        ["An SCP at the org level overrides a correct account-level grant."],
        ["cloud", "iam", "crossaccount"],
    ),
    (
        "toolchains",
        "resolve a native-dependency ABI mismatch across environments",
        "Un modulo nativo funziona in un ambiente e crasha in un altro per un mismatch ABI (glibc/compiler/arch). Rendilo portabile o correttamente vincolato.",
        [
            "A native ABI mismatch (glibc/arch/compiler) is a build-target problem, not app logic.",
            "Identify the ABI axis that differs (libc version, arch, C++ ABI) between the two environments.",
            "Build for the correct target (or pin a compatible manylinux/base) and verify on both.",
        ],
        [
            "Copy a binary built for one libc to an incompatible one.",
            "Force-load with LD_PRELOAD hacks.",
        ],
        ["ldd + the exact error name the ABI axis.", "manylinux/target pinning gives portability."],
        [
            "Identify the differing ABI axis",
            "Build for the correct target / pin compatible base",
            "Verify on both envs",
        ],
        ["Statically link or ship in a container to fix the ABI to the image."],
        ["The C++ ABI (pre/post-cxx11) differs though glibc matches."],
        ["toolchain", "abi", "native"],
    ),
    (
        "filesystem",
        "repair inconsistent filesystem after unclean shutdown, minimizing loss",
        "Dopo uno spegnimento non pulito il filesystem e' incoerente. Ripara minimizzando la perdita, con evidenza prima di ogni azione distruttiva.",
        [
            "Filesystem repair can lose data — image the device first so any fsck decision is reversible.",
            "Run the check in report mode to understand the damage before applying repairs.",
            "Apply repairs, then verify mount + data integrity; recover orphans from lost+found.",
        ],
        [
            "Run fsck -y on a questionable disk with no image.",
            "Mount rw and worsen the corruption.",
        ],
        [
            "Image first; fsck decisions are otherwise irreversible.",
            "Report mode before repair mode.",
        ],
        ["Image the device", "Assess damage in report mode", "Repair + verify; recover lost+found"],
        ["Copy off critical files read-only before any repair if the FS still mounts ro."],
        ["A journal replay alone may fix it without a full fsck."],
        ["fs", "fsck", "corruption"],
    ),
    (
        "proxy",
        "fix TLS termination + backend re-encryption mismatch",
        "Un reverse proxy termina TLS ma la ri-cifratura verso il backend fallisce (SNI/cert/protocollo). Ripristina il flusso end-to-end sicuro.",
        [
            "Front TLS OK + backend TLS failing is a re-encryption mismatch: SNI, trust, or protocol to the upstream.",
            "Inspect the proxy->backend handshake (SNI sent, CA trusted, protocol/cipher) separately from the client side.",
            "Fix the specific upstream TLS parameter; keep verification ON to the backend.",
        ],
        [
            "Disable upstream TLS verification to 'unblock'.",
            "Assume the client-side cert is the backend problem.",
        ],
        [
            "The proxy->backend handshake is a separate TLS session with its own SNI/trust.",
            "Keep verify on to the backend.",
        ],
        [
            "Inspect the upstream handshake",
            "Fix SNI/trust/protocol to the backend",
            "Verify secure end to end",
        ],
        ["Use a shared internal CA the proxy trusts for backend certs."],
        ["The backend expects SNI the proxy doesn't send, so it serves the wrong cert."],
        ["proxy", "tls", "reencrypt"],
    ),
    (
        "kubernetes",
        "debug a pod that can reach the internet but not a ClusterIP service",
        "Un pod raggiunge internet ma non un Service ClusterIP interno. Individua il livello rotto (kube-proxy/CNI/NetworkPolicy/DNS) e ripristina.",
        [
            "Egress-OK but ClusterIP-fail isolates to in-cluster networking: kube-proxy rules, CNI, NetworkPolicy, or cluster DNS.",
            "Test each layer: does DNS resolve the service, do the iptables/ipvs rules exist, does a NetworkPolicy block it?",
            "Fix the specific broken layer; verify service-to-service traffic within the cluster.",
        ],
        [
            "Blame the app for an in-cluster networking break.",
            "Delete NetworkPolicies wholesale to 'test'.",
        ],
        [
            "ClusterIP relies on kube-proxy rules + DNS; test both.",
            "A default-deny NetworkPolicy silently blocks it.",
        ],
        [
            "Test DNS/kube-proxy/NetworkPolicy layers",
            "Fix the broken layer",
            "Verify in-cluster service traffic",
        ],
        ["Exec a debug pod on the same node to bisect node-local vs cross-node paths."],
        ["A default-deny NetworkPolicy without an allow-DNS rule breaks resolution first."],
        ["k8s", "clusterip", "networking"],
    ),
    (
        "databases",
        "safely add an index to a huge table without locking writes",
        "Devi aggiungere un indice a una tabella enorme in produzione senza bloccare le scritture. Pianifica ed esegui la creazione concorrente in sicurezza.",
        [
            "A naive CREATE INDEX locks the table — use the concurrent/online path and plan for its failure modes.",
            "Verify the online-index prerequisites (no long transactions, disk headroom, it can fail and leave an invalid index).",
            "Create it concurrently, monitor progress, and validate/clean up if it fails partway.",
        ],
        [
            "Run a blocking CREATE INDEX in peak hours.",
            "Assume concurrent creation can't fail (it can, leaving an invalid index).",
        ],
        [
            "Concurrent index build avoids the write lock but is slower and can fail.",
            "Ensure disk headroom for the build.",
        ],
        [
            "Verify prerequisites",
            "Create index concurrently + monitor",
            "Validate / clean up on failure",
        ],
        ["Build on a replica and promote, if the concurrent path is too risky for this size."],
        ["A long-open transaction stalls the concurrent build indefinitely."],
        ["db", "index", "online"],
    ),
    (
        "security",
        "investigate anomalous outbound traffic without tipping off the process",
        "Un processo genera traffico in uscita anomalo. Indaga preservando le prove e senza allertare il processo, poi contieni.",
        [
            "Investigating live malicious traffic: observe first (don't kill/alert), preserve volatile evidence, THEN contain.",
            "Capture the connections, the owning process, and its artifacts before it can react or self-destruct.",
            "Contain by network isolation (not process kill, which loses state); rotate exposed credentials.",
        ],
        [
            "Kill the process immediately, losing memory/connection evidence.",
            "Block the IP and alert the malware to go quiet.",
        ],
        [
            "Capture before you contain; killing destroys volatile state.",
            "Network isolation preserves the process for analysis.",
        ],
        [
            "Observe + capture evidence",
            "Isolate the network (not kill)",
            "Rotate creds; then analyze",
        ],
        ["Snapshot the VM/memory for offline forensics before any containment."],
        ["The process watches for its own kill and wipes traces on SIGTERM."],
        ["security", "forensics", "exfiltration"],
    ),
    (
        "performance",
        "diagnose tail latency (p99) while median stays low",
        "La latenza mediana e' ottima ma la p99 e' pessima e colpisce utenti reali. Individua la causa della coda (GC/lock/IO burst/queueing) ed eliminala.",
        [
            "Good median + bad p99 is a tail problem: intermittent GC pauses, lock waits, IO bursts, or queueing.",
            "Capture per-request traces at the tail, not aggregates, to see what the slow 1% hit.",
            "Fix the specific tail source; verify p99 drops without regressing median.",
        ],
        [
            "Optimize the median path and ignore the tail users feel.",
            "Average away the tail in dashboards.",
        ],
        [
            "The tail is a different code path/event than the median.",
            "Trace the slow requests specifically.",
        ],
        [
            "Trace tail requests",
            "Identify + fix the tail source",
            "Verify p99 improves, median holds",
        ],
        ["Add request hedging so a slow replica doesn't dominate the tail."],
        ["A periodic GC/compaction pause explains the p99 spikes."],
        ["perf", "tail-latency", "p99"],
    ),
    (
        "networking",
        "fix an IPv6-related failure on a dual-stack host",
        "Un host dual-stack fallisce alcune connessioni perche' preferisce IPv6 dove non funziona (Happy Eyeballs mal configurato). Ripristina senza disabilitare IPv6 del tutto.",
        [
            "Some-connections-fail on dual-stack often means broken IPv6 preferred over working IPv4.",
            "Confirm IPv6 reachability vs IPv4 and how the resolver/app orders the families.",
            "Fix IPv6 (or address selection / Happy Eyeballs) rather than crudely disabling IPv6.",
        ],
        ["Disable IPv6 globally as the fix.", "Blame the app for an address-selection issue."],
        [
            "Test AAAA reachability directly vs A.",
            "Address-selection/Happy-Eyeballs governs the choice.",
        ],
        [
            "Compare v6 vs v4 reachability",
            "Fix v6 or address selection",
            "Verify without disabling IPv6",
        ],
        ["Correct the gai.conf/address-selection policy instead of disabling v6."],
        ["v6 works to some destinations but a broken v6 default route breaks others."],
        ["net", "ipv6", "dualstack"],
    ),
    (
        "storage",
        "recover from an accidental overlay/bind mount hiding data",
        "Dati 'spariti': un mount (overlay/bind) e' stato montato sopra una directory popolata, nascondendo i file sottostanti. Recupera senza perdere nulla.",
        [
            "Vanished data under a mountpoint is usually hidden, not deleted, by a mount shadowing the directory.",
            "Confirm a mount covers the path; the underlying files are intact beneath it.",
            "Unmount (or bind-view the underlying) to reveal the data; fix the mount config so it doesn't re-shadow.",
        ],
        [
            "Assume the data is deleted and restore from backup unnecessarily.",
            "Delete the 'empty' directory (it's not empty).",
        ],
        [
            "A mount over a populated dir hides its contents until unmounted.",
            "The lower data is intact beneath the mount.",
        ],
        [
            "Confirm the shadowing mount",
            "Reveal the underlying data",
            "Fix the mount so it stops shadowing",
        ],
        [
            "Bind-mount the underlying filesystem elsewhere to read the hidden files without unmounting."
        ],
        ["An automount re-shadows the directory on next access."],
        ["storage", "mount", "shadowing"],
    ),
    (
        "recovery",
        "rebuild a lost RAID array configuration without reformatting",
        "La configurazione di un array RAID e' andata persa (superblock/metadata) ma i dischi sono integri. Ricostruisci l'array senza reinizializzare i dati.",
        [
            "Lost array metadata with intact disks is recoverable by re-assembling with the ORIGINAL parameters — never re-create with defaults.",
            "Determine the original layout (order, chunk size, level) from disk superblocks/backups before assembling.",
            "Assemble read-only first to validate, then bring it online; do NOT let a create zero the data.",
        ],
        [
            "Re-create the array with default parameters, destroying the data layout.",
            "Guess the disk order.",
        ],
        [
            "Assemble (not create) preserves data; create can wipe it.",
            "Superblocks/backups hold the original geometry.",
        ],
        [
            "Determine original geometry",
            "Assemble read-only to validate",
            "Bring online; never create-over",
        ],
        ["Use a metadata backup or a known-good peer to recover the exact parameters."],
        ["Wrong disk order assembles but yields garbage — validate read-only first."],
        ["raid", "recovery", "assemble"],
    ),
    (
        "services",
        "eliminate a slow memory/fd creep that only shows after days",
        "Un servizio degrada solo dopo giorni per un lento creep di memoria/fd che i test brevi non colgono. Individua e correggi la vera perdita.",
        [
            "A days-long creep won't reproduce in short tests — you need trend data over time, not a snapshot.",
            "Instrument long-run trends (RSS, fd count, thread count) and diff across days to see the slope.",
            "Localize the leaking resource, fix it, and add a trend alert so future creep is caught early.",
        ],
        [
            "Conclude 'no leak' from a short test.",
            "Restart on a schedule and never find the creep.",
        ],
        [
            "Trend over days beats a point-in-time check.",
            "fd/thread creep is as common as heap creep.",
        ],
        ["Capture multi-day trends", "Localize + fix the leak", "Add a trend alert"],
        ["Bisect by rolling back recent changes to find when the slope appeared."],
        ["The creep is a slowly-growing internal cache with no eviction."],
        ["services", "leak", "longrun"],
    ),
    (
        "cloud",
        "fix an intermittent throttling error under burst load",
        "Sotto burst, chiamate a un servizio cloud falliscono in modo intermittente per throttling/rate limit. Rendi il client resiliente rispettando i limiti.",
        [
            "Intermittent failures under burst are rate-limiting/throttling — the fix is client-side backoff + limit awareness, not brute force.",
            "Confirm the throttling signal (429/limit headers) and the actual quota.",
            "Add jittered exponential backoff + request smoothing; stay under the quota, request an increase if genuinely needed.",
        ],
        [
            "Retry immediately in a tight loop, amplifying the throttle.",
            "Ignore the limit and just add more workers.",
        ],
        [
            "429 + limit headers tell you the quota.",
            "Jittered backoff avoids synchronized retries.",
        ],
        [
            "Confirm the throttle + quota",
            "Add jittered backoff + smoothing",
            "Verify success under burst within quota",
        ],
        ["Batch/coalesce requests to fit the quota, or request a quota increase with data."],
        ["A shared account quota is consumed by another workload, not just this one."],
        ["cloud", "throttling", "backoff"],
    ),
    (
        "toolchains",
        "fix nondeterministic builds that break caching and reproducibility",
        "Build non deterministici (timestamp/ordine/percorsi assoluti embeddati) rompono cache e riproducibilita'. Rendi il build bit-per-bit riproducibile.",
        [
            "Nondeterministic outputs (embedded timestamps, file ordering, absolute paths) break caching and reproducibility.",
            "Identify the nondeterminism source by diffing two builds of the same input.",
            "Eliminate it (SOURCE_DATE_EPOCH, sorted inputs, path remapping); verify two builds are byte-identical.",
        ],
        [
            "Accept 'close enough' outputs that differ each build.",
            "Fix one source and miss others.",
        ],
        [
            "diffoscope pinpoints what differs between two builds.",
            "SOURCE_DATE_EPOCH pins timestamps.",
        ],
        [
            "Diff two builds",
            "Eliminate each nondeterminism source",
            "Verify byte-identical rebuilds",
        ],
        ["Build in a hermetic sandbox that strips ambient nondeterminism."],
        ["Locale/timezone in the build env leaks into sorted output."],
        ["toolchain", "reproducible", "determinism"],
    ),
    (
        "env_path",
        "resolve conflicting library versions loaded at runtime (dll/so hell)",
        "Un processo carica a runtime la versione sbagliata di una libreria condivisa (DLL/so hell), causando crash o comportamenti errati. Correggi la risoluzione senza rompere altri processi.",
        [
            "Wrong shared-lib loaded at runtime is a search-order / RPATH / SxS problem, not app logic.",
            "Trace what the loader actually resolves (ldd/DependencyWalker) and why the wrong one wins.",
            "Fix the resolution for THIS process (RPATH/manifest/isolated dir) without perturbing global paths.",
        ],
        [
            "Overwrite the system library with the wanted version, breaking other apps.",
            "Copy DLLs into system32.",
        ],
        [
            "The loader's search order decides the winner; trace it.",
            "Isolate per-app rather than mutate global.",
        ],
        [
            "Trace the actual load",
            "Fix per-process resolution",
            "Verify without affecting other processes",
        ],
        ["Ship the app with its libs in a private directory / app manifest (SxS)."],
        ["A LD_LIBRARY_PATH set in a parent shell poisons the child's resolution."],
        ["env", "dll-hell", "loader"],
    ),
    (
        "monitoring",
        "fix metrics with wrong values due to counter resets/rate errors",
        "Un pannello mostra valori assurdi (picchi negativi/enormi) per reset di contatori mal gestiti. Correggi le query rate senza perdere dati reali.",
        [
            "Absurd metric spikes usually mean counter resets handled wrong in the rate query, not bad data.",
            "Confirm the metric is a monotonic counter and the query accounts for resets (rate/increase semantics).",
            "Fix the query/recording rule to handle resets; verify the panel matches reality.",
        ],
        ["'Fix' by clamping values, hiding the query bug.", "Treat a counter like a gauge."],
        [
            "rate()/increase() handle counter resets; raw diffs don't.",
            "A restart resets the counter to zero.",
        ],
        [
            "Confirm counter semantics",
            "Fix the rate/reset handling",
            "Verify the panel matches reality",
        ],
        ["Add recording rules so the corrected rate is precomputed and consistent."],
        ["A relabel drops the instance label, merging counters from many hosts."],
        ["monitoring", "counters", "promql"],
    ),
    (
        "filesystem",
        "safely deduplicate/reclaim space without breaking hardlinks or CoW",
        "Devi recuperare spazio deduplicando file identici, ma senza rompere hardlink esistenti o la semantica copy-on-write. Recupera in sicurezza.",
        [
            "Naive dedup (replace-with-link) can break apps that assume independent files or CoW semantics.",
            "Understand which files are safe to link (truly immutable) vs those needing independent copies.",
            "Dedup only the safe set (reflink/CoW where available); verify no app breaks and space is reclaimed.",
        ],
        [
            "Hardlink files that get edited independently, causing cross-contamination.",
            "Dedup mutable data.",
        ],
        [
            "reflink/CoW dedup is safe for mutable files; hardlink is not.",
            "Only immutable files are hardlink-safe.",
        ],
        [
            "Classify safe-to-dedup files",
            "Dedup with the right mechanism (reflink/hardlink)",
            "Verify no breakage + space reclaimed",
        ],
        ["Use filesystem-native dedup (ZFS/Btrfs) instead of manual linking."],
        ["A backup tool follows hardlinks and now stores less independence than expected."],
        ["fs", "dedup", "reflink"],
    ),
    (
        "services",
        "fix a service that works interactively but fails under the service manager",
        "Un programma gira a mano ma fallisce quando lanciato dal service manager (env/cwd/tty/permessi diversi). Individua la differenza di contesto e correggi.",
        [
            "'Works by hand, fails as a service' is a context difference: env, cwd, TTY, user, or resource limits differ.",
            "Diff the interactive environment against the service's (env, cwd, user, limits, no TTY).",
            "Supply the missing context in the unit/definition; verify it runs identically under the manager.",
        ],
        [
            "Run the service as your interactive user to 'fix' it.",
            "Assume the manager provides your shell's env (it doesn't).",
        ],
        [
            "The service manager gives a minimal env, no TTY, a set cwd/user.",
            "Diff the two contexts.",
        ],
        [
            "Diff interactive vs service context",
            "Supply the missing context in the unit",
            "Verify it runs under the manager",
        ],
        ["Wrap the program in a script that sets an explicit, documented environment."],
        ["The program needs a controlling TTY it only had interactively."],
        ["services", "context", "environment"],
    ),
    (
        "users",
        "fix a home directory / profile corruption blocking login",
        "Un utente non riesce piu' a fare login per profilo/home corrotto (permessi, file di init, quota). Ripristina l'accesso preservando i dati utente.",
        [
            "Login failure from a corrupt profile/home is fixable without deleting the user's data.",
            "Identify the specific blocker (home perms/owner, a broken init/profile file, quota) from the login error/logs.",
            "Repair that item, preserving user data; verify a clean login.",
        ],
        ["Delete and recreate the profile, losing user data.", "chmod the whole home to 777."],
        [
            "Login error/logs name the blocker (perms vs init file vs quota).",
            "Repair, don't recreate.",
        ],
        ["Identify the login blocker", "Repair it preserving data", "Verify a clean login"],
        ["Log in with a temporary clean profile to repair the corrupt one from the side."],
        ["A syntax error in the user's shell init aborts every login."],
        ["users", "profile", "login"],
    ),
    (
        "databases",
        "fix Redis evicting keys unexpectedly under maxmemory policy",
        "Redis espelle chiavi in modo inatteso: la policy maxmemory/eviction non e' adatta al workload. Correggi senza perdere dati che devono persistere.",
        [
            "Unexpected eviction means the maxmemory policy doesn't match the data's persistence needs.",
            "Determine which keys must persist vs are cache, and the current policy/memory pressure.",
            "Set the right policy (noeviction/allkeys-lru per key class) and size memory; verify persistence.",
        ],
        [
            "Set allkeys-lru on a store holding must-keep data.",
            "Just raise maxmemory and ignore the policy mismatch.",
        ],
        [
            "Policy must match data semantics (cache vs store).",
            "Separate volatile from durable keys.",
        ],
        [
            "Classify keys + read policy",
            "Set correct eviction policy + memory",
            "Verify durable keys survive",
        ],
        ["Split cache and durable data into separate instances with different policies."],
        ["A missing TTL makes cache keys count as durable, driving eviction."],
        ["db", "redis", "eviction"],
    ),
    (
        "databases",
        "recover a MongoDB replica set that lost primary quorum",
        "Un replica set MongoDB ha perso il quorum e nessun nodo e' primario (solo secondari). Ripristina un primario in sicurezza senza divergenza.",
        [
            "No-primary means lost quorum — restore a voting majority before forcing anything.",
            "Assess node states and the most up-to-date secondary; prefer restoring quorum over force-reconfig.",
            "Reconfigure to regain a majority (or force with the freshest node), verify a single primary and no rollback surprises.",
        ],
        [
            "Force-reconfig to the wrong node, losing recent writes.",
            "Bring back a stale node as primary.",
        ],
        [
            "Restore quorum first; force-reconfig is last resort.",
            "Pick the freshest secondary if forcing.",
        ],
        [
            "Assess node freshness/state",
            "Restore quorum (or force freshest)",
            "Verify single primary + no data loss",
        ],
        ["Add/repair an arbiter to restore an odd voting count."],
        ["A hidden/delayed member miscounts toward the majority."],
        ["db", "mongodb", "quorum"],
    ),
    (
        "proxy",
        "fix websocket/long-lived connections dropped by the proxy",
        "Il reverse proxy chiude le connessioni WebSocket/long-lived per timeout o upgrade header mancante. Ripristina il supporto senza allungare i timeout ovunque.",
        [
            "Dropped websockets are usually a missing Upgrade/Connection header pass-through or a too-short read timeout.",
            "Confirm the proxy forwards the upgrade headers and the timeout suits long-lived streams.",
            "Fix header pass-through + a scoped timeout for the ws route; verify a long-lived connection holds.",
        ],
        [
            "Raise all timeouts globally to mask it.",
            "Miss that the Upgrade header isn't forwarded.",
        ],
        [
            "Websockets need Upgrade/Connection headers passed through.",
            "Scope timeouts to the ws route.",
        ],
        [
            "Confirm header pass-through + timeout",
            "Fix them for the ws route",
            "Verify a long-lived connection holds",
        ],
        ["Use a dedicated location/route block for websocket endpoints."],
        ["Buffering on the proxy breaks streaming even when headers are right."],
        ["proxy", "websocket", "timeout"],
    ),
    (
        "iac",
        "fix a Helm release stuck in a failed/pending-upgrade state",
        "Una release Helm e' bloccata in stato failed/pending-upgrade e ogni upgrade fallisce. Riportala a uno stato sano senza cancellare risorse in uso.",
        [
            "A stuck Helm release has a bad stored revision blocking new upgrades — reconcile the release state, don't delete live resources.",
            "Inspect the release history and what left it pending (a failed hook, a timeout).",
            "Roll back to the last good revision or repair the pending state; verify a clean subsequent upgrade.",
        ],
        [
            "helm delete the release, taking down live resources.",
            "Force an install over a broken release.",
        ],
        [
            "The release history shows the bad revision.",
            "Rollback beats delete-and-reinstall for live workloads.",
        ],
        [
            "Inspect release history",
            "Rollback / repair the pending state",
            "Verify a clean upgrade",
        ],
        ["Manually correct the release secret/state if rollback can't proceed."],
        ["A failed pre-upgrade hook leaves the release wedged."],
        ["iac", "helm", "release"],
    ),
    (
        "cloud",
        "debug cloud-init failing to configure a new instance",
        "Una nuova istanza non si configura: cloud-init fallisce a meta'. Diagnostica dove e perche' e rendi il provisioning affidabile.",
        [
            "cloud-init failing mid-way leaves a half-provisioned host — read its logs to find the failing module.",
            "Identify the failing stage/module (network, packages, user-data script) from the cloud-init logs.",
            "Fix the failing unit (idempotently) and re-run that stage; verify a clean provision from scratch.",
        ],
        [
            "Manually fix the one instance and never fix the template.",
            "Assume the image is broken when user-data failed.",
        ],
        [
            "cloud-init logs pinpoint the failing module and stage.",
            "user-data scripts should be idempotent.",
        ],
        [
            "Read cloud-init logs",
            "Fix the failing module idempotently",
            "Verify a clean provision from scratch",
        ],
        ["Test the user-data locally with cloud-init's schema/validation before launch."],
        ["A metadata-service timeout, not the script, fails provisioning."],
        ["cloud", "cloud-init", "provisioning"],
    ),
    (
        "security",
        "remediate a sandbox escape / over-broad container capability",
        "Un container ha capability/montaggi troppo ampi (rischio escape). Riduci la superficie mantenendo il funzionamento del workload.",
        [
            "Over-broad capabilities/mounts widen the escape surface — reduce to the minimum the workload proves it needs.",
            "Enumerate the granted capabilities/mounts and which the app actually uses.",
            "Drop the rest (cap-drop ALL + add-back, read-only mounts, seccomp); verify the workload still works.",
        ],
        ["Run --privileged because it's easier.", "Keep CAP_SYS_ADMIN 'just in case'."],
        [
            "Drop ALL then add back only what's used.",
            "Read-only root + seccomp shrink the surface.",
        ],
        [
            "Enumerate current caps/mounts vs usage",
            "Drop to minimum + add seccomp",
            "Verify workload still works",
        ],
        ["Adopt a hardened runtime profile (gVisor/rootless) for defense in depth."],
        ["A capability is needed only at startup — grant narrowly or via an init step."],
        ["security", "container", "capabilities"],
    ),
    (
        "filesharing",
        "fix NFS performance collapse under concurrent clients",
        "Le performance NFS crollano con molti client concorrenti (sync/wsize/attr-cache). Individua il collo di bottiglia e ripristina il throughput in sicurezza.",
        [
            "NFS collapse under concurrency is usually sync semantics, small rsize/wsize, or attribute-cache thrash — not raw disk.",
            "Measure where time goes (server IO vs network vs metadata) and the mount options in play.",
            "Tune the specific bottleneck (rsize/wsize, actimeo) without unsafe async that risks data on crash.",
        ],
        [
            "Switch to async to 'speed it up', risking data on a crash.",
            "Blame the disk without measuring metadata load.",
        ],
        [
            "Small rsize/wsize and attr-cache thrash hurt concurrency.",
            "async is fast but unsafe on crash.",
        ],
        [
            "Measure the bottleneck",
            "Tune rsize/wsize/actimeo safely",
            "Verify throughput under concurrency",
        ],
        ["Scale out with pNFS/multiple exports if a single server is the wall."],
        ["The metadata (getattr) load, not data, saturates under many clients."],
        ["nfs", "performance", "concurrency"],
    ),
    (
        "git",
        "recover from a corrupted packfile in a shared repository",
        "Un packfile corrotto in un repository condiviso causa errori fetch/checkout. Recupera gli oggetti mancanti senza perdere cronologia.",
        [
            "A corrupt packfile is usually recoverable by refetching the bad objects from a healthy peer — history survives.",
            "Run fsck to identify the corrupt/missing objects, then fetch them from a good clone/remote.",
            "Repair the object store and repack; verify integrity without rewriting history.",
        ],
        [
            "Re-clone and lose local-only branches without saving them.",
            "Ignore fsck errors until checkout breaks.",
        ],
        ["git fsck names the bad objects.", "A healthy peer has the missing objects to refetch."],
        ["fsck to find bad objects", "Refetch from a healthy peer", "Repack + verify integrity"],
        ["Restore the packfile from a backup/mirror if no clone has the objects."],
        ["The corruption is in a rarely-accessed old object, surfacing only on a full clone."],
        ["git", "packfile", "corruption"],
    ),
    (
        "performance",
        "diagnose swap thrashing that makes a host unresponsive",
        "Un host e' quasi irresponsivo per swap thrashing: la memoria e' sovraccarica e il paging domina. Stabilizza senza uccidere ciecamente processi critici.",
        [
            "Thrashing = working set exceeds RAM, so paging dominates — relieve pressure, don't just kill at random.",
            "Identify the memory hog and whether swap is undersized or a leak drives it.",
            "Relieve pressure (bound the hog, add RAM/swap headroom) and set limits so one process can't thrash the host.",
        ],
        [
            "kill -9 processes blindly under pressure, hitting a critical one.",
            "Add huge swap, masking a leak with slow death.",
        ],
        [
            "Thrashing shows as high major-fault rate + swap IO.",
            "Bound the hog with a cgroup limit.",
        ],
        [
            "Identify the hog + swap sizing",
            "Relieve pressure + set per-service limits",
            "Verify responsiveness returns",
        ],
        ["Use a memory cgroup / earlyoom so the offender is capped before the host thrashes."],
        ["A memory-mapped file, not anonymous memory, drives the paging."],
        ["perf", "swap", "thrashing"],
    ),
    (
        "networking",
        "fix ARP/neighbor cache issues causing wrong-host delivery",
        "Il traffico verso un host arriva a un host sbagliato per una voce ARP/neighbor stale o un IP duplicato. Individua e correggi senza flush ciechi ripetuti.",
        [
            "Wrong-host delivery points at a stale ARP/neighbor entry or a duplicate IP on the segment.",
            "Inspect the ARP/neighbor table and detect duplicate IPs (who answers for the address).",
            "Fix the root (remove the duplicate / correct the binding); a flush alone recurs if the duplicate remains.",
        ],
        [
            "Flush ARP repeatedly without finding the duplicate IP.",
            "Blame DNS for an L2 delivery problem.",
        ],
        [
            "arping reveals if two MACs claim one IP.",
            "A flush is temporary if the duplicate stays.",
        ],
        [
            "Inspect ARP/neighbor + detect duplicate IP",
            "Remove the duplicate / fix binding",
            "Verify correct delivery",
        ],
        ["Enable duplicate-address detection / port security on the switch."],
        ["A VRRP/HA pair mis-config makes two hosts answer for the VIP."],
        ["net", "arp", "duplicate-ip"],
    ),
    (
        "services",
        "fix a systemd/launchd unit that restarts too fast and gets rate-limited",
        "Un servizio va in crash-loop e il manager lo blocca per start-limit. Individua la causa del crash e ripristina, senza solo alzare il limite.",
        [
            "A start-limit block is the manager protecting you from a crash loop — the fix is the crash, not the limit.",
            "Read why it crashes each start (logs) before touching restart settings.",
            "Fix the crash cause; reset the failed state; only then tune restart policy if genuinely needed.",
        ],
        [
            "Raise StartLimitBurst so it loops forever silently.",
            "Reset the counter without fixing the crash.",
        ],
        [
            "The start-limit is a symptom of a crashing service.",
            "Fix the crash, then reset-failed.",
        ],
        [
            "Read the per-start crash reason",
            "Fix the crash cause",
            "Reset failed state + verify stable",
        ],
        ["Add a backoff (RestartSec) once the real crash is fixed, as hygiene."],
        ["The crash is a missing dependency that appears only after boot."],
        ["services", "crashloop", "startlimit"],
    ),
    (
        "storage",
        "fix a full inode table on a filesystem with free bytes",
        "Le scritture falliscono anche se 'df' mostra spazio libero: gli inode sono esauriti (milioni di file piccoli). Recupera senza cancellare dati vivi.",
        [
            "Writes fail with free bytes = inode exhaustion (too many small files) — bytes and inodes are separate limits.",
            "Confirm inode usage and locate the directory generating millions of files.",
            "Reclaim safely (clean the offender's churn, archive) or migrate to a filesystem sized for more inodes.",
        ],
        ["Keep looking at byte free space and miss inodes.", "Delete live data to free inodes."],
        [
            "df -i shows inode usage separately.",
            "A cache/session dir often generates the file explosion.",
        ],
        [
            "Confirm inode exhaustion (df -i)",
            "Find + clean the file-churn source",
            "Verify writes; prevent recurrence",
        ],
        [
            "Recreate the filesystem with a higher inode ratio if the workload legitimately needs it."
        ],
        ["The offender is a mail/session/cache dir with millions of tiny files."],
        ["storage", "inodes", "smallfiles"],
    ),
    (
        "env_path",
        "fix locale/encoding misconfiguration corrupting text processing",
        "Configurazione locale/encoding errata corrompe l'elaborazione di testo (UTF-8 vs Latin-1), causando errori e mojibake. Correggi in modo coerente.",
        [
            "Text corruption/mojibake is a locale/encoding mismatch between the data and the environment.",
            "Identify the actual encoding of the data vs the locale the tools assume.",
            "Set a consistent UTF-8 locale (or convert the data) end to end; verify correct round-trips.",
        ],
        [
            "Set LANG randomly until it 'looks right' on your terminal only.",
            "Convert data in place without a backup.",
        ],
        [
            "The data's real encoding vs the assumed locale is the mismatch.",
            "Make the whole pipeline UTF-8.",
        ],
        [
            "Detect data encoding vs locale",
            "Set consistent UTF-8 / convert data",
            "Verify correct round-trip",
        ],
        ["Normalize input to UTF-8 at ingestion so downstream is always consistent."],
        ["A service inherits C locale under the manager, differing from your shell."],
        ["env", "locale", "encoding"],
    ),
    (
        "recovery",
        "reconstruct a deleted config from a running process's memory/fds",
        "Un file di configurazione critico e' stato cancellato ma il processo che lo usa e' ancora in esecuzione. Ricostruisci la config dai suoi fd/memoria prima di riavviare.",
        [
            "A deleted config still used by a running process is often recoverable from its open fd or memory — do NOT restart yet.",
            "Locate the process holding the deleted file and read it back via /proc/<pid>/fd (or its loaded state).",
            "Restore the file from that source, verify, THEN it's safe to restart.",
        ],
        [
            "Restart the process first, permanently losing the recoverable file.",
            "Rebuild from memory without verifying.",
        ],
        [
            "/proc/<pid>/fd can still read a deleted-but-open file.",
            "Never restart before recovering.",
        ],
        ["Find the holding process", "Recover the file via its fd", "Verify, then restart safely"],
        ["Dump the process memory and extract the loaded config if no fd holds the file."],
        ["The process read the config once and closed the fd — memory is the only source."],
        ["recovery", "deleted-config", "proc"],
    ),
]


@register("hard_tasks", ["linux", "windows", "macos"])
def hard_tasks():
    for os in ("linux", "windows", "macos"):
        for (
            domain,
            short,
            goal,
            reasoning,
            mistakes,
            hints,
            reference,
            alternative,
            edge,
            tags,
        ) in HARD_TASKS:
            yield _task(
                os,
                domain,
                "hard",
                short,
                goal,
                scenario=(
                    f"On {os}, a hard operational problem: {goal} Requires methodical diagnosis; the naive "
                    f"one-line fix is wrong or masks the cause."
                ),
                reasoning=reasoning,
                cmds=[f"# {os}-appropriate diagnostic + fix sequence for: {short}"],
                forbidden=[
                    r"reboot\s*#.*to clear",
                    r"chmod\s+-R\s+777",
                    r"--force\b.*#.*blind",
                    r"rm\s+-rf\s+/(\s|$)",
                ],
                safety=[
                    "Diagnose before acting; no blind reboots/kills.",
                    "Least-privilege, reversible change; capture prior state.",
                    "Do not mask the symptom or weaken security.",
                ],
                success_criteria=f"The '{short}' problem is genuinely resolved (root cause fixed and verified), not masked.",
                success=Verify(kind="artifact", path=f"hard_{domain}_{tags[-1]}_resolved.txt"),
                recovery="Capture prior state before changing it; every step is reversible if recorded.",
                mistakes=mistakes,
                hints=hints,
                reference=reference,
                alternative=alternative,
                edge=edge,
                gt={"task": short, "tier": "hard"},
                tags=["hard"] + tags,
                family="hard_tasks",
            )


@register("expert_tasks", ["linux", "windows", "macos"])
def expert_tasks():
    for os in ("linux", "windows", "macos"):
        for (
            domain,
            short,
            goal,
            reasoning,
            mistakes,
            hints,
            reference,
            alternative,
            edge,
            tags,
        ) in EXPERT_TASKS:
            yield _task(
                os,
                domain,
                "expert",
                short,
                goal,
                scenario=(
                    f"On {os}, an expert-level problem demanding deep causal reasoning: {goal} "
                    f"Multiple plausible causes; only evidence separates them."
                ),
                reasoning=reasoning,
                cmds=[f"# {os}-appropriate deep-diagnosis + remediation for: {short}"],
                forbidden=[
                    r"reboot\s*#.*to clear",
                    r"restore.*over.*production.*#.*untested",
                    r"--force\b.*#.*blind",
                    r"setenforce\s+0",
                    r"DisableRealtimeMonitoring",
                ],
                safety=[
                    "Gather evidence before any irreversible action.",
                    "Preserve data/evidence; snapshot before destructive steps.",
                    "Fix the root cause and add a guardrail; never trade long-term integrity for a quick unblock.",
                ],
                success_criteria=f"The expert problem '{short}' is resolved at the root, verified with evidence, "
                f"with data/integrity preserved.",
                success=Verify(kind="artifact", path=f"expert_{domain}_{tags[-1]}_resolved.txt"),
                recovery="Every irreversible action sits behind a captured rollback point (image/snapshot/backup).",
                mistakes=mistakes,
                hints=hints,
                reference=reference,
                alternative=alternative,
                edge=edge,
                gt={"task": short, "tier": "expert"},
                tags=["expert"] + tags,
                family="expert_tasks",
            )
