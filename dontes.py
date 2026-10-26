"""Közös Elfogadás / Elutasítás gombok vezetői döntésekhez (jelentkezés, inaktivitás).

Az egyes modulok a bot.dontes_kezelok szótárban regisztrálják a saját kezelőjüket:
    bot.dontes_kezelok["inakt"] = self.dontes   # async def dontes(interaction, azonosito, elfogad)
"""
import discord

from util import vezeto_e


class DontesGomb(discord.ui.DynamicItem[discord.ui.Button], template=r"dontes:(?P<tipus>[a-z]+):(?P<id>\d+):(?P<mit>[ie])"):
    def __init__(self, tipus: str, azonosito: int, elfogad: bool):
        super().__init__(discord.ui.Button(
            label="Elfogadás" if elfogad else "Elutasítás",
            emoji="✅" if elfogad else "❌",
            style=discord.ButtonStyle.success if elfogad else discord.ButtonStyle.danger,
            custom_id=f"dontes:{tipus}:{azonosito}:{'i' if elfogad else 'e'}",
        ))
        self.tipus, self.azonosito, self.elfogad = tipus, azonosito, elfogad

    @classmethod
    async def from_custom_id(cls, i: discord.Interaction, item: discord.ui.Button, match):
        return cls(match["tipus"], int(match["id"]), match["mit"] == "i")

    async def callback(self, i: discord.Interaction):
        if not await vezeto_e(i.client, i.user):
            return await i.response.send_message("❌ Ezt csak a vezetők dönthetik el.", ephemeral=True)
        kezelo = i.client.dontes_kezelok.get(self.tipus)
        if kezelo is None:
            return await i.response.send_message("❌ Ez a döntés jelenleg nem kezelhető.", ephemeral=True)
        await kezelo(i, self.azonosito, self.elfogad)


def dontes_nezet(tipus: str, azonosito: int) -> discord.ui.View:
    nezet = discord.ui.View(timeout=None)
    nezet.add_item(DontesGomb(tipus, azonosito, True))
    nezet.add_item(DontesGomb(tipus, azonosito, False))
    return nezet
