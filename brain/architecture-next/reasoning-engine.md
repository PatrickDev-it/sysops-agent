# reasoning-engine.md

> Owner: **inferenza causale, ipotesi, aggiornamento dei belief, selezione della recovery.** È il "System-2"
> del [cognitive-architecture.md](cognitive-architecture.md). Il *dato* belief è in [belief-system.md](belief-system.md).

---

## Responsabilità

1. **Belief update:** da nuove osservazioni, promuovere/refutare belief (OBSERVED→INFERRED→PROVEN/REFUTED).
2. **Causal inference:** costruire catene "sintomo → causa" ancorate ai Fact del World Model.
3. **Hypothesis management:** generare ipotesi diagnostiche, ordinarle per verosimiglianza *e costo di verifica*,
   e scegliere il **probe più informativo** (value-of-information) prima di agire.
4. **Recovery selection:** quando un'azione fallisce, l'error-class (dal Knowledge Graph) **vincola** le recovery
   ammesse (invariante v1: la recovery deriva dall'errore osservato, non è libera).

## Diagnosi come ricerca di ipotesi (non come chat)

```
Sintomo: "il sito è down" (goal)
  H1: servizio nginx down        (verifica: systemctl status — costo basso, info alta) ← si prova prima
  H2: porta 443 occupata da altro(verifica: ss -ltnp)
  H3: cert scaduto               (verifica: openssl/certutil x509 -dates)
  H4: firewall                   (verifica: regole)
Reasoning ordina per P(H)·info/costo → chiede al System Mapper il probe di H1 → aggiorna belief → riordina.
```

Questo è **abduction + active testing**, non un LLM che spara comandi (v1 T070). Il modello propone *ipotesi*
(giudizio), il resto (scelta del probe, esecuzione) è deterministico.

## Solo PROVEN guida azioni distruttive

Un belief INFERRED può guidare un altro *probe*, mai un'azione irreversibile. Il Reasoning Engine è l'unico owner
delle transizioni `belief.*` (single-owner). I REFUTED entrano in una *blocklist* che impedisce di ri-tentare la
stessa assunzione fallita (cura al loop v1).

## Confronto competitor

- **Tutti i competitor** fanno reasoning *implicito* dentro il ReAct loop del modello: nessuna struttura di ipotesi,
  nessun blocco dei REFUTED, nessuna separazione probe/azione. Risultato (osservato in v1 e coerente con Goose su
  modelli piccoli): **flailing** — comandi random cambiando dominio.
- Il nostro reasoning **esplicito + ancorato ai Fact** è il moat #1 ([../100_market/moat.md](../100_market/moat.md)):
  rende un 4B affidabile perché non gli chiediamo di "ragionare bene nel vuoto", ma di scegliere tra ipotesi
  strutturate con evidenza fornita.

## Pattern

Abduction (inference to best explanation) · Active learning / VoI probing · Truth-maintenance (belief revision) ·
Constraint satisfaction (recovery vincolata dall'error-class) · Blackboard knowledge source.

## Alternative scartate

- **Reasoning implicito nel modello (ReAct):** non ispezionabile, non vincolabile, costoso. **Rifiutato** come primario.
- **Regole diagnostiche puramente deterministiche (expert system classico):** non scala all'apertura del dominio
  sysops. **Rifiutato** come *unico* meccanismo — usiamo il modello per *generare* ipotesi, le regole per *vincolarle*.

## Trade-off

- Struttura esplicita = più codice e schema. Ripagato in debuggabilità (ogni diagnosi è una catena ispezionabile) e
  in frugalità (il probe VoI evita azioni inutili).
- Richiede una buona error-ontology (KG). Investimento condiviso col Knowledge Graph.

## Benchmark teorico

Numero di azioni fino alla diagnosi corretta: target **≤ log(#ipotesi)** grazie al probing VoI, vs O(#tentativi)
del flailing. Su un incident tipico: 2–3 probe mirati vs 6–12 tentativi random di v1.

## Evoluzioni

Ipotesi con priori appresi dall'experience store · propagazione bayesiana della confidence · spiegazioni
controfattuali ("se avessi visto X, avrei concluso Y") · reasoning gerarchico per incident multi-causa.
