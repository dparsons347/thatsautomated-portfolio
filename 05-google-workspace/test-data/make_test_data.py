"""Builds the fake client documents used in the Project 5 tests and Loom.
All names, numbers and employers are invented. Run: python3 make_test_data.py"""
import random
from pathlib import Path
from reportlab.lib.pagesizes import letter
from reportlab.pdfgen import canvas
from PIL import Image, ImageDraw, ImageFont
from pypdf import PdfReader, PdfWriter

OUT = Path(__file__).parent


def form(path, title, rows, footer="Demonstration document. All data is fictional."):
    c = canvas.Canvas(str(OUT / path), pagesize=letter)
    w, h = letter
    c.setFont("Helvetica-Bold", 18)
    c.drawString(60, h - 80, title)
    c.setFont("Helvetica", 11)
    y = h - 130
    for k, v in rows:
        c.rect(60, y - 8, w - 120, 26, stroke=1, fill=0)
        c.drawString(70, y, k)
        c.drawRightString(w - 70, y, v)
        y -= 34
    c.setFont("Helvetica-Oblique", 9)
    c.drawString(60, 50, footer)
    c.save()


form("W-2 2025 Marcus Rivera.pdf", "Form W-2  Wage and Tax Statement  2025", [
    ("Employee", "Marcus Rivera"), ("Employer", "Pine Hollow Logistics LLC"),
    ("Employer EIN", "00-0000000 (fictional)"), ("1  Wages, tips, other comp.", "$61,240.00"),
    ("2  Federal income tax withheld", "$6,118.00"), ("16  State wages (AL)", "$61,240.00"),
    ("17  State income tax", "$2,450.00")])

form("1099-NEC Rivera Consulting.pdf", "Form 1099-NEC  Nonemployee Compensation  2025", [
    ("Recipient", "Marcus Rivera"), ("Payer", "Brightwater Events Inc."),
    ("1  Nonemployee compensation", "$8,900.00"), ("4  Federal income tax withheld", "$0.00")])

form("Chase bank statement March.pdf", "Checking Account Statement  March 2026", [
    ("Account holder", "Marcus Rivera"), ("Account", "xxxx-0000 (fictional)"),
    ("Beginning balance", "$4,210.55"), ("Deposits", "$5,880.00"),
    ("Withdrawals", "$5,102.37"), ("Ending balance", "$4,988.18")])

form("Brokerage 1099-B locked.pdf", "Form 1099-B  Proceeds from Broker Transactions  2025", [
    ("Recipient", "Marcus Rivera"), ("Payer", "Fictional Brokerage Co."),
    ("Proceeds", "$12,400.00"), ("Cost basis", "$10,950.00")])
reader = PdfReader(str(OUT / "Brokerage 1099-B locked.pdf"))
writer = PdfWriter()
for p in reader.pages:
    writer.add_page(p)
writer.encrypt(user_password="oakline", owner_password="oakline-owner", algorithm="AES-256")
with open(OUT / "Brokerage 1099-B locked.pdf", "wb") as f:
    writer.write(f)

# A phone photo of a receipt: large enough (over 20 KB) that it is not skipped as a logo.
random.seed(7)
img = Image.new("RGB", (900, 1400), (236, 232, 222))
d = ImageDraw.Draw(img)
for _ in range(9000):  # paper grain so the JPEG is a realistic size
    x, y = random.randrange(900), random.randrange(1400)
    g = random.randrange(205, 240)
    d.point((x, y), fill=(g, g - 3, g - 10))
try:
    font = ImageFont.truetype("DejaVuSans.ttf", 34)
except OSError:
    font = ImageFont.load_default()
lines = ["OFFICE SUPPLY DEPOT", "Auburn, AL", "", "03/14/2026  10:42", "",
         "Printer paper x4      31.96", "Toner cartridge       89.99", "File folders          12.49",
         "", "Subtotal             134.44", "Tax                   12.10", "TOTAL                146.54",
         "", "VISA ****0000", "Thank you"]
y = 120
for ln in lines:
    d.text((110, y), ln, fill=(40, 40, 40), font=font)
    y += 60
img = img.rotate(2.5, expand=False, fillcolor=(90, 90, 90))
img.save(OUT / "receipt office supplies.jpg", quality=85)

# A signature logo: small image that must be skipped.
logo = Image.new("RGB", (120, 40), (20, 70, 120))
ImageDraw.Draw(logo).text((10, 12), "Rivera", fill=(255, 255, 255))
logo.save(OUT / "signature-logo.png")

for p in sorted(OUT.iterdir()):
    if p.suffix in (".pdf", ".jpg", ".png"):
        print(f"{p.name:40s} {p.stat().st_size:>8d} bytes")
