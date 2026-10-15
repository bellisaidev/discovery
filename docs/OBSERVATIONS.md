# Osservazioni M5 e M6

Il nucleo numerico M4 resta invariato. Le osservazioni non eseguono inferenza,
apprendimento o passi di simulazione e non consumano i suoi generatori casuali.
Selezioni, filtri, zoom e cursori appartengono alla GUI.

Il fingerprint osservativo mantiene esattamente la serializzazione M4. La sua
implementazione usa cache locali limitate per scalari ripetuti e omette dalla
copia le sole code che M4 esclude già dal digest. I test confrontano i digest
con l'implementazione originale, comprese strutture annidate, array non contigui,
Unicode, zero negativo e stati reali. Nessun dato numerico viene arrotondato.

## Disponibilità dei dati neurali

| Sorgente | Genoma e bias | Attivazioni e delta acquisiti |
| --- | --- | --- |
| Individuo vivo corrente | Disponibili | Ultimo stato del cervello |
| Archivio M4 con genomi | Genoma alla nascita | Non registrati in SQLite |
| Snapshot richiesto in M5 | Genoma referenziato | Disponibili al tick registrato |
| Vecchi dati privi di genomi | Non disponibili | Non disponibili |

Uno snapshot non è uno stato esatto alla morte. Non si ricostruiscono attivazioni,
plasticità o genomi mancanti. Le attivazioni di fine tick provengono dall'ultima
inferenza, prima dell'apprendimento del tick; il delta acquisito include già tale
apprendimento. Il peso effettivo mostrato vale per il prossimo forward ed è
`clip(peso_genetico + delta_acquisito, ±parameter_bound)`. La differenza effettiva
dal peso genetico può differire dal delta acquisito per effetto del clipping.

Neuroni e connessioni descrivono la complessità strutturale. I delta acquisiti
descrivono la plasticità individuale. Nessuna delle due misure dimostra adattamento
comportamentale, apprendimento vantaggioso o maggiore intelligenza.

## Contratti di integrazione

`ExperimentReader` restituisce dati distaccati e paginati. La connessione degli
archivi usa `mode=ro` e `query_only`; la connessione presa in prestito dal logger
mantiene transazioni e configurazione originarie. La GUI non forza campioni o
commit per aggiornare le visualizzazioni.

`ObservationWriter.capture(id)` acquisisce solo organismi vivi a un confine di
tick già osservato. Registra snapshot e revisione insieme alla cronologia pendente,
senza produrre un campione statistico aggiuntivo. Una richiesta ripetuta sullo
stesso organismo e tick è idempotente. La conferma richiede il commit riuscito;
le scritture da riprovare comprendono anche la revisione osservativa.

`SamplingPolicy.requested_ids(tick, living_ids)` è il punto di integrazione per
future politiche automatiche configurabili. La futura sessione applicativa potrà
invocarlo fra tick completi e usare lo stesso writer. M5/M6 non installano né
eseguono un campionatore automatico e non aggiungono configurazioni al motore.

`InterventionRecord` e `ObservationWriter.append_intervention` accettano una
descrizione versionata dell'intervento al confine corrente. Non applicano effetti,
non pianificano interventi e non sono accessibili ai cervelli. In queste milestone
il writer degli interventi è esercitato soltanto dai test con dati sintetici.

## Persistenza e provenienza

Schema operativo 3; SQLite incorporato nei nuovi checkpoint 104. Il lettore dei
checkpoint continua ad accettare lo schema M4 103. Formato esterno e stato numerico
rimangono versione 1; tutti i controlli dell'ambiente numerico sono mantenuti.

Gli snapshot contengono tick, riferimento genetico, sequenza degli eventi,
fingerprint numerico e checksum del payload. Il digest della cronologia M4 è
logico, ordinato e indipendente dalla disposizione delle pagine SQLite. Le sole
osservazioni aggiuntive non causano una diramazione. Un salvataggio considera
anche la revisione osservativa, quindi registra un nuovo snapshot anche in pausa.

Una diramazione importa esclusivamente la cronologia e le osservazioni contenute
nel checkpoint. Non cerca snapshot nella prosecuzione presente nel database di
destinazione. Quando la traiettoria coincide, le osservazioni vengono unite per
chiave, senza duplicazioni; payload discordanti generano un errore.

La fixture `tests/fixtures/m4-tick17.dlcp` è stata generata con le sorgenti M4,
prima delle modifiche osservative, dal preset diagnostico e seed 42. Il JSON
adiacente conserva ambiente, UUID e fingerprint completi attesi ai tick 17, 41 e
120. Il test binario richiede l'ambiente numerico originale; non elude i controlli
di compatibilità per far passare il caricamento su ambienti differenti.

Il database operativo adiacente `m4-tick17.sqlite3` è stato ripristinato usando
le sorgenti M4 congelate: conserva lo schema operativo 2. I test verificano
migrazione, rollback, backup, stesso UUID e continuazione deterministica.

## Dashboard e limiti delle osservazioni

Le connessioni del worker analitico sono indipendenti e in sola lettura. Le query
usano il prefisso già persistito della traiettoria; nel corrente i campioni
pendenti del logger vengono aggiunti come copie in memoria, senza commit forzati.
Le analisi di longevità e genealogia dichiarano il confine persistito e censurano
morti successive al cursore. Il browser non costruisce una simulazione.

Le serie sono lette con pagine da 1.000 righe tramite la chiave `(esperimento,
tick)`. Per la visualizzazione si conservano primo, ultimo, minimo e massimo
per metrica e colonna di pixel. I tassi sono calcolati sui campioni originali
prima della riduzione; i buchi effettivi nei campioni interrompono le linee.
Il tooltip legge il campione originale precedente. La riduzione non modifica
SQLite e non promette di mostrare ogni oscillazione intermedia a scala ridotta.

La genealogia carica 100 individui alla volta e conserva al massimo 500 nodi
nella vista. Si può scegliere un ramo e continuare a espanderlo; la cache della
vista non limita la genealogia conservata. Anche esperimenti e interventi sono
paginati; la chiave composta degli interventi conserva tutti i record allo stesso
tick. Nessun produttore di interventi è attivato.

L'Inspector conserva al massimo due superfici per le connessioni e 512 etichette.
La cache del genoma alla nascita è distaccata dal motore; attività e delta sono
acquisiti di nuovo al tick corrente. Solo le rappresentazioni dei colori sono
quantizzate in pixel. Le connessioni ricolorate più recentemente vengono disegnate
in primo piano agli incroci. La tabella mostra i pesi con otto decimali;
il payload persistito conserva tutti i valori originali in precisione completa.
