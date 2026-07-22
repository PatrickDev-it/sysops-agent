# RFC 004 — Public Staging Baseline

> Stato: **IMPLEMENTATA LOCALMENTE / VERIFICA REMOTA IN CORSO**, 2026-07-22. Priorità P0.
> Il developer ha autorizzato la
> pubblicazione anticipata per ottenere un URL stabile, purché il repository sia
> presentato come alpha sperimentale e superi i gate minimi sotto.

## Context

Sistemista ha una tesi tecnica credibile — runtime deterministico attorno a due piccoli
modelli GGUF — ma non è oggi publication-ready: il worktree è intenzionalmente in corso,
3 test falliscono dopo la rilocazione, Ruff e Mypy non sono verdi, Gitleaks segnala 10
finding non triaged, e mancano licenza, CI e governance open-source.

Il link pubblico ha valore di portfolio solo se non crea un debito reputazionale. La
pubblicazione anticipata deve quindi separare due stati:

1. **public alpha**: codice ispezionabile, build/test riproducibili, limiti espliciti;
2. **production candidate**: execution boundary sicuro, benchmark multi-OS e release
   supply-chain verificabile, raggiunto solo dopo gli RFC successivi.

## Proposal

Creare `Ignoryx/sistemista` con branch `development`, `validation`, `production`.
`development` è il default iniziale; nessun branch chiamato `main` o `master` resta nel
contratto remoto. La prima release è `0.1.0-alpha` e dichiara espressamente:

- research preview locale, single-user e single-host;
- mutazioni host non sicure per esecuzione unattended;
- supporto OS e target 8 GB non ancora certificati;
- modelli e `llama-server` sono artefatti esterni, non inclusi.

### Gate prima del primo push pubblico

1. **Integrità** — worktree intenzionale, nessun file personale o stato runtime.
2. **Legale** — Apache-2.0, notice/provenienza di modelli e dipendenze, metadata package.
3. **Security** — Gitleaks full-history con zero finding non triaged; fixture sintetiche
   allowlisted in modo puntuale; nessun token o path infrastrutturale reale.
4. **Quality** — test non-certification verdi, Ruff verde, wheel e sdist costruibili.
5. **Documentation** — README coerente con `config.py`, setup riproducibile, limiti prima
   dei claim, nessuna promessa "any OS / any problem / 8 GB" senza evidenza.
6. **Automation** — CI least-privilege con test/lint/build/secret scan e dipendenze pinned.

### Gate di promozione

- `development → validation`: RFC-005 Secure Execution Boundary implementata e testata.
- `validation → production`: tutti gli RFC publication-target chiusi, benchmark ripetuto,
  security review, SBOM/provenance, release firmata e GO documentato.

## Alternatives

- **Pubblicare subito lo stato corrente** — rifiutato: nessuna licenza, gate rossi e claim
  contraddittori renderebbero il link un rischio reputazionale.
- **Attendere il GO finale prima di creare il repository** — rifiutato: impedisce di avere
  un URL stabile e di mostrare in modo trasparente l'evoluzione ingegneristica.
- **Repository privato fino al GO** — rifiutato per il target portfolio; l'alpha pubblico
  è accettabile solo con limitazioni e gate verificabili.

## Decision

Adottare la pubblicazione progressiva: prima alpha pubblica minima e onesta su
`development`, poi promozioni tracciate dagli RFC. La visibilità non equivale a readiness.

## Consequences

- Il README e i metadata diventano superficie contrattuale e devono seguire il runtime.
- Ogni RFC successivo aggiorna evidenza, status e changelog nello stesso merge.
- Branch protection e required checks diventano parte del prodotto, non configurazione
  amministrativa opzionale.
- L'organizzazione GitHub attualmente flagged può rendere l'URL non visibile ai terzi;
  questo è un vincolo esterno, non un motivo per abbassare i gate del repository.

## Implementation evidence — 2026-07-22

- `Ignoryx/sistemista` è pubblico con `development` default e branch `validation`/`production`.
- Ruleset attivo: PR, review CODEOWNER, conversazioni risolte, history lineare, sei status
  obbligatori, blocco delete e force-push; bypass admin consentito soltanto via PR.
- Secret scanning, push protection, Dependabot security updates e private reporting abilitati.
- Gate locale: 692 passed, 3 skipped; Ruff/format, build, pip-audit e Gitleaks verdi.
- La PR bootstrap ha registrato CI, ma il dispatch restituisce HTTP 500 e Security non viene
  indicizzato mentre l'organizzazione è flagged; chiusura subordinata al ripristino GitHub e
  alla prima esecuzione remota verde di entrambi i workflow.

## Falsification / stop conditions

Il primo push pubblico è bloccato se anche una sola condizione resta vera:

- un finding Gitleaks non è spiegato o rimosso;
- un test o Ruff fallisce;
- il pacchetto non si costruisce da un checkout pulito;
- licenza o provenienza di un artefatto è incerta;
- README e comportamento osservabile si contraddicono.
