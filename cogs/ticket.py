"""Ticket rendszer: testreszabható kategóriák (adatbázisból), űrlapkérdések, átvétel, HTML átirat, értékelés."""
import asyncio
import html
import io
import re
import unicodedata

import discord
from discord import app_commands
from discord.ext import commands

from util import IDOZONA, KEK, SARGA, ZOLD, most, naplo, staff_e, staff_only

# Az első használatkor ezekkel töltődik fel egy szerver kategórialistája. Utána a dashboardon szabadon szerkeszthető.
ALAP_KATEGORIAK = [
    ("tamogatas", "Támogatás", "🛠️", "Általános kérdés vagy segítségkérés."),
    ("panasz", "Panasz", "📢", "Panasz egy játékosra vagy staff tagra."),
    ("jatekos_jelentes", "Játékos jelentése", "🚨", "Szabályszegő játékos jelentése bizonyítékkal."),
    ("staff_jelentkezes", "Staff jelentkezés", "📝", "Jelentkezés staff pozícióra."),
    ("fellebbezes", "Fellebbezés", "⚖️", "Szankció (némítás, kitiltás) fellebbezése."),
]
ALAP_PANEL_CIM = "🎫 Ticket rendszer"
ALAP_PANEL_LEIRAS = ("Segítségre van szükséged, jelentenél valamit, vagy fellebbeznél egy büntetés ellen?\n"
                     "Válaszd ki lent a megfelelő típust, és külön csatornát nyitunk neked.")
ALAP_UDVOZLO = ("Köszönjük, hogy megkerestél minket! Írd le részletesen a kérésedet vagy a problémádat, "
                "és egy staff tag hamarosan válaszol.\nHa jelentést teszel, csatolj képet vagy videót bizonyítékként.")
MAX_KATEGORIA = 25  # a Discord legördülő menüje legfeljebb ennyi elemet bír


class TicketHiba(Exception):
    """Olvasható hibaüzenettel jelzi, hogy a ticket nem nyitható meg (a szöveg közvetlenül megjeleníthető)."""


def kulcs_keszit(nev: str) -> str:
    """Szépen olvasható, csatornanévnek is jó azonosító: 'Játékos jelentése' -> 'jatekos-jelentese'."""
    s = unicodedata.normalize("NFKD", nev.lower())
    s = "".join(c for c in s if not unicodedata.combining(c))
    return re.sub(r"[^a-z0-9]+", "-", s).strip("-")[:25] or "ticket"


def szin_ertek(szoveg: str | None, alap: discord.Color = KEK) -> discord.Color:
    if szoveg and re.fullmatch(r"#?[0-9a-fA-F]{6}", szoveg.strip()):
        return discord.Color(int(szoveg.strip().lstrip("#"), 16))
    return alap


def emoji_ertek(szoveg: str | None):
    return discord.PartialEmoji.from_str(szoveg.strip()) if szoveg and szoveg.strip() else None


class PanelNezet(discord.ui.View):
    """A ticket panel legördülő menüje. A menüpontok szerverenként az adatbázisból jönnek."""

    def __init__(self, opciok: list[discord.SelectOption] | None = None):
        super().__init__(timeout=None)
        if opciok:
            self.valaszt.options = opciok

    @discord.ui.select(
        custom_id="ticket:kategoria", placeholder="Válaszd ki a ticket típusát…",
        options=[discord.SelectOption(label="Ticket", value="ticket")],
    )
    async def valaszt(self, i: discord.Interaction, menu: discord.ui.Select):
        await i.client.get_cog("Ticket").megnyit(i, i.data["values"][0])


class KerdesModal(discord.ui.Modal):
    """A kategóriához beállított kérdések (legfeljebb 5), amelyeket ticketnyitás előtt kell kitölteni."""

    def __init__(self, kategoria, kerdesek: list[str]):
        super().__init__(title=kategoria["nev"][:45])
        self.kategoria = kategoria
        self.mezok: list[tuple[str, discord.ui.TextInput]] = []
        for kerdes in kerdesek[:5]:
            mezo = discord.ui.TextInput(
                label=kerdes[:45], max_length=900,
                style=discord.TextStyle.short if len(kerdes) < 30 else discord.TextStyle.paragraph,
            )
            self.add_item(mezo)
            self.mezok.append((kerdes, mezo))

    async def on_submit(self, i: discord.Interaction):
        await i.client.get_cog("Ticket").ticket_letrehoz(i, self.kategoria, {k: str(m) for k, m in self.mezok})


class LezarModal(discord.ui.Modal, title="Ticket lezárása"):
    indok = discord.ui.TextInput(
        label="Lezárás oka", style=discord.TextStyle.paragraph, required=False, max_length=300,
        placeholder="Pl. a probléma megoldódott.",
    )

    async def on_submit(self, i: discord.Interaction):
        await i.client.get_cog("Ticket").lezar(i, str(self.indok).strip() or "Nincs megadva")


class TicketNezet(discord.ui.View):
    """A ticketcsatornában megjelenő gombok."""

    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="Átveszem", emoji="🙋", style=discord.ButtonStyle.success, custom_id="ticket:atvesz")
    async def atvesz(self, i: discord.Interaction, gomb: discord.ui.Button):
        await i.client.get_cog("Ticket").atvesz(i)

    @discord.ui.button(label="Lezárás", emoji="🔒", style=discord.ButtonStyle.danger, custom_id="ticket:lezar")
    async def lezar(self, i: discord.Interaction, gomb: discord.ui.Button):
        cog = i.client.get_cog("Ticket")
        t = await cog.ticket(i.channel.id)
        if not t or not t["nyitva"]:
            return await i.response.send_message("❌ Ez nem egy nyitott ticket.", ephemeral=True)
        if i.user.id != t["user_id"] and not await cog.kezelo_e(i.user, t):
            return await i.response.send_message("❌ A ticketet csak a nyitója vagy a kezelők zárhatják le.", ephemeral=True)
        await i.response.send_modal(LezarModal())


class ErtekelGomb(discord.ui.DynamicItem[discord.ui.Button], template=r"ticket:ertek:(?P<id>\d+):(?P<pont>[1-5])"):
    """1–5 csillagos értékelés a lezárás utáni üzenetben (újraindítás után is működik)."""

    def __init__(self, ticket_id: int, pont: int):
        super().__init__(discord.ui.Button(
            label="⭐" * pont, style=discord.ButtonStyle.secondary, custom_id=f"ticket:ertek:{ticket_id}:{pont}"
        ))
        self.ticket_id, self.pont = ticket_id, pont

    @classmethod
    async def from_custom_id(cls, i: discord.Interaction, item: discord.ui.Button, match):
        return cls(int(match["id"]), int(match["pont"]))

    async def callback(self, i: discord.Interaction):
        db = i.client.db
        t = await db.fetchone("SELECT user_id, ertekeles FROM ticketek WHERE id=?", (self.ticket_id,))
        if not t or t["user_id"] != i.user.id:
            return await i.response.send_message("❌ Ezt a ticketet nem te nyitottad.", ephemeral=True)
        if t["ertekeles"]:
            return await i.response.edit_message(content="Ezt a ticketet már értékelted. Köszönjük!", view=None)
        await db.execute("UPDATE ticketek SET ertekeles=? WHERE id=?", (self.pont, self.ticket_id))
        await i.response.edit_message(content=f"Köszönjük az értékelést! {'⭐' * self.pont}", view=None)


def ertekelo_nezet(ticket_id: int) -> discord.ui.View:
    nezet = discord.ui.View(timeout=None)
    for pont in range(1, 6):
        nezet.add_item(ErtekelGomb(ticket_id, pont))
    return nezet


class Ticket(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    async def cog_load(self):
        self.bot.add_view(PanelNezet())
        self.bot.add_view(TicketNezet())
        self.bot.add_dynamic_items(ErtekelGomb)

    async def ticket(self, csatorna_id: int):
        return await self.bot.db.fetchone("SELECT * FROM ticketek WHERE csatorna_id=?", (csatorna_id,))

    # ------------------------------------------------------------------ kategóriák
    async def kategoriak(self, guild_id: int, csak_aktiv: bool = True):
        """A szerver ticket-kategóriái. Az első lekéréskor az alapértelmezett lista kerül be."""
        db = self.bot.db
        if await db.get(guild_id, "ticket_kat_init") is None:
            van = await db.fetchone("SELECT COUNT(*) AS n FROM ticket_kategoriak WHERE guild_id=?", (guild_id,))
            if van["n"] == 0:
                for sorrend, (kulcs, nev, emoji, leiras) in enumerate(ALAP_KATEGORIAK):
                    await db.execute(
                        "INSERT INTO ticket_kategoriak (guild_id, kulcs, nev, emoji, leiras, sorrend) VALUES (?, ?, ?, ?, ?, ?)",
                        (guild_id, kulcs, nev, emoji, leiras, sorrend),
                    )
            await db.set(guild_id, "ticket_kat_init", "1")
        return await db.fetchall(
            "SELECT * FROM ticket_kategoriak WHERE guild_id=?" + (" AND aktiv=1" if csak_aktiv else "") + " ORDER BY sorrend, id",
            (guild_id,),
        )

    async def kategoria(self, guild_id: int, kulcs: str):
        await self.kategoriak(guild_id)  # biztosítja az alapértelmezett lista létrejöttét
        return await self.bot.db.fetchone(
            "SELECT * FROM ticket_kategoriak WHERE guild_id=? AND kulcs=?", (guild_id, kulcs)
        )

    async def kat_nev(self, guild_id: int, kulcs: str) -> str:
        kat = await self.kategoria(guild_id, kulcs)
        return kat["nev"] if kat else kulcs

    async def kezelo_e(self, tag: discord.Member, t) -> bool:
        """Kezelheti-e a tag a ticketet: staff, vagy a kategória kezelő rangjának tagja."""
        if await staff_e(self.bot, tag):
            return True
        kat = await self.kategoria(tag.guild.id, t["kategoria"])
        return bool(kat and kat["rang_id"] and any(r.id == kat["rang_id"] for r in tag.roles))

    # ------------------------------------------------------------------ panel
    async def panel_nezet(self, guild_id: int) -> PanelNezet:
        opciok = [
            discord.SelectOption(
                label=k["nev"][:100], value=k["kulcs"], emoji=emoji_ertek(k["emoji"]), description=(k["leiras"] or None) and k["leiras"][:100]
            )
            for k in (await self.kategoriak(guild_id))[:MAX_KATEGORIA]
        ]
        return PanelNezet(opciok or [discord.SelectOption(label="Nincs elérhető ticket-típus", value="ticket")])

    async def panel_embed(self, guild_id: int) -> discord.Embed:
        db = self.bot.db
        kat_sorok = "\n".join(
            f"{k['emoji'] or '▫️'} **{k['nev']}**" + (f" – {k['leiras']}" if k["leiras"] else "")
            for k in await self.kategoriak(guild_id)
        )
        leiras = await db.get(guild_id, "ticket_panel_leiras", ALAP_PANEL_LEIRAS)
        return discord.Embed(
            title=await db.get(guild_id, "ticket_panel_cim", ALAP_PANEL_CIM),
            description=f"{leiras}\n\n{kat_sorok}\n\nKérjük, ne nyiss feleslegesen ticketet, és légy türelmes.",
            color=szin_ertek(await db.get(guild_id, "ticket_panel_szin")),
        )

    async def panel_kozzetesz(self, guild: discord.Guild, csatorna: discord.TextChannel) -> discord.Message:
        uzenet = await csatorna.send(embed=await self.panel_embed(guild.id), view=await self.panel_nezet(guild.id))
        await self.bot.db.set(guild.id, "ticket_panel", f"{csatorna.id}:{uzenet.id}")
        return uzenet

    async def panel_frissit(self, guild: discord.Guild) -> bool:
        """A korábban kihelyezett panel átírása az aktuális kategóriákra és megjelenésre."""
        ertek = await self.bot.db.get(guild.id, "ticket_panel")
        if not ertek:
            return False
        csatorna_id, uzenet_id = (int(x) for x in ertek.split(":"))
        csatorna = guild.get_channel(csatorna_id)
        if csatorna is None:
            return False
        try:
            uzenet = await csatorna.fetch_message(uzenet_id)
            await uzenet.edit(embed=await self.panel_embed(guild.id), view=await self.panel_nezet(guild.id))
        except discord.HTTPException:
            return False
        return True

    # ------------------------------------------------------------------ megnyitás
    async def megnyit(self, i: discord.Interaction, kulcs: str):
        kat = await self.kategoria(i.guild.id, kulcs)
        if not kat or not kat["aktiv"]:
            await i.response.send_message("❌ Ez a ticket-típus már nem elérhető.", ephemeral=True)
            return await self._panel_visszaallit(i)
        kerdesek = [k.strip() for k in kat["kerdesek"].splitlines() if k.strip()][:5]
        if kerdesek:
            await i.response.send_modal(KerdesModal(kat, kerdesek))
            return await self._panel_visszaallit(i)
        await self._panel_visszaallit(i)
        await self.ticket_letrehoz(i, kat, {})

    async def _panel_visszaallit(self, i: discord.Interaction):
        """A menü a kiválasztott értéken maradna, ezért friss nézetre cseréljük az üzenetet."""
        try:
            await i.message.edit(view=await self.panel_nezet(i.guild.id))
        except (discord.HTTPException, AttributeError):
            pass

    async def ticket_nyit(self, g: discord.Guild, tag: discord.Member, kat, valaszok: dict, *,
                          kezdemenyezett: bool = False, extra: list | None = None) -> discord.TextChannel:
        """Ticket megnyitása egy tagnak (Discord-interakció nélkül, a web és a jelentkezés is ezt használja).

        kezdemenyezett: a staff nyitotta a tagnak, ilyenkor nem korlátoz az egyszerre nyitható ticketek száma.
        extra: további mezők a nyitóüzenetben, (név, érték, soron belüli) hármasokként. Hibánál TicketHiba.
        """
        db = self.bot.db
        if not kezdemenyezett:
            max_nyitott = int(await db.get(g.id, "ticket_max_nyitott", 1))
            nyitottak = await db.fetchall("SELECT id, csatorna_id FROM ticketek WHERE guild_id=? AND user_id=? AND nyitva=1", (g.id, tag.id))
            el = []
            for t in nyitottak:
                if t["csatorna_id"] and g.get_channel(t["csatorna_id"]):
                    el.append(t["csatorna_id"])
                else:  # árva rekord: a csatornát időközben törölték
                    await db.execute("UPDATE ticketek SET nyitva=0, lezarva=? WHERE id=?", (most().isoformat(), t["id"]))
            if len(el) >= max_nyitott:
                raise TicketHiba(f"Elérted az egyszerre nyitható ticketek számát ({max_nyitott}): " + ", ".join(f"<#{c}>" for c in el))

        staff_id = await db.get(g.id, "staffrang")
        kezelo = g.get_role(kat["rang_id"]) if kat["rang_id"] else None
        kezelo = kezelo or (g.get_role(int(staff_id)) if staff_id else None)
        if kezelo is None:
            raise TicketHiba("A ticket rendszer még nincs beállítva. Egy adminisztrátor állítsa be a staff rangot.")
        kategoria_csatorna = None
        for ertek in (kat["discord_kategoria_id"], await db.get(g.id, "ticket_kategoria")):
            if ertek and (kategoria_csatorna := g.get_channel(int(ertek))):
                break

        ugy = await db.execute(
            "INSERT INTO ticketek (guild_id, user_id, kategoria, letrehozva) VALUES (?, ?, ?, ?)",
            (g.id, tag.id, kat["kulcs"], most().isoformat()),
        )
        olvas = dict(view_channel=True, send_messages=True, attach_files=True, read_message_history=True, embed_links=True)
        jogok = {
            g.default_role: discord.PermissionOverwrite(view_channel=False),
            tag: discord.PermissionOverwrite(**olvas),
            kezelo: discord.PermissionOverwrite(**olvas, manage_messages=True),
            g.me: discord.PermissionOverwrite(**olvas, manage_channels=True, manage_messages=True),
        }
        try:
            csatorna = await g.create_text_channel(
                f"{kat['kulcs']}-{ugy:04d}", category=kategoria_csatorna if isinstance(kategoria_csatorna, discord.CategoryChannel) else None,
                overwrites=jogok, topic=f"Ticket #{ugy:04d} • {kat['nev']} • {tag}",
            )
        except discord.HTTPException:
            await db.execute("DELETE FROM ticketek WHERE id=?", (ugy,))
            raise TicketHiba("A ticketet nem sikerült létrehozni (a botnak nincs csatornakezelési jogosultsága).")
        await db.execute("UPDATE ticketek SET csatorna_id=? WHERE id=?", (csatorna.id, ugy))

        e = discord.Embed(
            title=f"{kat['emoji'] or '🎫'} {kat['nev']} • #{ugy:04d}",
            description=(kat["udvozlo"] or ALAP_UDVOZLO).replace("{tag}", tag.mention),
            color=szin_ertek(kat["szin"]), timestamp=most(),
        )
        e.add_field(name="Nyitotta", value=tag.mention)
        e.add_field(name="Kategória", value=kat["nev"])
        for nev, ertek, sorban in extra or []:
            e.add_field(name=str(nev)[:256], value=str(ertek)[:1000] or "–", inline=sorban)
        for kerdes, valasz in valaszok.items():
            e.add_field(name=kerdes[:256], value=valasz[:1000] or "–", inline=False)
        # A ping a tartalomban van (a beágyazáson kívül), így tényleg értesít.
        await csatorna.send(content=f"{tag.mention} {kezelo.mention}", embed=e, view=TicketNezet())
        # Partnerségi ticketnél a partner modul veszi át a folyamatot (szöveg bekérése, ellenőrzés, ping-javaslat).
        if (partner := self.bot.get_cog("Partner")) and kat["kulcs"] == await partner.ticket_tipus(g.id):
            await partner.inditas(g, csatorna, tag, ugy)
        return csatorna

    async def ticket_letrehoz(self, i: discord.Interaction, kat, valaszok: dict):
        await i.response.defer(ephemeral=True)
        try:
            csatorna = await self.ticket_nyit(i.guild, i.user, kat, valaszok)
        except TicketHiba as hiba:
            return await i.followup.send(f"❌ {hiba}", ephemeral=True)
        await i.followup.send(f"✅ A ticketed megnyílt: {csatorna.mention}", ephemeral=True)

    # ------------------------------------------------------------------ átvétel
    async def atvesz(self, i: discord.Interaction):
        t = await self.ticket(i.channel.id)
        if not t or not t["nyitva"]:
            return await i.response.send_message("❌ Ez nem egy nyitott ticket.", ephemeral=True)
        if not await self.kezelo_e(i.user, t):
            return await i.response.send_message("❌ Ezt csak a kezelők teheti meg.", ephemeral=True)
        if t["atvette"]:
            return await i.response.send_message(f"❌ Ezt a ticketet már átvette <@{t['atvette']}>.", ephemeral=True)
        await self.bot.db.execute(
            "UPDATE ticketek SET atvette=?, atvetel_ido=? WHERE id=?", (i.user.id, most().isoformat(), t["id"])
        )
        nezet = TicketNezet()
        nezet.atvesz.disabled = True
        e = i.message.embeds[0]
        e.add_field(name="Átvette", value=i.user.mention)
        await i.response.edit_message(embed=e, view=nezet)
        await i.followup.send(f"🙋 {i.user.mention} átvette a ticketet.")

    # ------------------------------------------------------------------ lezárás
    async def atirat(self, csatorna: discord.TextChannel, t, kat_nev: str, lezaro: discord.abc.User, indok: str) -> str:
        """A ticket teljes beszélgetése önálló, szépen formázott HTML fájlként."""
        esc = html.escape
        uzenetek = []
        async for m in csatorna.history(limit=None, oldest_first=True):
            ido = m.created_at.astimezone(IDOZONA).strftime("%Y.%m.%d. %H:%M:%S")
            torzs = esc(m.clean_content).replace("\n", "<br>")
            for emb in m.embeds:
                reszek = [esc(x) for x in (emb.title, emb.description) if x]
                reszek += [f"<b>{esc(f.name)}</b>: {esc(f.value)}" for f in emb.fields]
                if reszek:
                    torzs += f'<div class="beagyazas">{"<br>".join(reszek)}</div>'
            for fajl in m.attachments:
                torzs += f'<div class="csatolmany">📎 <a href="{esc(fajl.url)}">{esc(fajl.filename)}</a></div>'
            if not torzs:
                continue
            bot_jelzo = ' <span class="bot">BOT</span>' if m.author.bot else ""
            uzenetek.append(
                f'<div class="uzenet"><img src="{esc(m.author.display_avatar.url)}" alt="">'
                f'<div><b>{esc(m.author.display_name)}</b>{bot_jelzo} '
                f'<span class="ido">{ido}</span><div>{torzs}</div></div></div>'
            )
        return f"""<!doctype html><html lang="hu"><head><meta charset="utf-8">
<title>Ticket #{t['id']:04d} átirat</title><style>
body{{background:#313338;color:#dbdee1;font:15px/1.5 system-ui,sans-serif;margin:0;padding:24px}}
.fejlec{{background:#2b2d31;border-radius:8px;padding:16px 20px;margin-bottom:20px;max-width:900px}}
.fejlec h1{{margin:0 0 8px;font-size:20px}}.fejlec div{{color:#949ba4}}
.uzenet{{display:flex;gap:12px;padding:8px 0;max-width:900px}}.uzenet img{{width:40px;height:40px;border-radius:50%}}
.ido{{color:#949ba4;font-size:12px;margin-left:6px}}.bot{{background:#5865f2;color:#fff;border-radius:3px;font-size:10px;padding:1px 4px}}
.beagyazas{{border-left:4px solid #5865f2;background:#2b2d31;padding:8px 12px;margin-top:4px;border-radius:0 4px 4px 0}}
.csatolmany{{margin-top:4px}}a{{color:#00a8fc}}
</style></head><body><div class="fejlec"><h1>🎫 Ticket #{t['id']:04d} – {esc(kat_nev)}</h1>
<div>Nyitotta: {esc(str(t['user_id']))} • Lezárta: {esc(lezaro.display_name)} • Lezárva: {most().astimezone(IDOZONA):%Y.%m.%d. %H:%M}</div>
<div>Lezárás oka: {esc(indok)} • Üzenetek: {len(uzenetek)}</div></div>{''.join(uzenetek)}</body></html>"""

    async def lezaras(self, g: discord.Guild, csatorna: discord.TextChannel, t, lezaro, indok: str) -> None:
        """A ticket lezárása: átirat a naplóba és a nyitónak, értékelés kérése, a csatorna törlése.

        A lezaro bármi lehet, aminek van id, mention és display_name attribútuma (Discord-tag vagy a webes admin).
        """
        await self.bot.db.execute("UPDATE ticketek SET nyitva=0, lezarva=? WHERE id=?", (most().isoformat(), t["id"]))

        cim = await self.kat_nev(g.id, t["kategoria"])
        szoveg = (await self.atirat(csatorna, t, cim, lezaro, indok)).encode("utf-8")
        fajlnev = f"ticket-{t['id']:04d}.html"

        e = discord.Embed(title=f"Ticket lezárva • #{t['id']:04d}", color=SARGA, timestamp=most())
        e.add_field(name="Nyitotta", value=f"<@{t['user_id']}>")
        e.add_field(name="Kategória", value=cim)
        e.add_field(name="Átvette", value=f"<@{t['atvette']}>" if t["atvette"] else "senki")
        e.add_field(name="Lezárta", value=lezaro.mention)
        e.add_field(name="Indoklás", value=indok, inline=False)
        await naplo(self.bot, g, e, file=discord.File(io.BytesIO(szoveg), filename=fajlnev))

        tulaj = g.get_member(t["user_id"])
        if tulaj:
            dm = discord.Embed(
                title=f"A ticketed lezárult – {g.name}",
                description=f"**Kategória:** {cim}\n**Indoklás:** {indok}\n\nHogyan értékeled az ügyintézést?",
                color=ZOLD,
            )
            try:
                await tulaj.send(
                    embed=dm, file=discord.File(io.BytesIO(szoveg), filename=fajlnev), view=ertekelo_nezet(t["id"])
                )
            except discord.HTTPException:
                pass  # a tagnak le van tiltva a DM

        await asyncio.sleep(5)
        try:
            await csatorna.delete(reason=f"Ticket #{t['id']:04d} lezárva: {indok}")
        except discord.HTTPException:
            pass

    async def lezar(self, i: discord.Interaction, indok: str):
        t = await self.ticket(i.channel.id)
        if not t or not t["nyitva"]:
            return await i.response.send_message("❌ Ez nem egy nyitott ticket.", ephemeral=True)
        await i.response.send_message("🔒 A ticket 5 másodperc múlva lezárul. Az átirat mentése folyamatban…")
        await self.lezaras(i.guild, i.channel, t, i.user, indok)

    # ------------------------------------------------------------------ parancsok
    ticket_csoport = app_commands.Group(name="ticket", description="Ticket rendszer kezelése.", guild_only=True)

    @ticket_csoport.command(name="panel", description="Ticket panel kihelyezése egy csatornába.")
    @app_commands.describe(csatorna="Ide kerül a ticket nyitására szolgáló panel")
    @app_commands.checks.has_permissions(administrator=True)
    async def panel(self, i: discord.Interaction, csatorna: discord.TextChannel):
        try:
            await self.panel_kozzetesz(i.guild, csatorna)
        except discord.HTTPException:
            return await i.response.send_message("❌ Nem tudok üzenetet küldeni abba a csatornába.", ephemeral=True)
        await i.response.send_message(
            f"✅ A panel kihelyezve: {csatorna.mention}\nA kategóriákat a dashboardon szerkesztheted, a panel automatikusan frissül.",
            ephemeral=True,
        )

    @ticket_csoport.command(name="frissites", description="A kihelyezett panel frissítése az aktuális kategóriákkal.")
    @app_commands.checks.has_permissions(administrator=True)
    async def frissites(self, i: discord.Interaction):
        if await self.panel_frissit(i.guild):
            return await i.response.send_message("✅ A panel frissítve.", ephemeral=True)
        await i.response.send_message("❌ Nincs kihelyezett panel (vagy törölték). Használd a `/ticket panel` parancsot.", ephemeral=True)

    @ticket_csoport.command(name="kategoria", description="Alapértelmezett csatornakategória az új ticketeknek.")
    @app_commands.describe(kategoria="A csatornakategória (a ticket-típusokhoz külön is megadható a dashboardon)")
    @app_commands.checks.has_permissions(administrator=True)
    async def kategoria_cmd(self, i: discord.Interaction, kategoria: discord.CategoryChannel):
        await self.bot.db.set(i.guild.id, "ticket_kategoria", str(kategoria.id))
        await i.response.send_message(f"✅ Az új ticketek ide kerülnek: **{kategoria.name}**", ephemeral=True)

    @ticket_csoport.command(name="hozzaad", description="Tag hozzáadása a jelenlegi tickethez.")
    @app_commands.describe(tag="Akit hozzáadsz a ticketcsatornához")
    @staff_only()
    async def hozzaad(self, i: discord.Interaction, tag: discord.Member):
        t = await self.ticket(i.channel.id)
        if not t or not t["nyitva"]:
            return await i.response.send_message("❌ Ezt a parancsot egy nyitott ticketben használd.", ephemeral=True)
        await i.channel.set_permissions(
            tag, view_channel=True, send_messages=True, attach_files=True, read_message_history=True
        )
        await i.response.send_message(f"✅ {tag.mention} hozzá lett adva a tickethez.")

    @ticket_csoport.command(name="eltavolit", description="Tag eltávolítása a jelenlegi ticketből.")
    @app_commands.describe(tag="Akit eltávolítasz a ticketcsatornából")
    @staff_only()
    async def eltavolit(self, i: discord.Interaction, tag: discord.Member):
        t = await self.ticket(i.channel.id)
        if not t or not t["nyitva"]:
            return await i.response.send_message("❌ Ezt a parancsot egy nyitott ticketben használd.", ephemeral=True)
        if tag.id == t["user_id"]:
            return await i.response.send_message("❌ A ticket nyitóját nem távolíthatod el.", ephemeral=True)
        await i.channel.set_permissions(tag, overwrite=None)
        await i.response.send_message(f"✅ {tag.mention} el lett távolítva a ticketből.")


async def setup(bot):
    await bot.add_cog(Ticket(bot))
