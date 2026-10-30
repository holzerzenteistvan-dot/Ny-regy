"""Partnerség: ticketben zajló partnerkérés, tagszám alapú ping-javaslat, bizonyíték és Partner Manager döntés.

Menet:
 1. A "Partnerség" típusú ticket megnyílásakor a bot elkéri a másik szerver partnerszövegét.
 2. Ellenőrzi a meghívót (érvényes, soha nem jár le), kiolvassa a tagszámot, és megnézi, hogy az elmúlt
    UJRA_HONAP hónapban volt-e már partnerség ezzel a szerverrel.
 3. A tagszám alapján ping-et javasol (a tagszám → ping szinteket az admin állítja be). A kérelmező elfogadhatja vagy elutasíthatja.
 4. Elfogadás után a bot kiküldi a saját partnerszövegünket; a kérelmező kiteszi, majd képernyőképet küld bizonyítéknak.
 5. A Partner Manager rangot a bot értesíti; a manager elfogadhatja, elutasíthatja vagy üzenhet a ticketben.
 6. Elfogadáskor a partner a beállított csatornába kerül beágyazásban (tagszám, jóváhagyó manager), a ping mellette, az embeden kívül.
"""
import asyncio
import calendar
import logging
import re
from datetime import datetime, timezone

import discord
from discord import app_commands
from discord.ext import commands

from cogs.nyitas import PING_OPCIOK, ping_ertek, ping_tartalom
from util import KEK, PIROS, SARGA, ZOLD, csatorna_kap, most, naplo, ts

log = logging.getLogger("dcbot.partner")

ALAP_KULCS = "partnerseg"  # a partnerségi ticket-típus alapértelmezett kulcsa (a "Partnerség" névből ez lesz)
UJRA_HONAP = 3  # ennyi hónapig nem köthető újra partnerség ugyanazzal a szerverrel
NYITOTT = ("szoveg", "ajanlat", "kep", "manager")
MAX_SZOVEG = 1900  # a saját partnerszövegünk üzenetként megy ki, ezért 2000 alatt kell maradnia

MEGHIVO_RE = re.compile(r"(?:https?://)?(?:www\.)?(?:discord\.gg|discord(?:app)?\.com/invite)/([A-Za-z0-9-]{2,32})", re.IGNORECASE)
PING_VALASZTEK = [("Nincs ping", "nincs"), ("@everyone", "everyone"), ("@here", "here"), ("Egy rang pingelése", "rang")]

GOMBOK = {
    "ajanl_el": ("Elfogadom", "✅", discord.ButtonStyle.success),
    "ajanl_ut": ("Nem kérem a pinget", "❌", discord.ButtonStyle.danger),
    "folytat": ("Folytatás", "▶️", discord.ButtonStyle.primary),
    "mgr_el": ("Elfogadás", "✅", discord.ButtonStyle.success),
    "mgr_ut": ("Elutasítás", "❌", discord.ButtonStyle.danger),
    "mgr_uz": ("Üzenet", "✉️", discord.ButtonStyle.secondary),
}


# ---------------------------------------------------------------- segédfüggvények
def honap_eltolas(ido: datetime, honap: int) -> datetime:
    """Az időpont eltolva a megadott számú hónappal (negatív = vissza); a hónap végén a nap levágódik."""
    osszes = ido.year * 12 + (ido.month - 1) + honap
    ev, ho = divmod(osszes, 12)
    ho += 1
    return ido.replace(year=ev, month=ho, day=min(ido.day, calendar.monthrange(ev, ho)[1]))


def meghivo_kodok(szoveg: str) -> list[str]:
    """A szövegben talált különböző Discord-meghívókódok, a megjelenés sorrendjében."""
    kodok: list[str] = []
    for kod in MEGHIVO_RE.findall(szoveg or ""):
        if kod not in kodok:
            kodok.append(kod)
    return kodok


def tagszam_szoveg(n: int) -> str:
    return f"{n:,}".replace(",", " ")


def ping_cimke(g: discord.Guild, ping: str) -> str:
    """A ping olvasható neve (nem említés, így nem értesít)."""
    if ping == "everyone":
        return "@everyone"
    if ping == "here":
        return "@here"
    if ping.startswith("rang:") and ping[5:].isdigit():
        rang = g.get_role(int(ping[5:]))
        return f"@{rang.name}" if rang else "(törölt rang)"
    return "nincs ping"


class MeghivoHiba(Exception):
    """A meghívó nem megfelelő (a szöveg közvetlenül megjeleníthető). atmeneti: csak Discord-hiba miatt nem sikerült."""

    def __init__(self, uzenet: str, atmeneti: bool = False):
        super().__init__(uzenet)
        self.atmeneti = atmeneti


def nezet(azon: int, *akciok: str) -> discord.ui.View:
    v = discord.ui.View(timeout=None)
    for akcio in akciok:
        v.add_item(PartnerGomb(akcio, azon))
    return v


# ---------------------------------------------------------------- gombok és űrlapok
class PartnerGomb(discord.ui.DynamicItem[discord.ui.Button], template=r"partner:(?P<akcio>[a-z_]+):(?P<id>\d+)"):
    """A partnerség gombjai (újraindítás után is működnek)."""

    def __init__(self, akcio: str, azon: int):
        cimke, emoji, stilus = GOMBOK[akcio]
        super().__init__(discord.ui.Button(label=cimke, emoji=emoji, style=stilus, custom_id=f"partner:{akcio}:{azon}"))
        self.akcio, self.azon = akcio, azon

    @classmethod
    async def from_custom_id(cls, i: discord.Interaction, item: discord.ui.Button, match):
        return cls(match["akcio"], int(match["id"]))

    async def callback(self, i: discord.Interaction):
        await i.client.get_cog("Partner").gomb(i, self.akcio, self.azon)


class ElutasitModal(discord.ui.Modal, title="Partnerség elutasítása"):
    indok = discord.ui.TextInput(label="Az elutasítás oka", style=discord.TextStyle.paragraph, max_length=500,
                                 placeholder="Ezt látja a kérelmező a ticketben.")

    def __init__(self, azon: int):
        super().__init__()
        self.azon = azon

    async def on_submit(self, i: discord.Interaction):
        await i.client.get_cog("Partner").elutasit(i, self.azon, str(self.indok).strip())


class UzenetModal(discord.ui.Modal, title="Üzenet a kérelmezőnek"):
    szoveg = discord.ui.TextInput(label="Üzenet", style=discord.TextStyle.paragraph, max_length=1500,
                                  placeholder="Pl. a képernyőképen nem látszik a ping, kérlek küldj újat.")

    def __init__(self, azon: int):
        super().__init__()
        self.azon = azon

    async def on_submit(self, i: discord.Interaction):
        await i.client.get_cog("Partner").uzen(i, self.azon, str(self.szoveg).strip())


class SajatSzovegModal(discord.ui.Modal, title="Saját partnerszövegünk"):
    szoveg = discord.ui.TextInput(label="A szöveg, amit a partnerek kitesznek", style=discord.TextStyle.paragraph,
                                  max_length=MAX_SZOVEG)

    def __init__(self, jelenlegi: str):
        super().__init__()
        self.szoveg.default = jelenlegi[:MAX_SZOVEG] or None

    async def on_submit(self, i: discord.Interaction):
        await i.client.db.set(i.guild.id, "partner_sajat_szoveg", str(self.szoveg).strip())
        await i.response.send_message("✅ A saját partnerszövegünk elmentve.", ephemeral=True)


# ---------------------------------------------------------------- a modul
class Partner(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self._aktiv: set[int] = set()  # a folyamatban lévő partnerségi ticketek csatornái (az üzenetfigyeléshez)
        self._zarak: dict[int, asyncio.Lock] = {}

    async def cog_load(self):
        self.bot.add_dynamic_items(PartnerGomb)
        sorok = await self.bot.db.fetchall("SELECT csatorna_id FROM partnersegek WHERE statusz IN ('szoveg','ajanlat','kep','manager')")
        self._aktiv = {s["csatorna_id"] for s in sorok}

    def zar(self, azon: int) -> asyncio.Lock:
        return self._zarak.setdefault(azon, asyncio.Lock())

    def aktiv_csatorna(self, csatorna_id: int) -> bool:
        """Folyamatban lévő partnerségi ticket-e (az automod itt nem tiltja a meghívót és a linkeket)."""
        return csatorna_id in self._aktiv

    async def sor(self, azon: int):
        return await self.bot.db.fetchone("SELECT * FROM partnersegek WHERE id=?", (azon,))

    async def sor_csatorna(self, csatorna_id: int):
        return await self.bot.db.fetchone("SELECT * FROM partnersegek WHERE csatorna_id=? ORDER BY id DESC LIMIT 1", (csatorna_id,))

    async def ticket_tipus(self, guild_id: int) -> str:
        return await self.bot.db.get(guild_id, "partner_ticket_tipus") or ALAP_KULCS

    async def manager_rang(self, g: discord.Guild) -> discord.Role | None:
        rang_id = await self.bot.db.get(g.id, "partner_manager_rang")
        return g.get_role(int(rang_id)) if rang_id else None

    async def manager_e(self, tag: discord.Member) -> bool:
        if tag.guild_permissions.administrator:
            return True
        rang = await self.manager_rang(tag.guild)
        return bool(rang and rang in tag.roles)

    async def lezar_allapot(self, sor, statusz: str, **mezok) -> None:
        """Végállapot beírása, és a csatorna kikerül a figyelt csatornák közül."""
        oszlopok = {"statusz": statusz, **mezok}
        await self.bot.db.execute(
            f"UPDATE partnersegek SET {', '.join(f'{k}=?' for k in oszlopok)} WHERE id=?", (*oszlopok.values(), sor["id"]))
        self._aktiv.discard(sor["csatorna_id"])

    # ------------------------------------------------------------------ 1. lépés: ticket megnyitása
    async def inditas(self, g: discord.Guild, csatorna: discord.TextChannel, tag: discord.Member, ticket_id: int) -> None:
        """A ticketrendszer hívja, amikor megnyílt egy partnerségi ticket."""
        azon = await self.bot.db.execute(
            "INSERT INTO partnersegek (guild_id, ticket_id, csatorna_id, user_id, letrehozva) VALUES (?, ?, ?, ?, ?)",
            (g.id, ticket_id, csatorna.id, tag.id, ts()))
        self._aktiv.add(csatorna.id)
        e = discord.Embed(
            title="🤝 Partnerségi kérelem",
            description=(
                "Köszönjük az érdeklődést! Első lépésként **másold be ide a saját szervered partnerszövegét** egyetlen üzenetben.\n\n"
                "• A szövegben pontosan **egy** Discord-meghívó legyen.\n"
                "• A meghívó **soha ne járjon le** (létrehozáskor a lejárat: *Soha*).\n"
                f"• Ugyanazzal a szerverrel **{UJRA_HONAP} hónapon belül** nem köthető új partnerség.\n\n"
                "A bot ellenőrzi a meghívót és a tagszámot, majd javasol egy pinget."),
            color=KEK)
        await csatorna.send(embed=e)
        log.info("Partnerségi ticket indult: %s (#%s)", csatorna.name, azon)

    # ------------------------------------------------------------------ meghívó és előzmények
    async def meghivo_ellenorzes(self, kod: str, g: discord.Guild) -> discord.Invite:
        """Érvényes-e a meghívó, soha nem jár-e le, és kiolvasható-e a tagszám. Hibánál MeghivoHiba."""
        inv = None
        for kiserlet in range(2):  # átmeneti hibánál (429, 5xx) egyszer újrapróbáljuk
            try:
                inv = await self.bot.fetch_invite(kod, with_counts=True, with_expiration=True)
                break
            except discord.NotFound:
                raise MeghivoHiba("Ez a meghívó érvénytelen vagy már lejárt. Hozz létre egy újat, és küldd be újra a szöveget.")
            except discord.HTTPException as hiba:
                log.warning("A meghívó ellenőrzése nem sikerült: kód=%s státusz=%s discord-hibakód=%s szöveg=%s",
                            kod, hiba.status, hiba.code, hiba.text[:200])
                if kiserlet == 0 and (hiba.status == 429 or hiba.status >= 500):
                    await asyncio.sleep(2)
                    continue
                raise MeghivoHiba(
                    f"A meghívót most nem sikerült ellenőrizni (Discord-hiba: {hiba.status}"
                    f"{f'/{hiba.code}' if hiba.code else ''}). Próbáld újra egy perc múlva, ha marad a hiba, szólj egy staff tagnak.", atmeneti=True)
        if inv.guild is None:
            raise MeghivoHiba("Ez a meghívó nem egy szerverre mutat.")
        if inv.guild.id == g.id:
            raise MeghivoHiba("Ez a saját szerverünk meghívója. A partnerszerver meghívóját add meg.")
        if inv.expires_at is not None:
            raise MeghivoHiba(
                f"Ez a meghívó lejár (<t:{int(inv.expires_at.timestamp())}:R>). Hozz létre egy olyat, ahol a lejárat **soha**, "
                "és küldd be újra a szöveget.")
        if inv.approximate_member_count is None:
            raise MeghivoHiba("Ebből a meghívóból nem olvasható ki a szerver tagszáma. Hozz létre egy új meghívót, és próbáld újra.", atmeneti=True)
        return inv

    async def uj_partnerseg_tiltas(self, g: discord.Guild, partner_id: int, sajat_id: int) -> str | None:
        """Ha nem köthető partnerség a szerverrel, a ok szövege; különben None."""
        db = self.bot.db
        hatar = int(honap_eltolas(most(), -UJRA_HONAP).timestamp())
        utolso = await db.fetchone(
            "SELECT dontes_ido FROM partnersegek WHERE guild_id=? AND partner_guild_id=? AND statusz='elfogadva' "
            "AND dontes_ido>=? AND id!=? ORDER BY dontes_ido DESC LIMIT 1", (g.id, partner_id, hatar, sajat_id))
        if utolso:
            ujra = honap_eltolas(datetime.fromtimestamp(utolso["dontes_ido"], timezone.utc), UJRA_HONAP)
            return (f"Ezzel a szerverrel az elmúlt {UJRA_HONAP} hónapban már volt partnerségünk (<t:{utolso['dontes_ido']}:D>). "
                    f"Új partnerség legkorábban <t:{int(ujra.timestamp())}:D> után köthető.")
        folyamatban = await db.fetchall(
            "SELECT csatorna_id FROM partnersegek WHERE guild_id=? AND partner_guild_id=? "
            "AND statusz IN ('ajanlat','kep','manager') AND id!=?", (g.id, partner_id, sajat_id))
        for sor in folyamatban:
            if g.get_channel(sor["csatorna_id"]):
                return f"Ezzel a szerverrel már van folyamatban lévő partnerségi kérelem: <#{sor['csatorna_id']}>."
        return None

    async def javasolt_ping(self, guild_id: int, tagszam: int) -> str:
        """A tagszámhoz tartozó legmagasabb elért szint pingje (üres, ha egy szint sem érhető el)."""
        szint = await self.bot.db.fetchone(
            "SELECT ping FROM partner_szintek WHERE guild_id=? AND min_tagok<=? ORDER BY min_tagok DESC LIMIT 1", (guild_id, tagszam))
        return szint["ping"] if szint else ""

    # ------------------------------------------------------------------ üzenetek figyelése
    @commands.Cog.listener()
    async def on_message(self, uzenet: discord.Message):
        if uzenet.author.bot or uzenet.guild is None or uzenet.channel.id not in self._aktiv:
            return
        sor = await self.sor_csatorna(uzenet.channel.id)
        if not sor or sor["user_id"] != uzenet.author.id:
            return
        async with self.zar(sor["id"]):
            sor = await self.sor(sor["id"])  # a zár alatt újra beolvassuk: közben változhatott
            if sor["statusz"] == "szoveg":
                await self.szoveg_feldolgoz(uzenet, sor)
            elif sor["statusz"] in ("kep", "manager"):
                await self.kep_feldolgoz(uzenet, sor)

    @commands.Cog.listener()
    async def on_guild_channel_delete(self, csatorna):
        """A ticket lezárásakor (a csatorna törlésekor) a félbemaradt kérelem megszakadtnak számít."""
        if csatorna.id in self._aktiv:
            await self.bot.db.execute(
                "UPDATE partnersegek SET statusz='megszakitva' WHERE csatorna_id=? AND statusz IN ('szoveg','ajanlat','kep','manager')",
                (csatorna.id,))
            self._aktiv.discard(csatorna.id)

    # ------------------------------------------------------------------ 2. lépés: a másik szerver szövege
    async def szoveg_feldolgoz(self, uzenet: discord.Message, sor) -> None:
        g, db = uzenet.guild, self.bot.db
        szoveg = uzenet.content.strip()
        if not szoveg:
            return await uzenet.reply("❌ A partnerszöveget szövegként másold be az üzenetbe.", mention_author=False)
        kodok = meghivo_kodok(szoveg)
        if not kodok:
            return await uzenet.reply("❌ Nem találtam Discord-meghívót a szövegben. Tegyél bele egy soha le nem járó meghívót, és küldd be újra.", mention_author=False)
        if len(kodok) > 1:
            return await uzenet.reply("❌ Több különböző meghívó van a szövegben. Hagyd benne csak a szervered meghívóját, és küldd be újra.", mention_author=False)
        try:
            inv = await self.meghivo_ellenorzes(kodok[0], g)
        except MeghivoHiba as hiba:
            return await uzenet.reply(f"❌ {hiba}", mention_author=False)
        if tiltas := await self.uj_partnerseg_tiltas(g, inv.guild.id, sor["id"]):
            return await uzenet.reply(f"❌ {tiltas}", mention_author=False)

        tagszam = inv.approximate_member_count
        ajanlott = await self.javasolt_ping(g.id, tagszam)
        await db.execute(
            "UPDATE partnersegek SET statusz='ajanlat', partner_guild_id=?, partner_nev=?, partner_szoveg=?, invite_kod=?, tagszam=?, ping=? WHERE id=?",
            (inv.guild.id, inv.guild.name[:100], szoveg, kodok[0], tagszam, ajanlott, sor["id"]))

        e = discord.Embed(title="📊 Ping-javaslat", color=SARGA)
        e.add_field(name="Szerver", value=inv.guild.name[:100])
        e.add_field(name="Tagok", value=tagszam_szoveg(tagszam))
        if ajanlott:
            e.add_field(name="Javasolt ping", value=f"**{ping_cimke(g, ajanlott)}**")
            e.description = (f"A szerveredet ellenőriztem: a meghívó rendben van, és **{tagszam_szoveg(tagszam)}** tagod van.\n"
                             f"Ennyi taggal ezt a pinget javasoljuk: **{ping_cimke(g, ajanlott)}**. Elfogadod?")
            gombok = ("ajanl_el", "ajanl_ut")
        else:
            e.add_field(name="Javasolt ping", value="nincs ping")
            e.description = (f"A szerveredet ellenőriztem: a meghívó rendben van, és **{tagszam_szoveg(tagszam)}** tagod van.\n"
                             "Ennyi taggal a partnerség ping nélkül megy ki. Folytatod?")
            gombok = ("folytat",)
        await uzenet.channel.send(f"<@{sor['user_id']}>", embed=e, view=nezet(sor["id"], *gombok),
                                  allowed_mentions=discord.AllowedMentions(users=True))

    # ------------------------------------------------------------------ 3-4. lépés: ping és saját szöveg
    async def ajanlat_valasz(self, i: discord.Interaction, sor, akcio: str) -> None:
        if i.user.id != sor["user_id"]:
            return await i.response.send_message("❌ Ezt csak a kérelmező döntheti el.", ephemeral=True)
        sajat = (await self.bot.db.get(i.guild.id, "partner_sajat_szoveg") or "").strip()
        if not sajat:
            return await i.response.send_message("❌ A saját partnerszövegünk még nincs beállítva. Szólj egy staff tagnak.", ephemeral=True)
        async with self.zar(sor["id"]):
            sor = await self.sor(sor["id"])
            if sor["statusz"] != "ajanlat":
                return await i.response.send_message("❌ Erről már döntöttél.", ephemeral=True)
            ping = "" if akcio == "ajanl_ut" else sor["ping"]
            await self.bot.db.execute("UPDATE partnersegek SET statusz='kep', ping=? WHERE id=?", (ping, sor["id"]))
        cimke = ping_cimke(i.guild, ping)
        e = i.message.embeds[0]
        e.add_field(name="Döntés", value=("Elfogadva" if akcio != "ajanl_ut" else "Ping nélkül folytatjuk"), inline=False)
        await i.response.edit_message(embed=e, view=None)
        # A saját szöveg külön, sima üzenetként megy ki, hogy könnyen másolható legyen.
        await i.channel.send(sajat, allowed_mentions=discord.AllowedMentions.none())
        if ping:
            teendo = f"Tedd ki a fenti szöveget a szervereden **{cimke}** pinggel"
        else:
            teendo = "Tedd ki a fenti szöveget a szervereden (ping nélkül)"
        await i.channel.send(embed=discord.Embed(
            description=f"{teendo}, majd küldj ide egy **képernyőképet** a kitett üzenetről bizonyítékként.", color=KEK))

    # ------------------------------------------------------------------ 5. lépés: képernyőkép és manager értesítése
    async def kep_feldolgoz(self, uzenet: discord.Message, sor) -> None:
        kepek = [a for a in uzenet.attachments if (a.content_type or "").startswith("image/")]
        if not kepek:
            if uzenet.attachments:
                await uzenet.reply("❌ Képernyőképet (képfájlt) várok bizonyítéknak.", mention_author=False)
            return
        g, db = uzenet.guild, self.bot.db
        # A korábbi kezelőpanel gombjait kikapcsoljuk: mindig a legfrissebb bizonyíték az érvényes.
        if sor["panel_uzenet_id"]:
            try:
                regi = await uzenet.channel.fetch_message(sor["panel_uzenet_id"])
                await regi.edit(view=None)
            except discord.HTTPException:
                pass
        rang = await self.manager_rang(g)
        if rang is None and (staff_id := await db.get(g.id, "staffrang")):
            rang = g.get_role(int(staff_id))
        e = discord.Embed(title="🤝 Partnerségi kérelem – jóváhagyásra vár", color=SARGA, timestamp=most())
        e.description = (sor["partner_szoveg"] or "")[:1500]
        e.add_field(name="Szerver", value=sor["partner_nev"] or "–")
        e.add_field(name="Tagok", value=tagszam_szoveg(sor["tagszam"] or 0))
        e.add_field(name="Ping", value=ping_cimke(g, sor["ping"]))
        e.add_field(name="Kérelmező", value=f"<@{sor['user_id']}>")
        e.add_field(name="Meghívó", value=f"https://discord.gg/{sor['invite_kod']}", inline=False)
        e.set_image(url=kepek[0].url)
        panel = await uzenet.channel.send(
            rang.mention if rang else None, embed=e, view=nezet(sor["id"], "mgr_el", "mgr_ut", "mgr_uz"),
            allowed_mentions=discord.AllowedMentions(roles=[rang] if rang else False))
        await db.execute("UPDATE partnersegek SET statusz='manager', panel_uzenet_id=? WHERE id=?", (panel.id, sor["id"]))
        await uzenet.reply("📨 Köszönjük! A bizonyítékot továbbítottam a Partner Managereknek, hamarosan döntenek.", mention_author=False)

    # ------------------------------------------------------------------ gombok
    async def gomb(self, i: discord.Interaction, akcio: str, azon: int) -> None:
        sor = await self.sor(azon)
        if not sor or sor["guild_id"] != i.guild_id:
            return await i.response.send_message("❌ Ez a partnerségi kérelem nem található.", ephemeral=True)
        if akcio in ("ajanl_el", "ajanl_ut", "folytat"):
            return await self.ajanlat_valasz(i, sor, akcio)
        # Innentől a Partner Managerek gombjai.
        if not await self.manager_e(i.user):
            return await i.response.send_message("❌ Ezt csak a Partner Managerek tehetik meg.", ephemeral=True)
        if sor["statusz"] != "manager":
            return await i.response.send_message("❌ Ez a kérelem már le van zárva.", ephemeral=True)
        if akcio == "mgr_ut":
            return await i.response.send_modal(ElutasitModal(azon))
        if akcio == "mgr_uz":
            return await i.response.send_modal(UzenetModal(azon))
        await self.elfogad(i, azon)

    # ------------------------------------------------------------------ manager döntések
    # A döntések a Discord-gombokról és a dashboardról is ugyanezeken a függvényeken mennek át.
    # A manager bármi lehet, aminek van id, mention és display_name attribútuma (Discord-tag vagy a webes admin).
    # Visszatérés: None siker esetén, különben a hiba olvasható szövege.
    async def dontes_elfogad(self, g: discord.Guild, azon: int, manager) -> str | None:
        db = self.bot.db
        csatorna = await csatorna_kap(self.bot, g, "partner_csatorna")
        if csatorna is None:
            return "Nincs beállítva a partnerek csatornája (`/partner csatorna` vagy a dashboard)."
        async with self.zar(azon):
            sor = await self.sor(azon)
            if not sor or sor["guild_id"] != g.id or sor["statusz"] != "manager":
                return "Ez a kérelem már le van zárva."
            # Elfogadás előtt újra megnézzük a meghívót: a partner közben törölhette vagy lejáratóra cserélhette.
            try:
                inv = await self.meghivo_ellenorzes(sor["invite_kod"], g)
            except MeghivoHiba as hiba:
                return f"A partner meghívója időközben megváltozott, ezért most nem fogadható el: {hiba}"
            tagszam = inv.approximate_member_count
            e = discord.Embed(title=f"🤝 {sor['partner_nev']}", description=(sor["partner_szoveg"] or "")[:4000], color=ZOLD, timestamp=most())
            e.add_field(name="👥 Tagok", value=tagszam_szoveg(tagszam))
            e.add_field(name="✅ Jóváhagyta", value=manager.mention)
            e.add_field(name="📩 Kérelmező", value=f"<@{sor['user_id']}>")
            e.set_footer(text="Partnerség")
            link = discord.ui.View()
            link.add_item(discord.ui.Button(label="Csatlakozás", emoji="🔗", url=f"https://discord.gg/{sor['invite_kod']}"))
            tartalom, engedely = ping_tartalom(sor["ping"])  # a ping az üzenet szövegében van, az embeden kívül
            try:
                await csatorna.send(tartalom, embed=e, view=link, allowed_mentions=engedely)
            except discord.HTTPException:
                return f"Nem tudok üzenetet küldeni a {csatorna.mention} csatornába."
            await self.lezar_allapot(sor, "elfogadva", manager_id=manager.id, dontes_ido=ts(), tagszam=tagszam)

        await self._panel_lezar(g, sor, f"✅ Elfogadta {manager.mention}", ZOLD)
        await self._ticketbe(g, sor, content=(
            f"✅ <@{sor['user_id']}> a partnerségedet {manager.mention} jóváhagyta, és kikerült a {csatorna.mention} csatornába. "
            "A ticketet most már lezárhatod."))
        log_embed = discord.Embed(title="Partnerség elfogadva", color=ZOLD, timestamp=most())
        log_embed.add_field(name="Szerver", value=f"{sor['partner_nev']} ({tagszam_szoveg(tagszam)} tag)")
        log_embed.add_field(name="Jóváhagyta", value=manager.mention)
        await naplo(self.bot, g, log_embed)
        return None

    async def dontes_elutasit(self, g: discord.Guild, azon: int, manager, indok: str) -> str | None:
        async with self.zar(azon):
            sor = await self.sor(azon)
            if not sor or sor["guild_id"] != g.id or sor["statusz"] != "manager":
                return "Ez a kérelem már le van zárva."
            await self.lezar_allapot(sor, "elutasitva", manager_id=manager.id, dontes_ido=ts(), indok=indok[:500])
        await self._panel_lezar(g, sor, f"❌ Elutasította {manager.mention}", PIROS)
        e = discord.Embed(title="❌ A partnerségi kérelmet elutasították", description=indok, color=PIROS)
        e.set_footer(text=f"Elutasította: {manager.display_name}")
        await self._ticketbe(g, sor, content=f"<@{sor['user_id']}>", embed=e)
        return None

    async def dontes_uzenet(self, g: discord.Guild, azon: int, manager, szoveg: str) -> str | None:
        sor = await self.sor(azon)
        if not sor or sor["guild_id"] != g.id or sor["statusz"] != "manager":
            return "Ez a kérelem már le van zárva."
        e = discord.Embed(title="✉️ Üzenet a Partner Managertől", description=szoveg[:1500], color=KEK)
        avatar = getattr(getattr(manager, "display_avatar", None), "url", None)
        e.set_author(name=manager.display_name, **({"icon_url": avatar} if avatar else {}))
        e.set_footer(text="Ha új bizonyíték kell, küldj ide egy új képernyőképet.")
        if not await self._ticketbe(g, sor, content=f"<@{sor['user_id']}>", embed=e):
            return "A ticketcsatorna már nem létezik."
        return None

    async def _ticketbe(self, g: discord.Guild, sor, **kwargs) -> bool:
        """Üzenet a kérelem ticketjébe (a kérelmező említése értesít). False, ha a csatorna már nincs meg."""
        csatorna = g.get_channel(sor["csatorna_id"])
        if csatorna is None:
            return False
        try:
            await csatorna.send(allowed_mentions=discord.AllowedMentions(users=True), **kwargs)
        except discord.HTTPException:
            return False
        return True

    async def _panel_lezar(self, g: discord.Guild, sor, dontes: str, szin: discord.Color) -> None:
        """A kezelőpanel gombjainak kikapcsolása és a döntés rávezetése."""
        csatorna = g.get_channel(sor["csatorna_id"])
        if csatorna is None or not sor["panel_uzenet_id"]:
            return
        try:
            panel = await csatorna.fetch_message(sor["panel_uzenet_id"])
            e = panel.embeds[0]
            e.color = szin
            e.add_field(name="Döntés", value=dontes, inline=False)
            await panel.edit(embed=e, view=None)
        except (discord.HTTPException, IndexError):
            pass

    # A Discordos oldali kezelők: jogosultság-ellenőrzés, majd a közös döntésfüggvények.
    async def elfogad(self, i: discord.Interaction, azon: int) -> None:
        await i.response.defer()
        if hiba := await self.dontes_elfogad(i.guild, azon, i.user):
            await i.followup.send(f"❌ {hiba}", ephemeral=True)

    async def elutasit(self, i: discord.Interaction, azon: int, indok: str) -> None:
        if not await self.manager_e(i.user):
            return await i.response.send_message("❌ Ezt csak a Partner Managerek tehetik meg.", ephemeral=True)
        await i.response.defer(ephemeral=True)
        hiba = await self.dontes_elutasit(i.guild, azon, i.user, indok)
        await i.followup.send(f"❌ {hiba}" if hiba else "✅ A kérelmet elutasítottad, a kérelmező értesítést kapott.", ephemeral=True)

    async def uzen(self, i: discord.Interaction, azon: int, szoveg: str) -> None:
        if not await self.manager_e(i.user):
            return await i.response.send_message("❌ Ezt csak a Partner Managerek tehetik meg.", ephemeral=True)
        await i.response.defer(ephemeral=True)
        hiba = await self.dontes_uzenet(i.guild, azon, i.user, szoveg)
        await i.followup.send(f"❌ {hiba}" if hiba else "✅ Az üzenet elment a ticketbe.", ephemeral=True)

    # ------------------------------------------------------------------ telepítés (parancs és dashboard)
    async def telepit(self, g: discord.Guild) -> str:
        """A Partnerség ticket-típus létrehozása (vagy bekapcsolása) és a panel frissítése. Az eredmény olvasható szöveg."""
        from cogs.ticket import MAX_KATEGORIA  # késői import: a ticket modul hívja ezt a modult is
        ticket, db = self.bot.get_cog("Ticket"), self.bot.db
        kulcs = await self.ticket_tipus(g.id)
        kat = await ticket.kategoria(g.id, kulcs)
        if kat is None:
            if len(await ticket.kategoriak(g.id, csak_aktiv=False)) >= MAX_KATEGORIA:
                return f"❌ Legfeljebb {MAX_KATEGORIA} ticket-típus lehet. Törölj egyet a Ticketek oldalon."
            rang = await self.manager_rang(g)
            sorrend = (await db.fetchone("SELECT COALESCE(MAX(sorrend), -1) + 1 AS n FROM ticket_kategoriak WHERE guild_id=?", (g.id,)))["n"]
            await db.execute(
                "INSERT INTO ticket_kategoriak (guild_id, kulcs, nev, emoji, leiras, rang_id, sorrend) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (g.id, kulcs, "Partnerség", "🤝", "Partnerségi kérelem a szerverünkkel.", rang.id if rang else None, sorrend))
            uzenet = "✅ A Partnerség ticket-típus létrejött."
        else:
            await db.execute("UPDATE ticket_kategoriak SET aktiv=1 WHERE id=?", (kat["id"],))
            uzenet = "✅ A Partnerség ticket-típus már létezett, bekapcsoltam."
        uzenet += " A ticket panel frissült." if await ticket.panel_frissit(g) else " Még nincs kihelyezett panel (Ticketek oldal vagy /ticket panel)."
        if not await self.manager_rang(g):
            uzenet += " ⚠️ A Partner Manager rang még nincs beállítva."
        return uzenet

    # ------------------------------------------------------------------ parancsok (admin)
    partner = app_commands.Group(
        name="partner", description="A partnerségi rendszer beállításai.", guild_only=True,
        default_permissions=discord.Permissions(administrator=True),
    )

    @partner.command(name="telepites", description="A Partnerség ticket-típus létrehozása, és a ticket panel frissítése.")
    @app_commands.checks.has_permissions(administrator=True)
    async def telepites(self, i: discord.Interaction):
        await i.response.defer(ephemeral=True)
        await i.followup.send(await self.telepit(i.guild), ephemeral=True)

    @partner.command(name="kezelo_rang", description="A Partner Manager rang beállítása.")
    @app_commands.describe(rang="Ők kapnak értesítést, és ők dönthetnek a partnerségekről")
    @app_commands.checks.has_permissions(administrator=True)
    async def kezelo_rang(self, i: discord.Interaction, rang: discord.Role):
        await self.bot.db.set(i.guild.id, "partner_manager_rang", str(rang.id))
        await i.response.send_message(
            f"✅ Partner Manager rang: {rang.mention}\nA már létező Partnerség ticket-típus kezelő rangját a dashboardon állíthatod át.",
            ephemeral=True, allowed_mentions=discord.AllowedMentions.none())

    @partner.command(name="csatorna", description="A csatorna, ahová az elfogadott partnerségek kerülnek.")
    @app_commands.checks.has_permissions(administrator=True)
    async def csatorna_cmd(self, i: discord.Interaction, csatorna: discord.TextChannel):
        await self.bot.db.set(i.guild.id, "partner_csatorna", str(csatorna.id))
        await i.response.send_message(f"✅ Az elfogadott partnerségek ide kerülnek: {csatorna.mention}", ephemeral=True)

    @partner.command(name="szoveg", description="A saját partnerszövegünk beállítása, amit a partnerek kitesznek.")
    @app_commands.checks.has_permissions(administrator=True)
    async def szoveg_cmd(self, i: discord.Interaction):
        await i.response.send_modal(SajatSzovegModal(await self.bot.db.get(i.guild.id, "partner_sajat_szoveg") or ""))

    @partner.command(name="szint_beallit", description="Ping rendelése egy tagszám-küszöbhöz (a küszöböt elérő szerverek ezt kapják javaslatként).")
    @app_commands.describe(tagok="Legalább ennyi tag kell a szinthez", ping="Milyen pinget javasoljon a bot", rang="Csak 'Egy rang pingelése' esetén")
    @app_commands.choices(ping=[app_commands.Choice(name=nev, value=ertek) for nev, ertek in PING_VALASZTEK])
    @app_commands.checks.has_permissions(administrator=True)
    async def szint_beallit(self, i: discord.Interaction, tagok: app_commands.Range[int, 0, 10_000_000],
                            ping: app_commands.Choice[str], rang: discord.Role | None = None):
        if ping.value == "rang" and rang is None:
            return await i.response.send_message("❌ Rang pingeléséhez add meg a rangot is.", ephemeral=True)
        ertek = ping_ertek(ping.value, str(rang.id) if rang else "")
        await self.bot.db.execute(
            "INSERT INTO partner_szintek (guild_id, min_tagok, ping) VALUES (?, ?, ?) "
            "ON CONFLICT(guild_id, min_tagok) DO UPDATE SET ping=excluded.ping", (i.guild.id, tagok, ertek))
        await i.response.send_message(f"✅ {tagszam_szoveg(tagok)}+ tag → **{ping_cimke(i.guild, ertek)}**", ephemeral=True)

    @partner.command(name="szint_torol", description="Egy tagszám-küszöb törlése.")
    @app_commands.checks.has_permissions(administrator=True)
    async def szint_torol(self, i: discord.Interaction, tagok: app_commands.Range[int, 0, 10_000_000]):
        await self.bot.db.execute("DELETE FROM partner_szintek WHERE guild_id=? AND min_tagok=?", (i.guild.id, tagok))
        await i.response.send_message(f"✅ A(z) {tagszam_szoveg(tagok)} tagos küszöb törölve (ha létezett).", ephemeral=True)

    @partner.command(name="szintek", description="A tagszám → ping szintek listája.")
    @app_commands.checks.has_permissions(administrator=True)
    async def szintek(self, i: discord.Interaction):
        sorok = await self.bot.db.fetchall("SELECT min_tagok, ping FROM partner_szintek WHERE guild_id=? ORDER BY min_tagok", (i.guild.id,))
        if not sorok:
            return await i.response.send_message("Még nincs szint. Adj hozzá egyet: `/partner szint_beallit`.", ephemeral=True)
        leiras = "\n".join(f"**{tagszam_szoveg(s['min_tagok'])}+ tag** → {ping_cimke(i.guild, s['ping'])}" for s in sorok)
        await i.response.send_message(embed=discord.Embed(title="Partner ping szintek", description=leiras, color=KEK), ephemeral=True)


async def setup(bot):
    await bot.add_cog(Partner(bot))
