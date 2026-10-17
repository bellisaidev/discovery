# Digital Life Lab — Roadmap e stato verificabile

Revisione documentale: **17 ottobre 2026**. Analisi implementativa del 16 ottobre:
`main` a `57b6012`, versione `0.4.0`. La direzione attuale è descritta in
[PROJECT_VISION](PROJECT_VISION.md), la storia delle scelte in [DECISIONS](DECISIONS.md).

La roadmap descrive stato e direzioni considerate, senza imporre un ordine di
sviluppo. Numerazione e dipendenze documentano riferimenti e relazioni tecniche
attuali, non una sequenza obbligatoria. Nuove scoperte, risultati sperimentali o
istruzioni esplicite dell'utente possono modificare, eliminare o sostituire
qualsiasi milestone futura, comprese quelle già approvate. Gli stati distinguono
ciò che è implementato da ciò che è in sviluppo, approvato o soltanto proposto.

## Come leggere lo stato

| Stato | Significato |
| --- | --- |
| `COMPLETED` | Implementata e verificata con evidenze nel perimetro dichiarato. |
| `IN_PROGRESS` | Implementazione iniziata; chiusura e verifiche del perimetro ancora incomplete. |
| `PLANNED` | Approvata, ma implementazione non iniziata. |
| `PROPOSED` | Idea o estensione in discussione, senza approvazione verificabile. |
| `BLOCKED` | Impedimento concreto che blocca l'attività, da identificare. |

Lo stato riguarda il software e le verifiche dichiarate, non il successo di una
domanda scientifica. Non si usano percentuali. In questa ricostruzione nessun nuovo
sviluppo è classificato `PLANNED` o `BLOCKED`: mancano evidenze di approvazione o di
un impedimento concreto. Una funzionalità già codificata su un branch può essere
`IN_PROGRESS` anche se l'approvazione per integrarla rimane non verificata.

## Branch e provenienza

Inventario dei riferimenti **disponibili localmente**, senza fetch o verifica remota:

| Riferimento | Commit | Contenuto verificato |
| --- | --- | --- |
| `main` (corrente) | `57b6012` | M1–M6, documentazione di validazione; nessuna rilocalizzazione. |
| `origin/main`, `origin/HEAD` | `57b6012` | Riferimenti remoti memorizzati localmente, coincidenti con `main` al momento dell'analisi. |
| `resource-moving` | `98f46b2` | Un commit successivo alla baseline, con rilocalizzazione e test dedicati. |
| `origin/resource-moving` | `98f46b2` | Riferimento remoto memorizzato localmente; aggiornamento sul server non verificato. |

Il merge-base è `57b6012`; non sono stati cambiati branch né eseguiti merge.
All'inizio dell'analisi del 16 ottobre non risultavano modifiche a file tracciati; `.vscode/` era già non
tracciata. Non è stato trovato `AGENTS.md` o un equivalente di istruzioni per agenti
nei percorsi applicabili e nei file del repository ispezionati. Il workflow è
pertanto raccolto qui e raggiungibile dal README, senza aggiungere orchestrazione.

`configs/relocation.toml` esiste nell'albero Git di `resource-moving`, non nel
checkout `main`. Il suo nome in una scheda IDE non prova che sia disponibile sul
branch corrente. I riferimenti a quel branch sotto usano commit immutabili.

## Evidenze e verifiche documentate

Nell'analisi del 16 ottobre sono stati esaminati README, `pyproject.toml`, preset, moduli in `src/`, test,
rapporti e artefatti di `docs/`, cronologia e differenze dei branch locali.
Gli esiti delle suite sotto sono **storici, riportati nei documenti versionati**;
non sono nuove esecuzioni del 16 o 17 ottobre. La suite applicativa, i benchmark,
la GUI e il packaging non sono stati rieseguiti per queste modifiche documentali.

| Baseline documentata | Evidenza storica |
| --- | --- |
| V1, M1–M3 | [VALIDATION](VALIDATION.md): 49 test, lint, build e prove prolungate del 14 ottobre 2026. |
| M4 | [M4_VALIDATION](M4_VALIDATION.md): 103 test, lint, formattazione, distribuzione e riprese del 14 ottobre. |
| M5 | [M5_VALIDATION](M5_VALIDATION.md): 140 test prima di M6 e benchmark su sorgenti M5 congelate, 15 ottobre. |
| M6 | [M6_VALIDATION](M6_VALIDATION.md): suite completa 175 test senza errori o skip; successivi 33 test CLI/GUI e dashboard sulle sorgenti definitive, 15 ottobre. |

La dichiarazione `COMPLETED` di M1–M6 deriva dalla convergenza fra codice presente,
test presenti e questi rapporti; non dalla sola intestazione del README.
Le verifiche documentali del 16 ottobre hanno riguardato il controllo dei collegamenti locali,
degli stati e dei riferimenti Git, della coerenza fra i tre documenti e della
limitazione delle modifiche alla documentazione, oltre a `git diff --check`.
Esito del 16 ottobre: 167 collegamenti/ancore locali validi nei quattro Markdown interessati,
17 schede DEC complete e dieci riferimenti a commit esistenti; sette report JSON
citati leggibili. Verificati anche i whitespace dei tre file nuovi tramite
`git diff --no-index --check`. Invariati gli hash dei 41 file tracciati controllati
in sorgenti, configurazioni, test e metadati di progetto; invariati dimensioni e
timestamp dei 128 file database rilevati in `experiments/` e `tests/`.

La revisione del 17 ottobre cambia il ruolo della documentazione e le indicazioni
per gli agenti, conservando le evidenze implementative precedenti. Non introduce
funzionalità né modifica lo stato delle milestone. La nuova impostazione è
registrata in [DEC-018](DECISIONS.md#dec-018--documentazione-descrittiva-e-direzione-rivedibile).
Verifiche documentali del 17 ottobre: 175 collegamenti/ancore locali validi,
18 schede DEC complete, motivazioni delle 17 schede precedenti conservate e stati
delle milestone invariati. Controllati `git status`, `git diff` e whitespace;
invariati gli hash di 76 altri file controllati e dimensioni/timestamp dei 128
file database rilevati. Nessuna nuova esecuzione di test applicativi.

## Milestone della baseline main

| ID | Titolo | Stato | Principali commit di implementazione |
| --- | --- | --- | --- |
| M1 | Ecosistema e simulazione di base | `COMPLETED` | `b19d1c1`, `045ad98` |
| M2 | Riproduzione, mutazioni e plasticità | `COMPLETED` | `b19d1c1`, `045ad98` |
| M3 | Segnali, statistiche e confronti sperimentali | `COMPLETED` | `b19d1c1`, `045ad98` |
| M4 | Checkpoint e ripresa deterministica | `COMPLETED` | `d987d0e`, `b16e66a` |
| M5 | Neural Inspector | `COMPLETED` | `9d9dbc9`, `259b596` |
| M6 | Dashboard evolutiva | `COMPLETED` | `9ee48cb` |

Versione M5/M6 fissata da `6471177`; rapporto consolidato in `57b6012`.
Per tutte le schede seguenti la data di revisione è il 16 ottobre 2026 e il
perimetro implementato è quello verificato a `57b6012`.

### M1 — Ecosistema e simulazione di base

- **Obiettivo:** simulare individui con percezione e azioni locali in un mondo 2D.
- **Stato:** `COMPLETED` in `main`.
- **Implementato:** dieci fondatrici di default, controllori NumPy, corpi circolari,
  sensori orientati, risorse, metabolismo, costi delle azioni, collisioni, mortalità,
  estinzione senza reinserimenti, GUI Pygame e modalità headless.
- **Mancante:** nessuna lacuna documentata nel perimetro consegnato; predazione,
  materiali manipolabili e termodinamica completa non fanno parte della milestone.
- **Test/verifiche:** [test_core.py](../tests/test_core.py), test GUI in
  [test_cli_gui.py](../tests/test_cli_gui.py), rapporto V1 e artefatti
  [acceptance-100k.json](acceptance-100k.json), [benchmark.json](benchmark.json).
- **Dipendenze:** Python 3.12, NumPy, configurazione validata; Pygame CE per la GUI.
- **Limiti:** solver iterativo limitato, prestazioni dipendenti dalla popolazione,
  isolamento architetturale; Linux non verificato nei rapporti disponibili.
- **Riferimenti:** [simulation.py](../src/digital_ecosystem/simulation.py),
  [world.py](../src/digital_ecosystem/world.py),
  [physics.py](../src/digital_ecosystem/physics.py), DEC-001–005 e DEC-010.

### M2 — Riproduzione, mutazioni e plasticità

- **Obiettivo:** distinguere variazione ereditabile e modifiche individuali.
- **Stato:** `COMPLETED` in `main`.
- **Implementato:** riproduzione asessuata richiesta neuralmente, soglie energetiche,
  cooldown e collocazione valida; mutazioni di pesi, bias, nodi e connessioni di DAG;
  plasticità hebbiana limitata, separata dal genoma e non ereditata.
- **Mancante:** nessuna lacuna nel perimetro consegnato; apprendimento adattivo non
  dimostrato; crossover, speciazione, reti ricorrenti e NEAT completo non implementati.
- **Test/verifiche:** [test_evolution.py](../tests/test_evolution.py), ereditarietà
  senza delta acquisiti, ogni operazione strutturale e 500 mutazioni consecutive;
  [VALIDATION](VALIDATION.md), [diagnostic-10k.json](diagnostic-10k.json).
- **Dipendenze:** M1 e contabilizzazione dei trasferimenti energetici.
- **Limiti:** interfacce fisse 16 input/6 output, massimi di 96 nodi e 1500
  connessioni nel preset sperimentale; complessità non equivale a intelligenza.
- **Riferimenti:** [genome.py](../src/digital_ecosystem/genome.py),
  [brain.py](../src/digital_ecosystem/brain.py),
  [reproduction.py](../src/digital_ecosystem/reproduction.py), DEC-006/007/014.

### M3 — Segnali, statistiche e confronti sperimentali

- **Obiettivo:** consentire interazioni locali e osservazioni riproducibili.
- **Stato:** `COMPLETED` in `main`.
- **Implementato:** due campi di segnali con diffusione, decadimento, scadenza e
  sottrazione dell'autosegnale; logging SQLite e CSV; genealogie, energia,
  complessità, diversità approssimata; controlli indipendenti e confronti fattoriali
  di plasticità, mutazioni e segnali con più seed.
- **Mancante:** nessuna lacuna nel perimetro descrittivo; protocollo lungo dieci seed
  × otto condizioni × 10000 tick non eseguito integralmente nel rapporto V1.
- **Test/verifiche:** [test_signals.py](../tests/test_signals.py),
  [test_logging.py](../tests/test_logging.py),
  [test_comparison.py](../tests/test_comparison.py); 24 esecuzioni brevi documentate
  in [comparison-summary.json](comparison-summary.json) e
  [comparison-runs.csv](comparison-runs.csv).
- **Dipendenze:** M1–M2, SQLite della libreria standard.
- **Limiti:** campioni normalmente ogni 30 tick, diversità fino a 128 coppie,
  vite in corso censurate, nessun test di significatività automatico. L'emissione
  non prova comunicazione significativa.
- **Riferimenti:** [signals.py](../src/digital_ecosystem/signals.py),
  [experiment_logger.py](../src/digital_ecosystem/experiment_logger.py),
  [comparison.py](../src/digital_ecosystem/comparison.py), DEC-002/008/009/011.

### M4 — Checkpoint e ripresa deterministica

- **Obiettivo:** conservare lo stato completo e continuare senza alterare la traiettoria.
- **Stato:** `COMPLETED` in `main`.
- **Implementato:** archivi `.dlcp` autosufficienti, stato numerico e RNG,
  configurazione, genomi, plasticità e SQLite selettivo; checksum, pubblicazione
  atomica, rotazione, lock; migrazioni, ripresa e diramazione con provenienza.
- **Mancante:** nessuna lacuna nel perimetro consegnato; conversione di ambienti
  numerici incompatibili e ripresa dalle sole statistiche non supportate.
- **Test/verifiche:** [test_checkpoint.py](../tests/test_checkpoint.py), matrice
  tre seed/otto condizioni, arresti di subprocess, errori SQLite, corruzione,
  collisioni di cronologia; [M4_VALIDATION](M4_VALIDATION.md),
  [m4-performance.json](m4-performance.json): overhead mediano 6,1283% nel protocollo
  documentato di sei esecuzioni da 100000 tick, entro il budget del 10%.
- **Dipendenze:** M1–M3 e persistibilità dello stato completo.
- **Limiti:** compatibilità stretta del nucleo e dell'ambiente numerico;
  un arresto forzato perde il lavoro dopo l'ultimo checkpoint valido. Budget
  prestazionale circoscritto al protocollo, non garantito per ogni popolazione.
- **Riferimenti:** [checkpoint.py](../src/digital_ecosystem/checkpoint.py),
  [state.py](../src/digital_ecosystem/state.py),
  [storage.py](../src/digital_ecosystem/storage.py), DEC-012/013.

### M5 — Neural Inspector

- **Obiettivo:** ispezionare reti e confrontare eredità e stato acquisito senza agire sul motore.
- **Stato:** `COMPLETED` in `main`.
- **Implementato:** Inspector Pygame, ricerca per ID, viste Live/Genoma, zoom,
  filtri, tabella connessioni, snapshot manuali persistenti, confronto ancestrale,
  consultazione dei morti quando esistono dati e compatibilità con fixture M4.
- **Mancante:** nessuna lacuna nel perimetro manuale; `SamplingPolicy` è un
  contratto, senza campionatore automatico attivo. Dati storici non registrati
  non possono essere ricostruiti.
- **Test/verifiche:** [test_observations.py](../tests/test_observations.py),
  [test_observation_hash.py](../tests/test_observation_hash.py), test CLI/GUI,
  fixture [m4-tick17.json](../tests/fixtures/m4-tick17.json);
  [M5_VALIDATION](M5_VALIDATION.md), [m5-performance.json](m5-performance.json).
- **Dipendenze:** M2–M4, genomi archiviati e contratti di osservazione.
- **Limiti:** snapshot manuali; genoma alla nascita distinto dalle attivazioni;
  ultimo snapshot distinto dallo stato alla morte; grafi densi con sovrapposizioni.
- **Riferimenti:** [inspector.py](../src/digital_ecosystem/inspector.py),
  [observations.py](../src/digital_ecosystem/observations.py),
  [neural_layout.py](../src/digital_ecosystem/neural_layout.py),
  [OBSERVATIONS](OBSERVATIONS.md), DEC-002/016.

### M6 — Dashboard evolutiva

- **Obiettivo:** consultare serie storiche e genealogie della sessione o di archivi.
- **Stato:** `COMPLETED` in `main`.
- **Implementato:** sei famiglie di grafici, intervalli, cursore e tooltip dei
  campioni originali; riduzione grafica con estremi preservati; query asincrone,
  genealogia progressiva, biblioteca SQLite e `--browse` in sola lettura senza
  costruire una `Simulation`; collegamento al Neural Inspector.
- **Mancante:** nessuna lacuna nel perimetro consegnato; marcatori e payload di
  intervento non applicano modifiche ambientali, nuove specie o nuove risorse.
- **Test/verifiche:** [test_dashboard.py](../tests/test_dashboard.py), test CLI/GUI;
  [M6_VALIDATION](M6_VALIDATION.md), [m6-performance.json](m6-performance.json) per
  stress sintetico e [m6-performance-real.json](m6-performance-real.json) per una
  traiettoria reale. Soglie documentate: prima vista ≤2 s, input/ridisegno p95
  ≤100 ms, crescita RSS ≤64 MiB, nei casi misurati.
- **Dipendenze:** dati M3/M4 e lettori M5; Pygame CE per l'interfaccia.
- **Limiti:** campioni storici, non ricostruzione di stati intermedi; individui
  analizzati fino al confine persistito; memoria e latenze non garantite per archivi
  illimitati; benchmark iniziale con cache filesystem riscaldata.
- **Riferimenti:** [analytics.py](../src/digital_ecosystem/analytics.py),
  [dashboard.py](../src/digital_ecosystem/dashboard.py), DEC-002/011/016.

## Sviluppi successivi

Gli ID `EXT-*` sono riferimenti documentali stabili; non introducono milestone M7+
approvate né priorità obbligatorie. Le evidenze delle schede risalgono al
16 ottobre 2026. Le direzioni restano modificabili o sostituibili in base ai
risultati e alle nuove istruzioni dell'utente; la storia delle proposte precedenti
rimane consultabile anche quando non vengono più perseguite.

### EXT-001 — Rilocalizzazione dinamica delle risorse

- **Obiettivo:** studiare disponibilità e distribuzione variabile delle risorse.
- **Stato:** `IN_PROGRESS`, esclusivamente in `resource-moving` a `98f46b2`;
  integrazione e approvazione scientifica generale non verificate.
- **Implementato nel branch:** flag disattivato nel preset sperimentale, preset
  dedicato, disattivazione dei depositi esauriti, ricollocamento con esclusione
  geometrica e tentativi limitati, refill conteggiato come rigenerazione, RNG
  dedicato, eventi e stato serializzato; adattamenti a sensori, fisica e renderer.
  In modalità relocation sostituisce la rigenerazione continua sul posto.
- **Mancante/verifiche:** esistono nove funzioni di test in
  [test_resources.py al commit](https://github.com/bellisaidev/discovery/blob/98f46b2/tests/test_resources.py),
  ma non è stato trovato un rapporto versionato con gli esiti. Non eseguiti qui.
  Il test chiamato checkpoint continuity verifica `to_state`/`from_state`, non
  l'intero archivio `.dlcp`; quello legacy usa uno stato privato dei nuovi campi,
  non la fixture binaria M4. Il caso GUI controlla lo snapshot senza avviare un renderer.
- **Dipendenze:** M1–M4; revisione di compatibilità, logging e osservazione M5/M6.
- **Limiti/chiusura:** verificare suite del branch e archivio reale, confronto
  contro la baseline `main`, prestazioni ed evidenze GUI. Il test con relocation
  disabilitata confronta due istanze del nuovo codice: da solo non dimostra
  equivalenza con il vecchio motore. Al momento dell'analisi non erano documentati
  approvazione e criteri di integrazione; una nuova richiesta esplicita può
  definirli o modificarli senza conferme aggiuntive dovute a questa scheda.
- **Riferimenti:** [commit 98f46b2](https://github.com/bellisaidev/discovery/commit/98f46b2),
  [preset nel branch](https://github.com/bellisaidev/discovery/blob/98f46b2/configs/relocation.toml),
  DEC-015 `PROPOSED`. Nessuna funzionalità di questo branch è attribuita a `main`.

### EXT-002 — Analisi dell'apprendimento adattivo

- **Obiettivo/stato:** distinguere modifiche neurali e vantaggio comportamentale;
  `PROPOSED`, approvazione di uno studio specifico non verificata.
- **Disponibile:** plasticità M2, controlli fattoriali M3, snapshot M5 e analisi M6.
- **Mancante:** protocollo approvato, indicatori operativi, controlli e analisi
  capaci di sostenere conclusioni sull'adattamento; nessun risultato conclusivo.
- **Verifiche/dipendenze:** test dei meccanismi in M2/M3/M5, non test di efficacia
  adattiva; dipende da tali strumenti e da traiettorie sperimentali documentate.
- **Limiti/riferimenti:** [visione](PROJECT_VISION.md#limiti-dellinterpretazione-scientifica),
  [VALIDATION](VALIDATION.md); la serie fattoriale lunga suggerita resta da eseguire.

### EXT-003 — Nuove modalità di sperimentazione

- **Obiettivo/stato:** progettare protocolli e confronti ulteriori; `PROPOSED`.
- **Disponibile:** headless/GUI, confronti multiseed, ripresa e diramazione M3/M4.
- **Mancante:** requisiti e approvazione per nuove modalità, protocolli predittivi
  o studi di evoluzione aperta; non è stato trovato un piano approvato.
- **Verifiche/dipendenze:** copertura delle modalità esistenti in test CLI,
  comparison e checkpoint; nessun test di modalità future. Dipende da M3/M4.
- **Limiti/riferimenti:** [README](../README.md), DEC-008/009/013; un prefisso
  storico condiviso non produce repliche indipendenti.

### EXT-004 — Modificare l'ambiente conservando la storia evolutiva

- **Obiettivo/stato:** introdurre interventi espliciti con provenienza conservata;
  `PROPOSED` per un sistema generale di interventi.
- **Disponibile:** cronologia geometrica delle risorse M4, record versionati e
  marcatori M5/M6; EXT-001 è una specifica estensione in un altro branch.
- **Mancante:** applicazione e pianificazione di interventi, configurazione e
  politica approvate, semantica di diramazione per cambi di regole; `--resume`
  attualmente rifiuta la sostituzione della configurazione salvata.
- **Verifiche/dipendenze:** test di registrazione sintetica e portabilità in
  observations, non interventi reali; dipende da M4–M6 e dalle decisioni future.
- **Limiti/riferimenti:** [OBSERVATIONS](OBSERVATIONS.md), DEC-013/016; un record
  descrittivo non applica effetti al mondo. Un futuro sistema di interventi
  comporterebbe effetti e provenienza da distinguere dalle osservazioni della baseline.

### EXT-005 — Strumenti avanzati di osservazione

- **Obiettivo/stato:** estendere osservazione senza perturbare il motore; `PROPOSED`.
- **Disponibile:** M5/M6, paginazione e contratto `SamplingPolicy`.
- **Mancante:** campionamento neurale automatico e registrazione completa delle
  traiettorie/attivazioni; requisiti, budget e approvazione non verificati.
- **Verifiche/dipendenze:** test d'indipendenza osservativa già disponibili; nessun
  test di un campionatore attivo inesistente. Dipende da M3–M6.
- **Limiti/riferimenti:** [OBSERVATIONS](OBSERVATIONS.md), DEC-002/016; crescita
  dei dati da misurare, nessuna ricostruzione dei dati mai registrati.

### EXT-006 — Evoluzione strutturale delle reti neurali

- **Obiettivo/stato:** base DAG `COMPLETED` in M2; ampliamento di modelli e
  interfacce `PROPOSED`, senza approvazione verificabile.
- **Disponibile:** aggiunta/rimozione di nodi e connessioni, mutazione parametrica,
  validazione topologica, limiti configurabili, analisi della complessità.
- **Mancante:** eventuali reti ricorrenti, nuove interfacce, altri meccanismi di
  plasticità o apprendimento predittivo; nessuno di questi è attribuito alla M2.
- **Verifiche/dipendenze:** test strutturali di evolution e visualizzazione M5;
  nessun test o risultato per i modelli futuri. Dipende da M2 e dalla revisione
  di sensori, stato e checkpoint se cambiano i contratti numerici.
- **Limiti/riferimenti:** [genome.py](../src/digital_ecosystem/genome.py),
  DEC-007/014, [visione](PROJECT_VISION.md); crescita strutturale non prova cognizione.

## Questioni aperte e documenti storici

- I rapporti M5/M6 descrivono benchmark con `resource_radius = 20`; il preset
  sperimentale a `57b6012` usa `7`. Non trasferire automaticamente quei risultati
  prestazionali alla configurazione attuale. Origine della discrepanza non verificata;
  conservare configurazione effettiva e manifest di ogni prova.
- `Configuration()` usa rigenerazione `0.08`, mentre `Configuration.load()` carica
  il preset sperimentale con `0.58`. Non equiparare i due percorsi di inizializzazione.
- Le frasi «nessuna ripresa da checkpoint» in VALIDATION V1 e «Inspector e dashboard
  non implementati» in M4_VALIDATION descrivono i perimetri storici, superati da
  M4 e M5/M6 rispettivamente; i rapporti originali restano conservati.
- Non è disponibile un registro originale completo di approvazioni e alternative:
  DECISIONS distingue ricostruzione della baseline e proposte. Le date dei commit
  non sono usate come date di approvazione.
- Linux e determinismo fra ambienti diversi non sono verificati nei rapporti;
  stato attuale del server Git e risultati non versionati del branch relocation
  non verificati. Nessuno di questi punti costituisce da solo un'attività `BLOCKED`.

## Workflow condiviso tra agenti

Prassi suggerite per ChatGPT, Codex, Antigravity, collaboratori umani e futuri
agenti, indipendentemente dal prodotto. Non costituiscono un'autorità superiore
alle nuove istruzioni esplicite dell'utente e non introducono automazioni.

**Orientamento:** PROJECT_VISION aiuta a comprendere obiettivi e ipotesi attuali,
questa ROADMAP descrive stato, relazioni tecniche e lacune, DECISIONS spiega le
ragioni storiche delle scelte. Il confronto con branch, commit, worktree e codice
reale permette di riconoscere differenze o informazioni superate.

**Cambiamenti di direzione:** una richiesta esplicita dell'utente può modificare
anche le convenzioni oggi centrali. Non serve una nuova approvazione soltanto
perché la richiesta contraddice visione, milestone o decisioni storiche. Gli agenti
segnalano rischi, compromessi, rotture tecniche ed effetti sui confronti, procedendo
nel perimetro richiesto senza blocchi automatici fondati sulla documentazione.
Se mancano informazioni necessarie all'implementazione, la chiarificazione riguarda
quelle informazioni, non la riconferma di un cambiamento già richiesto.

**Integrità delle evidenze:** preservare dati sperimentali e provenienza, distinguere
osservazioni, ipotesi e conclusioni, riferire solo test effettivamente eseguiti e
attribuire ogni funzionalità al branch che la contiene. La conservazione dei dati
non impone compatibilità concettuale o tecnica con scelte abbandonate: eventuali
migrazioni, incompatibilità e nuovi significati delle metriche vanno resi espliciti
senza riscrivere retroattivamente i risultati precedenti.

**Alla consegna:** gli aggiornamenti pertinenti possono riguardare ROADMAP per lo
stato, DECISIONS per storia e motivazioni, PROJECT_VISION per la direzione più
recente, incluse correzioni descrittive. Il riepilogo include modifiche, verifiche
effettive e problemi residui. Per rendere le schede verificabili sono utili data,
branch e commit/riferimento disponibile, perimetro, test (compresi skip e fallimenti)
e nuove limitazioni. Le informazioni non verificabili restano identificate come
tali; i rapporti precedenti conservano la propria provenienza.

Quando più agenti lavorano contemporaneamente, il coordinamento sui file aiuta
a preservare le modifiche altrui senza presumere che i branch contengano lo stesso lavoro.
