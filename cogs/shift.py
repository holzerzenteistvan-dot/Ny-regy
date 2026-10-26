"""Szolgálat (shift) rendszer: belépés/kilépés, szünet, heti és havi összesítők, automatikus lezárás."""
import discord
from discord import app_commands
from discord.ext import commands, tasks

from util import KEK, PIROS, SARGA, ZOLD, het_kezdete, honap_kezdete, ido_szoveg, naplo, staff_e, staff_only, ts

ALAP_MAX_ORA = 8  # ennyi óra után a bot automatikusan lezárja az elfelejtett szolgálatot

# Egy shift tiszta időtartama másodpercben (a szünetek nélkül). A futó shiftnél a :most az aktuális idő.
IDO_SQL = (
    "MAX(0, COALESCE(veg, :most) - kezdet - szunet_mp"
    " - CASE WHEN szunet_kezdet IS NOT NULL THEN :most - szunet_kezdet ELSE 0 END)"
)


class PanelNezet(discord.ui.View):
    """Szolgálat panel gombjai (újraindítás után is működnek)."""

    def __init__(self):
        super().__init__(timeout=None)

    async def _vegrehajt(self, i: discord.Interaction, muvelet: str):
        if not await staff_e(i.client, i.user):
            return await i.response.send_message("❌ Ehhez staff jogosultság szükséges.", ephemeral=True)
        uzenet = await getattr(i.client.get_cog("Shift"), muvelet)(i.user)
        await i.response.send_message(uzenet, ephemeral=True)

    @discord.ui.button(label="Szolgálatba lépés", emoji="🟢", style=discord.ButtonStyle.success, custom_id="shift:start")
    async def gomb_start(self, i: discord.Interaction, gomb: discord.ui.Button):
        await self._vegrehajt(i, "start")

    @discord.ui.button(label="Szolgálat vége", emoji="🔴", style=discord.ButtonStyle.danger, custom_id="shift:stop")
    async def gomb_stop(self, i: discord.Interaction, gomb: discord.ui.Button):
        await self._vegrehajt(i, "stop")

    @discord.ui.button(label="Szünet / folytatás", emoji="⏸️", style=discord.ButtonStyle.secondary, custom_id="shift:szunet")
    async def gomb_szunet(self, i: discord.Interaction, gomb: discord.ui.Button):
        await self._vegrehajt(i, "szunet")


class Shift(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    async def cog_load(self):
        self.bot.add_view(PanelNezet())
        self.ellenorzo.start()

    async def cog_unload(self):
        self.ellenorzo.cancel()

    # ------------------------------------------------------------------ lekérdezések
    async def aktiv(self, guild_id: int, user_id: int):
        return await self.bot.db.fetchone(
            "SELECT * FROM shiftek WHERE guild_id=? AND user_id=? AND veg IS NULL", (guild_id, user_id)
        )

    async def ossz_mp(self, guild_id: int, user_id: int, tol: float, ig: float | None = None) -> int:
        """Egy tag szolgálati ideje másodpercben a [tol, ig) időszakban (a shift kezdete számít)."""
        sor = await self.bot.db.fetchone(
            f"SELECT COALESCE(SUM({IDO_SQL}), 0) AS mp FROM shiftek "
            "WHERE guild_id=:g AND user_id=:u AND kezdet>=:tol AND kezdet<:ig",
            {"most": ts(), "g": guild_id, "u": user_id, "tol": int(tol), "ig": int(ig or ts() + 1)},
        )
        return int(sor["mp"])

    async def ranglista(self, guild_id: int, tol: float, ig: float | None = None, limit: int = 15):
        return await self.bot.db.fetchall(
            f"SELECT user_id, SUM({IDO_SQL}) AS mp FROM shiftek "
            "WHERE guild_id=:g AND kezdet>=:tol AND kezdet<:ig GROUP BY user_id ORDER BY mp DESC LIMIT :limit",
            {"most": ts(), "g": guild_id, "tol": int(tol), "ig": int(ig or ts() + 1), "limit": limit},
        )

    # ------------------------------------------------------------------ műveletek
    async def _rang(self, tag: discord.Member, fel: bool):
        rang_id = await self.bot.db.get(tag.guild.id, "shift_rang")
        rang = tag.guild.get_role(int(rang_id)) if rang_id else None
        if rang is None:
            return
        try:
            if fel:
                await tag.add_roles(rang, reason="Szolgálatba lépett")
            else:
                await tag.remove_roles(rang, reason="Szolgálat vége")
        except discord.HTTPException:
            pass

    async def _naplozz(self, tag: discord.Member, cim: str, szin: discord.Color, leiras: str | None = None):
        e = discord.Embed(title=cim, description=leiras, color=szin)
        e.set_author(name=tag.display_name, icon_url=tag.display_avatar.url)
        await naplo(self.bot, tag.guild, e)

    async def start(self, tag: discord.Member) -> str:
        if await self.aktiv(tag.guild.id, tag.id):
            return "❌ Már szolgálatban vagy."
        await self.bot.db.execute(
            "INSERT INTO shiftek (guild_id, user_id, kezdet) VALUES (?, ?, ?)", (tag.guild.id, tag.id, ts())
        )
        await self._rang(tag, True)
        await self._naplozz(tag, "🟢 Szolgálatba lépett", ZOLD)
        return "✅ Szolgálatba léptél. Jó munkát!"

    async def stop(self, tag: discord.Member) -> str:
        s = await self.aktiv(tag.guild.id, tag.id)
        if not s:
            return "❌ Nem vagy szolgálatban."
        most_ = ts()
        szunet = s["szunet_mp"] + (most_ - s["szunet_kezdet"] if s["szunet_kezdet"] else 0)
        await self.bot.db.execute(
            "UPDATE shiftek SET veg=?, szunet_mp=?, szunet_kezdet=NULL WHERE id=?", (most_, szunet, s["id"])
        )
        ido = ido_szoveg(most_ - s["kezdet"] - szunet)
        await self._rang(tag, False)
        await self._naplozz(tag, "🔴 Szolgálat vége", PIROS, f"Szolgálati idő: **{ido}**")
        return f"✅ Kiléptél a szolgálatból. Szolgálati idő: **{ido}**"

    async def szunet(self, tag: discord.Member) -> str:
        s = await self.aktiv(tag.guild.id, tag.id)
        if not s:
            return "❌ Nem vagy szolgálatban."
        most_ = ts()
        if s["szunet_kezdet"]:
            await self.bot.db.execute(
                "UPDATE shiftek SET szunet_mp=szunet_mp+?, szunet_kezdet=NULL WHERE id=?",
                (most_ - s["szunet_kezdet"], s["id"]),
            )
            return "▶️ Folytattad a szolgálatot."
        await self.bot.db.execute("UPDATE shiftek SET szunet_kezdet=? WHERE id=?", (most_, s["id"]))
        return "⏸️ Szünetre mentél. A szünet nem számít bele a szolgálati időbe. A folytatáshoz használd újra ugyanezt."

    # ------------------------------------------------------------------ automatikus lezárás
    @tasks.loop(minutes=5)
    async def ellenorzo(self):
        db = self.bot.db
        for s in await db.fetchall("SELECT * FROM shiftek WHERE veg IS NULL"):
            guild = self.bot.get_guild(s["guild_id"])
            if guild is None:
                continue
            max_mp = int(await db.get(guild.id, "shift_max_ora", ALAP_MAX_ORA)) * 3600
            most_ = ts()
            szunet = s["szunet_mp"] + (most_ - s["szunet_kezdet"] if s["szunet_kezdet"] else 0)
            if most_ - s["kezdet"] - szunet < max_mp:
                continue
            veg = s["kezdet"] + szunet + max_mp  # a plafonon túli idő nem számít bele
            await db.execute(
                "UPDATE shiftek SET veg=?, szunet_mp=?, szunet_kezdet=NULL, auto_lezart=1 WHERE id=?",
                (veg, szunet, s["id"]),
            )
            if tag := guild.get_member(s["user_id"]):
                await self._rang(tag, False)
                await self._naplozz(
                    tag, "⚠️ Szolgálat automatikusan lezárva", SARGA,
                    f"Elfelejtettél kilépni, ezért a szolgálat {max_mp // 3600} óránál lezárult.",
                )
                try:
                    await tag.send(
                        f"A(z) **{guild.name}** szerveren a szolgálatod automatikusan lezárult, "
                        f"mert {max_mp // 3600} óra után sem léptél ki. Legközelebb ne felejts el kilépni!"
                    )
                except discord.HTTPException:
                    pass

    @ellenorzo.before_loop
    async def _var(self):
        await self.bot.wait_until_ready()

    # ------------------------------------------------------------------ parancsok
    shift = app_commands.Group(name="shift", description="Szolgálati idő kezelése.", guild_only=True)

    @shift.command(name="start", description="Szolgálatba lépés.")
    @staff_only()
    async def start_cmd(self, i: discord.Interaction):
        await i.response.send_message(await self.start(i.user), ephemeral=True)

    @shift.command(name="stop", description="Szolgálat befejezése.")
    @staff_only()
    async def stop_cmd(self, i: discord.Interaction):
        await i.response.send_message(await self.stop(i.user), ephemeral=True)

    @shift.command(name="szunet", description="Szünet kezdete, vagy a szolgálat folytatása.")
    @staff_only()
    async def szunet_cmd(self, i: discord.Interaction):
        await i.response.send_message(await self.szunet(i.user), ephemeral=True)

    @shift.command(name="en", description="A saját (vagy egy másik staff tag) szolgálati idejének megtekintése.")
    @app_commands.describe(tag="Kinek az idejét nézed (alapból a sajátodat)")
    @staff_only()
    async def en_cmd(self, i: discord.Interaction, tag: discord.Member | None = None):
        tag = tag or i.user
        g = i.guild
        s = await self.aktiv(g.id, tag.id)
        if not s:
            allapot = "⚪ Nincs szolgálatban"
        elif s["szunet_kezdet"]:
            allapot = f"⏸️ Szünetben (szolgálatban <t:{s['kezdet']}:R> óta)"
        else:
            allapot = f"🟢 Szolgálatban <t:{s['kezdet']}:R> óta"
        het = await self.ossz_mp(g.id, tag.id, het_kezdete().timestamp())
        honap = await self.ossz_mp(g.id, tag.id, honap_kezdete().timestamp())
        osszes = await self.ossz_mp(g.id, tag.id, 0)
        e = discord.Embed(title=f"Szolgálati idő – {tag.display_name}", description=allapot, color=KEK)
        e.set_thumbnail(url=tag.display_avatar.url)
        e.add_field(name="Ezen a héten", value=ido_szoveg(het))
        e.add_field(name="Ebben a hónapban", value=ido_szoveg(honap))
        e.add_field(name="Összesen", value=ido_szoveg(osszes))
        await i.response.send_message(embed=e, ephemeral=True)

    @shift.command(name="ki_szolgalatban", description="Ki van most szolgálatban?")
    @staff_only()
    async def ki_cmd(self, i: discord.Interaction):
        sorok = await self.bot.db.fetchall(
            "SELECT * FROM shiftek WHERE guild_id=? AND veg IS NULL ORDER BY kezdet", (i.guild.id,)
        )
        if not sorok:
            return await i.response.send_message("Jelenleg senki sincs szolgálatban.", ephemeral=True)
        sorok_szoveg = [
            f"{'⏸️' if s['szunet_kezdet'] else '🟢'} <@{s['user_id']}> • {ido_szoveg(ts() - s['kezdet'])} • "
            f"<t:{s['kezdet']}:t> óta"
            for s in sorok
        ]
        e = discord.Embed(title=f"Szolgálatban ({len(sorok)} fő)", description="\n".join(sorok_szoveg), color=ZOLD)
        await i.response.send_message(embed=e, ephemeral=True)

    @shift.command(name="ranglista", description="A legtöbb szolgálati időt teljesítő staff tagok.")
    @app_commands.describe(idoszak="Melyik időszakot nézzük")
    @app_commands.choices(idoszak=[
        app_commands.Choice(name="Ez a hét", value="het"),
        app_commands.Choice(name="Ez a hónap", value="honap"),
        app_commands.Choice(name="Összesen", value="osszes"),
    ])
    @staff_only()
    async def ranglista_cmd(self, i: discord.Interaction, idoszak: app_commands.Choice[str] | None = None):
        kulcs = idoszak.value if idoszak else "het"
        tol = {"het": het_kezdete().timestamp(), "honap": honap_kezdete().timestamp(), "osszes": 0}[kulcs]
        nev = {"het": "ezen a héten", "honap": "ebben a hónapban", "osszes": "összesen"}[kulcs]
        sorok = await self.ranglista(i.guild.id, tol)
        if not sorok:
            return await i.response.send_message("Ebben az időszakban még nincs szolgálati idő.", ephemeral=True)
        ermek = ["🥇", "🥈", "🥉"]
        szoveg = "\n".join(
            f"{ermek[n] if n < 3 else f'**{n + 1}.**'} <@{s['user_id']}> • **{ido_szoveg(s['mp'])}**"
            for n, s in enumerate(sorok)
        )
        await i.response.send_message(
            embed=discord.Embed(title=f"Szolgálati ranglista – {nev}", description=szoveg, color=KEK), ephemeral=True
        )

    @shift.command(name="panel", description="Szolgálat panel kihelyezése gombokkal.")
    @app_commands.describe(csatorna="Ide kerül a panel")
    @app_commands.checks.has_permissions(administrator=True)
    async def panel_cmd(self, i: discord.Interaction, csatorna: discord.TextChannel):
        e = discord.Embed(
            title="🕒 Szolgálat",
            description="Szolgálatba lépéshez, kilépéshez és szünethez használd az alábbi gombokat.\n"
                        "Az idődet a bot automatikusan méri, a szünet nem számít bele.",
            color=KEK,
        )
        try:
            await csatorna.send(embed=e, view=PanelNezet())
        except discord.HTTPException:
            return await i.response.send_message("❌ Nem tudok üzenetet küldeni abba a csatornába.", ephemeral=True)
        await i.response.send_message(f"✅ A panel kihelyezve: {csatorna.mention}", ephemeral=True)

    @shift.command(name="beallit", description="Szolgálati rang és az automatikus lezárás idejének beállítása.")
    @app_commands.describe(
        rang="Ezt a rangot kapják a szolgálatban lévők (nem kötelező)",
        max_ora="Ennyi óra után lezárja a bot az elfelejtett szolgálatot (1–24)",
    )
    @app_commands.checks.has_permissions(administrator=True)
    async def beallit_cmd(
        self, i: discord.Interaction, rang: discord.Role | None = None, max_ora: app_commands.Range[int, 1, 24] | None = None
    ):
        if rang is None and max_ora is None:
            return await i.response.send_message("Adj meg legalább egy értéket.", ephemeral=True)
        if rang:
            await self.bot.db.set(i.guild.id, "shift_rang", str(rang.id))
        if max_ora:
            await self.bot.db.set(i.guild.id, "shift_max_ora", str(max_ora))
        await i.response.send_message("✅ A szolgálati beállítások mentve.", ephemeral=True)


async def setup(bot):
    await bot.add_cog(Shift(bot))
