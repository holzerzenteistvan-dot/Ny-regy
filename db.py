"""SQLite adatbázis – egyetlen kapcsolat, egyszerű segédfüggvényekkel."""
import asyncio

import aiosqlite

SEMA = """
CREATE TABLE IF NOT EXISTS beallitasok (
    guild_id INTEGER NOT NULL,
    kulcs    TEXT    NOT NULL,
    ertek    TEXT    NOT NULL,
    PRIMARY KEY (guild_id, kulcs)
);

CREATE TABLE IF NOT EXISTS szankciok (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    guild_id     INTEGER NOT NULL,
    user_id      INTEGER NOT NULL,
    moderator_id INTEGER NOT NULL,
    tipus        TEXT    NOT NULL,
    indok        TEXT    NOT NULL,
    letrehozva   TEXT    NOT NULL,
    lejar        TEXT,
    aktiv        INTEGER NOT NULL DEFAULT 1
);
CREATE INDEX IF NOT EXISTS idx_szankciok_tag ON szankciok (guild_id, user_id);

CREATE TABLE IF NOT EXISTS ticketek (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    guild_id    INTEGER NOT NULL,
    csatorna_id INTEGER,
    user_id     INTEGER NOT NULL,
    kategoria   TEXT    NOT NULL,
    atvette     INTEGER,
    nyitva      INTEGER NOT NULL DEFAULT 1,
    letrehozva  TEXT    NOT NULL,
    lezarva     TEXT,
    ertekeles   INTEGER,
    atvetel_ido TEXT
);
CREATE INDEX IF NOT EXISTS idx_ticketek_csatorna ON ticketek (csatorna_id);
CREATE TABLE IF NOT EXISTS shiftek (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    guild_id      INTEGER NOT NULL,
    user_id       INTEGER NOT NULL,
    kezdet        INTEGER NOT NULL,
    veg           INTEGER,
    szunet_mp     INTEGER NOT NULL DEFAULT 0,
    szunet_kezdet INTEGER,
    auto_lezart   INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_shiftek ON shiftek (guild_id, user_id, kezdet);

CREATE TABLE IF NOT EXISTS inaktivitasok (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    guild_id    INTEGER NOT NULL,
    user_id     INTEGER NOT NULL,
    kezdet      INTEGER NOT NULL,
    veg         INTEGER NOT NULL,
    indok       TEXT    NOT NULL,
    statusz     TEXT    NOT NULL DEFAULT 'fuggoben',
    uzenet_id   INTEGER,
    csatorna_id INTEGER,
    dontotte    INTEGER,
    lezarva     INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS jelentkezesek (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    guild_id    INTEGER NOT NULL,
    user_id     INTEGER NOT NULL,
    valaszok    TEXT    NOT NULL,
    statusz     TEXT    NOT NULL DEFAULT 'fuggoben',
    dontotte    INTEGER,
    letrehozva  INTEGER NOT NULL,
    uzenet_id   INTEGER,
    csatorna_id INTEGER
);

CREATE TABLE IF NOT EXISTS staff_pontok (
    guild_id   INTEGER NOT NULL,
    user_id    INTEGER NOT NULL,
    honap      TEXT    NOT NULL,
    pont       INTEGER NOT NULL,
    megjegyzes TEXT,
    pontozo    INTEGER NOT NULL,
    PRIMARY KEY (guild_id, user_id, honap)
);

CREATE TABLE IF NOT EXISTS szintek (
    guild_id INTEGER NOT NULL,
    user_id  INTEGER NOT NULL,
    xp       INTEGER NOT NULL DEFAULT 0,
    uzenetek INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (guild_id, user_id)
);
CREATE INDEX IF NOT EXISTS idx_szintek_xp ON szintek (guild_id, xp DESC);
CREATE TABLE IF NOT EXISTS szint_rangok (
    guild_id INTEGER NOT NULL,
    szint    INTEGER NOT NULL,
    rang_id  INTEGER NOT NULL,
    PRIMARY KEY (guild_id, szint)
);
CREATE TABLE IF NOT EXISTS szint_szorzok (
    guild_id INTEGER NOT NULL,
    rang_id  INTEGER NOT NULL,
    szorzo   REAL    NOT NULL,
    PRIMARY KEY (guild_id, rang_id)
);

CREATE TABLE IF NOT EXISTS nyeremenyjatekok (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    guild_id        INTEGER NOT NULL,
    csatorna_id     INTEGER NOT NULL,
    uzenet_id       INTEGER,
    nyeremeny       TEXT    NOT NULL,
    nyertesek_szama INTEGER NOT NULL,
    vege            INTEGER NOT NULL,
    inditotta       INTEGER NOT NULL,
    kell_rang_id    INTEGER,
    min_szint       INTEGER NOT NULL DEFAULT 0,
    befejezve       INTEGER NOT NULL DEFAULT 0,
    nyertesek       TEXT    NOT NULL DEFAULT ''
);
CREATE TABLE IF NOT EXISTS nyj_reszvevok (
    nyj_id  INTEGER NOT NULL,
    user_id INTEGER NOT NULL,
    PRIMARY KEY (nyj_id, user_id)
);

CREATE TABLE IF NOT EXISTS javaslatok (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    guild_id    INTEGER NOT NULL,
    csatorna_id INTEGER,
    uzenet_id   INTEGER,
    user_id     INTEGER NOT NULL,
    szoveg      TEXT    NOT NULL,
    statusz     TEXT    NOT NULL DEFAULT 'nyitott',
    indok       TEXT,
    dontotte    INTEGER,
    letrehozva  INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS javaslat_szavazatok (
    javaslat_id INTEGER NOT NULL,
    user_id     INTEGER NOT NULL,
    szavazat    INTEGER NOT NULL,
    PRIMARY KEY (javaslat_id, user_id)
);

CREATE TABLE IF NOT EXISTS belepesek (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    guild_id        INTEGER NOT NULL,
    user_id         INTEGER NOT NULL,
    belepett        INTEGER NOT NULL,
    fiok_letrehozva INTEGER NOT NULL,
    eredmeny        TEXT    NOT NULL DEFAULT 'maradt',
    ok              TEXT,
    kilepett        INTEGER
);
CREATE INDEX IF NOT EXISTS idx_belepesek_ido ON belepesek (guild_id, belepett);
CREATE INDEX IF NOT EXISTS idx_belepesek_tag ON belepesek (guild_id, user_id);

CREATE TABLE IF NOT EXISTS ticket_kategoriak (
    id                   INTEGER PRIMARY KEY AUTOINCREMENT,
    guild_id             INTEGER NOT NULL,
    kulcs                TEXT    NOT NULL,
    nev                  TEXT    NOT NULL,
    emoji                TEXT,
    leiras               TEXT,
    udvozlo              TEXT,
    szin                 TEXT,
    discord_kategoria_id INTEGER,
    rang_id              INTEGER,
    kerdesek             TEXT    NOT NULL DEFAULT '',
    sorrend              INTEGER NOT NULL DEFAULT 0,
    aktiv                INTEGER NOT NULL DEFAULT 1,
    UNIQUE (guild_id, kulcs)
);

CREATE TABLE IF NOT EXISTS nyitasok (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    guild_id       INTEGER NOT NULL,
    csatorna_id    INTEGER NOT NULL,
    cim            TEXT    NOT NULL,
    szoveg         TEXT    NOT NULL DEFAULT '',
    szin           TEXT,
    link           TEXT,
    kod            TEXT,
    ping           TEXT    NOT NULL DEFAULT '',
    kuldte         INTEGER NOT NULL DEFAULT 0,
    kuldte_nev     TEXT,
    letrehozva     INTEGER NOT NULL,
    idopont        INTEGER,
    statusz        TEXT    NOT NULL DEFAULT 'idozitett',
    uzenet_id      INTEGER,
    lezarva        INTEGER,
    zaras_uzenet_id INTEGER
);
CREATE INDEX IF NOT EXISTS idx_nyitasok ON nyitasok (guild_id, statusz);

CREATE TABLE IF NOT EXISTS napi_aktivitas (
    guild_id INTEGER NOT NULL,
    nap      TEXT    NOT NULL,
    user_id  INTEGER NOT NULL,
    uzenetek INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (guild_id, nap, user_id)
);
CREATE TABLE IF NOT EXISTS napi_csatorna (
    guild_id    INTEGER NOT NULL,
    nap         TEXT    NOT NULL,
    csatorna_id INTEGER NOT NULL,
    uzenetek    INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (guild_id, nap, csatorna_id)
);
CREATE TABLE IF NOT EXISTS napi_tagok (
    guild_id INTEGER NOT NULL,
    nap      TEXT    NOT NULL,
    belepett INTEGER NOT NULL DEFAULT 0,
    kilepett INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (guild_id, nap)
);"""


class DB:
    def __init__(self, ut: str = "dcbot.db"):
        self.ut = ut
        self.kapcsolat: aiosqlite.Connection | None = None
        # Egyetlen kapcsolaton dolgozunk, ezért az írásokat sorba rendezzük: egy írás (utasítás + mentés) addig
        # tart, amíg a zár nála van. Így soha nem marad félbehagyott tranzakció másik művelet alatt.
        self._zar = asyncio.Lock()
        # A beállításokat minden üzenetnél olvassuk (pl. staff rang), ezért memóriában is tartjuk őket.
        # Írni mindig a set() / torol() függvényekkel kell, hogy a gyorsítótár naprakész maradjon.
        self._beallitasok: dict[tuple[int, str], str | None] = {}

    async def start(self) -> None:
        self.kapcsolat = await aiosqlite.connect(self.ut)
        self.kapcsolat.row_factory = aiosqlite.Row
        await self.kapcsolat.execute("PRAGMA journal_mode=WAL")
        await self.kapcsolat.executescript(SEMA)
        # Régebbi adatbázisok kiegészítése az újonnan bevezetett oszloppal.
        oszlopok = {sor["name"] for sor in await self.fetchall("PRAGMA table_info(ticketek)")}
        if "atvetel_ido" not in oszlopok:
            await self.kapcsolat.execute("ALTER TABLE ticketek ADD COLUMN atvetel_ido TEXT")
        # A jelentkezések új oszlopai (privát üzenetes jelentkezés, döntés megjegyzéssel, ticket az elfogadottnak).
        oszlopok = {sor["name"] for sor in await self.fetchall("PRAGMA table_info(jelentkezesek)")}
        for oszlop, leiras in (("forras", "TEXT NOT NULL DEFAULT 'discord'"), ("megjegyzes", "TEXT"),
                               ("dontes_ido", "INTEGER"), ("ticket_csatorna_id", "INTEGER")):
            if oszlop not in oszlopok:
                await self.kapcsolat.execute(f"ALTER TABLE jelentkezesek ADD COLUMN {oszlop} {leiras}")
        await self.kapcsolat.commit()

    async def close(self) -> None:
        if self.kapcsolat:
            await self.kapcsolat.close()

    async def execute(self, sql: str, args: tuple = ()) -> int:
        """Lefuttat egy módosító parancsot, visszaadja az utolsó sor azonosítóját."""
        async with self._zar:
            try:
                async with self.kapcsolat.execute(sql, args) as kurzor:
                    azonosito = kurzor.lastrowid
                await self.kapcsolat.commit()
            except Exception:
                await self.kapcsolat.rollback()
                raise
        return azonosito

    async def executemany(self, sql: str, sorok: list) -> None:
        async with self._zar:
            try:
                await self.kapcsolat.executemany(sql, sorok)
                await self.kapcsolat.commit()
            except Exception:
                await self.kapcsolat.rollback()
                raise

    async def mentes(self, fajl: str) -> None:
        """Konzisztens pillanatkép az adatbázisról egy új fájlba (VACUUM INTO)."""
        async with self._zar:
            await self.kapcsolat.commit()  # a VACUUM nem futhat tranzakción belül
            async with self.kapcsolat.execute("VACUUM INTO ?", (fajl,)):
                pass

    async def fetchone(self, sql: str, args: tuple = ()):
        async with self.kapcsolat.execute(sql, args) as kurzor:
            return await kurzor.fetchone()

    async def fetchall(self, sql: str, args: tuple = ()):
        async with self.kapcsolat.execute(sql, args) as kurzor:
            return await kurzor.fetchall()

    async def get(self, guild_id: int, kulcs: str, alap=None):
        kulcs_ = (guild_id, kulcs)
        if kulcs_ not in self._beallitasok:
            sor = await self.fetchone("SELECT ertek FROM beallitasok WHERE guild_id=? AND kulcs=?", kulcs_)
            self._beallitasok[kulcs_] = sor["ertek"] if sor else None
        ertek = self._beallitasok[kulcs_]
        return ertek if ertek is not None else alap

    async def torol(self, guild_id: int, kulcs: str) -> None:
        await self.execute("DELETE FROM beallitasok WHERE guild_id=? AND kulcs=?", (guild_id, kulcs))
        self._beallitasok[(guild_id, kulcs)] = None

    async def set(self, guild_id: int, kulcs: str, ertek: str) -> None:
        await self.execute(
            "INSERT INTO beallitasok (guild_id, kulcs, ertek) VALUES (?, ?, ?) "
            "ON CONFLICT(guild_id, kulcs) DO UPDATE SET ertek=excluded.ertek",
            (guild_id, kulcs, ertek),
        )
        self._beallitasok[(guild_id, kulcs)] = ertek
