# Milestone 4 — verifica del 14 ottobre 2026

**Milestone 4 verificata nell'ambiente Windows riportato sotto.**

Perimetro: checkpoint autosufficienti, ripristino deterministico, archivio genetico
e continuità SQLite. Neural Inspector e dashboard non sono stati implementati.
I risultati della V1 rimangono in [VALIDATION.md](VALIDATION.md).

## Correttezza

Comandi effettivamente eseguiti dalla radice del progetto su Windows:

```powershell
.venv\Scripts\python.exe -m pytest -q
.venv\Scripts\python.exe -m ruff check .
.venv\Scripts\python.exe -m ruff format --check .
```

La suite completa definitiva ha prodotto **103 passed in 162.58s**.
Comprende il recupero GUI, SIGINT e il fallimento dell'esportazione SQLite.
Ruff: `All checks passed!`; formattazione: `32 files already formatted`.

Le verifiche comprendono:

- 24 confronti: seed 0, 1, 2 e otto combinazioni di plasticità, mutazioni e segnali.
  Riprese ai tick 17, 41 e 120; confronto dello stato completo, RNG, ordine dei
  genomi, array e campioni/eventi della cronologia.
- Nascite diagnostiche da output neurale, mutazioni strutturali, cooldown,
  plasticità, morte, estinzione, rigenerazione e tracce di emettitori morti.
- Archivio trasferito in una directory nuova, origine rinominata e inutilizzabile
  dal percorso originale; nessun dato del secondo esperimento del database sorgente
  incluso nel checkpoint. Genomi completi e checksum verificati.
- Continuazione dello stesso UUID; diramazione da un checkpoint precedente e da
  una cronologia divergente allo stesso tick, con dati originali preservati.
  Replay di eventi identici idempotente, payload discordanti rifiutati.
- Lock esclusivo, compreso un tentativo di ripresa mentre il primo scrittore ha
  una transazione pendente. Il lock viene verificato prima di accedere a SQLite.
- Arresti reali di subprocess tramite `os._exit(77)` in sette punti: dopo flush,
  esportazione, array e archivio, prima/dopo pubblicazione e prima della rotazione.
  Tutti i file pubblicati restano caricabili; i lock sono rilasciati dal processo.
- File troncati, checksum JSON/NumPy/SQLite alterati, ambiente incompatibile,
  errore prima della pubblicazione e rotazione corrente più tre precedenti.
- Errore SQLite reale `database or disk is full`, ottenuto limitando
  `max_page_count`, seguito da rimozione del limite e replay del batch non
  confermato: eventi, campioni, risorse e individui coincidono con il controllo.
  Un trigger SQLite simula inoltre un guasto a metà scrittura osservativa.
- Migrazione interrotta con rollback dello schema e backup integro, poi migrazione
  riuscita; nessun genoma storico inventato per i dati precedenti.
- Argomenti CLI espliciti rifiutati con `--resume`, seed/configurazione conservati,
  tick aggiuntivi, destinazione predefinita e CSV, chiusura e interruzione.
- GUI dummy: salvataggio, caricamento in pausa, elenco recenti, file mancante e
  chiusura fallita senza abbandonare la sessione. Headless senza importare Pygame.
- SIGINT reale richiesto durante `step`: completamento del tick, checkpoint al
  tick 1 e codice 130. Dopo un errore osservativo, Play/Tick della GUI riprovano
  la registrazione senza avanzare; un arresto richiesto ferma anche il ciclo GUI
  al primo confine di tick.

Una prima suite durante un aggiornamento dei metadati di compatibilità ha dato
92 successi e 8 errori di compatibilità tra processi che avevano caricato versioni
diverse del modulo. Gli otto casi sono stati rieseguiti con successo; la successiva
suite da 100 test è passata; dopo gli ultimi controlli la suite definitiva sopra
riportata è passata con 103 test.

## Distribuzione e GUI

```powershell
& 'C:\Users\sparo\.local\bin\uv.exe' build --offline
& 'C:\Users\sparo\.local\bin\uv.exe' pip install --python .package-check\Scripts\python.exe --no-deps --offline dist\digital_life_lab-0.2.0-py3-none-any.whl
.venv\Scripts\python.exe -m digital_ecosystem --config configs\diagnostic.toml --gui-frames 6 --output experiments\m4-gui-real
```

Wheel e sdist **0.2.0** costruiti con successo. La wheel è installata in
`.package-check`, con import verificato da `site-packages`, fuori da `src`.
Dal suo ambiente: nuova simulazione headless di 10 tick, CSV, ripresa in una seconda
directory per altri 5 tick e CSV, senza importazione di Pygame. Il preset incluso
contiene la configurazione effettiva, compresa rigenerazione `0.58`.

GUI reale con SDL Windows: apertura e chiusura riuscite, 3 tick, 20 organismi e
10 nascite diagnostiche. Ripresa del checkpoint GUI in un'altra directory tramite
`--resume ... --gui-frames 6`: stesso UUID, tick ancora 3 e 20 organismi, quindi
nessun avanzamento durante la pausa iniziale. Un primo tentativo con un file
creato dal processo sandbox ha incontrato un errore di accesso del sistema;
la verifica riuscita usa il checkpoint creato dalla GUI reale.

Il rendering dummy dei nuovi controlli è stato acquisito e ispezionato:
[m4-gui.png](m4-gui.png).

## Prestazioni

Comando effettivamente eseguito, con nessun altro test, build o benchmark pesante
avviato contemporaneamente:

```powershell
.venv\Scripts\python.exe tools\benchmark_checkpoints.py --steps 100000 --repeats 3 --extras
```

Preset sperimentale, seed 42, sei esecuzioni sequenziali da 100.000 tick.
Configurazione congelata all'avvio e riportata integralmente nel JSON; la
rigenerazione è **0.58**, valore modificato dall'utente e preservato. Cambia
soltanto l'abilitazione dei checkpoint automatici. Entrambi i controlli registrano
gli stessi 3.341 campioni (ogni 30 tick, più i confini 10.000 e il finale), con
commit ai medesimi confini. Lo stato finale e l'hash di tutti i campioni coincidono
all'interno di ciascuna coppia. Il salvataggio di chiusura resta attivo in entrambi.

| Coppia | Senza automatici, s | Ogni 10.000 tick, s |
| --- | ---: | ---: |
| 1 | 60.6901 | 69.2418 |
| 2 | 55.8265 | 59.2645 |
| 3 | 55.8423 | 55.7509 |
| Mediana | **55.8423** | **59.2645** |

Incremento dalle mediane: **6.1283%**, entro il budget approvato **≤10%**.
Sono conservati i tempi individuali, compresa la prima coppia sopra il 10%:
la variabilità fra prove non è nascosta e non indica un beneficio dei checkpoint.
Il criterio usa le mediane, secondo il protocollo approvato.

I 30 checkpoint automatici misurati hanno queste distribuzioni:

| Misura | Minimo | Mediana | Massimo |
| --- | ---: | ---: | ---: |
| Dimensione `.dlcp`, byte | 451435 | 1720638 | 2994559 |
| Esportazione SQLite, s | 0.0443 | 0.2215 | 2.0900 |
| Acquisizione/serializzazione dello stato, s | 0.0028 | 0.0031 | 0.0103 |
| Produzione archivio compresso, s | 0.0402 | 0.1104 | 0.3731 |
| Verifica e sincronizzazione, s | 0.0145 | 0.0406 | 0.0809 |
| Salvataggio completo, s | 0.1075 | 0.3888 | 2.4312 |

A 100.000 tick: `.dlcp` circa **2.99 MB decimali**, SQLite incorporato **7.57 MB**.
L'esportazione è selettiva nel motore SQLite, senza copia integrale del database
sorgente né seconda copia integrale in memoria. Array e database sono scritti
nell'archivio in streaming. Restano quattro versioni per esecuzione con automatici,
una per il controllo. Il salvataggio automatico finale e quello di chiusura sono
accorpati perché stato e cronologia non cambiano.

Le fasi sono intervalli operativi: la serializzazione misura acquisizione della
rappresentazione completa e fingerprint; la produzione ZIP comprende codifica
JSON/NPY, checksum e compressione; verifica/sincronizzazione comprende controllo
CRC e `fsync`. Il totale include flush del logger, preparazione, pubblicazione e
rotazione, e non è la sola somma delle colonne intermedie.

Tutte e sei le prove ripristinano il checkpoint finale in una directory isolata,
con database originale rinominato, confrontando stato iniziale e tick successivo.
Il database operativo supera `PRAGMA integrity_check`. Il preset sperimentale
finisce estinto: 1 nascita e 11 morti, senza interventi sulla popolazione.
Errore finale del bilancio energetico: circa −6.74 × 10⁻¹⁰.

Prove supplementari definitive, anch'esse con ripristino isolato e confronto del
tick successivo:

| Condizione | Tick | Individui iniziali/finali | Tempo totale, s | `.dlcp`, byte | Salvataggio, s |
| --- | ---: | ---: | ---: | ---: | ---: |
| Diagnostica | 10000 | 10 / 8 | 76.9320 | 412893 | 0.1440 |
| Sperimentale | 100 | 10 / 10 | 0.8353 | 200852 | 0.1825 |
| Sperimentale | 100 | 100 / 100 | 6.6921 | 1127600 | 1.1778 |
| Sperimentale | 100 | 256 / 256 | 16.9589 | 2726714 | 2.6623 |

La diagnostica registra 34 nascite e mantiene 8 organismi attivi: la verifica non
si limita a uno stato estinto. Il suo errore energetico finale è 1.36 × 10⁻⁸,
senza rinormalizzazioni. Nelle prove da 100 tick la popolazione iniziale è il
solo parametro fisico modificato rispetto al preset sperimentale; nessun
intervento mantiene artificialmente gli organismi vivi. Il budget del 10% riguarda
il protocollo sperimentale da 100.000 tick, non è una garanzia per ogni popolazione.

Ambiente misurato: Windows 11 10.0.26300, Python 3.12.15, NumPy 2.5.4,
Pygame-ce 2.5.8. Il JSON conserva build numerica, capacità CPU, configurazione,
tempi e dimensioni di ogni checkpoint, UUID/percorsi e fingerprint.

Il primo confronto completo ha superato il budget: mediane 51.4543 e 58.9395 s,
incremento **14.55%**. Evidenza conservata in
[m4-performance-before-optimization.json](m4-performance-before-optimization.json).
Questo insuccesso ha richiesto l'eliminazione di commit ridondanti e la separazione
tra energie campionate e cronologia geometrica nell'archivio. Le coordinate
modificate sono conservate e la ricostruzione storica ha un test specifico.

## Limiti

- Verifiche eseguite su Windows; Linux documentato nei comandi del README ma non
  provato in questa sessione. Non si promette identità numerica fra ambienti diversi.
- Compatibilità verificata per Python, NumPy/build, sistema/architettura, capacità
  CPU, impostazioni numeriche e hash del nucleo. Nessuna conversione automatica di
  checkpoint incompatibili; versione formato 1, schema operativo 2, snapshot 103.
- Un arresto forzato perde i tick successivi all'ultimo checkpoint valido e può
  lasciare directory `.saving-*`, ignorate in caricamento. Il test non simula un
  guasto fisico del disco o un'interruzione di alimentazione dell'intera macchina.
- Le verifiche di atomicità e sincronizzazione riguardano il filesystem locale;
  non sono una garanzia per filesystem remoti con diverse semantiche di flush.
- La genealogia e gli snapshot genetici crescono con le nascite. Il caricamento
  limita ciascun payload JSON/NumPy a 64 MiB; SQLite viene elaborato in streaming.
- L'isolamento degli organismi rimane architetturale: nessuna esecuzione di plugin
  o codice arbitrario, nessuna sandbox per codice ostile.
