"""Belépés: üdvözlés, alaprang, tartós belépési napló (belepesek tábla), lekérdező parancsok."""
import discord
from discord import app_commands
from discord.ext import commands

from util import KEK, NARANCS, ZOLD, ido_szoveg, most, naplo, staff_only, ts

ALAP_UZENET = "Üdvözlünk a szerveren, {tag}! 🎉\nTe vagy a **{szam}.** tagunk. Érezd jól magad!"
SZANKCIO_TIPUSOK = "('warn', 'timeout', 'kick', 'ban')"


class Belepes(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    async def szankciok_szama(self, guild_id: int, user_id: int) -> int:
        sor = await self.bot.db.fetchone(
            f"SELECT COUNT(*) AS db FROM szankciok WHERE guild_id=? AND user_id=? AND tipus IN {SZANKCIO_TIPUSOK}",
            (guild_id, user_id),
        )
        return sor["db"]

    # ------------------------------------------------------------------ események
    @commands.Cog.listener()
    async def on_member_join(self, tag: discord.Member):
        if tag.bot:
            return
        db, g = self.bot.db, tag.guild

        korabbi = (await db.fetchone(
            "SELECT COUNT(*) AS db FROM belepesek WHERE guild_id=? AND user_id=?", (g.id, tag.id)
        ))["db"]
        # A belépést előbb rögzítjük, mint hogy bármi történne vele: így a raid-érzékelés és a napló is tartós.
        belepes_id = await db.execute(
            "INSERT INTO belepesek (guild_id, user_id, belepett, fiok_letrehozva) VALUES (?, ?, ?, ?)",
            (g.id, tag.id, ts(), int(tag.created_at.timestamp())),
        )

        # Az erős moderáció dönthet úgy, hogy a tag nem maradhat (raid mód, túl új fiók).
        automod = self.bot.get_cog("AutoMod")
        if automod and await automod.belepes_ellenorzes(tag, belepes_id):
            return

        if rang_id := await db.get(g.id, "belepes_rang"):
            if rang := g.get_role(int(rang_id)):
                try:
                    await tag.add_roles(rang, reason="Automatikus alaprang belépéskor")
                except discord.HTTPException:
                    await naplo(self.bot, g, discord.Embed(
                        title="Nem sikerült az alaprang kiosztása",
                        description=f"{tag.mention} megkapta volna a(z) {rang.mention} rangot, "
                                    "de a botnak nincs hozzá jogosultsága (a bot rangja legyen magasabb).",
                        color=NARANCS,
                    ))

        if csatorna_id := await db.get(g.id, "belepes_csatorna"):
            if csatorna := g.get_channel(int(csatorna_id)):
                sablon = await db.get(g.id, "belepes_uzenet", ALAP_UZENET)
                szoveg = (
                    sablon.replace("{tag}", tag.mention)
                    .replace("{szerver}", g.name)
                    .replace("{szam}", str(g.member_count))
                )
                e = discord.Embed(title=f"Üdvözlünk, {tag.display_name}!", description=szoveg, color=ZOLD)
                e.set_thumbnail(url=tag.display_avatar.url)
                try:
                    await csatorna.send(content=tag.mention, embed=e)
                except discord.HTTPException:
                    pass

        szankciok = await self.szankciok_szama(g.id, tag.id)
        e = discord.Embed(title="Tag csatlakozott", color=NARANCS if (korabbi or szankciok) else ZOLD, timestamp=most())
        e.set_thumbnail(url=tag.display_avatar.url)
        e.add_field(name="Tag", value=f"{tag.mention} (`{tag.id}`)")
        e.add_field(name="Fiók létrehozva", value=discord.utils.format_dt(tag.created_at, "R"))
        e.add_field(name="Tagok száma", value=str(g.member_count))
        if korabbi:
            e.add_field(name="⚠️ Visszatérő tag", value=f"Ez a(z) **{korabbi + 1}.** belépése.")
        if szankciok:
            e.add_field(name="⚠️ Korábbi szankciók", value=f"{szankciok} db (`/belepesek tag`, `/elozmenyek`)")
        await naplo(self.bot, g, e)

    @commands.Cog.listener()
    async def on_member_remove(self, tag: discord.Member):
        if tag.bot:
            return
        db, g = self.bot.db, tag.guild
        sor = await db.fetchone(
            "SELECT id, belepett, eredmeny FROM belepesek WHERE guild_id=? AND user_id=? AND kilepett IS NULL "
            "ORDER BY id DESC LIMIT 1", (g.id, tag.id),
        )
        if sor:
            await db.execute("UPDATE belepesek SET kilepett=? WHERE id=?", (ts(), sor["id"]))
        if sor and sor["eredmeny"] == "kirugva":
            return  # az automatikus kirúgás már bekerült a naplóba

        e = discord.Embed(title="Tag kilépett", color=KEK, timestamp=most())
        e.add_field(name="Tag", value=f"{tag.mention} (`{tag.id}`)")
        kezdet = sor["belepett"] if sor else (int(tag.joined_at.timestamp()) if tag.joined_at else None)
        if kezdet:
            e.add_field(name="Tagság hossza", value=ido_szoveg(ts() - kezdet))
        rangok = [r.mention for r in tag.roles if not r.is_default()]
        if rangok:
            e.add_field(name="Rangjai", value=" ".join(rangok)[:1000], inline=False)
        await naplo(self.bot, g, e)

    # ------------------------------------------------------------------ parancsok
    belepesek = app_commands.Group(name="belepesek", description="A szerverre történt belépések naplója.", guild_only=True)

    @belepesek.command(name="lista", description="A legutóbbi belépések az elmúlt napokban.")
    @app_commands.describe(napok="Hány napra visszamenőleg (1–30)")
    @staff_only()
    async def lista(self, i: discord.Interaction, napok: app_commands.Range[int, 1, 30] = 1):
        db = self.bot.db
        tol = ts() - napok * 86400
        osszes = await db.fetchone(
            "SELECT COUNT(*) AS db, COALESCE(SUM(eredmeny='kirugva'), 0) AS kirugva, COALESCE(SUM(kilepett IS NOT NULL), 0) AS kilepett "
            "FROM belepesek WHERE guild_id=? AND belepett>=?", (i.guild.id, tol),
        )
        sorok = await db.fetchall(
            "SELECT * FROM belepesek WHERE guild_id=? AND belepett>=? ORDER BY id DESC LIMIT 20", (i.guild.id, tol)
        )
        e = discord.Embed(title=f"Belépések – elmúlt {napok} nap", color=KEK)
        e.add_field(name="Belépett", value=str(osszes["db"]))
        e.add_field(name="Automatikusan kirúgva", value=str(osszes["kirugva"]))
        e.add_field(name="Azóta kilépett", value=str(osszes["kilepett"]))
        e.description = "\n".join(
            f"{'🚫' if s['eredmeny'] == 'kirugva' else '✅'} <@{s['user_id']}> • <t:{s['belepett']}:R> • fiók: <t:{s['fiok_letrehozva']}:R>"
            + (f"\n> {s['ok'][:80]}" if s["ok"] else "")
            for s in sorok
        ) or "Ebben az időszakban nem volt belépés."
        if osszes["db"] > len(sorok):
            e.set_footer(text=f"A legutóbbi {len(sorok)} belépés látszik.")
        await i.response.send_message(embed=e, ephemeral=True, allowed_mentions=discord.AllowedMentions.none())

    @belepesek.command(name="tag", description="Egy felhasználó belépéseinek és kilépéseinek története.")
    @app_commands.describe(felhasznalo="Kinek a történetét nézed")
    @staff_only()
    async def tag(self, i: discord.Interaction, felhasznalo: discord.User):
        db = self.bot.db
        sorok = await db.fetchall(
            "SELECT * FROM belepesek WHERE guild_id=? AND user_id=? ORDER BY id DESC LIMIT 15", (i.guild.id, felhasznalo.id)
        )
        szankciok = await self.szankciok_szama(i.guild.id, felhasznalo.id)
        bent = i.guild.get_member(felhasznalo.id) is not None
        e = discord.Embed(title=f"Belépési előzmények – {felhasznalo}", color=KEK)
        e.set_thumbnail(url=felhasznalo.display_avatar.url)
        e.add_field(name="Most a szerveren", value="igen" if bent else "nem")
        e.add_field(name="Belépések száma", value=str(len(sorok)))
        e.add_field(name="Szankciók", value=str(szankciok))
        e.add_field(name="Fiók létrehozva", value=discord.utils.format_dt(felhasznalo.created_at, "R"))
        e.description = "\n".join(
            f"{'🚫' if s['eredmeny'] == 'kirugva' else '✅'} belépett <t:{s['belepett']}:f>"
            + (f" • kilépett <t:{s['kilepett']}:f>" if s["kilepett"] else "")
            + (f"\n> {s['ok'][:80]}" if s["ok"] else "")
            for s in sorok
        ) or "Ehhez a felhasználóhoz nincs rögzített belépés."
        await i.response.send_message(embed=e, ephemeral=True)


async def setup(bot):
    await bot.add_cog(Belepes(bot))
