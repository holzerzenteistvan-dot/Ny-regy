"""Alapbeállítások: naplócsatorna, staff rang, belépési üzenet."""
import discord
from discord import app_commands
from discord.ext import commands

from util import KEK


class Alap(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    beallitas = app_commands.Group(
        name="beallitas",
        description="A bot alapbeállításai.",
        guild_only=True,
        default_permissions=discord.Permissions(administrator=True),
    )

    @beallitas.command(name="naplo", description="Naplócsatorna beállítása (szankciók, moderáció, ticket átiratok).")
    @app_commands.describe(csatorna="Ide kerülnek a naplóbejegyzések")
    @app_commands.checks.has_permissions(administrator=True)
    async def naplo_cmd(self, i: discord.Interaction, csatorna: discord.TextChannel):
        await self.bot.db.set(i.guild.id, "naplo", str(csatorna.id))
        await i.response.send_message(f"✅ A naplócsatorna beállítva: {csatorna.mention}", ephemeral=True)

    @beallitas.command(name="staffrang", description="A staff tagok rangjának beállítása.")
    @app_commands.describe(rang="Ez a rang kezelheti a ticketeket és használhatja a moderációs parancsokat")
    @app_commands.checks.has_permissions(administrator=True)
    async def staffrang_cmd(self, i: discord.Interaction, rang: discord.Role):
        await self.bot.db.set(i.guild.id, "staffrang", str(rang.id))
        await i.response.send_message(f"✅ A staff rang beállítva: {rang.mention}", ephemeral=True)

    @beallitas.command(name="vezetoi", description="Vezetői csatorna és vezetői rang beállítása.")
    @app_commands.describe(
        csatorna="Ide érkeznek a jelentkezések, inaktivitási kérelmek és a staff riportok",
        rang="A vezetők rangja: ők bírálhatják el a kérelmeket, és pontozhatják a staffot",
    )
    @app_commands.checks.has_permissions(administrator=True)
    async def vezetoi_cmd(self, i: discord.Interaction, csatorna: discord.TextChannel, rang: discord.Role):
        await self.bot.db.set(i.guild.id, "vezetoi_csatorna", str(csatorna.id))
        await self.bot.db.set(i.guild.id, "vezetorang", str(rang.id))
        await i.response.send_message(
            f"✅ Vezetői csatorna: {csatorna.mention} • vezetői rang: {rang.mention}", ephemeral=True
        )

    @beallitas.command(name="belepes", description="Üdvözlő csatorna, alaprang és üdvözlő üzenet beállítása.")
    @app_commands.describe(
        csatorna="Ide érkezik az üdvözlő üzenet",
        rang="Ezt a rangot kapja minden új tag (nem kötelező)",
        uzenet="Egyedi üdvözlés. Használható: {tag}, {szerver}, {szam} (nem kötelező)",
    )
    @app_commands.checks.has_permissions(administrator=True)
    async def belepes_cmd(
        self,
        i: discord.Interaction,
        csatorna: discord.TextChannel,
        rang: discord.Role | None = None,
        uzenet: app_commands.Range[str, 1, 1000] | None = None,
    ):
        db = self.bot.db
        await db.set(i.guild.id, "belepes_csatorna", str(csatorna.id))
        if rang:
            await db.set(i.guild.id, "belepes_rang", str(rang.id))
        if uzenet:
            await db.set(i.guild.id, "belepes_uzenet", uzenet)
        figyelmeztetes = ""
        if rang and rang >= i.guild.me.top_role:
            figyelmeztetes = "\n⚠️ A bot rangja nem áll magasabban ennél a rangnál, ezért nem fogja tudni kiosztani."
        await i.response.send_message(f"✅ A belépési rendszer beállítva.{figyelmeztetes}", ephemeral=True)

    @beallitas.command(name="allapot", description="A jelenlegi alapbeállítások megtekintése.")
    @app_commands.checks.has_permissions(administrator=True)
    async def allapot_cmd(self, i: discord.Interaction):
        db, g = self.bot.db, i.guild

        async def csatorna(kulcs):
            ertek = await db.get(g.id, kulcs)
            return f"<#{ertek}>" if ertek else "nincs beállítva"

        async def rang(kulcs):
            ertek = await db.get(g.id, kulcs)
            return f"<@&{ertek}>" if ertek else "nincs beállítva"

        e = discord.Embed(title="Alapbeállítások", color=KEK)
        e.add_field(name="Naplócsatorna", value=await csatorna("naplo"))
        e.add_field(name="Staff rang", value=await rang("staffrang"))
        e.add_field(name="Vezetői csatorna", value=await csatorna("vezetoi_csatorna"))
        e.add_field(name="Vezetői rang", value=await rang("vezetorang"))
        e.add_field(name="Üdvözlő csatorna", value=await csatorna("belepes_csatorna"))
        e.add_field(name="Alaprang belépéskor", value=await rang("belepes_rang"))
        e.add_field(name="Ticket kategória", value=await csatorna("ticket_kategoria"))
        await i.response.send_message(embed=e, ephemeral=True)


async def setup(bot):
    await bot.add_cog(Alap(bot))
