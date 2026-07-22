# Verification Model — Expected Verification & Expected Recovery

> **Owner** di `VerificationKind` e `RecoveryClass`, e del formalismo con cui una Decision dichiara
> *come sarà verificata* e *come sarà recuperata* (campi 20–21 di [decision-model.md](decision-model.md)).
> Mappa sul runtime: [_artifact_check](../../workspace/src/orchestrator.py),
> `observe_judge`/[supervisor.verify](../../workspace/src/supervisor.py),
> [behavior_verifier](../../workspace/src/tools/behavior_verifier.py), e
> [error_classifier](../../workspace/src/error_classifier.py).

---

## 1. Principio

Una Decision è **incompleta** se non dichiara come verrà giudicata. La mission richiede che ogni
Decision porti `expected_verification` ed `expected_recovery`: senza, il sistema può dichiarare "fatto"
senza prova (invariante #9: *l'artifact check sovrascrive l'exit code*; red flag AGENTS.md:
*claim_completion_without_verify* è globalmente vietato in `error_classifier.FORBIDDEN_ALWAYS`).

---

## 2. `VerificationKind` (enum chiuso)

Il *tipo* di verifica attesa per una Decision, ordinato dal più debole (structural) al più forte
(behavioral) — allineato ai tre tier di [state.py::DesiredState](../../workspace/src/state.py).

| `VerificationKind` | Cosa controlla | Motore runtime | Tier |
|--------------------|----------------|----------------|------|
| `NONE` | nulla (no-op / SKIPPED) | — | — |
| `EXIT_CODE` | il comando è uscito 0 | `run_ok` | debole |
| `ARTIFACT_EXISTS` | il file previsto esiste | `_artifact_check` exists() | 1 structural |
| `ARTIFACT_CONTENT` | il file contiene il valore atteso **verbatim** | `_artifact_check` contains_string() | 1 structural |
| `CAPABILITY_PRESENT` | il tool è su PATH / belief `x:exists` PROVEN | `is_executable()` / belief | 2 capability |
| `BEHAVIORAL` | uno smoke-test conferma operatività | `behavior_verifier` | 3 behavioral |
| `SEMANTIC_JUDGE` | il verifier LLM giudica il soddisfacimento dei criteri | `supervisor.verify` | trasversale |

Regola **VER-1 (verifica minima per Intent)**: ogni `IntentClass`
([strategy-model.md](strategy-model.md)) ha una `VerificationKind` **minima** richiesta. Una Decision
la cui `expected_verification` è più debole del minimo del suo Intent è un difetto
`MISSING_VERIFICATION`, misurabile prima dell'esito:

| `IntentClass` | `VerificationKind` minima |
|---------------|---------------------------|
| `OBSERVE_AND_REPORT` | `ARTIFACT_CONTENT` (il contenuto deve essere il valore osservato, non solo esistere) |
| `PROVISION` | `CAPABILITY_PRESENT` |
| `REPAIR` | `BEHAVIORAL` |
| `CONFIGURE` | `ARTIFACT_CONTENT` |
| `SCAFFOLD` | `BEHAVIORAL` (o `ARTIFACT_EXISTS` se il criterio è solo strutturale) |
| `MUTATE_STATE` | `BEHAVIORAL` |
| `REFUSE` | `NONE` (il successo è l'assenza di azione) |

Questo formalizza il **wrong-completion-assumption** già codificato in `behavior_verifier`
(`is_wrong_completion_assumption`): passare il tier 1 (`ARTIFACT_EXISTS`) ma non il tier 3
(`BEHAVIORAL`) su un Intent `REPAIR` è un gap di verifica *pianificato*, non un caso.

---

## 3. `RecoveryClass` (enum chiuso) — allineato a error_classifier

`expected_recovery` è **derivato**, non inventato: è esattamente
`error_classifier.allowed_recoveries(class)` per la `ErrorClass` che la Decision rischia. Questo
rispetta l'invariante #4 (*recovery deriva dall'errore osservato*) e riusa le tabelle già in produzione
([error_classifier.py](../../workspace/src/error_classifier.py)):

| `ErrorClass` (rischiata) | `RecoveryClass[]` attese (da `ALLOWED_RECOVERIES`) |
|--------------------------|----------------------------------------------------|
| `INVALID_EXECUTABLE` | delete_corrupt_binary · reinstall · discover_real_path |
| `FILE_NOT_FOUND` | locate · install · create_parent_dirs · use_alternative_path |
| `PERMISSION_DENIED` | fix_permissions · run_as_admin · use_user_install |
| `PACKAGE_NOT_FOUND` | search_registry · install_alternative · use_prebuilt_wheel |
| `NETWORK_ERROR` | retry · use_offline_cache · change_registry_mirror |
| `ENV_SCOPE_MISMATCH` | install_globally · activate_venv · use_absolute_path |
| `COMMAND_SYNTAX` | correct_flags · use_alternative_command · run_discovery_for_syntax |
| `TIMEOUT` | retry_with_longer_timeout · split_into_smaller_steps |
| `UNKNOWN` | ∅ → escalation umana (nessuna recovery automatica) |

Più il vincolo globale `FORBIDDEN_ALWAYS`: `write_placeholder`, `overwrite_executable`,
`create_fake_output`, `claim_completion_without_verify` — **mai** ammessi come `expected_recovery`,
qualunque `ErrorClass`.

---

## 4. Difetti di verifica/recovery (analisi)

| Difetto | Definizione | Rilevazione |
|---------|-------------|-------------|
| `MISSING_VERIFICATION` | `expected_verification` più debole del minimo dell'Intent, **o** stadio `VERIFICATION` assente dalla trace | confronto con tabella VER-1 |
| `WEAK_VERIFICATION` | verifica presente ma un tier sotto il necessario (es. `ARTIFACT_EXISTS` su OBSERVE che richiede `ARTIFACT_CONTENT`) | tier compare |
| `RECOVERY_MISMATCH` | recovery tentata ∉ `allowed_recoveries(class)` | set membership |
| `FORBIDDEN_RECOVERY` | recovery ∈ `FORBIDDEN_ALWAYS` | set membership |
| `PREMATURE_VERIFY` | `VERIFY` di un target il cui `install`/`produce` è ancora `REFUTED` | belief check (rule `_rule_install_fail_blocks_verify`) |
| `REDUNDANT_VERIFY` | `VERIFY` di ciò che è già PROVEN (skippato da `ExecutionPolicyGuard`) | policy log |

`WEAK_VERIFICATION` è la firma diretta del difetto centrale del corpus D1: l'artifact check di
WIN-ENV_PATH-00001 dà `exists+nonempty` (tier 1) e passa, ma il contenuto è il placeholder
`PATH_CONTENT` — la verifica *avrebbe dovuto* essere `ARTIFACT_CONTENT` contro il valore osservato. Il
file [WIN-ENV_PATH-00001.json](../../workspace/validation/windows-lab/failure-db/WIN-ENV_PATH-00001.json)
mostra proprio `success_check.kind="artifact"` ok=true con verdict INCOMPLETE: verifica strutturale
verde, verifica di contenuto assente. Il framework rende questo gap **tipizzato**, non aneddotico.

---

## 5. Output

Le violazioni di questo modello confluiscono in
[reports/root-cause-analysis.md](reports/root-cause-analysis.md) (come `DivergenceCause` di tipo
`MISSING_VERIFICATION`) e pesano nell'`ArchitecturalComponent` `VERIFICATION`. Un `MISSING_VERIFICATION`
sistematico su un Intent è candidato ad alta leva: aggiungere il tier minimo alla scomposizione del
goal alza il FTFR senza nuove capability.

Invariante **VER-2**: `expected_recovery` non è mai una lista libera — è sempre la proiezione di
`allowed_recoveries`. Nessun documento di questo framework introduce recovery fuori da quelle tabelle
(single owner: `error_classifier`).
