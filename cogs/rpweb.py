"""A roleplay-specifikus dashboard oldalak: szerver nyitás, jelentkezések, szankciók és ticketek webes kezelése.

Az RPWeb a Dashboard cog őse (lásd cogs/dashboard.py): az itt lévő metódusok a Dashboard önmaga segédeit használják
(hozzaferes, _post, vissza, kirajzol, szekcio, _nev, opciok, link), ezért önállóan nem példányosíthatók.
"""
import asyncio
import json
import logging
import re
from datetime import datetime
from types import SimpleNamespace

import discord
from aiohttp import web

from cogs.nyitas import ALAP_SZIN, NyitasHiba, PING_OPCIOK, link_ervenyes, ping_ertek
from cogs.staff import JelentkezesHiba
from cogs.szankcio import SzankcioHiba
from util import IDOZONA, most, ts
from webkozos import datum, egeszseg_hex, m, mp_datum, relativ
from webui import Nyers, cimke, csempe, esc, kartya, mezo_html, oldalfej, opcio_html, tabla, ures, urlap

log = logging.getLogger("dcbot.rpweb")

NYITAS_STATUSZ = {"idozitett": ("időzítve", "sarga"), "kuldes": ("küldés…", "sarga"), "kuldve": ("nyitva", "zold"),
                  "lezarva": ("lezárva", ""), "hiba": ("hiba", "piros")}
JEL_STATUSZ = {"fuggoben": ("függőben", "sarga"), "elfogadva": ("elfogadva", "zold"), "elutasitva": ("elutasítva", "piros")}
SZANKCIO_MUVELETEK = [("warn", "⚠️ Figyelmeztetés"), ("timeout", "🔇 Némítás"), ("kick", "👢 Kirúgás"), ("ban", "🔨 Kitiltás")]


def _egesz(ertek, alap: int, kicsi: int, nagy: int) -> int:
    try:
        return max(kicsi, min(nagy, int(ertek)))
    except (TypeError, ValueError):
        return alap


class RPWeb:
    # ================================================================== közös segédek
    async def opciok_teljes(self, g) -> dict[str, list[tuple[str, str]]]:
        """A szokásos csatorna, kategória és rang listák, kiegészítve a ticket-típusokkal."""
        op = self.opciok(g)
        kategoriak = await self.bot.get_cog("Ticket").kategoriak(g.id, csak_aktiv=False)
        op["ticket_tipus"] = [(k["kulcs"], f"{k['emoji'] or ''} {k['nev']}".strip()) for k in kategoriak]
        return op

    @staticmethod
    def web_mod(s: dict) -> SimpleNamespace:
        """A belépett adminisztrátor mint moderátor (a szankciók, ticketek és naplók ezt várják)."""
        return SimpleNamespace(id=s["u"], mention=f"<@{s['u']}>", display_name=s["n"])

    async def cel_azonosit(self, g, szoveg: str) -> tuple[int | None, str | None]:
        """Egy tag azonosítója a megadott szövegből: azonosító, említés vagy név. Visszaad: (azonosító, hiba)."""
        szoveg = (szoveg or "").strip()
        if not szoveg:
            return None, "Add meg a tag azonosítóját, említését vagy nevét."
        if talalat := re.fullmatch(r"<@!?(\d{15,22})>|(\d{15,22})", szoveg):
            return int(talalat.group(1) or talalat.group(2)), None
        if (tag := getattr(g, "get_member_named", lambda _: None)(szoveg)) is not None:
            return tag.id, None
        try:
            tagok = await g.query_members(query=szoveg, limit=6)
        except Exception:
            tagok = []
        if len(tagok) == 1:
            return tagok[0].id, None
        if len(tagok) > 1:
            return None, "Több tag is megfelel: " + ", ".join(f"{t.display_name} ({t.id})" for t in tagok[:5]) + ". Add meg az azonosítót."
        return None, "Nincs ilyen nevű tag a szerveren. Add meg az azonosítóját."

    def hatterben(self, korutin) -> None:
        """Hosszabb műveletek (pl. ticket lezárása) a válasz után, a háttérben futnak."""
        if not hasattr(self, "_hatter"):
            self._hatter = set()

        def kesz(feladat):
            self._hatter.discard(feladat)
            if not feladat.cancelled() and feladat.exception():
                log.error("Hiba egy háttérműveletnél", exc_info=feladat.exception())

        feladat = asyncio.ensure_future(korutin)
        self._hatter.add(feladat)
        feladat.add_done_callback(kesz)

    def csatorna_link(self, g, csatorna_id: int | None) -> str:
        return f"https://discord.com/channels/{g.id}/{csatorna_id}" if csatorna_id else ""

    def _rang_nev(self, g, rang_id) -> str:
        rang = g.get_role(int(rang_id)) if rang_id and str(rang_id).isdigit() else None
        return rang.name if rang else "–"

    # ================================================================== szerver nyitás
    async def nyitas(self, request: web.Request):
        s, g = self.hozzaferes(request)
        db, cog = self.bot.db, self.bot.get_cog("Nyitas")
        op = await self.opciok_teljes(g)
        a = await cog.alapok(g.id)
        mezo = lambda mz, ertek: str(mezo_html(mz, ertek, op, g.name, "ny-"))
        mezok = "".join([
            mezo(m("csatorna", "Csatorna", "csatorna", seg="Ide kerül a nyitás üzenet."), a["csatorna"]),
            mezo(m("ping", "Ping", "valasztek", lehetosegek=PING_OPCIOK, alap="everyone",
                   seg="A ping az üzenet szövegében van, a beágyazáson kívül, így tényleg értesít."), a["ping"]),
            mezo(m("ping_rang", "Pingelt rang", "rang", seg="Csak az „Egy rang pingelése” választásnál számít. A rang legyen megemlíthető."), a["ping_rang"]),
            mezo(m("szin", "Az üzenet színe", "szin", alap=ALAP_SZIN), a["szin"]),
            mezo(m("cim", "Cím", "rovid", max_hossz=100, teljes=True), a["cim"]),
            mezo(m("szoveg", "Üzenet", "szoveg", sorok=4, teljes=True), a["szoveg"]),
            mezo(m("kod", "Szerverkód", "rovid", max_hossz=60, seg="Nem kötelező. Kódként jelenik meg a beágyazásban."), a["kod"]),
            mezo(m("link", "Csatlakozási link", "rovid", max_hossz=300, seg="Nem kötelező, https:// címmel kezdődjön. Gomb lesz belőle."), a["link"]),
            mezo(m("idopont", "Időzítés", "idopont", teljes=True,
                   seg="Üresen hagyva azonnal kimegy. Megadva a bot a (budapesti idő szerinti) időpontban küldi ki."), ""),
            mezo(m("mentes_alap", "Mentés alapértelmezett sablonként", "kapcsolo", alap=0, teljes=True,
                   seg="A következő nyitásnál és a gyors nyitásnál ez lesz az előre kitöltött érték."), "0"),
        ])
        elonezet = Nyers(
            '<div class="elo-doboz" id="nyitas-elo"><span class="ec-ping-cimke" hidden>Szöveges tartalom (a beágyazáson kívül):</span>'
            '<div class="ec-ping" hidden></div><div class="dc-embed"><div class="ec-cim"></div><div class="ec-szoveg"></div>'
            '<div class="ec-kod" hidden>🔑 Szerverkód: <b></b></div><div class="ec-gomb" hidden>🎮 Csatlakozás</div></div></div>')
        gombok = '<div class="sor" style="margin-top:14px"><button name="muvelet" value="kuld">🟢 Nyitás kiküldése / időzítése</button></div>'
        beado = urlap(f"/szerver/{g.id}/nyitas/kuld", s["c"], Nyers(f'<div class="mezok">{mezok}</div>{elonezet}{gombok}'),
                      vissza="nyitas", sav=False, extra=' data-elo-forma="nyitas-elo"')

        ping_nev = {"": "nincs ping", "everyone": "@everyone", "here": "@here", "rang": "@" + self._rang_nev(g, a["ping_rang"])}.get(a["ping"], "nincs ping")
        csatorna = g.get_channel(int(a["csatorna"])) if a["csatorna"].isdigit() else None
        gyors_info = (f'<p style="margin-top:0">Csatorna: <b>{esc("#" + csatorna.name) if csatorna else "nincs beállítva"}</b> • Ping: <b>{esc(ping_nev)}</b> • '
                      f'Cím: <b>{esc(a["cim"])}</b></p>')
        gyors = urlap(f"/szerver/{g.id}/nyitas/kuld", s["c"], Nyers(
            '<input type="hidden" name="muvelet" value="gyors"><button>⚡ Gyors nyitás a mentett sablonnal</button>'),
            vissza="nyitas", sav=False, megerosites="Kimegy a nyitás üzenet a mentett sablonnal, a pinggel együtt. Folytatod?")
        gyors_kartya = kartya("Gyors nyitás", Nyers(gyors_info + str(gyors)),
                              "Egy kattintással kiküldi a mentett sablont. A sablont lent, a mentés kapcsolóval lehet átírni.")

        sorok = await db.fetchall("SELECT * FROM nyitasok WHERE guild_id=? ORDER BY id DESC LIMIT 40", (g.id,))
        tabla_sorok = []
        for x in sorok:
            nev, szin = NYITAS_STATUSZ.get(x["statusz"], (x["statusz"], ""))
            ping = {"everyone": "@everyone", "here": "@here"}.get(x["ping"], "@" + self._rang_nev(g, x["ping"][5:]) if x["ping"].startswith("rang:") else "–")
            csat = g.get_channel(x["csatorna_id"])
            muvelet = ""
            if x["statusz"] == "kuldve":
                muvelet = str(urlap(f"/szerver/{g.id}/nyitas/muvelet", s["c"], Nyers(
                    f'<input type="hidden" name="azon" value="{x["id"]}"><input type="hidden" name="muvelet" value="lezar">'
                    '<button class="veszely kicsi">🔴 Lezárás</button>'), vissza="nyitas", sav=False,
                    megerosites="Lezárod a szervert? A nyitás üzenet „lezárult” állapotra változik."))
                if x["uzenet_id"]:
                    muvelet += f' <a href="{esc(self.link(g, x["csatorna_id"], x["uzenet_id"]))}" target="_blank" rel="noopener">↗</a>'
            elif x["statusz"] == "idozitett":
                muvelet = str(urlap(f"/szerver/{g.id}/nyitas/muvelet", s["c"], Nyers(
                    f'<input type="hidden" name="azon" value="{x["id"]}"><input type="hidden" name="muvelet" value="torol">'
                    '<button class="masodlagos kicsi">Törlés</button>'), vissza="nyitas", sav=False,
                    megerosites="Törlöd ezt az időzített nyitást?"))
            tabla_sorok.append([f"#{x['id']}", cimke(nev, szin), x["cim"], f"#{csat.name}" if csat else "–", ping,
                                mp_datum(x["idopont"]), x["kuldte_nev"] or "–", Nyers(muvelet)])
        elozmeny = kartya("Előzmények", tabla(["#", "Állapot", "Cím", "Csatorna", "Ping", "Időpont", "Küldte", ""], tabla_sorok, "nyitasok", False)
                          if tabla_sorok else ures("Még nem volt nyitás.", "🟢"), "A kiküldött és az időzített nyitások")
        return self.kirajzol(
            request, s, g, "nyitas", "Szerver nyitás", oldalfej("Szerver nyitás", "Nyitás üzenet beágyazással és külön ping-gel, azonnal vagy időzítve."),
            gyors_kartya, kartya("Új nyitás", beado, "Az előnézetben látod: a ping az üzenet szövegében, a beágyazáson kívül van, alatta jelenik meg a beágyazás."),
            await self.szekcio(s, g, "nyitas_auto", "nyitas"), elozmeny)

    async def nyitas_kuld(self, request: web.Request):
        s, g, adat = await self._post(request)
        cog = self.bot.get_cog("Nyitas")
        a = await cog.alapok(g.id)
        if adat.get("muvelet") == "gyors":
            ertek = dict(a, idopont="")
        else:
            ertek = {k: str(adat.get(k, "")).strip() for k in ("csatorna", "ping", "ping_rang", "szin", "cim", "szoveg", "kod", "link", "idopont")}
        if ertek["csatorna"] not in {str(c.id) for c in g.text_channels}:
            self.vissza(g, adat, hiba="nyitas_csatorna")
        ping = ertek["ping"] if ertek["ping"] in ("", "everyone", "here", "rang") else ""
        if ping == "rang" and ertek["ping_rang"] not in {str(r.id) for r in g.roles if not r.is_default()}:
            self.vissza(g, adat, hiba="nyitas_rang")
        szin = egeszseg_hex(ertek["szin"]) or ALAP_SZIN
        idopont = None
        if ertek["idopont"]:
            try:
                idopont = int(datetime.strptime(ertek["idopont"][:16], "%Y-%m-%dT%H:%M").replace(tzinfo=IDOZONA).timestamp())
            except ValueError:
                self.vissza(g, adat, hiba="nyitas_ido")
        if adat.get("muvelet") != "gyors" and "1" in adat.getall("mentes_alap", []):
            db = self.bot.db
            for kulcs, v in (("nyitas_csatorna", ertek["csatorna"]), ("nyitas_ping", ping), ("nyitas_ping_rang", ertek["ping_rang"]),
                             ("nyitas_szin", szin), ("nyitas_cim", ertek["cim"][:100]), ("nyitas_szoveg", ertek["szoveg"][:1800]),
                             ("nyitas_kod", ertek["kod"][:60]), ("nyitas_link", ertek["link"][:300])):
                await db.set(g.id, kulcs, v)
        try:
            _, azonnal = await cog.kozzetesz(
                g, csatorna_id=int(ertek["csatorna"]), cim=ertek["cim"], szoveg=ertek["szoveg"], szin=szin, ping=ping_ertek(ping, ertek["ping_rang"]),
                link=ertek["link"], kod=ertek["kod"], kuldte=s["u"], kuldte_nev=s["n"], idopont=idopont)
        except NyitasHiba as hiba:
            self.vissza(g, adat, szoveg=("hiba", str(hiba)))
        self.vissza(g, adat, ok="nyitas_kuldve" if azonnal else "nyitas_idozitve")

    async def nyitas_muvelet(self, request: web.Request):
        s, g, adat = await self._post(request)
        cog = self.bot.get_cog("Nyitas")
        azon = _egesz(adat.get("azon"), 0, 0, 2 ** 62)
        try:
            if adat.get("muvelet") == "lezar":
                await cog.lezar(g, azon)
                self.vissza(g, adat, ok="nyitas_lezarva")
            if adat.get("muvelet") == "torol":
                await cog.torol(g, azon)
                self.vissza(g, adat, ok="nyitas_torolve")
        except NyitasHiba as hiba:
            self.vissza(g, adat, szoveg=("hiba", str(hiba)))
        self.vissza(g, adat, hiba="ervenytelen")

    # ================================================================== jelentkezések
    def _jel_kartya(self, s, g, x, nyitva: bool = False) -> str:
        try:
            valaszok = json.loads(x["valaszok"])
        except ValueError:
            valaszok = {}
        nev, szin = JEL_STATUSZ.get(x["statusz"], (x["statusz"], ""))
        tag = g.get_member(x["user_id"])
        valasz_html = "".join(f'<div class="valasz"><b>{esc(k)}</b><div>{esc(v)}</div></div>' for k, v in valaszok.items()) or "<p class=\"halk\">Nincs válasz.</p>"
        forras = "privát üzenet" if x["forras"] == "dm" else "Discord űrlap"
        info = (f'<p class="halk" style="margin-top:0">Beküldve: {mp_datum(x["letrehozva"])} • forrás: {forras} • '
                f'{"a szerveren van" if tag else "nincs a szerveren"}'
                + (f' • döntött: {esc(self._nev(g, x["dontotte"]))} ({mp_datum(x["dontes_ido"])})' if x["dontotte"] else "") + "</p>")
        if x["megjegyzes"]:
            info += f'<div class="valasz"><b>Megjegyzés a jelentkezőnek</b><div>{esc(x["megjegyzes"])}</div></div>'
        muvelet = ""
        if x["statusz"] == "fuggoben":
            muvelet = str(urlap(f"/szerver/{g.id}/jelentkezes/dontes", s["c"], Nyers(
                f'<input type="hidden" name="azon" value="{x["id"]}">'
                '<div class="mezo"><label>Megjegyzés a jelentkezőnek (nem kötelező)</label>'
                '<textarea name="megjegyzes" rows="2" maxlength="500" placeholder="Ezt a jelentkező is megkapja privátban."></textarea></div>'
                '<div class="sor"><button name="muvelet" value="elfogad">✅ Elfogadás</button>'
                '<button class="veszely" name="muvelet" value="elutasit">❌ Elutasítás</button></div>'), vissza="jelentkezesek", sav=False))
        elif x["statusz"] == "elfogadva":
            csatorna = g.get_channel(x["ticket_csatorna_id"]) if x["ticket_csatorna_id"] else None
            if csatorna is not None:
                muvelet = (f'<div class="sor">{cimke("ticket megnyitva", "zold")}'
                           f'<a href="{esc(self.csatorna_link(g, csatorna.id))}" target="_blank" rel="noopener">#{esc(csatorna.name)} ↗</a></div>')
            else:
                muvelet = str(urlap(f"/szerver/{g.id}/jelentkezes/ticket", s["c"], Nyers(
                    f'<input type="hidden" name="azon" value="{x["id"]}"><button>🎫 Ticket nyitása a jelentkezőnek</button>'),
                    vissza="jelentkezesek", sav=False))
        jel = str(cimke(nev, szin))
        return (f'<details id="j{x["id"]}"{" open" if nyitva else ""}><summary><span>#{x["id"]}</span><span>{esc(self._nev(g, x["user_id"]))}</span>{jel}'
                f'<span class="halk">{relativ(max(0, ts() - x["letrehozva"]))}</span></summary>'
                f'<div class="belso">{info}{valasz_html}<div style="margin-top:14px">{muvelet}</div></div></details>')

    async def jelentkezesek(self, request: web.Request):
        s, g = self.hozzaferes(request)
        db = self.bot.db
        db_statusz = {x["statusz"]: x["db"] for x in await db.fetchall(
            "SELECT statusz, COUNT(*) AS db FROM jelentkezesek WHERE guild_id=? GROUP BY statusz", (g.id,))}
        ticketes = (await db.fetchone(
            "SELECT COUNT(*) AS db FROM jelentkezesek WHERE guild_id=? AND ticket_csatorna_id IS NOT NULL", (g.id,)))["db"]
        csempek = "".join(str(c) for c in [
            csempe(db_statusz.get("fuggoben", 0), "Elbírálásra vár", "⏳", "sarga"), csempe(db_statusz.get("elfogadva", 0), "Elfogadva", "✅", "zold"),
            csempe(db_statusz.get("elutasitva", 0), "Elutasítva", "❌", "piros"), csempe(ticketes, "Ticketet kapott", "🎫", "kek")])
        sorok = await db.fetchall("SELECT * FROM jelentkezesek WHERE guild_id=? ORDER BY id DESC LIMIT 200", (g.id,))
        nyitott = request.query.get("j", "")
        fuggo = [x for x in reversed(sorok) if x["statusz"] == "fuggoben"]
        elfogadott = [x for x in sorok if x["statusz"] == "elfogadva"][:15]
        fuggo_html = "".join(self._jel_kartya(s, g, x, nyitva=True) for x in fuggo) or str(ures("Nincs elbírálásra váró jelentkezés. 🎉", "✅"))
        elfogadott_html = "".join(self._jel_kartya(s, g, x, nyitva=nyitott == str(x["id"])) for x in elfogadott) or str(ures("Még nincs elfogadott jelentkezés.", "📝"))
        osszes = tabla(["#", "Jelentkező", "Állapot", "Beküldve", "Döntött", "Ticket"], [
            [f"#{x['id']}", self._nev(g, x["user_id"]), cimke(*JEL_STATUSZ.get(x["statusz"], (x["statusz"], ""))), mp_datum(x["letrehozva"]),
             self._nev(g, x["dontotte"]), "✅" if x["ticket_csatorna_id"] else "–"] for x in sorok], "jelentkezesek-lista")

        op = await self.opciok_teljes(g)
        panel = await db.get(g.id, "jelentkezes_panel")
        panel_info = "Még nincs kihelyezve."
        if panel:
            cs_id, uz_id = (int(x) for x in panel.split(":"))
            if csatorna := g.get_channel(cs_id):
                panel_info = Nyers(f'Kihelyezve: <b>#{esc(csatorna.name)}</b> • <a href="{esc(self.link(g, cs_id, uz_id))}" target="_blank" rel="noopener">megnyitás ↗</a>')
        panel_urlap = urlap(f"/szerver/{g.id}/jelentkezes/panel", s["c"], Nyers(
            f'<div class="sor"><select name="csatorna" style="max-width:280px">{opcio_html(op["csatorna"], set())}</select>'
            '<button>Jelentkezési panel kihelyezése</button></div>'), vissza="jelentkezesek", sav=False)
        panel_kartya = kartya("Jelentkezési panel", Nyers(f'<p style="margin-top:0">{panel_info}</p>{panel_urlap}'),
                              "A panelen a „Jelentkezem” gombra kattintva a bot privát üzenetben kérdezi végig a jelentkezőt. A parancs: /jelentkezes.")
        return self.kirajzol(
            request, s, g, "jelentkezesek", "Jelentkezések", oldalfej("Jelentkezések", "A jelentkezők privát üzenetben töltik ki, itt bírálhatók el."),
            f'<div class="racs r4">{csempek}</div>',
            kartya("Elbírálásra váró", Nyers(fuggo_html), "Nyisd le a jelentkezést, olvasd el a válaszokat, majd fogadd el vagy utasítsd el."),
            kartya("Elfogadottak", Nyers(elfogadott_html), "Az elfogadott jelentkezőnek innen nyitható ticket."),
            kartya("Összes jelentkezés", osszes, "A legutóbbi 200"), panel_kartya,
            await self.szekcio(s, g, "jelentkezes", "jelentkezesek"))

    async def jelentkezes_dontes_web(self, request: web.Request):
        s, g, adat = await self._post(request)
        muvelet = adat.get("muvelet")
        if muvelet not in ("elfogad", "elutasit"):
            self.vissza(g, adat, hiba="ervenytelen")
        elfogad = muvelet == "elfogad"
        azon = _egesz(adat.get("azon"), 0, 0, 2 ** 62)
        try:
            e = await self.bot.get_cog("Staff").jelentkezes_dont(g, azon, self.web_mod(s), elfogad, str(adat.get("megjegyzes", "")))
        except JelentkezesHiba as hiba:
            self.vissza(g, adat, szoveg=("hiba", str(hiba)))
        reszek = [f"A jelentkezés {'elfogadva' if elfogad else 'elutasítva'}."]
        reszek.append("A jelentkező privátban értesítést kapott." if e["dm"] else "A jelentkezőnek nem sikerült privátban értesítést küldeni.")
        if e["rang"]:
            reszek.append(f"Megkapta a(z) {e['rang']} rangot.")
        if e["rang_hiba"]:
            reszek.append("A rangot nem sikerült kiosztani (a bot rangja legyen magasabb).")
        if e["ticket"] is not None:
            reszek.append(f"Ticket megnyitva: #{e['ticket'].name}.")
        if e["ticket_hiba"]:
            reszek.append(f"A ticket nem nyílt meg: {e['ticket_hiba']}")
        self.vissza(g, adat, szoveg=("ok", " ".join(reszek)))

    async def jelentkezes_ticket_web(self, request: web.Request):
        s, g, adat = await self._post(request)
        azon = _egesz(adat.get("azon"), 0, 0, 2 ** 62)
        try:
            await self.bot.get_cog("Staff").jelentkezes_ticket(g, azon, self.web_mod(s))
        except JelentkezesHiba as hiba:
            self.vissza(g, adat, szoveg=("hiba", str(hiba)))
        self.vissza(g, adat, ok="jel_ticket")

    async def jelentkezes_panel_web(self, request: web.Request):
        s, g, adat = await self._post(request)
        csatorna = next((c for c in g.text_channels if str(c.id) == adat.get("csatorna", "")), None)
        if csatorna is None:
            self.vissza(g, adat, hiba="ervenytelen")
        try:
            await self.bot.get_cog("Staff").panel_kozzetesz(g, csatorna)
        except discord.HTTPException:
            self.vissza(g, adat, hiba="panel_hiba")
        self.vissza(g, adat, ok="jel_panel")

    # ================================================================== szankciók
    def szankcio_urlap_kartya(self, s, g) -> Nyers:
        """A szankciók naplója fölött lévő művelet-űrlapok (kiadás és kitiltás feloldása)."""
        tipus = "".join(f'<option value="{v}">{esc(n)}</option>' for v, n in SZANKCIO_MUVELETEK)
        kiadas = urlap(f"/szerver/{g.id}/szankcio/vegrehajt", s["c"], Nyers(
            '<div class="mezok"><div class="mezo teljes"><label>Tag</label>'
            '<input type="text" name="cel" required maxlength="100" placeholder="Azonosító, említés vagy név">'
            '<div class="seg">Kitiltásnál a szerveren kívüli felhasználó azonosítója is megadható.</div></div>'
            f'<div class="mezo"><label>Művelet</label><select name="tipus">{tipus}</select></div>'
            '<div class="mezo"><label>Némítás hossza (perc)</label><input type="number" name="perc" value="60" min="1" max="40320"></div>'
            '<div class="mezo"><label>Kitiltás: törölt üzenetek (nap)</label><input type="number" name="torles_nap" value="0" min="0" max="7"></div>'
            '<div class="mezo teljes"><label>Indok</label><textarea name="indok" required minlength="3" maxlength="500" rows="2" '
            'placeholder="Ezt a tag is megkapja privátban, és bekerül a naplóba."></textarea></div></div>'
            '<button>🔨 Végrehajtás</button>'), vissza="szankciok", sav=False,
            megerosites="Biztosan végrehajtod a szankciót? A tag értesítést kap, és a napló is rögzíti.")
        felold = urlap(f"/szerver/{g.id}/szankcio/felold", s["c"], Nyers(
            '<div class="sor"><input type="text" name="uid" required maxlength="25" placeholder="Kitiltott felhasználó azonosítója" style="max-width:280px">'
            '<input type="text" name="indok" required minlength="3" maxlength="500" placeholder="Indok" style="max-width:280px"><button class="masodlagos">Feloldás</button></div>'),
            vissza="szankciok", sav=False)
        return Nyers(str(kartya("Szankció kiadása", kiadas, "Ugyanaz, mint a Discord parancsok: ellenőrzi a rangsort, értesíti a tagot, és naplózza.")) +
                     str(kartya("Kitiltás feloldása", felold)))

    def szankcio_sor_gomb(self, s, g, x) -> Nyers:
        """Egy naplósor művelete: aktív figyelmeztetés/némítás visszavonása, kitiltás feloldása."""
        if not x["aktiv"]:
            return Nyers("")
        if x["tipus"] in ("warn", "timeout"):
            return urlap(f"/szerver/{g.id}/szankcio/visszavon", s["c"], Nyers(
                f'<input type="hidden" name="ugy" value="{x["id"]}"><div class="sor"><input type="text" name="indok" required minlength="3" maxlength="500" '
                'placeholder="Indok" style="max-width:170px"><button class="masodlagos kicsi">Visszavonás</button></div>'), vissza="szankciok", sav=False)
        if x["tipus"] == "ban":
            return urlap(f"/szerver/{g.id}/szankcio/felold", s["c"], Nyers(
                f'<input type="hidden" name="uid" value="{x["user_id"]}"><div class="sor"><input type="text" name="indok" required minlength="3" maxlength="500" '
                'placeholder="Indok" style="max-width:170px"><button class="masodlagos kicsi">Feloldás</button></div>'), vissza="szankciok", sav=False)
        return Nyers("")

    async def szankcio_vegrehajt(self, request: web.Request):
        s, g, adat = await self._post(request)
        cel_id, hiba = await self.cel_azonosit(g, str(adat.get("cel", "")))
        if hiba:
            self.vissza(g, adat, szoveg=("hiba", hiba))
        try:
            ugy, eszkalacio = await self.bot.get_cog("Szankcio").web_szankcio(
                g, str(adat.get("tipus", "")), cel_id, self.web_mod(s), str(adat.get("indok", "")),
                perc=_egesz(adat.get("perc"), 60, 1, 40320), torles_nap=_egesz(adat.get("torles_nap"), 0, 0, 7))
        except SzankcioHiba as hiba:
            self.vissza(g, adat, szoveg=("hiba", str(hiba)))
        self.vissza(g, adat, szoveg=("ok", f"A szankció végrehajtva (ügy #{ugy})." + (f" {eszkalacio}" if eszkalacio else "")))

    async def szankcio_visszavon(self, request: web.Request):
        s, g, adat = await self._post(request)
        try:
            await self.bot.get_cog("Szankcio").web_visszavon(g, _egesz(adat.get("ugy"), 0, 0, 2 ** 62), self.web_mod(s), str(adat.get("indok", "")))
        except SzankcioHiba as hiba:
            self.vissza(g, adat, szoveg=("hiba", str(hiba)))
        self.vissza(g, adat, ok="szankcio_visszavonva")

    async def szankcio_felold(self, request: web.Request):
        s, g, adat = await self._post(request)
        uid, hiba = await self.cel_azonosit(g, str(adat.get("uid", "")))
        if hiba:
            self.vissza(g, adat, szoveg=("hiba", "Adj meg érvényes felhasználó-azonosítót."))
        try:
            await self.bot.get_cog("Szankcio").web_felold(g, uid, self.web_mod(s), str(adat.get("indok", "")))
        except SzankcioHiba as hiba:
            self.vissza(g, adat, szoveg=("hiba", str(hiba)))
        self.vissza(g, adat, ok="szankcio_feloldva")

    # ================================================================== ticketek
    async def ticket_web_kartyak(self, s, g, kategoriak) -> Nyers:
        """A Ticketek oldal két extra kártyája: ticket nyitása taghoz, nyitott ticketek lezárása."""
        db = self.bot.db
        aktiv = [k for k in kategoriak if k["aktiv"]]
        opciok = "".join(f'<option value="{esc(k["kulcs"])}">{esc((k["emoji"] or "") + " " + k["nev"])}</option>' for k in aktiv)
        nyit = urlap(f"/szerver/{g.id}/ticket/nyit", s["c"], Nyers(
            '<div class="sor"><input type="text" name="cel" required maxlength="100" placeholder="Tag: azonosító, említés vagy név" style="max-width:320px">'
            f'<select name="tipus" style="max-width:260px" required>{opciok}</select><button>🎫 Ticket megnyitása</button></div>'),
            vissza="ticketek", sav=False) if aktiv else ures("Előbb hozz létre egy ticket-típust.", "🎫")
        nyit_kartya = kartya("Ticket nyitása taghoz", nyit, "A tag és a kezelők megkapják a nyitóüzenetet és a pinget. Az egyszerre nyitható ticketek száma ilyenkor nem korlátoz.")

        kat_nevek = {k["kulcs"]: k["nev"] for k in kategoriak}
        sorok = await db.fetchall("SELECT * FROM ticketek WHERE guild_id=? AND nyitva=1 ORDER BY id DESC LIMIT 50", (g.id,))
        tabla_sorok = []
        for x in sorok:
            csat = g.get_channel(x["csatorna_id"]) if x["csatorna_id"] else None
            link = Nyers(f'<a href="{esc(self.csatorna_link(g, x["csatorna_id"]))}" target="_blank" rel="noopener">#{esc(csat.name)} ↗</a>') if csat else "–"
            lezar = urlap(f"/szerver/{g.id}/ticket/lezar", s["c"], Nyers(
                f'<input type="hidden" name="azon" value="{x["id"]}"><div class="sor"><input type="text" name="indok" maxlength="300" placeholder="Lezárás oka" '
                'style="max-width:170px"><button class="veszely kicsi">Lezárás</button></div>'), vissza="ticketek", sav=False,
                megerosites="Lezárod a ticketet? A csatorna törlődik, az átirat a naplócsatornába kerül.")
            tabla_sorok.append([f"{x['id']:04d}", kat_nevek.get(x["kategoria"], x["kategoria"]), self._nev(g, x["user_id"]), self._nev(g, x["atvette"]),
                                datum(x["letrehozva"]), link, lezar])
        nyitott = kartya("Nyitott ticketek", tabla(["#", "Típus", "Nyitotta", "Átvette", "Megnyitva", "Csatorna", ""], tabla_sorok, "nyitott-ticketek", False)
                         if tabla_sorok else ures("Nincs nyitott ticket.", "✅"), "Innen le is zárhatók: az átirat a naplócsatornába kerül, a nyitó értékelést kap.")
        return Nyers(str(nyit_kartya) + str(nyitott))

    async def ticket_nyit_web(self, request: web.Request):
        s, g, adat = await self._post(request)
        ticket = self.bot.get_cog("Ticket")
        cel_id, hiba = await self.cel_azonosit(g, str(adat.get("cel", "")))
        if hiba:
            self.vissza(g, adat, szoveg=("hiba", hiba))
        tag = g.get_member(cel_id)
        if tag is None or getattr(tag, "bot", False):
            self.vissza(g, adat, szoveg=("hiba", "Ez a felhasználó nincs a szerveren (vagy bot)."))
        kat = await ticket.kategoria(g.id, str(adat.get("tipus", "")))
        if kat is None or not kat["aktiv"]:
            self.vissza(g, adat, hiba="nem_talalhato")
        try:
            await ticket.ticket_nyit(g, tag, kat, {}, kezdemenyezett=True, extra=[("Megnyitotta", f"<@{s['u']}>", True)])
        except Exception as hiba:
            from cogs.ticket import TicketHiba
            if isinstance(hiba, TicketHiba):
                self.vissza(g, adat, szoveg=("hiba", str(hiba)))
            raise
        self.vissza(g, adat, ok="ticket_megnyitva")

    async def ticket_lezar_web(self, request: web.Request):
        s, g, adat = await self._post(request)
        ticket = self.bot.get_cog("Ticket")
        azon = _egesz(adat.get("azon"), 0, 0, 2 ** 62)
        t = await self.bot.db.fetchone("SELECT * FROM ticketek WHERE id=? AND guild_id=?", (azon, g.id))
        if not t or not t["nyitva"]:
            self.vissza(g, adat, hiba="nem_talalhato")
        indok = str(adat.get("indok", "")).strip()[:300] or "Weben lezárva"
        csatorna = g.get_channel(t["csatorna_id"]) if t["csatorna_id"] else None
        if csatorna is None:  # a csatornát közben törölték: csak az adatbázisban zárjuk le
            await self.bot.db.execute("UPDATE ticketek SET nyitva=0, lezarva=? WHERE id=?", (most().isoformat(), t["id"]))
        else:
            self.hatterben(ticket.lezaras(g, csatorna, t, self.web_mod(s), indok))
        self.vissza(g, adat, ok="ticket_lezarva")
