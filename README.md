# A SQUARE: Phase 1 storefront

Run: `pip install -r requirements.txt && streamlit run app.py`
Admin: set `ASQUARE_ADMIN_PASSWORD` (see `.streamlit/secrets.toml.example`), open the footer "Admin" link.

Your existing `a_square.db` works as is: new columns and tables are added automatically, nothing is dropped.

## Done in this pass
Logo (SVG, dark/light, favicon), announcement bar, header with search suggestions and wishlist/cart/account icons with live counts (Bag renamed to Cart), full-card clickable category and product images with fixed aspect ratios, filters + sorting + pagination, product page with required size/colour and size suggestion, wishlist, cart (DB-backed, survives page navigation), server-side coupon engine, COD checkout with atomic stock decrement, order tracking by order ID + mobile, basic admin (products with validated image uploads, stock, orders, coupons, homepage text).

## Not done yet
UPI gateway, customer accounts/password reset, reviews, custom T-shirt designer, abandoned carts, notifications, shipping/PIN checks, reports, SEO, Supabase migration, PNG logo export, automated tests.
