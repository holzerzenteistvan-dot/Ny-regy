"""Fejlesztői helyettesítők: discord / aiohttp / aiosqlite nélkül futtatható füstteszthez."""
import asyncio, sqlite3, sys, types

class Meta(type):
    def __getattr__(cls, n):
        if n.startswith("__"): raise AttributeError(n)
        return Anything
    def __getitem__(cls, i): return cls

class Anything(metaclass=Meta):
    def __init_subclass__(cls, **kw): pass
    def __init__(self, *a, **k): self._a, self._k = a, k
    def __call__(self, *a, **k):
        return a[0] if len(a) == 1 and callable(a[0]) and not k else Anything()
    def __getattr__(self, n):
        if n.startswith("__"): raise AttributeError(n)
        return Anything()
    def __or__(self, o): return self
    def __ror__(self, o): return self

def modul(nev, **attr):
    m = types.ModuleType(nev); m.__dict__.update(attr)
    m.__getattr__ = lambda n: Anything if not n.startswith("__") else (_ for _ in ()).throw(AttributeError(n))
    sys.modules[nev] = m; return m

class HTTPException(Exception): pass
class NotFound(HTTPException): pass
class Forbidden(HTTPException): pass
class Embed:
    def __init__(self, **k): self.__dict__.update(k); self.fields = []; self.color = k.get("color")
    def add_field(self, name, value, inline=True): self.fields.append((name, value, inline)); return self
    def set_footer(self, **k): self.footer = k; return self
    def set_author(self, **k): return self
    def set_thumbnail(self, **k): return self
class AllowedMentions:
    def __init__(self, **k): self.k = k
    @classmethod
    def none(cls): return cls(none=True)
class Object:
    def __init__(self, id): self.id = id
class Color:
    @staticmethod
    def blurple(): return 1
    green = red = gold = orange = light_grey = blurple
    def __init__(self, v): self.v = v

def telepit():
    d = modul("discord", HTTPException=HTTPException, NotFound=NotFound, Forbidden=Forbidden, Embed=Embed,
              AllowedMentions=AllowedMentions, Object=Object, Color=Color)
    modul("discord.ext"); modul("discord.ext.commands", Cog=Anything, Bot=Anything); modul("discord.ext.tasks")
    class Loop:
        def __init__(self, f): self.f = f
        def before_loop(self, g): return g
        def after_loop(self, g): return g
        def start(self, *a): pass
        def cancel(self): pass
        def __call__(self, *a, **k): return self.f(*a, **k)
        def __get__(self, o, t=None): return self
    sys.modules["discord.ext.tasks"].loop = lambda **k: (lambda f: Loop(f))
    d.ext = sys.modules["discord.ext"]; d.ext.commands = sys.modules["discord.ext.commands"]; d.ext.tasks = sys.modules["discord.ext.tasks"]
    d.app_commands = modul("discord.app_commands", Range=Anything, Choice=Anything, Group=Anything)
    d.ui = modul("discord.ui"); d.utils = modul("discord.utils")
    sys.modules["discord.ext"].commands = sys.modules["discord.ext.commands"]
    sys.modules["discord.ext"].tasks = sys.modules["discord.ext.tasks"]
    # aiohttp.web
    class Response:
        def __init__(self, text="", **k): self.text = text; self.k = k; self.cookies_torolve = []
        def del_cookie(self, n, **k): self.cookies_torolve.append(n)
        def set_cookie(self, n, v, **k): self.sutik = getattr(self, "sutik", {}); self.sutik[n] = v
    class HTTPFound(Exception):
        def __init__(self, location): super().__init__(location); self.location = location; self.sutik = {}
        def set_cookie(self, n, v, **k): self.sutik[n] = v
        def del_cookie(self, *a, **k): pass
    class HTTPForbidden(Exception):
        def __init__(self, text=""): super().__init__(text)
    class HTTPNotFound(Exception): pass
    class HTTPException_(Exception): pass
    web = modul("aiohttp.web", Response=Response, HTTPFound=HTTPFound, HTTPForbidden=HTTPForbidden, HTTPNotFound=HTTPNotFound,
                HTTPException=HTTPException_, middleware=lambda f: f, get=lambda *a: ("get", a), post=lambda *a: ("post", a),
                Request=Anything, StreamResponse=Anything, Application=Anything, AppRunner=Anything, TCPSite=Anything)
    modul("aiohttp", web=web, ClientSession=Anything)
    # aiosqlite: sqlite3 köré tett aszinkron burkoló
    class Kurzor:
        def __init__(s, c): s.c = c; s.lastrowid = c.lastrowid
        async def __aenter__(s): return s
        async def __aexit__(s, *a): s.c.close(); return False
        async def fetchone(s): return s.c.fetchone()
        async def fetchall(s): return s.c.fetchall()
    class Kapcsolat:
        def __init__(s, ut): s.k = sqlite3.connect(ut); s.k.row_factory = sqlite3.Row; s.row_factory = None
        def execute(s, sql, args=()):
            c = s.k.execute(sql, args)
            class Ido:
                async def __aenter__(_): return Kurzor(c)
                async def __aexit__(_, *a): c.close(); return False
                def __await__(_):
                    async def f():
                        c.fetchall(); return Kurzor(c)
                    return f().__await__()
            return Ido()
        async def executescript(s, q): s.k.executescript(q)
        async def executemany(s, q, r): s.k.executemany(q, r)
        async def commit(s): s.k.commit()
        async def rollback(s): s.k.rollback()
        async def close(s): s.k.close()
    class Csatlakozas:
        def __init__(s, ut): s.ut = ut
        def __await__(s):
            async def f(): return Kapcsolat(s.ut)
            return f().__await__()
    modul("aiosqlite", connect=Csatlakozas, Connection=Kapcsolat, Row=sqlite3.Row)
