"""Súgó és a bot állapota: /segitseg, /bot."""
import os
import platform
import time

import discord
from discord import app_commands
from discord.ext import commands

from util import KEK, ido_szoveg, staff_e, staff_only, vezeto_e

# (szint, cím, sorok). A szint: 0 = mindenki, 1 = staff, 2 = vezető, 3 = adminisztrátor.
SUGO = [
    (0, "👤 Mindenkinek", [
        "`/javaslat uj` – javaslat beküldése szavazásra",
        "`/staff jelentkezes` – jelentkezés staff pozícióra",
        "`/szint profil`, `toplista`, `rangok` – szint és XP",
        "Ticket nyitása a ticket panel menüjéből, nyereményjátékban részvétel a gombbal",
    ]),
    (1, "🛡️ Staff – moderáció", [
        "`/figyelmeztet`, `/nemit`, `/kirug`, `/kitilt`, `/felold`, `/visszavon`",
        "`/elozmenyek` – egy felhasználó szankciói",
        "`/belepesek lista`, `/belepesek tag` – belépési napló",
        "`/ticket hozzaad`, `/ticket eltavolit` – tagok a ticketben",
    ]),
    (1, "🕒 Staff – szolgálat és értékelés", [
        "`/shift start`, `stop`, `szunet`, `en`, `ki_szolgalatban`, `ranglista`",
        "`/inaktivitas keres`, `visszateres`, `lista`",
        "`/staff teljesitmeny` – saját havi teljesítmény",
        "`/javaslat dontes` – döntés egy javaslatról",
        "`/nyeremenyjatek inditas`, `befejez`, `ujrasorsol`, `lista`",
        "`/stats szerver`, `ticketek`, `shiftek`, `riport`, `/bot`",
    ]),
    (2, "⭐ Vezetők", [
        "Jelentkezések és inaktivitási kérelmek elbírálása a gombokkal",
        "`/staff riport`, `/staff pontozas`, más staff tagok teljesítménye",
    ]),
    (3, "⚙️ Adminisztrátorok", [
        "`/partner telepites`, `kezelo_rang`, `csatorna`, `szoveg`, `szint_beallit`, `szint_torol`, `szintek` – partnerségi rendszer",
        "`/beallitas naplo`, `staffrang`, `vezetoi`, `belepes`, `allapot`",
        "`/automod ...` – szűrők, tiltott szavak, engedélyezett linkek, raid mód",
        "`/ticket panel`, `kategoria` • `/shift panel`, `beallit` • `/inaktivitas beallit` • `/staff beallit`",
        "`/szint rang_hozzaad`, `rang_torol`, `csatorna`, `kivetel`, `szorzo`, `xp_ad`",
        "`/javaslat csatorna` • `/stats csatorna` • `/mentes` • webes dashboard",
    ]),
]
SZINT_NEVEK = ["tag", "staff", "vezető", "adminisztrátor"]


class Segitseg(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @app_commands.command(name="segitseg", description="A bot parancsai, a jogosultságodnak megfelelően.")
    @app_commands.guild_only()
    async def segitseg(self, i: discord.Interaction):
        if i.user.guild_permissions.administrator:
            szint = 3
        elif await vezeto_e(self.bot, i.user):
            szint = 2
        elif await staff_e(self.bot, i.user):
            szint = 1
        else:
            szint = 0
        e = discord.Embed(
            title="📖 Súgó", color=KEK,
            description="Az alábbi parancsok **neked** érhetők el. A magasabb jogosultságú parancsok rejtve maradnak.",
        )
        for minimum, cim, sorok in SUGO:
            if szint >= minimum:
                e.add_field(name=cim, value="\n".join(sorok), inline=False)
        e.set_footer(text=f"Jogosultságod: {SZINT_NEVEK[szint]}")
        await i.response.send_message(embed=e, ephemeral=True)

    @app_commands.command(name="bot", description="A bot állapota: késleltetés, működési idő, adatbázis.")
    @app_commands.guild_only()
    @staff_only()
    async def allapot_cmd(self, i: discord.Interaction):
        mp = int(time.time() - self.bot.inditas)
        nap, maradek = divmod(mp, 86400)
        meret = os.path.getsize(self.bot.db.ut) / 1024 / 1024 if os.path.exists(self.bot.db.ut) else 0
        karbantartas = self.bot.get_cog("Karbantartas")
        mentes = karbantartas.utolso_mentes if karbantartas else None
        e = discord.Embed(title="🤖 A bot állapota", color=KEK)
        e.add_field(name="Késleltetés", value=f"{self.bot.latency * 1000:.0f} ms")
        e.add_field(name="Működési idő", value=(f"{nap} nap " if nap else "") + ido_szoveg(maradek))
        e.add_field(name="Szerverek / tagok", value=f"{len(self.bot.guilds)} / {sum(g.member_count or 0 for g in self.bot.guilds)}")
        e.add_field(name="Adatbázis", value=f"{meret:.1f} MB")
        e.add_field(name="Utolsó mentés", value=discord.utils.format_dt(mentes, "R") if mentes else "még nem volt")
        e.add_field(name="Verziók", value=f"Python {platform.python_version()} • discord.py {discord.__version__}")
        await i.response.send_message(embed=e, ephemeral=True)


async def setup(bot):
    await bot.add_cog(Segitseg(bot))
