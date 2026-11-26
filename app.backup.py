import streamlit as st
import sqlite3, json, os, uuid, re, html, base64, mimetypes
from datetime import datetime, date
from pathlib import Path
from urllib.parse import urlencode
import pandas as pd

ROOT = Path(__file__).parent
DB = ROOT / "a_square.db"
ASSETS = ROOT / "assets"
UPLOADS = ASSETS / "uploads"
UPLOADS.mkdir(parents=True, exist_ok=True)
FREE_SHIP_AT, SHIP_FEE, PAGE_SIZE = 999, 79, 12
FAVICON = ASSETS / "favicon.svg"

# ---------------------------------------------------------------------------
# Brand mark (traced from the original A SQUARE logo)
# ---------------------------------------------------------------------------
_GREEN = [(34.3, 11.2), (48.7, 35.5), (41.5, 41), (34.5, 29.2), (24.5, 45.5), (32.5, 46.2), (4.5, 63)]
_RED = [(49, 37.8), (64, 63), (52.5, 63), (46, 51.5), (35, 63), (22.2, 63)]

def _poly(pts, sc, ox, oy):
    return "M" + " L".join(f"{(x - 4.5) * sc + ox:.2f} {(y - 11.2) * sc + oy:.2f}" for x, y in pts) + " Z"

def mark_svg_body(sc, ox, oy):
    return f'<path d="{_poly(_GREEN, sc, ox, oy)}" fill="#25E87A"/><path d="{_poly(_RED, sc, ox, oy)}" fill="#EB1A2A"/>'

# Used only if assets/logo_dark.svg is missing
LOGO_SVG_FALLBACK = (
    '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 360 110" role="img" aria-label="A SQUARE">'
    + mark_svg_body(1.75, 10, 11)
    + '<text x="132" y="66" font-family="Poppins, Arial, sans-serif" font-weight="700" font-size="38" letter-spacing="2" fill="#FFFFFF">A SQUARE</text>'
    + '<text x="133" y="88" font-family="Poppins, Arial, sans-serif" font-weight="500" font-size="11" letter-spacing="2.4" fill="#25E87A">· WEAR YOUR IDENTITY.</text></svg>')

def svg_uri(svg): return "data:image/svg+xml;base64," + base64.b64encode(svg.encode()).decode()

# Branded placeholder: shown whenever a real image is missing or fails to load
PLACEHOLDER = svg_uri(
    '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 400 500"><defs><linearGradient id="g" x1="0" y1="0" x2="1" y2="1">'
    '<stop offset="0" stop-color="#16231b"/><stop offset="1" stop-color="#080B09"/></linearGradient></defs>'
    '<rect width="400" height="500" fill="url(#g)"/><g opacity=".9">' + mark_svg_body(3.2, 105, 165) + '</g></svg>')

def read_asset(name, fallback):
    try: return (ASSETS / name).read_text(encoding="utf-8")
    except OSError: return fallback

st.set_page_config(page_title="A SQUARE | Wear Your Identity", page_icon=str(FAVICON) if FAVICON.exists() else "🟩",
                   layout="wide", initial_sidebar_state="collapsed")

# ============================ DATABASE ============================
def db():
    con = sqlite3.connect(DB, check_same_thread=False)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA foreign_keys=ON")
    return con

def add_col(con, table, col, decl):
    if col not in [r[1] for r in con.execute(f"PRAGMA table_info({table})")]:
        con.execute(f"ALTER TABLE {table} ADD COLUMN {col} {decl}")

def init_db():
    con = db()
    con.execute("""CREATE TABLE IF NOT EXISTS products(
        id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT, category TEXT, gender TEXT,
        price REAL, mrp REAL, description TEXT, image TEXT, sizes TEXT, stock INTEGER,
        color TEXT, featured INTEGER DEFAULT 0, active INTEGER DEFAULT 1)""")
    con.execute("""CREATE TABLE IF NOT EXISTS orders(
        id TEXT PRIMARY KEY, created_at TEXT, customer TEXT, phone TEXT, email TEXT,
        address TEXT, items TEXT, subtotal REAL, discount REAL, shipping REAL,
        total REAL, payment TEXT, status TEXT)""")
    con.execute("CREATE TABLE IF NOT EXISTS subscribers(email TEXT PRIMARY KEY, created_at TEXT)")
    for c, d in [("images", "TEXT"), ("colors", "TEXT"), ("is_new", "INTEGER DEFAULT 0"),
                 ("is_best", "INTEGER DEFAULT 0"), ("fabric", "TEXT"), ("fit", "TEXT")]:
        add_col(con, "products", c, d)
    add_col(con, "orders", "payment_status", "TEXT DEFAULT 'Pending'")
    add_col(con, "orders", "coupon", "TEXT")
    add_col(con, "subscribers", "consent", "INTEGER DEFAULT 1")
    con.execute("""CREATE TABLE IF NOT EXISTS carts(sid TEXT, product_id INTEGER, size TEXT, color TEXT,
        qty INTEGER CHECK(qty>0), PRIMARY KEY(sid,product_id,size,color))""")
    con.execute("CREATE TABLE IF NOT EXISTS wishlist(sid TEXT, product_id INTEGER, PRIMARY KEY(sid,product_id))")
    con.execute("""CREATE TABLE IF NOT EXISTS coupons(code TEXT PRIMARY KEY, kind TEXT CHECK(kind IN('percent','fixed','freeship')),
        value REAL, min_order REAL DEFAULT 0, max_discount REAL, starts TEXT, expires TEXT,
        usage_limit INTEGER, used INTEGER DEFAULT 0, active INTEGER DEFAULT 1)""")
    con.execute("""CREATE TABLE IF NOT EXISTS site_content(k TEXT PRIMARY KEY, v TEXT)""")
    con.execute("""CREATE TABLE IF NOT EXISTS messages(id INTEGER PRIMARY KEY AUTOINCREMENT, created_at TEXT, name TEXT, phone TEXT, message TEXT)""")
    con.execute("INSERT OR IGNORE INTO coupons(code,kind,value,min_order,max_discount,usage_limit) VALUES('SQUARE10','percent',10,499,300,1000)")
    for k, v in {"announce": "Free shipping above ₹999  |  Use SQUARE10 for 10% off your first order",
                 "hero_title": "YOUR STYLE. YOUR RULES.",
                 "hero_text": "Discover everyday fashion that reflects your identity.",
                 "hero_image": "https://images.unsplash.com/photo-1523398002811-999ca8dec234?w=1800",
                 "contact_phone": "", "whatsapp": "", "contact_email": "", "address": "", "hours": "Mon–Sat, 10 AM – 7 PM",
                 "instagram": "", "facebook": "",
                 "about_story": ("A SQUARE started with a simple idea: good style should not be expensive or complicated. "
                                 "We make everyday pieces, from tees and hoodies to shirts and bottomwear, with a clean streetwear edge so you can look sharp without overthinking it.\n\n"
                                 "Every piece is designed to be worn on repeat: soft fabrics, honest fits and details that stay out of the way. "
                                 "Our logo says it best. A strong shape, two colours, and a signature that is yours to wear.")}.items():
        con.execute("INSERT OR IGNORE INTO site_content VALUES(?,?)", (k, v))
    if con.execute("SELECT COUNT(*) FROM products").fetchone()[0] == 0:
        U = "https://images.unsplash.com/"
        s = [("A Square Essential Tee", "T-Shirts", "Unisex", 599, 999, "Premium everyday cotton tee with a clean A Square signature.", "photo-1521572163474-6864f9cf17ab", "S,M,L,XL,XXL", 40, "Black,White", 1, 1, 1),
             ("Midnight Oversized Tee", "T-Shirts", "Men", 799, 1299, "Relaxed oversized fit made for everyday streetwear.", "photo-1503341504253-dff4815485f1", "S,M,L,XL,XXL", 30, "Black", 1, 1, 0),
             ("Classic White Tee", "T-Shirts", "Unisex", 549, 899, "A versatile essential with a soft-touch finish.", "photo-1523381210434-271e8be1f52b", "S,M,L,XL", 35, "White", 1, 0, 1),
             ("Urban Green Hoodie", "Hoodies", "Unisex", 1499, 2199, "A warm hoodie with a minimal urban silhouette.", "photo-1556821840-3a63f95609a7", "S,M,L,XL,XXL", 18, "Green,Black", 1, 1, 1),
             ("Everyday Cargo Pants", "Bottomwear", "Men", 1299, 1899, "Utility-inspired cargo pants with a tapered fit.", "photo-1515886657613-9f3515b0c78f", "28,30,32,34,36", 16, "Olive", 0, 0, 1),
             ("A Square Women Crop Tee", "T-Shirts", "Women", 649, 999, "A modern cropped silhouette for effortless styling.", "photo-1554568218-0f1715e72254", "XS,S,M,L,XL", 22, "Black", 0, 1, 0),
             ("Street Mode Sweatshirt", "Sweatshirts", "Unisex", 1199, 1799, "A relaxed sweatshirt for everyday comfort.", "photo-1578681994506-b8f463449011", "S,M,L,XL", 20, "Grey", 0, 0, 0),
             ("Signature Black Shirt", "Shirts", "Men", 1099, 1599, "A clean-cut shirt that moves from day to night.", "photo-1598033129183-c4f50c736f10", "S,M,L,XL", 14, "Black", 0, 0, 0)]
        for n, c, g, p, m, d, img, sz, stk, col, f, new, best in s:
            u = f"{U}{img}?w=900"
            con.execute("""INSERT INTO products(name,category,gender,price,mrp,description,image,images,sizes,stock,color,colors,featured,is_new,is_best)
                VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""", (n, c, g, p, m, d, u, json.dumps([u]), sz, stk, col.split(",")[0], col, f, new, best))
    con.execute("UPDATE products SET colors=color WHERE colors IS NULL OR colors=''")
    con.execute("UPDATE products SET images=json_array(image) WHERE images IS NULL OR images=''")
    con.commit(); con.close()

init_db()

# ============================ HELPERS ============================
def money(v): return f"₹{v:,.0f}"
def esc(s): return html.escape(str(s))

@st.cache_data(show_spinner=False)
def _file_uri(path, mtime):
    mime = mimetypes.guess_type(path)[0] or "image/jpeg"
    return f"data:{mime};base64," + base64.b64encode(Path(path).read_bytes()).decode()

def img_src(path):
    """Return something a browser can load. Remote URLs pass through; local files
    (admin uploads, assets/…) are inlined as data URIs, because the browser cannot
    open server file paths. Missing files fall back to the branded placeholder."""
    p = str(path or "").strip()
    if p.startswith(("http://", "https://", "data:")): return p
    f = Path(p) if Path(p).is_absolute() else ROOT / p
    try:
        if f.is_file(): return _file_uri(str(f), f.stat().st_mtime)
    except OSError: pass
    return PLACEHOLDER

def bg(path, extra=""):
    """CSS background with a built-in fallback: if the real image fails to load the
    placeholder layer underneath shows instead of a broken-image icon."""
    return f"{extra}background-image:url('{esc(img_src(path))}'),url('{PLACEHOLDER}')"

def cat_image(cat, default):
    for ext in ("jpg", "jpeg", "png", "webp"):
        f = ASSETS / "categories" / f"{re.sub(r'[^a-z0-9]+', '-', cat.lower())}.{ext}"
        if f.is_file(): return str(f)
    return default

def content(k):
    con = db(); r = con.execute("SELECT v FROM site_content WHERE k=?", (k,)).fetchone(); con.close()
    return r["v"] if r else ""

def digits(s): return re.sub(r"\D", "", s or "")

def intl(s):
    """Phone number -> international digits for wa.me / tel: links (10-digit numbers get India's +91)."""
    d = digits(s)
    return "91" + d if len(d) == 10 else d

def clean_url(v, base):
    """Accept a full link or just a handle (@asquare) and return a safe http(s) URL."""
    v = (v or "").strip()
    if not v: return ""
    if re.match(r"https?://", v, re.I): return v
    return base + v.lstrip("@/")

SOC = {
    "instagram": '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.9"><rect x="3" y="3" width="18" height="18" rx="5.2"/><circle cx="12" cy="12" r="4.2"/><circle cx="17.4" cy="6.6" r="1.1" fill="currentColor" stroke="none"/></svg>',
    "facebook": '<svg viewBox="0 0 24 24" fill="currentColor"><path d="M13.6 21.5v-8.2h2.8l.5-3.3h-3.3V7.9c0-.9.4-1.7 1.8-1.7h1.6V3.4c-.3 0-1.300-.2-2.500-.2-2.600 0-4.300 1.600-4.300 4.400V10H7.400v3.300h2.800v8.200z"/></svg>',
    "whatsapp": '<svg viewBox="0 0 24 24" fill="currentColor"><path d="M12.04 2a9.9 9.9 0 0 0-8.5 14.9L2 22l5.3-1.4A9.9 9.9 0 1 0 12.04 2zm0 1.8a8.1 8.1 0 1 1-4.2 15l-.3-.2-3.100.8.8-3-.2-.3a8.1 8.1 0 0 1 7-12.300zM8.700 7.300c-.2 0-.5.1-.7.400-.3.300-1 1-1 2.400s1 2.800 1.200 3c.1.200 2 3.200 5 4.400 2.500 1 3 .8 3.500.7.600-.1 1.700-.7 1.900-1.400.2-.7.2-1.200.2-1.400-.1-.1-.3-.2-.6-.3l-1.800-.9c-.3-.1-.5-.1-.7.100l-.8 1c-.1.200-.3.200-.6.100a6.600 6.600 0 0 1-3.200-2.800c-.2-.4.200-.4.700-1.300.1-.2 0-.3 0-.5l-.8-1.800c-.2-.5-.4-.4-.6-.4z"/></svg>',
}
PHONE_ICO = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M5 4h4l2 5-2.500 1.500a11 11 0 0 0 5 5L15 13l5 2v4a2 2 0 0 1-2 2A16 16 0 0 1 3 6a2 2 0 0 1 2-2z"/></svg>'
MAIL_ICO = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><rect x="3" y="5" width="18" height="14" rx="2"/><path d="M3 7l9 6 9-6"/></svg>'
PIN_ICO = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M12 21s7-6.300 7-12a7 7 0 0 0-14 0c0 5.700 7 12 7 12z"/><circle cx="12" cy="9" r="2.500"/></svg>'

def social_links():
    """(instagram_url, facebook_url, whatsapp_url, whatsapp_digits) from the admin settings."""
    ig = clean_url(content("instagram"), "https://instagram.com/")
    fb = clean_url(content("facebook"), "https://facebook.com/")
    wa = intl(content("whatsapp"))
    wa_url = f"https://wa.me/{wa}?text=" + "Hi%20A%20SQUARE%2C%20I%20need%20some%20help." if wa else ""
    return ig, fb, wa_url, wa

def socials_html():
    ig, fb, wa_url, _ = social_links()
    out = ""
    if wa_url: out += f'<a class="soc wa" target="_blank" rel="noopener noreferrer" href="{esc(wa_url)}" aria-label="Chat on WhatsApp" title="WhatsApp">{SOC["whatsapp"]}</a>'
    if ig: out += f'<a class="soc ig" target="_blank" rel="noopener noreferrer" href="{esc(ig)}" aria-label="Instagram" title="Instagram">{SOC["instagram"]}</a>'
    if fb: out += f'<a class="soc fb" target="_blank" rel="noopener noreferrer" href="{esc(fb)}" aria-label="Facebook" title="Facebook">{SOC["facebook"]}</a>'
    return out

@st.cache_data(ttl=60, show_spinner=False)
def load_catalog(_v=0):
    con = db(); rows = [dict(r) for r in con.execute("SELECT * FROM products WHERE active=1 ORDER BY featured DESC,id DESC")]; con.close()
    for p in rows:
        p["sizes_l"] = [s.strip() for s in (p["sizes"] or "").split(",") if s.strip()]
        p["colors_l"] = [c.strip() for c in (p["colors"] or p["color"] or "").split(",") if c.strip()]
        try: p["images_l"] = json.loads(p["images"]) or [p["image"]]
        except Exception: p["images_l"] = [p["image"]]
        p["disc"] = round((1 - p["price"] / p["mrp"]) * 100) if p["mrp"] and p["mrp"] > p["price"] else 0
    return rows

qp = st.query_params
if "sid" not in qp:
    qp["sid"] = uuid.uuid4().hex
SID = qp["sid"] if re.fullmatch(r"[0-9a-f]{32}", qp.get("sid", "")) else uuid.uuid4().hex

def url(**kw):
    return "?" + urlencode({"sid": SID, **{k: v for k, v in kw.items() if v not in (None, "")}})

def cart_rows():
    con = db()
    rows = [dict(r) for r in con.execute("""SELECT c.product_id pid,c.size,c.color,c.qty,p.name,p.price,p.mrp,p.image,p.stock,p.category
        FROM carts c JOIN products p ON p.id=c.product_id WHERE c.sid=? AND p.active=1""", (SID,))]
    con.close(); return rows

def cart_count():
    con = db(); n = con.execute("SELECT COALESCE(SUM(qty),0) FROM carts WHERE sid=?", (SID,)).fetchone()[0]; con.close(); return n

def wish_ids():
    con = db(); r = {x[0] for x in con.execute("SELECT product_id FROM wishlist WHERE sid=?", (SID,))}; con.close(); return r

def apply_coupon(code, subtotal):
    if not code: return 0, False, ""
    con = db(); c = con.execute("SELECT * FROM coupons WHERE code=?", (code.upper().strip(),)).fetchone(); con.close()
    today = date.today().isoformat()
    if not c or not c["active"]: return 0, False, "This coupon code is not valid."
    if c["starts"] and today < c["starts"]: return 0, False, "This coupon is not active yet."
    if c["expires"] and today > c["expires"]: return 0, False, "This coupon has expired."
    if c["usage_limit"] is not None and c["used"] >= c["usage_limit"]: return 0, False, "This coupon has reached its usage limit."
    if subtotal < (c["min_order"] or 0): return 0, False, f"Add items worth {money(c['min_order'])} or more to use this coupon."
    if c["kind"] == "freeship": return 0, True, "Free shipping applied."
    d = subtotal * c["value"] / 100 if c["kind"] == "percent" else c["value"]
    if c["max_discount"]: d = min(d, c["max_discount"])
    return round(min(d, subtotal)), False, f"Coupon {c['code']} applied."

def totals(rows, code):
    sub = sum(r["price"] * r["qty"] for r in rows)
    disc, fs, msg = apply_coupon(code, sub)
    ship = 0 if (sub - disc >= FREE_SHIP_AT or fs or not rows) else SHIP_FEE
    return sub, disc, ship, sub - disc + ship, msg

# ============================ STYLE ============================
SEARCH_ICON = svg_uri('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="#F8FAF8" stroke-width="1.8" stroke-linecap="round"><circle cx="11" cy="11" r="7"/><path d="M20 20l-4-4"/></svg>')

CSS = """
@import url('https://fonts.googleapis.com/css2?family=DM+Sans:wght@400;500;600;700&family=Space+Grotesk:wght@500;700&family=Poppins:wght@500;600;700&display=swap');
:root{--bg:#080B09;--bg2:#111713;--green:#27D17F;--red:#ED3545;--text:#F8FAF8;--muted:#9AA69E;--line:#26332B}
.stApp{background:radial-gradient(1200px 500px at 50% 18%,rgba(39,209,127,.10),transparent 60%),#080B09;color:var(--text);font-family:'DM Sans',sans-serif}
[data-testid="stHeader"],[data-testid="stToolbar"]{display:none}
.block-container{max-width:1280px;padding:0 1rem 2rem!important}
h1,h2,h3{font-family:'Space Grotesk',sans-serif!important;letter-spacing:-.5px;color:var(--text)}

/* ---- LINKS: kill Streamlit's blue underlined links everywhere, then colour per component ---- */
@M a,@M a:visited,@M a:hover,@M a:active{color:inherit!important;text-decoration:none!important}

/* ---- top bar + header (matches the reference design) ---- */
.topbar{display:flex;justify-content:space-between;gap:12px;padding:10px 0;font-size:13px;border-bottom:1px solid var(--line);flex-wrap:wrap}
.topbar b{color:var(--green)}
@M .topbar .tl a{color:var(--muted)!important;padding:0 8px}
@M .topbar .tl a:hover{color:var(--green)!important}
.hdr{display:flex;align-items:center;gap:22px;padding:14px 0;flex-wrap:wrap;border-bottom:2px solid var(--green)}
.hdr>a>img{height:56px;display:block}
.hdr form{flex:1;min-width:200px;margin:0}
.hdr input{width:100%;background-color:var(--bg2)!important;background-image:url("@SEARCH")!important;background-repeat:no-repeat!important;background-position:18px center!important;background-size:20px!important;
  border:1px solid var(--line);border-radius:999px;padding:13px 20px 13px 50px;color:var(--text);font:inherit;outline:none}
.hdr input:focus{border-color:var(--green)}
.pnav{display:flex;align-items:center;gap:2px;background:var(--bg2);border:1px solid var(--line);border-radius:999px;padding:5px}
.pnav>a,.pnav summary{list-style:none;cursor:pointer;display:flex;align-items:center;gap:8px;padding:9px 16px;border-radius:999px;font-weight:600;font-size:14px;white-space:nowrap}
.pnav summary::-webkit-details-marker{display:none}
.pnav svg{width:16px;height:16px;stroke:currentColor;fill:none;stroke-width:1.9;stroke-linecap:round;stroke-linejoin:round;flex:none}
@M .pnav>a{color:var(--text)!important}
@M .pnav>a.on{background:#0f3a24;color:var(--green)!important}
@M .pnav>a:hover{color:var(--green)!important}
.pnav summary{color:var(--text)}.pnav summary:hover{color:var(--green)}
.dd{position:relative}
.ddm{position:absolute;top:115%;left:0;z-index:99;background:var(--bg2);border:1px solid var(--line);border-radius:14px;padding:8px;min-width:180px;display:flex;flex-direction:column}
@M .ddm a{padding:8px 12px;border-radius:8px;font-size:14px;color:var(--text)!important}
@M .ddm a:hover{background:#0f3a24;color:var(--green)!important}
.icons{display:flex;gap:14px;align-items:center}
.ic{position:relative;display:inline-flex;width:30px;height:30px}
.ic svg{width:28px;height:28px;stroke:#F8FAF8;fill:none;stroke-width:1.8;stroke-linecap:round;stroke-linejoin:round}
.badge{position:absolute;top:-6px;right:-8px;background:var(--red);color:#fff;border-radius:999px;font-size:11px;min-width:18px;height:18px;line-height:18px;text-align:center;font-weight:700}
.cartlink{display:flex;flex-direction:column;align-items:center;font-size:12px;gap:1px;color:var(--text)}
.avatar{width:46px;height:46px;border-radius:50%;border:1px solid var(--line);background:var(--bg2);display:flex;align-items:center;justify-content:center}
.avatar svg{width:22px;height:22px;stroke:#F8FAF8;fill:none;stroke-width:1.8}

/* ---- hero ---- */
.hero{border-radius:20px;border:1px solid var(--line);min-height:380px;padding:56px 6%;display:flex;flex-direction:column;justify-content:center;background-size:cover;background-position:center;background-color:var(--bg2);margin-top:18px}
.hero h1{font-size:clamp(36px,6.5vw,76px);line-height:1;margin:0 0 14px;max-width:760px}
.hero p{color:#cdd6cf;font-size:17px;max-width:480px;margin-bottom:24px}
.cta{display:inline-block;background:var(--green);font-weight:700;padding:13px 26px;border-radius:10px;width:fit-content}
@M .cta{color:#05140b!important}
.cta:hover{background:#53e99c}
@M .cta.ghost{background:transparent;border:1px solid var(--line);color:var(--text)!important}
.sec{font-family:'Space Grotesk';font-size:26px;font-weight:700;margin:34px 0 4px}
.sub{color:var(--muted);font-size:14px;margin-bottom:14px}

/* ---- section head + pills ---- */
.pagehead{display:flex;justify-content:space-between;align-items:flex-end;gap:16px;flex-wrap:wrap;margin:34px 0 20px}
.pagehead h2{font-size:clamp(28px,4vw,46px);font-weight:800;margin:0;text-transform:uppercase}
.pagehead h2 span{color:var(--green)}
.rule{display:flex;align-items:center;gap:14px;color:var(--muted);margin-top:6px}.rule i{width:56px;height:2px;background:var(--green)}
.pills{display:flex;gap:10px;flex-wrap:wrap}
.pills a{padding:9px 20px;border:1px solid var(--line);border-radius:999px;background:var(--bg2);font-size:14px;font-weight:500}
@M .pills a{color:var(--text)!important}
@M .pills a.on,@M .pills a:hover{background:var(--green);color:#05140b!important;border-color:var(--green)}

/* ---- category cards ---- */
.catgrid{display:grid;grid-template-columns:repeat(3,1fr);gap:20px}
.cat{position:relative;display:block;aspect-ratio:4/4.6;border:1.5px solid var(--green);border-radius:16px;overflow:hidden;box-shadow:0 0 0 1px rgba(39,209,127,.15);background:var(--bg2)}
.cat .bgimg{position:absolute;inset:0;background-size:cover;background-position:center;transition:transform .35s}
.cat:hover .bgimg{transform:scale(1.04)}
.cat:after{content:"";position:absolute;inset:0;background:linear-gradient(to top,rgba(5,12,8,.92) 0%,rgba(5,12,8,0) 45%)}
@M .cat{color:var(--text)!important}
.cat .cap{position:absolute;left:14px;right:14px;bottom:14px;z-index:2;display:flex;align-items:center;gap:12px;font-weight:700;font-size:18px}
.cat .ci{width:46px;height:46px;border:1.5px solid var(--green);border-radius:50%;display:flex;align-items:center;justify-content:center;font-size:20px;background:rgba(8,11,9,.6)}
.cat .ch{margin-left:auto;width:34px;height:34px;border:1px solid #cfd8d1;border-radius:50%;display:flex;align-items:center;justify-content:center;font-size:16px}

/* ---- trust strip ---- */
.trust{display:grid;grid-template-columns:repeat(4,1fr);margin-top:34px;padding:22px 0;border-top:1px solid var(--line);border-bottom:1px solid var(--line);background:linear-gradient(115deg,rgba(39,209,127,.16) 0 4%,transparent 4% 8%,rgba(39,209,127,.08) 8% 10%,transparent 10%)}
.trust>div{display:flex;gap:14px;align-items:center;justify-content:center;padding:0 10px;border-left:1px solid var(--line)}.trust>div:first-child{border:0}
.trust .ti{font-size:30px;color:var(--green)}.trust b{display:block;font-size:15px}.trust span{color:var(--muted);font-size:13px}

/* ---- product cards ---- */
.pgrid{display:grid;grid-template-columns:repeat(4,1fr);gap:16px}
.pcard{background:var(--bg2);border:1px solid var(--line);border-radius:14px;padding:10px;position:relative}
.pcard .im{display:block;aspect-ratio:4/5;overflow:hidden;border-radius:10px;background:#16201a}
.pcard .ph{display:block;width:100%;height:100%;background-size:cover;background-position:center;transition:transform .3s}
.pcard:hover .ph{transform:scale(1.03)}
.pcard .w{position:absolute;top:18px;right:18px;width:34px;height:34px;border-radius:50%;background:rgba(8,11,9,.8);display:flex;align-items:center;justify-content:center;font-size:17px}
@M .pcard .w{color:var(--text)!important}
@M .pcard .w.on{color:var(--red)!important}
.pcard .b{position:absolute;top:18px;left:18px;display:flex;flex-direction:column;gap:4px}
.pill{font-size:10px;font-weight:700;padding:3px 8px;border-radius:5px;background:var(--green);color:#05140b;width:fit-content}
.pill.r{background:var(--red);color:#fff}
.pn{font-weight:600;margin-top:10px;font-size:15px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.pm{color:var(--muted);font-size:12px;margin-top:3px}
.pp{margin-top:6px;font-weight:700}.pp s{color:#77827a;font-weight:400;font-size:12px;margin-left:6px}.pp em{color:var(--green);font-style:normal;font-size:12px;margin-left:6px}
.oos{color:var(--red);font-size:12px;font-weight:600}

/* ---- product page gallery / cart thumb ---- */
.gmain{aspect-ratio:4/5;border-radius:14px;border:1px solid var(--line);background-size:cover;background-position:center;background-color:var(--bg2)}
.gth{display:grid;grid-template-columns:repeat(4,1fr);gap:8px;margin-top:8px}
.gth i{display:block;aspect-ratio:1;border-radius:10px;border:1px solid var(--line);background-size:cover;background-position:center;background-color:var(--bg2)}
.cth{width:90px;height:112px;border-radius:10px;border:1px solid var(--line);background-size:cover;background-position:center;background-color:var(--bg2)}

/* ---- generic ---- */
div.stButton>button,div.stFormSubmitButton>button{background:var(--green);color:#05140b;border:0;border-radius:10px;font-weight:700;min-height:44px}
div.stButton>button:hover{background:#53e99c;color:#05140b}
div.stButton>button:disabled{background:#1b261f;color:#5b685f}
input,textarea,[data-baseweb="select"]>div{background-color:var(--bg2)!important;color:var(--text)!important;border-color:var(--line)!important}
[data-testid="stMetric"]{background:var(--bg2);padding:14px;border:1px solid var(--line);border-radius:10px}
.box{background:var(--bg2);border:1px solid var(--line);border-radius:14px;padding:16px}
@M .box a{color:var(--green)!important}
.foot{border-top:1px solid var(--line);margin-top:48px;padding:28px 0;color:var(--muted);font-size:13px;display:flex;gap:24px;flex-wrap:wrap;justify-content:space-between}
.foot img{height:40px}
@M .foot a{color:var(--muted)!important}
@M .foot a:hover{color:var(--green)!important}
/* ---- social icons, contact cards, about ---- */
.socs{display:flex;gap:10px;flex-wrap:wrap}
.soc{width:44px;height:44px;border-radius:50%;display:inline-flex;align-items:center;justify-content:center;flex:none;transition:transform .15s}
.soc svg{width:22px;height:22px}
.soc:hover{transform:translateY(-2px)}
@M .soc{color:#fff!important}
.soc.ig{background:linear-gradient(45deg,#f9ce34,#ee2a7b 55%,#6228d7)}.soc.fb{background:#1877F2}.soc.wa{background:#25D366}
.soc.ph{background:#0f3a24}.soc.ph svg,.soc.ml svg,.soc.pn2 svg{stroke:#27D17F}.soc.ml{background:#0f3a24}.soc.pn2{background:#0f3a24}
.ccards{display:grid;grid-template-columns:repeat(auto-fit,minmax(290px,1fr));gap:16px;margin-top:6px}
.ccard{background:var(--bg2);border:1px solid var(--line);border-radius:16px;padding:20px;display:flex;gap:16px;align-items:flex-start}
.ccard .soc{width:52px;height:52px}.ccard .soc svg{width:26px;height:26px}
.ccard h4{margin:0 0 2px;font-size:17px}.ccard p{margin:0 0 12px;color:var(--muted);font-size:14px;word-break:break-word}
.cta.sm{padding:9px 18px;font-size:14px}
@M .cta.wa{background:#25D366;color:#06260f!important}
.fr{display:flex;flex-direction:column;align-items:flex-end;gap:12px}
.abhero{border:1px solid var(--line);border-radius:20px;padding:44px 6%;margin-top:18px;background:linear-gradient(100deg,rgba(39,209,127,.14),rgba(8,11,9,0) 70%),var(--bg2)}
.abhero h1{font-size:clamp(32px,5vw,58px);line-height:1.05;margin:0 0 12px}.abhero h1 span{color:var(--green)}
.abhero p{color:#cdd6cf;font-size:17px;line-height:1.7;max-width:760px;margin:0 0 14px}
.vals{display:grid;grid-template-columns:repeat(4,1fr);gap:16px}
.val{background:var(--bg2);border:1px solid var(--line);border-radius:16px;padding:22px}
.val .vi{font-size:28px}.val b{display:block;margin:10px 0 6px;font-size:17px}.val span{color:var(--muted);font-size:14px;line-height:1.5}
@media(max-width:900px){.vals{grid-template-columns:repeat(2,1fr)}.fr{align-items:flex-start}}
@media(max-width:600px){.vals{grid-template-columns:1fr}}
.ship{height:8px;background:var(--line);border-radius:9px;overflow:hidden;margin:6px 0}.ship i{display:block;height:100%;background:var(--green)}

@media(max-width:900px){.pnav{order:5;width:100%;overflow-x:auto}.catgrid{grid-template-columns:repeat(3,1fr)}.pgrid{grid-template-columns:repeat(3,1fr)}.trust{grid-template-columns:repeat(2,1fr);row-gap:18px}.trust>div:nth-child(3){border:0}}
@media(max-width:600px){.catgrid{grid-template-columns:repeat(2,1fr);gap:12px}.pgrid{grid-template-columns:repeat(2,1fr);gap:10px}.cat .cap{font-size:14px;gap:8px}.cat .ci{width:34px;height:34px;font-size:15px}.cat .ch{display:none}.hero{padding:36px 6%;min-height:300px}.hdr>a>img{height:44px}}
"""
CSS = CSS.replace("@M ", '.stApp [data-testid="stMarkdownContainer"] ').replace("@SEARCH", SEARCH_ICON)
st.markdown(f"<style>{CSS}</style>", unsafe_allow_html=True)

# ============================ ROUTING / ACTIONS ============================
page = qp.get("p", "home")
catalog = load_catalog()
by_id = {p["id"]: p for p in catalog}

if "wish" in qp:
    try:
        pid = int(qp["wish"]); con = db()
        if con.execute("SELECT 1 FROM wishlist WHERE sid=? AND product_id=?", (SID, pid)).fetchone():
            con.execute("DELETE FROM wishlist WHERE sid=? AND product_id=?", (SID, pid))
        elif pid in by_id:
            con.execute("INSERT INTO wishlist VALUES(?,?)", (SID, pid))
        con.commit(); con.close()
    except ValueError: pass
    del qp["wish"]

def go(p, **kw):
    for k in list(qp.keys()):
        if k != "sid": del qp[k]
    qp["p"] = p
    for k, v in kw.items(): qp[k] = str(v)
    st.rerun()

# ============================ HEADER ============================
logo = read_asset("logo_dark.svg", LOGO_SVG_FALLBACK)
logo_uri = svg_uri(logo)

def I(body): return f'<svg viewBox="0 0 24 24">{body}</svg>'
ICO = {
    "home": I('<path d="M3 11l9-8 9 8"/><path d="M5 10v10h5v-6h4v6h5V10"/>'),
    "shop": I('<rect x="3" y="3" width="7" height="7" rx="1.5"/><rect x="14" y="3" width="7" height="7" rx="1.5"/><rect x="3" y="14" width="7" height="7" rx="1.5"/><rect x="14" y="14" width="7" height="7" rx="1.5"/>'),
    "offers": I('<path d="M3 12V4h8l10 10-8 8z"/><circle cx="7.500" cy="8.500" r="1.200"/>'),
    "about": I('<circle cx="12" cy="12" r="9"/><path d="M12 11v6"/><circle cx="12" cy="7.500" r=".6"/>'),
    "contact": I('<rect x="3" y="5" width="18" height="14" rx="2"/><path d="M3 7l9 6 9-6"/>'),
    "chev": I('<path d="M6 9l6 6 6-6"/>'),
    "heart": I('<path d="M12 21s-8-5.200-8-11a4.600 4.600 0 0 1 8-3 4.600 4.600 0 0 1 8 3c0 5.800-8 11-8 11z"/>'),
    "cart": I('<path d="M2 3h3l2.500 12h11L21 7H6"/><circle cx="9" cy="20" r="1.500"/><circle cx="18" cy="20" r="1.500"/>'),
    "user": I('<circle cx="12" cy="8" r="4"/><path d="M4 21c0-4.400 3.600-7 8-7s8 2.600 8 7"/>'),
}
SHOP_LINKS = [("Men", {"g": "Men"}), ("Women", {"g": "Women"}), ("Unisex", {"g": "Unisex"}), ("Accessories", {"cat": "Accessories"}),
              ("New Arrivals", {"new": 1}), ("Best Sellers", {"best": 1}), ("Sale", {"sale": 1}), ("All products", {})]
dd = "".join(f'<a target="_self" href="{url(p="shop", **kw)}">{l}</a>' for l, kw in SHOP_LINKS)
def nav(label, key, href, on):
    return f'<a target="_self" class="{"on" if on else ""}" href="{href}">{ICO[key]}{label}</a>'
sugg = "".join(f'<option value="{esc(n)}">' for n in sorted({p["name"] for p in catalog}) + ["T-Shirts", "Hoodies", "Shirts", "Jeans", "Oversized"])
st.markdown(f"""<div class="topbar"><div>🔥 {esc(content("announce"))}</div>
<div class="tl"><a target="_self" href="{url(p='track')}">Track Order</a>|<a target="_self" href="{url(p='contact')}">Help</a>|<a target="_self" href="{url(p='contact')}">Contact</a></div></div>
<div class="hdr"><a target="_self" href="{url(p='home')}"><img src="{logo_uri}" alt="A SQUARE"></a>
<nav class="pnav">{nav("Home", "home", url(p="home"), page == "home")}
<details class="dd"><summary>{ICO["shop"]}Shop{ICO["chev"]}</summary><div class="ddm">{dd}</div></details>
{nav("Offers", "offers", url(p="shop", sale=1), False)}{nav("About", "about", url(p="about"), page == "about")}{nav("Contact", "contact", url(p="contact"), page == "contact")}</nav>
<form method="get" target="_self"><input type="hidden" name="sid" value="{SID}"><input type="hidden" name="p" value="shop">
<input name="q" list="sugg" placeholder="Search for your style…" value="{esc(qp.get('q', ''))}" aria-label="Search"><datalist id="sugg">{sugg}</datalist></form>
<div class="icons"><a target="_self" class="ic" href="{url(p='wishlist')}" title="Wishlist">{ICO["heart"]}<span class="badge">{len(wish_ids())}</span></a>
<a target="_self" class="cartlink" href="{url(p='cart')}" title="Cart"><span class="ic">{ICO["cart"]}<span class="badge">{cart_count()}</span></span>Cart</a>
<a target="_self" class="avatar" href="{url(p='account')}" title="Account">{ICO["user"]}</a></div></div>""", unsafe_allow_html=True)

# ============================ COMPONENTS ============================
def card(p, wl):
    badges = ("<span class='pill'>NEW</span>" if p["is_new"] else "") + ("<span class='pill r'>BESTSELLER</span>" if p["is_best"] else "")
    stock = "<span class='oos'>Out of stock</span>" if p["stock"] <= 0 else ("<span class='oos'>Only few left</span>" if p["stock"] < 8 else "")
    d = f"<em>{p['disc']}% OFF</em>" if p["disc"] else ""
    keep = {k: v for k, v in qp.items() if k not in ("sid", "p", "wish")}
    return f"""<div class="pcard"><a target="_self" class="im" href="{url(p='product', id=p['id'])}"><span class="ph" role="img" aria-label="{esc(p['name'])}" style="{bg(p['images_l'][0])}"></span></a>
<div class="b">{badges}</div><a target="_self" class="w {'on' if p['id'] in wl else ''}" href="{url(p=page, wish=p['id'], **keep)}" aria-label="Toggle wishlist">{'♥' if p['id'] in wl else '♡'}</a>
<div class="pn">{esc(p['name'])}</div><div class="pm">{esc(p['category'])} · {' / '.join(p['colors_l'][:3])} · {' '.join(p['sizes_l'][:5])}</div>
<div class="pp">{money(p['price'])}<s>{money(p['mrp'])}</s>{d}</div>{stock}</div>"""

def grid(items):
    if not items:
        st.markdown("<div class='box'>No products match. Try removing a filter or searching for a different keyword such as <b>tee</b> or <b>hoodie</b>.</div>", unsafe_allow_html=True); return
    wl = wish_ids()
    st.markdown('<div class="pgrid">' + "".join(card(p, wl) for p in items) + "</div>", unsafe_allow_html=True)

def section(title, sub=""):
    st.markdown(f'<div class="sec">{title}</div><div class="sub">{sub}</div>', unsafe_allow_html=True)

# ============================ PAGES ============================
if page == "home":
    st.markdown(f"""<div class="hero" style="background-image:linear-gradient(100deg,rgba(8,11,9,.95),rgba(8,11,9,.35)),url('{esc(img_src(content('hero_image')))}')">
<h1>{esc(content('hero_title'))}</h1><p>{esc(content('hero_text'))}</p>
<a target="_self" class="cta" href="{url(p='shop')}">EXPLORE COLLECTION</a></div>""", unsafe_allow_html=True)
    U = "https://images.unsplash.com/"
    cats = [("T-Shirts", "photo-1521572163474-6864f9cf17ab", "👕"), ("Hoodies", "photo-1556821840-3a63f95609a7", "🧥"), ("Shirts", "photo-1598033129183-c4f50c736f10", "👔"),
            ("Bottomwear", "photo-1515886657613-9f3515b0c78f", "👖"), ("Jeans", "photo-1542272604-787c3835535d", "👖"), ("Accessories", "photo-1553062407-98eeb64c6a62", "🎒")]
    pills = f'<a target="_self" class="on" href="{url(p="shop")}">All</a>' + "".join(f'<a target="_self" href="{url(p="shop", cat=c)}">{c}</a>' for c, _, _ in cats)
    tiles = "".join(
        f'<a target="_self" class="cat" href="{url(p="shop", cat=c)}"><div class="bgimg" role="img" aria-label="{c}" style="{bg(cat_image(c, f"{U}{i}?w=600&h=700&fit=crop"))}"></div>'
        f'<div class="cap"><span class="ci">{ic}</span>{c}<span class="ch">›</span></div></a>' for c, i, ic in cats)
    st.markdown(f"""<div class="pagehead"><div><h2>Shop by <span>category</span></h2><div class="rule"><i></i>Find your next favourite fit.</div></div><div class="pills">{pills}</div></div>
<div class="catgrid">{tiles}</div>""", unsafe_allow_html=True)
    st.markdown(f"""<div class="trust"><div><span class="ti">🚚</span><p style="margin:0"><b>Free Shipping</b><span>On Orders Above {money(FREE_SHIP_AT)}</span></p></div>
<div><span class="ti">🛡</span><p style="margin:0"><b>Secure Payments</b><span>UPI + COD</span></p></div>
<div><span class="ti">↩</span><p style="margin:0"><b>Easy Returns</b><span>Within 7 Days</span></p></div>
<div><span class="ti">🎧</span><p style="margin:0"><b>24/7 Support</b><span>We're Here to Help</span></p></div></div>""", unsafe_allow_html=True)
    section("Trending now", "The pieces everyone will be talking about."); grid([p for p in catalog if p["featured"]][:4])
    section("New arrivals"); grid([p for p in catalog if p["is_new"]][:4])
    section("Best sellers"); grid([p for p in catalog if p["is_best"]][:4])
    section("Exclusive offers", "Coupons apply automatically at checkout when you enter the code.")
    st.markdown(f"<div class='box'><b>SQUARE10</b> &nbsp;10% off orders above ₹499 (max ₹300). Free shipping above {money(FREE_SHIP_AT)}.</div>", unsafe_allow_html=True)
    section("Brand story")
    st.markdown("<div class='box'>A SQUARE is affordable everyday fashion with a streetwear edge. We make clothes that fit your day and your identity.</div>", unsafe_allow_html=True)
    section("Stay in the loop", "Get new drops and offers. Unsubscribe any time.")
    with st.form("news"):
        em = st.text_input("Email address"); ok = st.checkbox("I agree to receive A SQUARE marketing emails.")
        if st.form_submit_button("SUBSCRIBE"):
            if ok and re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", em.strip()):
                con = db(); con.execute("INSERT OR REPLACE INTO subscribers(email,created_at,consent) VALUES(?,?,1)", (em.strip().lower(), datetime.now().isoformat())); con.commit(); con.close()
                st.success("You're subscribed.")
            else: st.error("Enter a valid email and tick the consent box.")

elif page == "shop":
    st.markdown("<h1 style='margin-top:18px'>Shop</h1>", unsafe_allow_html=True)
    cats = sorted({p["category"] for p in catalog} | {"Accessories", "Jeans"})
    sizes = sorted({s for p in catalog for s in p["sizes_l"]}); colors = sorted({c for p in catalog for c in p["colors_l"]})
    with st.expander("Filters & sorting", expanded=False):
        a, b, c = st.columns(3)
        q = a.text_input("Search", qp.get("q", ""))
        cat = b.multiselect("Category", cats, default=[qp["cat"]] if qp.get("cat") in cats else [])
        g = c.multiselect("Collection", ["Men", "Women", "Unisex"], default=[qp["g"]] if qp.get("g") in ("Men", "Women", "Unisex") else [])
        d, e, f, h = st.columns(4)
        sz = d.multiselect("Size", sizes); col = e.multiselect("Colour", colors)
        pmin = f.number_input("Min price", 0, 100000, 0, 100); pmax = h.number_input("Max price", 0, 100000, 100000, 100)
        i, j, k, l = st.columns(4)
        mind = i.selectbox("Discount", ["Any", "20%+", "30%+", "40%+"]); instock = j.checkbox("In stock only")
        only_new = k.checkbox("New arrivals", value=qp.get("new") == "1"); only_best = l.checkbox("Best sellers", value=qp.get("best") == "1")
        sort = st.selectbox("Sort by", ["Popularity", "Newest first", "Price: low to high", "Price: high to low", "Highest discount"])
    data = catalog[:]
    if q: data = [p for p in data if all(w in f"{p['name']} {p['category']} {p['description']} {p['colors']}".lower() for w in q.lower().split())]
    if cat: data = [p for p in data if p["category"] in cat]
    if g: data = [p for p in data if p["gender"] in g]
    if sz: data = [p for p in data if set(sz) & set(p["sizes_l"])]
    if col: data = [p for p in data if set(col) & set(p["colors_l"])]
    data = [p for p in data if pmin <= p["price"] <= pmax]
    if mind != "Any": data = [p for p in data if p["disc"] >= int(mind[:2])]
    if qp.get("sale") == "1": data = [p for p in data if p["disc"] > 0]
    if instock: data = [p for p in data if p["stock"] > 0]
    if only_new: data = [p for p in data if p["is_new"]]
    if only_best: data = [p for p in data if p["is_best"]]
    keyf = {"Popularity": (lambda p: -p["is_best"]), "Newest first": (lambda p: -p["id"]), "Price: low to high": (lambda p: p["price"]),
            "Price: high to low": (lambda p: -p["price"]), "Highest discount": (lambda p: -p["disc"])}[sort]
    data.sort(key=keyf)
    pages = max(1, -(-len(data) // PAGE_SIZE))
    pg = st.number_input("Page", 1, pages, 1) if pages > 1 else 1
    st.caption(f"{len(data)} styles")
    grid(data[(pg - 1) * PAGE_SIZE: pg * PAGE_SIZE])
    if not data and q:
        st.caption("Popular searches: t-shirt, hoodie, oversized, cargo")

elif page == "product":
    try: p = by_id.get(int(qp.get("id", 0)))
    except ValueError: p = None
    if not p: st.warning("This product is no longer available."); st.stop()
    l, r = st.columns([1.05, 1])
    with l:
        thumbs = "".join(f'<i style="{bg(im)}"></i>' for im in p["images_l"][1:5])
        st.markdown(f'<div class="gmain" role="img" aria-label="{esc(p["name"])}" style="{bg(p["images_l"][0])}"></div>' + (f'<div class="gth">{thumbs}</div>' if thumbs else ""), unsafe_allow_html=True)
    with r:
        st.markdown(f"<h1 style='margin:0'>{esc(p['name'])}</h1><div class='pp' style='font-size:24px'>{money(p['price'])}<s>{money(p['mrp'])}</s><em>{p['disc']}% OFF</em></div>", unsafe_allow_html=True)
        st.write(p["description"])
        st.caption(f"Fabric: {p['fabric'] or 'Cotton blend'}  ·  Fit: {p['fit'] or 'Regular'}")
        size = st.radio("Size", p["sizes_l"], index=None, horizontal=True)
        color = st.radio("Colour", p["colors_l"], index=None, horizontal=True)
        with st.expander("Size guide & recommendation"):
            h = st.number_input("Height (cm)", 120, 220, 170); w = st.number_input("Weight (kg)", 30, 160, 65)
            fit = st.selectbox("Preferred fit", ["Slim", "Regular", "Oversized"])
            if st.button("Suggest my size"):
                bmi_i = (w / ((h / 100) ** 2))
                order = ["XS", "S", "M", "L", "XL", "XXL"]
                idx = 0 if w < 50 else 1 if w < 60 else 2 if w < 72 else 3 if w < 85 else 4 if w < 100 else 5
                idx = max(0, min(5, idx + {"Slim": -1 if bmi_i < 21 else 0, "Regular": 0, "Oversized": 1}[fit]))
                st.info(f"Suggested size: **{order[idx]}**. This is general guidance, not a guaranteed fit. Check the product's size chart.")
        qty = st.number_input("Quantity", 1, max(1, min(10, p["stock"])), 1)
        st.caption(f"{'In stock' if p['stock'] > 0 else 'Out of stock'}  ·  Delivery in 4–7 days  ·  Easy returns and exchanges")
        if st.button("ADD TO CART", use_container_width=True, disabled=p["stock"] <= 0):
            if not size or not color: st.error("Select a size and a colour first.")
            else:
                con = db()
                have = con.execute("SELECT COALESCE(SUM(qty),0) FROM carts WHERE sid=? AND product_id=? AND size=? AND color=?", (SID, p["id"], size, color)).fetchone()[0]
                if have + qty > p["stock"]: st.error(f"Only {p['stock']} available.")
                else:
                    con.execute("""INSERT INTO carts VALUES(?,?,?,?,?) ON CONFLICT(sid,product_id,size,color) DO UPDATE SET qty=qty+excluded.qty""", (SID, p["id"], size, color, int(qty)))
                    con.commit(); con.close(); go("cart")
                con.close()
        st.markdown(f'<a target="_self" class="cta ghost" href="{url(p="shop", wish=p["id"])}">♡ Wishlist</a>', unsafe_allow_html=True)

elif page == "wishlist":
    st.markdown("<h1 style='margin-top:18px'>Wishlist</h1>", unsafe_allow_html=True)
    items = [by_id[i] for i in wish_ids() if i in by_id]
    grid(items) if items else st.info("Nothing saved yet. Tap the heart on any product.")

elif page == "cart":
    st.markdown("<h1 style='margin-top:18px'>Your cart</h1>", unsafe_allow_html=True)
    rows = cart_rows()
    if not rows:
        st.info("Your cart is empty."); st.markdown(f'<a target="_self" class="cta" href="{url(p="shop")}">START SHOPPING</a>', unsafe_allow_html=True)
    else:
        con = db()
        for r in rows:
            c1, c2, c3, c4 = st.columns([1, 3, 1.3, 1.5])
            c1.markdown(f'<div class="cth" style="{bg(r["image"])}"></div>', unsafe_allow_html=True)
            c2.markdown(f"**{esc(r['name'])}**  \nSize {esc(r['size'])} · {esc(r['color'])}  \n{money(r['price'])}" + ("  \n:red[Only %d left]" % r["stock"] if r["qty"] > r["stock"] else ""))
            k = f"{r['pid']}{r['size']}{r['color']}"
            nq = c3.number_input("Qty", 1, 10, min(r["qty"], 10), key="q" + k)
            if nq != r["qty"]:
                con.execute("UPDATE carts SET qty=? WHERE sid=? AND product_id=? AND size=? AND color=?", (nq, SID, r["pid"], r["size"], r["color"])); con.commit(); st.rerun()
            if c4.button("Remove", key="r" + k):
                con.execute("DELETE FROM carts WHERE sid=? AND product_id=? AND size=? AND color=?", (SID, r["pid"], r["size"], r["color"])); con.commit(); st.rerun()
            if c4.button("Move to wishlist", key="m" + k):
                con.execute("INSERT OR IGNORE INTO wishlist VALUES(?,?)", (SID, r["pid"]))
                con.execute("DELETE FROM carts WHERE sid=? AND product_id=? AND size=? AND color=?", (SID, r["pid"], r["size"], r["color"])); con.commit(); st.rerun()
        con.close()
        code = st.text_input("Coupon code", st.session_state.get("coupon", "")).strip().upper(); st.session_state["coupon"] = code
        sub, disc, ship, total, msg = totals(rows, code)
        if msg: (st.success if disc or "Free" in msg else st.warning)(msg)
        left = max(0, FREE_SHIP_AT - (sub - disc))
        st.markdown(f"<div class='ship'><i style='width:{min(100, (sub-disc)/FREE_SHIP_AT*100):.0f}%'></i></div><div class='sub'>{'You have free shipping.' if left == 0 else f'Add {money(left)} more for free shipping.'}</div>", unsafe_allow_html=True)
        st.markdown(f"<div class='box'>Subtotal: {money(sub)}<br>Discount: −{money(disc)}<br>Shipping: {'FREE' if ship == 0 else money(ship)}<h2 style='margin:8px 0 0'>Total {money(total)}</h2></div>", unsafe_allow_html=True)
        if st.button("PROCEED TO CHECKOUT", use_container_width=True): go("checkout")

elif page == "checkout":
    st.markdown("<h1 style='margin-top:18px'>Checkout</h1>", unsafe_allow_html=True)
    rows = cart_rows()
    if not rows: st.warning("Your cart is empty."); st.stop()
    code = st.session_state.get("coupon", "")
    sub, disc, ship, total, _ = totals(rows, code)
    with st.form("co"):
        name = st.text_input("Full name *"); phone = st.text_input("Mobile number *", max_chars=10); email = st.text_input("Email")
        a1 = st.text_input("House number and street *"); a2 = st.text_input("Locality *")
        c1, c2, c3 = st.columns(3); city = c1.text_input("City *"); state = c2.text_input("State *"); pin = c3.text_input("PIN code *", max_chars=6)
        note = st.text_area("Delivery instructions")
        pay = st.radio("Payment", ["Cash on Delivery", "UPI (needs payment gateway: coming in Phase 2)"])
        st.markdown(f"**Payable: {money(total)}**")
        go_btn = st.form_submit_button("PLACE ORDER", use_container_width=True)
    if go_btn:
        if not (name.strip() and a1.strip() and a2.strip() and city.strip() and state.strip()) or not re.fullmatch(r"[6-9]\d{9}", phone) or not re.fullmatch(r"\d{6}", pin):
            st.error("Enter your name, a valid 10-digit mobile number, a 6-digit PIN code and the full address.")
        elif pay.startswith("UPI"):
            st.warning("Online payment is not connected yet. Choose Cash on Delivery for now.")
        else:
            con = db(); oid = "ASQ" + datetime.now().strftime("%y%m%d") + uuid.uuid4().hex[:5].upper()
            try:
                con.execute("BEGIN IMMEDIATE")
                for r in rows:
                    if con.execute("UPDATE products SET stock=stock-? WHERE id=? AND stock>=?", (r["qty"], r["pid"], r["qty"])).rowcount == 0:
                        raise ValueError(f"{r['name']} no longer has enough stock.")
                sub, disc, ship, total, _ = totals(rows, code)
                if code and disc: con.execute("UPDATE coupons SET used=used+1 WHERE code=?", (code,))
                con.execute("""INSERT INTO orders(id,created_at,customer,phone,email,address,items,subtotal,discount,shipping,total,payment,status,payment_status,coupon)
                    VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""", (oid, datetime.now().strftime("%d %b %Y, %I:%M %p"), name.strip(), phone, email.strip(),
                    f"{a1}, {a2}, {city}, {state} - {pin}. {note}", json.dumps(rows), sub, disc, ship, total, "Cash on Delivery", "Order Placed", "COD Pending", code))
                con.execute("DELETE FROM carts WHERE sid=?", (SID,)); con.commit()
                st.session_state["coupon"] = ""; load_catalog.clear(); con.close(); go("success", o=oid)
            except ValueError as e:
                con.rollback(); con.close(); st.error(str(e))

elif page == "success":
    st.success("Order placed.")
    st.markdown(f"<h1>Thank you for choosing A SQUARE.</h1><p>Order number: <b>{esc(qp.get('o',''))}</b>. Pay cash when it arrives. Track it any time with this number and your mobile number.</p>", unsafe_allow_html=True)

elif page == "track":
    st.markdown("<h1 style='margin-top:18px'>Track your order</h1>", unsafe_allow_html=True)
    o = st.text_input("Order number").strip().upper(); ph = st.text_input("Registered mobile number").strip()
    if st.button("TRACK"):
        con = db(); r = con.execute("SELECT * FROM orders WHERE id=? AND phone=?", (o, ph)).fetchone(); con.close()
        if r: st.success(f"Status: {r['status']}  ·  Payment: {r['payment_status']}  ·  Total: {money(r['total'])}")
        else: st.error("No order matches those details.")

elif page == "about":
    story = "".join(f"<p>{esc(x.strip())}</p>" for x in content("about_story").split("\n\n") if x.strip())
    st.markdown(f"""<div class="abhero"><h1>Wear your <span>identity.</span></h1>{story}
<div style="margin-top:18px"><a target="_self" class="cta" href="{url(p='shop')}">SHOP THE COLLECTION</a></div></div>""", unsafe_allow_html=True)
    section("What we stand for", "Four simple promises behind every piece.")
    st.markdown(f"""<div class="vals">
<div class="val"><div class="vi">🧵</div><b>Everyday comfort</b><span>Soft, breathable fabrics and honest fits made to be worn on repeat.</span></div>
<div class="val"><div class="vi">💸</div><b>Fair pricing</b><span>Streetwear style without the streetwear markup. Free shipping above {money(FREE_SHIP_AT)}.</span></div>
<div class="val"><div class="vi">🟩</div><b>Clean streetwear edge</b><span>Minimal silhouettes and a bold green-and-red signature you will recognise.</span></div>
<div class="val"><div class="vi">↩</div><b>Easy returns</b><span>Not the right fit? Returns and exchanges within 7 days.</span></div></div>""", unsafe_allow_html=True)
    section("Shop with confidence")
    st.markdown(f"""<div class="trust"><div><span class="ti">🚚</span><p style="margin:0"><b>Delivery in 4–7 days</b><span>Across India</span></p></div>
<div><span class="ti">🛡</span><p style="margin:0"><b>Pay your way</b><span>UPI + Cash on Delivery</span></p></div>
<div><span class="ti">↩</span><p style="margin:0"><b>7-day returns</b><span>Easy exchanges</span></p></div>
<div><span class="ti">💬</span><p style="margin:0"><b>Real support</b><span>Chat with us on WhatsApp</span></p></div></div>""", unsafe_allow_html=True)
    sl = socials_html()
    if sl: section("Follow A SQUARE", "New drops, styling ideas and offers."); st.markdown(f'<div class="socs">{sl}</div>', unsafe_allow_html=True)

elif page == "contact":
    ph, em, addr, hrs = content("contact_phone"), content("contact_email"), content("address"), content("hours")
    ig, fb, wa_url, wa = social_links()
    st.markdown("""<div class="pagehead"><div><h2>Get in <span>touch</span></h2><div class="rule"><i></i>Questions about an order, sizing or returns? We are happy to help.</div></div></div>""", unsafe_allow_html=True)
    def ccard(cls, icon, title, sub, href="", label="", btn=""):
        b = f'<a target="_blank" rel="noopener noreferrer" class="cta sm {btn}" href="{esc(href)}">{label}</a>' if href else ""
        return f'<div class="ccard"><span class="soc {cls}">{icon}</span><div><h4>{title}</h4><p>{sub}</p>{b}</div></div>'
    cards = ""
    if wa: cards += ccard("wa", SOC["whatsapp"], "WhatsApp", esc(content("whatsapp")), wa_url, "Chat on WhatsApp", "wa")
    if ph: cards += ccard("ph", PHONE_ICO, "Call us", esc(ph), "tel:+" + intl(ph), "Call now")
    if em: cards += ccard("ml", MAIL_ICO, "Email", esc(em), "mailto:" + em, "Send an email")
    if addr or hrs: cards += ccard("pn2", PIN_ICO, "Visit / hours", (esc(addr) + "<br>" if addr else "") + esc(hrs))
    if ig: cards += ccard("ig", SOC["instagram"], "Instagram", "Follow us for new drops", ig, "Open Instagram")
    if fb: cards += ccard("fb", SOC["facebook"], "Facebook", "Like and follow our page", fb, "Open Facebook")
    if cards: st.markdown(f'<div class="ccards">{cards}</div>', unsafe_allow_html=True)
    else: st.markdown("<div class='box'>Contact details will appear here once they are added in <b>Admin → Contact &amp; About</b>. Meanwhile, send us a message below.</div>", unsafe_allow_html=True)
    section("Send us a message", "Leave your details and we will get back to you.")
    with st.form("msg", clear_on_submit=True):
        n1 = st.text_input("Your name *"); p1 = st.text_input("Mobile number *", max_chars=10); m1 = st.text_area("How can we help? *", max_chars=1000)
        if st.form_submit_button("SEND MESSAGE"):
            if n1.strip() and re.fullmatch(r"[6-9]\d{9}", p1) and m1.strip():
                con = db(); con.execute("INSERT INTO messages(created_at,name,phone,message) VALUES(?,?,?,?)", (datetime.now().strftime("%d %b %Y, %I:%M %p"), n1.strip(), p1, m1.strip())); con.commit(); con.close()
                st.success("Thanks! Your message has been received.")
            else: st.error("Enter your name, a valid 10-digit mobile number and your message.")
    section("Quick answers")
    for q_, a_ in [("How long does delivery take?", "Orders usually arrive in 4–7 days."),
                   ("What is the shipping charge?", f"Shipping is {money(SHIP_FEE)}, and free on orders above {money(FREE_SHIP_AT)}."),
                   ("Can I return or exchange an item?", "Yes. Returns and exchanges are accepted within 7 days of delivery."),
                   ("How can I pay?", "Cash on Delivery today. UPI is coming soon."),
                   ("Where is my order?", "Use Track Order in the top bar with your order number and mobile number.")]:
        with st.expander(q_): st.write(a_)

elif page == "account":
    st.markdown("<h1 style='margin-top:18px'>Account</h1><div class='box'>Customer sign-up, saved addresses and order history arrive in Phase 2. You can already checkout as a guest and <a target='_self' href='" + url(p='track') + "'><b>track an order</b></a>.</div>", unsafe_allow_html=True)

elif page == "admin":
    st.markdown("<h1 style='margin-top:18px'>Admin</h1>", unsafe_allow_html=True)
    secret = st.secrets.get("ASQUARE_ADMIN_PASSWORD", os.getenv("ASQUARE_ADMIN_PASSWORD", "")) if hasattr(st, "secrets") else os.getenv("ASQUARE_ADMIN_PASSWORD", "")
    if not secret: st.error("Admin is disabled. Set ASQUARE_ADMIN_PASSWORD in Streamlit secrets or the environment."); st.stop()
    if not st.session_state.get("is_admin"):
        pw = st.text_input("Admin password", type="password")
        if pw and pw == secret: st.session_state["is_admin"] = True; st.rerun()
        elif pw: st.error("Incorrect password.")
        st.stop()
    t1, t2, t3, t4, t5, t6 = st.tabs(["Overview", "Products", "Orders", "Coupons", "Homepage", "Contact & About"])
    con = db()
    with t1:
        o = con.execute("SELECT COUNT(*) n, COALESCE(SUM(total),0) s FROM orders WHERE status!='Cancelled'").fetchone()
        a, b, c = st.columns(3); a.metric("Orders", o["n"]); b.metric("Revenue", money(o["s"])); c.metric("Low stock (<8)", con.execute("SELECT COUNT(*) FROM products WHERE stock<8 AND active=1").fetchone()[0])
    with t2:
        st.dataframe(pd.read_sql_query("SELECT id,name,category,gender,price,mrp,stock,is_new,is_best,active FROM products", con), hide_index=True, use_container_width=True)
        with st.form("np"):
            n = st.text_input("Name"); cat = st.selectbox("Category", ["T-Shirts", "Hoodies", "Shirts", "Sweatshirts", "Bottomwear", "Jeans", "Accessories"]); gen = st.selectbox("Collection", ["Men", "Women", "Unisex"])
            pr = st.number_input("Selling price", 1); mr = st.number_input("MRP", 1); ds = st.text_area("Description")
            sz = st.text_input("Sizes (comma separated)", "S,M,L,XL"); cl = st.text_input("Colours (comma separated)", "Black"); sk = st.number_input("Stock", 0)
            ims = st.file_uploader("Images (jpg/png/webp, max 5 MB each)", accept_multiple_files=True, type=["jpg", "jpeg", "png", "webp"])
            fl, nw, bs = st.columns(3); ft = fl.checkbox("Featured"); nw2 = nw.checkbox("New arrival"); bs2 = bs.checkbox("Best seller")
            if st.form_submit_button("PUBLISH PRODUCT"):
                paths = []
                for f in ims or []:
                    if f.size > 5_000_000: st.error(f"{f.name} is over 5 MB."); paths = None; break
                    ext = Path(f.name).suffix.lower(); fn = UPLOADS / f"{uuid.uuid4().hex}{ext}"; fn.write_bytes(f.getvalue()); paths.append(str(fn))
                if paths is not None and n and paths and mr >= pr:
                    con.execute("""INSERT INTO products(name,category,gender,price,mrp,description,image,images,sizes,stock,color,colors,featured,is_new,is_best)
                        VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""", (n, cat, gen, pr, mr, ds, paths[0], json.dumps(paths), sz, sk, cl.split(",")[0].strip(), cl, int(ft), int(nw2), int(bs2)))
                    con.commit(); load_catalog.clear(); st.success("Published.")
                elif paths is not None: st.error("Add a name, at least one image, and an MRP not lower than the price.")
        pid = st.number_input("Product ID", 1, step=1); ns = st.number_input("New stock", 0, step=1)
        if st.button("UPDATE STOCK"): con.execute("UPDATE products SET stock=? WHERE id=?", (ns, pid)); con.commit(); load_catalog.clear(); st.success("Stock updated.")
    with t3:
        od = pd.read_sql_query("SELECT id,created_at,customer,phone,total,payment,payment_status,status FROM orders ORDER BY rowid DESC", con)
        st.dataframe(od, hide_index=True, use_container_width=True)
        if not od.empty:
            oid = st.selectbox("Order", od["id"].tolist())
            stt = st.selectbox("Order status", ["Order Placed", "Confirmed", "Processing", "Packed", "Shipped", "Out for Delivery", "Delivered", "Cancelled", "Return Requested", "Returned / Refunded"])
            ps = st.selectbox("Payment status", ["Pending", "Paid", "Failed", "Refunded", "COD Pending", "COD Collected"])
            if st.button("UPDATE ORDER"): con.execute("UPDATE orders SET status=?,payment_status=? WHERE id=?", (stt, ps, oid)); con.commit(); st.success("Updated.")
    with t4:
        st.dataframe(pd.read_sql_query("SELECT * FROM coupons", con), hide_index=True, use_container_width=True)
        with st.form("cp"):
            cc = st.text_input("Code").upper(); kd = st.selectbox("Type", ["percent", "fixed", "freeship"]); vl = st.number_input("Value", 0.0)
            mo = st.number_input("Minimum order", 0.0); mx = st.number_input("Max discount (0 = none)", 0.0); ex = st.text_input("Expiry (YYYY-MM-DD, optional)"); ul = st.number_input("Usage limit", 1, value=100)
            if st.form_submit_button("SAVE COUPON") and cc:
                con.execute("INSERT OR REPLACE INTO coupons(code,kind,value,min_order,max_discount,expires,usage_limit,active) VALUES(?,?,?,?,?,?,?,1)", (cc, kd, vl, mo, mx or None, ex or None, ul)); con.commit(); st.success("Saved.")
    with t5:
        for k, lbl in [("announce", "Announcement bar"), ("hero_title", "Hero title"), ("hero_text", "Hero text"), ("hero_image", "Hero image URL")]:
            v = st.text_input(lbl, content(k), key="c" + k)
            if v != content(k): con.execute("UPDATE site_content SET v=? WHERE k=?", (v, k)); con.commit()
    with t6:
        st.caption("These details appear on the Contact page, the About page and the footer. Leave a field empty to hide it.")
        with st.form("contact_settings"):
            f_ph = st.text_input("Contact phone number", content("contact_phone"), placeholder="+91 98765 43210")
            f_wa = st.text_input("WhatsApp number (customers are sent straight to a WhatsApp chat)", content("whatsapp"), placeholder="+91 98765 43210")
            f_em = st.text_input("Email", content("contact_email"), placeholder="hello@yourbrand.com")
            f_ad = st.text_input("Address (optional)", content("address")); f_hr = st.text_input("Working hours", content("hours"))
            f_ig = st.text_input("Instagram link or @handle", content("instagram"), placeholder="https://instagram.com/yourhandle")
            f_fb = st.text_input("Facebook page link", content("facebook"), placeholder="https://facebook.com/yourpage")
            f_st = st.text_area("About story (leave a blank line between paragraphs)", content("about_story"), height=220)
            if st.form_submit_button("SAVE CONTACT & ABOUT"):
                errs = []
                for lbl, v in (("Contact phone", f_ph), ("WhatsApp number", f_wa)):
                    if v.strip() and not 10 <= len(digits(v)) <= 13: errs.append(f"{lbl} must have 10 to 13 digits.")
                if f_em.strip() and not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", f_em.strip()): errs.append("Enter a valid email address.")
                for lbl, v, base in (("Instagram", f_ig, "https://instagram.com/"), ("Facebook", f_fb, "https://facebook.com/")):
                    if v.strip() and not re.fullmatch(r"https?://[^\s\"'<>]+", clean_url(v, base)): errs.append(f"{lbl} link is not valid.")
                if errs:
                    for e_ in errs: st.error(e_)
                else:
                    for k_, v_ in {"contact_phone": f_ph, "whatsapp": f_wa, "contact_email": f_em, "address": f_ad, "hours": f_hr,
                                   "instagram": f_ig, "facebook": f_fb, "about_story": f_st}.items():
                        con.execute("INSERT OR REPLACE INTO site_content(k,v) VALUES(?,?)", (k_, v_.strip()))
                    con.commit(); st.success("Saved. Your Contact page and footer are updated.")
        st.markdown("**Customer messages**")
        st.dataframe(pd.read_sql_query("SELECT created_at,name,phone,message FROM messages ORDER BY id DESC", con), hide_index=True, use_container_width=True)
    con.close()

else:
    st.warning("Page not found.")

# ============================ FOOTER ============================
_fp = content("contact_phone")
st.markdown(f"""<div class="foot"><div><img src="{logo_uri}" alt="A SQUARE"><br>© 2026 A SQUARE</div>
<div class="fr"><div><a target="_self" href="{url(p='shop')}">Shop</a> · <a target="_self" href="{url(p='about')}">About</a> · <a target="_self" href="{url(p='contact')}">Contact</a> · <a target="_self" href="{url(p='track')}">Track order</a> · <a target="_self" href="{url(p='admin')}">Admin</a></div>
{f'<div><a href="tel:+{intl(_fp)}">📞 {esc(_fp)}</a></div>' if _fp else ''}<div class="socs">{socials_html()}</div></div></div>""", unsafe_allow_html=True)
