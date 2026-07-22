# 700 · Research — index

> Owner: **indice dei paper/idee rilevanti al *design*, con la lezione applicata a Sistemista.**
> Owner solo dell'*indice e della lezione*; il contenuto tecnico che ne deriva vive nei doc proprietari.
> Regola: non citare un paper come autorità — cita la **decisione** che ha influenzato (e linka il DEC).

---

## Indice (design-relevant)

| Idea / paper | Rilevanza per Sistemista | Applicata in |
|---|---|---|
| **ReAct** (reason+act interleaved) | loop thought→action→observation del PTY | `orchestrator.py` lifecycle |
| **Reflexion** (self-feedback verbale) | verify()/observer che rivede dopo il passo | [memory.md](../../workspace/src/memory.py) |
| **Agent-Computer Interface** (SWE-agent) | presentare output PTY su misura per l'LLM, non grezzo | non nei report → gap in [research/competitors/index](../research/competitors/index.md) |
| **Toolformer / tool-use tipizzato** | schema esplicito degli step (DISCOVERY/MODIFY/…) | `state.py::step_type` |
| **MCP** (Model Context Protocol) | standard per estensioni future | [research/competitors/goose](../research/competitors/goose.md) |

> ⚠️ **Da compilare:** aggiungere una riga solo quando un paper ha **effettivamente** influenzato una
> decisione (con DEC-NNN). Niente lista-desideri: l'indice riflette scelte fatte, non letture ipotetiche.

Collegati: [../800_decisions/README](../800_decisions/README.md) · [memory.py](../../workspace/src/memory.py)
