"""Füstteszt az RP funkciókhoz: nyitás/zárás, jelentkezés, ticket, szankció, webes oldalak.

Futtatás: python teszt_rp.py
Ha a discord.py / aiohttp / aiosqlite nincs telepítve, a teszt_helyettesitok.py egyszerűsített helyettesítőket tölt be,
így a logika (SQL, döntések, üzenetek felépítése, HTML) ellenőrizhető Discord nélkül is. Ez nem helyettesíti a valódi,
szerveren végzett kipróbálást.
"""
import asyncio, os, sys, tempfile, time
from datetime import datetime, timedelta
from types import SimpleNamespace

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
try:
    import discord, aiohttp, aiosqlite  # noqa
    VALODI = True
except ImportError:
    import teszt_helyettesitok
    teszt_helyettesitok.telepit()
    VALODI = False

import discord
from db import DB
from util import IDOZONA, ts
from cogs.nyitas import Nyitas, NyitasHiba
from cogs.staff import JelentkezesHiba, Staff
from cogs.szankcio import Szankcio, SzankcioHiba
from cogs.ticket import Ticket
from cogs.dashboard import Dashboard

ELKULDOTT = []


class Rang:
    def __init__(self, id, nev, hely=1, alap=False): self.id, self.name, self.hely, self._alap = id, nev, hely, alap
    def is_default(self): return self._alap
    def __ge__(self, o): return self.hely >= o.hely
    def __lt__(self, o): return self.hely < o.hely
    def __eq__(self, o): return isinstance(o, Rang) and o.id == self.id
    def __hash__(self): return self.id
    @property
    def mention(self): return f"<@&{self.id}>"
    @property
    def members(self): return []


class Uzenet:
    def __init__(self, csatorna, id, **kw): self.csatorna, self.id, self.kw = csatorna, id, kw; self.embeds = [kw["embed"]] if kw.get("embed") else []
    async def edit(self, **kw): self.kw.update(kw); ELKULDOTT.append(("edit", self.csatorna.id, kw)); self.embeds = [kw["embed"]] if kw.get("embed") else self.embeds


class Csatorna:
    def __init__(self, id, nev): self.id, self.name, self.uzenetek = id, nev, {}
    @property
    def mention(self): return f"<#{self.id}>"
    async def send(self, **kw):
        u = Uzenet(self, 5000 + len(ELKULDOTT), **kw); self.uzenetek[u.id] = u; ELKULDOTT.append(("send", self.id, kw)); return u
    async def fetch_message(self, id):
        if id not in self.uzenetek: raise discord.NotFound()
        return self.uzenetek[id]
    async def delete(self, **k): pass


class Tag:
    def __init__(self, id, nev, rangok=None, hely=1):
        self.id, self.display_name, self.name, self.bot, self.roles, self.joined_at = id, nev, nev, False, list(rangok or []), None
        self.top_role, self.dm, self.timeout_ = Rang(100 + id, "r", hely), [], None
        self.display_avatar = SimpleNamespace(url="https://x/a.png")
    @property
    def mention(self): return f"<@{self.id}>"
    async def send(self, **kw): self.dm.append(kw)
    async def add_roles(self, *r, **k): self.roles += list(r)
    async def timeout(self, d, **k): self.timeout_ = d
    async def kick(self, **k): pass
    def __hash__(self): return self.id
    def __eq__(self, o): return getattr(o, "id", None) == self.id


class Szerver:
    def __init__(self):
        self.id, self.name, self.owner_id, self.member_count = 1, "Teszt RP", 1, 3
        self.csatornak = {c.id: c for c in (Csatorna(10, "nyitas"), Csatorna(11, "vezetoi"), Csatorna(12, "naplo"), Csatorna(13, "zaras"))}
        self.rangok = {r.id: r for r in (Rang(1, "@everyone", 0, True), Rang(20, "staff", 5), Rang(21, "vezeto", 6), Rang(22, "tag", 2), Rang(23, "ping", 1))}
        self.tagok, self.tiltottak, self.categories = {}, [], []
        self.me = Tag(999, "bot", hely=50); self.me.guild_permissions = SimpleNamespace(**{k: True for k in (
            "manage_roles", "kick_members", "ban_members", "moderate_members", "manage_channels", "manage_messages", "view_audit_log")})
        self.default_role, self.icon = self.rangok[1], None
    @property
    def text_channels(self): return list(self.csatornak.values())
    @property
    def roles(self): return list(self.rangok.values())
    def get_channel(self, i): return self.csatornak.get(i)
    def get_role(self, i): return self.rangok.get(i)
    def get_member(self, i): return self.tagok.get(i)
    def get_member_named(self, n): return next((t for t in self.tagok.values() if t.display_name == n), None)
    async def query_members(self, **k): return []
    async def create_text_channel(self, nev, **k):
        c = Csatorna(900 + len(self.csatornak), nev); self.csatornak[c.id] = c; return c
    async def ban(self, cel, **k): self.tiltottak.append(cel.id)
    async def unban(self, cel, **k):
        if cel.id not in self.tiltottak: raise discord.NotFound()
        self.tiltottak.remove(cel.id)


class Bot:
    def __init__(self, db, g):
        self.db, self.g, self.user, self.dontes_kezelok, self.cogs = db, g, Tag(999, "bot"), {}, {}
        self.guilds = [g]
    def get_cog(self, n): return self.cogs[n]
    def get_guild(self, i): return self.g if i == 1 else None
    async def fetch_user(self, i): return self.g.tagok.get(i) or Tag(i, f"u{i}")
    def add_view(self, *a): pass
    def add_dynamic_items(self, *a): pass


def ellenor(felt, szoveg):
    if not felt:
        print("HIBA:", szoveg); sys.exit(1)
    print("ok  ", szoveg)


async def fo():
    fajl = tempfile.mktemp(suffix=".db")
    db = DB(fajl); await db.start()
    g = Szerver(); bot = Bot(db, g)
    bot.cogs.update({"Nyitas": Nyitas(bot), "Staff": Staff(bot), "Szankcio": Szankcio(bot), "Ticket": Ticket(bot),
                     "Statisztika": SimpleNamespace(ment_most=lambda: asyncio.sleep(0)),
                     "Shift": SimpleNamespace(ranglista=lambda *a, **k: asyncio.sleep(0, result=[]))})
    ny, staff, szank, ticket = (bot.cogs[x] for x in ("Nyitas", "Staff", "Szankcio", "Ticket"))
    admin = SimpleNamespace(id=1, mention="<@1>", display_name="Admin")
    for t in (Tag(2, "Jelentkezo"), Tag(3, "Jelentkezo2"), Tag(4, "Rosszalkodo")): g.tagok[t.id] = t
    await db.set(1, "staffrang", "20"); await db.set(1, "vezetorang", "21"); await db.set(1, "vezetoi_csatorna", "11"); await db.set(1, "naplo", "12")

    # ---------------------------------------------------------------- nyitás és zárás
    azon, azonnal = await ny.kozzetesz(g, csatorna_id=10, cim="Nyitva!", szoveg="Gyertek", szin="#2ecc8f", ping="everyone",
                                       link="https://roblox.com/x", kod="ABC", kuldte=1, kuldte_nev="Admin")
    elso = [x for x in ELKULDOTT if x[0] == "send" and x[1] == 10][-1][2]
    ellenor(azonnal and elso["content"] == "@everyone", "a nyitás pingje az üzenet szövegében van")
    ellenor("@everyone" not in (elso["embed"].description or "") and elso["embed"].title == "Nyitva!", "a ping nincs a beágyazásban")
    ellenor(elso["allowed_mentions"].k.get("everyone") is True, "az everyone említés engedélyezve van")
    ellenor(elso["view"] is not None, "a csatlakozás gomb kint van")
    await ny.lezar(g, azon, "Admin")
    szerk = [x for x in ELKULDOTT if x[0] == "edit" and x[1] == 10][-1][2]
    ellenor(szerk["content"] is None and szerk["view"] is None, "a nyitás üzenetről lekerül a ping és a gomb")
    zaras = [x for x in ELKULDOTT if x[0] == "send" and x[1] == 10][-1][2]
    ellenor(zaras["content"] == "@here" and "lezárult" in zaras["embed"].title, "a zárás külön üzenet: beágyazás + külön ping")
    sor = await db.fetchone("SELECT * FROM nyitasok WHERE id=?", (azon,))
    ellenor(sor["statusz"] == "lezarva" and sor["zaras_uzenet_id"], "a nyitás lezárva az adatbázisban")
    try:
        await ny.lezar(g, azon); ellenor(False, "kétszeres zárás tiltott")
    except NyitasHiba:
        ellenor(True, "kétszeres zárás tiltott")
    await db.set(1, "zaras_csatorna", "13"); await db.set(1, "zaras_ping", ""); await db.set(1, "zaras_cim", "Vége")
    a2, _ = await ny.kozzetesz(g, csatorna_id=10, cim="N2", szoveg="x", szin=None, ping="rang:23", link="", kod="", kuldte=1, kuldte_nev="Admin")
    ellenor([x for x in ELKULDOTT if x[1] == 10][-1][2]["content"] == "<@&23>", "rang ping")
    await ny.lezar(g, a2)
    z2 = [x for x in ELKULDOTT if x[0] == "send" and x[1] == 13][-1][2]
    ellenor(z2["content"] is None and z2["embed"].title == "Vége", "külön zárás csatorna, ping nélkül, saját cím")
    i3, kijott = await ny.kozzetesz(g, csatorna_id=10, cim="Később", szoveg="", szin=None, ping="", link="", kod="", kuldte=1, kuldte_nev="A", idopont=ts() + 3600)
    ellenor(not kijott and (await db.fetchone("SELECT statusz FROM nyitasok WHERE id=?", (i3,)))["statusz"] == "idozitett", "időzített nyitás vár")
    await ny.torol(g, i3)
    for rossz in (dict(link="http://nem-https.hu"), dict(cim="  ")):
        try:
            kw = dict(csatorna_id=10, cim="x", szoveg="", szin=None, ping="", link="", kod="", kuldte=1, kuldte_nev="A"); kw.update(rossz)
            await ny.kozzetesz(g, **kw); ellenor(False, "érvénytelen adat elutasítva")
        except NyitasHiba:
            ellenor(True, f"érvénytelen adat elutasítva {list(rossz)}")

    # automatikus nyitás/zárás
    most_ = datetime.now(IDOZONA) - timedelta(minutes=1)
    if most_.date() == datetime.now(IDOZONA).date():
        await db.set(1, "nyitas_auto", "1"); await db.set(1, "nyitas_csatorna", "10"); await db.set(1, "nyitas_ping", "everyone")
        await db.set(1, "nyitas_auto_nyit", most_.strftime("%H:%M"))
        db_elott = (await db.fetchone("SELECT COUNT(*) AS n FROM nyitasok"))["n"]
        await ny.automatikus(g); await ny.automatikus(g)
        ellenor((await db.fetchone("SELECT COUNT(*) AS n FROM nyitasok"))["n"] == db_elott + 1, "az automatikus nyitás pontosan egyszer fut le")
        sor = await db.fetchone("SELECT * FROM nyitasok WHERE statusz='kuldve' ORDER BY id DESC LIMIT 1")
        ellenor(sor and sor["kuldte_nev"] == "Automata" and sor["ping"] == "everyone", "az automatikus nyitás a mentett sablonnal megy")
        await db.set(1, "nyitas_auto_zar", datetime.now(IDOZONA).strftime("%H:%M"))
        await ny.automatikus(g)
        ellenor((await db.fetchone("SELECT statusz FROM nyitasok WHERE id=?", (sor["id"],)))["statusz"] == "kuldve", "a ma nyitott szerver nem záródik a mai záróidőnél korábban")
        await db.execute("UPDATE nyitasok SET letrehozva=? WHERE id=?", (ts() - 86400, sor["id"]))
        await db.torol(1, "nyitas_auto_utolso_zar")
        await ny.automatikus(g)
        ellenor((await db.fetchone("SELECT statusz FROM nyitasok WHERE id=?", (sor["id"],)))["statusz"] == "lezarva", "az éjszakai (tegnap nyitott) szerver automatikusan zárul")

    # ---------------------------------------------------------------- jelentkezés
    jel = g.tagok[2]
    azon = await staff.jelentkezes_bead(g, jel, {"Hány éves vagy?": "18", "Miért te?": "Mert jó vagyok"}, "dm")
    ellenor(bool(g.csatornak[11].uzenetek), "a jelentkezés kikerült a vezetői csatornába")
    r = await db.fetchone("SELECT * FROM jelentkezesek WHERE id=?", (azon,))
    ellenor(r["forras"] == "dm" and r["statusz"] == "fuggoben" and r["uzenet_id"], "a jelentkezés DM-forrással elmentve")
    try:
        await staff.jelentkezes_bead(g, jel, {"a": "b"}); ellenor(False, "dupla jelentkezés tiltott")
    except JelentkezesHiba:
        ellenor(True, "dupla jelentkezés tiltott")
    await db.set(1, "jelentkezes_rang", "22")
    e = await staff.jelentkezes_dont(g, azon, admin, True, "Üdv a csapatban!")
    ellenor(e["dm"] and e["rang"] == "tag" and not e["rang_hiba"], "elfogadás: privát értesítés és rang")
    ellenor(jel.dm and jel.dm[-1].get("view") is not None and "Üdv a csapatban" in str(jel.dm[-1]["embed"].fields), "az elfogadott ticket gombot és megjegyzést kap privátban")
    ellenor(not [x for x in ELKULDOTT if x[0] == "edit" and x[1] == 11][-1][2]["view"], "a vezetői üzenetről lekerülnek a gombok")
    try:
        await staff.jelentkezes_dont(g, azon, admin, False); ellenor(False, "kétszeres döntés tiltott")
    except JelentkezesHiba:
        ellenor(True, "kétszeres döntés tiltott")
    csat = await staff.jelentkezes_ticket(g, azon, admin)
    r = await db.fetchone("SELECT * FROM jelentkezesek WHERE id=?", (azon,))
    ellenor(r["ticket_csatorna_id"] == csat.id, "ticket nyílt az elfogadottnak")
    tk = [x for x in ELKULDOTT if x[0] == "send" and x[1] == csat.id][-1][2]
    ellenor("Mert jó vagyok" in str(tk["embed"].fields) and "<@2>" in tk["content"] and "<@&20>" in tk["content"], "a ticketben benne vannak a jelentkezés válaszai és a ping")
    try:
        await staff.jelentkezes_ticket(g, azon, admin); ellenor(False, "második ticket tiltott")
    except JelentkezesHiba:
        ellenor(True, "második ticket tiltott")
    a2 = await staff.jelentkezes_bead(g, g.tagok[3], {"k": "v"}, "dm")
    e = await staff.jelentkezes_dont(g, a2, admin, False, "Most nem")
    ellenor(e["dm"] and "elutas" in g.tagok[3].dm[-1]["embed"].description and g.tagok[3].dm[-1].get("view") is None, "elutasítás: nincs ticket gomb")
    try:
        await staff.jelentkezes_ticket(g, a2, admin); ellenor(False, "elutasítottnak nem nyitható ticket")
    except JelentkezesHiba:
        ellenor(True, "elutasítottnak nem nyitható ticket")

    # ---------------------------------------------------------------- szankciók a weben
    rossz = g.tagok[4]
    ugy, _ = await szank.web_szankcio(g, "warn", 4, admin, "Szabályszegés")
    ellenor(ugy and rossz.dm, "figyelmeztetés kiadva, a tag értesítést kapott")
    ugy2, _ = await szank.web_szankcio(g, "timeout", 4, admin, "Spam", perc=30)
    ellenor(rossz.timeout_ == timedelta(minutes=30), "némítás végrehajtva")
    await szank.web_visszavon(g, ugy, admin, "Tévedés")
    ellenor((await db.fetchone("SELECT aktiv FROM szankciok WHERE id=?", (ugy,)))["aktiv"] == 0, "visszavonás")
    await szank.web_szankcio(g, "ban", 777, admin, "Kitiltás tag nélkül")
    ellenor(777 in g.tiltottak, "kitiltás szerveren kívüli azonosítóra")
    await szank.web_felold(g, 777, admin, "Megbocsátva")
    ellenor(777 not in g.tiltottak, "feloldás")
    for hibas in (("warn", 999, "Indok van"), ("warn", 4, "x"), ("warn", 1, "Admin magát")):
        try:
            await szank.web_szankcio(g, hibas[0], hibas[1], admin, hibas[2]); ellenor(False, f"hibás szankció elutasítva {hibas}")
        except SzankcioHiba:
            ellenor(True, f"hibás szankció elutasítva {hibas[1:]}")
    g.tagok[4].top_role = Rang(1, "magas", 99)
    try:
        await szank.web_szankcio(g, "kick", 4, admin, "Túl magas rang"); ellenor(False, "rangsor ellenőrzés")
    except SzankcioHiba:
        ellenor(True, "a botnál magasabb rangú tag nem büntethető")

    # ---------------------------------------------------------------- weboldalak
    d = Dashboard.__new__(Dashboard)
    d.bot, d.titok, d.biztonsagos = bot, b"teszt", False
    suti = d._alair({"u": 1, "n": "Admin", "c": "CSRF", "g": [1], "e": time.time() + 1000})

    class Kerés(dict):
        def __init__(s, query=None, adat=None, cookies=None):
            super().__init__(nonce="n"); s.query, s.cookies, s.match_info, s._adat = query or {}, {"dc_session": suti, **(cookies or {})}, {"gid": "1"}, adat
        async def post(s):
            class Adat(dict):
                def getall(self, k, alap=None): v = self.get(k); return [] if v is None else (v if isinstance(v, list) else [v])
            return Adat({"csrf": "CSRF", **(s._adat or {})})

    for utvonal, fv in (("nyitas", d.nyitas), ("jelentkezesek", d.jelentkezesek), ("szankciok", d.szankciok), ("ticketek", d.ticketek), ("attekintes", d.attekintes), ("staff", d.staff)):
        valasz = await fv(Kerés())
        ellenor(len(valasz.text) > 2000 and "alsosav" in valasz.text and "Hiba" not in valasz.text[:200], f"a(z) {utvonal} oldal kirajzolódik")
    jel_oldal = (await d.jelentkezesek(Kerés())).text
    ellenor("Ticket nyitása a jelentkezőnek" not in jel_oldal and "ticket megnyitva" in jel_oldal and "Mert jó vagyok" in jel_oldal, "a jelentkezések oldalon látszik az elfogadott és a ticketje")
    ny_oldal = (await d.nyitas(Kerés())).text
    ellenor("data-elo-forma" in ny_oldal and "nyitas-elo" in ny_oldal and "Automatikus nyitás és zárás" in ny_oldal and 'name="idopont"' in ny_oldal, "a nyitás oldalon van előnézet, időzítés és automatika")
    ellenor("szankcio/vegrehajt" in (await d.szankciok(Kerés())).text and "Kitiltás feloldása" in (await d.szankciok(Kerés())).text, "a szankciók oldalon weben is kiadható minden")
    ellenor("ticket/nyit" in (await d.ticketek(Kerés())).text, "a ticketek oldalon nyitható ticket taghoz")

    async def post(fv, **adat):
        try:
            await fv(Kerés(adat=adat))
        except Exception as ex:
            return ex
    ex = await post(d.nyitas_kuld, csatorna="10", ping="here", ping_rang="", szin="#ff0000", cim="Webes nyitás", szoveg="Hello", kod="", link="", idopont="", mentes_alap=["0", "1"], vissza="nyitas")
    ellenor("nyitas_kuldve" in ex.location, "webes nyitás kiküldve")
    ellenor(await db.get(1, "nyitas_cim") == "Webes nyitás", "a webes nyitás sablonként elmentve")
    ex = await post(d.nyitas_kuld, csatorna="99999", ping="", cim="x", szoveg="", vissza="nyitas")
    ellenor("nyitas_csatorna" in ex.location, "érvénytelen csatorna hibaüzenet")
    ex = await post(d.nyitas_kuld, csatorna="10", ping="", cim="Időzített", szoveg="", idopont=(datetime.now() + timedelta(hours=2)).strftime("%Y-%m-%dT%H:%M"), vissza="nyitas")
    ellenor("nyitas_idozitve" in ex.location, "webes időzítés")
    nyit_id = (await db.fetchone("SELECT id FROM nyitasok WHERE statusz='kuldve' ORDER BY id DESC LIMIT 1"))["id"]
    ex = await post(d.nyitas_muvelet, azon=str(nyit_id), muvelet="lezar", vissza="nyitas")
    ellenor("nyitas_lezarva" in ex.location, "webes zárás")
    a3 = await staff.jelentkezes_bead(g, g.tagok[3], {"k": "v"}, "dm")
    ex = await post(d.jelentkezes_dontes_web, azon=str(a3), muvelet="elfogad", megjegyzes="Web", vissza="jelentkezesek")
    flash = d._ellenoriz(ex.sutik["dc_flash"])
    ellenor(flash["t"] == "ok" and "elfogadva" in flash["m"], "webes elfogadás szöveges visszajelzéssel")
    ex = await post(d.jelentkezes_ticket_web, azon=str(a3), vissza="jelentkezesek")
    ellenor("jel_ticket" in ex.location, "webes ticket nyitás az elfogadottnak")
    g.tagok[4].top_role = Rang(104, "r", 1)
    ex = await post(d.szankcio_vegrehajt, cel="Rosszalkodo", tipus="warn", indok="Webes figyelmeztetés", perc="60", torles_nap="0", vissza="szankciok")
    ellenor("ügy #" in d._ellenoriz(ex.sutik["dc_flash"])["m"], "webes szankció")
    ex = await post(d.szankcio_vegrehajt, cel="1234", tipus="kick", indok="Nincs a szerveren", vissza="szankciok")
    ellenor(d._ellenoriz(ex.sutik["dc_flash"])["t"] == "hiba", "webes szankció hibaüzenet")
    kerés = Kerés(adat={"nyitas_auto": ["0", "1"], "nyitas_auto_napok": ["0", "4"], "nyitas_auto_nyit": "20:00", "nyitas_auto_zar": "99:99", "zaras_ping": "", "zaras_szin": "#112233", "vissza": "nyitas"})
    kerés.match_info["szekcio"] = "nyitas_auto"
    try:
        await d.mentes(kerés)
    except Exception as ex:
        pass
    ellenor(await db.get(1, "nyitas_auto") == "1" and await db.get(1, "nyitas_auto_napok") == "0,4" and await db.get(1, "nyitas_auto_nyit") == "20:00", "az automatikus nyitás beállításai mentődnek")
    ellenor(await db.get(1, "nyitas_auto_zar") is None and await db.get(1, "zaras_ping") == "", "érvénytelen idő nem mentődik, a ping nélküli zárás megmarad")
    print("\nMINDEN TESZT RENDBEN", "(valódi könyvtárakkal)" if VALODI else "(helyettesítőkkel)")
    os.remove(fajl)

asyncio.run(fo())
