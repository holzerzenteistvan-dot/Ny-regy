"""Roblox RP Discord bot – belépési pont."""
import logging
import os
import time

import discord
from discord import app_commands
from discord.ext import commands
from dotenv import load_dotenv

from db import DB
from dontes import DontesGomb
from util import StaffHiba

load_dotenv()
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("dcbot")

MODULOK = (
    "alap", "belepes", "szankcio", "automod", "ticket",
    "shift", "inaktivitas", "staff", "nyitas", "szint", "nyeremeny", "javaslat", "statisztika",
    "segitseg", "karbantartas", "dashboard",
)


class Bot(commands.Bot):
    def __init__(self):
        intents = discord.Intents.default()
        intents.members = True
        intents.message_content = True
        super().__init__(command_prefix=commands.when_mentioned, intents=intents, help_command=None)
        self.db = DB(os.getenv("ADATBAZIS", "dcbot.db"))
        self.inditas = time.time()
        self.dontes_kezelok: dict = {}  # a vezetői döntés-gombok kezelői (lásd dontes.py)

    async def setup_hook(self):
        await self.db.start()
        self.add_dynamic_items(DontesGomb)
        for modul in MODULOK:
            await self.load_extension(f"cogs.{modul}")
        # Ha meg van adva GUILD_ID, a parancsok azonnal megjelennek (fejlesztéshez ideális).
        if guild_id := os.getenv("GUILD_ID"):
            szerver = discord.Object(int(guild_id))
            self.tree.copy_global_to(guild=szerver)
            await self.tree.sync(guild=szerver)
        else:
            await self.tree.sync()

    async def on_ready(self):
        log.info("Bejelentkezve mint %s (%s)", self.user, self.user.id)

    async def close(self):
        await super().close()  # ez tölti ki a modulokat is (pl. a statisztika utolsó mentése)
        await self.db.close()


bot = Bot()


@bot.tree.error
async def parancs_hiba(interaction: discord.Interaction, hiba: app_commands.AppCommandError):
    if isinstance(hiba, StaffHiba):
        uzenet = str(hiba)
    elif isinstance(hiba, app_commands.CheckFailure):
        uzenet = "Ehhez a parancshoz nincs jogosultságod."
    else:
        log.exception("Parancshiba: %s", interaction.command and interaction.command.qualified_name, exc_info=hiba)
        uzenet = "Váratlan hiba történt. Kérlek, próbáld újra később."
    if interaction.response.is_done():
        await interaction.followup.send(uzenet, ephemeral=True)
    else:
        await interaction.response.send_message(uzenet, ephemeral=True)


if __name__ == "__main__":
    token = os.getenv("DISCORD_TOKEN")
    if not token:
        raise SystemExit("Hiányzik a DISCORD_TOKEN. Másold le a .env.example fájlt .env néven, és töltsd ki.")
    bot.run(token, log_handler=None)
