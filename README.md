# Roblox RP Discord bot

Magyar nyelvű, moduláris Discord bot Roblox RP szerverekhez (Python, discord.py). Minden felirat, üzenet és parancsleírás magyarul van.

## Modulok és parancsok

| Modul | Mit tud | Parancsok |
|---|---|---|
| **Szerver nyitás / zárás** | beágyazott nyitás- és zárásüzenet, **a ping külön, az embeden kívül**, csatlakozás gomb, időzítés, **automatikus napi nyitás és zárás** | `/nyitas`, `/zaras`, dashboard: Szerver nyitás |
| **Jelentkezés** | a bot **privát üzenetben** kérdezi végig a jelentkezőt, a vezetők weben vagy gombbal döntenek, az **elfogadott ticketet nyithat** | `/jelentkezes`, `/staff panel`, dashboard: Jelentkezések |
| **Alapbeállítások** | napló, staff és vezetői rang, vezetői csatorna | `/beallitas naplo`, `staffrang`, `vezetoi`, `belepes`, `allapot` |
| **Belépés** | üdvözlés, alaprang, **tartós belépési napló** (visszatérők, korábbi szankciók jelzése) | `/beallitas belepes`, `/belepesek lista`, `/belepesek tag` |
| **Szankció rendszer** | ügyazonosítók, előzmények, automatikus eszkaláció | `/figyelmeztet`, `/nemit`, `/kirug`, `/kitilt`, `/felold`, `/elozmenyek`, `/visszavon` |
| **Erős moderáció** | spam, linkek, meghívók, szitokszűrő, tömeges említés, új fiók szűrő, raid mód | `/automod allapot`, `beallit`, `szo_hozzaad`, `szo_torol`, `szo_lista`, `link_engedelyez`, `link_lista`, `kivetel`, `raid` |
| **Ticket** | **szabadon testreszabható ticket-típusok** (név, emoji, szín, kezelő rang, csatornakategória, űrlapkérdések), átvétel, HTML átirat, értékelés | `/ticket panel`, `frissites`, `kategoria`, `hozzaad`, `eltavolit` |
| **Szolgálat (shift)** | belépés/kilépés, szünet, panel gombokkal, heti/havi összesítő, automatikus lezárás | `/shift start`, `stop`, `szunet`, `en`, `ki_szolgalatban`, `ranglista`, `panel`, `beallit` |
| **Inaktivitás** | kérelem, vezetői elbírálás gombokkal, inaktív rang, automatikus lejárat | `/inaktivitas keres`, `visszateres`, `lista`, `beallit` |
| **Staff** | jelentkezés űrlappal, havi teljesítmény, vezetői pontozás, automatikus riport | `/staff jelentkezes`, `teljesitmeny`, `riport`, `pontozas`, `beallit` |
| **Szint rendszer** | XP üzenetekért és hangcsatornáért, szintrangok, XP-szorzók | `/szint profil`, `toplista`, `rang_hozzaad`, `rang_torol`, `rangok`, `csatorna`, `kivetel`, `szorzo`, `xp_ad` |
| **Nyereményjáték** | gombos részvétel, feltételek (rang, szint), automatikus sorsolás, újrasorsolás | `/nyeremenyjatek inditas`, `befejez`, `ujrasorsol`, `lista` |
| **Javaslatok** | `👍`/`👎` szavazás, staff döntés státusszal | `/javaslat uj`, `dontes`, `csatorna` |
| **Statisztika** | aktív tagok, üzenetek, ticket idők, szolgálati idők, heti és havi riport | `/stats szerver`, `ticketek`, `shiftek`, `riport`, `csatorna` |
| **Súgó** | jogosultság szerinti parancslista, a bot állapota | `/segitseg`, `/bot` |
| **Karbantartás** | napi automatikus adatbázis-mentés, régi adatok takarítása | `/mentes` |
| **Dashboard** | modern webes felület: szinte minden beállítás, ticket-típusok szerkesztése, statisztikák, naplók | böngészőben (lásd lent) |

## Újdonságok (RP funkciók)

**Szerver nyitás és zárás.** A dashboard *Szerver nyitás* oldalán egy űrlapon megadod a csatornát, a pinget (`@everyone`, `@here` vagy egy rang), a színt, a címet, a szöveget, a szerverkódot és a csatlakozási linket; élő előnézet mutatja, hogyan fog kinézni. Az üzenet **szövegében** van a ping, a beágyazás külön alatta, így a ping tényleg értesít, és nincs az embedbe zárva. Azonnal kimehet vagy időzíthető, a sablon elmenthető, és a *Gyors nyitás* gombbal egy kattintással kimegy. A **zárás** új, beágyazott üzenetet küld külön pinggel (saját csatorna, ping, szín, cím és szöveg állítható), az eredeti nyitás üzenet pedig lehalkul (a ping és a gomb eltűnik). Az *Automatikus nyitás és zárás* kártyán megadható a napok, a nyitás és a zárás ideje (budapesti idő); az éjfél utáni zárás is működik.

**Jelentkezés privátban.** A `/jelentkezes` parancs vagy a kihelyezett panel *Jelentkezem* gombja után a bot privát üzenetben felteszi a kérdéseket (a kérdések a dashboardon állíthatók, legfeljebb 5), a végén összegzést mutat, és beküldés előtt megerősítést kér. A jelentkezés a vezetői csatornában és a dashboard *Jelentkezések* oldalán is megjelenik. Elbírálni mindkét helyen lehet, megjegyzéssel is. Elfogadáskor a jelentkező privátban értesítést kap (és opcionálisan rangot), alatta egy **Ticket nyitása** gombbal. Weben a vezető is nyithat neki ticketet; a jelentkezés válaszai bekerülnek a ticketbe. Beállítható az is, hogy a ticket elfogadáskor magától megnyíljon.

**Szankciók a weben.** A *Szankciónapló* oldalon figyelmeztetés, némítás, kirúgás és kitiltás adható ki (azonosító, említés vagy név alapján, kitiltás szerveren kívüli azonosítóra is), a sorokból visszavonható a figyelmeztetés/némítás, és feloldható a kitiltás. Ugyanazokat az ellenőrzéseket és naplózást használja, mint a Discord parancsok.

**Ticketek a weben.** A *Ticketek* oldalon ticket nyitható egy tagnak, a nyitott ticketek pedig lezárhatók (átirat a naplócsatornába).

**Telefonon.** A dashboard telefonra van méretezve: alsó gyorsmenü, nagy érintési felületek, a táblázatok görgethetők, az űrlapmezők nem nagyítanak rá iPhone-on. Telefonról éréséhez a dashboardot HTTPS mögé kell tenni (lásd lent).

## Telepítés

1. **Python 3.10 vagy újabb** szükséges.
2. A [Discord Developer Portalon](https://discord.com/developers/applications) hozz létre egy alkalmazást és egy botot.
   A **Bot** fülön kapcsold be ezt a két *Privileged Gateway Intent*-et: **Server Members Intent** és **Message Content Intent**.
3. Hívd meg a botot a szerverre az **OAuth2 → URL Generator** fülön (`bot` és `applications.commands` jogkör).
   Szükséges jogosultságok: *Rangok kezelése, Csatornák kezelése, Tagok kirúgása, Tagok kitiltása, Tagok moderálása,
   Üzenetek kezelése, Üzenetelőzmények olvasása, Üzenetek küldése, Beágyazott linkek, Fájlok csatolása, Naplók megtekintése.*
   (A *Naplók megtekintése* csak a Discord felületén végzett kitiltások és kirúgások rögzítéséhez kell. Nélküle a bot ezeket nem látja, minden más működik.)
   **Fontos:** a bot rangja legyen a szerver rangsorában **magasabban** minden rangnál, amit kezelnie kell (alaprang, szintrangok, szolgálati rang, inaktív rang).
4. `pip install -r requirements.txt`
5. Másold le a `.env.example` fájlt `.env` néven, és írd bele a bot tokenjét. (A `GUILD_ID` megadásával a parancsok azonnal megjelennek, különben akár egy óráig is eltarthat.)
6. Indítás: `python main.py`. Az adatbázis (`dcbot.db`) az első indításkor automatikusan létrejön.

## Első beállítás (ebben a sorrendben)

1. `/beallitas naplo` – naplócsatorna
2. `/beallitas staffrang` – a staff rangja
3. `/beallitas vezetoi` – vezetői csatorna és vezetői rang (ide érkeznek a jelentkezések, inaktivitási kérelmek, staff riportok)
4. `/beallitas belepes` – üdvözlő csatorna, alaprang, opcionális egyedi üzenet (`{tag}`, `{szerver}`, `{szam}`)
5. `/ticket kategoria` és `/ticket panel` – ticketek
6. `/shift panel` (és opcionálisan `/shift beallit`) – szolgálat
7. `/inaktivitas beallit` – az inaktív rang
8. `/javaslat csatorna`, `/stats csatorna`, `/szint rang_hozzaad` – javaslatok, riportok, szintrangok
9. `/automod allapot` – a moderáció alapértékeinek ellenőrzése

A beállítások nagy részét a **dashboardon** is el lehet végezni, egyetlen űrlapon.

## Jogosultságok

- **Adminisztrátor:** minden beállítás.
- **Vezető** (`/beallitas vezetoi`): jelentkezések és inaktivitási kérelmek elbírálása, staff pontozás, mások teljesítményének megtekintése.
- **Staff** (`/beallitas staffrang`): moderációs parancsok, ticketek, szolgálat, inaktivitás, javaslatok eldöntése, nyereményjáték indítása.
- **Mindenki:** `/javaslat uj`, `/staff jelentkezes`, `/szint profil`, `/szint toplista`, ticketnyitás, nyereményjátékban részvétel.

## Szankció-eszkaláció

- Minden büntetés egyedi **ügyazonosítót** kap (pl. `#12`), és bekerül a naplócsatornába.
- A figyelmeztetések **30 nap** után lejárnak (nem számítanak az eszkalációba, de az előzményekben megmaradnak).
- **3 aktív figyelmeztetés** → automatikus 24 órás némítás. **5 aktív figyelmeztetés** → automatikus kitiltás.
- Az erős moderáció is ezt használja: törlés → figyelmeztetés → némítás → kitiltás.
- Az értékek a `cogs/szankcio.py` fájl elején módosíthatók.

## Erős moderáció – tudnivalók

- A **staff tagok** és a `/automod kivetel` csatornák mentesülnek a szűrők alól.
- **Linkek:** a GIF-ek és hasonló oldalak engedélyezettek (Tenor, Giphy, Imgur, Gyazo, Streamable, Medal, YouTube, Twitch, Spotify, Roblox, Discord-csatolmányok). Más linket a bot töröl. Az oldalak listája a `/automod link_engedelyez` paranccsal (vagy a dashboardon) bővíthető. A csatolt képek és videók nem linkek, azokra nem vonatkozik a szűrő.
- **Szitokszűrő:** ékezet-, írásjel- és leet-mentes (`k.u.r.v.a`, `b4zdmeeeg`, `bazd meg` is találat). Az alaplista magyar és angol szavakat tartalmaz. A `=` jellel kezdődő szó (pl. `=fasz`) csak önálló szóként számít, így a `fasza` nem találat. Egy rövid szó ártatlan szavakban is előfordulhat, ezért a listán óvatosan bánj a rövid, `=` nélküli szavakkal. A lista a `/automod szo_*` parancsokkal szerkeszthető.
- **Spam:** 5 üzenet 6 másodpercen belül, vagy ugyanaz az üzenet 3-szor. A bot a spammelő friss üzeneteit is törli.
- **Új fiók szűrő:** a 3 napnál fiatalabb Discord-fiókokat a bot kirúgja (DM-ben elmagyarázza az okát).
- **Raid mód:** ha 15 másodperc alatt 6 tag csatlakozik, a bot riasztást küld a naplócsatornába (staff ping), kirúgja a gyanús belépőket, és 10 percig minden új belépőt kirúg. Kézzel: `/automod raid`.
- Csak a spam-számláló él memóriában (másodperceket él meg). A belépések és a **raid mód állapota tartósan az adatbázisban van**: újraindítás után sem vész el, és a raid-érzékelés is ebből számol.

## Belépési napló

Minden belépés és kilépés bekerül az adatbázisba (`belepesek` tábla): mikor lépett be, mikor jött létre a fiókja, maradt-e vagy az automatikus moderáció kirúgta, és mikor lépett ki.
- A naplócsatornába érkező belépési üzenet jelzi, ha a tag **visszatérő** (hányadik belépése), és ha van **korábbi szankciója**. Ilyenkor narancssárga.
- `/belepesek lista` az elmúlt napok belépéseit, `/belepesek tag` egy felhasználó teljes történetét mutatja.
- A Discord felületén végzett kitiltásokat, feloldásokat és kirúgásokat a bot is rögzíti a szankció-előzményekbe, hogy a lista teljes legyen.

## Szolgálat, inaktivitás, staff értékelés

- A szolgálati időt a bot méri, a szünet nem számít bele. Aki elfelejt kilépni, annak a szolgálata 8 óra után automatikusan lezárul (állítható: `/shift beallit`).
- Az inaktivitási kérelmet (`/inaktivitas keres`) a vezetők a kérelem alatti gombokkal fogadják el vagy utasítják el. Elfogadás után a tag megkapja az inaktív rangot, lejáratkor a bot visszaveszi.
- A **havi staff riport** automatikusan megjelenik a vezetői csatornában a hónap első napján (szolgálati idő, átvett ticketek, szankciók, értékelések, inaktivitás, vezetői pontszám).
- Ha beállítod a heti minimális szolgálati időt (`/staff beallit`), a bot hétfőnként jelzi a vezetőknek, ki nem érte el (az igazoltan inaktívak kivételével).

## Mentés és karbantartás

- A bot 6 óránként ellenőrzi, és naponta egyszer **mentést készít** az adatbázisról a `mentesek/` mappába (alapból az utolsó 7 napot őrzi meg; a mappa a `.env`-ben a `MENTES_MAPPA` értékkel módosítható). Azonnali mentés: `/mentes`.
- A 400 napnál régebbi napi statisztikát és belépési naplót a bot törli, hogy az adatbázis ne hízzon el.
- **Visszaállítás:** állítsd le a botot, másold a kívánt mentést `dcbot.db` néven a bot mappájába, indítsd újra.
- A mentés ugyanazon a gépen készül, ahol a bot fut. Fontos adatoknál időnként másold máshová is a `mentesek/` mappát.

## Statisztika

A `/stats` parancsok bármikor lekérdezhetők. A `/stats csatorna` beállítása után a bot hétfőnként heti, a hónap első napján havi riportot küld (8:00 után).

## Dashboard (webes felület)

A dashboard a Discord-fiókoddal való belépés után érhető el, és csak azokat a szervereket mutatja, ahol adminisztrátor vagy. Sötét és világos témában is használható (a 🌓 gombbal váltható), és telefonról is kényelmes.

**Oldalak:**
- **Áttekintés:** állapotellenőrző lista (mi hiányzik még: csatornák, rangok, a bot jogosultságai, rangsor-problémák), teendők (elbírálásra váró jelentkezések, kérelmek, javaslatok közvetlen linkkel), számlálók, napi üzenetdiagram, legutóbbi események.
- **Alapok, Belépés, Szintek, Javaslatok és játékok, Staff és szolgálat:** a hozzájuk tartozó beállítások űrlapon. A belépési üzenetnél élő előnézet van.
- **Ticketek:** a ticket-típusok teljes szerkesztője (lásd lent), a panel kihelyezése és frissítése, a ticketek listája.
- **Automod és szankciók:** minden szűrő és küszöb, tiltott szavak, engedélyezett oldalak, kivételcsatornák, eszkaláció-beállítások, a legutóbbi szankciók.
- **Belépés:** a belépések tartós naplója, raid mód gombbal.
- **Statisztika:** diagramok (üzenetek, belépések/kilépések), legaktívabb tagok és csatornák, ticket-átlagok és megoszlás, szolgálati idők 7, 14, 30 vagy 90 napra.
- **Szankciónapló:** szűrhető teljes lista.

**Ticket-típusok testreszabása:** minden típushoz megadható a név, az emoji (akár egyedi szerver-emoji), a leírás, a ticket színe, az üdvözlő szöveg, a csatornakategória, a kezelő rang (csak ez látja az ilyen ticketeket) és legfeljebb 5 kérdés. A kérdések ticketnyitás előtt űrlapként jelennek meg, a válaszok bekerülnek a ticketbe. A típusok átrendezhetők, ideiglenesen elrejthetők, törölhetők, és a kihelyezett panel minden módosítás után magától frissül. Legfeljebb 25 típus lehet.

**Más testreszabható dolgok:** a staff jelentkezési űrlap kérdései, az XP mennyisége és a várakozás, a hangcsatornás XP, a szintrangok és XP-szorzók, a szankció-eszkaláció küszöbei és lejáratai, az egyszerre nyitható ticketek száma, a panel címe, szövege és színe.

**Beállítás:**
1. A Developer Portalon az **OAuth2** oldalon másold ki a **Client ID**-t és a **Client Secret**-et.
2. Ugyanitt a **Redirects** listához add hozzá: `<DASHBOARD_URL>/callback` (pl. `http://localhost:8080/callback`), és kattints a **Save Changes** gombra.
3. Töltsd ki a `.env`-ben: `CLIENT_ID`, `CLIENT_SECRET`, `DASHBOARD_URL`, és egy hosszú, véletlen `SESSION_SECRET`-et.
4. Indítsd újra a botot, és nyisd meg a `DASHBOARD_URL` címet.

Alapból csak a saját gépről érhető el (`127.0.0.1`). Ha az interneten át akarod elérni, **tegyél elé HTTPS-t** (pl. Caddy vagy nginx reverse proxy), állítsd a `DASHBOARD_URL`-t `https://`-re, és ne tedd közvetlenül nyilvánossá a 8080-as portot. Minden űrlap CSRF-védett, a kimenet escape-elt, a belépés aláírt sütivel történik.

## Önellenőrzés

```
python teszt.py              # a szűrők és a számítások tesztje
python teszt_integracio.py   # belépési napló, raid, mentés, dashboard (ideiglenes adatbázissal)
python teszt_rp.py           # nyitás/zárás, jelentkezés, ticket, szankció, webes oldalak
```
