"""Gyors önellenőrzés a szűrők logikájához: python teszt.py"""
from cogs.automod import (ALAP_DOMAINEK, ALAP_SZAVAK, LINK, MEGHIVO, domain_tiszta, normal, szo_listabol,
                          tiltott_link, tiltott_szo)

szavak = szo_listabol(ALAP_SZAVAK)
domainek = set(ALAP_DOMAINEK)

# szitokszűrő
assert tiltott_szo("Ez egy K.u.R.v.a!!", szavak)
assert tiltott_szo("b4zdmeeeg", szavak)
assert tiltott_szo("bazd meg", szavak)  # szóközös kijátszás
assert tiltott_szo("te faszom", szavak) and tiltott_szo("fasz!", szavak)
assert not tiltott_szo("Ez a film nagyon fasza volt", szavak)  # önálló szóként keresett "fasz" nem találat
assert not tiltott_szo("Szegecit vettem, a Nigeria szép ország", szavak)
assert not tiltott_szo("Szia, jó napot kívánok! Szőlőt szeretnék.", szavak)
assert normal("Szőlő") == "szolo"

# linkszűrő: GIF-ek és hasonló oldalak mehetnek, a többi nem
assert not tiltott_link("https://tenor.com/view/macska-gif-123", domainek)
assert not tiltott_link("https://media.giphy.com/media/abc/giphy.gif", domainek)
assert not tiltott_link("https://www.youtube.com/watch?v=x https://youtu.be/y", domainek)
assert not tiltott_link("https://www.roblox.com/games/123/Valami", domainek)
assert not tiltott_link("www.imgur.com/a/x és https://cdn.discordapp.com/attachments/1/2/k.png", domainek)
assert tiltott_link("https://rosszoldal.hu/tenor.com", domainek)  # a név az útvonalban nem számít
assert tiltott_link("https://tenor.com.csalas.ru/x", domainek)
assert tiltott_link("nézd: https://pelda.hu", domainek)
assert not tiltott_link("nincs itt semmilyen link", domainek)
assert MEGHIVO.search("gyere: discord.gg/abcd") and not MEGHIVO.search("https://tenor.com/x")
assert LINK.findall("nézd https://x.hu/a és www.y.hu") == ["https://x.hu/a", "www.y.hu"]
assert domain_tiszta("https://www.Tenor.com/view") == "tenor.com" and domain_tiszta("nemdomain") is None
print("Minden teszt rendben.")

# ---- a többi modul tiszta függvényei
from cogs.inaktivitas import datum_ts
from cogs.nyeremeny import idotartam_mp
from cogs.szint import savok, szint_xp, xp_szint

assert idotartam_mp("30p") == 1800 and idotartam_mp("2ó") == 7200 and idotartam_mp("1d") == 86400
assert idotartam_mp("10s") is None and idotartam_mp("0p") is None
assert datum_ts("2099-01-05") == datum_ts("2099.01.05.") and datum_ts("holnap") is None
assert [xp_szint(x) for x in (0, 99, 100, 400, 10000)] == [0, 0, 1, 2, 10]
assert szint_xp(xp_szint(5000)) <= 5000 < szint_xp(xp_szint(5000) + 1) and len(savok(150)) == 12
print("A többi modul tesztjei is rendben vannak.")
