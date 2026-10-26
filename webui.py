"""A dashboard megjelenése: oldalváz, stílus, kis JavaScript, űrlapmezők, táblázatok, diagramok.

Minden szöveget escape-elünk; a már biztonságos HTML-t a Nyers típus jelöli.
"""
import html
import itertools
import math

esc = html.escape


class Nyers(str):
    """Már biztonságos (escape-elt) HTML. Ezt a sablon-függvények nem escape-elik újra."""


def _s(x) -> str:
    return str(x) if isinstance(x, Nyers) else esc(str(x))


# ---------------------------------------------------------------------- stílus
CSS = """
:root{--bg:#0c0e13;--panel:#151822;--panel2:#1b1f2c;--vonal:#272c3b;--szoveg:#e7e9ef;--halk:#8d95a9;--fo:#7c5cff;--fo2:#4f8cff;
--zold:#2ecc8f;--piros:#ff5d6c;--sarga:#ffc857;--arnyek:0 8px 30px rgba(0,0,0,.35);--r:14px}
html[data-tema=vilagos]{--bg:#f3f5fa;--panel:#fff;--panel2:#f5f7fc;--vonal:#e1e5ef;--szoveg:#1a1f2e;--halk:#6b7388;--arnyek:0 8px 30px rgba(30,40,80,.10)}
*{box-sizing:border-box}html{scroll-behavior:smooth}
body{margin:0;background:var(--bg);color:var(--szoveg);font:15px/1.55 Inter,system-ui,-apple-system,"Segoe UI",sans-serif;
background-image:radial-gradient(900px 400px at 85% -10%,rgba(124,92,255,.14),transparent),radial-gradient(700px 400px at -10% 110%,rgba(79,140,255,.10),transparent);background-attachment:fixed}
a{color:var(--fo2);text-decoration:none}a:hover{text-decoration:underline}
h1{font-size:26px;margin:0;letter-spacing:-.02em}h2{font-size:17px;margin:0;letter-spacing:-.01em}h3{font-size:15px;margin:0}
.oldalsav{position:fixed;inset:0 auto 0 0;width:262px;background:var(--panel);border-right:1px solid var(--vonal);display:flex;flex-direction:column;padding:18px 14px;overflow-y:auto;z-index:30;transition:transform .25s}
.logo{display:flex;align-items:center;gap:10px;color:var(--szoveg);font-size:17px;padding:4px 8px 16px}.logo:hover{text-decoration:none}
.logo-jel{width:34px;height:34px;border-radius:10px;display:grid;place-items:center;background:linear-gradient(135deg,var(--fo),var(--fo2));box-shadow:0 4px 16px rgba(124,92,255,.45)}
.szerver-chip{display:flex;align-items:center;gap:10px;background:var(--panel2);border:1px solid var(--vonal);border-radius:12px;padding:10px 12px;margin-bottom:14px;color:var(--szoveg)}
.szerver-chip:hover{text-decoration:none;border-color:var(--fo)}.szerver-chip small{color:var(--halk);display:block;line-height:1.2}
.ikon{width:36px;height:36px;border-radius:10px;background:linear-gradient(135deg,var(--fo),var(--fo2));display:grid;place-items:center;font-weight:700;color:#fff;overflow:hidden;flex:none}
.ikon img{width:100%;height:100%;object-fit:cover}
.csoport{font-size:11px;text-transform:uppercase;letter-spacing:.09em;color:var(--halk);margin:14px 10px 6px}
.oldalsav nav a{display:flex;align-items:center;gap:11px;padding:9px 12px;border-radius:10px;color:var(--halk);margin-bottom:2px;font-weight:500;transition:.15s}
.oldalsav nav a:hover{background:var(--panel2);color:var(--szoveg);text-decoration:none}
.oldalsav nav a.aktiv{background:linear-gradient(90deg,rgba(124,92,255,.22),rgba(124,92,255,.04));color:var(--szoveg);box-shadow:inset 3px 0 0 var(--fo)}
.oldalsav nav a span.i{width:22px;text-align:center}
.felhasznalo{margin-top:auto;padding:12px 8px 2px;border-top:1px solid var(--vonal);display:flex;align-items:center;justify-content:space-between;gap:8px;color:var(--halk);font-size:13px}
.tartalom{margin-left:262px;min-height:100vh}
.felso{display:flex;align-items:center;gap:12px;padding:14px 32px;position:sticky;top:0;z-index:20;background:color-mix(in srgb,var(--bg) 82%,transparent);backdrop-filter:blur(10px);border-bottom:1px solid var(--vonal)}
.felso .morzsa{margin-right:auto;color:var(--halk)}#menu-gomb{display:none}
main{max-width:1180px;margin:0 auto;padding:28px 32px 90px;animation:be .35s ease}
@keyframes be{from{opacity:0;transform:translateY(6px)}to{opacity:1;transform:none}}
.oldalfej{display:flex;align-items:flex-end;justify-content:space-between;gap:16px;margin-bottom:24px;flex-wrap:wrap}
.oldalfej p{margin:4px 0 0;color:var(--halk)}
.kartya{background:var(--panel);border:1px solid var(--vonal);border-radius:var(--r);padding:20px 22px;margin-bottom:18px;box-shadow:var(--arnyek)}
.kartya>.fej{display:flex;align-items:center;justify-content:space-between;gap:12px;margin-bottom:14px}
.kartya>.fej p,.leiras{margin:3px 0 0;color:var(--halk);font-size:13.5px}
.racs{display:grid;gap:16px;margin-bottom:18px}.r2{grid-template-columns:repeat(auto-fit,minmax(340px,1fr))}.r4{grid-template-columns:repeat(auto-fit,minmax(200px,1fr))}.r6{grid-template-columns:repeat(auto-fit,minmax(168px,1fr))}
.csempe{background:var(--panel);border:1px solid var(--vonal);border-radius:var(--r);padding:16px 18px;display:flex;gap:14px;align-items:center;transition:.2s}
.csempe:hover{transform:translateY(-2px);border-color:var(--fo)}
.csempe .jel{width:44px;height:44px;border-radius:12px;display:grid;place-items:center;font-size:21px;flex:none;background:rgba(124,92,255,.16)}
.csempe.zold .jel{background:rgba(46,204,143,.16)}.csempe.piros .jel{background:rgba(255,93,108,.16)}.csempe.sarga .jel{background:rgba(255,200,87,.16)}.csempe.kek .jel{background:rgba(79,140,255,.16)}
.csempe b{display:block;font-size:24px;line-height:1.1;letter-spacing:-.02em}.csempe span.c{color:var(--halk);font-size:13px}
.cimke{display:inline-block;padding:2px 10px;border-radius:99px;font-size:12px;font-weight:600;background:var(--panel2);color:var(--halk);border:1px solid var(--vonal)}
.cimke.zold{background:rgba(46,204,143,.14);color:var(--zold);border-color:transparent}.cimke.piros{background:rgba(255,93,108,.14);color:var(--piros);border-color:transparent}
.cimke.sarga{background:rgba(255,200,87,.14);color:var(--sarga);border-color:transparent}.cimke.fo{background:rgba(124,92,255,.16);color:#a995ff;border-color:transparent}
table{width:100%;border-collapse:collapse}td a{white-space:nowrap}th{position:sticky;top:0;text-align:left;color:var(--halk);font-size:12px;text-transform:uppercase;letter-spacing:.06em;padding:8px 12px;background:var(--panel)}
td{padding:11px 12px;border-top:1px solid var(--vonal);vertical-align:top}tbody tr:hover td{background:var(--panel2)}
.gorgetheto{overflow-x:auto;max-height:560px}
.szuro{width:100%;max-width:320px}
.ures{text-align:center;color:var(--halk);padding:30px 10px}.ures .nagy{font-size:34px;display:block;margin-bottom:6px}
label{display:block;margin:0 0 6px;font-weight:600;font-size:13.5px}
input[type=text],input[type=number],input[type=search],select,textarea{width:100%;background:var(--panel2);color:var(--szoveg);border:1px solid var(--vonal);border-radius:10px;padding:9px 12px;font:inherit;transition:.15s}
input:focus,select:focus,textarea:focus{outline:0;border-color:var(--fo);box-shadow:0 0 0 3px rgba(124,92,255,.22)}
textarea{resize:vertical;min-height:80px}select[multiple]{min-height:150px}
input[type=color]{width:46px;height:40px;padding:3px;border-radius:10px;border:1px solid var(--vonal);background:var(--panel2);cursor:pointer}
.mezo{margin-bottom:18px}.seg{color:var(--halk);font-size:12.5px;margin-top:5px}
.mezok{display:grid;grid-template-columns:repeat(auto-fit,minmax(300px,1fr));gap:4px 22px}.mezok .teljes{grid-column:1/-1}
.kapcsolo{display:flex;align-items:center;gap:12px;cursor:pointer;margin:0;font-weight:600}.kapcsolo input[type=checkbox]{display:none}
.csuszka{width:42px;height:24px;border-radius:99px;background:var(--vonal);position:relative;transition:.2s;flex:none}
.csuszka::after{content:"";position:absolute;top:3px;left:3px;width:18px;height:18px;border-radius:50%;background:#fff;transition:.2s}
.kapcsolo input:checked+.csuszka{background:var(--fo)}.kapcsolo input:checked+.csuszka::after{left:21px}
.sor{display:flex;gap:10px;align-items:center;flex-wrap:wrap}
button,.gomb{background:linear-gradient(135deg,var(--fo),var(--fo2));color:#fff;border:0;border-radius:10px;padding:9px 18px;font:inherit;font-weight:600;cursor:pointer;display:inline-flex;align-items:center;gap:8px;transition:.15s;box-shadow:0 4px 14px rgba(124,92,255,.3)}
button:hover,.gomb:hover{filter:brightness(1.1);text-decoration:none;transform:translateY(-1px)}
button.masodlagos,.gomb.masodlagos{background:var(--panel2);color:var(--szoveg);box-shadow:none;border:1px solid var(--vonal)}
button.veszely{background:rgba(255,93,108,.14);color:var(--piros);box-shadow:none;border:1px solid transparent}
button.kicsi{padding:5px 11px;font-size:13px}
.mentes-sav{position:sticky;bottom:14px;display:none;justify-content:flex-end;gap:10px;align-items:center;margin-top:6px;padding:12px 16px;border-radius:12px;background:var(--panel);border:1px solid var(--fo);box-shadow:var(--arnyek);z-index:5}
.mentes-sav.latszik{display:flex;animation:be .25s}.mentes-sav span{margin-right:auto;color:var(--halk);font-size:13px}
details{border:1px solid var(--vonal);border-radius:12px;margin-bottom:12px;background:var(--panel2)}
summary{cursor:pointer;padding:13px 16px;display:flex;align-items:center;gap:12px;font-weight:600;list-style:none}summary::-webkit-details-marker{display:none}
summary::after{content:"▾";margin-left:auto;color:var(--halk);transition:.2s}details[open]>summary::after{transform:rotate(180deg)}
details>.belso{padding:4px 18px 16px;border-top:1px solid var(--vonal);padding-top:16px}
.ellenorzes{display:flex;gap:12px;align-items:flex-start;padding:10px 0;border-top:1px solid var(--vonal)}.ellenorzes:first-of-type{border-top:0}
.ellenorzes .j{font-size:18px;width:26px;flex:none;text-align:center}.ellenorzes small{color:var(--halk);display:block}
.savos{height:8px;background:var(--panel2);border-radius:99px;overflow:hidden;min-width:90px}.savos i{display:block;height:100%;background:linear-gradient(90deg,var(--fo),var(--fo2));border-radius:99px}
.toast{position:fixed;right:22px;bottom:22px;z-index:50;background:var(--panel);border:1px solid var(--zold);border-left-width:4px;border-radius:12px;padding:13px 18px;box-shadow:var(--arnyek);animation:be .3s;transition:.4s}
.toast.hiba{border-color:var(--piros)}.toast.el{opacity:0;transform:translateY(10px);pointer-events:none}
.elonezet{background:#313338;color:#dbdee1;border-radius:10px;padding:14px 16px;border-left:4px solid #5865f2;white-space:pre-wrap;margin-top:8px;font-size:14px}
.diagram svg{width:100%;height:auto;display:block}.diagram text{fill:var(--halk);font-size:11px}.diagram .racs-vonal{stroke:var(--vonal);stroke-dasharray:3 4}
.diagram rect.o{transition:.15s}.diagram rect.o:hover{filter:brightness(1.25)}
.fank{display:flex;gap:26px;align-items:center;flex-wrap:wrap}.jelmagyarazat{display:grid;gap:7px;font-size:14px}
.jelmagyarazat i{display:inline-block;width:11px;height:11px;border-radius:3px;margin-right:8px}
.bejelentkezes{min-height:100vh;display:grid;place-items:center;padding:20px}.bejelentkezes .kartya{max-width:440px;text-align:center;padding:38px 34px}
.bejelentkezes .logo-jel{width:62px;height:62px;font-size:30px;margin:0 auto 16px;border-radius:18px}
.sz-lista a{display:flex;align-items:center;gap:14px;padding:14px;border:1px solid var(--vonal);border-radius:12px;margin-bottom:10px;background:var(--panel2);color:var(--szoveg)}
.sz-lista a:hover{border-color:var(--fo);text-decoration:none;transform:translateY(-1px)}
.elo-doboz{background:#313338;color:#dbdee1;border-radius:12px;padding:14px 16px;margin:6px 0 14px;font-size:14px}
.elo-doboz .ec-ping-cimke{display:block;color:#949ba4;font-size:11.5px;margin-bottom:4px}
.elo-doboz .ec-ping{display:inline-block;background:rgba(88,101,242,.3);color:#c9cdfb;border-radius:4px;padding:0 4px;margin-bottom:8px;font-weight:500}
.dc-embed{border-left:4px solid var(--elo-szin,#2ecc8f);background:#2b2d31;border-radius:4px;padding:10px 14px;max-width:520px}
.dc-embed .ec-cim{font-weight:700;color:#fff;margin-bottom:4px}.dc-embed .ec-szoveg{white-space:pre-wrap;word-break:break-word}
.dc-embed .ec-kod{margin-top:8px}.dc-embed .ec-gomb{display:inline-block;margin-top:10px;background:#4e5058;color:#fff;border-radius:4px;padding:5px 12px;font-size:13px}
.nap-valaszto{display:flex;flex-wrap:wrap;gap:8px}.nap-valaszto label{margin:0;cursor:pointer}
.nap-valaszto input{display:none}.nap-valaszto span{display:inline-block;min-width:46px;text-align:center;padding:7px 12px;border-radius:10px;border:1px solid var(--vonal);background:var(--panel2);font-weight:600;color:var(--halk)}
.nap-valaszto input:checked+span{background:var(--fo);border-color:var(--fo);color:#fff}
details.jel>summary{flex-wrap:wrap}.valasz{background:var(--panel);border:1px solid var(--vonal);border-radius:10px;padding:10px 12px;margin-bottom:8px}
.valasz b{display:block;font-size:12.5px;color:var(--halk);margin-bottom:3px}.valasz div{white-space:pre-wrap;word-break:break-word}
.halk{color:var(--halk)}
.alsosav{display:none}.menu-hatter{display:none}
@media(max-width:900px){.oldalsav{transform:translateX(-100%);width:min(300px,86vw);padding-bottom:calc(18px + env(safe-area-inset-bottom))}
body.menu-nyitva .oldalsav{transform:none;box-shadow:var(--arnyek)}
body.menu-nyitva .menu-hatter{display:block;position:fixed;inset:0;background:rgba(0,0,0,.5);z-index:25}
.tartalom{margin-left:0}#menu-gomb{display:inline-flex}
main{padding:18px 14px calc(96px + env(safe-area-inset-bottom))}.felso{padding:10px 14px;padding-top:calc(10px + env(safe-area-inset-top))}
.mezok{grid-template-columns:1fr}.kartya{padding:16px 15px;border-radius:12px}h1{font-size:22px}
.racs{gap:12px}.r2,.r4,.r6{grid-template-columns:1fr 1fr}.r2{grid-template-columns:1fr}.csempe{padding:12px 13px;gap:10px}.csempe b{font-size:20px}.csempe .jel{width:38px;height:38px}
input[type=text],input[type=number],input[type=search],input[type=datetime-local],input[type=time],select,textarea{font-size:16px;min-height:44px}
button,.gomb{min-height:44px;justify-content:center}button.kicsi{min-height:36px}
.sor{width:100%}.sor>input,.sor>select{max-width:none!important;flex:1 1 100%}.sor>button{flex:1 1 auto}
th,td{padding:9px 8px}.gorgetheto{max-height:none;-webkit-overflow-scrolling:touch}
.toast{left:12px;right:12px;bottom:calc(84px + env(safe-area-inset-bottom))}
.mentes-sav{bottom:calc(76px + env(safe-area-inset-bottom))}
.alsosav{display:flex;position:fixed;left:0;right:0;bottom:0;z-index:28;background:var(--panel);border-top:1px solid var(--vonal);padding:6px 6px calc(6px + env(safe-area-inset-bottom));justify-content:space-around}
.alsosav a{flex:1;display:flex;flex-direction:column;align-items:center;gap:2px;padding:6px 2px;border-radius:10px;color:var(--halk);font-size:11px;font-weight:600;min-height:48px;justify-content:center}
.alsosav a:hover{text-decoration:none}.alsosav a .i{font-size:19px;line-height:1}.alsosav a.aktiv{color:var(--szoveg);background:rgba(124,92,255,.18)}}
@media(max-width:380px){.r4,.r6{grid-template-columns:1fr}}
"""

JS = """
(()=>{const $=(s,r=document)=>r.querySelector(s),$$=(s,r=document)=>[...r.querySelectorAll(s)];
const T=localStorage.getItem('tema');if(T)document.documentElement.dataset.tema=T;
$('#tema')?.addEventListener('click',()=>{const u=document.documentElement.dataset.tema==='vilagos'?'sotet':'vilagos';document.documentElement.dataset.tema=u;localStorage.setItem('tema',u)});
$('#menu-gomb')?.addEventListener('click',()=>document.body.classList.toggle('menu-nyitva'));
$('#menu-tobb')?.addEventListener('click',e=>{e.preventDefault();document.body.classList.add('menu-nyitva')});
$('.menu-hatter')?.addEventListener('click',()=>document.body.classList.remove('menu-nyitva'));
$$('.oldalsav nav a').forEach(a=>a.addEventListener('click',()=>document.body.classList.remove('menu-nyitva')));
$$('[data-elo-forma]').forEach(f=>{const d=$('#'+f.dataset.eloForma),v=n=>f.elements[n]?.value||'',ping=()=>({everyone:'@everyone',here:'@here',rang:'@'+(f.elements.ping_rang?.selectedOptions[0]?.text||'rang'),'':''}[v('ping')]??'');
const frissit=()=>{const p=ping(),pe=$('.ec-ping',d);pe.textContent=p;pe.hidden=!p;$('.ec-ping-cimke',d).hidden=!p;$('.ec-cim',d).textContent=v('cim');$('.ec-szoveg',d).textContent=v('szoveg');
const k=$('.ec-kod',d);k.hidden=!v('kod');$('b',k).textContent=v('kod');$('.ec-gomb',d).hidden=!v('link');if(/^#[0-9a-f]{6}$/i.test(v('szin')))$('.dc-embed',d).style.setProperty('--elo-szin',v('szin'))};
f.addEventListener('input',frissit);f.addEventListener('change',frissit);frissit()});
$$('[data-szuro]').forEach(i=>i.addEventListener('input',()=>{const q=i.value.toLowerCase();$$('#'+i.dataset.szuro+' tbody tr').forEach(tr=>tr.hidden=!tr.textContent.toLowerCase().includes(q))}));
$$('[data-megerosites]').forEach(f=>f.addEventListener('submit',e=>{if(!confirm(f.dataset.megerosites))e.preventDefault()}));
const t=$('.toast');if(t)setTimeout(()=>t.classList.add('el'),4200);
$$('[data-elonezet]').forEach(ta=>{const c=$('#'+ta.dataset.elonezet),f=()=>{c.textContent=ta.value.replaceAll('{tag}','@MintaTag').replaceAll('{szerver}',ta.dataset.szerver||'Szerver').replaceAll('{szam}','1234')};ta.addEventListener('input',f);f()});
$$('input[type=color][data-szoveg]').forEach(c=>{const x=$('#'+c.dataset.szoveg);c.addEventListener('input',()=>x.value=c.value);x.addEventListener('input',()=>{if(/^#[0-9a-f]{6}$/i.test(x.value))c.value=x.value})});
$$('form[data-valtozas]').forEach(f=>f.addEventListener('input',()=>$('.mentes-sav',f)?.classList.add('latszik')));
document.addEventListener('keydown',e=>{if((e.ctrlKey||e.metaKey)&&e.key==='s'){const f=$('form[data-valtozas] .mentes-sav.latszik')?.closest('form');if(f){e.preventDefault();f.requestSubmit()}}});
})();
"""

NAV = [
    ("Általános", [("", "📊", "Áttekintés"), ("alapok", "⚙️", "Alapok"), ("statisztika", "📈", "Statisztika")]),
    ("RP szerver", [("nyitas", "🟢", "Szerver nyitás"), ("jelentkezesek", "📝", "Jelentkezések")]),
    ("Közösség", [("belepes", "👋", "Belépés"), ("ticketek", "🎫", "Ticketek"), ("szint", "✨", "Szintek"),
                  ("kozosseg", "💡", "Javaslatok és játékok")]),
    ("Moderáció", [("moderacio", "🛡️", "Automod és szankciók"), ("szankciok", "📜", "Szankciónapló")]),
    ("Csapat", [("staff", "🕒", "Staff és szolgálat")]),
]


def ikon_html(guild) -> Nyers:
    ikon = getattr(guild, "icon", None)
    if ikon:
        return Nyers(f'<span class="ikon"><img src="{esc(ikon.url)}" alt=""></span>')
    return Nyers(f'<span class="ikon">{esc((guild.name or "?")[:1].upper())}</span>')


def oldal_vaz(cim: str, tartalom: str, *, nonce: str, felhasznalo: dict | None = None, guild=None, aktiv: str = "",
              uzenet: tuple[str, str] | None = None) -> str:
    if guild is not None:
        csoportok = "".join(
            f'<div class="csoport">{esc(nev)}</div>' + "".join(
                f'<a href="/szerver/{guild.id}{"/" + k if k else ""}" class="{"aktiv" if k == aktiv else ""}">'
                f'<span class="i">{ikon}</span>{esc(cimke)}</a>' for k, ikon, cimke in pontok
            ) for nev, pontok in NAV
        )
        sav = (f'<a class="szerver-chip" href="/">{ikon_html(guild)}<span><b>{esc(guild.name)}</b>'
               f'<small>{getattr(guild, "member_count", 0)} tag • váltás</small></span></a><nav>{csoportok}</nav>')
        morzsa = esc(guild.name)
    else:
        sav = '<nav><div class="csoport">Menü</div><a href="/" class="aktiv"><span class="i">🏠</span>Szerverek</a></nav>'
        morzsa = "Irányítópult"
    also = ""
    if guild is not None:
        gyors = [("", "📊", "Áttekintés"), ("nyitas", "🟢", "Nyitás"), ("jelentkezesek", "📝", "Jelentkezés"), ("moderacio", "🛡️", "Moderáció")]
        also = ('<nav class="alsosav" aria-label="Gyors menü">' + "".join(
            f'<a href="/szerver/{guild.id}{"/" + k if k else ""}" class="{"aktiv" if k == aktiv else ""}"><span class="i">{ikon}</span>{esc(cimke)}</a>'
            for k, ikon, cimke in gyors) + '<a href="#" id="menu-tobb"><span class="i">☰</span>Több</a></nav>')
    lab = ""
    if felhasznalo:
        lab = (f'<div class="felhasznalo"><span>👤 {esc(felhasznalo["n"])}</span>'
               f'<form method="post" action="/kilepes"><input type="hidden" name="csrf" value="{esc(felhasznalo["c"])}">'
               '<button class="masodlagos kicsi">Kilépés</button></form></div>')
    toast = ""
    if uzenet:
        toast = f'<div class="toast {"hiba" if uzenet[0] == "hiba" else ""}">{"✅" if uzenet[0] != "hiba" else "⚠️"} {esc(uzenet[1])}</div>'
    return (
        f'<!doctype html><html lang="hu" data-tema="sotet"><head><meta charset="utf-8">'
        f'<meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover"><meta name="theme-color" content="#0c0e13"><title>{esc(cim)} • Irányítópult</title>'
        f"<style>{CSS}</style><noscript><style>.mentes-sav{{display:flex}}</style></noscript></head><body>"
        f'<aside class="oldalsav"><a class="logo" href="/"><span class="logo-jel">🛡️</span><b>Irányítópult</b></a>{sav}{lab}</aside>'
        f'<div class="tartalom"><header class="felso"><button id="menu-gomb" class="masodlagos kicsi" aria-label="Menü">☰</button>'
        f'<span class="morzsa">{morzsa}</span><button id="tema" class="masodlagos kicsi" title="Világos / sötét téma">🌓</button></header>'
        f"<main>{tartalom}</main></div>{also}<div class=\"menu-hatter\"></div>{toast}"
        f'<script nonce="{nonce}">{JS}</script></body></html>'
    )


def bejelentkezes_oldal(cim: str, szoveg: str, gomb: str, link: str, nonce: str) -> str:
    return (
        f'<!doctype html><html lang="hu" data-tema="sotet"><head><meta charset="utf-8">'
        f'<meta name="viewport" content="width=device-width,initial-scale=1"><title>{esc(cim)}</title><style>{CSS}</style></head><body>'
        f'<div class="bejelentkezes"><div class="kartya"><span class="logo-jel">🛡️</span><h1>{esc(cim)}</h1>'
        f'<p class="leiras" style="margin:10px 0 24px;font-size:15px">{esc(szoveg)}</p>'
        f'<a class="gomb" href="{esc(link)}">{esc(gomb)}</a></div></div><script nonce="{nonce}">{JS}</script></body></html>'
    )


# ---------------------------------------------------------------------- komponensek
def oldalfej(cim: str, alcim: str = "", jobb: str = "") -> Nyers:
    return Nyers(f'<div class="oldalfej"><div><h1>{esc(cim)}</h1>' + (f"<p>{esc(alcim)}</p>" if alcim else "")
                 + f'</div><div class="sor">{jobb}</div></div>')


def kartya(cim: str, tartalom, leiras: str = "", jobb: str = "") -> Nyers:
    fej = ""
    if cim:
        fej = (f'<div class="fej"><div><h2>{esc(cim)}</h2>' + (f"<p>{esc(leiras)}</p>" if leiras else "")
               + f"</div><div class=\"sor\">{jobb}</div></div>")
    return Nyers(f'<section class="kartya">{fej}{tartalom}</section>')


def csempe(ertek, cimke_: str, ikon: str, szin: str = "") -> Nyers:
    return Nyers(f'<div class="csempe {szin}"><div class="jel">{ikon}</div><div><b>{esc(str(ertek))}</b>'
                 f'<span class="c">{esc(cimke_)}</span></div></div>')


def cimke(szoveg: str, tipus: str = "") -> Nyers:
    return Nyers(f'<span class="cimke {tipus}">{esc(szoveg)}</span>')


def ures(szoveg: str, ikon: str = "🗂️") -> Nyers:
    return Nyers(f'<div class="ures"><span class="nagy">{ikon}</span>{esc(szoveg)}</div>')


def tabla(fejlec: list[str], sorok: list[list], azon: str = "tabla", szuro: bool = True) -> Nyers:
    if not sorok:
        return ures("Nincs megjeleníthető adat.")
    kereso = (f'<input class="szuro" type="search" placeholder="🔎 Szűrés a táblázatban…" data-szuro="{azon}" '
              'style="margin-bottom:12px">') if szuro and len(sorok) > 5 else ""
    fej = "".join(f"<th>{esc(f)}</th>" for f in fejlec)
    torzs = "".join("<tr>" + "".join(f"<td>{_s(c)}</td>" for c in sor) + "</tr>" for sor in sorok)
    return Nyers(f'{kereso}<div class="gorgetheto"><table id="{azon}"><thead><tr>{fej}</tr></thead><tbody>{torzs}</tbody></table></div>')


def savos(szazalek: float) -> Nyers:
    return Nyers(f'<div class="savos"><i style="width:{max(0, min(100, szazalek)):.0f}%"></i></div>')


def ellenorzes(rendben: bool | None, cim: str, leiras: str = "", link: str = "") -> Nyers:
    """Egy sor a beállítás-ellenőrző listában. rendben: True / False / None (figyelmeztetés)."""
    jel = {True: "✅", False: "❌", None: "⚠️"}[rendben]
    gomb = f'<a class="gomb masodlagos kicsi" href="{esc(link)}">Javítás</a>' if link and rendben is not True else ""
    return Nyers(f'<div class="ellenorzes"><span class="j">{jel}</span><div style="flex:1"><b>{esc(cim)}</b>'
                 + (f"<small>{esc(leiras)}</small>" if leiras else "") + f"</div>{gomb}</div>")


# ---------------------------------------------------------------------- űrlapok
def urlap(akcio: str, csrf: str, tartalom, *, vissza: str, gomb: str = "Mentés", sav: bool = True,
          megerosites: str = "", osztaly: str = "", extra: str = "") -> Nyers:
    kiegeszites = f' data-megerosites="{esc(megerosites)}"' if megerosites else ""
    mentes = (f'<div class="mentes-sav"><span>Nem mentett változtatások (Ctrl+S)</span><button>{esc(gomb)}</button></div>'
              if sav else "")
    return Nyers(f'<form method="post" action="{esc(akcio)}" class="{osztaly}"{" data-valtozas" if sav else ""}{kiegeszites}{extra}>'
                 f'<input type="hidden" name="csrf" value="{esc(csrf)}"><input type="hidden" name="vissza" value="{esc(vissza)}">'
                 f"{tartalom}{mentes}</form>")


def opcio_html(opciok: list[tuple[str, str]], kivalasztott: set[str]) -> str:
    return "".join(f'<option value="{esc(v)}"{" selected" if v in kivalasztott else ""}>{esc(n)}</option>' for v, n in opciok)


def mezo_html(m: dict, ertek: str | None, opciok: dict[str, list[tuple[str, str]]], szerver: str = "", elotag: str = "") -> Nyers:
    """Egy beállítási mező a leírása (m) és a jelenlegi értéke alapján. Az elotag az id-k egyedivé tételére szolgál."""
    k, t = m["kulcs"], m["tipus"]
    azon = f"{elotag}{k}"
    seg = f'<div class="seg">{esc(m["seg"])}</div>' if m.get("seg") else ""
    osztaly = "mezo teljes" if m.get("teljes") else "mezo"
    cim = f'<label for="{azon}">{esc(m["nev"])}</label>'
    if t == "kapcsolo":
        bekapcsolva = (ertek if ertek is not None else str(m.get("alap", 0))) == "1"
        return Nyers(f'<div class="{osztaly}"><label class="kapcsolo"><input type="hidden" name="{k}" value="0">'
                     f'<input type="checkbox" name="{k}" value="1"{" checked" if bekapcsolva else ""}><span class="csuszka"></span>'
                     f'{esc(m["nev"])}</label>{seg}</div>')
    if t == "valasztek":
        ertek = ertek if ertek is not None else str(m.get("alap", ""))
        return Nyers(f'<div class="{osztaly}">{cim}<select id="{azon}" name="{k}">{opcio_html(m["lehetosegek"], {ertek})}</select>{seg}</div>')
    if t == "idopont":
        return Nyers(f'<div class="{osztaly}">{cim}<input id="{azon}" type="datetime-local" name="{k}" value="{esc(ertek or "")}">{seg}</div>')
    if t == "ido":
        return Nyers(f'<div class="{osztaly}">{cim}<input id="{azon}" type="time" name="{k}" value="{esc(ertek or m.get("alap", ""))}">{seg}</div>')
    if t == "napok":
        kivalasztott = set((ertek if ertek is not None else m.get("alap", "0,1,2,3,4,5,6")).split(","))
        napok = ["Hé", "Ke", "Sze", "Csü", "Pé", "Szo", "Va"]
        gombok = "".join(f'<label><input type="checkbox" name="{k}" value="{n}"{" checked" if str(n) in kivalasztott else ""}><span>{nap}</span></label>'
                         for n, nap in enumerate(napok))
        return Nyers(f'<div class="{osztaly}"><label>{esc(m["nev"])}</label><div class="nap-valaszto">{gombok}</div>{seg}</div>')
    if t in ("csatorna", "kategoria", "rang", "ticket_tipus"):
        return Nyers(f'<div class="{osztaly}">{cim}<select id="{azon}" name="{k}"><option value="">— nincs —</option>'
                     f'{opcio_html(opciok[t], {ertek} if ertek else set())}</select>{seg}</div>')
    if t == "csatornak":
        return Nyers(f'<div class="{osztaly}">{cim}<select id="{azon}" name="{k}" multiple>'
                     f'{opcio_html(opciok["csatorna"], set((ertek or "").split(",")))}</select>'
                     f'{seg}<div class="seg">Több csatorna is kijelölhető (Ctrl vagy Cmd + kattintás).</div></div>')
    if t == "szam":
        ertek = ertek if ertek is not None else str(m.get("alap", ""))
        return Nyers(f'<div class="{osztaly}">{cim}<input id="{azon}" type="number" name="{k}" min="{m["min"]}" max="{m["max"]}" '
                     f'step="{m.get("lepes", 1)}" value="{esc(ertek)}">{seg}</div>')
    if t == "szin":
        ertek = ertek or m.get("alap", "#5865f2")
        return Nyers(f'<div class="{osztaly}">{cim}<div class="sor"><input type="color" data-szoveg="{azon}" value="{esc(ertek)}">'
                     f'<input id="{azon}" type="text" name="{k}" value="{esc(ertek)}" maxlength="7" style="max-width:130px"></div>{seg}</div>')
    if t == "rovid":
        return Nyers(f'<div class="{osztaly}">{cim}<input id="{azon}" type="text" name="{k}" value="{esc(ertek if ertek is not None else m.get("alap", ""))}" '
                     f'maxlength="{m.get("max_hossz", 200)}">{seg}</div>')
    if t == "lista":
        ertek = ertek if ertek is not None else "\n".join(m.get("alap", []))
        return Nyers(f'<div class="{osztaly}">{cim}<textarea id="{azon}" name="{k}" rows="{m.get("sorok", 7)}">{esc(ertek)}</textarea>{seg}</div>')
    elonezet = ""
    if m.get("elonezet"):
        elonezet = f' data-elonezet="{azon}-el" data-szerver="{esc(szerver)}"'
        seg += f'<div class="seg">Előnézet:</div><div class="elonezet" id="{azon}-el"></div>'
    return Nyers(f'<div class="{osztaly}">{cim}<textarea id="{azon}" name="{k}" rows="{m.get("sorok", 4)}"{elonezet}>'
                 f'{esc(ertek if ertek is not None else m.get("alap", ""))}</textarea>{seg}</div>')


# ---------------------------------------------------------------------- diagramok
def _szep_max(ertek: float) -> float:
    if ertek <= 4:
        return 4
    nagysag = 10 ** math.floor(math.log10(ertek))
    for lepes in (1, 2, 2.5, 5, 10):
        if ertek <= lepes * nagysag:
            return lepes * nagysag
    return 10 * nagysag


_diagram_szamlalo = itertools.count()


def oszlopdiagram(cimkek: list[str], sorozatok: list[tuple[str, list[float], str]], magassag: int = 230) -> Nyers:
    """Oszlopdiagram egy vagy több sorozattal. sorozatok: (név, értékek, szín)."""
    szel, bal, lent, fent = 780, 42, 30, 14
    legnagyobb = _szep_max(max([max(v) for _, v, _ in sorozatok if v] + [1]))
    n, sdb = len(cimkek), len(sorozatok)
    azon = f"d{next(_diagram_szamlalo)}"  # a színátmenet-azonosítók az egész oldalon egyediek kell legyenek
    sav = (szel - bal) / n
    oszlop_sz = max(3.0, min(36.0, (sav - 8) / sdb))
    vaszon = magassag - lent - fent
    resz = [f'<defs>' + "".join(
        f'<linearGradient id="{azon}g{i}" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="{szin}"/><stop offset="1" stop-color="{szin}" stop-opacity=".45"/></linearGradient>'
        for i, (_, _, szin) in enumerate(sorozatok)) + "</defs>"]
    for r in range(5):
        y = fent + vaszon * r / 4
        resz.append(f'<line class="racs-vonal" x1="{bal}" x2="{szel}" y1="{y:.1f}" y2="{y:.1f}"/>'
                    f'<text x="{bal - 8}" y="{y + 4:.1f}" text-anchor="end">{legnagyobb * (4 - r) / 4:g}</text>')
    kihagy = max(1, math.ceil(n / 12))
    for x_i, cimke_ in enumerate(cimkek):
        kozep = bal + sav * x_i + sav / 2
        if x_i % kihagy == 0:
            resz.append(f'<text x="{kozep:.1f}" y="{magassag - 8}" text-anchor="middle">{esc(cimke_)}</text>')
        for s_i, (nev, ertekek, _) in enumerate(sorozatok):
            h = vaszon * ertekek[x_i] / legnagyobb
            x = kozep - oszlop_sz * sdb / 2 + oszlop_sz * s_i + 1
            resz.append(f'<rect class="o" x="{x:.1f}" y="{fent + vaszon - h:.1f}" width="{oszlop_sz - 2:.1f}" height="{max(h, 0):.1f}" '
                        f'rx="4" fill="url(#{azon}g{s_i})"><title>{esc(cimke_)} – {esc(nev)}: {ertekek[x_i]:g}</title></rect>')
    jelmagy = ""
    if sdb > 1:
        jelmagy = '<div class="sor" style="margin-top:8px">' + "".join(
            f'<span><i style="display:inline-block;width:11px;height:11px;border-radius:3px;background:{szin};margin-right:6px"></i>{esc(nev)}</span>'
            for nev, _, szin in sorozatok) + "</div>"
    return Nyers(f'<div class="diagram"><svg viewBox="0 0 {szel} {magassag}" role="img">{"".join(resz)}</svg>{jelmagy}</div>')


SZINEK = ["#7c5cff", "#4f8cff", "#2ecc8f", "#ffc857", "#ff5d6c", "#ff8f5c", "#b86bff", "#4fd1d9"]


def fank_diagram(adatok: list[tuple[str, float]]) -> Nyers:
    osszes = sum(v for _, v in adatok)
    if not osszes:
        return ures("Még nincs adat.")
    kerulet, eltolas, reszek, jelmagy = 2 * math.pi * 62, 0.0, [], []
    for n, (nev, ertek) in enumerate(adatok):
        hossz = kerulet * ertek / osszes
        szin = SZINEK[n % len(SZINEK)]
        reszek.append(f'<circle cx="80" cy="80" r="62" fill="none" stroke="{szin}" stroke-width="22" stroke-dasharray="{hossz:.2f} {kerulet - hossz:.2f}" '
                      f'stroke-dashoffset="{-eltolas:.2f}" transform="rotate(-90 80 80)"><title>{esc(nev)}: {ertek:g}</title></circle>')
        jelmagy.append(f'<div><i style="background:{szin}"></i>{esc(nev)} <b>{ertek:g}</b> <span class="halk">({100 * ertek / osszes:.0f}%)</span></div>')
        eltolas += hossz
    return Nyers(f'<div class="fank"><svg viewBox="0 0 160 160" width="170" height="170">{"".join(reszek)}'
                 f'<text x="80" y="86" text-anchor="middle" style="fill:var(--szoveg);font-size:22px;font-weight:700">{osszes:g}</text></svg>'
                 f'<div class="jelmagyarazat">{"".join(jelmagy)}</div></div>')
