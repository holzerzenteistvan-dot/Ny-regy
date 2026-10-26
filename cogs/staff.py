"""Staff jelentkezés, havi teljesítmény-értékelés, vezetői pontozás és automatikus riportok."""
import asyncio
import json
import logging
import os
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import discord
from discord import app_commands
from discord.ext import commands, tasks

from cogs.ticket import TicketHiba
from dontes import dontes_nezet
from util import (IDOZONA, KEK, PIROS, SARGA, ZOLD, csatorna_kap, elozo_honap_kezdete, het_kezdete, honap_kezdete,
                  ido_szoveg, iso, most, naplo, ts, vezeto_e, vezeto_only, staff_only)


def _iso_ts(masodperc: float) -> str:
    return iso(datetime.fromtimestamp(masodperc, timezone.utc))


ALAP_KERDESEK = [
    "Hány éves vagy?",
    "Korábbi staff tapasztalatod (szerver, pozíció, mennyi ideig)",
    "Miért téged válasszunk?",
    "Heti hány órát tudsz a szerveren lenni?",
]


log = logging.getLogger("dcbot.staff")

ALAP_ELFOGAD = "Szia {tag}! A jelentkezésedet **elfogadtuk**! 🎉 Az alábbi gombbal egy ticketet nyithatsz, ahol a vezetők felveszik veled a kapcsolatot."
ALAP_ELUTASIT = "Szia {tag}! A jelentkezésedet sajnos **elutasítottuk**. Köszönjük, hogy jelentkeztél, később újra próbálkozhatsz!"
KERDES_IDO = 900  # ennyi másodpercig vár a bot egy-egy válaszra a privát üzenetben
MAX_VALASZ = 1000
MEGSE = {"megse", "mégse", "cancel", "stop"}


class JelentkezesHiba(Exception):
    """Olvasható hibaüzenettel jelzi, hogy a jelentkezéssel kapcsolatos művelet nem végezhető el."""


class JelentkezesPanelNezet(discord.ui.View):
    """A kihelyezett jelentkezési panel gombja (újraindítás után is működik)."""

    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="Jelentkezem", emoji="📝", style=discord.ButtonStyle.success, custom_id="jel:inditas")
    async def inditas(self, i: discord.Interaction, gomb: discord.ui.Button):
        await i.client.get_cog("Staff").dm_inditas(i)


class JelTicketGomb(discord.ui.DynamicItem[discord.ui.Button], template=r"jel:ticket:(?P<id>\d+)"):
    """Az elfogadott jelentkező privát értesítésében lévő „Ticket nyitása” gomb."""

    def __init__(self, azon: int):
        super().__init__(discord.ui.Button(label="Ticket nyitása", emoji="🎫", style=discord.ButtonStyle.primary,
                                           custom_id=f"jel:ticket:{azon}"))
        self.azon = azon

    @classmethod
    async def from_custom_id(cls, i: discord.Interaction, item: discord.ui.Button, match):
        return cls(int(match["id"]))

    async def callback(self, i: discord.Interaction):
        await i.client.get_cog("Staff").ticket_gomb(i, self.azon)


class BekuldesNezet(discord.ui.View):
    """A privát üzenetes jelentkezés végén: beküldés vagy elvetés."""

    def __init__(self):
        super().__init__(timeout=600)
        self.bekuldi: bool | None = None

    @discord.ui.button(label="Beküldés", emoji="✅", style=discord.ButtonStyle.success)
    async def be(self, i: discord.Interaction, gomb: discord.ui.Button):
        self.bekuldi = True
        await i.response.edit_message(view=None)
        self.stop()

    @discord.ui.button(label="Elvetés", emoji="🗑️", style=discord.ButtonStyle.secondary)
    async def el(self, i: discord.Interaction, gomb: discord.ui.Button):
        self.bekuldi = False
        await i.response.edit_message(view=None)
        self.stop()


class Staff(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self._dm_folyamatok: set[tuple[int, int]] = set()  # (szerver, felhasználó): éppen zajló privát jelentkezések
        self._hatter: set[asyncio.Task] = set()

    async def cog_load(self):
        self.bot.dontes_kezelok["jel"] = self.jelentkezes_dontes
        self.bot.add_view(JelentkezesPanelNezet())
        self.bot.add_dynamic_items(JelTicketGomb)
        self.automata.start()

    async def cog_unload(self):
        self.automata.cancel()
        self.bot.dontes_kezelok.pop("jel", None)
        for feladat in list(self._hatter):
            feladat.cancel()

    def hatterben(self, korutin) -> None:
        feladat = asyncio.ensure_future(korutin)
        self._hatter.add(feladat)

        def kesz(f):
            self._hatter.discard(f)
            if not f.cancelled() and f.exception():
                log.error("Hiba a jelentkezés háttérfolyamatában", exc_info=f.exception())

        feladat.add_done_callback(kesz)

    # ------------------------------------------------------------------ beállítások
    async def kerdesek(self, guild_id: int) -> list[str]:
        nyers = await self.bot.db.get(guild_id, "jelentkezes_kerdesek")
        lista = [k.strip() for k in nyers.splitlines() if k.strip()] if nyers else []
        return (lista or ALAP_KERDESEK)[:5]

    # ------------------------------------------------------------------ panel
    async def panel_kozzetesz(self, guild: discord.Guild, csatorna: discord.TextChannel) -> discord.Message:
        """A jelentkezési panel kihelyezése: a gombra kattintva a bot privátban kérdezi végig a jelentkezőt."""
        db = self.bot.db
        kerdesek = await self.kerdesek(guild.id)
        e = discord.Embed(
            title="📝 Jelentkezés",
            description=("Szeretnél a csapat tagja lenni? Kattints a **Jelentkezem** gombra, és a bot **privát üzenetben** "
                         f"felteszi a {len(kerdesek)} kérdést. A döntésről itt is értesítést kapsz.\n"
                         "Győződj meg róla, hogy a szerver tagjaitól engedélyezted a privát üzeneteket."),
            color=ZOLD,
        )
        uzenet = await csatorna.send(embed=e, view=JelentkezesPanelNezet())
        await db.set(guild.id, "jelentkezes_panel", f"{csatorna.id}:{uzenet.id}")
        return uzenet

    # ------------------------------------------------------------------ jelentkezés privát üzenetben
    async def dm_inditas(self, i: discord.Interaction):
        """A „Jelentkezem” gomb és a /jelentkezes parancs: elindítja a privát üzenetes kérdezést."""
        g, db = i.guild, self.bot.db
        if await db.get(g.id, "jelentkezes_nyitva", "1") == "0":
            return await i.response.send_message("❌ A jelentkezés jelenleg le van zárva.", ephemeral=True)
        if await csatorna_kap(self.bot, g, "jelentkezes_csatorna", "vezetoi_csatorna") is None:
            return await i.response.send_message("❌ A jelentkezések fogadása még nincs beállítva.", ephemeral=True)
        if await db.fetchone("SELECT id FROM jelentkezesek WHERE guild_id=? AND user_id=? AND statusz='fuggoben'", (g.id, i.user.id)):
            return await i.response.send_message("❌ Már van függőben lévő jelentkezésed. Légy türelmes!", ephemeral=True)
        if (g.id, i.user.id) in self._dm_folyamatok:
            return await i.response.send_message("❌ A jelentkezésed már folyamatban van, nézd meg a privát üzeneteidet.", ephemeral=True)
        await i.response.defer(ephemeral=True)
        kerdesek = await self.kerdesek(g.id)
        bevezeto = discord.Embed(
            title=f"📝 Jelentkezés – {g.name}",
            description=(f"{len(kerdesek)} kérdést teszek fel. Válaszolj mindegyikre egy-egy üzenettel (legfeljebb {MAX_VALASZ} karakter).\n"
                         f"Bármikor megszakíthatod a `mégse` beírásával. Egy-egy válaszra {KERDES_IDO // 60} percig várok."),
            color=ZOLD)
        try:
            await i.user.send(embed=bevezeto)
        except discord.HTTPException:
            return await i.followup.send(
                "❌ Nem tudok privát üzenetet küldeni neked. Engedélyezd a privát üzeneteket ennél a szervernél "
                "(Szerver beállításai → Adatvédelem), majd próbáld újra.", ephemeral=True)
        await i.followup.send("✅ Privát üzenetben megkérdezlek, nézd meg az üzeneteidet!", ephemeral=True)
        self._dm_folyamatok.add((g.id, i.user.id))
        self.hatterben(self.dm_folyamat(g, i.user, kerdesek))

    async def dm_folyamat(self, g: discord.Guild, user: discord.abc.User, kerdesek: list[str]) -> None:
        kulcs = (g.id, user.id)
        try:
            valaszok: dict[str, str] = {}

            def sajat(uzenet: discord.Message) -> bool:
                return uzenet.author.id == user.id and uzenet.guild is None

            for n, kerdes in enumerate(kerdesek, 1):
                await user.send(f"**{n}/{len(kerdesek)}.** {kerdes}")
                while True:
                    try:
                        uzenet = await self.bot.wait_for("message", check=sajat, timeout=KERDES_IDO)
                    except asyncio.TimeoutError:
                        return await user.send("⌛ Túl sokáig nem válaszoltál, a jelentkezés megszakadt. A panelen újra elindíthatod.")
                    szoveg = uzenet.content.strip()
                    if szoveg.lower() in MEGSE:
                        return await user.send("🛑 A jelentkezést megszakítottad. Bármikor újra elindíthatod.")
                    szoveg = "\n".join(x for x in [szoveg] + [a.url for a in uzenet.attachments] if x)
                    if not szoveg:
                        await user.send("Kérlek, írj választ szövegesen.")
                    elif len(szoveg) > MAX_VALASZ:
                        await user.send(f"A válaszod túl hosszú ({len(szoveg)} karakter), legfeljebb {MAX_VALASZ} lehet. Kérlek, rövidítsd.")
                    else:
                        valaszok[kerdes] = szoveg
                        break

            osszegzes = discord.Embed(title="Ellenőrizd a jelentkezésedet", color=SARGA,
                                      description="Ha minden rendben, küldd be. Beküldés után már nem módosítható.")
            for kerdes, valasz in valaszok.items():
                osszegzes.add_field(name=kerdes[:256], value=valasz[:1000], inline=False)
            nezet = BekuldesNezet()
            await user.send(embed=osszegzes, view=nezet)
            await nezet.wait()
            if nezet.bekuldi is None:
                return await user.send("⌛ Nem érkezett megerősítés, a jelentkezés nem lett beküldve.")
            if not nezet.bekuldi:
                return await user.send("🗑️ A jelentkezést elvetettük.")
            try:
                azon = await self.jelentkezes_bead(g, user, valaszok, "dm")
            except JelentkezesHiba as hiba:
                return await user.send(f"❌ {hiba}")
            await user.send(f"✅ A jelentkezésedet (**#{azon}**) elküldtem a vezetőknek. A döntésről itt értesítést kapsz.")
        except discord.HTTPException:
            log.warning("A privát jelentkezés megszakadt (a felhasználó lezárta a privát üzeneteket): %s", kulcs)
        finally:
            self._dm_folyamatok.discard(kulcs)

    async def jelentkezes_bead(self, g: discord.Guild, user: discord.abc.User, valaszok: dict, forras: str = "dm") -> int:
        """Elmenti a jelentkezést és kirakja a vezetői csatornába. Hibánál JelentkezesHiba."""
        db = self.bot.db
        csatorna = await csatorna_kap(self.bot, g, "jelentkezes_csatorna", "vezetoi_csatorna")
        if csatorna is None:
            raise JelentkezesHiba("A jelentkezések fogadása még nincs beállítva.")
        if await db.fetchone("SELECT id FROM jelentkezesek WHERE guild_id=? AND user_id=? AND statusz='fuggoben'", (g.id, user.id)):
            raise JelentkezesHiba("Már van függőben lévő jelentkezésed.")
        azon = await db.execute(
            "INSERT INTO jelentkezesek (guild_id, user_id, valaszok, letrehozva, forras) VALUES (?, ?, ?, ?, ?)",
            (g.id, user.id, json.dumps(valaszok, ensure_ascii=False), ts(), forras))
        tag = g.get_member(user.id)
        e = discord.Embed(title=f"📝 Staff jelentkezés • #{azon}", color=SARGA, timestamp=datetime.now(timezone.utc))
        e.set_author(name=user.display_name, icon_url=user.display_avatar.url)
        e.add_field(name="Jelentkező", value=f"{user.mention} (`{user.id}`)", inline=False)
        e.add_field(name="Szerveren van", value=f"<t:{int(tag.joined_at.timestamp())}:R> óta" if tag and tag.joined_at else "–")
        e.add_field(name="Forrás", value="privát üzenet" if forras == "dm" else "Discord űrlap")
        for kerdes, valasz in valaszok.items():
            e.add_field(name=kerdes[:256], value=valasz[:1000], inline=False)
        url = (os.getenv("DASHBOARD_URL") or "").rstrip("/")
        if url:
            e.add_field(name="Weben is elbírálható", value=f"[Megnyitás a dashboardon]({url}/szerver/{g.id}/jelentkezesek?j={azon}#j{azon})", inline=False)
        vezeto_id = await db.get(g.id, "vezetorang")
        try:
            uzenet = await csatorna.send(content=f"<@&{vezeto_id}>" if vezeto_id else None, embed=e, view=dontes_nezet("jel", azon),
                                         allowed_mentions=discord.AllowedMentions(roles=True))
        except discord.HTTPException:
            await db.execute("DELETE FROM jelentkezesek WHERE id=?", (azon,))
            raise JelentkezesHiba("A jelentkezést nem sikerült továbbítani a vezetőknek. Szólj egy adminnak.")
        await db.execute("UPDATE jelentkezesek SET uzenet_id=?, csatorna_id=? WHERE id=?", (uzenet.id, csatorna.id, azon))
        return azon

    # ------------------------------------------------------------------ elbírálás (Discord gombok és web közös)
    async def _vezetoi_frissit(self, g: discord.Guild, sor, elfogad: bool, mod, megjegyzes: str | None) -> None:
        """A vezetői csatornában lévő jelentkezés átírása a döntésre (a gombok eltűnnek)."""
        csatorna = g.get_channel(sor["csatorna_id"]) if sor["csatorna_id"] else None
        if csatorna is None or not sor["uzenet_id"]:
            return
        try:
            uzenet = await csatorna.fetch_message(sor["uzenet_id"])
            e = uzenet.embeds[0] if uzenet.embeds else discord.Embed(title=f"Jelentkezés #{sor['id']}")
            e.color = ZOLD if elfogad else PIROS
            e.add_field(name="Döntés", value=f"{'✅ Elfogadva' if elfogad else '❌ Elutasítva'} • {mod.mention}", inline=False)
            if megjegyzes:
                e.add_field(name="Megjegyzés a jelentkezőnek", value=megjegyzes[:1000], inline=False)
            await uzenet.edit(embed=e, view=None)
        except discord.HTTPException:
            pass

    async def _dm_ertesites(self, g: discord.Guild, uid: int, elfogad: bool, megjegyzes: str | None, azon: int, ticket_gomb: bool) -> bool:
        cel = g.get_member(uid)
        if cel is None:
            try:
                cel = await self.bot.fetch_user(uid)
            except discord.HTTPException:
                return False
        db = self.bot.db
        sablon = (await db.get(g.id, "jelentkezes_elfogad_uzenet") or ALAP_ELFOGAD) if elfogad else (await db.get(g.id, "jelentkezes_elutasit_uzenet") or ALAP_ELUTASIT)
        e = discord.Embed(title=f"Jelentkezésed eredménye – {g.name}", color=ZOLD if elfogad else PIROS, timestamp=datetime.now(timezone.utc),
                          description=sablon.replace("{tag}", cel.display_name).replace("{szerver}", g.name)[:3500])
        if megjegyzes:
            e.add_field(name="Üzenet a vezetőktől", value=megjegyzes[:1000], inline=False)
        kwargs = {"embed": e}
        if elfogad and ticket_gomb:
            nezet = discord.ui.View(timeout=None)
            nezet.add_item(JelTicketGomb(azon))
            kwargs["view"] = nezet
        try:
            await cel.send(**kwargs)
            return True
        except discord.HTTPException:
            return False

    async def jelentkezes_dont(self, g: discord.Guild, azon: int, mod, elfogad: bool, megjegyzes: str = "") -> dict:
        """Jelentkezés elbírálása. A mod-nak id és mention attribútuma legyen (Discord-tag vagy webes admin).

        Visszaad: {"dm", "rang", "rang_hiba", "ticket", "ticket_hiba"}. Hibánál JelentkezesHiba.
        """
        db = self.bot.db
        sor = await db.fetchone("SELECT * FROM jelentkezesek WHERE id=? AND guild_id=?", (azon, g.id))
        if not sor:
            raise JelentkezesHiba("A jelentkezés nem található.")
        if sor["statusz"] != "fuggoben":
            raise JelentkezesHiba("Ezt a jelentkezést már elbírálták.")
        megjegyzes = (megjegyzes or "").strip()[:500] or None
        await db.execute("UPDATE jelentkezesek SET statusz=?, dontotte=?, dontes_ido=?, megjegyzes=? WHERE id=? AND statusz='fuggoben'",
                         ("elfogadva" if elfogad else "elutasitva", mod.id, ts(), megjegyzes, azon))
        friss = await db.fetchone("SELECT * FROM jelentkezesek WHERE id=?", (azon,))
        if friss["dontotte"] != mod.id or friss["dontes_ido"] is None:
            raise JelentkezesHiba("Ezt a jelentkezést közben már elbírálta valaki más.")

        eredmeny = {"dm": False, "rang": None, "rang_hiba": False, "ticket": None, "ticket_hiba": None}
        tag = g.get_member(sor["user_id"])
        if elfogad and tag is not None:
            rang_id = await db.get(g.id, "jelentkezes_rang")
            rang = g.get_role(int(rang_id)) if rang_id and str(rang_id).isdigit() else None
            if rang is not None:
                try:
                    await tag.add_roles(rang, reason=f"Elfogadott jelentkezés #{azon}")
                    eredmeny["rang"] = rang.name
                except discord.HTTPException:
                    eredmeny["rang_hiba"] = True
        if elfogad and tag is not None and await db.get(g.id, "jelentkezes_auto_ticket", "0") == "1":
            try:
                eredmeny["ticket"] = await self.jelentkezes_ticket(g, azon, mod)
            except JelentkezesHiba as hiba:
                eredmeny["ticket_hiba"] = str(hiba)
        await self._vezetoi_frissit(g, sor, elfogad, mod, megjegyzes)
        eredmeny["dm"] = await self._dm_ertesites(g, sor["user_id"], elfogad, megjegyzes, azon, ticket_gomb=eredmeny["ticket"] is None)
        e = discord.Embed(title=f"Jelentkezés {'elfogadva' if elfogad else 'elutasítva'} • #{azon}", color=ZOLD if elfogad else PIROS, timestamp=most())
        e.add_field(name="Jelentkező", value=f"<@{sor['user_id']}>")
        e.add_field(name="Döntött", value=mod.mention)
        if megjegyzes:
            e.add_field(name="Megjegyzés", value=megjegyzes, inline=False)
        await naplo(self.bot, g, e)
        return eredmeny

    async def jelentkezes_dontes(self, i: discord.Interaction, azon: int, elfogad: bool):
        """A vezetői csatorna Elfogadás / Elutasítás gombja."""
        await i.response.defer(ephemeral=True)
        try:
            e = await self.jelentkezes_dont(i.guild, azon, i.user, elfogad)
        except JelentkezesHiba as hiba:
            return await i.followup.send(f"❌ {hiba}", ephemeral=True)
        reszek = [f"✅ A jelentkezés {'elfogadva' if elfogad else 'elutasítva'}.",
                  "A jelentkező privátban értesítést kapott." if e["dm"] else "A jelentkezőnek nem sikerült privátban értesítést küldeni."]
        if e["rang"]:
            reszek.append(f"Megkapta a(z) {e['rang']} rangot.")
        if e["rang_hiba"]:
            reszek.append("A rangot nem sikerült kiosztani (a bot rangja legyen magasabb).")
        if e["ticket"] is not None:
            reszek.append(f"Ticket megnyitva: {e['ticket'].mention}")
        if e["ticket_hiba"]:
            reszek.append(f"A ticket nem nyílt meg: {e['ticket_hiba']}")
        await i.followup.send(" ".join(reszek), ephemeral=True)

    # ------------------------------------------------------------------ ticket az elfogadottnak
    async def jelentkezes_ticket(self, g: discord.Guild, azon: int, mod) -> discord.TextChannel:
        """Ticket nyitása az elfogadott jelentkezőnek (a válaszai bekerülnek a ticketbe). Hibánál JelentkezesHiba."""
        db, ticket = self.bot.db, self.bot.get_cog("Ticket")
        sor = await db.fetchone("SELECT * FROM jelentkezesek WHERE id=? AND guild_id=?", (azon, g.id))
        if not sor:
            raise JelentkezesHiba("A jelentkezés nem található.")
        if sor["statusz"] != "elfogadva":
            raise JelentkezesHiba("Csak elfogadott jelentkezőnek nyitható ticket.")
        if sor["ticket_csatorna_id"] and g.get_channel(sor["ticket_csatorna_id"]):
            raise JelentkezesHiba("Ehhez a jelentkezéshez már megnyílt a ticket.")
        tag = g.get_member(sor["user_id"])
        if tag is None:
            raise JelentkezesHiba("A jelentkező nincs a szerveren.")
        kulcs = await db.get(g.id, "jelentkezes_ticket_tipus") or "staff_jelentkezes"
        kat = await ticket.kategoria(g.id, kulcs)
        if kat is None or not kat["aktiv"]:
            kat = next(iter(await ticket.kategoriak(g.id)), None)
        if kat is None:
            raise JelentkezesHiba("Nincs elérhető ticket-típus. Hozz létre egyet a Ticketek oldalon.")
        try:
            valaszok = json.loads(sor["valaszok"])
        except ValueError:
            valaszok = {}
        try:
            csatorna = await ticket.ticket_nyit(g, tag, kat, valaszok, kezdemenyezett=True,
                                                extra=[("Jelentkezés", f"#{azon} (elfogadva)", True)])
        except TicketHiba as hiba:
            raise JelentkezesHiba(str(hiba))
        await db.execute("UPDATE jelentkezesek SET ticket_csatorna_id=? WHERE id=?", (csatorna.id, azon))
        return csatorna

    async def ticket_gomb(self, i: discord.Interaction, azon: int):
        """A „Ticket nyitása” gomb az elfogadó privát üzenetben: csak maga a jelentkező használhatja."""
        sor = await self.bot.db.fetchone("SELECT * FROM jelentkezesek WHERE id=?", (azon,))
        if not sor or sor["user_id"] != i.user.id:
            return await i.response.send_message("❌ Ez a gomb nem hozzád tartozik.", ephemeral=True)
        g = self.bot.get_guild(sor["guild_id"])
        if g is None:
            return await i.response.send_message("❌ A szerver most nem érhető el.", ephemeral=True)
        await i.response.defer(ephemeral=True)
        try:
            csatorna = await self.jelentkezes_ticket(g, azon, SimpleNamespace(id=i.user.id, mention=i.user.mention, display_name=i.user.display_name))
        except JelentkezesHiba as hiba:
            return await i.followup.send(f"❌ {hiba}", ephemeral=True)
        await i.followup.send(f"✅ A ticketed megnyílt: {csatorna.mention}", ephemeral=True)

    # ------------------------------------------------------------------ teljesítmény
    async def adatok(self, guild: discord.Guild, user_id: int, tol: datetime, ig: datetime) -> dict:
        """Egy staff tag teljesítménye a [tol, ig) időszakban."""
        db = self.bot.db
        shift = self.bot.get_cog("Shift")
        inakt = self.bot.get_cog("Inaktivitas")
        tol_ts, ig_ts = tol.timestamp(), ig.timestamp()
        tol_iso, ig_iso = _iso_ts(tol_ts), _iso_ts(ig_ts)

        ticket = await db.fetchone(
            "SELECT COUNT(*) AS db, AVG(ertekeles) AS atlag FROM ticketek "
            "WHERE guild_id=? AND atvette=? AND letrehozva>=? AND letrehozva<?",
            (guild.id, user_id, tol_iso, ig_iso),
        )
        szankcio = await db.fetchone(
            "SELECT COUNT(*) AS db FROM szankciok WHERE guild_id=? AND moderator_id=? AND letrehozva>=? AND letrehozva<? "
            "AND tipus IN ('warn', 'timeout', 'kick', 'ban')",
            (guild.id, user_id, tol_iso, ig_iso),
        )
        pont = await db.fetchone(
            "SELECT pont, megjegyzes FROM staff_pontok WHERE guild_id=? AND user_id=? AND honap=?",
            (guild.id, user_id, tol.astimezone(IDOZONA).strftime("%Y-%m")),
        )
        return {
            "shift_mp": await shift.ossz_mp(guild.id, user_id, tol_ts, ig_ts),
            "ticket": ticket["db"],
            "ertekeles": ticket["atlag"],
            "szankcio": szankcio["db"],
            "inaktiv_mp": await inakt.inaktiv_mp(guild.id, user_id, tol_ts, ig_ts),
            "pont": pont["pont"] if pont else None,
            "megjegyzes": pont["megjegyzes"] if pont else None,
        }

    async def staff_tagok(self, guild: discord.Guild) -> list[discord.Member]:
        rang_id = await self.bot.db.get(guild.id, "staffrang")
        rang = guild.get_role(int(rang_id)) if rang_id else None
        return [t for t in rang.members if not t.bot] if rang else []

    async def havi_riport(self, guild: discord.Guild, tol: datetime, ig: datetime) -> list[discord.Embed]:
        tagok = await self.staff_tagok(guild)
        if not tagok:
            return []
        sorok = []
        for tag in tagok:
            sorok.append((tag, await self.adatok(guild, tag.id, tol, ig)))
        sorok.sort(key=lambda x: x[1]["shift_mp"], reverse=True)

        sorok_szoveg = []
        for n, (tag, a) in enumerate(sorok, 1):
            ertek = f" • ⭐ {a['ertekeles']:.1f}" if a["ertekeles"] else ""
            pont = f" • pont: **{a['pont']}/5**" if a["pont"] else ""
            inaktiv = f" • 🌴 {a['inaktiv_mp'] // 86400} nap" if a["inaktiv_mp"] >= 86400 else ""
            sorok_szoveg.append(
                f"**{n}.** {tag.mention} • ⏱️ {ido_szoveg(a['shift_mp'])} • 🎫 {a['ticket']} • 🔨 {a['szankcio']}"
                f"{ertek}{pont}{inaktiv}"
            )
        cim = f"📊 Staff riport – {tol.astimezone(IDOZONA):%Y.%m.%d.} – {(ig - timedelta(seconds=1)).astimezone(IDOZONA):%Y.%m.%d.}"
        embedek = []
        for k in range(0, len(sorok_szoveg), 15):
            e = discord.Embed(title=cim if k == 0 else None, description="\n".join(sorok_szoveg[k:k + 15]), color=KEK)
            embedek.append(e)
        embedek[-1].set_footer(text="⏱️ szolgálati idő • 🎫 átvett ticket • 🔨 kiadott szankció • ⭐ ticket értékelés átlaga")
        return embedek

    # ------------------------------------------------------------------ automatikus riportok
    @tasks.loop(hours=1)
    async def automata(self):
        most_ = datetime.now(IDOZONA)
        if most_.hour < 8:
            return
        db = self.bot.db
        for guild in self.bot.guilds:
            csatorna = await csatorna_kap(self.bot, guild, "vezetoi_csatorna")
            if csatorna is None:
                continue
            # Havonta egyszer (a hónap első napján): az előző hónap riportja
            kulcs = most_.strftime("%Y-%m")
            if most_.day == 1 and await db.get(guild.id, "staff_riport_utolso") != kulcs:
                await db.set(guild.id, "staff_riport_utolso", kulcs)
                embedek = await self.havi_riport(guild, elozo_honap_kezdete(), honap_kezdete())
                for k in range(0, len(embedek), 10):
                    await csatorna.send(embeds=embedek[k:k + 10])
            # Hetente egyszer (hétfőn): ki maradt el a minimális szolgálati időtől
            if most_.weekday() == 0 and await db.get(guild.id, "staff_heti_utolso") != most_.strftime("%Y-%m-%d"):
                await db.set(guild.id, "staff_heti_utolso", most_.strftime("%Y-%m-%d"))
                await self.minimum_ellenorzes(guild, csatorna)

    @automata.before_loop
    async def _var(self):
        await self.bot.wait_until_ready()

    async def minimum_ellenorzes(self, guild: discord.Guild, csatorna: discord.TextChannel):
        minimum = int(await self.bot.db.get(guild.id, "staff_minimum_ora", 0))
        if not minimum:
            return
        ig = het_kezdete()
        tol = ig - timedelta(days=7)
        shift, inakt = self.bot.get_cog("Shift"), self.bot.get_cog("Inaktivitas")
        keves = []
        for tag in await self.staff_tagok(guild):
            if await inakt.inaktiv_mp(guild.id, tag.id, tol.timestamp(), ig.timestamp()) >= 3 * 86400:
                continue  # a héten jelentős részben igazoltan inaktív volt
            mp = await shift.ossz_mp(guild.id, tag.id, tol.timestamp(), ig.timestamp())
            if mp < minimum * 3600:
                keves.append(f"{tag.mention} • {ido_szoveg(mp)} / {minimum} ó")
        if not keves:
            return
        e = discord.Embed(
            title="⚠️ Minimális szolgálati idő nem teljesítve",
            description="A múlt héten nem érték el a heti minimumot:\n" + "\n".join(keves)[:3800],
            color=SARGA,
        )
        await csatorna.send(embed=e)

    # ------------------------------------------------------------------ parancsok
    staff = app_commands.Group(name="staff", description="Staff jelentkezés és értékelés.", guild_only=True)

    @staff.command(name="jelentkezes", description="Jelentkezés staff pozícióra (a bot privát üzenetben kérdez).")
    async def jelentkezes(self, i: discord.Interaction):
        await self.dm_inditas(i)

    @app_commands.command(name="jelentkezes", description="Jelentkezés: a bot privát üzenetben felteszi a kérdéseket.")
    @app_commands.guild_only()
    async def jelentkezes_gyors(self, i: discord.Interaction):
        await self.dm_inditas(i)

    @staff.command(name="panel", description="A jelentkezési panel kihelyezése egy csatornába.")
    @app_commands.describe(csatorna="Ide kerül a Jelentkezem gombos panel")
    @app_commands.checks.has_permissions(administrator=True)
    async def panel(self, i: discord.Interaction, csatorna: discord.TextChannel):
        try:
            await self.panel_kozzetesz(i.guild, csatorna)
        except discord.HTTPException:
            return await i.response.send_message("❌ Nem tudok írni ebbe a csatornába.", ephemeral=True)
        await i.response.send_message(f"✅ A jelentkezési panel kikerült ide: {csatorna.mention}", ephemeral=True)

    @staff.command(name="teljesitmeny", description="Egy staff tag teljesítményének megtekintése.")
    @app_commands.describe(tag="Kinek a teljesítményét nézed (alapból a sajátodat)", honap="Melyik hónapot nézzük")
    @app_commands.choices(honap=[
        app_commands.Choice(name="Ez a hónap", value="most"), app_commands.Choice(name="Előző hónap", value="elozo"),
    ])
    @staff_only()
    async def teljesitmeny(
        self, i: discord.Interaction, tag: discord.Member | None = None, honap: app_commands.Choice[str] | None = None
    ):
        tag = tag or i.user
        if tag.id != i.user.id and not await vezeto_e(self.bot, i.user):
            return await i.response.send_message("❌ Más teljesítményét csak a vezetők láthatják.", ephemeral=True)
        if honap and honap.value == "elozo":
            tol, ig = elozo_honap_kezdete(), honap_kezdete()
        else:
            tol, ig = honap_kezdete(), datetime.now(IDOZONA) + timedelta(seconds=1)
        a = await self.adatok(i.guild, tag.id, tol, ig)
        e = discord.Embed(title=f"Teljesítmény – {tag.display_name}", description=f"{tol:%Y. %m.} hónap", color=KEK)
        e.set_thumbnail(url=tag.display_avatar.url)
        e.add_field(name="⏱️ Szolgálati idő", value=ido_szoveg(a["shift_mp"]))
        e.add_field(name="🎫 Átvett ticketek", value=str(a["ticket"]))
        e.add_field(name="🔨 Kiadott szankciók", value=str(a["szankcio"]))
        e.add_field(name="⭐ Ticket értékelés", value=f"{a['ertekeles']:.1f} / 5" if a["ertekeles"] else "–")
        e.add_field(name="🌴 Igazolt inaktivitás", value=f"{a['inaktiv_mp'] // 86400} nap")
        e.add_field(name="📋 Vezetői pontszám", value=f"{a['pont']} / 5" if a["pont"] else "még nincs")
        if a["megjegyzes"]:
            e.add_field(name="Vezetői megjegyzés", value=a["megjegyzes"], inline=False)
        await i.response.send_message(embed=e, ephemeral=True)

    @staff.command(name="riport", description="Az aktuális havi staff riport azonnali megjelenítése.")
    @vezeto_only()
    async def riport(self, i: discord.Interaction):
        await i.response.defer(ephemeral=True)
        embedek = await self.havi_riport(i.guild, honap_kezdete(), datetime.now(IDOZONA) + timedelta(seconds=1))
        if not embedek:
            return await i.followup.send("❌ Nincs staff tag (állítsd be a `/beallitas staffrang` rangot).", ephemeral=True)
        for k in range(0, len(embedek), 10):
            await i.followup.send(embeds=embedek[k:k + 10], ephemeral=True)

    @staff.command(name="pontozas", description="Egy staff tag havi pontozása (csak vezetőknek).")
    @app_commands.describe(tag="Akit pontozol", pont="1–5 pont", megjegyzes="Rövid indoklás vagy visszajelzés")
    @vezeto_only()
    async def pontozas(
        self, i: discord.Interaction, tag: discord.Member, pont: app_commands.Range[int, 1, 5],
        megjegyzes: app_commands.Range[str, 0, 400] = "",
    ):
        if tag.id == i.user.id:
            return await i.response.send_message("❌ Magadat nem pontozhatod.", ephemeral=True)
        honap = datetime.now(IDOZONA).strftime("%Y-%m")
        await self.bot.db.execute(
            "INSERT INTO staff_pontok (guild_id, user_id, honap, pont, megjegyzes, pontozo) VALUES (?, ?, ?, ?, ?, ?) "
            "ON CONFLICT(guild_id, user_id, honap) DO UPDATE SET pont=excluded.pont, "
            "megjegyzes=excluded.megjegyzes, pontozo=excluded.pontozo",
            (i.guild.id, tag.id, honap, pont, megjegyzes or None, i.user.id),
        )
        await i.response.send_message(f"✅ {tag.mention} pontszáma erre a hónapra: **{pont}/5**", ephemeral=True)

    @staff.command(name="beallit", description="A jelentkezési csatorna és a heti minimális szolgálati idő beállítása.")
    @app_commands.describe(
        jelentkezesek="Ide érkeznek a jelentkezések (alapból a vezetői csatorna)",
        minimum_ora="Heti minimális szolgálati idő órában (0 = kikapcsolva)",
    )
    @app_commands.checks.has_permissions(administrator=True)
    async def beallit(
        self, i: discord.Interaction, jelentkezesek: discord.TextChannel | None = None,
        minimum_ora: app_commands.Range[int, 0, 100] | None = None,
    ):
        if jelentkezesek is None and minimum_ora is None:
            return await i.response.send_message("Adj meg legalább egy értéket.", ephemeral=True)
        if jelentkezesek:
            await self.bot.db.set(i.guild.id, "jelentkezes_csatorna", str(jelentkezesek.id))
        if minimum_ora is not None:
            await self.bot.db.set(i.guild.id, "staff_minimum_ora", str(minimum_ora))
        await i.response.send_message("✅ A staff beállítások mentve.", ephemeral=True)


async def setup(bot):
    await bot.add_cog(Staff(bot))
