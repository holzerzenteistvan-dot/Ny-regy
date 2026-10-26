"""Integrációs teszt: python teszt_integracio.py (a Discordhoz nem kapcsolódik, ideiglenes adatbázist használ)."""
import asyncio, os, sqlite3, sys, tempfile, time
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
sys.path.insert(0, ".")
D = tempfile.mkdtemp()
os.environ.update(ADATBAZIS=D + "/teszt.db", MENTES_MAPPA=D + "/mentesek", CLIENT_ID="1", CLIENT_SECRET="x",
                  DASHBOARD_URL="http://localhost:8098", DASHBOARD_PORT="8098", SESSION_SECRET="t")
import aiohttp
import main
from db import DB
from util import ts

class Tag:
    def __init__(self, guild, uid, kor_nap=400):
        self.id, self.guild, self.bot = uid, guild, False
        self.created_at = datetime.now(timezone.utc) - timedelta(days=kor_nap)
        self.display_name, self.mention, self.kirugva, self.roles, self.joined_at = f"T{uid}", f"<@{uid}>", False, [], None
        self.display_avatar = SimpleNamespace(url="http://x/a.png")
        guild.tagok[uid] = self
    async def send(self, *a, **k): pass
    async def kick(self, reason=None): self.kirugva = True; self.guild.tagok.pop(self.id, None)
    async def add_roles(self, *a, **k): pass

class Szerver:
    id, name, member_count = 1, "Teszt", 10
    def __init__(self): self.tagok = {}
    def get_member(self, uid): return self.tagok.get(uid)
    def get_role(self, _): return None
    def get_channel(self, _): return None

async def f():
    b = main.bot; db = b.db
    await db.start(); b.add_dynamic_items(main.DontesGomb)
    for m in main.MODULOK: await b.load_extension(f"cogs.{m}")

    # --- beállítás-gyorsítótár
    await db.set(1, "x", "1"); assert await db.get(1, "x") == "1"
    await db.torol(1, "x"); assert await db.get(1, "x") is None and await db.get(1, "x", "alap") == "alap"
    await db.set(1, "ures", ""); assert await db.get(1, "ures", "alap") == ""      # az üres érték nem azonos a hiánnyal

    # --- belépések tartós rögzítése, raid-érzékelés az adatbázisból
    bel, am, g = b.get_cog("Belépés") or b.get_cog("Belepes"), b.get_cog("AutoMod"), Szerver()
    await db.set(1, "automod_raid_limit", "3"); await db.set(1, "automod_uj_fiok_napok", "3"); am._cache.clear()
    t1, t2 = Tag(g, 101), Tag(g, 102)
    await bel.on_member_join(t1); await bel.on_member_join(t2)
    assert not t1.kirugva and not t2.kirugva
    assert (await db.fetchone("SELECT COUNT(*) AS n FROM belepesek"))["n"] == 2
    await bel.on_member_join(Tag(g, 103))                      # a 3. belépés raidet jelez: mindenki kirúgva
    sorok = await db.fetchall("SELECT user_id, eredmeny FROM belepesek ORDER BY id")
    print([(s["user_id"], s["eredmeny"]) for s in sorok]); assert all(s["eredmeny"] == "kirugva" for s in sorok) and not g.tagok
    assert await am.raid_aktiv(1)
    uj = DB(D + "/teszt.db"); await uj.start()                    # „újraindítás”: friss adatbázis-kapcsolat, üres gyorsítótár
    assert int(await uj.get(1, "automod_raid_vege", 0)) > ts(); await uj.close()
    t4 = Tag(g, 104); await bel.on_member_join(t4); assert t4.kirugva                          # raid alatt a következő is kirúgva
    await db.set(1, "automod_raid_vege", "0")
    uj_fiok = Tag(g, 105, kor_nap=1); await bel.on_member_join(uj_fiok); assert uj_fiok.kirugva  # túl új fiók
    ok = (await db.fetchone("SELECT ok FROM belepesek WHERE user_id=105"))["ok"]; assert "túl új" in ok
    t6 = Tag(g, 106); await db.set(1, "automod_raid_limit", "0"); am._cache.clear()
    await bel.on_member_join(t6); assert not t6.kirugva
    await bel.on_member_remove(t6)
    assert (await db.fetchone("SELECT kilepett FROM belepesek WHERE user_id=106"))["kilepett"] is not None
    await bel.on_member_join(Tag(g, 106))                      # visszatérő tag: második sor
    assert (await db.fetchone("SELECT COUNT(*) AS n FROM belepesek WHERE user_id=106"))["n"] == 2
    print("belépések rendben")

    # --- mentés és takarítás
    k = b.get_cog("Karbantartas")
    fajl = await k.mentes_keszit(); assert fajl and os.path.exists(fajl)
    assert await k.mentes_keszit() is None                      # aznapra már van
    assert await k.mentes_keszit(kenyszer=True) == fajl
    assert sqlite3.connect(fajl).execute("SELECT COUNT(*) FROM belepesek").fetchone()[0] >= 5
    await db.execute("INSERT INTO belepesek (guild_id,user_id,belepett,fiok_letrehozva) VALUES (1,999,?,0)", (ts() - 500 * 86400,))
    await k.takarit(); assert (await db.fetchone("SELECT COUNT(*) AS n FROM belepesek WHERE user_id=999"))["n"] == 0
    print("mentés és takarítás rendben")

    # --- ticket kategóriák az adatbázisból, űrlapok
    tk = b.get_cog("Ticket")
    kat = await tk.kategoriak(1)
    assert [k["kulcs"] for k in kat][:2] == ["tamogatas", "panasz"] and len(kat) == 5      # alapértelmezett lista bekerült
    from cogs.ticket import KerdesModal, kulcs_keszit, szin_ertek, emoji_ertek
    assert len(KerdesModal(kat[0], ["Mi a gond?", "Mióta áll fenn ez a probléma, és mit próbáltál már?"]).children) == 2
    assert kulcs_keszit("Játékos jelentése!") == "jatekos-jelentese" and szin_ertek("#ff0000").value == 0xFF0000 and szin_ertek("rossz").value == 0x5865F2
    sz = b.get_cog("Szankcio")
    await db.set(1, "szankcio_ban_db", "9"); assert (await sz.eszkalacio(1))["ban_db"] == 9 and (await sz.eszkalacio(1))["timeout_db"] == 3
    print("ticket kategóriák rendben")

    # --- dashboard: minden oldal és minden művelet
    dash = b.get_cog("Dashboard")
    b._connection.user = SimpleNamespace(id=999)
    elkuldott = []
    class Csatorna:
        def __init__(self, i, n): self.id, self.name = i, n
        async def send(self, **kw): elkuldott.append(kw); return SimpleNamespace(id=7000 + len(elkuldott))
        async def fetch_message(self, _): return SimpleNamespace(edit=self.szerkeszt)
        async def szerkeszt(self, **kw): elkuldott.append(("edit", kw))
    csat = [Csatorna(100 + n, f"csatorna{n}") for n in range(3)]
    rang = [SimpleNamespace(id=1, name="@everyone", is_default=lambda: True), SimpleNamespace(id=500, name="Staff", is_default=lambda: False),
            SimpleNamespace(id=501, name="Booster", is_default=lambda: False)]
    kat_csat = SimpleNamespace(id=900, name="Ticketek")
    hamis = SimpleNamespace(id=1, name="Teszt <b>szerver</b>", member_count=50, text_channels=csat, categories=[kat_csat], roles=rang,
                            get_member=lambda u: None, get_channel=lambda i: next((c for c in csat if c.id == i), None),
                            get_role=lambda i: next((r for r in rang if r.id == i), None))
    b.get_guild = lambda gid: hamis if gid == 1 else None
    suti = dash._alair({"u": 1, "n": "T", "g": [1], "c": "csrf1", "e": time.time() + 600})
    s_ = {"dc_session": suti}
    u = "http://localhost:8098"
    assert dash._ellenoriz(suti[:-3] + "abc") is None and dash._ellenoriz("szemét") is None and dash._ellenoriz("é.é") is None
    async with aiohttp.ClientSession() as ks:
        r = await ks.get(u + "/", allow_redirects=False); tx = await r.text(); assert r.status == 200 and "Belépés Discorddal" in tx
        assert "nonce-" in r.headers["Content-Security-Policy"] and "default-src 'none'" in r.headers["Content-Security-Policy"]
        r = await ks.get(u + "/login", allow_redirects=False); assert r.status == 302 and "discord.com/oauth2/authorize" in r.headers["Location"]
        r = await ks.get(u + "/szerver/1", allow_redirects=False); assert r.status == 302                 # belépés nélkül
        r = await ks.get(u + "/szerver/2", cookies=s_, allow_redirects=False); assert r.status == 403
        r = await ks.get(u + "/", cookies=s_); assert "Teszt &lt;b&gt;szerver" in await r.text()          # escape-elve
        for oldal in ("", "/alapok", "/statisztika", "/statisztika?napok=30", "/belepes", "/ticketek", "/szint", "/kozosseg", "/moderacio",
                      "/szankciok", "/szankciok?tipus=ban&felhasznalo=1", "/staff"):
            r = await ks.get(u + "/szerver/1" + oldal, cookies=s_); tx = await r.text()
            assert r.status == 200, (oldal, r.status, tx[:300])
            assert "<b>szerver" not in tx and "Traceback" not in tx
        def urlap(**mezok):
            f = aiohttp.FormData()
            for k_, v in mezok.items():
                for x in (v if isinstance(v, list) else [v]): f.add_field(k_, str(x))
            return f
        async def kuld(utvonal, **mezok):
            return await ks.post(u + "/szerver/1" + utvonal, data=urlap(**mezok), cookies=s_, allow_redirects=False)
        # biztonság: hibás vagy hiányzó CSRF
        for utvonal in ("/mentes/alapok", "/ticket/kategoria", "/ticket/panel", "/szint/rang", "/szint/szorzo", "/raid"):
            r = await kuld(utvonal, csrf="rossz"); assert r.status == 403, utvonal
        r = await ks.post(u + "/szerver/1/mentes/alapok", data=urlap(), cookies=s_, allow_redirects=False); assert r.status == 403
        r = await kuld("/mentes/nincs_ilyen", csrf="csrf1"); assert r.status == 404
        # beállítások mentése
        r = await kuld("/mentes/alapok", csrf="csrf1", vissza="alapok", naplo="101", staffrang="500", vezetorang="9999", vezetoi_csatorna="102")
        assert r.status == 302 and r.headers["Location"].endswith("/alapok?ok=mentve")
        assert await db.get(1, "naplo") == "101" and await db.get(1, "staffrang") == "500" and await db.get(1, "vezetorang") is None
        r = await kuld("/mentes/automod", csrf="csrf1", vissza="moderacio", automod_spam_limit="7", automod_raid_limit="99999", automod_link_szuro=["0"],
                       automod_meghivo_szuro=["0", "1"], automod_szavak="Kurva\n=Fasz\n\nkurva", automod_domainek="https://www.Tenor.com/x\nnemdomain\nroblox.com",
                       automod_kivetel=["100", "102", "777"])
        assert r.status == 302
        assert await db.get(1, "automod_spam_limit") == "7" and await db.get(1, "automod_raid_limit") == "100" and await db.get(1, "automod_link_szuro") == "0"
        assert await db.get(1, "automod_meghivo_szuro") == "1" and await db.get(1, "automod_szavak") == "kurva\n=fasz"
        assert await db.get(1, "automod_domainek") == "tenor.com\nroblox.com" and await db.get(1, "automod_kivetel") == "100,102"
        cfg = await am.cfg(1)                                                 # a gyorsítótár frissült
        assert cfg["spam_limit"] == 7 and cfg["link_szuro"] == 0 and cfg["kivetel"] == {100, 102} and cfg["domainek"] == {"tenor.com", "roblox.com"}
        await kuld("/mentes/szint", csrf="csrf1", vissza="szint", szint_xp_min="5", szint_xp_max="9999", szint_cooldown="30", szint_hang_xp="0")
        assert await db.get(1, "szint_xp_max") == "500" and await db.get(1, "szint_hang_xp") == "0"
        await kuld("/mentes/jelentkezes", csrf="csrf1", vissza="jelentkezesek", jelentkezes_kerdesek="Első?\nMásodik?\nHarmadik?\nNegyedik?\nÖtödik?\nHatodik?\nEelső?")
        assert (await db.get(1, "jelentkezes_kerdesek")).splitlines() == ["Első?", "Második?", "Harmadik?", "Negyedik?", "Ötödik?"]
        # ticket-típusok
        r = await kuld("/ticket/kategoria", csrf="csrf1", vissza="ticketek", muvelet="uj", nev="  ", leiras="x"); assert "hiba=nev" in r.headers["Location"]
        r = await kuld("/ticket/kategoria", csrf="csrf1", vissza="ticketek", muvelet="uj", nev="Játékos jelentése 2", emoji="🚨", leiras="Jelentés",
                       udvozlo="Szia {tag}!", szin="#ff0000", discord_kategoria_id="900", rang_id="501", kerdesek="Ki a vétkes?\nMikor volt?\nKi a vétkes?", aktiv=["0", "1"])
        assert r.headers["Location"].endswith("/ticketek?ok=kat_uj")
        uj = await db.fetchone("SELECT * FROM ticket_kategoriak WHERE guild_id=1 AND nev='Játékos jelentése 2'")
        assert uj["kulcs"] == "jatekos-jelentese-2" and uj["rang_id"] == 501 and uj["discord_kategoria_id"] == 900 and uj["szin"] == "#ff0000"
        assert uj["kerdesek"] == "Ki a vétkes?\nMikor volt?" and uj["aktiv"] == 1 and uj["sorrend"] == 5
        r = await kuld("/ticket/kategoria", csrf="csrf1", vissza="ticketek", muvelet="ment", azon=uj["id"], nev="Átírt név", emoji="nemvalidemoji",
                       rang_id="999", discord_kategoria_id="1234", aktiv=["0"])
        uj = await db.fetchone("SELECT * FROM ticket_kategoriak WHERE id=?", (uj["id"],))
        assert uj["nev"] == "Átírt név" and uj["emoji"] is None and uj["rang_id"] is None and uj["discord_kategoria_id"] is None and uj["aktiv"] == 0
        r = await kuld("/ticket/kategoria", csrf="csrf1", vissza="ticketek", muvelet="fel", azon=uj["id"])
        assert [k["kulcs"] for k in await tk.kategoriak(1, csak_aktiv=False)][4] == "jatekos-jelentese-2"
        assert "jatekos-jelentese-2" not in [k["kulcs"] for k in await tk.kategoriak(1)]                    # inaktív: nincs a panelen
        r = await kuld("/ticket/kategoria", csrf="csrf1", vissza="ticketek", muvelet="torol", azon=uj["id"]); assert "kat_torolve" in r.headers["Location"]
        r = await kuld("/ticket/kategoria", csrf="csrf1", vissza="ticketek", muvelet="torol", azon=987654); assert "nem_talalhato" in r.headers["Location"]
        # panel kihelyezése és frissítése
        r = await kuld("/ticket/panel", csrf="csrf1", vissza="ticketek", muvelet="frissit"); assert "nincs_panel" in r.headers["Location"]
        r = await kuld("/ticket/panel", csrf="csrf1", vissza="ticketek", muvelet="kozzetesz", csatorna="101"); assert "ok=panel" in r.headers["Location"]
        assert await db.get(1, "ticket_panel") == "101:7001"
        r = await kuld("/ticket/panel", csrf="csrf1", vissza="ticketek", muvelet="frissit"); assert "panel_frissitve" in r.headers["Location"]
        r = await kuld("/ticket/kategoria", csrf="csrf1", vissza="ticketek", muvelet="ment", azon=kat[0]["id"], nev="Segítség", aktiv=["1"])
        assert any(e[0] == "edit" for e in elkuldott if isinstance(e, tuple))                               # a panel automatikusan frissült
        # szintrangok, szorzók, raid
        r = await kuld("/szint/rang", csrf="csrf1", vissza="szint", muvelet="ad", szint="5", rang="500"); assert "rang_mentve" in r.headers["Location"]
        r = await kuld("/szint/rang", csrf="csrf1", vissza="szint", muvelet="ad", szint="500", rang="500"); assert "ervenytelen" in r.headers["Location"]
        r = await kuld("/szint/szorzo", csrf="csrf1", vissza="szint", muvelet="ad", rang="501", szorzo="1.5"); assert "szorzo_mentve" in r.headers["Location"]
        szint_cog = b.get_cog("Szint")
        assert [x["szint"] for x in await db.fetchall("SELECT szint FROM szint_rangok")] == [5]
        r = await kuld("/szint/szorzo", csrf="csrf1", vissza="szint", muvelet="ad", rang="501", szorzo="99"); assert "ervenytelen" in r.headers["Location"]
        tx = await (await ks.get(u + "/szerver/1/szint", cookies=s_)).text(); assert "5. szint" in tx and "1.5×" in tx
        await kuld("/szint/rang", csrf="csrf1", vissza="szint", muvelet="torol", szint="5"); await kuld("/szint/szorzo", csrf="csrf1", vissza="szint", muvelet="torol", rang="501")
        assert not await db.fetchall("SELECT * FROM szint_rangok") and not await db.fetchall("SELECT * FROM szint_szorzok")
        r = await kuld("/raid", csrf="csrf1", vissza="belepes", be="1"); assert "raid_be" in r.headers["Location"] and await am.raid_aktiv(1)
        assert "kézi kikapcsolásig" in await (await ks.get(u + "/szerver/1/belepes", cookies=s_)).text()
        r = await kuld("/raid", csrf="csrf1", vissza="belepes", be="0"); assert not await am.raid_aktiv(1)
        # a ticket oldalon megjelennek a típusok, az üzenetek pedig egyszeri toastként
        tx = await (await ks.get(u + "/szerver/1/ticketek?ok=kat_mentve", cookies=s_)).text()
        assert "Segítség" in tx and "A ticket-típus mentve" in tx and "Új ticket-típus" in tx
        assert "hiba=" not in tx and "<script nonce=" in tx
        tx = await (await ks.get(u + "/szerver/1/ticketek?ok=<script>alert(1)</script>", cookies=s_)).text(); assert "alert(1)" not in tx
    print("dashboard rendben")
    print("MINDEN TESZT RENDBEN")
    try:
        await b.close()
    except Exception as hiba: print("leállítás:", type(hiba).__name__)
asyncio.run(f())
