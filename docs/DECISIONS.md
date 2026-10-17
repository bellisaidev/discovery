# Digital Life Lab — Registro delle decisioni

Revisione documentale: **17 ottobre 2026**. Baseline esaminata il 16 ottobre:
`main` a `57b6012`, versione
`0.4.0`; branch aggiuntivo esaminato: `resource-moving` a `98f46b2`.
Documenti collegati: [PROJECT_VISION](PROJECT_VISION.md), [ROADMAP](ROADMAP.md).

## Criteri e provenienza

Questo registro ricostruisce scelte già espresse nella documentazione e nel codice.
Ogni voce è una registrazione storica contestualizzata, non un divieto di adottare
soluzioni diverse. Le nuove istruzioni esplicite dell'utente possono modificare
obiettivi, architettura e ipotesi scientifiche senza un'ulteriore approvazione
richiesta soltanto per il contrasto con una decisione precedente. `ACCEPTED` indica
un'adozione nel contesto descritto, non un obbligo permanente per gli agenti.

Per DEC-001–014 e DEC-016, `ACCEPTED` indica una scelta adottata nella baseline
`main`, attestata dai riferimenti: non certifica un verbale di approvazione
scientifica mai trovato. Le motivazioni sotto sintetizzano il contratto documentato
e i suoi effetti; non attribuiscono discussioni o intenzioni a singoli autori.
Le alternative non documentate sono dichiarate tali.

`PROPOSED` indica una scelta da discutere, anche quando esiste già codice in un
branch separato. `SUPERSEDED` conserva una scelta sostituita con collegamento alla
successiva. La sostituzione parziale del ruolo normativo di DEC-017 con il ruolo
descrittivo di DEC-018 deriva dalla richiesta esplicita del 17 ottobre 2026;
non cambia le scelte tecniche della baseline.
Gli ID sono stabili e non vanno rinumerati. La revisione di oggi non è la data
originale delle decisioni; le date dei commit attestano la cronologia del codice,
non la data di approvazione. DEC-017 deriva dalla richiesta esplicita dell'utente
del 16 ottobre 2026 che istituisce questa documentazione; DEC-018 ne rivede il ruolo.

| ID | Decisione | Stato |
| --- | --- | --- |
| [DEC-001](#dec-001--stack-python-numpy-e-pygame-ce) | Stack Python, NumPy e Pygame CE | `ACCEPTED` |
| [DEC-002](#dec-002--motore-separato-da-visualizzazione-e-osservazione) | Motore separato da visualizzazione e osservazione | `ACCEPTED` |
| [DEC-003](#dec-003--dieci-organismi-iniziali-di-default) | Dieci organismi iniziali di default | `ACCEPTED` |
| [DEC-004](#dec-004--sensori-locali-e-isolamento-architetturale) | Sensori locali e isolamento architetturale | `ACCEPTED` |
| [DEC-005](#dec-005--selezione-fisica-senza-fitness-o-reward-artificiali) | Selezione fisica senza fitness o reward artificiali | `ACCEPTED` |
| [DEC-006](#dec-006--riproduzione-asessuata-condizionata-fisicamente) | Riproduzione asessuata condizionata fisicamente | `ACCEPTED` |
| [DEC-007](#dec-007--genoma-mutabile-separato-dalla-plasticità) | Genoma mutabile separato dalla plasticità | `ACCEPTED` |
| [DEC-008](#dec-008--preset-sperimentale-e-diagnostico-distinti) | Preset sperimentale e diagnostico distinti | `ACCEPTED` |
| [DEC-009](#dec-009--determinismo-condizionato-e-flussi-casuali-separati) | Determinismo condizionato e flussi casuali separati | `ACCEPTED` |
| [DEC-010](#dec-010--contabilità-energetica-esplicita) | Contabilità energetica esplicita | `ACCEPTED` |
| [DEC-011](#dec-011--persistenza-sqlite-e-provenienza-dei-dati) | Persistenza SQLite e provenienza dei dati | `ACCEPTED` |
| [DEC-012](#dec-012--checkpoint-autosufficienti-e-compatibilità-esplicita) | Checkpoint autosufficienti e compatibilità esplicita | `ACCEPTED` |
| [DEC-013](#dec-013--separare-ripresa-e-diramazione) | Separare ripresa e diramazione | `ACCEPTED` |
| [DEC-014](#dec-014--limiti-computazionali-espliciti) | Limiti computazionali espliciti | `ACCEPTED` |
| [DEC-015](#dec-015--rilocalizzazione-dinamica-delle-risorse) | Rilocalizzazione dinamica delle risorse | `PROPOSED` |
| [DEC-016](#dec-016--osservazioni-neurali-e-contratti-per-estensioni-future) | Osservazioni neurali e contratti per estensioni future | `ACCEPTED` |
| [DEC-017](#dec-017--documentazione-centrale-e-workflow-condiviso) | Documentazione centrale e workflow condiviso (ruolo originario) | `SUPERSEDED` da DEC-018 |
| [DEC-018](#dec-018--documentazione-descrittiva-e-direzione-rivedibile) | Documentazione descrittiva e direzione rivedibile | `ACCEPTED` |

## DEC-001 — Stack Python, NumPy e Pygame CE

- **Stato:** `ACCEPTED`.
- **Data:** Data originale non verificata.
- **Contesto:** laboratorio desktop offline con motore numerico e interfaccia locale.
- **Alternative considerate:** non documentate; nessun confronto fra linguaggi o framework trovato.
- **Decisione adottata:** Python `>=3.12,<3.13`, NumPy `>=2,<3`, `pygame-ce >=2.5,<3`;
  packaging Hatchling, ambiente e lock gestiti tramite uv; nessuna GPU richiesta.
- **Motivazione:** stack coerente con controllori numerici NumPy e GUI desktop già
  documentati; non è ricostruita una valutazione comparativa delle prestazioni.
- **Conseguenze e compromessi:** installazione iniziale delle dipendenze, vincolo
  Python 3.12 e sessione grafica per la GUI; esecuzione successiva offline.
- **Componenti:** packaging, motore, renderer, tool di verifica.
- **Riferimenti:** [pyproject.toml](../pyproject.toml), [uv.lock](../uv.lock),
  [README](../README.md), implementazione `b19d1c1`, release `6471177`.

## DEC-002 — Motore separato da visualizzazione e osservazione

- **Stato:** `ACCEPTED`.
- **Data:** Data originale non verificata.
- **Contesto:** nella baseline l'osservazione è progettata per leggere la simulazione
  senza influenzare decisioni degli organismi o flussi casuali del motore.
- **Alternative considerate:** non documentate.
- **Decisione adottata:** `Simulation` orchestra il nucleo; renderer, logger,
  Inspector e dashboard osservano attraverso copie e lettori dedicati. Headless
  non richiede l'importazione di Pygame. Il browser non costruisce una simulazione.
- **Motivazione:** mantenere dinamica e osservazione indipendenti, consentendo
  confronti riproducibili e consultazione degli archivi.
- **Conseguenze e compromessi:** copie, fingerprint e query hanno costi da misurare;
  GUI e archivi distinguono dati campionati, correnti e non disponibili.
- **Componenti:** `Simulation`, `Renderer`, `ExperimentLogger`, `ExperimentReader`,
  `InspectorPanel`, `DashboardRenderer`.
- **Riferimenti:** [simulation.py](../src/digital_ecosystem/simulation.py),
  [OBSERVATIONS](OBSERVATIONS.md), [test_logging.py](../tests/test_logging.py),
  [test_observations.py](../tests/test_observations.py),
  [test_dashboard.py](../tests/test_dashboard.py); commit `b19d1c1`, `9d9dbc9`, `9ee48cb`.

## DEC-003 — Dieci organismi iniziali di default

- **Stato:** `ACCEPTED`.
- **Data:** Data originale non verificata.
- **Contesto:** condizioni iniziali dichiarate e riproducibili per la baseline.
- **Alternative considerate:** non documentate; popolazioni 100/256 compaiono nelle
  prove di carico, senza sostituire il default sperimentale.
- **Decisione adottata:** `initial_population = 10` nei due preset correnti e nel
  default di `WorldConfig`; collocazione casuale senza sovrapposizione dei corpi.
- **Motivazione:** fissare una condizione iniziale esplicita condivisa da CLI,
  configurazione e test; non è documentata una giustificazione biologica del numero.
- **Conseguenze e compromessi:** parametro modificabile, non principio scientifico;
  cambi di popolazione iniziale devono apparire nella configurazione effettiva.
- **Componenti:** `WorldConfig`, inizializzazione di `Simulation`, preset.
- **Riferimenti:** [experimental.toml](../configs/experimental.toml),
  [diagnostic.toml](../configs/diagnostic.toml),
  [test_core.py](../tests/test_core.py), commit `b19d1c1`.

## DEC-004 — Sensori locali e isolamento architetturale

- **Stato:** `ACCEPTED`.
- **Data:** Data originale non verificata.
- **Contesto:** il modello adottato limita le percezioni di ogni organismo,
  senza accesso a identità/genomi altrui o a infrastrutture esterne.
- **Alternative considerate:** non documentate; nessuna sandbox di codice arbitrario adottata.
- **Decisione adottata:** `Brain.forward` riceve 16 valori numerici e produce sei
  controlli fisici; i sensori rappresentano energia e tre settori locali per risorse,
  corpi, pareti e due segnali. `Organism` non riceve capacità OS, rete o filesystem.
- **Motivazione:** circoscrivere l'informazione e separare il controllore dall'ambiente.
- **Conseguenze e compromessi:** isolamento architetturale, senza protezione per
  plugin ostili; variazioni di input/output richiedono revisione dei contratti.
- **Componenti:** `Brain`, `Action`, `Organism`, `Sensors`, `World`.
- **Riferimenti:** [brain.py](../src/digital_ecosystem/brain.py),
  [organism.py](../src/digital_ecosystem/organism.py),
  [sensors.py](../src/digital_ecosystem/sensors.py), [README](../README.md), `b19d1c1`.

## DEC-005 — Selezione fisica senza fitness o reward artificiali

- **Stato:** `ACCEPTED`.
- **Data:** Data originale non verificata.
- **Contesto:** studiare conseguenze di interazioni e selezione senza forzare
  strategie desiderate o sopravvivenza della popolazione.
- **Alternative considerate:** fitness, reward e reinserimenti sono descritti come
  assenti nel README della baseline; non è documentata una loro implementazione precedente.
- **Decisione adottata:** nessun ranking selettivo o reward; comandi neurali,
  costi fisici, mortalità e riproduzione regolano le linee. Nessuna strategia di
  ricerca del cibo/cooperazione preprogrammata e nessun reinserimento dopo estinzione.
- **Motivazione:** preservare la distinzione fra regole imposte e processi osservabili.
- **Conseguenze e compromessi:** estinzione e assenza di emergenza sono esiti validi;
  metriche di longevità, figli e diversità restano descrittive. Il progettista
  influenza comunque sensori, costi e condizioni iniziali.
- **Componenti:** `Simulation.step`, `Reproduction`, `Brain`, logger, protocolli.
- **Riferimenti:** [README](../README.md),
  [simulation.py](../src/digital_ecosystem/simulation.py),
  [reproduction.py](../src/digital_ecosystem/reproduction.py),
  [test_core.py](../tests/test_core.py), [VALIDATION](VALIDATION.md), `b19d1c1`.

## DEC-006 — Riproduzione asessuata condizionata fisicamente

- **Stato:** `ACCEPTED`.
- **Data:** Data originale non verificata.
- **Contesto:** generare discendenti senza selezione esterna per punteggio.
- **Alternative considerate:** non documentate; crossover e riproduzione sessuata assenti.
- **Decisione adottata:** un solo genitore; richiesta dall'output neurale, soglia
  energetica, riserva, cooldown e spazio valido. Energia alla prole trasferita dal
  genitore; costo riproduttivo dissipato; richieste respinte senza addebito del costo.
- **Motivazione:** collegare la riproduzione a stato corporeo, azione e vincoli locali.
- **Conseguenze e compromessi:** genealogia con un genitore, limiti di spazio e
  popolazione registrati; ordine operativo e soglie sono parti del modello imposto.
- **Componenti:** `Reproduction`, `Organism`, genealogia, `EnergyLedger`.
- **Riferimenti:** [reproduction.py](../src/digital_ecosystem/reproduction.py),
  [test_evolution.py](../tests/test_evolution.py), [README](../README.md), `b19d1c1`.

## DEC-007 — Genoma mutabile separato dalla plasticità

- **Stato:** `ACCEPTED`.
- **Data:** Data originale non verificata.
- **Contesto:** distinguere variazione ereditabile e cambiamenti individuali nella vita.
- **Alternative considerate:** ereditarietà dei pesi acquisiti e NEAT completo sono
  descritti come assenti nella baseline; altre alternative non documentate.
- **Decisione adottata:** `Genome` conserva pesi, bias e struttura DAG ereditabili;
  mutazioni parametriche e strutturali avvengono nella prole. `Brain.acquired`
  contiene delta hebbiani limitati, con decadimento, e parte da zero alla nascita.
  Il genoma non viene modificato dall'apprendimento durante la vita.
- **Motivazione:** rendere separabili evoluzione genetica e plasticità individuale.
- **Conseguenze e compromessi:** aggiunta/rimozione di nodi e connessioni già
  presente; ingressi/uscite fissi, assenza di cicli, crossover e speciazione.
  Plasticità non garantisce adattamento e maggiore struttura non prova intelligenza.
- **Componenti:** `Genome`, `Brain`, `Reproduction`, stato e Inspector.
- **Riferimenti:** [genome.py](../src/digital_ecosystem/genome.py),
  [brain.py](../src/digital_ecosystem/brain.py),
  [test_evolution.py](../tests/test_evolution.py), [OBSERVATIONS](OBSERVATIONS.md), `b19d1c1`.

## DEC-008 — Preset sperimentale e diagnostico distinti

- **Stato:** `ACCEPTED`.
- **Data:** Data originale non verificata.
- **Contesto:** esercitare i componenti senza confondere condizioni diagnostiche
  favorevoli con una baseline scientifica o un salvataggio automatico della popolazione.
- **Alternative considerate:** non documentate; entrambi i preset usano lo stesso motore.
- **Decisione adottata:** `experimental.toml` è il preset CLI predefinito;
  `diagnostic.toml` dichiara parametri fisici diversi. TOML validato contro campi
  sconosciuti e valori incompatibili. Flag indipendenti e confronti su otto condizioni.
- **Motivazione:** rendere esplicite condizioni e controlli, mantenendo casuali gli
  output dei controllori anche nelle prove diagnostiche.
- **Conseguenze e compromessi:** risultati da confrontare solo con configurazioni
  effettive note. A questa revisione `Configuration()` ha rigenerazione `0.08`,
  mentre `Configuration.load()` usa `0.58` dal preset: non sono equivalenti.
- **Componenti:** configurazione, preset, CLI e comparison.
- **Riferimenti:** [configuration.py](../src/digital_ecosystem/configuration.py),
  [experimental.toml](../configs/experimental.toml),
  [diagnostic.toml](../configs/diagnostic.toml),
  [test_comparison.py](../tests/test_comparison.py), `b19d1c1`, `d987d0e`.

## DEC-009 — Determinismo condizionato e flussi casuali separati

- **Stato:** `ACCEPTED`.
- **Data:** Data originale non verificata.
- **Contesto:** confrontare traiettorie e continuare esperimenti in modo riproducibile.
- **Alternative considerate:** non documentate; il README esclude la promessa di
  identità bit per bit tra ambienti software e hardware diversi.
- **Decisione adottata:** seed registrato; flussi separati per ambiente, corpi
  iniziali, genomi, collocazione della prole e mutazioni. Osservatori non consumano
  tali flussi; checkpoint ne conserva gli stati. La ripresa attuale richiede
  compatibilità di configurazione, sorgenti e ambiente numerico.
- **Motivazione:** isolare le sorgenti di casualità e verificare le riprese.
- **Conseguenze e compromessi:** stesso seed da solo non basta; genealogie possono
  divergere nei controlli fattoriali. Compatibilità può rifiutare un archivio valido
  prodotto in un ambiente diverso; le verifiche documentate mantengono questi controlli.
- **Componenti:** `Simulation`, `Reproduction`, state, checkpoint, logger.
- **Riferimenti:** [simulation.py](../src/digital_ecosystem/simulation.py),
  [checkpoint.py](../src/digital_ecosystem/checkpoint.py),
  [test_comparison.py](../tests/test_comparison.py),
  [M4_VALIDATION](M4_VALIDATION.md), `b19d1c1`, `d987d0e`.

## DEC-010 — Contabilità energetica esplicita

- **Stato:** `ACCEPTED`.
- **Data:** Data originale non verificata.
- **Contesto:** distinguere energia introdotta, trasferita e dissipata evitando
  che raccolta o nascita creino energia non contabilizzata.
- **Alternative considerate:** il README dichiara che i residui alla morte sono
  dissipati, non restituiti ai depositi; altre valutazioni non documentate.
- **Decisione adottata:** `energia_corpi + energia_depositi = energia_iniziale +
  rigenerazione - dissipazione`. Raccolta e trasferimento alla prole sono interni;
  metabolismo, azioni, riproduzione e residui alla morte hanno categorie distinte.
- **Motivazione:** permettere verifiche indipendenti del bilancio e dei costi.
- **Conseguenze e compromessi:** azioni ridimensionate se non pagabili, tolleranze
  numeriche esplicite; modello metabolico, senza bilancio completo di calore e
  energia cinetica. Rigenerazione è l'unica introduzione dopo l'inizializzazione.
- **Componenti:** `EnergyLedger`, `World`, `Physics`, `Reproduction`, logger.
- **Riferimenti:** [world.py](../src/digital_ecosystem/world.py),
  [physics.py](../src/digital_ecosystem/physics.py),
  [test_core.py](../tests/test_core.py), [VALIDATION](VALIDATION.md), `b19d1c1`.

## DEC-011 — Persistenza SQLite e provenienza dei dati

- **Stato:** `ACCEPTED`.
- **Data:** Data originale non verificata.
- **Contesto:** osservare molte esecuzioni, genealogie e condizioni effettive,
  mantenendo accessibili i dati per analisi e confronti.
- **Alternative considerate:** non documentate; CSV è un'esportazione disponibile,
  non un sostituto adottato per la persistenza completa.
- **Decisione adottata:** SQLite con UUID per esperimento, seed, configurazione,
  versioni e hash sorgenti; campioni periodici, eventi vitali, individui, genomi
  deduplicati e cronologia delle risorse. Transazioni raggruppate e migrazioni con
  backup; lettori paginati e archivi aperti in sola lettura.
- **Motivazione:** conservare dati descrittivi e provenienza senza esporli ai cervelli.
- **Conseguenze e compromessi:** possibile perdita dell'ultimo batch dopo arresto
  forzato; nessuna ricostruzione di stati da sole statistiche. `lifespan` NULL per
  vite in corso, dati mancanti dichiarati, genealogia in memoria crescente.
- **Componenti:** `ExperimentLogger`, storage, `ExperimentReader`, analytics.
- **Riferimenti:** [experiment_logger.py](../src/digital_ecosystem/experiment_logger.py),
  [storage.py](../src/digital_ecosystem/storage.py),
  [test_logging.py](../tests/test_logging.py), [OBSERVATIONS](OBSERVATIONS.md),
  `b19d1c1`, `d987d0e`, `9d9dbc9`, `9ee48cb`.

## DEC-012 — Checkpoint autosufficienti e compatibilità esplicita

- **Stato:** `ACCEPTED`.
- **Data:** Data originale non verificata.
- **Contesto:** riprendere lo stato numerico completo senza dipendere dal database originale.
- **Alternative considerate:** recupero dalle sole statistiche escluso nel README;
  altri formati alternativi non documentati.
- **Decisione adottata:** `.dlcp` versionato con stato, configurazione, RNG, genomi,
  plasticità e SQLite del solo esperimento; JSON/NumPy senza pickle e checksum.
  Salvataggi a confini di tick completi, temporaneo, verifica, sincronizzazione e
  pubblicazione atomica, poi rotazione. Controlli di compatibilità prima del ripristino.
- **Motivazione:** portabilità dell'archivio nello stesso ambiente numerico e
  conservazione dell'ultima versione valida in caso di errore.
- **Conseguenze e compromessi:** costo di serializzazione e crescita degli archivi;
  non è garantita ripresa su ambienti incompatibili. Corrente più almeno tre
  precedenti; automatici ogni 10000 tick nel preset. Formato esterno 1, schema
  operativo corrente 3, SQLite incorporato 104; lettura M4 103 supportata.
- **Componenti:** `CheckpointManager`, `read_checkpoint`, state e storage.
- **Riferimenti:** [checkpoint.py](../src/digital_ecosystem/checkpoint.py),
  [state.py](../src/digital_ecosystem/state.py), [M4_VALIDATION](M4_VALIDATION.md),
  [OBSERVATIONS](OBSERVATIONS.md), [test_checkpoint.py](../tests/test_checkpoint.py),
  `d987d0e`, `b16e66a`, `9d9dbc9`.

## DEC-013 — Separare ripresa e diramazione

- **Stato:** `ACCEPTED`.
- **Data:** Data originale non verificata.
- **Contesto:** evitare di sovrascrivere una prosecuzione già registrata ripartendo
  da un checkpoint precedente o da una cronologia divergente.
- **Alternative considerate:** sovrascrittura dei parametri al resume e riuso
  indiscriminato della cronologia non adottati; discussione originale non disponibile.
- **Decisione adottata:** stesso UUID se la cronologia coincide; nuovo UUID e
  provenienza esplicita se la destinazione contiene una prosecuzione/divergenza.
  La diramazione importa il prefisso del checkpoint e preserva l'originale; lock esclusivo e
  replay idempotente con rifiuto dei payload discordanti. `--resume` rifiuta
  seed/configurazione/controlli espliciti; `--steps` conta tick aggiuntivi.
- **Motivazione:** preservare identità e integrità delle traiettorie e dei confronti.
- **Conseguenze e compromessi:** una diramazione con storia condivisa non è una
  replica indipendente. Le sole osservazioni non generano diramazioni e vengono
  unite solo per traiettorie coincidenti. Non è un editor delle condizioni fisiche.
- **Componenti:** resume, logger, `experiment_heads`, `experiment_origins`, storage, CLI.
- **Riferimenti:** [checkpoint.py](../src/digital_ecosystem/checkpoint.py),
  [storage.py](../src/digital_ecosystem/storage.py),
  [__main__.py](../src/digital_ecosystem/__main__.py),
  [test_checkpoint.py](../tests/test_checkpoint.py),
  [test_observations.py](../tests/test_observations.py), `d987d0e`, `9d9dbc9`.

## DEC-014 — Limiti computazionali espliciti

- **Stato:** `ACCEPTED`.
- **Data:** Data originale non verificata.
- **Contesto:** mantenere una simulazione desktop praticabile senza ranking per eliminazione.
- **Alternative considerate:** limite di popolazione disattivabile tramite
  `max_population = 0`; altri compromessi non documentati.
- **Decisione adottata:** massimo sperimentale 256 organismi, 96 nodi e 1500
  connessioni per rete; tentativi di collocazione e solver limitati. Richieste
  riproduttive valide bloccate dalla capacità vengono registrate, senza rimuovere
  altri organismi per fare spazio; mutazioni rispettano i limiti del grafo.
- **Motivazione:** rendere visibile il vincolo computazionale e verificarne gli effetti.
- **Conseguenze e compromessi:** il limite può influenzare le traiettorie e va
  riportato; nessuna garanzia di tempo reale a 256 individui. I limiti sono scelte
  implementative, non selezione per fitness né garanzia di evoluzione aperta.
- **Componenti:** configurazione, `Reproduction`, `Genome`, `Physics`, benchmark.
- **Riferimenti:** [experimental.toml](../configs/experimental.toml),
  [genome.py](../src/digital_ecosystem/genome.py),
  [test_evolution.py](../tests/test_evolution.py), [benchmark.json](benchmark.json), `b19d1c1`.

## DEC-015 — Rilocalizzazione dinamica delle risorse

- **Stato:** `PROPOSED` per l'adozione nella baseline condivisa.
- **Data:** Data originale non verificata. Il commit di implementazione è datato
  15 ottobre 2026; non è prova della data o dell'esistenza di un'approvazione.
- **Contesto:** il solo branch `resource-moving` contiene una variante del ciclo
  delle risorse. Non è presente un rapporto versionato di validazione/approvazione.
- **Alternative considerate:** il codice conserva il percorso di rigenerazione sul
  posto quando il flag è disabilitato; altre valutazioni non documentate.
- **Decisione adottata:** nessuna approvazione generale ricostruibile. La variante
  implementata a `98f46b2` disattiva depositi esauriti e tenta ricollocamento con
  refill contabilizzato, esclusione geometrica e RNG dedicato; il preset
  `relocation.toml` abilita la variante. Non si attribuisce questa scelta a `main`.
- **Motivazione:** la variante permette di studiare risorse mobili; la sua utilità
  scientifica è un'ipotesi, senza risultati adattivi dimostrati.
- **Conseguenze e compromessi:** sostituisce la rigenerazione continua, introduce
  stato attivo/inattivo, eventi e nuovi vincoli di compatibilità. Suite e archivio
  `.dlcp` reale da verificare; presenza di test non implica esito positivo.
- **Componenti:** World, configurazione, simulation, sensors, physics, renderer,
  state, preset e test nel branch separato.
- **Riferimenti:** [commit 98f46b2](https://github.com/bellisaidev/discovery/commit/98f46b2),
  [test del branch](https://github.com/bellisaidev/discovery/blob/98f46b2/tests/test_resources.py),
  [EXT-001](ROADMAP.md#ext-001--rilocalizzazione-dinamica-delle-risorse).
  La verifica è stata fatta sugli oggetti Git locali, senza accesso al server GitHub.

## DEC-016 — Osservazioni neurali e contratti per estensioni future

- **Stato:** `ACCEPTED` per i contratti e le funzionalità M5/M6 esistenti.
- **Data:** Data originale non verificata.
- **Contesto:** osservare parametri ereditari e acquisiti con provenienza, senza
  inventare stati storici o introdurre effetti ambientali nel percorso osservativo.
- **Alternative considerate:** ricostruzione di attivazioni/genomi mancanti esclusa
  esplicitamente; altri approcci non documentati.
- **Decisione adottata:** snapshot manuali distaccati a confini osservati, lettori
  paginati, checksum e revisione osservativa, confronto ancestrale. `SamplingPolicy`
  è solo un contratto. `InterventionRecord` registra descrizioni versionate, senza
  applicare o pianificare interventi; dashboard legge marcatori e serie registrate.
- **Motivazione:** rendere osservazioni e loro disponibilità verificabili, preservando
  compatibilità M4 e indipendenza dal nucleo numerico.
- **Conseguenze e compromessi:** snapshot manuali crescono con le acquisizioni;
  ultimo snapshot distinto dallo stato alla morte. Questa adozione non documenta
  l'approvazione di campionatore automatico, Dynamic Ecosystem o nuove regole ambientali.
- **Componenti:** observations, observation_hash, storage, Inspector, analytics, dashboard.
- **Riferimenti:** [OBSERVATIONS](OBSERVATIONS.md),
  [observations.py](../src/digital_ecosystem/observations.py),
  [M5_VALIDATION](M5_VALIDATION.md), [M6_VALIDATION](M6_VALIDATION.md),
  `9d9dbc9`, `259b596`, `9ee48cb`.

## DEC-017 — Documentazione centrale e workflow condiviso

- **Stato:** `SUPERSEDED` da [DEC-018](#dec-018--documentazione-descrittiva-e-direzione-rivedibile)
  il 17 ottobre 2026 per il ruolo normativo e le condizioni di aggiornamento;
  rimangono i tre documenti e il loro contenuto storico utile.
- **Data:** 16 ottobre 2026, data della richiesta originaria.
- **Contesto:** la richiesta originaria mirava a condividere visione, stato del
  progetto e decisioni fra collaboratori e agenti, distinguendo fatti, proposte e branch.
- **Alternative considerate:** nessuna discussione storica documentata; la richiesta
  esclude nuovi sistemi di orchestrazione e automazioni.
- **Decisione adottata:** PROJECT_VISION, ROADMAP e DECISIONS come riferimento
  condiviso; accesso dal README e workflow indipendente dal prodotto. Nessun merge,
  modifica alla simulazione o commit automatico per questa attività.
- **Motivazione:** consentire a un nuovo collaboratore di ricostruire vincoli e
  stato tramite evidenze, evitando approvazioni o verifiche inventate.
- **Conseguenze e compromessi:** nella redazione originaria si prescrivevano
  manutenzione documentale e aggiornamento di visione/principi solo con approvazione
  esplicita. Conservava i rapporti preesistenti come evidenze storiche e proponeva
  un workflow senza poteri speciali per un agente o esecuzione parallela richiesta.
  Le prescrizioni che potevano imporre conferme ridondanti o compatibilità
  concettuale sono sostituite da DEC-018; questa frase ne conserva la storia.
- **Componenti:** questi tre documenti e sezione del README; il precedente indirizzo
  per futuri file di istruzioni rinviava al workflow senza contraddirlo, ora riveduto da DEC-018.
- **Riferimenti:** richiesta dell'utente del 16 ottobre 2026,
  [visione](PROJECT_VISION.md), [workflow](ROADMAP.md#workflow-condiviso-tra-agenti),
  [README](../README.md#project-governance--documentation). Il messaggio originale
  non è un verbale storico versionato nel repository.

## DEC-018 — Documentazione descrittiva e direzione rivedibile

- **Stato:** `ACCEPTED` su richiesta esplicita dell'utente.
- **Data:** 17 ottobre 2026.
- **Contesto:** la prima redazione poteva essere interpretata come un insieme di
  principi permanenti e condizioni di approvazione che limitavano agenti e ricerca.
- **Alternative considerate:** mantenere il ruolo normativo originario di DEC-017;
  la richiesta attuale ne dispone la revisione conservando contenuti utili e storia.
- **Decisione adottata:** i documenti descrivono direzione attuale, stato verificabile,
  scelte contestualizzate e ipotesi aperte. Le nuove istruzioni esplicite dell'utente
  possono cambiare qualsiasi scelta o milestone futura senza conferme ulteriori
  dovute al solo contrasto con i documenti. Nessun ordine obbligatorio di sviluppo.
- **Motivazione:** permettere l'evoluzione della ricerca mantenendo visibili ragioni,
  evidenze e conseguenze delle scelte, senza attribuire autorità permanente alla storia.
- **Conseguenze e compromessi:** sostituisce il ruolo normativo e le condizioni di
  aggiornamento di [DEC-017](#dec-017--documentazione-centrale-e-workflow-condiviso),
  conservandone l'istituzione dei documenti e la motivazione originale. Anche
  assenza di reward e separazione fra apprendimento ed eredità sono riesaminabili.
  Gli agenti segnalano rischi e rotture tecniche, preservano integrità e provenienza
  dei dati e descrivono incompatibilità o perdita di confrontabilità; la compatibilità
  concettuale con scelte abbandonate non è una condizione per procedere.
- **Componenti:** PROJECT_VISION, ROADMAP, DECISIONS e sezione documentale del README;
  nessuna modifica a codice, configurazioni o funzionalità della simulazione.
- **Riferimenti:** richiesta esplicita dell'utente del 17 ottobre 2026,
  [PROJECT_VISION](PROJECT_VISION.md), [workflow](ROADMAP.md#workflow-condiviso-tra-agenti),
  [README](../README.md#project-governance--documentation). Nessun verbale separato
  è stato aggiunto; questa scheda registra fonte, differenze e conseguenze.

## Manutenzione del registro

Il [workflow condiviso](ROADMAP.md#workflow-condiviso-tra-agenti) aiuta a confrontare
richieste nuove, codice e storia. Le differenze segnalano conseguenze da spiegare,
non un blocco automatico. Una richiesta esplicita che cambia una scelta storica
costituisce già l'indicazione dell'utente: non occorre chiederla di nuovo per
aggiornare visione, roadmap o registro. Le correzioni descrittive non richiedono
un'approvazione separata della direzione scientifica.

Per nuove scelte assegnare il successivo ID e compilare stato, data verificabile
(altrimenti «Data originale non verificata»), contesto, alternative documentate,
decisione, motivazione, conseguenze/compromessi, componenti e riferimenti.
Una proposta può essere registrata come `ACCEPTED` sulla base di una nuova
istruzione esplicita dell'utente o di altra evidenza verificabile dell'adozione,
indicando contesto e perimetro, senza confondere decisione e implementazione.
La ROADMAP distingue l'avanzamento effettivo; PROJECT_VISION riflette la direzione
più recente anche quando abbandona le convenzioni precedenti.

Conservare la storia: quando una decisione viene sostituita, mantenere la voce,
marcarla `SUPERSEDED`, collegarla al nuovo ID e aggiungere nella nuova voce il
riferimento inverso. Conservare la motivazione originale e descrivere nella nuova
voce le differenze, le conseguenze e l'ambito eventualmente ancora valido della
precedente. Registrare data e fonte della sostituzione quando verificabili.
Non cancellare vecchie decisioni per far coincidere retroattivamente i documenti
con l'implementazione. Gli esiti dei test rimangono nei rapporti e nella ROADMAP,
con distinzione fra prove storiche ed esecuzioni della revisione corrente.
