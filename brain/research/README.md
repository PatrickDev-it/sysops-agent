# research/ — knowledge base esterna

> Owner: **conoscenza grezza sul mondo esterno** (competitor, e in futuro benchmark/repo).
> Distinzione dagli altri nodi:
> - `research/competitors/` = **competitive intelligence** (schede tecniche per progetto + matrici + ranking).
> - `700_research/` = **indice dei paper** che hanno influenzato il *design* (idee, non prodotti).
> - `100_market/` = **posizionamento** (moat, go-to-market) — *cita* research/competitors, non lo copia.

---

## Contenuto

| Sottocartella | Owner di… | Entry point |
|---|---|---|
| [competitors/](competitors/index.md) | schede tecniche dei competitor + matrici + ranking + white space | [competitors/index.md](competitors/index.md) |

## Provenienza & disciplina

Le schede in `competitors/` derivano da **due Deep Research interni** (uno sugli *agenti da terminale*, uno sui
*progetti OSS virali*), **ora rimossi**: il loro contenuto utile è stato consolidato integralmente qui, quindi
ogni scheda è self-contained. Quei Deep Research erano **AI-generated e contenevano dati dubbi/allucinati**.
Regola non negoziabile (ethos "non inventa, confronta"):

- ogni scheda ha un box **affidabilità** (✅ / ⚠️ / 🔴);
- i claim non verificati **non** diventano fatti: restano marcati *claim non verificato* o in quarantena (🔴);
- dove conosco la verità reale, **correggo la fonte** nella scheda (es. autore di Cline, stato di Continue).

Introdotto con la KB competitor → changelog PATCH-007, [DEC-018](../../.sinapsi/decisions.md) / [RFC-0003](../../.sinapsi/rfc/).
