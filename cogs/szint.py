"""Szint rendszer: XP üzenetekért és hangcsatornában töltött időért, szintrangok, toplista, XP-szorzók."""
import random
import time

import discord
from discord import app_commands
from discord.ext import commands, tasks

from util import KEK

XP_MIN, XP_MAX = 15, 25  # egy üzenetért kapott XP
XP_COOLDOWN = 60  # másodperc két XP-t érő üzenet között
HANG_XP = 10  # percenként a hangcsatornában (ha nem egyedül vagy, és nem vagy némítva)


def szint_xp(szint: int) -> int:
    """Az adott szint eléréséhez szükséges összes XP."""
    return 100 * szint * szint


def xp_szint(xp: int) -> int:
    return int((max(xp, 0) / 100) ** 0.5)


def savok(xp: int, hossz: int = 12) -> str:
    """Haladási sáv a következő szintig."""
    szint = xp_szint(xp)
    alap, cel = szint_xp(szint), szint_xp(szint + 1)
    kesz = round(hossz * (xp - alap) / (cel - alap))
    return "▰" * kesz + "▱" * (hossz - kesz)


class Szint(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self._utolso: dict[tuple[int, int], float] = {}
        self._szorzok: dict[int, dict[int, float]] = {}
        self._kivetelek: dict[int, set[int]] = {}

    async def cog_load(self):
        self.hang.start()

    async def cog_unload(self):
        self.hang.cancel()

    # ------------------------------------------------------------------ belső
    async def _szorzo(self, tag: discord.Member) -> float:
        if tag.guild.id not in self._szorzok:
            sorok = await self.bot.db.fetchall(
                "SELECT rang_id, szorzo FROM szint_szorzok WHERE guild_id=?", (tag.guild.id,)
            )
            self._szorzok[tag.guild.id] = {s["rang_id"]: s["szorzo"] for s in sorok}
        szorzok = self._szorzok[tag.guild.id]
        return max([szorzok[r.id] for r in tag.roles if r.id in szorzok], default=1.0)

    async def _kivetel(self, guild_id: int, csatorna_id: int) -> bool:
        if guild_id not in self._kivetelek:
            nyers = await self.bot.db.get(guild_id, "szint_kivetel", "")
            self._kivetelek[guild_id] = {int(x) for x in nyers.split(",") if x}
        return csatorna_id in self._kivetelek[guild_id]

    async def xp_ad(self, tag: discord.Member, mennyiseg: int, uzenet: bool = False) -> tuple[int, int]:
        """XP hozzáadása. (régi szint, új szint) párt ad vissza. Negatív mennyiség levon."""
        db = self.bot.db
        sor = await db.fetchone("SELECT xp FROM szintek WHERE guild_id=? AND user_id=?", (tag.guild.id, tag.id))
        regi = sor["xp"] if sor else 0
        uj = max(0, regi + mennyiseg)
        await db.execute(
            "INSERT INTO szintek (guild_id, user_id, xp, uzenetek) VALUES (?, ?, ?, ?) "
            "ON CONFLICT(guild_id, user_id) DO UPDATE SET xp=?, uzenetek=uzenetek+?",
            (tag.guild.id, tag.id, uj, int(uzenet), uj, int(uzenet)),
        )
        return xp_szint(regi), xp_szint(uj)

    async def rang_frissit(self, tag: discord.Member, szint: int):
        """A szintnek megfelelő legmagasabb rang marad meg, az alacsonyabb szintrangok lekerülnek."""
        sorok = await self.bot.db.fetchall(
            "SELECT szint, rang_id FROM szint_rangok WHERE guild_id=? ORDER BY szint", (tag.guild.id,)
        )
        if not sorok:
            return
        jogosult = [s for s in sorok if s["szint"] <= szint]  # szint szerint rendezett
        cel_id = jogosult[-1]["rang_id"] if jogosult else None
        szintrangok = {s["rang_id"] for s in sorok}
        torlendo = [r for r in tag.roles if r.id in szintrangok and r.id != cel_id]
        hozzaadando = tag.guild.get_role(cel_id) if cel_id and not any(r.id == cel_id for r in tag.roles) else None
        try:
            if torlendo:
                await tag.remove_roles(*torlendo, reason="Szintrang csere")
            if hozzaadando:
                await tag.add_roles(hozzaadando, reason=f"Elérte a(z) {szint}. szintet")
        except discord.HTTPException:
            pass

    async def _szintlepes(self, tag: discord.Member, szint: int, csatorna: discord.abc.Messageable | None):
        await self.rang_frissit(tag, szint)
        cel_id = await self.bot.db.get(tag.guild.id, "szint_csatorna")
        cel = tag.guild.get_channel(int(cel_id)) if cel_id else csatorna
        if cel is None:
            return
        try:
            await cel.send(f"🎉 {tag.mention} elérte a(z) **{szint}. szintet**!", delete_after=60 if not cel_id else None)
        except discord.HTTPException:
            pass

    # ------------------------------------------------------------------ XP gyűjtés
    @commands.Cog.listener()
    async def on_message(self, uzenet: discord.Message):
        if uzenet.author.bot or uzenet.guild is None or not isinstance(uzenet.author, discord.Member):
            return
        db, kulcs = self.bot.db, (uzenet.guild.id, uzenet.author.id)
        most_ = time.monotonic()
        pihenes = int(await db.get(uzenet.guild.id, "szint_cooldown", XP_COOLDOWN))
        if most_ - self._utolso.get(kulcs, 0) < pihenes or await self._kivetel(uzenet.guild.id, uzenet.channel.id):
            return
        self._utolso[kulcs] = most_
        xp_min = int(await db.get(uzenet.guild.id, "szint_xp_min", XP_MIN))
        xp_max = int(await db.get(uzenet.guild.id, "szint_xp_max", XP_MAX))
        mennyiseg = round(random.randint(min(xp_min, xp_max), max(xp_min, xp_max)) * await self._szorzo(uzenet.author))
        regi, uj = await self.xp_ad(uzenet.author, mennyiseg, uzenet=True)
        if uj > regi:
            await self._szintlepes(uzenet.author, uj, uzenet.channel)

    @tasks.loop(minutes=1)
    async def hang(self):
        for guild in self.bot.guilds:
            hang_xp = int(await self.bot.db.get(guild.id, "szint_hang_xp", HANG_XP))
            if hang_xp <= 0:
                continue  # ennél a szervernél ki van kapcsolva a hangcsatornás XP
            for csatorna in guild.voice_channels:
                if csatorna == guild.afk_channel:
                    continue
                emberek = [t for t in csatorna.members if not t.bot]
                if len(emberek) < 2:
                    continue  # egyedül ülve nem jár XP
                for tag in emberek:
                    if tag.voice and (tag.voice.self_deaf or tag.voice.deaf or tag.voice.mute or tag.voice.self_mute):
                        continue
                    regi, uj = await self.xp_ad(tag, round(hang_xp * await self._szorzo(tag)))
                    if uj > regi:
                        await self._szintlepes(tag, uj, None)

    @hang.before_loop
    async def _var(self):
        await self.bot.wait_until_ready()

    # ------------------------------------------------------------------ parancsok
    szint = app_commands.Group(name="szint", description="Szint rendszer.", guild_only=True)

    @szint.command(name="profil", description="Szint és XP megtekintése.")
    @app_commands.describe(tag="Kinek a szintjét nézed (alapból a sajátodat)")
    async def profil(self, i: discord.Interaction, tag: discord.Member | None = None):
        tag = tag or i.user
        sor = await self.bot.db.fetchone("SELECT xp, uzenetek FROM szintek WHERE guild_id=? AND user_id=?", (i.guild.id, tag.id))
        xp, uzenetek = (sor["xp"], sor["uzenetek"]) if sor else (0, 0)
        szint = xp_szint(xp)
        hely = (await self.bot.db.fetchone(
            "SELECT COUNT(*) + 1 AS hely FROM szintek WHERE guild_id=? AND xp>?", (i.guild.id, xp)
        ))["hely"]
        e = discord.Embed(title=f"{tag.display_name} szintje", color=KEK)
        e.set_thumbnail(url=tag.display_avatar.url)
        e.add_field(name="Szint", value=f"**{szint}**")
        e.add_field(name="Helyezés", value=f"**#{hely}**")
        e.add_field(name="Üzenetek", value=str(uzenetek))
        e.add_field(
            name=f"Haladás a(z) {szint + 1}. szintig", value=f"{savok(xp)}\n{xp} / {szint_xp(szint + 1)} XP", inline=False
        )
        await i.response.send_message(embed=e)

    @szint.command(name="toplista", description="A legtöbb XP-vel rendelkező tagok.")
    async def toplista(self, i: discord.Interaction):
        sorok = await self.bot.db.fetchall(
            "SELECT user_id, xp FROM szintek WHERE guild_id=? ORDER BY xp DESC LIMIT 10", (i.guild.id,)
        )
        if not sorok:
            return await i.response.send_message("Még senki sem gyűjtött XP-t.", ephemeral=True)
        ermek = ["🥇", "🥈", "🥉"]
        szoveg = "\n".join(
            f"{ermek[n] if n < 3 else f'**{n + 1}.**'} <@{s['user_id']}> • {xp_szint(s['xp'])}. szint • {s['xp']} XP"
            for n, s in enumerate(sorok)
        )
        await i.response.send_message(
            embed=discord.Embed(title="🏆 Szint toplista", description=szoveg, color=KEK),
            allowed_mentions=discord.AllowedMentions.none(),
        )

    @szint.command(name="rang_hozzaad", description="Rang hozzárendelése egy szinthez.")
    @app_commands.describe(szint="Ezen a szinten kapják meg a tagok", rang="A kiosztandó rang")
    @app_commands.checks.has_permissions(administrator=True)
    async def rang_hozzaad(self, i: discord.Interaction, szint: app_commands.Range[int, 1, 200], rang: discord.Role):
        await self.bot.db.execute(
            "INSERT INTO szint_rangok (guild_id, szint, rang_id) VALUES (?, ?, ?) "
            "ON CONFLICT(guild_id, szint) DO UPDATE SET rang_id=excluded.rang_id",
            (i.guild.id, szint, rang.id),
        )
        figyelmeztetes = "\n⚠️ A bot rangja nem áll magasabban ennél a rangnál." if rang >= i.guild.me.top_role else ""
        await i.response.send_message(f"✅ A(z) **{szint}. szinten** a(z) {rang.mention} rang jár.{figyelmeztetes}", ephemeral=True)

    @szint.command(name="rang_torol", description="Szintrang eltávolítása.")
    @app_commands.checks.has_permissions(administrator=True)
    async def rang_torol(self, i: discord.Interaction, szint: app_commands.Range[int, 1, 200]):
        await self.bot.db.execute("DELETE FROM szint_rangok WHERE guild_id=? AND szint=?", (i.guild.id, szint))
        await i.response.send_message(f"✅ A(z) {szint}. szinthez tartozó rang törölve.", ephemeral=True)

    @szint.command(name="rangok", description="A szintekhez rendelt rangok listája.")
    async def rangok(self, i: discord.Interaction):
        sorok = await self.bot.db.fetchall(
            "SELECT szint, rang_id FROM szint_rangok WHERE guild_id=? ORDER BY szint", (i.guild.id,)
        )
        szoveg = "\n".join(f"**{s['szint']}. szint** → <@&{s['rang_id']}>" for s in sorok) or "Még nincs szintrang beállítva."
        await i.response.send_message(
            embed=discord.Embed(title="Szintrangok", description=szoveg, color=KEK),
            ephemeral=True, allowed_mentions=discord.AllowedMentions.none(),
        )

    @szint.command(name="csatorna", description="Szintlépés-értesítések csatornája (üresen hagyva: abba a csatornába, ahol írt).")
    @app_commands.checks.has_permissions(administrator=True)
    async def csatorna(self, i: discord.Interaction, csatorna: discord.TextChannel | None = None):
        if csatorna:
            await self.bot.db.set(i.guild.id, "szint_csatorna", str(csatorna.id))
            return await i.response.send_message(f"✅ A szintlépések ide érkeznek: {csatorna.mention}", ephemeral=True)
        await self.bot.db.torol(i.guild.id, "szint_csatorna")
        await i.response.send_message("✅ A szintlépések abba a csatornába érkeznek, ahol a tag írt.", ephemeral=True)

    @szint.command(name="kivetel", description="Csatorna kizárása az XP-gyűjtésből (kapcsoló).")
    @app_commands.checks.has_permissions(administrator=True)
    async def kivetel(self, i: discord.Interaction, csatorna: discord.TextChannel):
        nyers = await self.bot.db.get(i.guild.id, "szint_kivetel", "")
        csatornak = {int(x) for x in nyers.split(",") if x}
        if csatorna.id in csatornak:
            csatornak.discard(csatorna.id)
            uzenet = f"✅ {csatorna.mention} újra ad XP-t."
        else:
            csatornak.add(csatorna.id)
            uzenet = f"✅ {csatorna.mention} többé nem ad XP-t."
        await self.bot.db.set(i.guild.id, "szint_kivetel", ",".join(map(str, csatornak)))
        self._kivetelek.pop(i.guild.id, None)
        await i.response.send_message(uzenet, ephemeral=True)

    @szint.command(name="szorzo", description="XP-szorzó beállítása egy rangnak (pl. boosterek). 1 = törlés.")
    @app_commands.describe(rang="Melyik rang kapja", szorzo="Pl. 1.5 = másfélszeres XP")
    @app_commands.checks.has_permissions(administrator=True)
    async def szorzo(self, i: discord.Interaction, rang: discord.Role, szorzo: app_commands.Range[float, 0.1, 5.0]):
        if szorzo == 1.0:
            await self.bot.db.execute("DELETE FROM szint_szorzok WHERE guild_id=? AND rang_id=?", (i.guild.id, rang.id))
            uzenet = f"✅ A(z) {rang.mention} rang XP-szorzója törölve."
        else:
            await self.bot.db.execute(
                "INSERT INTO szint_szorzok (guild_id, rang_id, szorzo) VALUES (?, ?, ?) "
                "ON CONFLICT(guild_id, rang_id) DO UPDATE SET szorzo=excluded.szorzo",
                (i.guild.id, rang.id, szorzo),
            )
            uzenet = f"✅ A(z) {rang.mention} rang XP-szorzója: **{szorzo}×**"
        self._szorzok.pop(i.guild.id, None)
        await i.response.send_message(uzenet, ephemeral=True, allowed_mentions=discord.AllowedMentions.none())

    @szint.command(name="xp_ad", description="XP hozzáadása vagy levonása egy tagtól.")
    @app_commands.describe(mennyiseg="Negatív szám esetén levonás")
    @app_commands.checks.has_permissions(administrator=True)
    async def xp_ad_cmd(self, i: discord.Interaction, tag: discord.Member, mennyiseg: app_commands.Range[int, -100000, 100000]):
        regi, uj = await self.xp_ad(tag, mennyiseg)
        await self.rang_frissit(tag, uj)
        await i.response.send_message(f"✅ {tag.mention}: {regi}. szint → **{uj}. szint**", ephemeral=True)


async def setup(bot):
    await bot.add_cog(Szint(bot))
