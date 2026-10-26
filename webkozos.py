"""A webes felület közös, Discordtól független segédei (mezőleírás, dátumformázás, színellenőrzés)."""
import re
from datetime import datetime

from util import IDOZONA


def m(kulcs, nev, tipus, **kw):
    """Egy beállítási mező leírása."""
    return {"kulcs": kulcs, "nev": nev, "tipus": tipus, **kw}


def egeszseg_hex(szoveg: str | None) -> str | None:
    return "#" + szoveg.strip().lstrip("#").lower() if szoveg and re.fullmatch(r"#?[0-9a-fA-F]{6}", szoveg.strip()) else None


def relativ(masodperc_ota: float) -> str:
    mp = int(masodperc_ota)
    if mp < 60:
        return "épp most"
    if mp < 3600:
        return f"{mp // 60} perce"
    if mp < 86400:
        return f"{mp // 3600} órája"
    return f"{mp // 86400} napja"


def datum(iso_szoveg: str | None) -> str:
    return datetime.fromisoformat(iso_szoveg).astimezone(IDOZONA).strftime("%Y.%m.%d. %H:%M") if iso_szoveg else "–"


def mp_datum(mp: int | None) -> str:
    return datetime.fromtimestamp(mp, IDOZONA).strftime("%Y.%m.%d. %H:%M") if mp else "–"


def ido_ervenyes(szoveg: str | None) -> bool:
    """HH:MM alakú időpont-e."""
    return bool(re.fullmatch(r"([01]\d|2[0-3]):[0-5]\d", szoveg or ""))
