# Mistral Vibe

> **Fonte:** il Deep Research interno sugli agenti da terminale (§ Mistral Vibe).
> **Affidabilità:** 🔴 **NON VERIFICATO / PROBABILE ALLUCINAZIONE.** Non esiste conferma indipendente di un
> prodotto "Mistral Vibe" con le specifiche del report (lancio 9 dic 2025, modelli "Devstral 2 123B", `pip
> install mistral-vibe`, ~4.6k★). Mistral ha modelli reali (Codestral, Devstral) e offerte di coding, ma
> "Vibe" con questi dettagli è **da trattare come ipotesi, non come fatto**. Scheda mantenuta per completezza
> del corpus, con tutte le affermazioni marcate come *claim-da-report*.

---

## Overview *(claim-da-report, non verificato)*

- **Cos'è:** CLI agent di coding di Mistral, basato sui modelli Devstral.
- **Mission:** automatizzare end-to-end task di codifica con modelli Mistral, nativo da terminale.
- **Vision:** portare Devstral nel workflow CLI con UX ricca.
- **Problema che risolve:** coding agentico da terminale con modelli europei/aperti Mistral.
- **Target:** utenti dell'ecosistema Mistral.
- **Anno:** *report:* 9 dicembre 2025.
- **Autori:** Mistral AI.
- **Licenza:** *report:* Apache-2.0.
- **Repository:** *report:* github.com/mistralai/mistral-vibe (**da verificare l'esistenza**).
- **Sito:** mistral.ai.

## Success Story *(claim-da-report)*

Report: annuncio Mistral (dic 2025), enfasi su Devstral 2 (123B) e automazione end-to-end; ~4.6k★. Traino: brand
Mistral. **Nessuna fonte indipendente per confermare timeline o metriche.**

## Adozione *(claim-da-report)*

~4.6k★ (report). Tutto il resto: non documentato / non verificabile.

## Filosofia progettuale *(inferita dal report)*

- Interattività ricca (slash commands, temi, multimodale).
- Sub-agent e delega di task (`task`).
- Ecosistema Mistral-first.
- Non vuole risolvere: sysops dedicato (generico via `bash`).

## Architettura *(claim-da-report)*

- Tool file/grep (`read`, `edit`, `bash`), slash commands, config in home dir.
- Sub-agent / delega (`task` command), cron interno, storia conversazioni, temi.
- Multimodale (immagini per modelli vision).
- Modelli Mistral (Medium 3.5 / Devstral) via API o locale.
- Plugin/skills per nuovi slash-command.

## Engineering *(claim-da-report)*

Python installabile (pip), dipendenze Node/UV, Docker per Linux. Nessun dettaglio affidabile su pattern/test.

## Reverse Engineering *(speculativo)*

Se reale: architettura ~ mix Goose/Cline (loop tool-use + slash commands). Scelta Python per rapidità;
Mistral-first per verticalizzazione sul proprio modello. **Analisi sospesa in assenza di codice verificabile.**

## Analisi del codice

🔴 **Impossibile:** repository non verificato. Nessuna valutazione di qualità/pulizia/debito possibile.

## UX *(claim-da-report)*

Autocomplete, temi, multimodale, slash commands, voice mode (sperimentale).

## AI Design *(claim-da-report)*

Loop simile a Goose (contesto git, correzione errori, parallelismo), sub-agent, delega. Devstral come modello.

## Sicurezza *(claim-da-report)*

`bash` interno e plugin custom = superficie; supporto Docker. Nessuna analisi affidabile.

## Performance *(claim-da-report)*

Devstral 123B richiede GPU/API cloud significative. Report cita "72% SWE-bench" per i modelli Mistral — **non verificato**.

## Punti di forza *(se reale)*

Modello Mistral forte, UX ricca, sub-agent/delega, multimodale.

## Debolezze *(se reale)*

Prodotto giovane, community piccola, dipendenze pesanti (Devstral 123B), feature sperimentali; **e soprattutto
incertezza sull'esistenza stessa**.

## Cosa NON copiare

- **Verticalizzazione su un singolo modello proprietario** (Devstral) → contro provider-neutrality.
- (Meta-lezione) **Non trattare claim non verificati come fatti** → questa scheda è l'esempio del perché.

## Cosa vale la pena copiare *(se confermato)*

- **Sub-agent / delega di task** → pattern di scomposizione utile (ma noi lo derivremmo dal reasoning, non da un comando).
- **Slash commands come skill estendibili** → UX di estensione pulita.

## Opportunità

Irrilevante finché non verificato. Se reale, competerebbe con Goose/Cline sul terreno "CLI agent ricco".

## Gap Analysis (vs Sistemista)

Non conducibile in modo affidabile. **Azione:** verificare l'esistenza reale prima di qualsiasi confronto.
Se confermato, si applicherebbero gli stessi gap di Goose (recovery delegata all'LLM, no reasoning ispezionabile).

## Lessons Learned

- **Metodo (la lezione vera qui):** un Second Brain è utile solo se distingue **fatto** da **claim**. Questa
  scheda resta *quarantenata* finché non c'è evidenza. Coerente con l'ethos "non inventa, confronta".

## Fonti

- Deep Research interno sugli agenti da terminale §Mistral Vibe (**unica fonte, non verificata**).
- **Azione richiesta:** cercare github.com/mistralai/mistral-vibe e l'annuncio ufficiale prima di promuovere
  qualsiasi affermazione a fatto.
