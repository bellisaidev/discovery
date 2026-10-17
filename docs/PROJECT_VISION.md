# Digital Life Lab — Visione del progetto

Revisione documentale: **17 ottobre 2026**. Baseline analizzata il 16 ottobre:
`main`, commit `57b6012`,
versione applicativa `0.4.0`. Lo stato delle implementazioni è nella
[ROADMAP](ROADMAP.md); le scelte e la loro provenienza sono in
[DECISIONS](DECISIONS.md). Il documento descrive la direzione di ricerca conosciuta
più recente, distinguendo obiettivi, ipotesi, convenzioni e vincoli del codice.
Le nuove istruzioni esplicite dell'utente possono modificarne qualsiasi aspetto;
questa visione non costituisce un'autorità superiore a tali istruzioni.

## Identità e obiettivi attuali

Digital Life Lab è un laboratorio sperimentale per studiare organismi digitali
autonomi, apprendimento individuale, ereditarietà, evoluzione e possibile emergenza
di comportamenti complessi. L'obiettivo è osservare le conseguenze delle interazioni
tra individui, ambiente e meccanismi evolutivi, senza programmare il successo degli
organismi o correggere una traiettoria perché non produce l'esito sperato.
Questa è la finalità della baseline descritta; obiettivi di ricerca differenti
possono portare a modelli e protocolli differenti.

Il sistema attuale è un'applicazione desktop offline con un mondo continuo 2D,
risorse energetiche e controllori neurali numerici. L'autonomia è circoscritta alle
azioni consentite dal modello fisico. Gli organismi non sono agenti linguistici:
ChatGPT, Codex, Antigravity ed eventuali altri strumenti collaborano al progetto
dall'esterno e non forniscono decisioni ai cervelli durante la simulazione.

## Domande di ricerca aperte

- Possono organismi digitali sviluppare comportamenti adattivi?
- Quali differenze si osservano fra apprendimento individuale ed evoluzione
  ereditaria, e con quali controlli è possibile distinguerle?
- Possono emergere strategie non esplicitamente programmate?
- Come influiscono distribuzione delle risorse, costi e altre regole ambientali
  sulle traiettorie evolutive?
- Possono evolvere strutture neurali più complesse, e quali effetti misurabili
  hanno sul comportamento?
- Quali condizioni potrebbero favorire cooperazione, competizione e comunicazione?
- In futuro, creature sufficientemente sofisticate potrebbero imparare a modificare
  il proprio ambiente?

## Ipotesi scientifiche

Fra le ipotesi attualmente considerate vi sono la possibilità che interazioni
locali e variazione ereditaria producano comportamenti adattivi, che la plasticità
individuale contribuisca a tali comportamenti e che condizioni ambientali diverse
favoriscano strategie diverse. Non sono risultati dimostrati. La presenza di
plasticità, mutazioni strutturali o canali di segnalazione non risponde da sola
alle domande precedenti; osservazioni e confronti possono smentire o riformulare
queste ipotesi.

## Convenzioni progettuali attuali

Le dodici scelte seguenti descrivono l'impostazione della baseline, non principi
immutabili o divieti per gli agenti. Anche assenza di reward, separazione fra
apprendimento ed ereditarietà, percezione locale e gestione delle estinzioni
possono essere riesaminate se cambiano gli obiettivi della ricerca. Una richiesta
esplicita dell'utente che le modifica non richiede una conferma aggiuntiva per il
solo fatto di contraddire questo documento. Restano da descrivere le conseguenze
sui dati, sui confronti e sui contratti tecnici coinvolti.

1. **Nessuna fitness function esplicita.** La selezione attuale non classifica gli
   individui mediante punteggi che premiano strategie desiderate. Le metriche
   descrittive restano esterne alle regole riproduttive.
2. **Nessun reward artificiale** per cooperazione, comunicazione o sopravvivenza.
   L'energia trasferita dalle risorse è parte del modello fisico; non è un punteggio
   comportamentale aggiunto al controllore.
3. **Nessuna strategia preprogrammata per ottenere risultati attesi.** I controllori
   producono comandi fisici; non ricevono regole come cercare cibo o cooperare.
   Sensori, azioni disponibili e condizioni riproduttive rimangono scelte imposte.
4. **Percezione locale e limitata.** Gli input rappresentano lo stato corporeo e
   misure locali. Non includono statistiche globali, genealogie, genomi altrui o
   informazioni remote privilegiate.
5. **Azioni neurali.** Accelerazione, rotazione, raccolta per contatto, emissioni e
   richiesta riproduttiva provengono dal sistema neurale individuale. Il motore ne
   applica limiti, costi e vincoli geometrici.
6. **Apprendimento distinto dall'eredità.** Il genoma descrive i parametri
   ereditabili; le modifiche acquisite nella vita sono uno stato separato. Nel
   modello attuale la prole inizia senza i delta acquisiti dal genitore.
7. **Selezione tramite mortalità e riproduzione.** Le conseguenze fisiche ed
   energetiche determinano la persistenza delle linee; la baseline non usa selezione
   esterna per punteggio.
8. **Regole fisiche e contabilizzazione esplicita.** Trasferimenti, rigenerazione e
   dissipazioni sono contabilizzati nel bilancio metabolico descritto nel README.
9. **Riproducibilità condizionata all'ambiente numerico.** Il logger registra seed,
   configurazione effettiva, sorgenti e ambiente. Non è garantita identità numerica
   fra ambienti incompatibili.
10. **Osservazione indipendente dalle decisioni.** Logger, Inspector e dashboard
    sono progettati e verificati per non cambiare dinamica, casualità o apprendimento.
    I record di intervento esistenti descrivono eventi senza applicarli al mondo.
11. **Nessun salvataggio artificiale dall'estinzione.** Il motore attuale non
    reinserisce individui né modifica automaticamente condizioni per impedire
    l'estinzione. Eventuali protocolli futuri di intervento avrebbero una provenienza
    distinta dalle osservazioni della baseline.
12. **Isolamento degli organismi.** I controllori attuali non ricevono accesso a
    sistema operativo, filesystem, rete o servizi esterni. L'implementazione offre isolamento
    architetturale, non una sandbox per eseguire codice arbitrario ostile.

Le evidenze principali sono in [Simulation](../src/digital_ecosystem/simulation.py),
[Brain](../src/digital_ecosystem/brain.py),
[Sensors](../src/digital_ecosystem/sensors.py),
[Reproduction](../src/digital_ecosystem/reproduction.py) e
[World](../src/digital_ecosystem/world.py). I contratti di osservazione sono descritti
in [OBSERVATIONS](OBSERVATIONS.md); la ricostruzione delle scelte è in DEC-002,
DEC-004, DEC-005, DEC-007, DEC-009 e DEC-010 del registro.

## Scelte implementative e vincoli tecnici attuali

Python, NumPy, Pygame CE, SQLite, dieci fondatrici, timestep, dimensioni del mondo,
16 input e 6 output, topologia iniziale, plasticità hebbiana, riproduzione
asessuata, numero di canali e limiti computazionali sono scelte della baseline.
Sono modificabili come le convenzioni scientifiche precedenti. Alcune scelte sono
però contratti effettivamente verificati dal codice corrente:

| Ambito | Vincolo della baseline | Effetti di una possibile revisione |
| --- | --- | --- |
| Runtime | Packaging limitato a Python `>=3.12,<3.13`. | Aggiornamento di dipendenze e verifiche dell'ambiente. |
| Interfaccia neurale | `Brain` e `Genome` validano 16 input e 6 output. | Revisione di sensori, azioni, genomi e stato persistito. |
| Struttura delle reti | Genomi aciclici con limiti configurati di nodi e connessioni. | Nuova semantica di inferenza e validazione se cambia il modello. |
| Parametri fisici | Configurazioni validate, incluso il limite `dt * max_speed <= body.radius`. | Revisione coerente di validazione e fisica se cambiano le assunzioni. |
| Checkpoint | Controlli su formato, nucleo e ambiente numerico compatibile. | Possibili migrazioni, nuove versioni del formato o incompatibilità da segnalare. |

Questi vincoli indicano cosa il software accetta oggi. Non impongono di conservare
in futuro la compatibilità tecnica o concettuale con una scelta abbandonata
dall'utente. Quando cambia il modello, la provenienza e l'integrità dei dati
precedenti restano da preservare, esplicitando quali confronti non sono più validi.

Il preset diagnostico serve a esercitare componenti con condizioni dichiarate.
Le sue nascite e sopravvivenze non costituiscono una validazione neutrale
dell'adattamento. Anche il preset sperimentale incorpora scelte progettuali:
la denominazione non dimostra assenza di influenze del progettista.

## Limiti dell'interpretazione scientifica

- Plasticità neurale non implica necessariamente apprendimento adattivo.
- Evoluzione non implica automaticamente aumento dell'intelligenza.
- Più neuroni o connessioni non implicano capacità cognitive superiori.
- Emissioni, contatti, sopravvivenza o crescita di una linea non bastano per
  dimostrare comunicazione, cooperazione o intelligenza.
- Non esistono evidenze nel repository che Digital Life Lab produca coscienza
  digitale; il progetto non rivendica tale risultato.
- Condizioni iniziali, sensori, azioni, costi, geometria e mutazioni sono influenze
  progettuali da dichiarare nei protocolli.
- Il bilancio riguarda energia metabolica utilizzabile, non una simulazione
  termodinamica completa di energia cinetica e calore.

I [rapporti di validazione](VALIDATION.md) e quelli delle
[M4](M4_VALIDATION.md), [M5](M5_VALIDATION.md) e [M6](M6_VALIDATION.md) documentano
correttezza operativa, riproducibilità e prestazioni nei rispettivi perimetri.
Non dimostrano adattamento o emergenza di capacità cognitive. Dataset sintetici
di stress e traiettorie simulate reali devono restare identificabili separatamente.

Per nuove analisi mantenere distinti dati osservati, ipotesi e conclusioni.
Definire prima indicatori, controlli, configurazioni e limiti interpretativi;
registrare anche estinzioni e risultati negativi. La disponibilità di confronti
fattoriali non equivale all'esecuzione del protocollo completo o a una prova causale.

## Direzioni future da discutere

Sono ipotesi **PROPOSED**, senza approvazione implicita di implementazione:
apprendimento predittivo; plasticità più sofisticata; nuovi organismi e nuove
interazioni; materiali manipolabili; modifiche ambientali durante le simulazioni;
possibile emergenza di strumenti e comportamenti collettivi; studi di evoluzione
aperta. Il loro perimetro e i protocolli possono evolvere insieme agli obiettivi;
non è richiesta compatibilità concettuale con tutte le convenzioni della baseline.

Fra le alternative possibili da discutere figurano anche reward espliciti,
ereditarietà di modifiche acquisite, percezione più ampia e protocolli con
interventi ambientali o di popolazione. Non sono implementazioni o risultati
attribuiti al repository attuale. Una loro adozione cambierebbe le domande e i
controlli sperimentali, senza essere vietata dalla storia del progetto.

L'evoluzione strutturale delle reti esiste già nella M2 per grafi aciclici;
estensioni a modelli ulteriori restano proposte. La rilocalizzazione delle risorse
ha un'implementazione nel solo branch `resource-moving`, non in `main`: ciò non
dimostra né approvazione generale di Dynamic Ecosystem né apprendimento adattivo.
Stato e lacune sono nella [ROADMAP](ROADMAP.md#sviluppi-successivi).

## Uso condiviso e revisione

Il [workflow condiviso](ROADMAP.md#workflow-condiviso-tra-agenti) offre riferimenti
per collaboratori e agenti, a prescindere dal prodotto utilizzato. Le differenze
fra nuova richiesta, codice e storia documentata servono a individuare rischi e
conseguenze; non bloccano automaticamente un cambiamento radicale già richiesto.

Questo documento si aggiorna quando evolve la direzione conosciuta del progetto.
Le nuove istruzioni esplicite dell'utente sono già una fonte sufficiente per
rivedere obiettivi, architettura e ipotesi, senza approvazioni ridondanti imposte
dalla documentazione. Le ragioni e le conseguenze del cambiamento trovano posto
in [DECISIONS](DECISIONS.md#manutenzione-del-registro), gli stati implementativi
nella ROADMAP. DEC-017 conserva l'istituzione originaria dei documenti;
[DEC-018](DECISIONS.md#dec-018--documentazione-descrittiva-e-direzione-rivedibile)
registra il ruolo descrittivo adottato con questa revisione.
