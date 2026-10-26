"""Karbantartás: napi automatikus adatbázis-mentés és a régi statisztikai adatok takarítása."""
import logging
import os
import re
from datetime import datetime, timedelta

import discord
from discord import app_commands
from discord.ext import commands, tasks

from util import IDOZONA, ts

log = logging.getLogger("dcbot.karbantartas")
MENTES_MAPPA = os.getenv("MENTES_MAPPA", "mentesek")
MEGTARTAS = 7  # ennyi napi mentést őrzünk meg
ADAT_NAP = 400  # ennél régebbi napi statisztikát és belépési naplót törlünk
MENTES_MINTA = re.compile(r"dcbot-\d{4}-\d{2}-\d{2}\.db")


class Karbantartas(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.utolso_mentes: datetime | None = None

    async def cog_load(self):
        self.ciklus.start()

    async def cog_unload(self):
        self.ciklus.cancel()

    async def mentes_keszit(self, kenyszer: bool = False) -> str | None:
        """Konzisztens pillanatkép az adatbázisról (VACUUM INTO). Naponta egy fájl készül."""
        os.makedirs(MENTES_MAPPA, exist_ok=True)
        fajl = os.path.join(MENTES_MAPPA, f"dcbot-{datetime.now(IDOZONA):%Y-%m-%d}.db")
        if os.path.exists(fajl):
            if not kenyszer:
                return None
            os.remove(fajl)
        await self.bot.db.mentes(fajl)
        for regi in sorted(f for f in os.listdir(MENTES_MAPPA) if MENTES_MINTA.fullmatch(f))[:-MEGTARTAS]:
            os.remove(os.path.join(MENTES_MAPPA, regi))
        self.utolso_mentes = datetime.now(IDOZONA)
        return fajl

    async def takarit(self):
        db = self.bot.db
        hatar = (datetime.now(IDOZONA) - timedelta(days=ADAT_NAP)).strftime("%Y-%m-%d")
        for tabla in ("napi_aktivitas", "napi_csatorna", "napi_tagok"):
            await db.execute(f"DELETE FROM {tabla} WHERE nap<?", (hatar,))
        await db.execute("DELETE FROM belepesek WHERE belepett<?", (ts() - ADAT_NAP * 86400,))
        await db.execute(
            "DELETE FROM nyj_reszvevok WHERE nyj_id IN "
            "(SELECT id FROM nyeremenyjatekok WHERE befejezve=1 AND vege<?)", (ts() - 90 * 86400,),
        )

    @tasks.loop(hours=6)
    async def ciklus(self):
        try:
            if fajl := await self.mentes_keszit():
                log.info("Adatbázis-mentés elkészült: %s", fajl)
            await self.takarit()
        except Exception:  # a karbantartás hibája ne állítsa meg a ciklust
            log.exception("A karbantartás nem sikerült")

    @ciklus.before_loop
    async def _var(self):
        await self.bot.wait_until_ready()

    @app_commands.command(name="mentes", description="Azonnali adatbázis-mentés készítése a bot gépén.")
    @app_commands.guild_only()
    @app_commands.checks.has_permissions(administrator=True)
    async def mentes(self, i: discord.Interaction):
        await i.response.defer(ephemeral=True)
        fajl = await self.mentes_keszit(kenyszer=True)
        meret = os.path.getsize(fajl) / 1024
        await i.followup.send(f"✅ A mentés elkészült: `{fajl}` ({meret:.0f} KB). Az utolsó {MEGTARTAS} napi mentést őrzöm meg.", ephemeral=True)


async def setup(bot):
    await bot.add_cog(Karbantartas(bot))
