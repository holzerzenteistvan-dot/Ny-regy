"""Szankció rendszer: figyelmeztetés, némítás, kirúgás, kitiltás, előzmények, automatikus eszkaláció."""
import asyncio
from datetime import datetime, timedelta
from types import SimpleNamespace

import discord
from discord import app_commands
from discord.ext import commands

from util import KEK, NARANCS, PIROS, SARGA, ZOLD, ido_szoveg, iso, most, naplo, staff_only

WARN_LEJARAT_NAP = 30  # ennyi nap után a figyelmeztetés már nem számít bele az eszkalációba
ESZK_TIMEOUT_DARAB = 3  # ennyi aktív figyelmeztetésnél automatikus némítás
ESZK_TIMEOUT_PERC = 24 * 60
ESZK_BAN_DARAB = 5  # ennyi aktív figyelmeztetésnél automatikus kitiltás

CIM = {
    "warn": "Figyelmeztetés",
    "timeout": "Némítás",
    "kick": "Kirúgás",
    "ban": "Kitiltás",
    "unban": "Kitiltás feloldása",
}
SZIN = {"warn": SARGA, "timeout": NARANCS, "kick": NARANCS, "ban": PIROS, "unban": ZOLD}

Indok = app_commands.Range[str, 3, 500]


class SzankcioHiba(Exception):
    """Olvasható hibaüzenettel jelzi, hogy a szankció nem hajtható végre (a szöveg közvetlenül megjeleníthető)."""


def _ok(szoveg: str) -> discord.Embed:
    return discord.Embed(description=szoveg, color=ZOLD)


class Szankcio(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self._nincs_naplo_jog: set[int] = set()  # ahol a bot nem láthatja a Discord naplóját (ne próbálkozzunk újra)

    # ------------------------------------------------------------------ belső segédek
    async def _rogzit(self, guild, user_id, mod_id, tipus, indok, lejar=None) -> int:
        return await self.bot.db.execute(
            "INSERT INTO szankciok (guild_id, user_id, moderator_id, tipus, indok, letrehozva, lejar) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (guild.id, user_id, mod_id, tipus, indok, most().isoformat(), lejar.isoformat() if lejar else None),
        )

    async def aktiv_warn(self, guild_id: int, user_id: int) -> int:
        sor = await self.bot.db.fetchone(
            "SELECT COUNT(*) AS db FROM szankciok "
            "WHERE guild_id=? AND user_id=? AND tipus='warn' AND aktiv=1 AND lejar>?",
            (guild_id, user_id, most().isoformat()),
        )
        return sor["db"]

    async def _ertesit(self, cel, guild, tipus, indok, ugy, megjegyzes=None):
        e = discord.Embed(
            title=f"{CIM[tipus]} – {guild.name}", description=megjegyzes, color=SZIN[tipus], timestamp=most()
        )
        e.add_field(name="Indoklás", value=indok, inline=False)
        e.add_field(name="Ügyazonosító", value=f"#{ugy}")
        e.set_footer(text="Ha tévedésnek tartod, nyiss fellebbezési ticketet a szerveren.")
        try:
            await cel.send(embed=e)
        except discord.HTTPException:
            pass  # a tagnak le van tiltva a DM

    async def _naplozz(self, guild, tipus, cel, mod, indok, ugy, megjegyzes=None):
        e = discord.Embed(title=f"{CIM[tipus]} • #{ugy}", color=SZIN[tipus], timestamp=most())
        e.add_field(name="Felhasználó", value=f"{cel.mention} (`{cel.id}`)")
        e.add_field(name="Moderátor", value=mod.mention)
        e.add_field(name="Indoklás", value=indok, inline=False)
        if megjegyzes:
            e.add_field(name="Megjegyzés", value=megjegyzes, inline=False)
        await naplo(self.bot, guild, e)

    def _ellenorzes(self, i: discord.Interaction, cel: discord.Member) -> str | None:
        """Hibaüzenetet ad vissza, ha a művelet nem engedélyezett."""
        if cel.id == i.user.id:
            return "Magadat nem büntetheted."
        if cel.bot:
            return "Botot nem büntethetsz."
        if cel.id == i.guild.owner_id:
            return "A szerver tulajdonosát nem büntetheted."
        if cel.top_role >= i.guild.me.top_role:
            return "A bot rangja nem áll elég magasan ehhez a taghoz."
        if i.user.id != i.guild.owner_id and cel.top_role >= i.user.top_role:
            return "Nálad magasabb vagy azonos rangú tagot nem büntethetsz."
        return None

    async def _timeout(self, guild, tag, mod, perc, indok) -> int:
        await tag.timeout(timedelta(minutes=perc), reason=indok)
        ugy = await self._rogzit(guild, tag.id, mod.id, "timeout", indok, most() + timedelta(minutes=perc))
        megj = f"Időtartam: **{perc} perc**"
        await self._ertesit(tag, guild, "timeout", indok, ugy, megj)
        await self._naplozz(guild, "timeout", tag, mod, indok, ugy, megj)
        return ugy

    async def _kick(self, guild, tag, mod, indok) -> int:
        ugy = await self._rogzit(guild, tag.id, mod.id, "kick", indok)
        await self._ertesit(tag, guild, "kick", indok, ugy)  # kirúgás előtt kell, utána már nem érjük el
        try:
            await tag.kick(reason=f"[#{ugy}] {indok}")
        except discord.HTTPException:
            await self.bot.db.execute("DELETE FROM szankciok WHERE id=?", (ugy,))
            raise
        await self._naplozz(guild, "kick", tag, mod, indok, ugy)
        return ugy

    async def _ban(self, guild, cel, mod, indok, torles_nap=0) -> int:
        ugy = await self._rogzit(guild, cel.id, mod.id, "ban", indok)
        await self._ertesit(cel, guild, "ban", indok, ugy)
        try:
            await guild.ban(cel, reason=f"[#{ugy}] {indok}", delete_message_seconds=torles_nap * 86400)
        except discord.HTTPException:
            await self.bot.db.execute("DELETE FROM szankciok WHERE id=?", (ugy,))
            raise
        await self._naplozz(guild, "ban", cel, mod, indok, ugy)
        return ugy

    # ------------------------------------------------------------------ közös végrehajtók (parancsok és web)
    @staticmethod
    def _indok_rendben(indok: str) -> str:
        indok = (indok or "").strip()
        if not 3 <= len(indok) <= 500:
            raise SzankcioHiba("Az indok legalább 3, legfeljebb 500 karakter legyen.")
        return indok

    async def web_szankcio(self, guild: discord.Guild, tipus: str, cel_id: int, mod, indok: str,
                           perc: int = 60, torles_nap: int = 0) -> tuple[int, str | None]:
        """Szankció kiadása Discord-interakció nélkül (a dashboardról). Visszaad: (ügyazonosító, eszkaláció szövege)."""
        if tipus not in ("warn", "timeout", "kick", "ban"):
            raise SzankcioHiba("Ismeretlen művelet.")
        indok = self._indok_rendben(indok)
        if cel_id == getattr(mod, "id", None):
            raise SzankcioHiba("Magadat nem büntetheted.")
        tag = guild.get_member(cel_id)
        if tag is None and tipus != "ban":
            raise SzankcioHiba("Ez a felhasználó nincs a szerveren.")
        if tag is not None:
            if tag.bot:
                raise SzankcioHiba("Botot nem büntethetsz.")
            if tag.id == guild.owner_id:
                raise SzankcioHiba("A szerver tulajdonosát nem büntetheted.")
            if tag.top_role >= guild.me.top_role:
                raise SzankcioHiba("A bot rangja nem áll elég magasan ehhez a taghoz.")
        try:
            if tipus == "warn":
                return await self.warn(guild, tag, mod, indok)
            if tipus == "timeout":
                return await self._timeout(guild, tag, mod, max(1, min(40320, int(perc))), indok), None
            if tipus == "kick":
                return await self._kick(guild, tag, mod, indok), None
            cel = tag
            if cel is None:
                try:
                    cel = await self.bot.fetch_user(cel_id)
                except discord.HTTPException:
                    raise SzankcioHiba("Nincs ilyen azonosítójú Discord-felhasználó.")
            return await self._ban(guild, cel, mod, indok, max(0, min(7, int(torles_nap)))), None
        except discord.HTTPException:
            raise SzankcioHiba("A művelet nem sikerült (a botnak nincs elég jogosultsága).")

    async def web_visszavon(self, guild: discord.Guild, ugy: int, mod, indok: str) -> None:
        """Figyelmeztetés vagy némítás visszavonása ügyazonosító alapján."""
        indok = self._indok_rendben(indok)
        db = self.bot.db
        sor = await db.fetchone("SELECT * FROM szankciok WHERE id=? AND guild_id=?", (ugy, guild.id))
        if not sor:
            raise SzankcioHiba("Nem található ilyen ügy.")
        if sor["tipus"] in ("ban", "unban"):
            raise SzankcioHiba("Kitiltás feloldásához a feloldás művelet való.")
        if not sor["aktiv"]:
            raise SzankcioHiba("Ez az ügy már vissza lett vonva.")
        await db.execute("UPDATE szankciok SET aktiv=0 WHERE id=?", (ugy,))
        if sor["tipus"] == "timeout" and (tag := guild.get_member(sor["user_id"])):
            try:
                await tag.timeout(None, reason=f"Visszavonva: {indok}")
            except discord.HTTPException:
                pass
        e = discord.Embed(title=f"Szankció visszavonva • #{ugy}", color=ZOLD, timestamp=most())
        e.add_field(name="Felhasználó", value=f"<@{sor['user_id']}>")
        e.add_field(name="Visszavonta", value=mod.mention)
        e.add_field(name="Eredeti típus", value=CIM[sor["tipus"]])
        e.add_field(name="Indoklás", value=indok, inline=False)
        await naplo(self.bot, guild, e)

    async def web_felold(self, guild: discord.Guild, uid: int, mod, indok: str) -> int:
        """Kitiltás feloldása. Visszaadja az új ügy azonosítóját."""
        indok = self._indok_rendben(indok)
        try:
            await guild.unban(discord.Object(uid), reason=f"{getattr(mod, 'display_name', mod)}: {indok}")
        except discord.NotFound:
            raise SzankcioHiba("Ez a felhasználó nincs kitiltva.")
        except discord.HTTPException:
            raise SzankcioHiba("A feloldás nem sikerült (hiányzó jogosultság).")
        await self.bot.db.execute("UPDATE szankciok SET aktiv=0 WHERE guild_id=? AND user_id=? AND tipus='ban'", (guild.id, uid))
        ugy = await self._rogzit(guild, uid, mod.id, "unban", indok)
        try:
            cel = await self.bot.fetch_user(uid)
        except discord.HTTPException:
            cel = SimpleNamespace(id=uid, mention=f"<@{uid}>")
        await self._naplozz(guild, "unban", cel, mod, indok, ugy)
        return ugy

    async def eszkalacio(self, guild_id: int) -> dict:
        """Az eszkaláció küszöbei. Szerverenként a dashboardon állíthatók, alapértékük a fájl elején van."""
        get = self.bot.db.get
        return {
            "nap": int(await get(guild_id, "szankcio_warn_nap", WARN_LEJARAT_NAP)),
            "timeout_db": int(await get(guild_id, "szankcio_timeout_db", ESZK_TIMEOUT_DARAB)),
            "timeout_perc": int(await get(guild_id, "szankcio_timeout_perc", ESZK_TIMEOUT_PERC)),
            "ban_db": int(await get(guild_id, "szankcio_ban_db", ESZK_BAN_DARAB)),
        }

    async def warn(self, guild, tag, mod, indok) -> tuple[int, str | None]:
        """Figyelmeztetés kiadása eszkalációval. Az erős moderáció is ezt használja."""
        eszk = await self.eszkalacio(guild.id)
        ugy = await self._rogzit(guild, tag.id, mod.id, "warn", indok, most() + timedelta(days=eszk["nap"]))
        darab = await self.aktiv_warn(guild.id, tag.id)
        megj = f"Aktív figyelmeztetések: **{darab}/{eszk['ban_db']}** (lejárat: {eszk['nap']} nap)"
        await self._ertesit(tag, guild, "warn", indok, ugy, megj)
        await self._naplozz(guild, "warn", tag, mod, indok, ugy, megj)

        eszkalacio = None
        try:
            if eszk["ban_db"] and darab >= eszk["ban_db"]:
                await self._ban(guild, tag, guild.me, f"Automatikus kitiltás: {darab} aktív figyelmeztetés.")
                eszkalacio = f"A tag elérte az {eszk['ban_db']} figyelmeztetést, ezért automatikusan ki lett tiltva."
            elif eszk["timeout_db"] and darab == eszk["timeout_db"]:
                await self._timeout(
                    guild, tag, guild.me, eszk["timeout_perc"], f"Automatikus némítás: {darab} aktív figyelmeztetés."
                )
                eszkalacio = (f"A tag elérte a {eszk['timeout_db']} figyelmeztetést, ezért "
                              f"{ido_szoveg(eszk['timeout_perc'] * 60)} időtartamra némítva lett.")
        except discord.HTTPException:
            eszkalacio = "Az automatikus büntetést nem sikerült végrehajtani (hiányzó jogosultság)."
        return ugy, eszkalacio

    # ------------------------------------------------------------------ kézi műveletek nyomon követése
    # Ha valaki a Discord saját felületén (nem a bot parancsával) tilt ki vagy rúg ki valakit,
    # azt is rögzítjük az előzményekbe, hogy a szankciók listája teljes maradjon.
    async def _recens(self, guild_id: int, user_id: int, tipus: str) -> bool:
        """Rögzített-e már (a bot által) ilyen szankció az elmúlt percben?"""
        return await self.bot.db.fetchone(
            "SELECT 1 FROM szankciok WHERE guild_id=? AND user_id=? AND tipus=? AND letrehozva>=?",
            (guild_id, user_id, tipus, iso(most() - timedelta(seconds=60))),
        ) is not None

    async def _naplobejegyzes(self, guild: discord.Guild, akcio: discord.AuditLogAction, user_id: int):
        if guild.id in self._nincs_naplo_jog:
            return None
        try:
            async for bejegyzes in guild.audit_logs(limit=8, action=akcio):
                if bejegyzes.target and bejegyzes.target.id == user_id and (most() - bejegyzes.created_at).total_seconds() < 20:
                    return bejegyzes
        except discord.Forbidden:
            self._nincs_naplo_jog.add(guild.id)
        except discord.HTTPException:
            pass
        return None

    async def _kezi_rogzit(self, guild, tipus: str, cel, bejegyzes):
        if bejegyzes and bejegyzes.user and bejegyzes.user.id == self.bot.user.id:
            return  # a bot saját műveletét már rögzítettük
        mod = bejegyzes.user if bejegyzes and bejegyzes.user else SimpleNamespace(id=0, mention="ismeretlen")
        indok = (bejegyzes.reason if bejegyzes and bejegyzes.reason else None) or "Nincs megadva az indok"
        if tipus == "unban":
            await self.bot.db.execute(
                "UPDATE szankciok SET aktiv=0 WHERE guild_id=? AND user_id=? AND tipus='ban'", (guild.id, cel.id)
            )
        ugy = await self._rogzit(guild, cel.id, mod.id, tipus, indok)
        await self._naplozz(guild, tipus, cel, mod, indok, ugy, "Kézi művelet a Discord felületén (nem a bot parancsával).")

    @commands.Cog.listener()
    async def on_member_ban(self, guild: discord.Guild, user: discord.User):
        if await self._recens(guild.id, user.id, "ban"):
            return
        await asyncio.sleep(1)  # a Discord naplója egy pillanatot késik
        await self._kezi_rogzit(guild, "ban", user, await self._naplobejegyzes(guild, discord.AuditLogAction.ban, user.id))

    @commands.Cog.listener()
    async def on_member_unban(self, guild: discord.Guild, user: discord.User):
        if await self._recens(guild.id, user.id, "unban"):
            return
        await asyncio.sleep(1)
        await self._kezi_rogzit(guild, "unban", user, await self._naplobejegyzes(guild, discord.AuditLogAction.unban, user.id))

    @commands.Cog.listener()
    async def on_member_remove(self, tag: discord.Member):
        if tag.bot or await self._recens(tag.guild.id, tag.id, "kick"):
            return
        await asyncio.sleep(1)
        if bejegyzes := await self._naplobejegyzes(tag.guild, discord.AuditLogAction.kick, tag.id):
            await self._kezi_rogzit(tag.guild, "kick", tag, bejegyzes)

    # ------------------------------------------------------------------ parancsok
    @app_commands.command(name="figyelmeztet", description="Figyelmeztetés kiadása egy tagnak.")
    @app_commands.describe(tag="Akit figyelmeztetsz", indok="A figyelmeztetés oka")
    @app_commands.guild_only()
    @staff_only()
    async def figyelmeztet(self, i: discord.Interaction, tag: discord.Member, indok: Indok):
        if hiba := self._ellenorzes(i, tag):
            return await i.response.send_message(f"❌ {hiba}", ephemeral=True)
        await i.response.defer(ephemeral=True)
        ugy, eszkalacio = await self.warn(i.guild, tag, i.user, indok)
        szoveg = f"✅ {tag.mention} figyelmeztetést kapott. Ügy: **#{ugy}**"
        if eszkalacio:
            szoveg += f"\n⚠️ {eszkalacio}"
        await i.followup.send(embed=_ok(szoveg), ephemeral=True)

    @app_commands.command(name="nemit", description="Tag ideiglenes némítása (timeout).")
    @app_commands.describe(tag="Akit némítasz", perc="Időtartam percben (max. 40320 = 28 nap)", indok="A némítás oka")
    @app_commands.guild_only()
    @staff_only()
    async def nemit(self, i: discord.Interaction, tag: discord.Member, perc: app_commands.Range[int, 1, 40320], indok: Indok):
        if hiba := self._ellenorzes(i, tag):
            return await i.response.send_message(f"❌ {hiba}", ephemeral=True)
        await i.response.defer(ephemeral=True)
        try:
            ugy = await self._timeout(i.guild, tag, i.user, perc, indok)
        except discord.HTTPException:
            return await i.followup.send("❌ A némítás nem sikerült (a botnak nincs elég jogosultsága).", ephemeral=True)
        await i.followup.send(embed=_ok(f"✅ {tag.mention} némítva **{perc} percre**. Ügy: **#{ugy}**"), ephemeral=True)

    @app_commands.command(name="kirug", description="Tag kirúgása a szerverről.")
    @app_commands.describe(tag="Akit kirúgsz", indok="A kirúgás oka")
    @app_commands.guild_only()
    @staff_only()
    async def kirug(self, i: discord.Interaction, tag: discord.Member, indok: Indok):
        if hiba := self._ellenorzes(i, tag):
            return await i.response.send_message(f"❌ {hiba}", ephemeral=True)
        await i.response.defer(ephemeral=True)
        try:
            ugy = await self._kick(i.guild, tag, i.user, indok)
        except discord.HTTPException:
            return await i.followup.send("❌ A kirúgás nem sikerült (a botnak nincs elég jogosultsága).", ephemeral=True)
        await i.followup.send(embed=_ok(f"✅ {tag.mention} ki lett rúgva. Ügy: **#{ugy}**"), ephemeral=True)

    @app_commands.command(name="kitilt", description="Felhasználó kitiltása a szerverről.")
    @app_commands.describe(
        felhasznalo="Akit kitiltasz (a szerveren kívüli felhasználó is megadható)",
        indok="A kitiltás oka",
        torles_nap="Hány napnyi üzenetét töröljük (0–7)",
    )
    @app_commands.guild_only()
    @staff_only()
    async def kitilt(
        self,
        i: discord.Interaction,
        felhasznalo: discord.User,
        indok: Indok,
        torles_nap: app_commands.Range[int, 0, 7] = 0,
    ):
        if isinstance(felhasznalo, discord.Member):
            if hiba := self._ellenorzes(i, felhasznalo):
                return await i.response.send_message(f"❌ {hiba}", ephemeral=True)
        elif felhasznalo.id == i.user.id:
            return await i.response.send_message("❌ Magadat nem büntetheted.", ephemeral=True)
        await i.response.defer(ephemeral=True)
        try:
            ugy = await self._ban(i.guild, felhasznalo, i.user, indok, torles_nap)
        except discord.HTTPException:
            return await i.followup.send("❌ A kitiltás nem sikerült (a botnak nincs elég jogosultsága).", ephemeral=True)
        await i.followup.send(embed=_ok(f"✅ {felhasznalo.mention} ki lett tiltva. Ügy: **#{ugy}**"), ephemeral=True)

    @app_commands.command(name="felold", description="Kitiltás feloldása.")
    @app_commands.describe(felhasznalo_id="A kitiltott felhasználó azonosítója", indok="A feloldás oka")
    @app_commands.guild_only()
    @staff_only()
    async def felold(self, i: discord.Interaction, felhasznalo_id: str, indok: Indok):
        try:
            uid = int(felhasznalo_id.strip())
        except ValueError:
            return await i.response.send_message("❌ Érvénytelen felhasználóazonosító.", ephemeral=True)
        await i.response.defer(ephemeral=True)
        try:
            await self.web_felold(i.guild, uid, i.user, indok)
        except SzankcioHiba as hiba:
            return await i.followup.send(f"❌ {hiba}", ephemeral=True)
        await i.followup.send(embed=_ok(f"✅ <@{uid}> kitiltása fel lett oldva."), ephemeral=True)

    @app_commands.command(name="elozmenyek", description="Egy felhasználó szankcióinak megtekintése.")
    @app_commands.describe(felhasznalo="Akinek az előzményeit nézed")
    @app_commands.guild_only()
    @staff_only()
    async def elozmenyek(self, i: discord.Interaction, felhasznalo: discord.User):
        db = self.bot.db
        sorok = await db.fetchall(
            "SELECT * FROM szankciok WHERE guild_id=? AND user_id=? ORDER BY id DESC LIMIT 15",
            (i.guild.id, felhasznalo.id),
        )
        osszes = (await db.fetchone(
            "SELECT COUNT(*) AS db FROM szankciok WHERE guild_id=? AND user_id=?", (i.guild.id, felhasznalo.id)
        ))["db"]
        aktiv = await self.aktiv_warn(i.guild.id, felhasznalo.id)
        ban_db = (await self.eszkalacio(i.guild.id))["ban_db"]

        e = discord.Embed(title=f"Szankció-előzmények – {felhasznalo}", color=KEK)
        e.set_thumbnail(url=felhasznalo.display_avatar.url)
        if not sorok:
            e.description = "Ennek a felhasználónak nincs szankciója. ✅"
        else:
            sorok_szoveg = []
            for s in sorok:
                datum = discord.utils.format_dt(datetime.fromisoformat(s["letrehozva"]), "d")
                indok = s["indok"] if len(s["indok"]) <= 100 else s["indok"][:97] + "…"
                sor = f"**#{s['id']}** • {CIM[s['tipus']]} • {datum} • <@{s['moderator_id']}>\n> {indok}"
                sorok_szoveg.append(sor if s["aktiv"] else f"~~{sor}~~")
            e.description = "\n".join(sorok_szoveg)
        e.set_footer(text=f"Összesen: {osszes} • Aktív figyelmeztetések: {aktiv}/{ban_db} • Áthúzott = visszavont")
        await i.response.send_message(embed=e, ephemeral=True)

    @app_commands.command(name="visszavon", description="Figyelmeztetés vagy némítás visszavonása ügyazonosító alapján.")
    @app_commands.describe(ugy="Az ügy azonosítója (a # utáni szám)", indok="A visszavonás oka")
    @app_commands.guild_only()
    @staff_only()
    async def visszavon(self, i: discord.Interaction, ugy: app_commands.Range[int, 1, 1_000_000_000], indok: Indok):
        try:
            await self.web_visszavon(i.guild, ugy, i.user, indok)
        except SzankcioHiba as hiba:
            return await i.response.send_message(f"❌ {hiba}", ephemeral=True)
        await i.response.send_message(embed=_ok(f"✅ A(z) **#{ugy}** ügy vissza lett vonva."), ephemeral=True)


async def setup(bot):
    await bot.add_cog(Szankcio(bot))
