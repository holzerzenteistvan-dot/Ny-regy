"""Inaktivitás rendszer: staff inaktivitási kérelmek, vezetői elbírálás, automatikus rangkezelés."""
import re
from datetime import datetime, time as ora

import discord
from discord import app_commands
from discord.ext import commands, tasks

from dontes import dontes_nezet
from util import IDOZONA, KEK, PIROS, SARGA, ZOLD, csatorna_kap, naplo, staff_only, ts

MAX_NAP = 90  # ennél hosszabb inaktivitás nem kérhető


def datum_ts(szoveg: str) -> int | None:
    """'2026-11-05', '2026.11.05.' vagy napok száma ('7') -> a nap végének unix ideje. Hibás bemenetnél None."""
    s = szoveg.strip().rstrip(".").replace(".", "-").replace("/", "-")
    if s.isdigit():
        return ts() + int(s) * 86400
    try:
        nap = datetime.strptime(s, "%Y-%m-%d").date()
    except ValueError:
        return None
    return int(datetime.combine(nap, ora(23, 59, 59), tzinfo=IDOZONA).timestamp())


class Inaktivitas(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    async def cog_load(self):
        self.bot.dontes_kezelok["inakt"] = self.dontes
        self.lejarat.start()

    async def cog_unload(self):
        self.lejarat.cancel()
        self.bot.dontes_kezelok.pop("inakt", None)

    # ------------------------------------------------------------------ lekérdezések
    async def aktiv(self, guild_id: int, user_id: int):
        """Az éppen érvényben lévő, elfogadott inaktivitás (ha van)."""
        most_ = ts()
        return await self.bot.db.fetchone(
            "SELECT * FROM inaktivitasok WHERE guild_id=? AND user_id=? AND statusz='elfogadva' "
            "AND lezarva=0 AND kezdet<=? AND veg>?",
            (guild_id, user_id, most_, most_),
        )

    async def inaktiv_mp(self, guild_id: int, user_id: int, tol: float, ig: float) -> int:
        """Az elfogadott inaktivitások átfedése másodpercben a [tol, ig) időszakkal."""
        sorok = await self.bot.db.fetchall(
            "SELECT kezdet, veg FROM inaktivitasok WHERE guild_id=? AND user_id=? AND statusz IN ('elfogadva', 'lejart')",
            (guild_id, user_id),
        )
        return int(sum(max(0, min(s["veg"], ig) - max(s["kezdet"], tol)) for s in sorok))

    async def _rang(self, tag: discord.Member, fel: bool):
        rang_id = await self.bot.db.get(tag.guild.id, "inaktiv_rang")
        rang = tag.guild.get_role(int(rang_id)) if rang_id else None
        if rang is None:
            return
        try:
            if fel:
                await tag.add_roles(rang, reason="Elfogadott inaktivitás")
            else:
                await tag.remove_roles(rang, reason="Az inaktivitás véget ért")
        except discord.HTTPException:
            pass

    # ------------------------------------------------------------------ vezetői döntés
    async def dontes(self, i: discord.Interaction, azon: int, elfogad: bool):
        db = self.bot.db
        sor = await db.fetchone("SELECT * FROM inaktivitasok WHERE id=?", (azon,))
        if not sor or sor["statusz"] != "fuggoben":
            return await i.response.send_message("❌ Ezt a kérelmet már elbírálták.", ephemeral=True)
        if elfogad and sor["veg"] <= ts():
            return await i.response.send_message("❌ Ez a kérelem már lejárt, nem fogadható el.", ephemeral=True)
        await db.execute(
            "UPDATE inaktivitasok SET statusz=?, dontotte=? WHERE id=?",
            ("elfogadva" if elfogad else "elutasitva", i.user.id, azon),
        )
        e = i.message.embeds[0]
        e.color = ZOLD if elfogad else PIROS
        e.add_field(name="Döntés", value=f"{'✅ Elfogadva' if elfogad else '❌ Elutasítva'} • {i.user.mention}", inline=False)
        await i.response.edit_message(embed=e, view=None)

        if tag := i.guild.get_member(sor["user_id"]):
            if elfogad:
                await self._rang(tag, True)
            szoveg = (
                f"Az inaktivitási kérelmed **elfogadva** (<t:{sor['veg']}:D>-ig). Pihenj sokat! 🌴"
                if elfogad else "Az inaktivitási kérelmedet sajnos **elutasították**. Kérdés esetén keresd a vezetőket."
            )
            try:
                await tag.send(f"**{i.guild.name}**: {szoveg}")
            except discord.HTTPException:
                pass

    # ------------------------------------------------------------------ lejárat
    @tasks.loop(minutes=10)
    async def lejarat(self):
        for s in await self.bot.db.fetchall(
            "SELECT * FROM inaktivitasok WHERE statusz='elfogadva' AND lezarva=0 AND veg<=?", (ts(),)
        ):
            await self.bot.db.execute("UPDATE inaktivitasok SET lezarva=1, statusz='lejart' WHERE id=?", (s["id"],))
            guild = self.bot.get_guild(s["guild_id"])
            if guild and (tag := guild.get_member(s["user_id"])):
                await self._rang(tag, False)
                try:
                    await tag.send(f"**{guild.name}**: az inaktivitásod véget ért. Visszavárunk! 👋")
                except discord.HTTPException:
                    pass

    @lejarat.before_loop
    async def _var(self):
        await self.bot.wait_until_ready()

    # ------------------------------------------------------------------ parancsok
    inaktivitas = app_commands.Group(name="inaktivitas", description="Inaktivitási kérelmek.", guild_only=True)

    @inaktivitas.command(name="keres", description="Inaktivitási kérelem beadása.")
    @app_commands.describe(
        meddig="Meddig leszel inaktív: dátum (ÉÉÉÉ-HH-NN, pl. 2026-11-05) vagy napok száma (pl. 7)",
        indok="Az inaktivitás oka",
    )
    @staff_only()
    async def keres(self, i: discord.Interaction, meddig: str, indok: app_commands.Range[str, 3, 500]):
        veg = datum_ts(meddig)
        most_ = ts()
        if veg is None:
            return await i.response.send_message(
                "❌ Érvénytelen dátum. Használd az `ÉÉÉÉ-HH-NN` formátumot (pl. `2026-11-05`), vagy add meg a napok számát (pl. `7`).",
                ephemeral=True,
            )
        if veg <= most_ or veg > most_ + MAX_NAP * 86400:
            return await i.response.send_message(
                f"❌ A dátumnak a jövőben kell lennie, és legfeljebb {MAX_NAP} napra kérhetsz inaktivitást.", ephemeral=True
            )
        db = self.bot.db
        van = await db.fetchone(
            "SELECT id FROM inaktivitasok WHERE guild_id=? AND user_id=? AND lezarva=0 "
            "AND statusz IN ('fuggoben', 'elfogadva')",
            (i.guild.id, i.user.id),
        )
        if van:
            return await i.response.send_message(
                "❌ Már van függőben lévő vagy aktív inaktivitásod. Előbb fejezd be a `/inaktivitas visszateres` paranccsal.",
                ephemeral=True,
            )
        csatorna = await csatorna_kap(self.bot, i.guild, "vezetoi_csatorna")
        if csatorna is None:
            return await i.response.send_message(
                "❌ A vezetői csatorna nincs beállítva. Egy adminisztrátor állítsa be a `/beallitas vezetoi` paranccsal.",
                ephemeral=True,
            )
        azon = await db.execute(
            "INSERT INTO inaktivitasok (guild_id, user_id, kezdet, veg, indok) VALUES (?, ?, ?, ?, ?)",
            (i.guild.id, i.user.id, most_, veg, indok),
        )
        e = discord.Embed(title=f"🌴 Inaktivitási kérelem • #{azon}", color=SARGA)
        e.set_author(name=i.user.display_name, icon_url=i.user.display_avatar.url)
        e.add_field(name="Kérelmező", value=i.user.mention)
        e.add_field(name="Meddig", value=f"<t:{veg}:D> (<t:{veg}:R>)")
        e.add_field(name="Indok", value=indok, inline=False)
        vezeto_id = await db.get(i.guild.id, "vezetorang")
        uzenet = await csatorna.send(
            content=f"<@&{vezeto_id}>" if vezeto_id else None, embed=e, view=dontes_nezet("inakt", azon)
        )
        await db.execute("UPDATE inaktivitasok SET uzenet_id=?, csatorna_id=? WHERE id=?", (uzenet.id, csatorna.id, azon))
        await i.response.send_message("✅ A kérelmedet elküldtem a vezetőknek. Értesítést kapsz a döntésről.", ephemeral=True)

    @inaktivitas.command(name="visszateres", description="Visszatérés: az inaktivitásod (vagy kérelmed) idő előtti befejezése.")
    @staff_only()
    async def visszateres(self, i: discord.Interaction):
        db = self.bot.db
        sor = await db.fetchone(
            "SELECT * FROM inaktivitasok WHERE guild_id=? AND user_id=? AND lezarva=0 "
            "AND statusz IN ('fuggoben', 'elfogadva') ORDER BY id DESC LIMIT 1",
            (i.guild.id, i.user.id),
        )
        if not sor:
            return await i.response.send_message("❌ Nincs aktív inaktivitásod.", ephemeral=True)
        uj_statusz = "lejart" if sor["statusz"] == "elfogadva" else "visszavont"
        await db.execute(
            "UPDATE inaktivitasok SET lezarva=1, statusz=?, veg=MIN(veg, ?) WHERE id=?", (uj_statusz, ts(), sor["id"])
        )
        await self._rang(i.user, False)
        await naplo(self.bot, i.guild, discord.Embed(
            title="Inaktivitás befejezve", description=f"{i.user.mention} visszatért az inaktivitásból.", color=ZOLD
        ))
        await i.response.send_message("✅ Üdv újra! Az inaktivitásod véget ért.", ephemeral=True)

    @inaktivitas.command(name="lista", description="Az aktív és függőben lévő inaktivitások listája.")
    @staff_only()
    async def lista(self, i: discord.Interaction):
        sorok = await self.bot.db.fetchall(
            "SELECT * FROM inaktivitasok WHERE guild_id=? AND lezarva=0 AND statusz IN ('fuggoben', 'elfogadva') "
            "ORDER BY veg",
            (i.guild.id,),
        )
        if not sorok:
            return await i.response.send_message("Jelenleg nincs aktív inaktivitás. ✅", ephemeral=True)
        szoveg = "\n".join(
            f"{'⏳ függőben' if s['statusz'] == 'fuggoben' else '🌴 aktív'} • <@{s['user_id']}> • <t:{s['veg']}:D> • "
            f"{s['indok'][:80]}"
            for s in sorok
        )
        await i.response.send_message(
            embed=discord.Embed(title="Inaktivitások", description=szoveg[:4000], color=KEK), ephemeral=True
        )

    @inaktivitas.command(name="beallit", description="Az inaktív rang beállítása.")
    @app_commands.describe(rang="Ezt a rangot kapják az elfogadott inaktivitás idejére")
    @app_commands.checks.has_permissions(administrator=True)
    async def beallit(self, i: discord.Interaction, rang: discord.Role):
        await self.bot.db.set(i.guild.id, "inaktiv_rang", str(rang.id))
        figyelmeztetes = "\n⚠️ A bot rangja nem áll magasabban ennél a rangnál." if rang >= i.guild.me.top_role else ""
        await i.response.send_message(f"✅ Inaktív rang: {rang.mention}{figyelmeztetes}", ephemeral=True)


async def setup(bot):
    await bot.add_cog(Inaktivitas(bot))
