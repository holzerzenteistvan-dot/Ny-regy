"""Javaslat rendszer: beküldés, gombos fel/le szavazás, staff döntés státusszal."""
import time

import discord
from discord import app_commands
from discord.ext import commands

from util import KEK, PIROS, SARGA, ZOLD, staff_only, ts

STATUSZOK = {
    "nyitott": ("🗳️ Szavazás folyik", KEK),
    "elfogadva": ("✅ Elfogadva", ZOLD),
    "elutasitva": ("❌ Elutasítva", PIROS),
    "megvalositva": ("🚀 Megvalósítva", discord.Color.gold()),
    "fontolora": ("🤔 Fontolóra véve", SARGA),
}
BEKULDES_PIHENO = 60  # másodperc két javaslat között tagonként


class SzavazGomb(discord.ui.DynamicItem[discord.ui.Button], template=r"jav:(?P<id>\d+):(?P<ir>[fl])"):
    def __init__(self, azon: int, fel: bool):
        super().__init__(discord.ui.Button(
            label="Mellette", emoji="👍", style=discord.ButtonStyle.success, custom_id=f"jav:{azon}:f"
        ) if fel else discord.ui.Button(
            label="Ellene", emoji="👎", style=discord.ButtonStyle.danger, custom_id=f"jav:{azon}:l"
        ))
        self.azon, self.fel = azon, fel

    @classmethod
    async def from_custom_id(cls, i: discord.Interaction, item: discord.ui.Button, match):
        return cls(int(match["id"]), match["ir"] == "f")

    async def callback(self, i: discord.Interaction):
        await i.client.get_cog("Javaslat").szavaz(i, self.azon, 1 if self.fel else -1)


def szavazo_nezet(azon: int) -> discord.ui.View:
    nezet = discord.ui.View(timeout=None)
    nezet.add_item(SzavazGomb(azon, True))
    nezet.add_item(SzavazGomb(azon, False))
    return nezet


class Javaslat(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self._utolso: dict[tuple[int, int], float] = {}

    async def cog_load(self):
        self.bot.add_dynamic_items(SzavazGomb)

    async def szavazatok(self, azon: int) -> tuple[int, int]:
        sor = await self.bot.db.fetchone(
            "SELECT COALESCE(SUM(szavazat = 1), 0) AS fel, COALESCE(SUM(szavazat = -1), 0) AS le "
            "FROM javaslat_szavazatok WHERE javaslat_id=?", (azon,),
        )
        return int(sor["fel"]), int(sor["le"])

    async def embed(self, sor, szerzo: discord.abc.User | None) -> discord.Embed:
        cim, szin = STATUSZOK[sor["statusz"]]
        fel, le = await self.szavazatok(sor["id"])
        e = discord.Embed(title=f"💡 Javaslat #{sor['id']}", description=sor["szoveg"], color=szin)
        if szerzo:
            e.set_author(name=szerzo.display_name, icon_url=szerzo.display_avatar.url)
        e.add_field(name="Állapot", value=cim)
        e.add_field(name="Szavazatok", value=f"👍 **{fel}**  •  👎 **{le}**")
        if sor["indok"] or sor["dontotte"]:
            e.add_field(
                name="Staff döntés",
                value=f"{sor['indok'] or 'Indoklás nélkül'}\n— <@{sor['dontotte']}>" if sor["dontotte"] else sor["indok"],
                inline=False,
            )
        e.set_footer(text=f"Beküldve • ID: {sor['id']}")
        return e

    async def szavaz(self, i: discord.Interaction, azon: int, ertek: int):
        db = self.bot.db
        sor = await db.fetchone("SELECT * FROM javaslatok WHERE id=?", (azon,))
        if not sor or sor["statusz"] not in ("nyitott", "fontolora"):
            return await i.response.send_message("❌ Erre a javaslatra már nem lehet szavazni.", ephemeral=True)
        regi = await db.fetchone("SELECT szavazat FROM javaslat_szavazatok WHERE javaslat_id=? AND user_id=?", (azon, i.user.id))
        if regi and regi["szavazat"] == ertek:  # ugyanarra újra kattintva a szavazat visszavonódik
            await db.execute("DELETE FROM javaslat_szavazatok WHERE javaslat_id=? AND user_id=?", (azon, i.user.id))
        else:
            await db.execute(
                "INSERT INTO javaslat_szavazatok (javaslat_id, user_id, szavazat) VALUES (?, ?, ?) "
                "ON CONFLICT(javaslat_id, user_id) DO UPDATE SET szavazat=excluded.szavazat",
                (azon, i.user.id, ertek),
            )
        szerzo = i.guild.get_member(sor["user_id"])
        await i.response.edit_message(embed=await self.embed(sor, szerzo))

    javaslat = app_commands.Group(name="javaslat", description="Javaslatok a szerverhez.", guild_only=True)

    @javaslat.command(name="uj", description="Új javaslat beküldése a szavazáshoz.")
    @app_commands.describe(szoveg="Mit javasolsz? Fejtsd ki röviden, érthetően.")
    async def uj(self, i: discord.Interaction, szoveg: app_commands.Range[str, 10, 1500]):
        db = self.bot.db
        csatorna_id = await db.get(i.guild.id, "javaslat_csatorna")
        csatorna = i.guild.get_channel(int(csatorna_id)) if csatorna_id else None
        if csatorna is None:
            return await i.response.send_message(
                "❌ A javaslatok csatornája még nincs beállítva. Egy adminisztrátor állítsa be a `/javaslat csatorna` paranccsal.",
                ephemeral=True,
            )
        kulcs = (i.guild.id, i.user.id)
        most_ = time.monotonic()
        if most_ - self._utolso.get(kulcs, 0) < BEKULDES_PIHENO:
            return await i.response.send_message("⏳ Kérlek, várj egy kicsit a következő javaslat beküldése előtt.", ephemeral=True)
        self._utolso[kulcs] = most_

        azon = await db.execute(
            "INSERT INTO javaslatok (guild_id, user_id, szoveg, letrehozva) VALUES (?, ?, ?, ?)",
            (i.guild.id, i.user.id, szoveg, ts()),
        )
        sor = await db.fetchone("SELECT * FROM javaslatok WHERE id=?", (azon,))
        try:
            uzenet = await csatorna.send(embed=await self.embed(sor, i.user), view=szavazo_nezet(azon))
        except discord.HTTPException:
            await db.execute("DELETE FROM javaslatok WHERE id=?", (azon,))
            return await i.response.send_message("❌ Nem tudok üzenetet küldeni a javaslatok csatornájába.", ephemeral=True)
        await db.execute("UPDATE javaslatok SET csatorna_id=?, uzenet_id=? WHERE id=?", (csatorna.id, uzenet.id, azon))
        await i.response.send_message(f"✅ A javaslatod beküldve: {uzenet.jump_url}", ephemeral=True)

    @javaslat.command(name="dontes", description="Döntés egy javaslatról (csak staff).")
    @app_commands.describe(azonosito="A javaslat száma (#azonosító)", statusz="A döntés", indok="Rövid indoklás")
    @app_commands.choices(statusz=[
        app_commands.Choice(name="Elfogadva", value="elfogadva"),
        app_commands.Choice(name="Elutasítva", value="elutasitva"),
        app_commands.Choice(name="Megvalósítva", value="megvalositva"),
        app_commands.Choice(name="Fontolóra véve", value="fontolora"),
    ])
    @staff_only()
    async def dontes(
        self, i: discord.Interaction, azonosito: app_commands.Range[int, 1, 1_000_000_000],
        statusz: app_commands.Choice[str], indok: app_commands.Range[str, 0, 500] = "",
    ):
        db = self.bot.db
        sor = await db.fetchone("SELECT * FROM javaslatok WHERE id=? AND guild_id=?", (azonosito, i.guild.id))
        if not sor:
            return await i.response.send_message("❌ Nem található ilyen javaslat.", ephemeral=True)
        await db.execute(
            "UPDATE javaslatok SET statusz=?, indok=?, dontotte=? WHERE id=?",
            (statusz.value, indok or None, i.user.id, azonosito),
        )
        sor = await db.fetchone("SELECT * FROM javaslatok WHERE id=?", (azonosito,))
        szerzo = i.guild.get_member(sor["user_id"])
        csatorna = i.guild.get_channel(sor["csatorna_id"]) if sor["csatorna_id"] else None
        try:
            uzenet = await csatorna.fetch_message(sor["uzenet_id"])
            lezart = statusz.value in ("elfogadva", "elutasitva", "megvalositva")
            await uzenet.edit(embed=await self.embed(sor, szerzo), view=None if lezart else szavazo_nezet(azonosito))
        except (AttributeError, discord.HTTPException):
            pass  # a csatorna vagy az üzenet már nem létezik
        if szerzo:
            try:
                await szerzo.send(
                    f"**{i.guild.name}**: a(z) **#{azonosito}** javaslatod állapota: **{STATUSZOK[statusz.value][0]}**"
                    + (f"\nIndoklás: {indok}" if indok else "")
                )
            except discord.HTTPException:
                pass
        await i.response.send_message(f"✅ A(z) #{azonosito} javaslat állapota: **{statusz.name}**", ephemeral=True)

    @javaslat.command(name="csatorna", description="A javaslatok csatornájának beállítása.")
    @app_commands.checks.has_permissions(administrator=True)
    async def csatorna(self, i: discord.Interaction, csatorna: discord.TextChannel):
        await self.bot.db.set(i.guild.id, "javaslat_csatorna", str(csatorna.id))
        await i.response.send_message(f"✅ A javaslatok ide érkeznek: {csatorna.mention}", ephemeral=True)


async def setup(bot):
    await bot.add_cog(Javaslat(bot))
