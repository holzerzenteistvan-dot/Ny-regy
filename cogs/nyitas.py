"""Szerver nyitás: beágyazott nyitás üzenet külön (nem beágyazott) pinggel, időzítés, lezárás.

A dashboard Nyitás oldaláról és parancsból is használható. A beállításokat (csatorna, ping, cím, szöveg, szín, link)
a dashboardon lehet elmenteni alapértelmezettként, így egy kattintással kimegy a nyitás.
"""
import logging
import re
from datetime import datetime, timedelta, timezone

import discord
from discord import app_commands
from discord.ext import commands, tasks

from cogs.ticket import szin_ertek
from util import IDOZONA, PIROS, SZURKE, ZOLD, staff_only, ts
from webkozos import ido_ervenyes

log = logging.getLogger("dcbot.nyitas")

ALAP_CIM = "🟢 A szerver megnyílt!"
ALAP_SZOVEG = "Szia! A szerver **nyitva van**, gyertek játszani! 🎮\nCsatlakozz az alábbi gombbal vagy a szerverkóddal, és érezd jól magad!"
ALAP_SZIN = "#2ecc8f"
ALAP_PING = "everyone"
ALAP_ZARAS_CIM = "🔴 A szerver lezárult"
ALAP_ZARAS_SZOVEG = "Köszönjük, hogy játszottatok! Legközelebb is várunk titeket. 👋"
ALAP_ZARAS_SZIN = "#ff5d6c"
ALAP_ZARAS_PING = "here"
AUTO_TURELEM_PERC = 45  # ennyivel a beállított idő után már nem nyit automatikusan (pl. ha a bot épp le volt állva)
PING_OPCIOK = [("", "Nincs ping"), ("everyone", "@everyone"), ("here", "@here"), ("rang", "Egy rang pingelése")]


class NyitasHiba(Exception):
    """Olvasható hibaüzenettel jelzi, hogy a nyitás nem küldhető ki (a szöveg közvetlenül megjeleníthető)."""


def link_ervenyes(szoveg: str) -> bool:
    return bool(re.fullmatch(r"https://[^\s]{3,290}", szoveg or ""))


def ping_tartalom(ping: str) -> tuple[str | None, discord.AllowedMentions]:
    """A ping szövege (az üzenet tartalmába kerül, nem a beágyazásba) és az engedélyezett említések."""
    if ping == "everyone":
        return "@everyone", discord.AllowedMentions(everyone=True)
    if ping == "here":
        return "@here", discord.AllowedMentions(everyone=True)
    if ping.startswith("rang:") and ping[5:].isdigit():
        rang_id = int(ping[5:])
        return f"<@&{rang_id}>", discord.AllowedMentions(roles=[discord.Object(rang_id)])
    return None, discord.AllowedMentions.none()


def ping_ertek(ping: str, rang_id: str) -> str:
    """A beállított ping típusból (és rangból) a tárolt ping érték."""
    if ping == "rang":
        return f"rang:{rang_id}" if rang_id and str(rang_id).isdigit() else ""
    return ping if ping in ("everyone", "here") else ""


class Nyitas(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    async def cog_load(self):
        self.idozito.start()

    async def cog_unload(self):
        self.idozito.cancel()

    # ------------------------------------------------------------------ alapértékek
    async def alapok(self, guild_id: int) -> dict:
        """A szerver mentett nyitás-sablonja (a dashboardon állítható)."""
        get = self.bot.db.get
        return {
            "csatorna": await get(guild_id, "nyitas_csatorna") or "",
            "cim": await get(guild_id, "nyitas_cim") or ALAP_CIM,
            "szoveg": await get(guild_id, "nyitas_szoveg") or ALAP_SZOVEG,
            "szin": await get(guild_id, "nyitas_szin") or ALAP_SZIN,
            "ping": await get(guild_id, "nyitas_ping", ALAP_PING),
            "ping_rang": await get(guild_id, "nyitas_ping_rang") or "",
            "link": await get(guild_id, "nyitas_link") or "",
            "kod": await get(guild_id, "nyitas_kod") or "",
        }

    async def zaras_alapok(self, guild_id: int) -> dict:
        """A zárás üzenet mentett sablonja (a dashboardon állítható)."""
        get = self.bot.db.get
        return {
            "csatorna": await get(guild_id, "zaras_csatorna") or "",
            "cim": await get(guild_id, "zaras_cim") or ALAP_ZARAS_CIM,
            "szoveg": await get(guild_id, "zaras_szoveg") or ALAP_ZARAS_SZOVEG,
            "szin": await get(guild_id, "zaras_szin") or ALAP_ZARAS_SZIN,
            "ping": await get(guild_id, "zaras_ping", ALAP_ZARAS_PING),
            "ping_rang": await get(guild_id, "zaras_ping_rang") or "",
        }

    # ------------------------------------------------------------------ üzenet felépítése
    @staticmethod
    def embed_keszit(sor) -> discord.Embed:
        """A nyitás beágyazása. A ping nem ebben van, hanem az üzenet szövegében (lásd ping_tartalom)."""
        e = discord.Embed(title=sor["cim"], description=sor["szoveg"], color=szin_ertek(sor["szin"], ZOLD),
                          timestamp=datetime.now(timezone.utc))
        if sor["kod"]:
            e.add_field(name="🔑 Szerverkód", value=f"`{sor['kod']}`")
        e.set_footer(text=f"Nyitotta: {sor['kuldte_nev'] or sor['kuldte']} • #{sor['id']}")
        return e

    @staticmethod
    def zaras_embed(z: dict, sor, lezaro: str) -> discord.Embed:
        e = discord.Embed(title=z["cim"][:100], description=z["szoveg"][:1800], color=szin_ertek(z["szin"], PIROS),
                          timestamp=datetime.now(timezone.utc))
        e.set_footer(text=f"Lezárta: {lezaro} • #{sor['id']}")
        return e

    @staticmethod
    def nezet(link: str | None) -> discord.ui.View | None:
        """A csatlakozás gomb (link gomb, újraindítás után is működik)."""
        if not link:
            return None
        nezet = discord.ui.View(timeout=None)
        nezet.add_item(discord.ui.Button(label="Csatlakozás", emoji="🎮", style=discord.ButtonStyle.link, url=link))
        return nezet

    async def _kuld(self, guild: discord.Guild, sor) -> None:
        """Kiküldi a nyitás üzenetet: a ping a tartalomban, a beágyazás külön. Hibánál NyitasHiba."""
        csatorna = guild.get_channel(sor["csatorna_id"])
        if csatorna is None:
            raise NyitasHiba("A kiválasztott csatorna nem található.")
        tartalom, engedely = ping_tartalom(sor["ping"])
        kwargs = {"content": tartalom, "embed": self.embed_keszit(sor), "allowed_mentions": engedely}
        if (nezet := self.nezet(sor["link"])) is not None:
            kwargs["view"] = nezet
        try:
            uzenet = await csatorna.send(**kwargs)
        except discord.HTTPException:
            raise NyitasHiba("Az üzenetet nem sikerült elküldeni: a botnak nincs jogosultsága írni abba a csatornába.")
        await self.bot.db.execute("UPDATE nyitasok SET uzenet_id=?, statusz='kuldve' WHERE id=?", (uzenet.id, sor["id"]))

    # ------------------------------------------------------------------ nyitás kiküldése / időzítése / lezárása
    async def kozzetesz(
        self, guild: discord.Guild, *, csatorna_id: int, cim: str, szoveg: str, szin: str | None, ping: str,
        link: str, kod: str, kuldte: int, kuldte_nev: str, idopont: int | None = None,
    ) -> tuple[int, bool]:
        """Nyitás üzenet kiküldése (vagy időzítése). Visszaad: (azonosító, azonnal kiment-e). Hibánál NyitasHiba."""
        cim, szoveg, link, kod = cim.strip()[:100], szoveg.strip()[:1800], link.strip(), kod.strip()[:60]
        if not cim:
            raise NyitasHiba("A cím kötelező (legfeljebb 100 karakter).")
        if link and not link_ervenyes(link):
            raise NyitasHiba("A csatlakozási link csak https:// címmel kezdődhet.")
        if guild.get_channel(csatorna_id) is None:
            raise NyitasHiba("A kiválasztott csatorna nem található.")
        most_ = ts()
        azonnal = idopont is None or idopont <= most_ + 20
        azon = await self.bot.db.execute(
            "INSERT INTO nyitasok (guild_id, csatorna_id, cim, szoveg, szin, link, kod, ping, kuldte, kuldte_nev, letrehozva, idopont, statusz) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (guild.id, csatorna_id, cim, szoveg, szin, link or None, kod or None, ping, kuldte, kuldte_nev[:80], most_,
             most_ if azonnal else idopont, "kuldes" if azonnal else "idozitett"))
        if azonnal:
            sor = await self.bot.db.fetchone("SELECT * FROM nyitasok WHERE id=?", (azon,))
            try:
                await self._kuld(guild, sor)
            except NyitasHiba:
                await self.bot.db.execute("UPDATE nyitasok SET statusz='hiba' WHERE id=?", (azon,))
                raise
        return azon, azonnal

    async def lezar(self, guild: discord.Guild, azon: int, lezaro: str = "") -> None:
        """Szerver lezárása: az eredeti nyitás üzenet szürke lesz (ping és gomb nélkül), és új, beágyazott zárás
        üzenet megy ki mellette külön pinggel. Hibánál NyitasHiba."""
        db = self.bot.db
        sor = await db.fetchone("SELECT * FROM nyitasok WHERE id=? AND guild_id=?", (azon, guild.id))
        if not sor:
            raise NyitasHiba("A nyitás nem található.")
        if sor["statusz"] != "kuldve":
            raise NyitasHiba("Csak kiküldött, még nyitva lévő szerver zárható le.")
        z = await self.zaras_alapok(guild.id)
        nyitas_csatorna = guild.get_channel(sor["csatorna_id"])
        zaras_csatorna = guild.get_channel(int(z["csatorna"])) if z["csatorna"].isdigit() else None
        zaras_csatorna = zaras_csatorna or nyitas_csatorna
        if zaras_csatorna is None:
            raise NyitasHiba("A zárás üzenet csatornája nem található.")
        # 1) az eredeti nyitás üzenet lehalkítása
        if nyitas_csatorna is not None and sor["uzenet_id"]:
            try:
                uzenet = await nyitas_csatorna.fetch_message(sor["uzenet_id"])
                e = uzenet.embeds[0] if uzenet.embeds else self.embed_keszit(sor)
                e.color = SZURKE
                e.set_footer(text=f"Lezárva • #{sor['id']}")
                await uzenet.edit(content=None, embed=e, view=None)
            except discord.NotFound:
                pass  # az üzenetet közben törölték, a zárást ettől még kiküldjük
            except discord.HTTPException:
                raise NyitasHiba("A nyitás üzenetet nem sikerült átírni (hiányzó jogosultság).")
        # 2) az új zárás üzenet: a ping a tartalomban, a beágyazás külön
        tartalom, engedely = ping_tartalom(ping_ertek(z["ping"], z["ping_rang"]))
        try:
            uj = await zaras_csatorna.send(content=tartalom, embed=self.zaras_embed(z, sor, lezaro or "automata"), allowed_mentions=engedely)
        except discord.HTTPException:
            raise NyitasHiba("A zárás üzenetet nem sikerült elküldeni: a botnak nincs jogosultsága írni abba a csatornába.")
        await db.execute("UPDATE nyitasok SET statusz='lezarva', lezarva=?, zaras_uzenet_id=? WHERE id=?", (ts(), uj.id, azon))

    async def torol(self, guild: discord.Guild, azon: int) -> None:
        """Időzített (még ki nem ment) nyitás törlése."""
        sor = await self.bot.db.fetchone("SELECT statusz FROM nyitasok WHERE id=? AND guild_id=?", (azon, guild.id))
        if not sor or sor["statusz"] != "idozitett":
            raise NyitasHiba("Csak időzített nyitás törölhető.")
        await self.bot.db.execute("DELETE FROM nyitasok WHERE id=?", (azon,))

    # ------------------------------------------------------------------ időzítő
    @tasks.loop(seconds=30)
    async def idozito(self):
        for sor in await self.bot.db.fetchall(
                "SELECT * FROM nyitasok WHERE statusz='idozitett' AND idopont<=? ORDER BY idopont LIMIT 20", (ts(),)):
            guild = self.bot.get_guild(sor["guild_id"])
            if guild is None:
                continue
            try:
                await self._kuld(guild, sor)
            except NyitasHiba as hiba:
                log.warning("Az időzített nyitás (#%s) nem küldhető ki: %s", sor["id"], hiba)
                await self.bot.db.execute("UPDATE nyitasok SET statusz='hiba' WHERE id=?", (sor["id"],))
            except Exception:
                log.exception("Hiba az időzített nyitásnál (#%s)", sor["id"])
                await self.bot.db.execute("UPDATE nyitasok SET statusz='hiba' WHERE id=?", (sor["id"],))
        for guild in self.bot.guilds:
            try:
                await self.automatikus(guild)
            except NyitasHiba as hiba:
                log.warning("Az automatikus nyitás/zárás nem sikerült (%s): %s", guild.id, hiba)
            except Exception:
                log.exception("Hiba az automatikus nyitásnál/zárásnál (%s)", guild.id)

    # ------------------------------------------------------------------ automatikus nyitás és zárás
    async def automatikus(self, guild: discord.Guild) -> None:
        """A dashboardon beállított napi nyitási és zárási idő szerint magától nyit és zár."""
        db = self.bot.db
        if await db.get(guild.id, "nyitas_auto", "0") != "1":
            return
        most_ = datetime.now(IDOZONA)
        ma = most_.strftime("%Y-%m-%d")
        nyit = await db.get(guild.id, "nyitas_auto_nyit")
        zar = await db.get(guild.id, "nyitas_auto_zar")
        nyitva = await db.fetchone("SELECT * FROM nyitasok WHERE guild_id=? AND statusz='kuldve' ORDER BY id DESC LIMIT 1", (guild.id,))

        if ido_ervenyes(nyit) and await db.get(guild.id, "nyitas_auto_utolso_nyit") != ma:
            napok = {int(x) for x in (await db.get(guild.id, "nyitas_auto_napok") or "0,1,2,3,4,5,6").split(",") if x.strip().isdigit()}
            cel = most_.replace(hour=int(nyit[:2]), minute=int(nyit[3:]), second=0, microsecond=0)
            if most_.weekday() in napok and cel <= most_ < cel + timedelta(minutes=AUTO_TURELEM_PERC):
                await db.set(guild.id, "nyitas_auto_utolso_nyit", ma)  # előbb jelöljük, hogy hiba esetén se ismétlődjön
                a = await self.alapok(guild.id)
                if nyitva is None and a["csatorna"].isdigit():
                    await self.kozzetesz(
                        guild, csatorna_id=int(a["csatorna"]), cim=a["cim"], szoveg=a["szoveg"], szin=a["szin"],
                        ping=ping_ertek(a["ping"], a["ping_rang"]), link=a["link"], kod=a["kod"],
                        kuldte=self.bot.user.id, kuldte_nev="Automata")
                    nyitva = await db.fetchone("SELECT * FROM nyitasok WHERE guild_id=? AND statusz='kuldve' ORDER BY id DESC LIMIT 1", (guild.id,))

        if ido_ervenyes(zar) and nyitva is not None and await db.get(guild.id, "nyitas_auto_utolso_zar") != ma:
            cel = most_.replace(hour=int(zar[:2]), minute=int(zar[3:]), second=0, microsecond=0)
            # Csak olyan nyitást zárunk, ami a mai záróidő előtt indult (így az éjfél utáni zárás is működik).
            if most_ >= cel and nyitva["letrehozva"] < cel.timestamp():
                await db.set(guild.id, "nyitas_auto_utolso_zar", ma)
                await self.lezar(guild, nyitva["id"], "automata")

    @idozito.before_loop
    async def _var(self):
        await self.bot.wait_until_ready()

    # ------------------------------------------------------------------ parancsok
    @app_commands.command(name="nyitas", description="Szerver nyitás üzenet kiküldése (a dashboardon mentett sablonnal).")
    @app_commands.describe(
        csatorna="Ide megy az üzenet (alapból a dashboardon beállított csatorna)",
        kod="Szerverkód (alapból a mentett)", link="Csatlakozási link, https://… (alapból a mentett)",
        uzenet="Egyedi szöveg a sablon helyett")
    @app_commands.guild_only()
    @staff_only()
    async def nyitas_cmd(
        self, i: discord.Interaction, csatorna: discord.TextChannel | None = None, kod: str | None = None,
        link: str | None = None, uzenet: str | None = None,
    ):
        a = await self.alapok(i.guild.id)
        csatorna_id = csatorna.id if csatorna else (int(a["csatorna"]) if a["csatorna"].isdigit() else None)
        if csatorna_id is None:
            return await i.response.send_message(
                "❌ Nincs nyitás csatorna beállítva. Add meg a parancsban, vagy állítsd be a dashboard Nyitás oldalán.", ephemeral=True)
        await i.response.defer(ephemeral=True)
        try:
            azon, _ = await self.kozzetesz(
                i.guild, csatorna_id=csatorna_id, cim=a["cim"], szoveg=uzenet or a["szoveg"], szin=a["szin"],
                ping=ping_ertek(a["ping"], a["ping_rang"]), link=link if link is not None else a["link"],
                kod=kod if kod is not None else a["kod"], kuldte=i.user.id, kuldte_nev=i.user.display_name)
        except NyitasHiba as hiba:
            return await i.followup.send(f"❌ {hiba}", ephemeral=True)
        await i.followup.send(f"✅ A nyitás üzenet kiment (**#{azon}**). Lezárás: `/zaras`.", ephemeral=True)

    @app_commands.command(name="zaras", description="A legutóbbi szerver nyitás lezárása.")
    @app_commands.guild_only()
    @staff_only()
    async def zaras_cmd(self, i: discord.Interaction):
        sor = await self.bot.db.fetchone(
            "SELECT id FROM nyitasok WHERE guild_id=? AND statusz='kuldve' ORDER BY id DESC LIMIT 1", (i.guild.id,))
        if not sor:
            return await i.response.send_message("❌ Nincs nyitva lévő szerver nyitás.", ephemeral=True)
        await i.response.defer(ephemeral=True)
        try:
            await self.lezar(i.guild, sor["id"], i.user.display_name)
        except NyitasHiba as hiba:
            return await i.followup.send(f"❌ {hiba}", ephemeral=True)
        await i.followup.send(f"✅ A(z) **#{sor['id']}** nyitás lezárva, a zárás üzenet kiment.", ephemeral=True)


async def setup(bot):
    await bot.add_cog(Nyitas(bot))
