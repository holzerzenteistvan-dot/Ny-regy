"""Statisztika: aktív tagok, üzenetek, ticket idők, szolgálati idők, automatikus heti és havi riport."""
from collections import Counter
from datetime import datetime, timedelta

import discord
from discord import app_commands
from discord.ext import commands, tasks

from util import (IDOZONA, KEK, csatorna_kap, elozo_honap_kezdete, het_kezdete, honap_kezdete, ido_szoveg, iso,
                  staff_only)


def nap_kulcs(ido: datetime) -> str:
    return ido.astimezone(IDOZONA).strftime("%Y-%m-%d")


def atlag_szoveg(mp: float | None) -> str:
    return ido_szoveg(mp) if mp is not None else "–"


class Statisztika(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        # Az események memóriában gyűlnek, és percenként egyben kerülnek az adatbázisba.
        self._uzenet = Counter()  # (guild, nap, user)
        self._csatorna = Counter()  # (guild, nap, csatorna)
        self._tagok = Counter()  # (guild, nap, "belepett" | "kilepett")

    async def cog_load(self):
        self.mentes.start()
        self.automata.start()

    async def cog_unload(self):
        self.mentes.cancel()
        self.automata.cancel()
        await self.ment_most()

    # ------------------------------------------------------------------ gyűjtés
    @commands.Cog.listener()
    async def on_message(self, uzenet: discord.Message):
        if uzenet.author.bot or uzenet.guild is None:
            return
        nap = nap_kulcs(uzenet.created_at)
        self._uzenet[(uzenet.guild.id, nap, uzenet.author.id)] += 1
        self._csatorna[(uzenet.guild.id, nap, uzenet.channel.id)] += 1

    @commands.Cog.listener()
    async def on_member_join(self, tag: discord.Member):
        if not tag.bot:
            self._tagok[(tag.guild.id, nap_kulcs(datetime.now(IDOZONA)), "belepett")] += 1

    @commands.Cog.listener()
    async def on_member_remove(self, tag: discord.Member):
        if not tag.bot:
            self._tagok[(tag.guild.id, nap_kulcs(datetime.now(IDOZONA)), "kilepett")] += 1

    async def ment_most(self):
        uzenet, csatorna, tagok = self._uzenet, self._csatorna, self._tagok
        self._uzenet, self._csatorna, self._tagok = Counter(), Counter(), Counter()
        db = self.bot.db
        await db.executemany(
            "INSERT INTO napi_aktivitas (guild_id, nap, user_id, uzenetek) VALUES (?, ?, ?, ?) "
            "ON CONFLICT(guild_id, nap, user_id) DO UPDATE SET uzenetek=uzenetek+excluded.uzenetek",
            [(g, n, u, db_) for (g, n, u), db_ in uzenet.items()],
        )
        await db.executemany(
            "INSERT INTO napi_csatorna (guild_id, nap, csatorna_id, uzenetek) VALUES (?, ?, ?, ?) "
            "ON CONFLICT(guild_id, nap, csatorna_id) DO UPDATE SET uzenetek=uzenetek+excluded.uzenetek",
            [(g, n, c, db_) for (g, n, c), db_ in csatorna.items()],
        )
        for (g, n, mit), db_ in tagok.items():
            await db.execute(
                f"INSERT INTO napi_tagok (guild_id, nap, {mit}) VALUES (?, ?, ?) "
                f"ON CONFLICT(guild_id, nap) DO UPDATE SET {mit}={mit}+excluded.{mit}",
                (g, n, db_),
            )

    @tasks.loop(minutes=1)
    async def mentes(self):
        await self.ment_most()

    # ------------------------------------------------------------------ riportok
    async def szerver_embed(self, guild: discord.Guild, tol: datetime, ig: datetime, cim: str) -> discord.Embed:
        """Szerverstatisztika a [tol, ig) időszakra."""
        await self.ment_most()
        db = self.bot.db
        t, i_ = nap_kulcs(tol), nap_kulcs(ig)
        arg = (guild.id, t, i_)
        osszes = await db.fetchone(
            "SELECT COALESCE(SUM(uzenetek), 0) AS db, COUNT(DISTINCT user_id) AS aktiv FROM napi_aktivitas "
            "WHERE guild_id=? AND nap>=? AND nap<?", arg,
        )
        tagok = await db.fetchone(
            "SELECT COALESCE(SUM(belepett), 0) AS be, COALESCE(SUM(kilepett), 0) AS ki FROM napi_tagok "
            "WHERE guild_id=? AND nap>=? AND nap<?", arg,
        )
        top_tagok = await db.fetchall(
            "SELECT user_id, SUM(uzenetek) AS db FROM napi_aktivitas WHERE guild_id=? AND nap>=? AND nap<? "
            "GROUP BY user_id ORDER BY db DESC LIMIT 5", arg,
        )
        top_csatornak = await db.fetchall(
            "SELECT csatorna_id, SUM(uzenetek) AS db FROM napi_csatorna WHERE guild_id=? AND nap>=? AND nap<? "
            "GROUP BY csatorna_id ORDER BY db DESC LIMIT 5", arg,
        )
        e = discord.Embed(title=cim, color=KEK, timestamp=datetime.now(IDOZONA))
        e.add_field(name="💬 Üzenetek", value=f"{osszes['db']:,}".replace(",", " "))
        e.add_field(name="🧑‍🤝‍🧑 Aktív tagok", value=str(osszes["aktiv"]))
        e.add_field(name="👥 Tagok száma", value=str(guild.member_count))
        e.add_field(name="📥 Csatlakozott", value=str(tagok["be"]))
        e.add_field(name="📤 Kilépett", value=str(tagok["ki"]))
        e.add_field(name="📈 Változás", value=f"{tagok['be'] - tagok['ki']:+d}")
        if top_tagok:
            e.add_field(
                name="Legaktívabb tagok",
                value="\n".join(f"**{n}.** <@{s['user_id']}> • {s['db']}" for n, s in enumerate(top_tagok, 1)),
            )
        if top_csatornak:
            e.add_field(
                name="Legaktívabb csatornák",
                value="\n".join(f"**{n}.** <#{s['csatorna_id']}> • {s['db']}" for n, s in enumerate(top_csatornak, 1)),
            )
        return e

    async def ticket_embed(self, guild: discord.Guild, tol: datetime, ig: datetime, cim: str) -> discord.Embed:
        db = self.bot.db
        arg = (guild.id, iso(tol), iso(ig))
        nyitott = await db.fetchone(
            "SELECT COUNT(*) AS db FROM ticketek WHERE guild_id=? AND letrehozva>=? AND letrehozva<?", arg
        )
        lezart = await db.fetchone(
            "SELECT COUNT(*) AS db, AVG(ertekeles) AS ertek, "
            "AVG((julianday(lezarva) - julianday(letrehozva)) * 86400) AS lezaras "
            "FROM ticketek WHERE guild_id=? AND lezarva>=? AND lezarva<?", arg,
        )
        atvetel = await db.fetchone(
            "SELECT AVG((julianday(atvetel_ido) - julianday(letrehozva)) * 86400) AS atvetel FROM ticketek "
            "WHERE guild_id=? AND atvetel_ido>=? AND atvetel_ido<?", arg,
        )
        folyamatban = await db.fetchone("SELECT COUNT(*) AS db FROM ticketek WHERE guild_id=? AND nyitva=1", (guild.id,))
        top = await db.fetchall(
            "SELECT atvette, COUNT(*) AS db FROM ticketek WHERE guild_id=? AND atvette IS NOT NULL "
            "AND letrehozva>=? AND letrehozva<? GROUP BY atvette ORDER BY db DESC LIMIT 5", arg,
        )
        e = discord.Embed(title=cim, color=KEK, timestamp=datetime.now(IDOZONA))
        e.add_field(name="🎫 Megnyitott", value=str(nyitott["db"]))
        e.add_field(name="🔒 Lezárt", value=str(lezart["db"]))
        e.add_field(name="📂 Jelenleg nyitva", value=str(folyamatban["db"]))
        e.add_field(name="⏱️ Átlagos átvételi idő", value=atlag_szoveg(atvetel["atvetel"]))
        e.add_field(name="🕓 Átlagos lezárási idő", value=atlag_szoveg(lezart["lezaras"]))
        e.add_field(name="⭐ Átlagos értékelés", value=f"{lezart['ertek']:.2f} / 5" if lezart["ertek"] else "–")
        if top:
            e.add_field(
                name="Legtöbb átvett ticket",
                value="\n".join(f"**{n}.** <@{s['atvette']}> • {s['db']}" for n, s in enumerate(top, 1)),
                inline=False,
            )
        return e

    async def shift_embed(self, guild: discord.Guild, tol: datetime, ig: datetime, cim: str) -> discord.Embed:
        sorok = await self.bot.get_cog("Shift").ranglista(guild.id, tol.timestamp(), ig.timestamp(), limit=15)
        e = discord.Embed(title=cim, color=KEK, timestamp=datetime.now(IDOZONA))
        if not sorok:
            e.description = "Ebben az időszakban nem volt szolgálati idő."
        else:
            osszes = sum(s["mp"] for s in sorok)
            e.description = "\n".join(
                f"**{n}.** <@{s['user_id']}> • {ido_szoveg(s['mp'])}" for n, s in enumerate(sorok, 1)
            )
            e.set_footer(text=f"Összesen: {ido_szoveg(osszes)} • {len(sorok)} fő")
        return e

    async def teljes_riport(self, guild: discord.Guild, tol: datetime, ig: datetime, nev: str) -> list[discord.Embed]:
        veg = ig - timedelta(seconds=1)
        idoszak = f"{tol.astimezone(IDOZONA):%Y.%m.%d.} – {veg.astimezone(IDOZONA):%Y.%m.%d.}"
        return [
            await self.szerver_embed(guild, tol, ig, f"📊 {nev} riport – {idoszak}"),
            await self.ticket_embed(guild, tol, ig, "🎫 Ticketek"),
            await self.shift_embed(guild, tol, ig, "🕒 Szolgálati idők"),
        ]

    # ------------------------------------------------------------------ automatikus riport
    @tasks.loop(hours=1)
    async def automata(self):
        most_ = datetime.now(IDOZONA)
        if most_.hour < 8:
            return
        db = self.bot.db
        for guild in self.bot.guilds:
            csatorna = await csatorna_kap(self.bot, guild, "riport_csatorna")
            if csatorna is None:
                continue
            if most_.weekday() == 0 and await db.get(guild.id, "riport_het_utolso") != nap_kulcs(most_):
                await db.set(guild.id, "riport_het_utolso", nap_kulcs(most_))
                ig = het_kezdete()
                await self._kuld(csatorna, await self.teljes_riport(guild, ig - timedelta(days=7), ig, "Heti"))
            if most_.day == 1 and await db.get(guild.id, "riport_ho_utolso") != most_.strftime("%Y-%m"):
                await db.set(guild.id, "riport_ho_utolso", most_.strftime("%Y-%m"))
                await self._kuld(csatorna, await self.teljes_riport(guild, elozo_honap_kezdete(), honap_kezdete(), "Havi"))

    async def _kuld(self, csatorna: discord.TextChannel, embedek: list[discord.Embed]):
        try:
            await csatorna.send(embeds=embedek)
        except discord.HTTPException:
            pass

    @mentes.before_loop
    @automata.before_loop
    async def _var(self):
        await self.bot.wait_until_ready()

    # ------------------------------------------------------------------ parancsok
    stats = app_commands.Group(name="stats", description="Szerver- és staffstatisztikák.", guild_only=True)

    @staticmethod
    def _idoszak(napok: int) -> tuple[datetime, datetime]:
        ma = datetime.now(IDOZONA).replace(hour=0, minute=0, second=0, microsecond=0)
        return ma - timedelta(days=napok - 1), ma + timedelta(days=1)

    @stats.command(name="szerver", description="Aktív tagok, üzenetek, csatlakozások az elmúlt napokban.")
    @app_commands.describe(napok="Hány napot nézzünk (1–90)")
    @staff_only()
    async def szerver(self, i: discord.Interaction, napok: app_commands.Range[int, 1, 90] = 7):
        tol, ig = self._idoszak(napok)
        await i.response.defer(ephemeral=True)
        await i.followup.send(embed=await self.szerver_embed(i.guild, tol, ig, f"📊 Szerverstatisztika – elmúlt {napok} nap"), ephemeral=True)

    @stats.command(name="ticketek", description="Ticketek száma, átvételi és lezárási idők, értékelések.")
    @app_commands.describe(napok="Hány napot nézzünk (1–90)")
    @staff_only()
    async def ticketek(self, i: discord.Interaction, napok: app_commands.Range[int, 1, 90] = 30):
        tol, ig = self._idoszak(napok)
        await i.response.defer(ephemeral=True)
        await i.followup.send(embed=await self.ticket_embed(i.guild, tol, ig, f"🎫 Ticket statisztika – elmúlt {napok} nap"), ephemeral=True)

    @stats.command(name="shiftek", description="Szolgálati idők összesítése.")
    @app_commands.describe(napok="Hány napot nézzünk (1–90)")
    @staff_only()
    async def shiftek(self, i: discord.Interaction, napok: app_commands.Range[int, 1, 90] = 7):
        tol, ig = self._idoszak(napok)
        await i.response.defer(ephemeral=True)
        await i.followup.send(embed=await self.shift_embed(i.guild, tol, ig, f"🕒 Szolgálati idők – elmúlt {napok} nap"), ephemeral=True)

    @stats.command(name="riport", description="A teljes riport azonnali megjelenítése.")
    @app_commands.describe(napok="Hány napot nézzünk (1–90)")
    @staff_only()
    async def riport(self, i: discord.Interaction, napok: app_commands.Range[int, 1, 90] = 7):
        tol, ig = self._idoszak(napok)
        await i.response.defer(ephemeral=True)
        await i.followup.send(embeds=await self.teljes_riport(i.guild, tol, ig, f"{napok} napos"), ephemeral=True)

    @stats.command(name="csatorna", description="Az automatikus heti és havi riport csatornájának beállítása.")
    @app_commands.checks.has_permissions(administrator=True)
    async def csatorna(self, i: discord.Interaction, csatorna: discord.TextChannel):
        await self.bot.db.set(i.guild.id, "riport_csatorna", str(csatorna.id))
        await i.response.send_message(
            f"✅ A heti (hétfőnként) és havi (a hónap első napján) riportok ide érkeznek: {csatorna.mention}", ephemeral=True
        )


async def setup(bot):
    await bot.add_cog(Statisztika(bot))
