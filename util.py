"""Közös segédfüggvények és állandók."""
import time
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import discord
from discord import app_commands

IDOZONA = ZoneInfo("Europe/Budapest")

KEK = discord.Color.blurple()
ZOLD = discord.Color.green()
PIROS = discord.Color.red()
SARGA = discord.Color.gold()
NARANCS = discord.Color.orange()
SZURKE = discord.Color.light_grey()


# ---------------------------------------------------------------- idő
def most() -> datetime:
    return datetime.now(timezone.utc)


def ts() -> int:
    """Jelenlegi unix idő másodpercben."""
    return int(time.time())


def iso(ido: datetime) -> str:
    return ido.astimezone(timezone.utc).isoformat()


def ido_szoveg(mp: float) -> str:
    """Másodpercből olvasható időtartam: '3 ó 25 p'."""
    mp = max(0, int(mp))
    ora, maradek = divmod(mp, 3600)
    perc = maradek // 60
    return f"{ora} ó {perc} p" if ora else f"{perc} p"


def het_kezdete(ref: datetime | None = None) -> datetime:
    """Az adott hét hétfője 00:00 (budapesti idő)."""
    ma = (ref or datetime.now(IDOZONA)).astimezone(IDOZONA)
    return (ma - timedelta(days=ma.weekday())).replace(hour=0, minute=0, second=0, microsecond=0)


def honap_kezdete(ref: datetime | None = None) -> datetime:
    ma = (ref or datetime.now(IDOZONA)).astimezone(IDOZONA)
    return ma.replace(day=1, hour=0, minute=0, second=0, microsecond=0)


def elozo_honap_kezdete(ref: datetime | None = None) -> datetime:
    return honap_kezdete(honap_kezdete(ref) - timedelta(days=1))


# ---------------------------------------------------------------- jogosultság
class StaffHiba(app_commands.CheckFailure):
    """Nem staff (vagy nem vezető) tag próbált védett parancsot használni."""


async def _rangja_van(bot, tag: discord.Member, kulcs: str) -> bool:
    rang_id = await bot.db.get(tag.guild.id, kulcs)
    return bool(rang_id) and any(r.id == int(rang_id) for r in tag.roles)


async def staff_e(bot, tag: discord.Member) -> bool:
    """Staff-e a tag: adminisztrátor, vezető, vagy megvan a beállított staff rangja."""
    if tag.guild_permissions.administrator:
        return True
    return await _rangja_van(bot, tag, "staffrang") or await _rangja_van(bot, tag, "vezetorang")


async def vezeto_e(bot, tag: discord.Member) -> bool:
    if tag.guild_permissions.administrator:
        return True
    return await _rangja_van(bot, tag, "vezetorang")


def staff_only():
    async def feltetel(i: discord.Interaction) -> bool:
        if await staff_e(i.client, i.user):
            return True
        raise StaffHiba("Ehhez a parancshoz staff jogosultság szükséges.")

    return app_commands.check(feltetel)


def vezeto_only():
    async def feltetel(i: discord.Interaction) -> bool:
        if await vezeto_e(i.client, i.user):
            return True
        raise StaffHiba("Ehhez a parancshoz vezetői jogosultság szükséges.")

    return app_commands.check(feltetel)


# ---------------------------------------------------------------- csatornák
async def csatorna_kap(bot, guild: discord.Guild, *kulcsok: str) -> discord.TextChannel | None:
    """Az első beállított, létező csatorna a megadott kulcsok közül."""
    for kulcs in kulcsok:
        csatorna_id = await bot.db.get(guild.id, kulcs)
        if csatorna_id and (csatorna := guild.get_channel(int(csatorna_id))):
            return csatorna
    return None


async def naplo(bot, guild: discord.Guild, embed: discord.Embed | None = None, **kwargs) -> None:
    """Üzenet küldése a beállított naplócsatornába (ha van)."""
    csatorna = await csatorna_kap(bot, guild, "naplo")
    if csatorna is None:
        return
    try:
        await csatorna.send(embed=embed, **kwargs)
    except discord.HTTPException:
        pass
