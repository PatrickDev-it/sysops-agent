# migration-plan.md

> Owner: **il ponte tra v1 e v2 — cosa MANTENERE, cosa RISCRIVERE, cosa ELIMINARE.** Questo è il *secondo* passo del
> mandato: prima si progetta ignorando l'esistente ([architecture.md](architecture.md)), poi lo si confronta col
> codice reale (analisi in [../../.sinapsi/](../../.sinapsi/) + lettura diretta di `workspace/`).

---

## Principio di migrazione: strangler fig, non big-bang

Non riscriviamo tutto in un colpo (rischio catastrofico). Costruiamo v2 **attorno** ai pezzi buoni di v1,
strangolando incrementalmente i pezzi cattivi. Il criterio per ogni modulo v1:

- **MANTIENI** se incarna già un principio v2 ed è pulito.
- **RISCRIVI** se il *concetto* è giusto ma l'implementazione è intrecciata/parziale.
- **ELIMINA** se è morto, duplicato, o contraddice l'architettura.

## Mappa v1 → v2

| Modulo v1 | LOC | Verdetto | Motivo / destinazione v2 |
|---|---|---|---|
| `terminal_runtime/` (pyte, VirtualScreen, PromptDetector, Driver) | ~660 | **MANTIENI** | è già [pty-runtime](pty-runtime.md)+[terminal-runtime](terminal-runtime.md) fatti bene; solo ripulire i confini |
| `state.py` (SystemState, WorldEntity, Fact) | 611 | **RISCRIVI** | concetto giusto (spine RAM); diventa [belief-system](belief-system.md)+[state-engine](state-engine.md) con Fact tipizzati/provenienza/TTL e single-owner |
| `reasoning.py` (BeliefSystem, Inference, Policy) | 1090 | **RISCRIVI** | il moat #1 è qui; splittare in [reasoning-engine](reasoning-engine.md) (inferenza) e le transizioni in state-engine; alleggerire |
| `knowledge/` (OCKE, registry, ranker) | ~1300 | **RISCRIVI→espandi** | è il seme del [knowledge-graph](knowledge-graph.md); generalizzare da "filtro OS" a ontologia interrogabile |
| `error_classifier.py` | 252 | **MANTIENI→espandi** | l'error-ontology serve a reasoning/recovery/KG; aggiungere test |
| `tools/safety_gate.py` | 78 | **RISCRIVI** | da classificatore ternario a [security](security.md) risk-vector ancorato ai Fact |
| `tools/template_guard.py` | 236 | **MANTIENI** | il blocco placeholder è un invariante v2; confluisce nello State Engine |
| `tools/discovery.py` + `capability_registry.py` | ~360 | **RISCRIVI** | diventano il [System Mapper](system-map.md) (probe→grafo) invece di liste piatte |
| `tools/observer.py`/`success_checker.py`/`behavior_verifier.py` | ~1000 | **RISCRIVI→unifica** | un solo [observation-engine](observation-engine.md) (bytes→Fact + Validator) |
| `telemetry.py` + `var/telemetry/*.json` | 51 + ~90 file | **RISCRIVI** | [telemetry](telemetry.md) first-class + aggregatore ARR; i `.json` **non** vanno versionati |
| `model_router.py` | 467 | **RISCRIVI** | diventa il Cost Optimizer di [performance](performance.md) (cascata/escalation) |
| `memory.py` (episodic.db) | 512 | **RISCRIVI** | gerarchia [memory](memory.md) + experience store indicizzato per signature |
| `orchestrator.py` | **1905** | **ELIMINA (scomponi)** | il god-object: la sua logica si redistribuisce in scheduler + engine; **non** sopravvive come file |
| `screen_parser.py` | 521 | **ELIMINA** | **dead code** (importato, mai chiamato); superato da pyte |
| `state_machine.py` | 280 | **ELIMINA** | **dead code** (importato, mai chiamato) |
| `executor.py` + `parser.py` | ~200 | **ELIMINA** | path di esecuzione morto (istanziato, mai invocato) |
| euristiche `_fix_*`/`_translate_*` (in orchestrator) | ~200 | **RISCRIVI** | non regex sparse nel control-flow: diventano un layer System-1 esplicito guidato dal [knowledge-graph](knowledge-graph.md) |

## Sequenza di migrazione (fasi, ognuna validabile end-to-end)

```
F0  Cleanup: elimina il dead code (screen_parser, state_machine, executor, parser) → base pulita. [già fattibile ora: PATCH-008]
F1  Belief spine: Fact tipizzati + State Engine + invarianti centralizzati (da state.py/reasoning.py).
F2  Observation Engine: bytes→Fact unificato (assorbe observer/success_checker/behavior_verifier).
F3  System Mapper + World Model: probe→grafo (da discovery/capability_registry).
F4  Context Engine: compilazione minima sotto budget (il salto di qualità sui token).  ← qui si vede l'ARR salire
F5  Cognitive scheduler + Planning DAG: sostituisce il loop dell'orchestrator.
F6  Knowledge Graph: da OCKE a ontologia interrogabile; sposta le _fix_ heuristics qui come dati.
F7  Learning Engine + experience store; Telemetry first-class con ARR.
F8  Security risk-vector; Runtime SSH (fleet).
```

Ogni fase mantiene il sistema **funzionante** (strangler): v2 cresce accanto a v1 dietro le stesse interfacce, e i
moduli v1 vengono spenti uno alla volta quando il sostituto è validato (RFC/validation cycle del progetto).

## Cosa NON rifare (errori v1 da non ripetere)

- Un orchestrator che accumula tutto → god-object. **v2: scheduler sottile + engine con contratti.**
- Euristiche di correzione modello sparse nel control-flow → palude di casi. **v2: layer System-1 + KG come dati.**
- Contesto accumulato nel prompt → parse-error 4B. **v2: Context Engine, contesto non cresce.**
- Telemetry scritta ma non aggregata → ottimizzazione cieca. **v2: ARR misurata dal giorno 1.**
- Dead code lasciato in albero contro i doc → drift. **v2: F0 parte da qui.**

## Rischi di migrazione → [risk-analysis.md](risk-analysis.md). Sequenza temporale → [roadmap-v2.md](roadmap-v2.md).
