"""Erős moderáció: spam, linkek, szitokszűrő, tömeges említés, új fiók szűrés, raid mód."""
import re
import time
import unicodedata
from collections import defaultdict, deque
from datetime import timedelta
from urllib.parse import urlsplit

import discord
from discord import app_commands
from discord.ext import commands

from util import KEK, PIROS, SARGA, most, naplo, staff_e, ts

# Alapértékek – szerverenként felülírhatók a /automod beallit paranccsal. A 0 kikapcsolja a szűrőt.
ALAP = {
    "spam_limit": 5,  # ennyi üzenet ...
    "spam_masodperc": 6,  # ... ennyi másodperc alatt = spam
    "ping_limit": 5,  # ennyi említés egy üzenetben = tömeges említés
    "uj_fiok_napok": 3,  # ennyi napnál fiatalabb fiókot kirúgunk
    "raid_limit": 6,  # ennyi belépés ...
    "raid_masodperc": 15,  # ... ennyi másodperc alatt = raid
    "link_szuro": 1,
    "meghivo_szuro": 1,
    "szitok_szuro": 1,
}
NEVEK = {
    "spam_limit": "Spam: üzenetek száma (0 = ki)",
    "spam_masodperc": "Spam: időablak másodpercben",
    "ping_limit": "Tömeges említés: határ (0 = ki)",
    "uj_fiok_napok": "Új fiók szűrő: minimum napok (0 = ki)",
    "raid_limit": "Raid: belépések száma (0 = ki)",
    "raid_masodperc": "Raid: időablak másodpercben",
    "link_szuro": "Linkszűrő (1 = be, 0 = ki)",
    "meghivo_szuro": "Meghívószűrő (1 = be, 0 = ki)",
    "szitok_szuro": "Szitokszűrő (1 = be, 0 = ki)",
}
# Tiltott szavak. Alapértelmezés: szövegrészletként keres (így a ragozott alakokat is megfogja).
# A "=" jellel kezdődő szó csak önálló szóként számít (hogy pl. a "fasza" ne legyen találat).
ALAP_SZAVAK = [
    # magyar szidalmak
    "kurva", "bazdmeg", "bazmeg", "kibaszott", "kibasz", "baszd", "baszod", "baszik", "baszott", "=basz",
    "picsa", "ribanc", "lofasz", "faszom", "faszfej", "faszkalap", "faszszopo", "gecilada", "szarhazi",
    "rohadek", "=fasz", "=geci", "=szar", "=pina", "=nyomorek",
    # megalázó, gyűlölködő kifejezések
    "buzi", "=nigger", "=niggers", "=nigga", "=niggas", "=fag", "=fags", "=retard", "=retarded", "=tranny", "=kys",
    # angol
    "fuck", "bitch", "asshole", "dickhead", "=shit", "=cunt", "=whore", "=slut",
]
# Ezekről a oldalakról szabad linket küldeni (az aldomainek is engedélyezettek, pl. media.tenor.com).
ALAP_DOMAINEK = [
    "tenor.com", "giphy.com", "imgur.com", "gyazo.com", "prnt.sc", "streamable.com", "medal.tv",
    "youtube.com", "youtu.be", "twitch.tv", "spotify.com", "roblox.com", "ro.blox.com",
    "discord.com", "discordapp.com", "discordapp.net",
]
RAID_PERCEK = 10  # az automatikusan bekapcsolt raid mód ennyi perc után lejár
RAID_KEZI = 4_102_444_800  # kézzel bekapcsolt raid mód: 2100-ig tart, amíg ki nem kapcsolják
RAID_OK = "Raid gyanú miatt a szerver ideiglenesen zárva van az új belépők előtt."
RAID_ZARVA = "A szerver jelenleg zárva van az új belépők előtt (raid védelem). Próbáld meg később."

LINK = re.compile(r"(?:https?://|www\.)\S+", re.IGNORECASE)
MEGHIVO = re.compile(r"(?:discord(?:app)?\.com/invite|discord\.gg|dsc\.gg)/\S+", re.IGNORECASE)
LEET = str.maketrans("013457@$", "oieastas")


def normal(szoveg: str) -> str:
    """Kisbetűs, ékezet- és írásjel-mentes, leet-feloldott, ismétlődés nélküli szöveg a szűrőhöz."""
    s = unicodedata.normalize("NFKD", szoveg.lower())
    s = "".join(c for c in s if not unicodedata.combining(c))
    s = s.translate(LEET)
    s = re.sub(r"[^a-z\s]", "", s)
    return re.sub(r"(.)\1+", r"\1", s)


def szo_listabol(nyers: list[str]) -> list[tuple[str, bool]]:
    """Nyers lista -> (normalizált szó, csak önálló szóként számít-e) párok."""
    kesz = []
    for szo in nyers:
        if n := normal(szo.lstrip("=")):
            kesz.append((n, szo.startswith("=")))
    return kesz


def tiltott_szo(szoveg: str, szavak: list[tuple[str, bool]]) -> bool:
    n = normal(szoveg)
    if not n:
        return False
    tokenek = set(n.split())
    kompakt = n.replace(" ", "")  # a "k u r v a" jellegű szóközös kijátszás ellen (csak hosszabb szavaknál)
    for szo, pontos in szavak:
        if pontos:
            if szo in tokenek:
                return True
        elif szo in n or (len(szo) >= 7 and szo in kompakt):
            return True
    return False


def link_host(link: str) -> str:
    if not re.match(r"https?://", link, re.IGNORECASE):
        link = "http://" + link
    try:
        return (urlsplit(link).hostname or "").lower().rstrip(".")
    except ValueError:
        return ""


def tiltott_link(szoveg: str, domainek) -> bool:
    """Igaz, ha az üzenetben van olyan link, ami nem az engedélyezett oldalakra mutat."""
    return any(
        not any(host == d or host.endswith("." + d) for d in domainek)
        for host in (link_host(l) for l in LINK.findall(szoveg))
    )


def domain_tiszta(szoveg: str) -> str | None:
    s = re.sub(r"^https?://", "", szoveg.strip().lower()).split("/")[0].split("?")[0].removeprefix("www.")
    return s if re.fullmatch(r"[a-z0-9-]+(?:\.[a-z0-9-]+)+", s) else None


class AutoMod(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self._cache: dict[int, dict] = {}
        # A spam-számláló csak másodperceket él meg, ezért elég a memória. A belépések és a raid mód állapota
        # viszont tartósan az adatbázisban van (belepesek tábla, automod_raid_vege beállítás).
        self._uzenetek = defaultdict(lambda: deque(maxlen=20))

    # ------------------------------------------------------------------ beállítások
    async def cfg(self, guild_id: int) -> dict:
        if (c := self._cache.get(guild_id)) is not None:
            return c
        sorok = await self.bot.db.fetchall(
            "SELECT kulcs, ertek FROM beallitasok WHERE guild_id=? AND kulcs LIKE 'automod\\_%' ESCAPE '\\'",
            (guild_id,),
        )
        nyers = {s["kulcs"][len("automod_"):]: s["ertek"] for s in sorok}
        c = {k: int(nyers.get(k, v)) for k, v in ALAP.items()}
        c["kivetel"] = {int(x) for x in nyers.get("kivetel", "").split(",") if x}
        szavak = [x for x in nyers["szavak"].split("\n") if x] if "szavak" in nyers else ALAP_SZAVAK
        c["szavak"] = szo_listabol(szavak)
        domainek = [x for x in nyers["domainek"].split("\n") if x] if "domainek" in nyers else ALAP_DOMAINEK
        c["domainek"] = set(domainek)
        self._cache[guild_id] = c
        return c

    async def _ment(self, guild_id: int, kulcs: str, ertek: str):
        await self.bot.db.set(guild_id, f"automod_{kulcs}", ertek)
        self._cache.pop(guild_id, None)

    async def _szavak_nyers(self, guild_id: int) -> list[str]:
        ertek = await self.bot.db.get(guild_id, "automod_szavak")
        if ertek is None:
            return list(ALAP_SZAVAK)
        return [s for s in ertek.split("\n") if s]

    async def _domainek_nyers(self, guild_id: int) -> list[str]:
        ertek = await self.bot.db.get(guild_id, "automod_domainek")
        if ertek is None:
            return list(ALAP_DOMAINEK)
        return [s for s in ertek.split("\n") if s]

    async def raid_vege(self, guild_id: int) -> int:
        """A raid mód lejáratának unix ideje (0 = nincs raid mód). Újraindítás után is megmarad."""
        return int(await self.bot.db.get(guild_id, "automod_raid_vege", 0))

    async def raid_aktiv(self, guild_id: int) -> bool:
        return await self.raid_vege(guild_id) > ts()

    # ------------------------------------------------------------------ belépés: raid és új fiók
    async def belepes_ellenorzes(self, tag: discord.Member, belepes_id: int) -> bool:
        """True-t ad vissza, ha a tagot kirúgtuk (ilyenkor a belépési modul nem köszönti).

        A belepes_id a belepesek tábla frissen rögzített sora: a raid-érzékelés is ebből számol,
        ezért a számlálás újraindítás után is helyes.
        """
        g, db = tag.guild, self.bot.db
        cfg = await self.cfg(g.id)

        if cfg["raid_limit"]:
            sorok = await db.fetchall(
                "SELECT id, user_id FROM belepesek WHERE guild_id=? AND belepett>=? AND eredmeny='maradt'",
                (g.id, ts() - cfg["raid_masodperc"]),
            )
            if len(sorok) >= cfg["raid_limit"] and not await self.raid_aktiv(g.id):
                await db.set(g.id, "automod_raid_vege", str(ts() + RAID_PERCEK * 60))
                await self._riaszt(g, len(sorok))
                for sor in sorok:
                    if gyanus := g.get_member(sor["user_id"]):
                        await self._kidob(gyanus, RAID_OK, sor["id"])
                return True

        if await self.raid_aktiv(g.id):
            await self._kidob(tag, RAID_ZARVA, belepes_id)
            return True

        if cfg["uj_fiok_napok"] and (most() - tag.created_at) < timedelta(days=cfg["uj_fiok_napok"]):
            await self._kidob(
                tag, f"A Discord-fiókod túl új (minimum {cfg['uj_fiok_napok']} napos fiók szükséges). Próbáld meg később.",
                belepes_id,
            )
            return True
        return False

    async def _kidob(self, tag: discord.Member, ok: str, belepes_id: int):
        try:
            await tag.send(f"Nem csatlakozhatsz a(z) **{tag.guild.name}** szerverhez: {ok}")
        except discord.HTTPException:
            pass
        try:
            await tag.kick(reason=f"Automatikus moderáció: {ok}")
        except discord.HTTPException:
            return
        await self.bot.db.execute("UPDATE belepesek SET eredmeny='kirugva', ok=? WHERE id=?", (ok, belepes_id))
        e = discord.Embed(title="Automatikus kirúgás belépéskor", description=ok, color=SARGA, timestamp=most())
        e.add_field(name="Tag", value=f"{tag.mention} (`{tag.id}`)")
        e.add_field(name="Fiók létrehozva", value=discord.utils.format_dt(tag.created_at, "R"))
        await naplo(self.bot, tag.guild, e)

    async def _riaszt(self, guild: discord.Guild, darab: int):
        rang_id = await self.bot.db.get(guild.id, "staffrang")
        ping = f"<@&{rang_id}> " if rang_id else ""
        e = discord.Embed(
            title="🚨 Raid mód bekapcsolva",
            description=f"{darab} új tag lépett be rövid idő alatt. Az új belépőket {RAID_PERCEK} percig automatikusan "
                        "kirúgom. Kikapcsolás: `/automod raid`.",
            color=PIROS, timestamp=most(),
        )
        await naplo(self.bot, guild, e, content=ping)

    # ------------------------------------------------------------------ üzenetszűrés
    def _spam_e(self, uzenet: discord.Message, cfg: dict) -> bool:
        kulcs = (uzenet.guild.id, uzenet.author.id)
        ido = time.monotonic()
        q = self._uzenetek[kulcs]
        q.append((ido, uzenet.content))
        friss = [x for x in q if ido - x[0] <= cfg["spam_masodperc"]]
        ismetlodo = uzenet.content and sum(1 for x in friss if x[1] == uzenet.content) >= 3
        if len(friss) >= cfg["spam_limit"] or ismetlodo:
            self._uzenetek.pop(kulcs, None)
            return True
        return False

    async def _szabalysertes(self, uzenet: discord.Message, ok: str, torol_tobbet: int = 0):
        try:
            if torol_tobbet:
                await uzenet.channel.purge(
                    limit=30,
                    check=lambda m: m.author.id == uzenet.author.id,
                    after=most() - timedelta(seconds=torol_tobbet),
                )
            await uzenet.delete()
        except discord.HTTPException:
            pass
        szankcio = self.bot.get_cog("Szankcio")
        ugy, eszkalacio = await szankcio.warn(
            uzenet.guild, uzenet.author, uzenet.guild.me, f"Automatikus moderáció: {ok}"
        )
        szoveg = f"{uzenet.author.mention}, figyelmeztetést kaptál ({ok}). Ügy: **#{ugy}**"
        if eszkalacio:
            szoveg += f"\n⚠️ {eszkalacio}"
        try:
            await uzenet.channel.send(szoveg, delete_after=10)
        except discord.HTTPException:
            pass

    @commands.Cog.listener()
    async def on_message(self, uzenet: discord.Message):
        if uzenet.author.bot or uzenet.guild is None or not isinstance(uzenet.author, discord.Member):
            return
        cfg = await self.cfg(uzenet.guild.id)
        if uzenet.channel.id in cfg["kivetel"] or await staff_e(self.bot, uzenet.author):
            return
        szoveg = uzenet.content
        # A partnerségi ticketben a partner szövege meghívót és linkeket tartalmaz, ezeket itt nem töröljük.
        partner = self.bot.get_cog("Partner")
        partner_ticket = bool(partner and partner.aktiv_csatorna(uzenet.channel.id))

        if cfg["spam_limit"] and self._spam_e(uzenet, cfg):
            return await self._szabalysertes(uzenet, "spam", torol_tobbet=cfg["spam_masodperc"] + 5)

        if cfg["ping_limit"] and (
            uzenet.mention_everyone or len(set(uzenet.mentions)) + len(uzenet.role_mentions) >= cfg["ping_limit"]
        ):
            return await self._szabalysertes(uzenet, "tömeges említés")

        if cfg["meghivo_szuro"] and not partner_ticket and MEGHIVO.search(szoveg):
            return await self._szabalysertes(uzenet, "Discord-meghívó küldése")

        if cfg["link_szuro"] and not partner_ticket and tiltott_link(szoveg, cfg["domainek"]):
            return await self._szabalysertes(uzenet, "nem engedélyezett link")

        if cfg["szitok_szuro"] and cfg["szavak"] and tiltott_szo(szoveg, cfg["szavak"]):
            return await self._szabalysertes(uzenet, "tiltott kifejezés")

    # ------------------------------------------------------------------ parancsok
    automod = app_commands.Group(
        name="automod",
        description="Az erős moderáció beállításai.",
        guild_only=True,
        default_permissions=discord.Permissions(administrator=True),
    )

    @automod.command(name="allapot", description="Az automatikus moderáció jelenlegi beállításai.")
    @app_commands.checks.has_permissions(administrator=True)
    async def allapot(self, i: discord.Interaction):
        cfg = await self.cfg(i.guild.id)
        e = discord.Embed(title="Erős moderáció – állapot", color=KEK)
        for kulcs, nev in NEVEK.items():
            e.add_field(name=nev, value=f"`{cfg[kulcs]}`")
        e.add_field(name="Tiltott szavak", value=f"{len(cfg['szavak'])} db (`/automod szo_lista`)")
        e.add_field(name="Engedélyezett linkek", value=f"{len(cfg['domainek'])} oldal (`/automod link_lista`)")
        raid_vege = await self.raid_vege(i.guild.id)
        if raid_vege <= ts():
            raid = "kikapcsolva"
        else:
            raid = "🚨 aktív, kézi kikapcsolásig" if raid_vege >= RAID_KEZI else f"🚨 aktív, lejár: <t:{raid_vege}:R>"
        e.add_field(name="Raid mód", value=raid)
        e.add_field(
            name="Kivételcsatornák", value=" ".join(f"<#{c}>" for c in cfg["kivetel"]) or "nincs", inline=False
        )
        e.set_footer(text="A staff tagok és a kivételcsatornák mentesülnek a szűrők alól.")
        await i.response.send_message(embed=e, ephemeral=True)

    @automod.command(name="beallit", description="Egy szűrő értékének módosítása.")
    @app_commands.describe(beallitas="Melyik értéket módosítod", ertek="Az új érték (0 = kikapcsolva)")
    @app_commands.choices(beallitas=[app_commands.Choice(name=n, value=k) for k, n in NEVEK.items()])
    @app_commands.checks.has_permissions(administrator=True)
    async def beallit(self, i: discord.Interaction, beallitas: app_commands.Choice[str], ertek: app_commands.Range[int, 0, 3600]):
        await self._ment(i.guild.id, beallitas.value, str(ertek))
        await i.response.send_message(f"✅ **{beallitas.name}** → `{ertek}`", ephemeral=True)

    @automod.command(name="szo_hozzaad", description="Tiltott szó vagy kifejezés hozzáadása.")
    @app_commands.describe(szo="A tiltott szó. Ha = jellel kezded (pl. =fasz), csak önálló szóként számít találatnak")
    @app_commands.checks.has_permissions(administrator=True)
    async def szo_hozzaad(self, i: discord.Interaction, szo: app_commands.Range[str, 3, 50]):
        szavak = await self._szavak_nyers(i.guild.id)
        if len(normal(szo.lstrip("="))) < 3:
            return await i.response.send_message("❌ A szónak legalább 3 betűt kell tartalmaznia.", ephemeral=True)
        if szo.lower() in szavak:
            return await i.response.send_message("❌ Ez a szó már szerepel a listán.", ephemeral=True)
        await self._ment(i.guild.id, "szavak", "\n".join(szavak + [szo.lower()]))
        await i.response.send_message("✅ A szó hozzáadva a tiltólistához.", ephemeral=True)

    @automod.command(name="szo_torol", description="Tiltott szó eltávolítása a listáról.")
    @app_commands.checks.has_permissions(administrator=True)
    async def szo_torol(self, i: discord.Interaction, szo: app_commands.Range[str, 3, 50]):
        szavak = await self._szavak_nyers(i.guild.id)
        if szo.lower() not in szavak:
            return await i.response.send_message("❌ Ez a szó nincs a listán.", ephemeral=True)
        szavak.remove(szo.lower())
        await self._ment(i.guild.id, "szavak", "\n".join(szavak))
        await i.response.send_message("✅ A szó eltávolítva a tiltólistáról.", ephemeral=True)

    @automod.command(name="szo_lista", description="A tiltott szavak listája (csak neked látszik).")
    @app_commands.checks.has_permissions(administrator=True)
    async def szo_lista(self, i: discord.Interaction):
        szavak = await self._szavak_nyers(i.guild.id)
        szoveg = " ".join(f"||{s}||" for s in szavak) or "A lista üres."
        await i.response.send_message(f"**Tiltott szavak ({len(szavak)} db):**\n{szoveg}"[:1900], ephemeral=True)

    @automod.command(name="link_engedelyez", description="Oldal engedélyezése vagy tiltása a linkszűrőben (kapcsoló).")
    @app_commands.describe(oldal="Pl. tenor.com – ha már engedélyezett, törli a listáról; ha nem, hozzáadja")
    @app_commands.checks.has_permissions(administrator=True)
    async def link_engedelyez(self, i: discord.Interaction, oldal: app_commands.Range[str, 4, 100]):
        domain = domain_tiszta(oldal)
        if domain is None:
            return await i.response.send_message("❌ Érvénytelen oldal. Példa: `tenor.com`", ephemeral=True)
        domainek = await self._domainek_nyers(i.guild.id)
        if domain in domainek:
            domainek.remove(domain)
            uzenet = f"✅ **{domain}** többé nem engedélyezett."
        else:
            domainek.append(domain)
            uzenet = f"✅ **{domain}** (és az aldomainjei) engedélyezve."
        await self._ment(i.guild.id, "domainek", "\n".join(domainek))
        await i.response.send_message(uzenet, ephemeral=True)

    @automod.command(name="link_lista", description="A linkszűrő által engedélyezett oldalak.")
    @app_commands.checks.has_permissions(administrator=True)
    async def link_lista(self, i: discord.Interaction):
        domainek = await self._domainek_nyers(i.guild.id)
        szoveg = "\n".join(f"• `{d}`" for d in sorted(domainek)) or "Nincs engedélyezett oldal."
        await i.response.send_message(f"**Engedélyezett oldalak ({len(domainek)} db):**\n{szoveg}"[:1900], ephemeral=True)

    @automod.command(name="kivetel", description="Csatorna felvétele/eltávolítása a moderáció kivételei közül.")
    @app_commands.describe(csatorna="Ebben a csatornában nem működnek a szűrők")
    @app_commands.checks.has_permissions(administrator=True)
    async def kivetel(self, i: discord.Interaction, csatorna: discord.TextChannel):
        cfg = await self.cfg(i.guild.id)
        csatornak = set(cfg["kivetel"])
        if csatorna.id in csatornak:
            csatornak.discard(csatorna.id)
            uzenet = f"✅ {csatorna.mention} újra moderálva van."
        else:
            csatornak.add(csatorna.id)
            uzenet = f"✅ {csatorna.mention} kivétel lett: itt nem működnek a szűrők."
        await self._ment(i.guild.id, "kivetel", ",".join(map(str, csatornak)))
        await i.response.send_message(uzenet, ephemeral=True)

    @automod.command(name="raid", description="Raid mód kézi be- vagy kikapcsolása.")
    @app_commands.describe(bekapcsolva="Igen: az új belépőket kirúgja a bot. Nem: kikapcsolja a raid módot.")
    @app_commands.checks.has_permissions(administrator=True)
    async def raid_cmd(self, i: discord.Interaction, bekapcsolva: bool):
        await self.bot.db.set(i.guild.id, "automod_raid_vege", str(RAID_KEZI if bekapcsolva else 0))
        if bekapcsolva:
            szoveg = "🚨 Raid mód **bekapcsolva**. Az új belépők kirúgásra kerülnek, amíg ki nem kapcsolod."
        else:
            szoveg = "✅ Raid mód **kikapcsolva**."
        await i.response.send_message(szoveg, ephemeral=True)


async def setup(bot):
    await bot.add_cog(AutoMod(bot))
