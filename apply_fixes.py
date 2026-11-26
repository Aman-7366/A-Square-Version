"""
A SQUARE - one-click fixes for app.py

Put this file in the SAME folder as app.py (C:\\A Square New) and run:

    python apply_fixes.py

It will:
  1. back up your app.py to app.backup.py
  2. fix faded / hard-to-read text (labels, tabs, expanders, captions, tables)
  3. make the Admin > Overview number cards clearly visible
  4. add Edit / Hide / Delete for products in Admin > Products
  5. create .streamlit/config.toml (dark theme, so tables and dropdowns are readable)

Then restart the app:  streamlit run app.py
"""
import re
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
APP = ROOT / "app.py"

EXTRA_CSS = r'''
/* ===== READABILITY FIXES ===== */
.stApp label,.stApp [data-testid="stWidgetLabel"],.stApp [data-testid="stWidgetLabel"] p,.stApp [data-testid="stWidgetLabel"] label{color:#F8FAF8!important;opacity:1!important;font-weight:500}
.stApp [data-testid="stRadio"] label p,.stApp [data-testid="stRadio"] label div,.stApp [data-testid="stCheckbox"] label p,.stApp [data-testid="stCheckbox"] label span{color:#F8FAF8!important;opacity:1!important}
.stApp [data-testid="stCaptionContainer"],.stApp [data-testid="stCaptionContainer"] p{color:#B7C2BB!important;opacity:1!important}
.stApp input::placeholder,.stApp textarea::placeholder{color:#7f8b83!important;opacity:1!important}
.stApp input:disabled{-webkit-text-fill-color:#B7C2BB!important}

/* tabs */
.stApp [data-testid="stTabs"] button[role="tab"] p{color:#D5DDD7!important;font-weight:600;opacity:1!important}
.stApp [data-testid="stTabs"] button[role="tab"]:hover p{color:#27D17F!important}
.stApp [data-testid="stTabs"] button[role="tab"][aria-selected="true"] p{color:#27D17F!important}
.stApp [data-baseweb="tab-highlight"]{background-color:#27D17F!important}
.stApp [data-baseweb="tab-border"]{background-color:#26332B!important}

/* admin overview metric cards */
.stApp [data-testid="stMetric"]{background:#111713!important;border:1px solid #27D17F!important;border-radius:14px;padding:18px 20px}
.stApp [data-testid="stMetricLabel"],.stApp [data-testid="stMetricLabel"] *{color:#D5DDD7!important;opacity:1!important;font-size:15px!important;font-weight:600}
.stApp [data-testid="stMetricValue"],.stApp [data-testid="stMetricValue"] *{color:#27D17F!important;opacity:1!important;font-weight:700!important;font-size:40px!important}

/* expanders */
.stApp [data-testid="stExpander"] details{background:#111713!important;border:1px solid #26332B!important;border-radius:12px}
.stApp [data-testid="stExpander"] summary{background:#111713!important;color:#F8FAF8!important;border-radius:12px}
.stApp [data-testid="stExpander"] summary p,.stApp [data-testid="stExpander"] summary span{color:#F8FAF8!important;opacity:1!important}
.stApp [data-testid="stExpander"] summary svg{fill:#F8FAF8!important;color:#F8FAF8!important}
.stApp [data-testid="stExpander"] summary:hover{background:#0f3a24!important}
.stApp [data-testid="stExpander"] summary:hover p{color:#27D17F!important}

/* forms, dropdowns, number steppers, uploader */
.stApp [data-testid="stForm"]{border:1px solid #26332B!important;border-radius:14px;background:#0d130f}
.stApp [data-baseweb="select"] *{color:#F8FAF8!important}
.stApp [data-baseweb="tag"]{background:#0f3a24!important}
[data-baseweb="popover"] ul,[data-baseweb="popover"] li,[data-baseweb="menu"]{background:#111713!important;color:#F8FAF8!important}
[data-baseweb="popover"] li:hover{background:#0f3a24!important}
.stApp [data-testid="stNumberInput"] button{background:#111713!important;color:#F8FAF8!important;border-color:#26332B!important}
.stApp [data-testid="stFileUploaderDropzone"]{background:#111713!important;border:1px dashed #3a4a40!important}
.stApp [data-testid="stFileUploaderDropzone"] *{color:#D5DDD7!important}
.stApp [data-testid="stFileUploaderDropzone"] button{background:#27D17F!important;color:#05140b!important}

/* delete button = red */
[class*="st-key-del"] button{background:#ED3545!important;color:#fff!important}
[class*="st-key-del"] button:hover{background:#ff5463!important}
[class*="st-key-del"] button:disabled{background:#3a1d21!important;color:#8a6a6e!important}
'''

NEW_T2 = r'''    with t2:
        CATS = ["T-Shirts", "Hoodies", "Shirts", "Sweatshirts", "Bottomwear", "Jeans", "Accessories"]
        if st.session_state.get("flash"): st.success(st.session_state.pop("flash"))

        def _rm_upload(path):
            try:
                f = Path(path)
                if f.is_file() and f.resolve().parent == UPLOADS.resolve(): f.unlink()
            except OSError: pass

        def _save_uploads(files):
            out = []
            for f in files or []:
                fn = UPLOADS / f"{uuid.uuid4().hex}{Path(f.name).suffix.lower()}"
                fn.write_bytes(f.getvalue()); out.append(str(fn))
            return out

        st.dataframe(pd.read_sql_query(
            "SELECT id,name,category,gender,price,mrp,stock,featured,is_new,is_best,"
            "CASE active WHEN 1 THEN 'Visible' ELSE 'Hidden' END AS status FROM products ORDER BY id DESC", con),
            hide_index=True, use_container_width=True)

        # ---------- manage an existing product: edit / hide / delete ----------
        st.markdown("### Manage a product")
        prows = con.execute("SELECT * FROM products ORDER BY id DESC").fetchall()
        if not prows:
            st.info("No products yet. Add your first product below.")
        else:
            labels = {r["id"]: f"#{r['id']}  {r['name']}" + ("   (hidden)" if not r["active"] else "") for r in prows}
            sel = st.selectbox("Choose a product", list(labels), format_func=lambda i: labels[i], key="mp_sel")
            p = con.execute("SELECT * FROM products WHERE id=?", (sel,)).fetchone()
            try: imgs = json.loads(p["images"] or "[]") or []
            except Exception: imgs = []
            if not imgs and p["image"]: imgs = [p["image"]]
            K = lambda s: f"{s}_{sel}"

            status = "Visible in store" if p["active"] else "Hidden from store"
            st.markdown(f"**Status:** {status}  ·  **Stock:** {p['stock']}  ·  **Price:** {money(p['price'])}")
            if imgs:
                st.markdown('<div class="gth">' + "".join(f'<i style="{bg(im)}"></i>' for im in imgs[:8]) + "</div>", unsafe_allow_html=True)

            a1, a2 = st.columns(2)
            if a1.button("Hide from store" if p["active"] else "Show in store", key=K("vis"), use_container_width=True):
                con.execute("UPDATE products SET active=? WHERE id=?", (0 if p["active"] else 1, sel)); con.commit(); load_catalog.clear()
                st.session_state["flash"] = "Product is now hidden from the store." if p["active"] else "Product is now visible in the store."
                st.rerun()
            a2.caption("Hidden products stay saved here but customers cannot see or buy them.")

            st.markdown("#### Edit details")
            with st.form(K("edit")):
                n = st.text_input("Name", p["name"] or "", key=K("en"))
                cats = CATS + ([p["category"]] if p["category"] and p["category"] not in CATS else [])
                cat = st.selectbox("Category", cats, index=cats.index(p["category"]) if p["category"] in cats else 0, key=K("ec"))
                cols = ["Men", "Women", "Unisex"]
                gen = st.selectbox("Collection", cols, index=cols.index(p["gender"]) if p["gender"] in cols else 2, key=K("eg"))
                c1, c2, c3 = st.columns(3)
                pr = c1.number_input("Selling price", min_value=1.0, value=float(p["price"] or 1), step=1.0, key=K("ep"))
                mr = c2.number_input("MRP", min_value=1.0, value=float(p["mrp"] or p["price"] or 1), step=1.0, key=K("em"))
                sk = c3.number_input("Stock", min_value=0, value=int(p["stock"] or 0), step=1, key=K("es"))
                ds = st.text_area("Description", p["description"] or "", key=K("ed"))
                sz = st.text_input("Sizes (comma separated)", p["sizes"] or "", key=K("ez"))
                cl = st.text_input("Colours (comma separated)", p["colors"] or p["color"] or "", key=K("el"))
                f1, f2 = st.columns(2)
                fab = f1.text_input("Fabric", p["fabric"] or "", key=K("efa"))
                fit = f2.text_input("Fit", p["fit"] or "", key=K("efi"))
                keep = st.multiselect("Images to keep (remove any you no longer want)", imgs, default=imgs,
                                      format_func=lambda x: f"Image {imgs.index(x) + 1}", key=K("ek")) if imgs else []
                new_imgs = st.file_uploader("Add more images (jpg/png/webp, max 5 MB each)", accept_multiple_files=True,
                                            type=["jpg", "jpeg", "png", "webp"], key=K("eu"))
                g1, g2, g3 = st.columns(3)
                ft = g1.checkbox("Featured", bool(p["featured"]), key=K("eft")); nw = g2.checkbox("New arrival", bool(p["is_new"]), key=K("enw"))
                bs = g3.checkbox("Best seller", bool(p["is_best"]), key=K("ebs"))
                if st.form_submit_button("SAVE CHANGES", use_container_width=True):
                    if not n.strip(): st.error("Product name cannot be empty.")
                    elif mr < pr: st.error("MRP cannot be lower than the selling price.")
                    elif any(f.size > 5_000_000 for f in new_imgs or []): st.error("Each image must be under 5 MB.")
                    elif not keep and not new_imgs: st.error("Keep or upload at least one image.")
                    else:
                        paths = list(keep) + _save_uploads(new_imgs)
                        for im in imgs:
                            if im not in keep: _rm_upload(im)
                        con.execute("""UPDATE products SET name=?,category=?,gender=?,price=?,mrp=?,description=?,image=?,images=?,sizes=?,stock=?,
                            color=?,colors=?,fabric=?,fit=?,featured=?,is_new=?,is_best=? WHERE id=?""",
                            (n.strip(), cat, gen, pr, mr, ds, paths[0], json.dumps(paths), sz.strip(), int(sk),
                             cl.split(",")[0].strip(), cl.strip(), fab.strip(), fit.strip(), int(ft), int(nw), int(bs), sel))
                        con.commit(); load_catalog.clear()
                        st.session_state["flash"] = "Changes saved."; st.rerun()

            with st.expander("Delete this product"):
                st.warning("This permanently removes the product and its uploaded images. Past orders keep their own copy of the item details. "
                           "If you only want to take it off the store for now, use Hide instead.")
                sure = st.checkbox("Yes, delete this product permanently", key=K("sure"))
                if st.button("DELETE PRODUCT", disabled=not sure, key=K("del")):
                    for im in imgs: _rm_upload(im)
                    con.execute("DELETE FROM carts WHERE product_id=?", (sel,))
                    con.execute("DELETE FROM wishlist WHERE product_id=?", (sel,))
                    con.execute("DELETE FROM products WHERE id=?", (sel,))
                    con.commit(); load_catalog.clear()
                    try: del st.session_state["mp_sel"]
                    except KeyError: pass
                    st.session_state["flash"] = "Product deleted."; st.rerun()

        # ---------- add a new product ----------
        with st.expander("Add a new product"):
            with st.form("np"):
                n = st.text_input("Name"); cat = st.selectbox("Category", CATS); gen = st.selectbox("Collection", ["Men", "Women", "Unisex"])
                pr = st.number_input("Selling price", min_value=1.0, value=1.0, step=1.0); mr = st.number_input("MRP", min_value=1.0, value=1.0, step=1.0)
                ds = st.text_area("Description")
                sz = st.text_input("Sizes (comma separated)", "S,M,L,XL"); cl = st.text_input("Colours (comma separated)", "Black")
                sk = st.number_input("Stock", min_value=0, value=0, step=1)
                ims = st.file_uploader("Images (jpg/png/webp, max 5 MB each)", accept_multiple_files=True, type=["jpg", "jpeg", "png", "webp"])
                fl, nw, bs = st.columns(3); ft = fl.checkbox("Featured"); nw2 = nw.checkbox("New arrival"); bs2 = bs.checkbox("Best seller")
                if st.form_submit_button("PUBLISH PRODUCT"):
                    if not n.strip(): st.error("Enter a product name.")
                    elif mr < pr: st.error("MRP cannot be lower than the selling price.")
                    elif not ims: st.error("Add at least one image.")
                    elif any(f.size > 5_000_000 for f in ims): st.error("Each image must be under 5 MB.")
                    else:
                        paths = _save_uploads(ims)
                        con.execute("""INSERT INTO products(name,category,gender,price,mrp,description,image,images,sizes,stock,color,colors,featured,is_new,is_best)
                            VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""", (n.strip(), cat, gen, pr, mr, ds, paths[0], json.dumps(paths), sz, int(sk),
                                                                      cl.split(",")[0].strip(), cl, int(ft), int(nw2), int(bs2)))
                        con.commit(); load_catalog.clear()
                        st.session_state["flash"] = "Product published."; st.rerun()
'''

CONFIG_TOML = """[theme]
base = "dark"
primaryColor = "#27D17F"
backgroundColor = "#080B09"
secondaryBackgroundColor = "#111713"
textColor = "#F8FAF8"
font = "sans serif"
"""


def main():
    if not APP.exists():
        sys.exit(f"Could not find app.py next to this script ({APP}).")
    src = APP.read_text(encoding="utf-8")
    if "READABILITY FIXES" in src:
        sys.exit("Fixes were already applied to this app.py. Nothing to do.")

    # 1. extra CSS, inserted just before the @M / @SEARCH replacement line
    anchor = 'CSS = CSS.replace("@M "'
    i = src.find(anchor)
    if i < 0:
        sys.exit('Could not find the CSS section in app.py (looking for: CSS = CSS.replace("@M " ...). No changes made.')

    # 2. products tab
    m = re.search(r"^    with t2:\n.*?(?=^    with t3:\n)", src, re.S | re.M)
    if not m:
        sys.exit("Could not find the Products tab (with t2: ... with t3:) in app.py. No changes made.")

    shutil.copy(APP, ROOT / "app.backup.py")
    new = src[:i] + 'CSS += """' + EXTRA_CSS + '"""\n' + src[i:m.start()] if i < m.start() else None
    if new is None:
        sys.exit("Unexpected app.py layout. No changes made.")
    new += NEW_T2 + src[m.end():]
    APP.write_text(new, encoding="utf-8")

    # 3. dark theme config (makes tables / dropdowns readable)
    cfg_dir = ROOT / ".streamlit"
    cfg_dir.mkdir(exist_ok=True)
    cfg = cfg_dir / "config.toml"
    if cfg.exists():
        shutil.copy(cfg, cfg_dir / "config.backup.toml")
    cfg.write_text(CONFIG_TOML, encoding="utf-8")

    print("Done.")
    print("  - app.py updated (backup saved as app.backup.py)")
    print("  - .streamlit/config.toml written (dark theme)")
    print("Now STOP the app (Ctrl+C) and start it again:  streamlit run app.py")


if __name__ == "__main__":
    main()
