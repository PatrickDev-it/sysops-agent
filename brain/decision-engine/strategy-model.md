# Strategy Model — Intent, Strategy, Expected Outcome

> **Owner** delle tassonomie `IntentClass` e `StrategyClass`, del contratto di evidenza per strategia,
> e della classificazione **deterministica** di intent/strategy da una `Decision`. Consumato da
> [decision-model.md](decision-model.md) (campi 3, 5, 10) e dal Trace Builder.

---

## 1. Perché serve una tassonomia di strategia

Il corpus mostra che **21/22 casi comprendono il goal** ma sbagliano la *strategia*
([decision-analysis.md §3](../../workspace/validation/windows-lab/reports/decision-analysis.md)):
`FABRICATE` invece di `DIAGNOSE` (D4), authoring invece di observe. La strategia è quindi una
dimensione di prima classe da tipizzare — misurare "goal compreso" non basta.

Una **Strategy** è il *tipo di approccio* a un obiettivo; è indipendente dal tool. Un **Intent** è il
*tipo di trasformazione del mondo* richiesto dal goal. Sono ortogonali: lo stesso Intent ammette più
Strategy (una corretta, altre no).

---

## 2. `IntentClass` (enum chiuso)

Che cosa il goal chiede di ottenere. Derivabile dal goal + `DesiredState`/`success_criteria`.

| `IntentClass` | Il mondo dopo | Firma nei success_criteria |
|---------------|---------------|-----------------------------|
| `OBSERVE_AND_REPORT` | uno stato **letto** e scritto verbatim in un artefatto | `exists(f)` + `contains_string(f, <valore osservato>)`, `readonly=true` |
| `PROVISION` | una capability/tool reso disponibile | `is_executable(x)` / belief `x:available_globally` |
| `CONFIGURE` | una configurazione portata a un valore target | `contains_string(cfg, target)` |
| `REPAIR` | uno stato rotto riportato a funzionante | behavioral smoke-test verde |
| `SCAFFOLD` | una struttura creata da zero | `dir_not_empty(x)` + manifest |
| `MUTATE_STATE` | uno stato di sistema cambiato (servizio, env) | belief/behavioral |
| `REFUSE` | nessun cambiamento (goal DESTRUCTIVE) | `must_refuse=true` |

`classify_intent(D)` è puramente funzione dei predicati di `expected_outcome` + del flag `readonly`/
`must_refuse` del case → deterministico, nessun modello.

---

## 3. `StrategyClass` (enum chiuso)

Come la Decision affronta l'Intent.

| `StrategyClass` | Descrizione | Intent per cui è *corretta* |
|-----------------|-------------|------------------------------|
| `OBSERVE_AND_REPORT` | osserva un valore, lo rende fatto PROVEN, lo scrive verbatim | `OBSERVE_AND_REPORT` |
| `DISCOVER_CAPABILITY` | prova l'esistenza di un tool prima di usarlo | qualunque, come pre-fase |
| `DIAGNOSE_THEN_ACT` | isola il fattore divergente, poi corregge solo quello | `REPAIR`, `CONFIGURE` |
| `INSTALL_THEN_VERIFY` | provisiona, poi verifica scope/PATH | `PROVISION` |
| `AUTHOR_ARTIFACT` | genera contenuto plausibile e lo scrive | `SCAFFOLD` (solo) |
| `MUTATE_AND_CONFIRM` | cambia stato di sistema e conferma | `MUTATE_STATE` |
| `REFUSE_AND_EXPLAIN` | rifiuta con motivazione | `REFUSE` |

### Matrice di appropriatezza (deterministica)

`strategy_ok(intent, strategy) = strategy ∈ CORRECT[intent]` dove `CORRECT` è la colonna 3 sopra.
Uno **strategy mismatch** è `strategy ∉ CORRECT[intent]`. Esempi diretti dal corpus:

| Caso | Intent | Strategy usata | mismatch? | Difetto |
|------|--------|----------------|-----------|---------|
| WIN-CICD-00001 | `REPAIR` | `AUTHOR_ARTIFACT` | ✅ sì | D4 FABRICATE |
| WIN-ENV_PATH-00001 | `OBSERVE_AND_REPORT` | `AUTHOR_ARTIFACT` (scrive espressione, non valore) | ✅ sì | D1 |

Il mismatch è la sorgente della `DivergenceCause.WRONG_STRATEGY`
([reasoning-taxonomy.md](reasoning-taxonomy.md)). È misurabile prima di guardare l'esito.

---

## 4. Contratto di evidenza per strategia (`STRATEGY_EVIDENCE`)

Owner della tabella referenziata da [decision-model.md §5](decision-model.md#5-derivazione-di-evidence_required-deterministica).
Ogni strategia dichiara le evidenze *strutturalmente richieste* prima di poter agire:

| `StrategyClass` | Evidenze richieste (oltre ai simboli liberi dell'outcome) |
|-----------------|-----------------------------------------------------------|
| `OBSERVE_AND_REPORT` | il valore osservato deve essere un `fact` PROVEN **prima** dell'EXECUTE di scrittura |
| `DISCOVER_CAPABILITY` | nessuna (è la fase che *produce* evidenza) |
| `DIAGNOSE_THEN_ACT` | un `fact`/`belief` che identifica il fattore divergente **prima** dell'azione correttiva |
| `INSTALL_THEN_VERIFY` | belief `target:scope` noto dopo l'install, prima del verify globale |
| `AUTHOR_ARTIFACT` | nessuna evidenza esterna (per questo è pericolosa fuori da `SCAFFOLD`) |
| `MUTATE_AND_CONFIRM` | belief sullo stato corrente prima della mutazione |
| `REFUSE_AND_EXPLAIN` | `risk == DESTRUCTIVE` da safety_gate |

Questa tabella è ciò che trasforma "il supervisor ha fabbricato" da giudizio soggettivo a
**misura**: `AUTHOR_ARTIFACT` su un Intent `REPAIR` ha `evidence_required` del diagnostico **non
soddisfatta** → `missing_evidence ≠ ∅` → difetto tipizzato.

---

## 5. Classificazione deterministica (algoritmo)

```
classify_strategy(D):
    # 1. Segnali strutturali, in ordine di specificità (primo match vince).
    if D.risk == DESTRUCTIVE and D.chosen_alternative is refusal:  return REFUSE_AND_EXPLAIN
    if D.phase == DISCOVER:                                        return DISCOVER_CAPABILITY
    if produces_artifact(D) and consumes_observed_value(D):        return OBSERVE_AND_REPORT
    if produces_artifact(D) and not consumes_any_evidence(D):      return AUTHOR_ARTIFACT
    if is_install(D):                                              return INSTALL_THEN_VERIFY
    if mutates_system_state(D):                                    return MUTATE_AND_CONFIRM
    if isolates_factor_before_change(D):                           return DIAGNOSE_THEN_ACT
    return AUTHOR_ARTIFACT   # default esplicito, MAI UNKNOWN (DE-8): "produce senza evidenza" è la
                            # classe più conservativa e più spesso corretta come diagnosi del difetto
```

I predicati ausiliari (`produces_artifact`, `consumes_observed_value`, `is_install`,
`mutates_system_state`) sono definiti su campi Decision (`facts_produced`, `evidence_available`,
`capabilities_used`, `expected_outcome`), mai su stringhe di comando specifiche. `is_install`/
`mutates_system_state` si appoggiano a `error_classifier`/`capability kind`, non a un catalogo di tool.

Invariante **STRAT-1**: `classify_strategy` e `classify_intent` sono funzioni pure e totali → nessun
`UNKNOWN` quando i campi bastano (DE-8). L'esito è ripetibile su release diverse (DE-1/DE-5).
