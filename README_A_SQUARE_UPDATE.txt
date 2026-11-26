A SQUARE - Updated Streamlit Store

FILES
- app.py: complete updated application source
- requirements.txt: required Python packages

INSTALL / UPDATE
1. Keep a backup of your current app.py and a_square.db.
2. Replace the existing app.py with this updated app.py.
3. Add or replace requirements.txt in the same project root.
4. Do NOT delete a_square.db or your assets folder (logo, images, uploads).
5. Commit and push both files to GitHub. Streamlit Community Cloud will install
   packages from requirements.txt and restart the app after deployment.
6. Open Admin and use the new "About & Contact" tab to edit the About text,
   phone, WhatsApp number, email, Instagram URL and Facebook URL.
7. Use the new "Excel Export" tab to prepare and download the workbook.

WHATSAPP FORMAT
Enter the WhatsApp number with country code and digits only, for example:
919876543210
The public Contact page creates a wa.me link automatically.

ADMIN PASSWORD
Keep your existing ASQUARE_ADMIN_PASSWORD setting in Streamlit secrets.
Do not place the password in app.py or commit secrets.toml to a public repo.

EXCEL EXPORT
The workbook contains Orders, Products, Subscribers, Coupons, Carts and Wishlist
worksheets. It may include customer personal information; store it securely.
