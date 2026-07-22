# scalability.md

> Owner: **scalare da 1 host a una fleet, e la concorrenza.** Non "più utenti" (non siamo un SaaS) ma **più sistemi
> gestiti da un cervello**.

---

## Tre assi di scala

1. **Verticale (un host, task complessi):** concorrenza interna — probe/azioni indipendenti in parallelo
   ([execution-engine.md](execution-engine.md)); il DAG di piano esprime cosa è parallelizzabile.
2. **Orizzontale (fleet, N host):** un cervello, N runtime remoti. Il [runtime.md](runtime.md) espone SSH con la
   stessa interfaccia del locale → un'azione gira indifferentemente qui o su host-42. Il World Model diventa
   **multi-host** (un sottografo per host + relazioni cross-host: load balancer → backend).
3. **Temporale (nel tempo):** l'experience store rende ogni run più economico del precedente su task ricorrenti.

## Fleet: un cervello, molti corpi

```
                 ┌───────────── Supervisor / engines (uno) ─────────────┐
                 │  Belief State (per-host + fleet-level)                │
                 │  World Model federato · Experience condivisa          │
                 └───────┬───────────────┬───────────────┬──────────────┘
                     runtime(ssh)     runtime(ssh)    runtime(ssh)
                     host-01          host-02          host-42
```

Il ragionamento è centrale; l'esecuzione è distribuita. Un incident cross-host ("il DB è lento → l'app va in timeout
su 3 nodi") si diagnostica sul **grafo di fleet**, non host per host in isolamento. Nessun competitor sysops-AI fa questo.

## Concorrenza e isolamento

- **Bulkhead:** azioni su host diversi isolate; il fallimento di un host non blocca gli altri.
- **Idempotenza** (execution-engine) rende sicura la riesecuzione parziale su fleet.
- **Rate/priority:** azioni ad alto rischio serializzate; probe read-only massimamente paralleli.

## Confronto competitor

- **Tutti i competitor sono single-host, single-repo, interattivi con un dev.** Nessuno è progettato per una fleet.
  Questo è un **white space enorme**: il sysops reale *è* multi-host (server, cluster, VPS). Ci arriviamo perché il
  runtime uniforme locale/SSH e il World Model a grafo lo rendono naturale.
- **Ansible/K8s** scalano ma sono *dichiarativi e non-diagnostici*; noi aggiungiamo il **ragionamento diagnostico**
  sopra la fleet.

## Pattern

Uniform local/remote interface · Bulkhead · Federated graph · Central-brain/distributed-effectors · Idempotent fan-out
· Backpressure/rate-limiting.

## Alternative scartate

- **Un agente per host (N cervelli):** N× costo di modello, nessuna visione cross-host, esperienza non condivisa.
  **Rifiutato** — un cervello, molti corpi.
- **Architettura cloud multi-tenant:** viola sovranità; non è il nostro modello. **Rifiutato.**

## Trade-off / Benchmark / Evoluzioni

Trade-off: un cervello centrale è un single-point-of-failure per la fleet → mitigazione: lo stato è persistente
(World Model/experience su disco), il cervello è ricostruibile; le azioni sono idempotenti. Benchmark: latenza di
diagnosi cross-host, # host gestiti per cervello. Evoluzioni: cervelli replicati con stato condiviso, gerarchia di
supervisori (regionali), consenso per azioni fleet-wide ad alto rischio.
