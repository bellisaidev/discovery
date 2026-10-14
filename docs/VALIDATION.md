# Verifiche effettivamente eseguite — Digital Life Lab 0.1.0

Data: 14 ottobre 2026. Ambiente verificato: Windows 11, CPython 3.12.15,
NumPy 2.5.4, pygame-ce 2.5.8, uv 0.13.1. Le prove Linux non sono state eseguite.
Le sorgenti usate dalle prove finali hanno SHA-256
`fe470512dbfab7f5c43b4aeb0128dbc4696c5b18b082d8fb306f5f32b80932c9`.

## Milestone e controlli

| Milestone | Evidenza |
| --- | --- |
| 1 — motore, reti, fisica e GUI | Dieci organismi iniziali; test di metabolismo, raccolta simultanea, orientamento sensoriale, movimento, collisioni, mortalità ed estinzione; GUI dummy e desktop reale |
| 2 — evoluzione e plasticità | Test di condizioni riproduttive, trasferimenti, cooldown, spazio e capacità; ereditarietà senza plasticità; tutte le mutazioni strutturali e 500 mutazioni consecutive valide |
| 3 — segnali e osservazione | Confronto con riferimento per emettitore a tre coefficienti di diffusione, inclusa diffusione estrema; scadenza e autosegnale; SQLite, CSV, durate censurate, genealogia, interruzioni e confronti multiseed |

Comandi finali:

```text
uv run pytest -q       → 49 passed in 14.71s
uv run ruff check .    → All checks passed!
uv build --offline     → wheel e archivio sorgente costruiti
```

uv è stato invocato mediante il percorso installato quando assente dal PATH.
Per i comandi di progetto si è usata una cache scrivibile locale tramite `UV_CACHE_DIR`.
Il wheel è stato installato in `.package-check`, un ambiente separato dentro il workspace,
e importato da `site-packages` avviando Python da quella cartella. Il preset incorporato
è stato caricato e il motore ha completato 100 tick con dieci organismi; Pygame non è stato
importato nel processo headless. L'installazione fresca ha richiesto risoluzione iniziale
online perché la prima risoluzione offline senza vincoli esatti non trovava metadati
sufficienti in cache; il funzionamento dopo l'installazione è stato verificato offline.

La GUI finale sul desktop ha completato 120 frame e 60 tick, con uscita ordinata e
dieci organismi. I test subprocess con driver dummy verificano disegno del pannello,
singolo tick, velocità, overlay, riavvio con seed e callback di esportazione.
[gui.png](gui.png) è una cattura riproducibile al tick 120, ispezionata visivamente.

Un test aggiuntivo ha rilevato sovrapposizione residua tra due corpi coincidenti contro
una parete. Il solver è stato corretto per distribuire la separazione secondo lo spazio
disponibile; la regressione passa. Non sono rimasti test o controlli di lint falliti.

## Esecuzioni prolungate finali

| Prova | Tick | Nascite | Morti | Popolazione finale | Massimo errore assoluto del bilancio |
| --- | ---: | ---: | ---: | ---: | ---: |
| experimental, seed 42 | 100000 | 1 | 11 | 0 | 4,984 × 10⁻¹⁰ |
| diagnostic, seed 42 | 10000 | 34 | 36 | 8 | 1,360 × 10⁻⁸ |

La prova sperimentale ha conservato 3335 campioni, 466900 righe dei depositi e tutti gli
11 eventi di morte; l'ultimo campione con organismi vivi è al tick 5070. L'esecuzione ha
proseguito fino al tick 100000 senza reinserimenti. L'esportazione dei cinque CSV è riuscita.
Il preset diagnostico ha mantenuto organismi attivi fino alla fine dei 10000 tick e
raggiunto la generazione 4. Sono verifiche di funzionamento, non prove di adattamento.

`PRAGMA integrity_check` restituisce `ok` per entrambi i database. Le discrepanze
energetiche riportate sono arrotondamento numerico; i trasferimenti non sono conteggiati
come nuova energia. Evidenze complete:

- [acceptance-100k.json](acceptance-100k.json)
- [diagnostic-10k.json](diagnostic-10k.json)
- Database locali: `experiments/final-100k/lab.sqlite3` e
  `experiments/final-diagnostic/lab.sqlite3`.

## Confronti e prestazioni

La CLI comparativa ha completato **24 esecuzioni**: otto combinazioni di plasticità,
mutazioni e segnali, seed 0/1/2, 300 tick per condizione, preset diagnostico.
I test automatici verificano inoltre riproducibilità e invarianti per ogni combinazione.

- [comparison-summary.json](comparison-summary.json): numerosità e dispersione per condizione.
- [comparison-runs.csv](comparison-runs.csv): risultati di ogni singola esecuzione.

Il protocollo scientifico suggerito nel README, dieci seed × otto condizioni × 10000 tick,
è disponibile ma **non è stato eseguito integralmente**. Le prove brevi non giustificano
conclusioni scientifiche su sopravvivenza, cooperazione o comunicazione.

Benchmark finale: 35 tick di riscaldamento e 180 tick misurati per caso, tracing della
memoria soltanto nel riscaldamento, senza GUI o logger. Parametri diagnostici mantengono
la popolazione fissa; nessun preset scientifico è modificato.

| Organismi | Segnali OFF, ms/tick | Segnali ON, ms/tick | Buffer NumPy dei segnali |
| ---: | ---: | ---: | ---: |
| 10 | 2,279 | 4,495 | 271992 byte |
| 100 | 25,724 | 47,025 | 466392 byte |
| 256 | 72,702 | 119,370 | 803352 byte |

A 256 individui, le sole griglie complete di un riferimento per emettitore occuperebbero
1843200 byte, senza contare lo storico necessario alla scadenza. I kernel condivisi
hanno un costo fisso, quindi il risparmio non vale per ogni popolazione piccola.
Le allocazioni complessive tracciate al riscaldamento sono circa 10,51 MB con 256 individui
e segnali attivi, contro 9,62 MB senza segnali. Non sono misure della memoria RSS del processo.

I risultati completi, incluso il percentile 95 dei tempi e l'ambiente, sono in
[benchmark.json](benchmark.json). Non si garantiscono 1× a grandi popolazioni né le
velocità 16×/64× richieste; la GUI riporta la velocità effettivamente sostenuta.

## Limiti residui

- Linux documentato ma non verificato; determinismo garantito soltanto nello stesso ambiente software.
- Solver di contatto iterativo limitato: ammassi estremi richiedono ulteriori prove e parametri appropriati.
- Nessuna prova di apprendimento adattivo o comunicazione significativa; nessuna correzione per forzarli.
- Campioni ogni 30 tick, eventi vitali completi, nessuna traiettoria o attivazione completa per ogni tick.
- Genealogia conservata in memoria; esperimenti con moltissime nascite possono aumentare il consumo.
- Arresto forzato o guasto del disco può perdere l'ultimo batch SQLite; nessuna ripresa da checkpoint.
- Isolamento architetturale degli organismi, senza sandbox per codice arbitrario.
