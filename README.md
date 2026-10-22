# Smart TRV (PI) – Home Assistant

Styrer radiatortermostater (testet mod modellen af Tuya **TV02-Zigbee** via Zigbee2MQTT) ud fra en **rumsensor** med en PI-regulator.

## Hvorfor Better Thermostat hænger på 21,5 °C

TV02 måler temperaturen lige ved den varme radiator. Better Thermostat retter for det ved at lægge forskellen mellem TRV-sensoren og rumsensoren oven i setpunktet. Det er en ren proportional korrektion, og en P-regulator ender altid med en fast restafvigelse. Ventilen skal stå lidt åben for at holde rummet varmt, og det kræver, at rummet er lidt *under* målet. Med TV02's 0,5 °C-trin lander det typisk på 21,5 °C.

Smart TRV tilføjer et **integralled**: så længe rummet er under målet, skubber den langsomt TRV-setpunktet op, indtil afvigelsen er 0.

Det passer med stuen: om natten, når det er koldest udenfor og radiatoren skal give mest, falder den til ~21,3 °C. Om eftermiddagen er den tættere på målet. Afvigelsen vokser med varmebehovet, og det er netop P-reguleringens kendetegn.

Simulering af en langsom stue med kolde nætter og et vindue åbnet 11:15–11:30 (`python tests/simulate_stue.py`), mål 22 °C:

| | Døgnet (uden udluftning) |
|---|---|
| Better Thermostat-agtig | 21,39–22,01 °C |
| Smart TRV (PI) | 21,88–22,22 °C |

TV02 kan ikke styres med ventilåbning i %, kun med et setpunkt. Integrationen regner derfor ventilen ud fra TV02's egen måling. Ligger setpunktet mindst 1 °C over det, TRV'en måler, står ventilen helt åben, og så lærer integralet ikke mere, for et højere setpunkt ændrer ikke noget. Det forhindrer, at en kold radiator om natten "pumper" det lærte offset op, så rummet bliver for varmt, når solen kommer. Er ventilen helt åben i over 2 timer, uden at TRV'en bliver varmere end rummet, skriver forklaringen, at radiatoren ikke bliver varm.

Integralet lærer højst med 0,3 °C afvigelse ad gangen. Store afvigelser, fx efter udluftning, klares af P-leddet, så integralet ikke "pumper sig op" og giver overshoot om eftermiddagen.

## Installation

1. Kopiér mappen `custom_components/smart_trv` til `/config/custom_components/smart_trv` i Home Assistant.
2. Genstart Home Assistant.
3. **Indstillinger → Enheder og tjenester → Tilføj integration → "Smart TRV (PI)"**.
4. Vælg rumsensor, en eller flere TV02'ere og eventuelt vinduessensorer.

Før du starter:

- **Slå Better Thermostat fra for det rum** (slet eller deaktivér BT-entiteten). Ellers kæmper de to om TV02'en.
- **Sæt `local_temperature_calibration` på TV02 til 0** i Zigbee2MQTT. BT kan have efterladt et offset. Det skader ikke, men så starter regulatoren fra et kendt udgangspunkt.
- Integrationen sætter selv TV02 i preset `manual`, så den interne ugeplan ikke overskriver setpunktet.

Brug den nye `climate.<navn>`-entitet i dit dashboard og dine automationer i stedet for TV02'en direkte.

## Indstillinger (kan ændres under "Konfigurer")

| Felt | Standard | Betydning |
|---|---|---|
| Kp | 3,0 | Hvor kraftigt der reageres på afvigelsen lige nu |
| Ki | 1,0 | Hvor hurtigt den sidste rest læres. Op = hurtigere, men mere overshoot |
| Max boost | 6 °C | Hvor langt over målet TRV-setpunktet må gå |
| Max sænkning | 3 °C | Hvor langt under målet TRV-setpunktet må gå |
| TRV-trin | 0,5 °C | TV02 tager kun halve grader |
| Interval | 5 min | Hvor tit der reguleres. Der sendes kun Zigbee-kommandoer, når setpunktet faktisk ændrer sig (sparer batteri) |

## Nattemperatur pr. rum

1. Lav en tidsplan i Home Assistant (Indstillinger → Enheder og tjenester → Hjælpere → Tidsplan), fx `schedule.christian_nat_varme`, der er **tændt om natten**. Flere rum kan godt dele samme plan.
2. På rummet: **Konfigurer → Natplan** → vælg tidsplanen. En `input_boolean` eller `binary_sensor` virker også.
3. Indstil **Nattemperatur** (`number.<rum>_night_temperature`) på enhedssiden eller dashboardet. Hvert rum har sin egen.

Når planen er tændt, styrer rummet efter nattemperaturen, og forklaringen starter med 🌙. Termostatkortet viser altid det aktuelle mål. Drejer du på det om natten, ændrer du nattemperaturen, og om dagen ændrer du dagtemperaturen. Skiftet mellem dag og nat lærer ikke integralet noget forkert, fordi ventilen står helt lukket eller helt åben, mens rummet skifter temperatur.

## Smart TRV-kortet

Integrationen har sit eget dashboardkort, som den selv indlæser. Du skal ikke tilføje nogen ressource.

Rediger dashboard → **Tilføj kort** → søg **"Smart TRV"** → vælg rummet. Eller i YAML:

```yaml
type: custom:smart-trv-card
entity: climate.stue_varme_test
show_graph: true   # 24 timers graf af rum vs. mål (valgfri)
```

Kortet viser:
- Rumtemperatur og mål med −/+ (venter, til du holder op med at klikke, før det sender)
- Status (Varmer, Ventil lukket, Vindue åbent, 🌙 nat) og tænd/sluk
- TRV-setpunkt, hvad TRV'en måler, lært offset og afvigelse
- Forklaringen i en sætning, med ⚠️-advarsler fremhævet
- Nattemperatur med −/+

Klik på en værdi for at se dens historik. Kortet finder selv rummets sensorer, så du skal kun vælge climate-entiteten.

Preview uden Home Assistant: `python -m http.server` i repoet, og åbn `http://localhost:8000/tests/card_preview.html`.

## Se hvad den laver

Integrationen laver sensorer, der kan vises som grafer (eksempel for "Stue"):

| Sensor | Viser |
|---|---|
| `sensor.stue_status` | Varmer / Ventil lukket / Vindue åbent / Slukket / Ingen rummåling. Attributten `explanation` forklarer i en sætning, hvad den gør og hvorfor |
| `sensor.stue_trv_setpoint` | Hvad TV02 har fået besked på |
| `sensor.stue_trv_temperature` | Hvad TV02 selv måler |
| `sensor.stue_error` | Mål minus rumtemperatur |
| `sensor.stue_p_term` | Den direkte reaktion på afvigelsen |
| `sensor.stue_integral` | Det lærte offset. Når den flader ud, har den lært rummet |

**Færdigt dashboard, der finder dine entiteter selv:**

1. Åbn **Udviklerværktøjer → Skabelon**, slet indholdet i venstre side, og indsæt hele [dashboard/generate_dashboard.jinja](dashboard/generate_dashboard.jinja).
2. Kopiér resultatet i højre side.
3. Lav et nyt dashboard → ✏️ Rediger → ⋮ → *Rå konfigurationseditor*, og indsæt det.

Du får én fane pr. Smart TRV-rum, uanset hvad du har kaldt dem. Hver fane viser forklaringen lige nu, grafer for rum/mål, TRV og regulatoren, plus en logbog over, hvad den har gjort. Tilføjer du flere rum senere, så kør skabelonen igen.

Tjenesten `smart_trv.reset_integral` nulstiller det lærte offset, fx hvis du flytter rumsensoren.

**Tuning:** svinger rummet op og ned, så sænk Ki (fx 0,5). Tager det for lang tid at nå målet, så hæv Ki eller Kp lidt. Det lærte integral gemmes ved genstart.

## Vil du hellere blive på Better Thermostat?

Prøv først det her:
- Kalibreringstype **"Target Temperature Based"** og kalibreringstilstand **"Aggressive"** (eller "AI Time Based").
- Tjek, at **tolerance** står på 0.
- Den faste restafvigelse forsvinder dog ikke helt, fordi BT ikke har et integralled.
