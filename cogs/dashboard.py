"""Webes irányítópult (dashboard) Discord OAuth2 belépéssel.

Csak akkor indul el, ha a .env-ben meg van adva: CLIENT_ID, CLIENT_SECRET és DASHBOARD_URL.
Csak azok láthatják egy szerver oldalait, akik azon a szerveren adminisztrátorok (vagy tulajdonosok).
Az oldalak a bottal egy folyamatban futnak (aiohttp), ugyanazt az adatbázist használják.
A megjelenés a webui.py fájlban van.
"""
import base64
import hashlib
import hmac
import json
import logging
import os
import re
import secrets
import time
from datetime import datetime, timedelta
from urllib.parse import urlencode

import aiohttp
import discord
from aiohttp import web
from discord.ext import commands

from cogs.automod import ALAP, ALAP_DOMAINEK, ALAP_SZAVAK, RAID_KEZI, domain_tiszta
from cogs.shift import ALAP_MAX_ORA
from cogs.nyitas import ALAP_PING, ALAP_SZIN, ALAP_ZARAS_CIM, ALAP_ZARAS_PING, ALAP_ZARAS_SZIN, ALAP_ZARAS_SZOVEG, PING_OPCIOK
from cogs.rpweb import RPWeb
from cogs.staff import ALAP_ELFOGAD, ALAP_ELUTASIT, ALAP_KERDESEK
from cogs.szankcio import ESZK_BAN_DARAB, ESZK_TIMEOUT_DARAB, ESZK_TIMEOUT_PERC, WARN_LEJARAT_NAP
from cogs.szint import HANG_XP, XP_COOLDOWN, XP_MAX, XP_MIN, szint_xp, xp_szint
from cogs.ticket import ALAP_PANEL_CIM, ALAP_PANEL_LEIRAS, MAX_KATEGORIA, kulcs_keszit
from webkozos import datum, egeszseg_hex, ido_ervenyes, m, mp_datum, relativ
from util import IDOZONA, het_kezdete, ido_szoveg, iso, ts
from webui import (Nyers, bejelentkezes_oldal, cimke, csempe, ellenorzes, esc, fank_diagram, kartya, mezo_html,
                   ikon_html, oldal_vaz, oldalfej, opcio_html, oszlopdiagram, savos, tabla, ures, urlap)

log = logging.getLogger("dcbot.dashboard")
DISCORD_API = "https://discord.com/api/v10"
MUNKAMENET_ORA = 6
OLDALAK = {"", "alapok", "statisztika", "belepes", "ticketek", "szint", "kozosseg", "moderacio", "szankciok", "staff", "nyitas", "jelentkezesek"}

UZENETEK = {
    "mentve": "A beállítások mentve.", "kat_mentve": "A ticket-típus mentve, a panel frissült.", "kat_uj": "Az új ticket-típus létrejött.",
    "kat_torolve": "A ticket-típus törölve.", "panel": "A ticket panel kihelyezve.", "panel_frissitve": "A ticket panel frissítve.",
    "rang_mentve": "A szintrang mentve.", "rang_torolve": "A szintrang törölve.", "szorzo_mentve": "Az XP-szorzó mentve.",
    "szorzo_torolve": "Az XP-szorzó törölve.", "raid_be": "A raid mód bekapcsolva.", "raid_ki": "A raid mód kikapcsolva.",
    "nyitas_kuldve": "A nyitás üzenet kiment a pinggel együtt.", "nyitas_idozitve": "A nyitás be lett időzítve, a bot a megadott időpontban küldi ki.",
    "nyitas_lezarva": "A szerver lezárva: a zárás üzenet kiment, a nyitás üzenet átíródott.", "nyitas_torolve": "Az időzített nyitás törölve.",
    "jel_ticket": "A ticket megnyílt az elfogadott jelentkezőnek.", "jel_panel": "A jelentkezési panel kihelyezve.",
    "szankcio_visszavonva": "A szankció visszavonva.", "szankcio_feloldva": "A kitiltás feloldva.",
    "ticket_megnyitva": "A ticket megnyílt, a tag értesítést kapott.", "ticket_lezarva": "A ticket lezárása elindult, az átirat a naplóba kerül.",
}
HIBAK = {
    "ervenytelen": "Érvénytelen adat. Ellenőrizd a megadott értékeket.", "nev": "A ticket-típus nevét meg kell adni (legfeljebb 45 karakter).",
    "limit": f"Legfeljebb {MAX_KATEGORIA} ticket-típus lehet.", "panel_hiba": "A panelt nem sikerült kihelyezni: a botnak nincs joga írni abba a csatornába.",
    "nincs_panel": "Még nincs kihelyezett panel. Előbb helyezd ki egy csatornába.", "nem_talalhato": "A kért elem nem található.",
    "nyitas_csatorna": "Válassz érvényes csatornát a nyitás üzenethez.", "nyitas_rang": "A pingelendő rang nem található.",
    "nyitas_ido": "Az időzítés időpontja érvénytelen.",
}


# ---------------------------------------------------------------------- a beállítások leírása


SZEKCIOK = {
    "alapok": {"cim": "Alapbeállítások", "leiras": "A bot működéséhez szükséges alapvető csatornák és rangok.", "mezok": [
        m("naplo", "Naplócsatorna", "csatorna", seg="Ide kerülnek a szankciók, ticket átiratok, belépési és moderációs naplók."),
        m("staffrang", "Staff rang", "rang", seg="Ez a rang használhatja a moderációs parancsokat, és kezelheti a ticketeket."),
        m("vezetorang", "Vezetői rang", "rang", seg="Ők bírálják el a jelentkezéseket és az inaktivitási kérelmeket, és pontozhatják a staffot."),
        m("vezetoi_csatorna", "Vezetői csatorna", "csatorna", seg="Ide érkeznek a kérelmek, jelentkezések és a havi staff riport."),
    ]},
    "belepes": {"cim": "Belépési üzenet", "leiras": "Mit lásson az új tag, és milyen rangot kapjon.", "mezok": [
        m("belepes_csatorna", "Üdvözlő csatorna", "csatorna"),
        m("belepes_rang", "Alaprang az új tagoknak", "rang", seg="A bot rangja legyen magasabb ennél a rangnál."),
        m("belepes_uzenet", "Üdvözlő üzenet", "szoveg", teljes=True, elonezet=True, sorok=4,
          seg="Használható: {tag} (említés), {szerver} (szerver neve), {szam} (hányadik tag)."),
    ]},
    "ticket": {"cim": "Ticket beállítások", "leiras": "A ticket rendszer általános működése és a panel megjelenése.", "mezok": [
        m("ticket_kategoria", "Alapértelmezett csatornakategória", "kategoria", seg="Ide kerülnek az új ticketek, ha a ticket-típusnál nincs másik megadva."),
        m("ticket_max_nyitott", "Egyszerre nyitható ticketek száma tagonként", "szam", min=1, max=10, alap=1),
        m("ticket_panel_cim", "A panel címe", "rovid", max_hossz=100, alap=ALAP_PANEL_CIM),
        m("ticket_panel_szin", "A panel színe", "szin", alap="#7c5cff"),
        m("ticket_panel_leiras", "A panel szövege", "szoveg", teljes=True, sorok=3, alap=ALAP_PANEL_LEIRAS,
          seg="Alatta a bot automatikusan felsorolja az elérhető ticket-típusokat."),
    ]},
    "automod": {"cim": "Erős moderáció", "leiras": "Automatikus szűrők. A staff tagok és a kivételcsatornák mentesülnek.", "mezok": [
        m("automod_spam_limit", "Spamszűrő: üzenetek száma", "szam", min=0, max=50, alap=ALAP["spam_limit"], seg="Ennyi üzenet a megadott időn belül spam. 0 = kikapcsolva."),
        m("automod_spam_masodperc", "Spamszűrő: időablak (mp)", "szam", min=1, max=60, alap=ALAP["spam_masodperc"]),
        m("automod_ping_limit", "Tömeges említés határa", "szam", min=0, max=50, alap=ALAP["ping_limit"], seg="Ennyi említés egy üzenetben figyelmeztetést von maga után. 0 = ki."),
        m("automod_uj_fiok_napok", "Új fiók szűrő (napok)", "szam", min=0, max=365, alap=ALAP["uj_fiok_napok"], seg="Az ennél fiatalabb Discord-fiókot a bot kirúgja. 0 = ki."),
        m("automod_raid_limit", "Raid-érzékelés: belépések száma", "szam", min=0, max=100, alap=ALAP["raid_limit"], seg="0 = kikapcsolva."),
        m("automod_raid_masodperc", "Raid-érzékelés: időablak (mp)", "szam", min=5, max=300, alap=ALAP["raid_masodperc"]),
        m("automod_link_szuro", "Linkszűrő", "kapcsolo", alap=1, seg="A listán nem szereplő oldalak linkjeit törli."),
        m("automod_meghivo_szuro", "Discord-meghívók tiltása", "kapcsolo", alap=1),
        m("automod_szitok_szuro", "Szitokszűrő", "kapcsolo", alap=1),
        m("automod_szavak", "Tiltott szavak (soronként egy)", "lista", ures_ment=True, alap=ALAP_SZAVAK, kisbetu=True, max_sor=500, max_hossz=60,
          sorok=9, seg="A = jellel kezdődő szó (pl. =fasz) csak önálló szóként számít találatnak."),
        m("automod_domainek", "Engedélyezett link-oldalak (soronként egy)", "lista", ures_ment=True, alap=ALAP_DOMAINEK, kisbetu=True,
          max_sor=300, max_hossz=100, sorok=9, seg="Az aldomainek is engedélyezettek (pl. a tenor.com a media.tenor.com-ot is)."),
        m("automod_kivetel", "Kivételcsatornák", "csatornak", teljes=True, seg="Ezekben a csatornákban nem működnek a szűrők."),
    ]},
    "szankcio": {"cim": "Szankció-eszkaláció", "leiras": "Mikor lépjen közbe automatikusan a bot a figyelmeztetések számától függően.", "mezok": [
        m("szankcio_warn_nap", "Figyelmeztetések lejárata (nap)", "szam", min=1, max=365, alap=WARN_LEJARAT_NAP, seg="Ennyi nap után nem számít bele az eszkalációba."),
        m("szankcio_timeout_db", "Automatikus némítás ennyi figyelmeztetésnél", "szam", min=0, max=50, alap=ESZK_TIMEOUT_DARAB, seg="0 = kikapcsolva."),
        m("szankcio_timeout_perc", "A némítás hossza (perc)", "szam", min=1, max=40320, alap=ESZK_TIMEOUT_PERC),
        m("szankcio_ban_db", "Automatikus kitiltás ennyi figyelmeztetésnél", "szam", min=0, max=50, alap=ESZK_BAN_DARAB, seg="0 = kikapcsolva."),
    ]},
    "szint": {"cim": "Szint rendszer", "leiras": "Mennyi XP jár, és hol.", "mezok": [
        m("szint_csatorna", "Szintlépés-értesítések csatornája", "csatorna", seg="Üresen hagyva abba a csatornába érkezik, ahol a tag írt."),
        m("szint_xp_min", "XP üzenetenként (legalább)", "szam", min=0, max=500, alap=XP_MIN),
        m("szint_xp_max", "XP üzenetenként (legfeljebb)", "szam", min=0, max=500, alap=XP_MAX),
        m("szint_cooldown", "Várakozás két XP-t érő üzenet között (mp)", "szam", min=0, max=3600, alap=XP_COOLDOWN),
        m("szint_hang_xp", "XP percenként hangcsatornában", "szam", min=0, max=500, alap=HANG_XP, seg="0 = a hangcsatornás XP kikapcsolva."),
        m("szint_kivetel", "Csatornák, ahol nem jár XP", "csatornak", teljes=True),
    ]},
    "staff": {"cim": "Staff beállítások", "leiras": "Jelentkezés, minimális aktivitás, riportok.", "mezok": [
        m("riport_csatorna", "Heti és havi statisztikai riport csatornája", "csatorna"),
        m("staff_minimum_ora", "Heti minimális szolgálati idő (óra)", "szam", min=0, max=100, alap=0, seg="0 = kikapcsolva. Aki nem éri el, arról a bot hétfőn jelez a vezetőknek."),
    ]},
    "jelentkezes": {"cim": "Jelentkezés beállításai", "leiras": "A privát üzenetes jelentkezés, az elfogadás és a ticket.", "mezok": [
        m("jelentkezes_nyitva", "Jelentkezés nyitva", "kapcsolo", alap=1, seg="Kikapcsolva a Jelentkezem gomb és a /jelentkezes nem indít új jelentkezést."),
        m("jelentkezes_csatorna", "A jelentkezések csatornája", "csatorna", seg="Ide érkezik a beküldött jelentkezés a vezetői pinggel. Üresen hagyva a vezetői csatornába."),
        m("jelentkezes_rang", "Rang elfogadáskor", "rang", seg="Nem kötelező. Az elfogadott jelentkező automatikusan megkapja."),
        m("jelentkezes_auto_ticket", "Ticket automatikus nyitása elfogadáskor", "kapcsolo", alap=0, teljes=True,
          seg="Kikapcsolva az elfogadott jelentkező privátban kap egy „Ticket nyitása” gombot, weben pedig a vezető nyithat neki ticketet."),
        m("jelentkezes_ticket_tipus", "Az elfogadottak ticket-típusa", "ticket_tipus", seg="Üresen hagyva a „Staff jelentkezés” típus, ha nincs olyan, az első elérhető."),
        m("jelentkezes_kerdesek", "Jelentkezési kérdések (soronként egy, legfeljebb 5)", "lista", teljes=True, alap=ALAP_KERDESEK, max_sor=5, max_hossz=45, sorok=5,
          seg="Ezeket kérdezi végig a bot privát üzenetben. Üresen hagyva az alapértelmezettek érvényesek."),
        m("jelentkezes_elfogad_uzenet", "Elfogadó üzenet (privátban)", "szoveg", teljes=True, sorok=3, alap=ALAP_ELFOGAD, seg="Használható: {tag}, {szerver}."),
        m("jelentkezes_elutasit_uzenet", "Elutasító üzenet (privátban)", "szoveg", teljes=True, sorok=3, alap=ALAP_ELUTASIT, seg="Használható: {tag}, {szerver}."),
    ]},
    "nyitas_auto": {"cim": "Automatikus nyitás és zárás", "leiras": "Napi idő szerint magától nyit és zár a bot. A zárás üzenet beágyazott, a ping külön, mellette.", "mezok": [
        m("nyitas_auto", "Automatikus nyitás és zárás", "kapcsolo", alap=0, teljes=True,
          seg="Nyitáskor a fenti mentett sablon megy ki. Csak akkor nyit, ha nincs már nyitva szerver."),
        m("nyitas_auto_napok", "Melyik napokon nyisson", "napok", teljes=True),
        m("nyitas_auto_nyit", "Nyitás ideje (budapesti idő)", "ido", seg="Üresen hagyva nem nyit automatikusan."),
        m("nyitas_auto_zar", "Zárás ideje (budapesti idő)", "ido", seg="Üresen hagyva nem zár automatikusan. Az éjfél utáni zárás is működik (pl. nyitás 20:00, zárás 02:00)."),
        m("zaras_csatorna", "A zárás üzenet csatornája", "csatorna", seg="Üresen hagyva ugyanoda megy, ahová a nyitás."),
        m("zaras_ping", "Zárás ping", "valasztek", lehetosegek=PING_OPCIOK, alap=ALAP_ZARAS_PING, ures_ment=True,
          seg="A ping az üzenet szövegében van, a beágyazáson kívül, így tényleg értesít."),
        m("zaras_ping_rang", "Pingelt rang zárásnál", "rang", seg="Csak az „Egy rang pingelése” választásnál számít."),
        m("zaras_szin", "A zárás üzenet színe", "szin", alap=ALAP_ZARAS_SZIN),
        m("zaras_cim", "Zárás cím", "rovid", max_hossz=100, teljes=True, alap=ALAP_ZARAS_CIM),
        m("zaras_szoveg", "Zárás üzenet", "szoveg", teljes=True, sorok=3, alap=ALAP_ZARAS_SZOVEG),
    ]},
    "szolgalat": {"cim": "Szolgálat és inaktivitás", "leiras": "A szolgálati rendszer és az inaktivitási kérelmek.", "mezok": [
        m("shift_rang", "Szolgálati rang", "rang", seg="A szolgálatban lévők megkapják."),
        m("shift_max_ora", "Elfelejtett szolgálat automatikus lezárása (óra)", "szam", min=1, max=24, alap=ALAP_MAX_ORA),
        m("inaktiv_rang", "Inaktív rang", "rang", seg="Az elfogadott inaktivitás idejére kapják meg."),
    ]},
    "javaslat": {"cim": "Javaslatok", "leiras": "", "mezok": [
        m("javaslat_csatorna", "Javaslatok csatornája", "csatorna", seg="Ide kerülnek a /javaslat uj paranccsal beküldött javaslatok."),
    ]},
}




def emoji_ervenyes(szoveg: str) -> bool:
    if not szoveg:
        return True
    if re.fullmatch(r"<a?:\w{2,32}:\d{15,22}>", szoveg):
        return True
    return len(szoveg) <= 12 and not szoveg.isascii() and not any(c.isalnum() for c in szoveg)


def egyenlo(a, b) -> bool:
    """Időzítés-biztos összehasonlítás (nem ASCII bemenetnél sem hibázik)."""
    return hmac.compare_digest(str(a).encode(), str(b).encode())








def epoch(iso_szoveg: str) -> float:
    return datetime.fromisoformat(iso_szoveg).timestamp()


def napok_listaja(db: int) -> list:
    ma = datetime.now(IDOZONA).date()
    return [ma - timedelta(days=n) for n in range(db - 1, -1, -1)]


SZANKCIO_CIMEK = {"warn": "Figyelmeztetés", "timeout": "Némítás", "kick": "Kirúgás", "ban": "Kitiltás", "unban": "Feloldás"}
SZANKCIO_SZINEK = {"warn": "sarga", "timeout": "sarga", "kick": "sarga", "ban": "piros", "unban": "zold"}


class Dashboard(RPWeb, commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.runner: web.AppRunner | None = None

    # ================================================================== indítás
    async def cog_load(self):
        self.client_id = os.getenv("CLIENT_ID")
        self.client_secret = os.getenv("CLIENT_SECRET")
        self.url = (os.getenv("DASHBOARD_URL") or "").rstrip("/")
        if not (self.client_id and self.client_secret and self.url):
            log.info("A dashboard ki van kapcsolva (hiányzik a CLIENT_ID, CLIENT_SECRET vagy DASHBOARD_URL).")
            return
        titok = os.getenv("SESSION_SECRET")
        if not titok:
            log.warning("Nincs SESSION_SECRET megadva: a bejelentkezések minden újraindításkor érvénytelenné válnak.")
        self.titok = (titok or secrets.token_hex(32)).encode()
        self.biztonsagos = self.url.startswith("https://")

        app = web.Application(middlewares=[self._kozbeeso])
        app.on_response_prepare.append(self._fejlecek)
        g = "/szerver/{gid}"
        app.add_routes([
            web.get("/", self.fooldal), web.get("/login", self.login), web.get("/callback", self.callback),
            web.post("/kilepes", self.kilepes),
            web.get(g, self.attekintes), web.get(g + "/", self.attekintes), web.get(g + "/alapok", self.alapok), web.get(g + "/statisztika", self.statisztika),
            web.get(g + "/belepes", self.belepes), web.get(g + "/ticketek", self.ticketek), web.get(g + "/szint", self.szint),
            web.get(g + "/kozosseg", self.kozosseg), web.get(g + "/moderacio", self.moderacio),
            web.get(g + "/szankciok", self.szankciok), web.get(g + "/staff", self.staff),
            web.post(g + "/mentes/{szekcio}", self.mentes), web.post(g + "/ticket/kategoria", self.ticket_kategoria),
            web.post(g + "/ticket/panel", self.ticket_panel), web.post(g + "/szint/rang", self.szint_rang),
            web.post(g + "/szint/szorzo", self.szint_szorzo), web.post(g + "/raid", self.raid),
            web.get(g + "/nyitas", self.nyitas), web.post(g + "/nyitas/kuld", self.nyitas_kuld), web.post(g + "/nyitas/muvelet", self.nyitas_muvelet),
            web.get(g + "/jelentkezesek", self.jelentkezesek), web.post(g + "/jelentkezes/dontes", self.jelentkezes_dontes_web),
            web.post(g + "/jelentkezes/ticket", self.jelentkezes_ticket_web), web.post(g + "/jelentkezes/panel", self.jelentkezes_panel_web),
            web.post(g + "/szankcio/vegrehajt", self.szankcio_vegrehajt), web.post(g + "/szankcio/visszavon", self.szankcio_visszavon),
            web.post(g + "/szankcio/felold", self.szankcio_felold),
            web.post(g + "/ticket/nyit", self.ticket_nyit_web), web.post(g + "/ticket/lezar", self.ticket_lezar_web),
        ])
        self.runner = web.AppRunner(app)
        await self.runner.setup()
       host = os.getenv("DASHBOARD_HOST", "0.0.0.0")
# Itt először a Render PORT változóját keressük, és CSAK ha az nincs, akkor esünk vissza a 8080-ra:
        port_str = os.getenv("PORT") or os.getenv("DASHBOARD_PORT") or "8080"
        port = int(port_str)
        await web.TCPSite(self.runner, host, port).start()
        log.info("A dashboard elindult: %s (helyi cím: %s:%s)", self.url, host, port)

    async def cog_unload(self):
        if self.runner:
            await self.runner.cleanup()

    @web.middleware
    async def _kozbeeso(self, request: web.Request, handler):
        request["nonce"] = secrets.token_urlsafe(12)
        try:
            return await handler(request)
        except web.HTTPException:
            raise
        except Exception:
            log.exception("Hiba a dashboard egyik oldalán: %s", request.path)
            nonce = request["nonce"]
            return web.Response(
                text=bejelentkezes_oldal("Hiba történt", "Az oldal betöltése közben váratlan hiba lépett fel. Részletek a bot naplójában.", "Vissza a főoldalra", "/", nonce),
                content_type="text/html", charset="utf-8", status=500,
            )

    @staticmethod
    async def _fejlecek(request, valasz):
        valasz.headers["X-Frame-Options"] = "DENY"
        valasz.headers["X-Content-Type-Options"] = "nosniff"
        valasz.headers["Referrer-Policy"] = "same-origin"
        valasz.headers["Content-Security-Policy"] = (
            f"default-src 'none'; style-src 'unsafe-inline'; script-src 'nonce-{request.get('nonce', '')}'; "
            "img-src 'self' data: https://cdn.discordapp.com; form-action 'self'; base-uri 'none'; frame-ancestors 'none'"
        )

    # ================================================================== munkamenet (aláírt süti)
    def _alair(self, adat: dict) -> str:
        nyers = base64.urlsafe_b64encode(json.dumps(adat, separators=(",", ":")).encode()).decode().rstrip("=")
        return f"{nyers}.{hmac.new(self.titok, nyers.encode(), hashlib.sha256).hexdigest()}"

    def _ellenoriz(self, suti: str | None) -> dict | None:
        try:
            nyers, alairas = (suti or "").rsplit(".", 1)
            elvart = hmac.new(self.titok, nyers.encode(), hashlib.sha256).hexdigest()
            if not hmac.compare_digest(alairas, elvart):
                return None
            adat = json.loads(base64.urlsafe_b64decode(nyers + "=" * (-len(nyers) % 4)))
            return adat if adat.get("e", 0) > time.time() else None
        except (ValueError, TypeError):
            return None

    def munkamenet(self, request: web.Request) -> dict | None:
        return self._ellenoriz(request.cookies.get("dc_session"))

    def _suti(self, valasz: web.StreamResponse, nev: str, ertek: str, mp: int):
        valasz.set_cookie(nev, ertek, max_age=mp, httponly=True, samesite="Lax", secure=self.biztonsagos, path="/")

    def hozzaferes(self, request: web.Request) -> tuple[dict, discord.Guild]:
        s = self.munkamenet(request)
        if not s:
            raise web.HTTPFound("/")
        try:
            gid = int(request.match_info["gid"])
        except ValueError:
            raise web.HTTPNotFound()
        guild = self.bot.get_guild(gid)
        if gid not in s["g"] or guild is None:
            raise web.HTTPForbidden(text="Ehhez a szerverhez nincs hozzáférésed.")
        return s, guild

    async def _post(self, request: web.Request):
        s, g = self.hozzaferes(request)
        adat = await request.post()
        if not egyenlo(adat.get("csrf", ""), s["c"]):
            raise web.HTTPForbidden(text="Érvénytelen kérés (lejárt az oldal). Frissítsd az oldalt, és próbáld újra.")
        return s, g, adat

    def vissza(self, g, adat, ok: str | None = None, hiba: str | None = None, szoveg: tuple[str, str] | None = None):
        """Átirányítás az oldalra. Az üzenet lehet előre megírt kód (ok / hiba) vagy szabad szöveg (szoveg=(\"ok\"|\"hiba\", szöveg))."""
        oldal = adat.get("vissza", "")
        oldal = oldal if oldal in OLDALAK else ""
        cim = f"/szerver/{g.id}" + (f"/{oldal}" if oldal else "")
        if szoveg is None:
            cim += f"?ok={ok}" if ok else f"?hiba={hiba}"
        valasz = web.HTTPFound(cim)
        if szoveg is not None:
            tipus, uzenet = szoveg
            self._suti(valasz, "dc_flash", self._alair({"t": "hiba" if tipus == "hiba" else "ok", "m": uzenet[:700], "e": time.time() + 120}), 120)
        raise valasz

    def kirajzol(self, request: web.Request, s: dict, g, aktiv: str, cim: str, *reszek) -> web.Response:
        kod, hiba = request.query.get("ok"), request.query.get("hiba")
        uzenet = ("ok", UZENETEK[kod]) if kod in UZENETEK else ("hiba", HIBAK[hiba]) if hiba in HIBAK else None
        suti = request.cookies.get("dc_flash")
        if uzenet is None and suti and (flash := self._ellenoriz(suti)):
            uzenet = (flash.get("t", "ok"), str(flash.get("m", "")))
        szoveg = oldal_vaz(cim, "".join(str(r) for r in reszek), nonce=request["nonce"], felhasznalo=s, guild=g, aktiv=aktiv, uzenet=uzenet)
        valasz = web.Response(text=szoveg, content_type="text/html", charset="utf-8")
        if suti:
            valasz.del_cookie("dc_flash", path="/")
        return valasz

    def egyszeru(self, request, cim, szoveg, gomb, link) -> web.Response:
        return web.Response(text=bejelentkezes_oldal(cim, szoveg, gomb, link, request["nonce"]), content_type="text/html", charset="utf-8")

    # ================================================================== belépés
    async def fooldal(self, request: web.Request):
        s = self.munkamenet(request)
        if not s:
            return self.egyszeru(request, "Irányítópult", "A bot beállításait és statisztikáit a Discord-fiókoddal jelentkezve érheted el. "
                                 "Csak azokat a szervereket látod, ahol adminisztrátor vagy.", "Belépés Discorddal", "/login")
        kartyak = []
        for gid in s["g"]:
            if guild := self.bot.get_guild(gid):
                kartyak.append(f'<a href="/szerver/{gid}">{ikon_html(guild)}<span><b>{esc(guild.name)}</b><br>'
                               f'<span class="halk">{guild.member_count} tag</span></span><span style="margin-left:auto">→</span></a>')
        tartalom = (oldalfej("Szervereid", "Válaszd ki, melyiket szeretnéd kezelni.")
                    + (kartya("", f'<div class="sz-lista">{"".join(kartyak)}</div>') if kartyak else
                       kartya("", ures("Nincs olyan szerver, ahol adminisztrátor vagy, és a bot is jelen van.", "🔍"))))
        return self.kirajzol(request, s, None, "", "Szerverek", tartalom)

    async def login(self, request: web.Request):
        allapot = secrets.token_urlsafe(16)
        parameterek = urlencode({
            "client_id": self.client_id, "redirect_uri": f"{self.url}/callback", "response_type": "code",
            "scope": "identify guilds", "state": allapot, "prompt": "none",
        })
        valasz = web.HTTPFound(f"https://discord.com/oauth2/authorize?{parameterek}")
        self._suti(valasz, "dc_state", allapot, 600)
        raise valasz

    async def callback(self, request: web.Request):
        kod, allapot = request.query.get("code"), request.query.get("state")
        if not kod or not allapot or not egyenlo(allapot, request.cookies.get("dc_state", "")):
            return self.egyszeru(request, "Sikertelen belépés", "Az azonosítás nem sikerült.", "Próbáld újra", "/login")
        try:
            async with aiohttp.ClientSession() as munkamenet:
                async with munkamenet.post(f"{DISCORD_API}/oauth2/token", data={
                    "client_id": self.client_id, "client_secret": self.client_secret, "grant_type": "authorization_code",
                    "code": kod, "redirect_uri": f"{self.url}/callback",
                }) as r:
                    if r.status != 200:
                        raise ValueError("token")
                    fejlec = {"Authorization": f"Bearer {(await r.json())['access_token']}"}
                async with munkamenet.get(f"{DISCORD_API}/users/@me", headers=fejlec) as r:
                    felhasznalo = await r.json()
                async with munkamenet.get(f"{DISCORD_API}/users/@me/guilds", headers=fejlec) as r:
                    szerverek = await r.json()
        except (aiohttp.ClientError, ValueError, KeyError):
            return self.egyszeru(request, "Sikertelen belépés", "A Discord nem válaszolt megfelelően.", "Próbáld újra", "/login")
        engedelyezett = [
            int(g["id"]) for g in szerverek
            if (g.get("owner") or int(g.get("permissions", 0)) & 0x8) and self.bot.get_guild(int(g["id"]))
        ]
        sutik = self._alair({
            "u": int(felhasznalo["id"]), "n": felhasznalo.get("global_name") or felhasznalo["username"],
            "g": engedelyezett, "c": secrets.token_urlsafe(16), "e": time.time() + MUNKAMENET_ORA * 3600,
        })
        valasz = web.HTTPFound("/")
        self._suti(valasz, "dc_session", sutik, MUNKAMENET_ORA * 3600)
        valasz.del_cookie("dc_state")
        raise valasz

    async def kilepes(self, request: web.Request):
        s = self.munkamenet(request)
        adat = await request.post()
        if s and egyenlo(adat.get("csrf", ""), s["c"]):
            valasz = web.HTTPFound("/")
            valasz.del_cookie("dc_session")
            raise valasz
        raise web.HTTPForbidden(text="Érvénytelen kérés.")

    # ================================================================== segédek
    def _nev(self, g, uid: int | None) -> str:
        if not uid:
            return "–"
        tag = g.get_member(uid)
        return f"{tag.display_name} ({uid})" if tag else str(uid)

    @staticmethod
    def opciok(g) -> dict[str, list[tuple[str, str]]]:
        return {
            "csatorna": [(str(c.id), f"#{c.name}") for c in g.text_channels],
            "kategoria": [(str(c.id), c.name) for c in g.categories],
            "rang": [(str(r.id), r.name) for r in reversed(g.roles) if not r.is_default()],
        }

    async def szekcio(self, s, g, kulcs: str, vissza: str, cim: str | None = None, leiras: str | None = None) -> Nyers:
        """Egy beállítási szakasz kártyája mentés-gombbal."""
        sz, op = SZEKCIOK[kulcs], await self.opciok_teljes(g)
        mezok = "".join([str(mezo_html(mz, await self.bot.db.get(g.id, mz["kulcs"]), op, g.name)) for mz in sz["mezok"]])
        urlap_html = urlap(f"/szerver/{g.id}/mentes/{kulcs}", s["c"], Nyers(f'<div class="mezok">{mezok}</div>'), vissza=vissza)
        return kartya(cim or sz["cim"], urlap_html, leiras if leiras is not None else sz["leiras"])

    async def szamol(self, sql: str, *arg) -> int:
        return (await self.bot.db.fetchone(sql, arg))["db"]

    def link(self, g, csatorna_id, uzenet_id) -> str:
        return f"https://discord.com/channels/{g.id}/{csatorna_id}/{uzenet_id}" if csatorna_id and uzenet_id else ""

    # ================================================================== beállítások mentése
    async def mentes(self, request: web.Request):
        s, g, adat = await self._post(request)
        kulcs = request.match_info["szekcio"]
        if kulcs not in SZEKCIOK:
            raise web.HTTPNotFound()
        db, op = self.bot.db, await self.opciok_teljes(g)
        for mz in SZEKCIOK[kulcs]["mezok"]:
            k, t = mz["kulcs"], mz["tipus"]
            if t == "valasztek":
                ertek = adat.get(k, "")
                ertek = ertek if ertek in {v for v, _ in mz["lehetosegek"]} else ""
            elif t == "ido":
                ertek = adat.get(k, "") if ido_ervenyes(adat.get(k, "")) else ""
            elif t == "napok":
                ertek = ",".join(sorted({x for x in adat.getall(k, []) if len(x) == 1 and x in "0123456"}))
            elif t in ("csatorna", "kategoria", "rang", "ticket_tipus"):
                ertek = adat.get(k, "")
                ertek = ertek if ertek in {v for v, _ in op[t]} else ""
            elif t == "csatornak":
                ervenyes = {v for v, _ in op["csatorna"]}
                ertek = ",".join(x for x in adat.getall(k, []) if x in ervenyes)
            elif t == "szam":
                try:
                    ertek = str(max(mz["min"], min(mz["max"], int(adat.get(k, "")))))
                except ValueError:
                    ertek = ""
            elif t == "kapcsolo":
                ertek = "1" if "1" in adat.getall(k, []) else "0"
            elif t == "szin":
                ertek = egeszseg_hex(adat.get(k, "")) or ""
            elif t == "lista":
                sorok = []
                for nyers in str(adat.get(k, "")).splitlines():
                    sor = nyers.strip()[: mz.get("max_hossz", 100)]
                    if mz.get("kisbetu"):
                        sor = sor.lower()
                    if k == "automod_domainek":
                        sor = domain_tiszta(sor) or ""
                    if sor and sor not in sorok:
                        sorok.append(sor)
                ertek = "\n".join(sorok[: mz.get("max_sor", 100)])
            elif t == "rovid":
                ertek = str(adat.get(k, "")).strip()[: mz.get("max_hossz", 200)]
            else:
                ertek = str(adat.get(k, "")).strip()[:1000]
            if ertek == "" and not mz.get("ures_ment"):
                await db.torol(g.id, k)
            else:
                await db.set(g.id, k, ertek)
        # A memóriában tartott beállítások frissítése
        if automod := self.bot.get_cog("AutoMod"):
            automod._cache.pop(g.id, None)
        if szint := self.bot.get_cog("Szint"):
            szint._kivetelek.pop(g.id, None)
        if kulcs == "ticket":
            await self.bot.get_cog("Ticket").panel_frissit(g)
        self.vissza(g, adat, ok="mentve")

    # ================================================================== áttekintés
    async def egeszseg(self, g) -> tuple[list[Nyers], int, int]:
        """Ellenőrzőlista: mi hiányzik még a teljes beállításhoz."""
        db, sorok = self.bot.db, []

        def uj(rendben, cim, leiras="", oldal=""):
            sorok.append((rendben, ellenorzes(rendben, cim, leiras, f"/szerver/{g.id}/{oldal}" if oldal is not None else "")))

        me = getattr(g, "me", None)
        if me is not None:
            jogok = me.guild_permissions
            hianyzo = [nev for attr, nev in [
                ("manage_roles", "Rangok kezelése"), ("kick_members", "Tagok kirúgása"), ("ban_members", "Tagok kitiltása"),
                ("moderate_members", "Tagok moderálása"), ("manage_channels", "Csatornák kezelése"),
                ("manage_messages", "Üzenetek kezelése"), ("view_audit_log", "Napló megtekintése"),
            ] if not getattr(jogok, attr, False)]
            uj(not hianyzo, "A bot jogosultságai", "Minden szükséges jogosultsága megvan." if not hianyzo else "Hiányzik: " + ", ".join(hianyzo), None)
        for kulcs, cim, oldal, fontos in [
            ("naplo", "Naplócsatorna beállítva", "alapok", True), ("staffrang", "Staff rang beállítva", "alapok", True),
            ("vezetorang", "Vezetői rang beállítva", "alapok", True), ("vezetoi_csatorna", "Vezetői csatorna beállítva", "alapok", True),
            ("belepes_csatorna", "Üdvözlő csatorna beállítva", "belepes", False), ("javaslat_csatorna", "Javaslatok csatornája beállítva", "kozosseg", False),
            ("riport_csatorna", "Heti és havi statisztikai riport csatornája", "staff", False),
        ]:
            ertek = await db.get(g.id, kulcs)
            letezik = bool(ertek) and (g.get_channel(int(ertek)) or g.get_role(int(ertek))) is not None
            uj(True if letezik else (False if fontos else None), cim, "" if letezik else "Még nincs beállítva (vagy a csatorna/rang törölve lett).", oldal)
        panel = await db.get(g.id, "ticket_panel")
        panel_van = bool(panel) and g.get_channel(int(panel.split(":")[0])) is not None
        uj(True if panel_van else None, "Ticket panel kihelyezve", "" if panel_van else "A tagok még nem tudnak ticketet nyitni.", "ticketek")
        if me is not None:
            for kulcs in ("belepes_rang", "shift_rang", "inaktiv_rang"):
                rang_id = await db.get(g.id, kulcs)
                rang = g.get_role(int(rang_id)) if rang_id else None
                if rang and rang >= me.top_role:
                    uj(False, f"A(z) „{rang.name}” rangot a bot nem tudja kiosztani", "A bot rangja legyen magasabb nála a rangsorban.", "alapok")
        rendben = sum(1 for r, _ in sorok if r is True)
        return [x for _, x in sorok], rendben, len(sorok)

    async def attekintes(self, request: web.Request):
        s, g = self.hozzaferes(request)
        db = self.bot.db
        await self.bot.get_cog("Statisztika").ment_most()
        het = ts() - 7 * 86400
        het_iso = iso(datetime.now(IDOZONA) - timedelta(days=7))
        napok = napok_listaja(14)
        kezdo = napok[0].isoformat()
        uzenet_nap = {x["nap"]: x["db"] for x in await db.fetchall(
            "SELECT nap, SUM(uzenetek) AS db FROM napi_aktivitas WHERE guild_id=? AND nap>=? GROUP BY nap", (g.id, kezdo))}
        nyitva = await self.szamol("SELECT COUNT(*) AS db FROM nyitasok WHERE guild_id=? AND statusz='kuldve'", g.id)
        csempek = Nyers("".join(str(c) for c in [
            csempe(g.member_count, "Tag", "👥"),
            csempe(sum(uzenet_nap.get(n.isoformat(), 0) for n in napok[-7:]), "Üzenet (7 nap)", "💬", "kek"),
            csempe(await self.szamol("SELECT COUNT(*) AS db FROM belepesek WHERE guild_id=? AND belepett>=?", g.id, het), "Belépés (7 nap)", "👋", "zold"),
            csempe(await self.szamol("SELECT COUNT(*) AS db FROM ticketek WHERE guild_id=? AND nyitva=1", g.id), "Nyitott ticket", "🎫", "sarga"),
            csempe(await self.szamol("SELECT COUNT(*) AS db FROM shiftek WHERE guild_id=? AND veg IS NULL", g.id), "Szolgálatban", "🕒"),
            csempe("Nyitva" if nyitva else "Zárva", "A szerver állapota", "🟢" if nyitva else "🔴", "zold" if nyitva else "piros"),
            csempe(await self.szamol("SELECT COUNT(*) AS db FROM szankciok WHERE guild_id=? AND letrehozva>=? AND tipus IN ('warn','timeout','kick','ban')", g.id, het_iso),
                   "Szankció (7 nap)", "🔨", "piros"),
        ]))
        diagram = oszlopdiagram([n.strftime("%m.%d.") for n in napok], [("Üzenet", [uzenet_nap.get(n.isoformat(), 0) for n in napok], "#7c5cff")])

        # Ellenőrzőlista
        sorok, rendben, osszes = await self.egeszseg(g)
        szazalek = 100 * rendben / osszes if osszes else 100
        egeszseg = kartya("Beállítások állapota", "".join(str(x) for x in sorok), f"{rendben} / {osszes} rendben",
                          str(savos(szazalek)))

        # Teendők
        teendok = []
        for x in await db.fetchall("SELECT * FROM jelentkezesek WHERE guild_id=? AND statusz='fuggoben' ORDER BY id LIMIT 8", (g.id,)):
            teendok.append([cimke("Jelentkezés", "fo"), self._nev(g, x["user_id"]), relativ(ts() - x["letrehozva"]),
                            Nyers(f'<a href="/szerver/{g.id}/jelentkezesek?j={x["id"]}#j{x["id"]}">Elbírálás →</a>')])
        for x in await db.fetchall("SELECT * FROM inaktivitasok WHERE guild_id=? AND statusz='fuggoben' ORDER BY id LIMIT 8", (g.id,)):
            teendok.append([cimke("Inaktivitás", "sarga"), self._nev(g, x["user_id"]), relativ(ts() - x["kezdet"]),
                            Nyers(f'<a href="{esc(self.link(g, x["csatorna_id"], x["uzenet_id"]))}" target="_blank" rel="noopener">Megnyitás ↗</a>')])
        for x in await db.fetchall("SELECT * FROM javaslatok WHERE guild_id=? AND statusz='nyitott' ORDER BY id DESC LIMIT 5", (g.id,)):
            teendok.append([cimke("Javaslat", "zold"), self._nev(g, x["user_id"]), relativ(ts() - x["letrehozva"]),
                            Nyers(f'<a href="{esc(self.link(g, x["csatorna_id"], x["uzenet_id"]))}" target="_blank" rel="noopener">Megnyitás ↗</a>')])
        teendok_kartya = kartya("Teendők", tabla(["Típus", "Tag", "Mióta", ""], teendok, "teendok", False) if teendok
                                else ures("Nincs elintézetlen kérelem. 🎉", "✅"), "Elbírálásra váró jelentkezések, kérelmek, javaslatok")

        # Legutóbbi események
        esemenyek = []
        for x in await db.fetchall("SELECT * FROM szankciok WHERE guild_id=? ORDER BY id DESC LIMIT 6", (g.id,)):
            esemenyek.append((epoch(x["letrehozva"]), cimke(SZANKCIO_CIMEK.get(x["tipus"], x["tipus"]), SZANKCIO_SZINEK.get(x["tipus"], "")),
                              self._nev(g, x["user_id"]), x["indok"][:70]))
        for x in await db.fetchall("SELECT * FROM belepesek WHERE guild_id=? ORDER BY id DESC LIMIT 6", (g.id,)):
            esemenyek.append((x["belepett"], cimke("Belépés" if x["eredmeny"] == "maradt" else "Kirúgva", "zold" if x["eredmeny"] == "maradt" else "piros"),
                              self._nev(g, x["user_id"]), x["ok"] or ""))
        esemenyek.sort(key=lambda e: e[0], reverse=True)
        esemeny_kartya = kartya("Legutóbbi események", tabla(
            ["", "Tag", "Részlet", "Mikor"], [[c, n, r, relativ(time.time() - t)] for t, c, n, r in esemenyek[:10]], "esemenyek", False), "Szankciók és belépések")

        return self.kirajzol(
            request, s, g, "", g.name, oldalfej(g.name, "Áttekintés"), f'<div class="racs r6">{csempek}</div>',
            f'<div class="racs r2">{egeszseg}{teendok_kartya}</div>',
            kartya("Napi üzenetek", diagram, "Az elmúlt 14 nap"), esemeny_kartya,
        )

    # ================================================================== alapok
    async def alapok(self, request: web.Request):
        s, g = self.hozzaferes(request)
        me = getattr(g, "me", None)
        jogok = []
        if me is not None:
            for attr, nev, miert in [
                ("manage_roles", "Rangok kezelése", "alaprang, szintrangok, szolgálati és inaktív rang kiosztása"),
                ("kick_members", "Tagok kirúgása", "/kirug és automatikus kirúgások"), ("ban_members", "Tagok kitiltása", "/kitilt és automatikus kitiltás"),
                ("moderate_members", "Tagok moderálása", "némítás (timeout)"), ("manage_channels", "Csatornák kezelése", "ticketcsatornák létrehozása"),
                ("manage_messages", "Üzenetek kezelése", "szűrők: üzenetek törlése"), ("view_audit_log", "Napló megtekintése", "a Discordon kézzel végzett kitiltások rögzítése"),
                ("send_messages", "Üzenetek küldése", "alapvető működés"), ("embed_links", "Beágyazott linkek", "szép üzenetek"),
            ]:
                jogok.append([getattr(me.guild_permissions, attr, False) and cimke("rendben", "zold") or cimke("hiányzik", "piros"), nev, miert])
        return self.kirajzol(
            request, s, g, "alapok", "Alapok", oldalfej("Alapok", "A bot működéséhez szükséges csatornák és rangok."),
            await self.szekcio(s, g, "alapok", "alapok"),
            kartya("A bot jogosultságai", tabla(["Állapot", "Jogosultság", "Mire kell"], jogok, "jogok", False) if jogok else ures("Nem érhető el."),
                   "Ha valami hiányzik, add meg a bot rangjának a Discord szerverbeállításaiban."),
        )

    # ================================================================== statisztika
    async def statisztika(self, request: web.Request):
        s, g = self.hozzaferes(request)
        db = self.bot.db
        await self.bot.get_cog("Statisztika").ment_most()
        try:
            db_nap = int(request.query.get("napok", 14))
        except ValueError:
            db_nap = 14
        db_nap = db_nap if db_nap in (7, 14, 30, 90) else 14
        napok = napok_listaja(db_nap)
        kezdo = napok[0].isoformat()
        uzenet_nap = {x["nap"]: x["db"] for x in await db.fetchall(
            "SELECT nap, SUM(uzenetek) AS db FROM napi_aktivitas WHERE guild_id=? AND nap>=? GROUP BY nap", (g.id, kezdo))}
        tag_nap = {x["nap"]: (x["belepett"], x["kilepett"]) for x in await db.fetchall(
            "SELECT nap, belepett, kilepett FROM napi_tagok WHERE guild_id=? AND nap>=?", (g.id, kezdo))}
        cimkek = [n.strftime("%m.%d.") for n in napok]
        szuro = Nyers('<div class="sor">' + "".join(
            f'<a class="gomb {"" if n == db_nap else "masodlagos"} kicsi" href="/szerver/{g.id}/statisztika?napok={n}">{n} nap</a>' for n in (7, 14, 30, 90)) + "</div>")

        osszes = await db.fetchone(
            "SELECT COALESCE(SUM(uzenetek),0) AS db, COUNT(DISTINCT user_id) AS aktiv FROM napi_aktivitas WHERE guild_id=? AND nap>=?", (g.id, kezdo))
        csempek = Nyers("".join(str(c) for c in [
            csempe(osszes["db"], "Üzenet", "💬", "kek"), csempe(osszes["aktiv"], "Aktív tag", "🧑‍🤝‍🧑", "zold"),
            csempe(sum(v[0] for v in tag_nap.values()), "Csatlakozott", "📥"), csempe(sum(v[1] for v in tag_nap.values()), "Kilépett", "📤", "piros"),
        ]))
        top_tagok = await db.fetchall(
            "SELECT user_id, SUM(uzenetek) AS db FROM napi_aktivitas WHERE guild_id=? AND nap>=? GROUP BY user_id ORDER BY db DESC LIMIT 10", (g.id, kezdo))
        top_csatornak = await db.fetchall(
            "SELECT csatorna_id, SUM(uzenetek) AS db FROM napi_csatorna WHERE guild_id=? AND nap>=? GROUP BY csatorna_id ORDER BY db DESC LIMIT 10", (g.id, kezdo))
        csat_sorok = []
        for x in top_csatornak:
            csatorna = g.get_channel(x["csatorna_id"])
            csat_sorok.append([f"#{csatorna.name}" if csatorna else str(x["csatorna_id"]), x["db"]])

        # Ticketek
        tol_iso, ig_iso = iso(datetime.now(IDOZONA) - timedelta(days=db_nap)), iso(datetime.now(IDOZONA) + timedelta(days=1))
        ticket_cog = self.bot.get_cog("Ticket")
        kat_nevek = {k["kulcs"]: k["nev"] for k in await ticket_cog.kategoriak(g.id, csak_aktiv=False)}
        kat_db = await db.fetchall(
            "SELECT kategoria, COUNT(*) AS db FROM ticketek WHERE guild_id=? AND letrehozva>=? AND letrehozva<? GROUP BY kategoria ORDER BY db DESC", (g.id, tol_iso, ig_iso))
        idok = await db.fetchone(
            "SELECT AVG((julianday(lezarva)-julianday(letrehozva))*86400) AS lezaras, AVG(ertekeles) AS ertek FROM ticketek "
            "WHERE guild_id=? AND lezarva>=? AND lezarva<?", (g.id, tol_iso, ig_iso))
        atvetel = await db.fetchone(
            "SELECT AVG((julianday(atvetel_ido)-julianday(letrehozva))*86400) AS atvetel FROM ticketek WHERE guild_id=? AND atvetel_ido>=? AND atvetel_ido<?", (g.id, tol_iso, ig_iso))
        atvetel_szoveg = ido_szoveg(atvetel["atvetel"]) if atvetel["atvetel"] else "–"
        lezaras_szoveg = ido_szoveg(idok["lezaras"]) if idok["lezaras"] else "–"
        ertek_szoveg = "{:.2f} / 5".format(idok["ertek"]) if idok["ertek"] else "–"
        megoszlas = fank_diagram([(kat_nevek.get(x["kategoria"], x["kategoria"]), x["db"]) for x in kat_db])
        ticket_tartalom = (
            f'<div class="racs r4">{csempe(atvetel_szoveg, "Átlagos átvételi idő", "⏱️", "sarga")}'
            f'{csempe(lezaras_szoveg, "Átlagos lezárási idő", "🕓")}{csempe(ertek_szoveg, "Átlagos értékelés", "⭐", "zold")}</div>{megoszlas}'
        )
        # Szolgálat
        shift_sorok = await self.bot.get_cog("Shift").ranglista(g.id, time.time() - db_nap * 86400, limit=10)

        return self.kirajzol(
            request, s, g, "statisztika", "Statisztika", oldalfej("Statisztika", f"Az elmúlt {db_nap} nap", str(szuro)),
            f'<div class="racs r4">{csempek}</div>',
            kartya("Üzenetek naponta", oszlopdiagram(cimkek, [("Üzenet", [uzenet_nap.get(n.isoformat(), 0) for n in napok], "#7c5cff")])),
            kartya("Belépések és kilépések", oszlopdiagram(cimkek, [
                ("Csatlakozott", [tag_nap.get(n.isoformat(), (0, 0))[0] for n in napok], "#2ecc8f"),
                ("Kilépett", [tag_nap.get(n.isoformat(), (0, 0))[1] for n in napok], "#ff5d6c")])),
            f'<div class="racs r2">{kartya("Legaktívabb tagok", tabla(["Tag", "Üzenet"], [[self._nev(g, x["user_id"]), x["db"]] for x in top_tagok], "top-tagok", False))}'
            f'{kartya("Legaktívabb csatornák", tabla(["Csatorna", "Üzenet"], csat_sorok, "top-csat", False))}</div>',
            kartya("Ticketek", ticket_tartalom, "Típusok szerinti megoszlás és átlagos idők"),
            kartya("Szolgálati idők", tabla(["#", "Staff tag", "Szolgálati idő"], [[n, self._nev(g, x["user_id"]), ido_szoveg(x["mp"])] for n, x in enumerate(shift_sorok, 1)], "shift", False)),
        )

    # ================================================================== belépés oldal
    async def belepes(self, request: web.Request):
        s, g = self.hozzaferes(request)
        db = self.bot.db
        automod = self.bot.get_cog("AutoMod")
        raid_vege = await automod.raid_vege(g.id)
        raid_aktiv = raid_vege > ts()
        napok = napok_listaja(30)
        tag_nap = {x["nap"]: (x["belepett"], x["kilepett"]) for x in await db.fetchall(
            "SELECT nap, belepett, kilepett FROM napi_tagok WHERE guild_id=? AND nap>=?", (g.id, napok[0].isoformat()))}
        raid_szoveg = ("🚨 Aktív" + (", kézi kikapcsolásig" if raid_vege >= RAID_KEZI else f", lejár: {mp_datum(raid_vege)}")) if raid_aktiv else "Kikapcsolva"
        raid_gomb = urlap(f"/szerver/{g.id}/raid", s["c"], Nyers(
            f'<input type="hidden" name="be" value="{0 if raid_aktiv else 1}">'
            f'<button class="{"" if raid_aktiv else "veszely"}">{"Raid mód kikapcsolása" if raid_aktiv else "Raid mód bekapcsolása"}</button>'), vissza="belepes", sav=False,
            megerosites="" if raid_aktiv else "Bekapcsolod a raid módot? Minden új belépőt kirúg a bot, amíg ki nem kapcsolod.")
        sorok = await db.fetchall("SELECT * FROM belepesek WHERE guild_id=? ORDER BY id DESC LIMIT 60", (g.id,))
        tabla_html = tabla(
            ["Tag", "Belépett", "Fiók kora", "Eredmény", "Kilépett"],
            [[self._nev(g, x["user_id"]), mp_datum(x["belepett"]), f"{(x['belepett'] - x['fiok_letrehozva']) // 86400} napos",
              cimke("maradt", "zold") if x["eredmeny"] == "maradt" else Nyers(str(cimke("kirúgva", "piros")) + f' <span class="halk">{esc(x["ok"] or "")}</span>'),
              mp_datum(x["kilepett"])] for x in sorok], "belepesek")
        return self.kirajzol(
            request, s, g, "belepes", "Belépés", oldalfej("Belépés", "Üdvözlés, alaprang és a belépések naplója."),
            await self.szekcio(s, g, "belepes", "belepes"),
            kartya("Raid védelem", f'<div class="sor"><b>{raid_szoveg}</b>{raid_gomb}</div>', "A küszöbök az „Automod és szankciók” oldalon állíthatók."),
            kartya("Belépések és kilépések", oszlopdiagram([n.strftime("%m.%d.") for n in napok], [
                ("Csatlakozott", [tag_nap.get(n.isoformat(), (0, 0))[0] for n in napok], "#2ecc8f"),
                ("Kilépett", [tag_nap.get(n.isoformat(), (0, 0))[1] for n in napok], "#ff5d6c")]), "Az elmúlt 30 nap"),
            kartya("Legutóbbi belépések", tabla_html, "Tartósan az adatbázisban tárolva"),
        )

    async def raid(self, request: web.Request):
        s, g, adat = await self._post(request)
        be = adat.get("be") == "1"
        await self.bot.db.set(g.id, "automod_raid_vege", str(RAID_KEZI if be else 0))
        self.vissza(g, adat, ok="raid_be" if be else "raid_ki")

    # ================================================================== ticketek
    def kat_urlap(self, s, g, k, op, uj: bool = False) -> Nyers:
        elo = f"k{k['id']}-" if not uj else "uj-"
        szoveg = lambda mz, ertek: mezo_html(mz, ertek, op, g.name, elo)
        mezok = "".join(str(x) for x in [
            szoveg(m("nev", "Név", "rovid", max_hossz=45), k["nev"] if not uj else ""),
            szoveg(m("emoji", "Emoji", "rovid", max_hossz=40, seg="Pl. 🛠️ vagy egyedi szerver-emoji: <:nev:123456789012345678>"), k["emoji"] or "" if not uj else ""),
            szoveg(m("leiras", "Rövid leírás (a menüben látszik)", "rovid", max_hossz=100, teljes=True), k["leiras"] or "" if not uj else ""),
            szoveg(m("udvozlo", "Üdvözlő szöveg a ticketben", "szoveg", sorok=3, teljes=True, seg="Használható: {tag}. Üresen hagyva az alapértelmezett szöveg jelenik meg."), k["udvozlo"] or "" if not uj else ""),
            szoveg(m("szin", "A ticket színe", "szin", alap="#7c5cff"), k["szin"] if not uj else None),
            szoveg(m("discord_kategoria_id", "Ide kerüljenek a ticketcsatornák", "kategoria", seg="Üresen hagyva az alapértelmezett csatornakategória."), str(k["discord_kategoria_id"] or "") if not uj else ""),
            szoveg(m("rang_id", "Kezelő rang", "rang", seg="Csak ez a rang látja és kezelheti az ilyen ticketeket. Üresen hagyva az általános staff rang."), str(k["rang_id"] or "") if not uj else ""),
            szoveg(m("kerdesek", "Kérdések ticketnyitáskor (soronként egy, legfeljebb 5)", "lista", sorok=4, teljes=True,
                     seg="Ha van kérdés, a tag előbb egy űrlapot tölt ki, a válaszok megjelennek a ticketben."), k["kerdesek"] if not uj else ""),
            szoveg(m("aktiv", "Elérhető a panelen", "kapcsolo", alap=1, teljes=True), ("1" if k["aktiv"] else "0") if not uj else "1"),
        ])
        azon = "" if uj else f'<input type="hidden" name="azon" value="{k["id"]}">'
        gombok = (f'<div class="sor" style="margin-top:6px"><button name="muvelet" value="{"uj" if uj else "ment"}">{"Létrehozás" if uj else "Mentés"}</button>'
                  + ("" if uj else '<button class="masodlagos" name="muvelet" value="fel" title="Feljebb">↑</button>'
                     '<button class="masodlagos" name="muvelet" value="le" title="Lejjebb">↓</button>')
                  + "</div>")
        beado = urlap(f"/szerver/{g.id}/ticket/kategoria", s["c"], Nyers(f'{azon}<div class="mezok">{mezok}</div>{gombok}'), vissza="ticketek", sav=False)
        torles = ""
        if not uj:
            torles = urlap(f"/szerver/{g.id}/ticket/kategoria", s["c"], Nyers(
                f'{azon}<button class="veszely kicsi" name="muvelet" value="torol">🗑️ Törlés</button>'), vissza="ticketek", sav=False,
                megerosites="Biztosan törlöd ezt a ticket-típust? A már megnyitott ticketek nem változnak.")
        return Nyers(beado + torles)

    async def ticketek(self, request: web.Request):
        s, g = self.hozzaferes(request)
        db, ticket_cog, op = self.bot.db, self.bot.get_cog("Ticket"), self.opciok(g)
        kategoriak = await ticket_cog.kategoriak(g.id, csak_aktiv=False)
        kat_nevek = {k["kulcs"]: k["nev"] for k in kategoriak}

        panel = await db.get(g.id, "ticket_panel")
        panel_info = "Még nincs kihelyezve."
        if panel:
            csatorna_id, uzenet_id = (int(x) for x in panel.split(":"))
            csatorna = g.get_channel(csatorna_id)
            if csatorna:
                panel_info = Nyers(f'Kihelyezve: <b>#{esc(csatorna.name)}</b> • <a href="{esc(self.link(g, csatorna_id, uzenet_id))}" target="_blank" rel="noopener">megnyitás ↗</a>')
        panel_urlap = urlap(f"/szerver/{g.id}/ticket/panel", s["c"], Nyers(
            f'<div class="sor"><select name="csatorna" style="max-width:280px">{opcio_html(op["csatorna"], set())}</select>'
            '<button name="muvelet" value="kozzetesz">Panel kihelyezése</button>'
            '<button class="masodlagos" name="muvelet" value="frissit">Kihelyezett panel frissítése</button></div>'), vissza="ticketek", sav=False)
        panel_kartya = kartya("Ticket panel", f'<p style="margin-top:0">{panel_info}</p>{panel_urlap}',
                              "A panelen a tagok a legördülő menüből választanak. A kategóriák módosításakor a kihelyezett panel automatikusan frissül.")

        kat_kartyak = []
        for k in kategoriak:
            jel = "" if k["aktiv"] else str(cimke("rejtett", "sarga"))
            kerdes_db = len([x for x in k["kerdesek"].splitlines() if x.strip()])
            kat_kartyak.append(
                f'<details><summary><span>{esc(k["emoji"] or "▫️")}</span><span>{esc(k["nev"])}</span>{jel}'
                f'<span class="halk" style="font-weight:400">{kerdes_db} kérdés</span></summary><div class="belso">{self.kat_urlap(s, g, k, op)}</div></details>')
        uj_urlap = f'<details{" open" if not kategoriak else ""}><summary>➕ Új ticket-típus</summary><div class="belso">{self.kat_urlap(s, g, {"id": 0}, op, uj=True)}</div></details>'
        kategoria_kartya = kartya("Ticket-típusok", "".join(kat_kartyak) + uj_urlap,
                                  f"{len(kategoriak)} / {MAX_KATEGORIA} típus. Minden típushoz külön név, emoji, színe, kezelő rang, csatornakategória és kérdéssor adható.")

        sorok = await db.fetchall("SELECT * FROM ticketek WHERE guild_id=? ORDER BY id DESC LIMIT 100", (g.id,))
        tabla_html = tabla(
            ["#", "Típus", "Nyitotta", "Átvette", "Állapot", "Értékelés", "Megnyitva"],
            [[f"{x['id']:04d}", kat_nevek.get(x["kategoria"], x["kategoria"]), self._nev(g, x["user_id"]), self._nev(g, x["atvette"]),
              cimke("nyitva", "zold") if x["nyitva"] else cimke("lezárva"), "⭐" * x["ertekeles"] if x["ertekeles"] else "–", datum(x["letrehozva"])] for x in sorok], "ticket-lista")
        return self.kirajzol(
            request, s, g, "ticketek", "Ticketek", oldalfej("Ticketek", "Típusok, panel, űrlapkérdések és a ticketek listája."),
            panel_kartya, await self.ticket_web_kartyak(s, g, kategoriak), kategoria_kartya, await self.szekcio(s, g, "ticket", "ticketek"),
            kartya("Legutóbbi ticketek", tabla_html),
        )

    async def ticket_kategoria(self, request: web.Request):
        s, g, adat = await self._post(request)
        db, ticket_cog, op = self.bot.db, self.bot.get_cog("Ticket"), self.opciok(g)
        muvelet = adat.get("muvelet", "")
        kategoriak = list(await ticket_cog.kategoriak(g.id, csak_aktiv=False))

        def mezok_beolvas():
            nev = str(adat.get("nev", "")).strip()[:45]
            emoji = str(adat.get("emoji", "")).strip()
            kerdesek, latott = [], set()
            for sor in str(adat.get("kerdesek", "")).splitlines():
                sor = sor.strip()[:45]
                if sor and sor not in latott:
                    kerdesek.append(sor)
                    latott.add(sor)
            kat_id, rang_id = adat.get("discord_kategoria_id", ""), adat.get("rang_id", "")
            return {
                "nev": nev, "emoji": emoji if emoji_ervenyes(emoji) else "", "leiras": str(adat.get("leiras", "")).strip()[:100],
                "udvozlo": str(adat.get("udvozlo", "")).strip()[:1000], "szin": egeszseg_hex(adat.get("szin", "")),
                "kat": int(kat_id) if kat_id in {v for v, _ in op["kategoria"]} else None,
                "rang": int(rang_id) if rang_id in {v for v, _ in op["rang"]} else None,
                "kerdesek": "\n".join(kerdesek[:5]), "aktiv": 1 if "1" in adat.getall("aktiv", []) else 0,
            }

        try:
            azon = int(adat.get("azon", 0))
        except ValueError:
            azon = 0
        sor = next((k for k in kategoriak if k["id"] == azon), None)

        if muvelet == "uj":
            if len(kategoriak) >= MAX_KATEGORIA:
                self.vissza(g, adat, hiba="limit")
            mz = mezok_beolvas()
            if not mz["nev"]:
                self.vissza(g, adat, hiba="nev")
            kulcs, n = kulcs_keszit(mz["nev"]), 2
            letezo = {k["kulcs"] for k in kategoriak}
            alap = kulcs
            while kulcs in letezo:
                kulcs, n = f"{alap}-{n}", n + 1
            await db.execute(
                "INSERT INTO ticket_kategoriak (guild_id, kulcs, nev, emoji, leiras, udvozlo, szin, discord_kategoria_id, rang_id, kerdesek, sorrend, aktiv) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (g.id, kulcs, mz["nev"], mz["emoji"] or None, mz["leiras"] or None, mz["udvozlo"] or None, mz["szin"], mz["kat"], mz["rang"],
                 mz["kerdesek"], max([k["sorrend"] for k in kategoriak] + [-1]) + 1, mz["aktiv"]),
            )
            ok = "kat_uj"
        elif sor is None:
            self.vissza(g, adat, hiba="nem_talalhato")
        elif muvelet == "ment":
            mz = mezok_beolvas()
            if not mz["nev"]:
                self.vissza(g, adat, hiba="nev")
            await db.execute(
                "UPDATE ticket_kategoriak SET nev=?, emoji=?, leiras=?, udvozlo=?, szin=?, discord_kategoria_id=?, rang_id=?, kerdesek=?, aktiv=? WHERE id=?",
                (mz["nev"], mz["emoji"] or None, mz["leiras"] or None, mz["udvozlo"] or None, mz["szin"], mz["kat"], mz["rang"], mz["kerdesek"], mz["aktiv"], azon),
            )
            ok = "kat_mentve"
        elif muvelet == "torol":
            await db.execute("DELETE FROM ticket_kategoriak WHERE id=?", (azon,))
            ok = "kat_torolve"
        elif muvelet in ("fel", "le"):
            sorrend = [k["id"] for k in kategoriak]
            i = sorrend.index(azon)
            j = i - 1 if muvelet == "fel" else i + 1
            if 0 <= j < len(sorrend):
                sorrend[i], sorrend[j] = sorrend[j], sorrend[i]
            for hely, kat_id in enumerate(sorrend):
                await db.execute("UPDATE ticket_kategoriak SET sorrend=? WHERE id=?", (hely, kat_id))
            ok = "kat_mentve"
        else:
            self.vissza(g, adat, hiba="ervenytelen")
        await ticket_cog.panel_frissit(g)
        self.vissza(g, adat, ok=ok)

    async def ticket_panel(self, request: web.Request):
        s, g, adat = await self._post(request)
        ticket_cog = self.bot.get_cog("Ticket")
        if adat.get("muvelet") == "frissit":
            if not await ticket_cog.panel_frissit(g):
                self.vissza(g, adat, hiba="nincs_panel")
            self.vissza(g, adat, ok="panel_frissitve")
        csatorna = next((c for c in g.text_channels if str(c.id) == adat.get("csatorna", "")), None)
        if csatorna is None:
            self.vissza(g, adat, hiba="ervenytelen")
        try:
            await ticket_cog.panel_kozzetesz(g, csatorna)
        except discord.HTTPException:
            self.vissza(g, adat, hiba="panel_hiba")
        self.vissza(g, adat, ok="panel")

    # ================================================================== szint
    async def szint(self, request: web.Request):
        s, g = self.hozzaferes(request)
        db, op = self.bot.db, self.opciok(g)
        rangok = await db.fetchall("SELECT szint, rang_id FROM szint_rangok WHERE guild_id=? ORDER BY szint", (g.id,))
        szorzok = await db.fetchall("SELECT rang_id, szorzo FROM szint_szorzok WHERE guild_id=? ORDER BY szorzo DESC", (g.id,))

        def rang_nev(rid):
            rang = g.get_role(rid)
            return rang.name if rang else f"(törölt rang {rid})"

        def torles(vege, kulcs, ertek):
            return str(urlap(f"/szerver/{g.id}/szint/{vege}", s["c"], Nyers(
                f'<input type="hidden" name="muvelet" value="torol"><input type="hidden" name="{kulcs}" value="{ertek}">'
                '<button class="veszely kicsi">Törlés</button>'), vissza="szint", sav=False))

        rang_tabla = tabla(["Szint", "Rang", ""], [[f"{x['szint']}. szint", rang_nev(x["rang_id"]), Nyers(torles("rang", "szint", x["szint"]))] for x in rangok], "szintrangok", False)
        rang_uj = urlap(f"/szerver/{g.id}/szint/rang", s["c"], Nyers(
            '<input type="hidden" name="muvelet" value="ad"><div class="sor"><input type="number" name="szint" min="1" max="200" placeholder="Szint" style="max-width:110px" required>'
            f'<select name="rang" style="max-width:260px" required><option value="">— rang —</option>{opcio_html(op["rang"], set())}</select><button>Hozzáadás</button></div>'),
            vissza="szint", sav=False)
        szorzo_tabla = tabla(["Rang", "Szorzó", ""], [[rang_nev(x["rang_id"]), f"{x['szorzo']:g}×", Nyers(torles("szorzo", "rang", x["rang_id"]))] for x in szorzok], "szorzok", False)
        szorzo_uj = urlap(f"/szerver/{g.id}/szint/szorzo", s["c"], Nyers(
            '<input type="hidden" name="muvelet" value="ad"><div class="sor">'
            f'<select name="rang" style="max-width:260px" required><option value="">— rang —</option>{opcio_html(op["rang"], set())}</select>'
            '<input type="number" name="szorzo" min="0.1" max="5" step="0.1" value="1.5" style="max-width:110px" required><button>Hozzáadás</button></div>'),
            vissza="szint", sav=False)

        hely = '<div style="height:12px"></div>'
        rang_kartya = kartya("Szintrangok", f"{rang_tabla}{hely}{rang_uj}", "Az adott szinten kapja meg a tag. Mindig a legmagasabb elért szintrang marad meg.")
        szorzo_kartya = kartya("XP-szorzók", f"{szorzo_tabla}{hely}{szorzo_uj}", "Pl. boostereknek 1,5×. Több rang esetén a legnagyobb számít.")
        top = await db.fetchall("SELECT user_id, xp, uzenetek FROM szintek WHERE guild_id=? ORDER BY xp DESC LIMIT 25", (g.id,))
        top_sorok = []
        for n, x in enumerate(top, 1):
            szint = xp_szint(x["xp"])
            alap, cel = szint_xp(szint), szint_xp(szint + 1)
            top_sorok.append([n, self._nev(g, x["user_id"]), f"{szint}.", Nyers(f'{savos(100 * (x["xp"] - alap) / (cel - alap))}'), f"{x['xp']} XP", x["uzenetek"]])
        return self.kirajzol(
            request, s, g, "szint", "Szintek", oldalfej("Szintek", "XP, szintrangok és szorzók."),
            await self.szekcio(s, g, "szint", "szint"),
            f'<div class="racs r2">{rang_kartya}{szorzo_kartya}</div>',
            kartya("Toplista", tabla(["#", "Tag", "Szint", "Haladás", "XP", "Üzenet"], top_sorok, "toplista")),
        )

    async def szint_rang(self, request: web.Request):
        s, g, adat = await self._post(request)
        db = self.bot.db
        if adat.get("muvelet") == "torol":
            try:
                await db.execute("DELETE FROM szint_rangok WHERE guild_id=? AND szint=?", (g.id, int(adat.get("szint", 0))))
            except ValueError:
                self.vissza(g, adat, hiba="ervenytelen")
            self.vissza(g, adat, ok="rang_torolve")
        try:
            szint = int(adat.get("szint", ""))
            rang = next(r for r in g.roles if str(r.id) == adat.get("rang") and not r.is_default())
            assert 1 <= szint <= 200
        except (ValueError, StopIteration, AssertionError):
            self.vissza(g, adat, hiba="ervenytelen")
        await db.execute(
            "INSERT INTO szint_rangok (guild_id, szint, rang_id) VALUES (?, ?, ?) ON CONFLICT(guild_id, szint) DO UPDATE SET rang_id=excluded.rang_id",
            (g.id, szint, rang.id))
        self.vissza(g, adat, ok="rang_mentve")

    async def szint_szorzo(self, request: web.Request):
        s, g, adat = await self._post(request)
        db = self.bot.db
        szint_cog = self.bot.get_cog("Szint")
        if adat.get("muvelet") == "torol":
            try:
                await db.execute("DELETE FROM szint_szorzok WHERE guild_id=? AND rang_id=?", (g.id, int(adat.get("rang", 0))))
            except ValueError:
                self.vissza(g, adat, hiba="ervenytelen")
            szint_cog._szorzok.pop(g.id, None)
            self.vissza(g, adat, ok="szorzo_torolve")
        try:
            szorzo = float(adat.get("szorzo", ""))
            rang = next(r for r in g.roles if str(r.id) == adat.get("rang") and not r.is_default())
            assert 0.1 <= szorzo <= 5
        except (ValueError, StopIteration, AssertionError):
            self.vissza(g, adat, hiba="ervenytelen")
        await db.execute(
            "INSERT INTO szint_szorzok (guild_id, rang_id, szorzo) VALUES (?, ?, ?) ON CONFLICT(guild_id, rang_id) DO UPDATE SET szorzo=excluded.szorzo",
            (g.id, rang.id, round(szorzo, 2)))
        szint_cog._szorzok.pop(g.id, None)
        self.vissza(g, adat, ok="szorzo_mentve")

    # ================================================================== közösség
    async def kozosseg(self, request: web.Request):
        s, g = self.hozzaferes(request)
        db = self.bot.db
        javaslatok = await db.fetchall(
            "SELECT j.*, COALESCE((SELECT SUM(szavazat=1) FROM javaslat_szavazatok WHERE javaslat_id=j.id),0) AS fel, "
            "COALESCE((SELECT SUM(szavazat=-1) FROM javaslat_szavazatok WHERE javaslat_id=j.id),0) AS le "
            "FROM javaslatok j WHERE guild_id=? ORDER BY id DESC LIMIT 50", (g.id,))
        statuszok = {"nyitott": ("szavazás", "fo"), "elfogadva": ("elfogadva", "zold"), "elutasitva": ("elutasítva", "piros"),
                     "megvalositva": ("megvalósítva", "zold"), "fontolora": ("fontolóra véve", "sarga")}
        jav_sorok = []
        for x in javaslatok:
            nev, szin = statuszok.get(x["statusz"], (x["statusz"], ""))
            jav_sorok.append([f"#{x['id']}", cimke(nev, szin), x["szoveg"][:90] + ("…" if len(x["szoveg"]) > 90 else ""), f"👍 {x['fel']}  👎 {x['le']}",
                              self._nev(g, x["user_id"]), Nyers(f'<a href="{esc(self.link(g, x["csatorna_id"], x["uzenet_id"]))}" target="_blank" rel="noopener">↗</a>')])
        jatekok = await db.fetchall(
            "SELECT n.*, (SELECT COUNT(*) FROM nyj_reszvevok WHERE nyj_id=n.id) AS reszvevok FROM nyeremenyjatekok n "
            "WHERE guild_id=? ORDER BY id DESC LIMIT 20", (g.id,))
        nyj_sorok = [[f"#{x['id']}", x["nyeremeny"], cimke("befejezve") if x["befejezve"] else cimke("fut", "zold"),
                      mp_datum(x["vege"]), x["reszvevok"], ", ".join(self._nev(g, int(u)) for u in x["nyertesek"].split(",") if u) or "–"] for x in jatekok]
        return self.kirajzol(
            request, s, g, "kozosseg", "Javaslatok és játékok", oldalfej("Javaslatok és játékok", "Szavazások és nyereményjátékok."),
            await self.szekcio(s, g, "javaslat", "kozosseg"),
            kartya("Javaslatok", tabla(["#", "Állapot", "Javaslat", "Szavazatok", "Beküldte", ""], jav_sorok, "javaslatok") if jav_sorok else ures("Még nincs javaslat.", "💡"),
                   "Döntés: /javaslat dontes a Discordon"),
            kartya("Nyereményjátékok", tabla(["#", "Nyeremény", "Állapot", "Vége", "Résztvevők", "Nyertesek"], nyj_sorok, "nyj") if nyj_sorok else ures("Még nem volt nyereményjáték.", "🎁"),
                   "Indítás: /nyeremenyjatek inditas a Discordon"),
        )

    # ================================================================== moderáció és szankciók
    async def moderacio(self, request: web.Request):
        s, g = self.hozzaferes(request)
        db = self.bot.db
        het_iso = iso(datetime.now(IDOZONA) - timedelta(days=7))
        db_tipus = {x["tipus"]: x["db"] for x in await db.fetchall(
            "SELECT tipus, COUNT(*) AS db FROM szankciok WHERE guild_id=? AND letrehozva>=? GROUP BY tipus", (g.id, het_iso))}
        automata = await self.szamol(
            "SELECT COUNT(*) AS db FROM szankciok WHERE guild_id=? AND letrehozva>=? AND moderator_id=? AND tipus='warn'", g.id, het_iso, self.bot.user.id)
        csempek = Nyers("".join(str(c) for c in [
            csempe(db_tipus.get("warn", 0), "Figyelmeztetés (7 nap)", "⚠️", "sarga"), csempe(db_tipus.get("timeout", 0), "Némítás", "🔇"),
            csempe(db_tipus.get("kick", 0) + db_tipus.get("ban", 0), "Kirúgás / kitiltás", "🔨", "piros"), csempe(automata, "Ebből automata", "🤖", "kek"),
        ]))
        sorok = await db.fetchall("SELECT * FROM szankciok WHERE guild_id=? ORDER BY id DESC LIMIT 15", (g.id,))
        tabla_html = tabla(["#", "Típus", "Tag", "Moderátor", "Indok", "Mikor"], [
            [x["id"], cimke(SZANKCIO_CIMEK.get(x["tipus"], x["tipus"]), SZANKCIO_SZINEK.get(x["tipus"], "")), self._nev(g, x["user_id"]),
             "🤖 automata" if x["moderator_id"] == self.bot.user.id else self._nev(g, x["moderator_id"]), x["indok"][:80], datum(x["letrehozva"])] for x in sorok], "szankcio-friss", False)
        return self.kirajzol(
            request, s, g, "moderacio", "Automod és szankciók", oldalfej("Automod és szankciók", "Szűrők, eszkaláció és a legutóbbi szankciók."),
            f'<div class="racs r4">{csempek}</div>', await self.szekcio(s, g, "automod", "moderacio"), await self.szekcio(s, g, "szankcio", "moderacio"),
            kartya("Legutóbbi szankciók", tabla_html, "", f'<a class="gomb masodlagos kicsi" href="/szerver/{g.id}/szankciok">Teljes napló →</a>'),
        )

    async def szankciok(self, request: web.Request):
        s, g = self.hozzaferes(request)
        szuro, tipus = request.query.get("felhasznalo", "").strip(), request.query.get("tipus", "")
        feltetel, arg = ["guild_id=?"], [g.id]
        if szuro.isdigit():
            feltetel.append("user_id=?")
            arg.append(int(szuro))
        if tipus in SZANKCIO_CIMEK:
            feltetel.append("tipus=?")
            arg.append(tipus)
        sorok = await self.bot.db.fetchall(f"SELECT * FROM szankciok WHERE {' AND '.join(feltetel)} ORDER BY id DESC LIMIT 300", tuple(arg))
        tabla_html = tabla(["#", "Típus", "Felhasználó", "Moderátor", "Indok", "Időpont", "Állapot", ""], [
            [x["id"], cimke(SZANKCIO_CIMEK.get(x["tipus"], x["tipus"]), SZANKCIO_SZINEK.get(x["tipus"], "")), self._nev(g, x["user_id"]),
             "🤖 automata" if x["moderator_id"] == self.bot.user.id else self._nev(g, x["moderator_id"]), x["indok"], datum(x["letrehozva"]),
             cimke("aktív", "zold") if x["aktiv"] else cimke("visszavont / lejárt"), self.szankcio_sor_gomb(s, g, x)] for x in sorok], "szankcio-lista")
        tipus_opciok = opcio_html([("", "Minden típus")] + list(SZANKCIO_CIMEK.items()), {tipus})
        szuro_urlap = (f'<form method="get" class="sor"><input type="text" name="felhasznalo" value="{esc(szuro)}" placeholder="Felhasználó azonosítója" style="max-width:260px">'
                       f'<select name="tipus" style="max-width:200px">{tipus_opciok}</select><button>Szűrés</button></form>')
        return self.kirajzol(
            request, s, g, "szankciok", "Szankciónapló", oldalfej("Szankciónapló", f"{len(sorok)} találat (legfeljebb 300)"),
            self.szankcio_urlap_kartya(s, g), kartya("", szuro_urlap), kartya("", tabla_html),
        )

    # ================================================================== staff
    async def staff(self, request: web.Request):
        s, g = self.hozzaferes(request)
        db = self.bot.db
        shift = self.bot.get_cog("Shift")
        aktiv = await db.fetchall("SELECT * FROM shiftek WHERE guild_id=? AND veg IS NULL ORDER BY kezdet", (g.id,))
        aktiv_tabla = tabla(["Staff tag", "Állapot", "Eltelt idő"], [
            [self._nev(g, x["user_id"]), cimke("szünet", "sarga") if x["szunet_kezdet"] else cimke("szolgálatban", "zold"), ido_szoveg(ts() - x["kezdet"])] for x in aktiv],
            "szolgalatban", False) if aktiv else ures("Jelenleg senki sincs szolgálatban.", "😴")
        ranglista = await shift.ranglista(g.id, het_kezdete().timestamp(), limit=15)
        legnagyobb = max([x["mp"] for x in ranglista] + [1])
        rang_tabla = tabla(["#", "Staff tag", "", "Idő"], [
            [n, self._nev(g, x["user_id"]), savos(100 * x["mp"] / legnagyobb), ido_szoveg(x["mp"])] for n, x in enumerate(ranglista, 1)], "heti", False) if ranglista else ures("Ezen a héten még nincs szolgálati idő.", "🕒")

        fuggo = []
        for x in await db.fetchall("SELECT * FROM jelentkezesek WHERE guild_id=? AND statusz='fuggoben' ORDER BY id", (g.id,)):
            fuggo.append([cimke("Jelentkezés", "fo"), self._nev(g, x["user_id"]), mp_datum(x["letrehozva"]),
                          Nyers(f'<a href="/szerver/{g.id}/jelentkezesek?j={x["id"]}#j{x["id"]}">Elbírálás →</a>')])
        for x in await db.fetchall("SELECT * FROM inaktivitasok WHERE guild_id=? AND statusz IN ('fuggoben','elfogadva') AND lezarva=0 ORDER BY id", (g.id,)):
            fuggo.append([cimke("Inaktivitás • " + ("aktív" if x["statusz"] == "elfogadva" else "függőben"), "sarga"), self._nev(g, x["user_id"]),
                          f"{mp_datum(x['kezdet'])} – {mp_datum(x['veg'])}", Nyers(f'<a href="{esc(self.link(g, x["csatorna_id"], x["uzenet_id"]))}" target="_blank" rel="noopener">Megnyitás ↗</a>')])
        return self.kirajzol(
            request, s, g, "staff", "Staff és szolgálat", oldalfej("Staff és szolgálat", "Jelentkezések, szolgálati idő, inaktivitás."),
            f'<div class="racs r2">{kartya("Most szolgálatban", aktiv_tabla)}{kartya("Heti ranglista", rang_tabla, "Szolgálati idő ezen a héten")}</div>',
            kartya("Jelentkezések és inaktivitás", tabla(["Típus", "Tag", "Időpont", ""], fuggo, "fuggo", False) if fuggo else ures("Nincs függő jelentkezés vagy kérelem.", "✅"),
                   "A jelentkezések a Jelentkezések oldalon vagy a vezetői csatornában a gombokkal bírálhatók el."),
            await self.szekcio(s, g, "staff", "staff"), await self.szekcio(s, g, "szolgalat", "staff"),
        )


async def setup(bot):
    await bot.add_cog(Dashboard(bot))
