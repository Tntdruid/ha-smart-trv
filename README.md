<img src="custom_components/smart_trv/brand/icon@2x.png" alt="Smart TRV" width="128" align="right">

# Smart TRV (PI) – Home Assistant

Styrer radiatortermostater (Tuya **TV02** og **TRV602** via Zigbee2MQTT, og andre TRV'er, der er en `climate`-entitet) ud fra en **rumsensor** med en PI-regulator, så rummet faktisk rammer målet.

## Hvorfor en TRV ikke rammer målet

En TRV måler temperaturen lige ved den varme radiator, så den tror, rummet er varmere, end det er. Den almindelige løsning er at lægge forskellen mellem TRV-sensoren og rumsensoren oven i setpunktet. Det er en ren proportional korrektion, og en P-regulator ender altid med en fast restafvigelse. Ventilen skal stå lidt åben for at holde rummet varmt, og det kræver, at rummet er lidt *under* målet. Med TV02's 0,5 °C-trin lander det typisk på 21,5 °C, når målet er 22.

Smart TRV tilføjer et **integralled**: så længe rummet er under målet, skubber den langsomt TRV-setpunktet op, indtil afvigelsen er 0.

Afvigelsen ved ren offset-korrektion vokser med varmebehovet. Den er størst om natten, når det er koldest udenfor og radiatoren skal give mest.

Simulering af en langsom stue med kolde nætter og et vindue åbnet 11:15–11:30 (`python tests/simulate_stue.py`), mål 22 °C:

| | Døgnet (uden udluftning) |
|---|---|
| Kun offset-korrektion (P) | 21,39–22,01 °C |
| Smart TRV (PI) | 21,88–22,22 °C |

TRV'erne styres med et setpunkt, ikke ventilåbning i %. Står ventilen allerede helt åben, lærer integralet ikke mere, for et højere setpunkt ændrer ikke noget. Melder TRV'en selv, hvor åben ventilen er (TRV602's `position`), bruger Smart TRV det: 95 % eller mere er helt åben, 5 % eller mindre er lukket. Ellers regner den ventilen for helt åben, når setpunktet ligger mindst 2 °C over det, TRV'en selv måler. Med lune radiatorer (fjernvarme) måler TRV'en kun ca. 1 °C over rummet, også mens den varmer, så en grænse på 1 °C fik integralet til at stå stille og rummet til at blive under målet (`python tests/simulate_lukewarm.py`). Det forhindrer, at en kold radiator om natten "pumper" det lærte offset op, så rummet bliver for varmt, når solen kommer. Er ventilen helt åben i over 2 timer, uden at TRV'en bliver varmere end rummet, skriver forklaringen, at radiatoren ikke bliver varm.

Integralet lærer højst med 0,3 °C afvigelse ad gangen. Store afvigelser, fx efter udluftning, klares af P-leddet, så integralet ikke "pumper sig op" og giver overshoot om eftermiddagen.

## Understøttede TRV'er

Alle TRV'er, der i Home Assistant er en `climate`-entitet med setpunkt og egen temperaturmåling. Testet mod:

| | Sluk ved åbent vindue | "Varmer"-status | Bemærk |
|---|---|---|---|
| Tuya **TV02** | `hvac_mode: off` | gættes ud fra setpunkt og TRV'ens måling | kun 0,5 °C-trin |
| Tuya **TRV602** | preset `off` (den har ingen hvac off) | fra TRV'ens `running_state` | i Z2M: sæt **`max_temperature` til 35 °C** (ellers afviser den Smart TRV's setpunkter over max, og varmer aldrig), og `mode` til **comfort** (`eco` åbner/lukker kun helt) |

Har en TRV hverken hvac off eller preset off, sætter Smart TRV den til laveste setpunkt, mens vinduet er åbent.

Tager en TRV ikke imod det setpunkt, Smart TRV sender (den viser stadig noget andet efter 10 minutter), skriver forklaringen en ⚠️-advarsel om det.

## Installation

**Med HACS (anbefalet):**

1. HACS → ⋮ → **Brugerdefinerede repositories** → tilføj `https://github.com/Tntdruid/ha-smart-trv`, kategori **Integration**.
2. Søg efter **Smart TRV (PI)** i HACS → **Download**.
3. Genstart Home Assistant.
4. **Indstillinger → Enheder og tjenester → Tilføj integration → "Smart TRV (PI)"**.

HACS giver besked, når der kommer en ny version.

**Manuelt:** Kopiér mappen `custom_components/smart_trv` til `/config/custom_components/smart_trv` og genstart Home Assistant.

Ved opsætningen vælger du rumsensor, en eller flere TRV'er og eventuelt vinduessensorer.

Før du starter:

- **Slå anden styring af rummets TRV'er fra**, fx andre termostat-integrationer eller automationer, der sætter TRV'ens temperatur. Ellers kæmper de om den.
- **Sæt `local_temperature_calibration` til 0** på TRV'erne i Zigbee2MQTT. Et gammelt offset fra en tidligere styring skader ikke, men så starter regulatoren fra et kendt udgangspunkt.
- Integrationen sætter selv TRV'erne i preset `manual`, så deres interne ugeplan ikke overskriver setpunktet.

Brug den nye `climate.<navn>`-entitet i dit dashboard og dine automationer i stedet for TRV'en direkte.

## Indstillinger (kan ændres under "Konfigurer")

| Felt | Standard | Betydning |
|---|---|---|
| Kp | 3,0 | Hvor kraftigt der reageres på afvigelsen lige nu |
| Ki | 1,0 | Hvor hurtigt den sidste rest læres. Op = hurtigere, men mere overshoot |
| Max boost | 6 °C | Hvor langt over målet TRV-setpunktet må gå |
| Max sænkning | 3 °C | Hvor langt under målet TRV-setpunktet må gå |
| TRV-trin | 0,5 °C | TV02 tager kun halve grader |
| Interval | 5 min | Hvor tit der reguleres. Nye målinger fra rumsensoren vises med det samme, men TRV'en får kun nyt setpunkt ved reguleringen, og kun når det er flyttet mindst ét TRV-trin. Det holder motoren i ro: ca. 20 ændringer i døgnet i stedet for flere hundrede (`python tests/simulate_chatter.py`) |

## Vinduer og døre

Vælg vindues- og dørsensorer under **Konfigurer**. Så slukker Smart TRV TRV'erne, mens der er åbent, og læringen står på pause imens. To timere pr. rum:

| Felt | Standard | Betydning |
|---|---|---|
| Sluk efter åben | 60 sek. | Hvor længe der skal være åbent, før TRV'erne slukkes. En dør, man går igennem, slukker ikke varmen |
| Tænd igen efter lukket | 0 sek. | Hvor længe der skal være lukket, før varmen starter igen |

Mens timeren kører, står der fx "🪟 Vindue/dør åben: slukker om 45 sek." i forklaringen. Står vinduet allerede åbent, når Home Assistant starter, slukkes der med det samme.

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

**Viser kortet "Konfigurationsfejl", eller snurrer det i kortvælgeren?** Så er den automatiske indlæsning ikke slået igennem. Tilføj kortet som ressource (Indstillinger → Betjeningspaneler → ⋮ → Ressourcer → Tilføj, type *JavaScript-modul*):

- `/smart_trv/smart-trv-card.js`: integrationen leverer selv filen, så den altid følger med, når du opdaterer.
- eller kopiér `custom_components/smart_trv/frontend/smart-trv-card.js` til `/config/www/` og brug `/local/smart-trv-card.js`. Husk så at kopiere den igen ved hver opdatering, og sæt fx `?v=0.3.2` bag adressen, så browseren henter den nye version.

Preview uden Home Assistant: `python -m http.server` i repoet, og åbn `http://localhost:8000/tests/card_preview.html`.

## Forvarmning

Bruger rummet en **tidsplan** som natplan, starter Smart TRV varmen så tidligt, at rummet *er* på dagtemperatur, når natten slutter (tidsplanens `next_event`). Den lærer selv rummets opvarmningshastighed (°C/time) ved fuld varme. Indtil den har målt, regner den med 1 °C/time. Den forvarmer højst 6 timer før. Mens den gør det, står der "☀️ Forvarmer: rummet skal være 22,0 °C kl. 06:00" i forklaringen. Kan slås fra under Konfigurer → *Forvarm før natten slutter*.

Simulering (`python tests/simulate_learning.py`), nat 19 °C til 06:00, dag 22 °C: rummet er 21,8 °C kl. 06:00 med forvarmning, mod 19,0 °C uden.

## Udetemperatur

Vælg en udesensor under Konfigurer (fx `sensor.ude_ude_temperatur`). Så lægger Smart TRV `0,1 × (mål − ude)` oven i TRV-setpunktet og reagerer på kolde nætter, *før* rummet bliver koldt. Det lærte offset tager sig af resten. I simuleringen halveres svinget på en normal dag (21,75–22,24 → 21,89–22,13 °C). Tilføjes udesensoren til et rum, der allerede har lært, trækkes kompenseringen fra det lærte, så setpunktet ikke springer.

## Overvågning af TRV'er

`binary_sensor.<rum>_problem` tænder, når en TRV er **offline**, ikke har meldt sig i **6 timer**, eller har **under 20 % batteri**. Batterisensoren findes selv via TRV'ens enhed. Problemet står også som ⚠️ i forklaringen, og fanen **Hele huset** i dashboard-skabelonen samler alle rum og deres problemer. Brug sensoren i en automation, hvis du vil have en notifikation.

## Automatisk tuning

En gang i døgnet ser Smart TRV på, hvordan rummet har opført sig, når det regulerer roligt. Opstarten om morgenen, udluftning og helt åben ventil tæller ikke med.
- Svingede rummet frem og tilbage: Kp −15 % og Ki −10 %.
- Lå det typisk mere end 0,12 °C fra målet uden at svinge: Kp +15 % og Ki +20 %.
- Ellers: ingen ændring.

Grænser: Kp 1–6 og Ki 0,3–3. Klimaentiteten viser de aktuelle `kp`, `ki` og `last_tuning`. Ændrer du selv Kp/Ki under Konfigurer, starter tuningen forfra fra dine værdier. Kan slås fra under *Automatisk tuning af Kp/Ki*.

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
