# future-research.md

> Owner: **le domande aperte e le direzioni di ricerca oltre v2.** Cosa potrebbe rendere Sistemista dominante — o
> obsoleto — nei prossimi 5 anni.

---

## Direzioni di ricerca (ordinate per leva)

1. **Learned Value-of-Information scheduling.** Lo scheduler cognitivo decide cosa pensare dopo. Oggi euristico;
   apprendere la stima del valore dall'experience store lo renderebbe il vero differenziatore. *Ref: active
   inference, expected value of information.*
2. **Distillazione di un modello sysops-nativo.** Un 3B/7B distillato sui trace di Sistemista (Fact→decisione) che
   emette nativamente piani-DAG e query-al-grafo → meno escalation, più frugalità. *Ref: agent distillation,
   process supervision.*
3. **Grammar-constrained decoding come default.** Forzare lo schema (Fact, piano, query) a livello di decoding rende
   affidabile anche un 3B. *Ref: constrained/structured decoding, GBNF.*
4. **World Model come simulatore.** Se il grafo cattura abbastanza semantica, si può *simulare* l'effetto di
   un'azione prima di eseguirla (dry-run cognitivo per azioni irreversibili). *Ref: model-based RL, digital twin.*
5. **Federated experience (privacy-preserving).** Playbook/pattern condivisi tra installazioni senza esporre dati di
   sistema → l'esperienza di tutti migliora ciascuno. *Ref: federated learning, differential privacy.*
6. **Neuro-symbolic reasoning.** Il KG (simbolico) + il modello (neurale) in un loop stretto: il modello propone,
   il simbolico verifica/vincola. È già la nostra direzione; formalizzarla. *Ref: neuro-symbolic AI.*
7. **Meta-cognizione / calibrazione.** Il sistema stima la *propria* confidence e decide quando escalare, quando
   chiedere all'umano, quando fermarsi. *Ref: LLM calibration, selective prediction.*
8. **Prompt-injection defense per output non fidati.** File di config/log possono contenere payload avversari; il
   reasoning deve trattarli come dati non fidati. *Ref: indirect prompt injection.*

## Domande aperte (oneste)

- Qual è il **modello locale minimo** che emette piani-DAG affidabili con grammar-constrained decoding? 3B basta o
  serve 7B? (Determina il vincolo hardware reale.)
- Il **World Model a grafo** scala a sistemi enormi (migliaia di container/servizi) senza diventare il collo di
  bottiglia che voleva eliminare?
- L'**experience store** generalizza tra parchi macchine diversi, o diventa overfit al singolo ambiente?
- Fino a che punto la **compilazione del contesto** può spingere il rapporto segnale/token prima di perdere
  informazione critica?
- La **fleet centralizzata** (un cervello, N corpi) è il modello giusto, o serve gerarchia/decentralizzazione?

## Cosa ci renderebbe obsoleti (e come rispondere)

- **Modelli locali che diventano enormemente più capaci e economici** → molta della nostra ingegneria di frugalità
  perde valore. *Risposta:* il World Model, l'experience store e lo Zero-Trust restano validi a qualsiasi taglia di
  modello; la frugalità diventa margine, non sopravvivenza.
- **Un leader open-source che apre un verticale sysops** → *Risposta:* velocità su M5 (experience) e sovranità/fleet,
  difficili da replicare per un cloud-agent.
- **Uno standard di "agent-OS" (MCP-like) che commoditizza i runtime** → *Risposta:* adottarlo come adapter; il
  nostro valore è il *cervello* (reasoning+world-model+experience), non il trasporto.

## Ponte col resto del brain

Queste direzioni alimentano [../700_research/README.md](../700_research/README.md) (indice paper) man mano che
influenzano decisioni reali (ogni idea adottata → una entry in [.sinapsi/decisions.md](../../.sinapsi/decisions.md)).
Regola invariata: *non si cita un paper come autorità, si cita la decisione che ha cambiato.*
