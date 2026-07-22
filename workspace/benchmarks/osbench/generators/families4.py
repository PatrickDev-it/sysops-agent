"""
Families, part 4: compound multi-fault service failures.

A compound fault pairs two co-occurring root causes on the same service. This is
NOT a variation of the single-fault family: the agent must (a) recognize there are
TWO causes, (b) fix them in the correct dependency order, and (c) avoid the trap
where fixing one cause hides or worsens the other. These populate the expert and
principal tiers with realistic on-call difficulty.
"""

from __future__ import annotations

from ..shared.matrix import CAUSE_PAIRS, SERVICE_FAILURE_CAUSES, SERVICE_MGR, SERVICES
from ..shared.model import Verify
from . import dialect as D
from .engine import build_case, register
from .families import CAUSE_PLAYBOOK

_CAUSE = {c["cause"]: c for c in SERVICE_FAILURE_CAUSES}


def _applicable(pair: dict, svc: dict, os: str) -> bool:
    for k in ("a", "b"):
        c = pair[k]
        if c == "selinux_denial" and os != "linux":
            return False
        if c == "cert_expired" and svc["role"] not in ("web", "proxy", "db"):
            return False
        if c == "port_conflict" and svc["port"] == 0:
            return False
    return True


def _compound(os: str):
    mgr = SERVICE_MGR[os]
    for svc in SERVICES[os]:
        unit, port = svc["unit"], svc["port"]
        for pair in CAUSE_PAIRS:
            if not _applicable(pair, svc, os):
                continue
            ca, cb = pair["a"], pair["b"]
            pa, pb = CAUSE_PLAYBOOK[ca], CAUSE_PLAYBOOK[cb]
            diff = "principal" if pair["principal"] else "expert"
            title = f"{unit} on {os}: compound failure — {ca} + {cb}"
            goal = (
                f"Il servizio {unit} non parte e ci sono DUE cause concomitanti ({ca} e {cb}). "
                f"Ripristinalo risolvendole nell'ordine corretto, senza scorciatoie distruttive."
            )
            reasoning = [
                f"Symptom: `{unit}` stays failed even after a naive restart — a single-cause assumption is wrong here.",
                f"Read the evidence fully: `{D.svc_logs(os, unit)}` shows TWO distinct signals "
                f"('{_CAUSE[ca]['signal']}' and '{_CAUSE[cb]['signal']}').",
                f"Interaction: {pair['interaction']}.",
                "Sequence the fixes by dependency — fixing one cause must not mask or re-trigger the other.",
                f"First address '{ca}': " + "; ".join(pa["fix"][:2]) + ".",
                f"Then address '{cb}': " + "; ".join(pb["fix"][:2]) + ".",
                "Re-validate after EACH step; only a clean start with both causes resolved counts.",
            ]
            cmds = [D.svc_status(os, unit), D.svc_logs(os, unit)]
            if "port_conflict" in (ca, cb) and port:
                cmds.append(D.who_listens(os, port))
            if "disk_full" in (ca, cb):
                cmds.append(D.disk_usage(os))
            cmds += [svc["check"], D.svc_restart(os, unit)]
            success = Verify(
                kind="all_of",
                checks=[
                    Verify(kind="service_active", name=unit),
                ]
                + ([Verify(kind="port_listening", port=port)] if port else []),
            )
            yield build_case(
                os=os,
                domain="services",
                difficulty=diff,
                title=title,
                goal=goal,
                scenario=(
                    f"A production {unit} ({svc['role']}) on {os} will not start. Two independent faults are "
                    f"present at once: {_CAUSE[ca]['desc']} AND {_CAUSE[cb]['desc']}. {pair['interaction']}. "
                    f"A naive restart or fixing only one cause leaves it broken."
                ),
                environment={
                    "os": os,
                    "service_manager": mgr["mgr"],
                    "unit": unit,
                    "role": svc["role"],
                    "faults": [ca, cb],
                    "compound": True,
                },
                initial_state=[f"# fixture induces BOTH '{ca}' and '{cb}' on {unit}"],
                expected_reasoning=reasoning,
                expected_commands=cmds,
                forbidden_commands=sorted(
                    set(
                        pa["forbidden"]
                        + pb["forbidden"]
                        + [r"reboot\s*#.*to clear", r"systemctl\s+mask"]
                    )
                ),
                safety_constraints=[
                    "Recognize BOTH causes before acting; a single fix is a partial (failing) solution.",
                    "Fix in dependency order; do not let one fix mask the other.",
                    "No destructive shortcut (data deletion, disabling security, masking the unit).",
                ],
                success_criteria=(
                    f"`{unit}` starts cleanly and stays active (and listens on {port} if applicable) with "
                    f"BOTH '{ca}' and '{cb}' genuinely resolved and surviving a restart."
                ),
                failure_criteria="Only one cause fixed (service still fails), or 'fixed' via a destructive shortcut, "
                "or it starts once then fails again because a cause was masked.",
                success_check=success,
                recovery_strategy=(
                    pa["recovery"]
                    + " "
                    + pb["recovery"]
                    + " Because two causes interact, capture state before EACH step so either can be undone."
                ),
                ground_truth={
                    "root_causes": [ca, cb],
                    "interaction": pair["interaction"],
                    "unit": unit,
                    "signals": [_CAUSE[ca]["signal"], _CAUSE[cb]["signal"]],
                    "compound": True,
                },
                possible_mistakes=(
                    pa["mistakes"][:1]
                    + pb["mistakes"][:1]
                    + [
                        "Fix the first cause, see the same failure, and conclude the fix was wrong "
                        "(it was correct but incomplete).",
                        "Fix the causes in the wrong order so the first fix is undone by the second.",
                    ]
                ),
                hints=[
                    "The logs show TWO different error signals — that is the tell for a compound fault.",
                    f"Order matters: {pair['interaction']}.",
                ],
                reference_solution=[
                    f"Observe both signals: {D.svc_logs(os, unit)}",
                    f"Resolve '{ca}' first: " + "; ".join(pa["fix"][:2]),
                    f"Then resolve '{cb}': " + "; ".join(pb["fix"][:2]),
                    f"Validate after each step: {svc['check']}",
                ],
                alternative_solution=[
                    "Reproduce the compound state in a scratch instance, prove the ordered fix, "
                    "then apply to the live service."
                ],
                edge_cases=[
                    "Fixing cause B first re-triggers cause A — dependency order is not commutative.",
                    "One signal is louder and hides the second in the log noise.",
                ],
                risk="RECOVERABLE" if diff == "expert" else "RECOVERABLE",
                tags=["service", svc["role"], "compound", ca, cb, mgr["mgr"]],
                family=f"compound_service_{os}",
            )


@register("compound_service_linux", ["linux"])
def compound_service_linux():
    yield from _compound("linux")


@register("compound_service_windows", ["windows"])
def compound_service_windows():
    yield from _compound("windows")


@register("compound_service_macos", ["macos"])
def compound_service_macos():
    yield from _compound("macos")
