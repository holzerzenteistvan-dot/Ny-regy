"""Nyereményjáték: gombos részvétel, feltételek (rang, szint), automatikus sorsolás, újrasorsolás."""
import random
import re

import discord
from discord import app_commands
from discord.ext import commands, tasks

from cogs.szint import xp_szint
from util import KEK, SZURKE, ZOLD, staff_only, ts

EGYSEGEK = {
    "p": 60, "perc": 60, "m": 60, "min": 60,
    "o": 3600, "ó": 3600, "ora": 3600, "óra": 3600, "h": 3600,
    "n": 86400, "nap": 86400, "d": 86400,
}
MAX_IDO = 30 * 86400


def idotartam_mp(szoveg: str) -> int | None:
    """'30p', '2 óra', '3n', '1d' -> másodperc. Hibás bemenetnél None."""
    egyezes = re.fullmatch(r"(\d+)\s*([a-zóÓ]+)", szoveg.strip().lower())
    if not egyezes or egyezes[2] not in EGYSEGEK:
        return None
    mp = int(egyezes[1]) * EGYSEGEK[egyezes[2]]
    return mp if 60 <= mp <= MAX_IDO else None


class ReszvetelGomb(discord.ui.DynamicItem[discord.ui.Button], template=r"nyj:(?P<id>\d+)"):
    def __init__(self, azon: int):
        super().__init__(discord.ui.Button(
            label="Részt veszek", emoji="🎉", style=discord.ButtonStyle.primary, custom_id=f"nyj:{azon}"
        ))
        self.azon = azon

    @classmethod
    async def from_custom_id(cls, i: discord.Interaction, item: discord.ui.Button, match):
        return cls(int(match["id"]))

    async def callback(self, i: discord.Interaction):
        await i.client.get_cog("Nyeremeny").reszvetel(i, self.azon)


def reszvetel_nezet(azon: int) -> discord.ui.View:
    nezet = discord.ui.View(timeout=None)
    nezet.add_item(ReszvetelGomb(azon))
    return nezet


class Nyeremeny(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    async def cog_load(self):
        self.bot.add_dynamic_items(ReszvetelGomb)
        self.ellenorzo.start()

    async def cog_unload(self):
        self.ellenorzo.cancel()

    # ------------------------------------------------------------------ részvétel
    async def jogosult_e(self, tag: discord.Member, sor) -> str | None:
        """Hibaüzenetet ad vissza, ha a tag nem felel meg a feltételeknek."""
        if sor["kell_rang_id"] and not any(r.id == sor["kell_rang_id"] for r in tag.roles):
            return f"Ehhez a nyereményjátékhoz szükséged van a <@&{sor['kell_rang_id']}> rangra."
        if sor["min_szint"]:
            xp = await self.bot.db.fetchone("SELECT xp FROM szintek WHERE guild_id=? AND user_id=?", (tag.guild.id, tag.id))
            if xp_szint(xp["xp"] if xp else 0) < sor["min_szint"]:
                return f"Ehhez minimum **{sor['min_szint']}. szint** szükséges."
        return None

    async def reszvetel(self, i: discord.Interaction, azon: int):
        db = self.bot.db
        sor = await db.fetchone("SELECT * FROM nyeremenyjatekok WHERE id=?", (azon,))
        if not sor or sor["befejezve"]:
            return await i.response.send_message("❌ Ez a nyereményjáték már véget ért.", ephemeral=True)
        if hiba := await self.jogosult_e(i.user, sor):
            return await i.response.send_message(f"❌ {hiba}", ephemeral=True, allowed_mentions=discord.AllowedMentions.none())
        benne = await db.fetchone("SELECT 1 FROM nyj_reszvevok WHERE nyj_id=? AND user_id=?", (azon, i.user.id))
        if benne:
            await db.execute("DELETE FROM nyj_reszvevok WHERE nyj_id=? AND user_id=?", (azon, i.user.id))
            uzenet = "↩️ Visszavontad a részvételedet."
        else:
            await db.execute("INSERT INTO nyj_reszvevok (nyj_id, user_id) VALUES (?, ?)", (azon, i.user.id))
            uzenet = "✅ Részt veszel a nyereményjátékban. Sok szerencsét! 🍀 (A részvétel visszavonásához kattints újra.)"
        db_szam = (await db.fetchone("SELECT COUNT(*) AS db FROM nyj_reszvevok WHERE nyj_id=?", (azon,)))["db"]
        await i.response.send_message(f"{uzenet}\nJelenleg **{db_szam}** résztvevő van.", ephemeral=True)

    # ------------------------------------------------------------------ sorsolás
    async def _jogosultak(self, guild: discord.Guild, sor, kizart: set[int]) -> list[int]:
        reszvevok = await self.bot.db.fetchall("SELECT user_id FROM nyj_reszvevok WHERE nyj_id=?", (sor["id"],))
        jogosultak = []
        for r in reszvevok:
            tag = guild.get_member(r["user_id"])
            if tag and tag.id not in kizart and not await self.jogosult_e(tag, sor):
                jogosultak.append(tag.id)
        return jogosultak

    async def _uzenet(self, sor) -> discord.Message | None:
        csatorna = self.bot.get_channel(sor["csatorna_id"])
        if csatorna is None or not sor["uzenet_id"]:
            return None
        try:
            return await csatorna.fetch_message(sor["uzenet_id"])
        except discord.HTTPException:
            return None

    async def _bejelent(self, guild: discord.Guild, sor, nyertesek: list[int]):
        csatorna = guild.get_channel(sor["csatorna_id"])
        if csatorna is None:
            return
        if nyertesek:
            emlitesek = ", ".join(f"<@{n}>" for n in nyertesek)
            szoveg = f"🎊 Gratulálunk {emlitesek}! Nyeremény: **{sor['nyeremeny']}**"
        else:
            szoveg = f"😕 A(z) **{sor['nyeremeny']}** nyereményjátékra nem volt jogosult résztvevő."
        try:
            await csatorna.send(szoveg, reference=await self._uzenet(sor) or None)
        except discord.HTTPException:
            return
        for n in nyertesek:
            if tag := guild.get_member(n):
                try:
                    await tag.send(f"🎉 Nyertél a(z) **{guild.name}** szerveren! Nyeremény: **{sor['nyeremeny']}**. "
                                   "Keresd a szervezőket az átvételhez.")
                except discord.HTTPException:
                    pass

    async def befejez(self, azon: int) -> str | None:
        """Befejezi és kisorsolja a nyereményjátékot. Hibaüzenetet ad vissza, ha nem lehetséges."""
        db = self.bot.db
        sor = await db.fetchone("SELECT * FROM nyeremenyjatekok WHERE id=?", (azon,))
        if not sor or sor["befejezve"]:
            return "Ez a nyereményjáték nem található, vagy már véget ért."
        guild = self.bot.get_guild(sor["guild_id"])
        if guild is None:
            return "A szerver nem érhető el."
        jogosultak = await self._jogosultak(guild, sor, set())
        nyertesek = random.sample(jogosultak, min(sor["nyertesek_szama"], len(jogosultak)))
        await db.execute(
            "UPDATE nyeremenyjatekok SET befejezve=1, nyertesek=? WHERE id=?", (",".join(map(str, nyertesek)), azon)
        )
        if uzenet := await self._uzenet(sor):
            e = uzenet.embeds[0] if uzenet.embeds else discord.Embed()
            e.title = f"🎉 Nyereményjáték – befejeződött • #{azon}"
            e.color = SZURKE if not nyertesek else ZOLD
            e.clear_fields()
            e.add_field(name="Nyertesek", value=", ".join(f"<@{n}>" for n in nyertesek) or "nincs jogosult résztvevő")
            e.add_field(name="Résztvevők", value=str(len(jogosultak)))
            try:
                await uzenet.edit(embed=e, view=None)
            except discord.HTTPException:
                pass
        await self._bejelent(guild, sor, nyertesek)
        return None

    @tasks.loop(seconds=20)
    async def ellenorzo(self):
        for sor in await self.bot.db.fetchall(
            "SELECT id FROM nyeremenyjatekok WHERE befejezve=0 AND vege<=?", (ts(),)
        ):
            await self.befejez(sor["id"])

    @ellenorzo.before_loop
    async def _var(self):
        await self.bot.wait_until_ready()

    # ------------------------------------------------------------------ parancsok
    nyeremenyjatek = app_commands.Group(name="nyeremenyjatek", description="Nyereményjátékok kezelése.", guild_only=True)

    @nyeremenyjatek.command(name="inditas", description="Új nyereményjáték indítása.")
    @app_commands.describe(
        nyeremeny="Mit lehet nyerni",
        idotartam="Meddig tart: pl. 30p, 2ó, 3n",
        nyertesek="Hány nyertest sorsoljunk",
        rang="Csak ezzel a ranggal lehet részt venni (nem kötelező)",
        min_szint="Minimum szint a részvételhez (nem kötelező)",
        csatorna="Melyik csatornába kerüljön (alapból ide)",
    )
    @staff_only()
    async def inditas(
        self, i: discord.Interaction, nyeremeny: app_commands.Range[str, 1, 200], idotartam: str,
        nyertesek: app_commands.Range[int, 1, 20] = 1, rang: discord.Role | None = None,
        min_szint: app_commands.Range[int, 0, 200] = 0, csatorna: discord.TextChannel | None = None,
    ):
        mp = idotartam_mp(idotartam)
        if mp is None:
            return await i.response.send_message(
                "❌ Érvénytelen időtartam. Példák: `30p`, `2ó`, `3n` (legalább 1 perc, legfeljebb 30 nap).", ephemeral=True
            )
        csatorna = csatorna or i.channel
        vege = ts() + mp
        azon = await self.bot.db.execute(
            "INSERT INTO nyeremenyjatekok (guild_id, csatorna_id, nyeremeny, nyertesek_szama, vege, inditotta, "
            "kell_rang_id, min_szint) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (i.guild.id, csatorna.id, nyeremeny, nyertesek, vege, i.user.id, rang.id if rang else None, min_szint),
        )
        e = discord.Embed(title=f"🎉 Nyereményjáték • #{azon}", description=f"## {nyeremeny}", color=KEK)
        e.add_field(name="Lejár", value=f"<t:{vege}:R> (<t:{vege}:f>)")
        e.add_field(name="Nyertesek száma", value=str(nyertesek))
        e.add_field(name="Indította", value=i.user.mention)
        feltetelek = []
        if rang:
            feltetelek.append(f"Rang: {rang.mention}")
        if min_szint:
            feltetelek.append(f"Minimum szint: **{min_szint}**")
        if feltetelek:
            e.add_field(name="Feltételek", value="\n".join(feltetelek), inline=False)
        e.set_footer(text="A részvételhez kattints a gombra. Újabb kattintással visszavonhatod.")
        try:
            uzenet = await csatorna.send(embed=e, view=reszvetel_nezet(azon))
        except discord.HTTPException:
            await self.bot.db.execute("DELETE FROM nyeremenyjatekok WHERE id=?", (azon,))
            return await i.response.send_message("❌ Nem tudok üzenetet küldeni abba a csatornába.", ephemeral=True)
        await self.bot.db.execute("UPDATE nyeremenyjatekok SET uzenet_id=? WHERE id=?", (uzenet.id, azon))
        await i.response.send_message(f"✅ A nyereményjáték elindult: {uzenet.jump_url}", ephemeral=True)

    @nyeremenyjatek.command(name="befejez", description="Nyereményjáték idő előtti befejezése és sorsolás.")
    @app_commands.describe(azonosito="A nyereményjáték száma (#azonosító)")
    @staff_only()
    async def befejez_cmd(self, i: discord.Interaction, azonosito: app_commands.Range[int, 1, 1_000_000_000]):
        sor = await self.bot.db.fetchone("SELECT guild_id FROM nyeremenyjatekok WHERE id=?", (azonosito,))
        if not sor or sor["guild_id"] != i.guild.id:
            return await i.response.send_message("❌ Nem található ilyen nyereményjáték.", ephemeral=True)
        await i.response.defer(ephemeral=True)
        hiba = await self.befejez(azonosito)
        await i.followup.send(f"❌ {hiba}" if hiba else "✅ A nyereményjáték befejeződött, a nyertesek kisorsolva.", ephemeral=True)

    @nyeremenyjatek.command(name="ujrasorsol", description="Új nyertes(ek) sorsolása egy befejezett nyereményjátékból.")
    @app_commands.describe(azonosito="A nyereményjáték száma", darab="Hány új nyertest sorsoljunk")
    @staff_only()
    async def ujrasorsol(
        self, i: discord.Interaction, azonosito: app_commands.Range[int, 1, 1_000_000_000],
        darab: app_commands.Range[int, 1, 20] = 1,
    ):
        db = self.bot.db
        sor = await db.fetchone("SELECT * FROM nyeremenyjatekok WHERE id=? AND guild_id=?", (azonosito, i.guild.id))
        if not sor:
            return await i.response.send_message("❌ Nem található ilyen nyereményjáték.", ephemeral=True)
        if not sor["befejezve"]:
            return await i.response.send_message("❌ Ez a nyereményjáték még tart. Előbb fejezd be.", ephemeral=True)
        korabbiak = {int(x) for x in sor["nyertesek"].split(",") if x}
        jogosultak = await self._jogosultak(i.guild, sor, korabbiak)
        if not jogosultak:
            return await i.response.send_message("❌ Nincs több jogosult résztvevő.", ephemeral=True)
        ujak = random.sample(jogosultak, min(darab, len(jogosultak)))
        await db.execute(
            "UPDATE nyeremenyjatekok SET nyertesek=? WHERE id=?", (",".join(map(str, [*korabbiak, *ujak])), azonosito)
        )
        await i.response.send_message("✅ Új sorsolás lezajlott.", ephemeral=True)
        await self._bejelent(i.guild, sor, ujak)

    @nyeremenyjatek.command(name="lista", description="A futó nyereményjátékok listája.")
    @staff_only()
    async def lista(self, i: discord.Interaction):
        sorok = await self.bot.db.fetchall(
            "SELECT * FROM nyeremenyjatekok WHERE guild_id=? AND befejezve=0 ORDER BY vege", (i.guild.id,)
        )
        if not sorok:
            return await i.response.send_message("Jelenleg nincs futó nyereményjáték.", ephemeral=True)
        szoveg = "\n".join(
            f"**#{s['id']}** • {s['nyeremeny'][:60]} • lejár <t:{s['vege']}:R> • <#{s['csatorna_id']}>" for s in sorok
        )
        await i.response.send_message(
            embed=discord.Embed(title="Futó nyereményjátékok", description=szoveg, color=KEK), ephemeral=True
        )


async def setup(bot):
    await bot.add_cog(Nyeremeny(bot))
