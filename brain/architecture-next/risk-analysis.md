# risk-analysis.md

> Owner: **i rischi dell'architettura v2 e della migrazione, con mitigazioni.** Onestà brutale: dove questo design
> può fallire.

---

## Rischi architetturali

| # | Rischio | Prob. | Impatto | Mitigazione |
|---|---|---|---|---|
| R1 | **Over-engineering:** troppi engine/confini → lentezza di sviluppo, il "brain" diventa un mostro peggiore del god-object | Alta | Alto | Strangler incrementale; ogni engine deve guadagnarsi il posto con una metrica; partire dai 4 componenti core (belief, observation, system-map, context) prima del resto |
| R2 | **Il Context Engine non regge la promessa** (ranking omette fatti critici → il modello sbaglia) | Media | Alto | Il ciclo è iterativo (gap → recupero al giro dopo); ranking migliora dall'esperienza; fallback a snapshot bounded; misurare su ARR, non a occhio |
| R3 | **Lo scheduler VoI è difficile da tarare** (stima del valore sbagliata → decisioni subottimali) | Media | Medio | Iniziare con euristiche semplici e trasparenti; apprendere i pesi dall'experience *dopo*, non prima; è deterministico → debuggabile |
| R4 | **Il World Model diverge dalla realtà** (TTL sbagliati → agire su mappa stale) | Media | Alto | TTL conservativi + ri-probe prima di azioni ad alto rischio; il Validator verifica gli effetti reali, non la mappa |
| R5 | **Schema/Fact troppo rigidi** → attrito quando il mondo non entra nello schema | Media | Medio | Fact estendibili + `raw` bounded come valvola di sfogo con `confidence:low`; lo schema evolve dall'uso |
| R6 | **Il modello locale 3B/4B non emette struttura affidabile** (piani DAG, schema output) | Alta | Alto | Grammar-constrained decoding / JSON schema forzato; il modello sceglie *intenti*, non sintassi; escalation a 8B su schema-violation |

## Rischi di migrazione

| # | Rischio | Mitigazione |
|---|---|---|
| M-R1 | Riscrittura big-bang che non converge mai | **Strangler fig obbligatorio**: v2 dietro interfacce v1, un modulo alla volta, ognuno validato |
| M-R2 | Perdere i pezzi buoni di v1 (pyte, invarianti, error-classifier) nella foga di riscrivere | Mappa esplicita MANTIENI in [migration-plan.md](migration-plan.md); quei moduli si portano, non si rifanno |
| M-R3 | Nessuna baseline ARR → non sappiamo se v2 migliora | **M0 misura l'ARR di v1 prima di toccare nulla** |
| M-R4 | Regressione di sicurezza durante il refactor del safety gate | Il risk-vector si affianca al gate v1; si spegne il vecchio solo quando il nuovo è validato su casi distruttivi |

## Rischi strategici / di prodotto

| # | Rischio | Mitigazione |
|---|---|---|
| S1 | Un leader (Claude Code/OpenHands) aggiunge un verticale sysops e ci schiaccia | Il nostro moat è cumulativo (experience store locale) + sovranità; difficile da replicare per un cloud-agent. Muoversi veloci su M5 |
| S2 | Il dominio sysops autonomo spaventa (rischio in produzione) → adozione lenta | Zero-Trust + explainability + CONFIRM come *feature di fiducia*, non ostacolo; iniziare da task read-only/diagnosi |
| S3 | Complessità dell'architettura scoraggia i contributor open-source | Confini netti + single-owner + doc (questo set) = onboarding chiaro; ogni engine è un modulo isolato contribuibile |

## Il rischio numero uno, nominato

> **R1 (over-engineering) è il rischio dominante.** La tentazione di costruire 20 engine perfetti prima che qualcosa
> funzioni è la morte del progetto. **Contromisura non negoziabile:** l'ordine di M1–M4 costruisce solo lo *spine
> minimo* (belief → observe → map → context → brain). Learning/fleet/security avanzata vengono *dopo* che il core
> alza l'ARR misurata. Se una parte di questo design non si guadagna il posto con una metrica, **non si costruisce**.

## Trade-off consapevole

v2 sposta complessità *dal modello* (che teniamo piccolo) *al nostro codice deterministico* (scheduler, context,
state). È una scommessa: che il codice deterministico testabile batta la "magia" di un ReAct loop su modello grande.
È la scommessa giusta per il vincolo locale/piccolo — ma va **verificata sull'ARR**, non assunta.
