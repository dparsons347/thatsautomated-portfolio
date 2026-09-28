"""Generate Project 2 sample invoices.

01 clean PDF  - Norton Lumber and Building Materials
02 clean PDF  - Hicks Hardware
03 phone photo JPG (skewed) - Ellis Equipment Rental
04 handwritten scan JPG - Tim Philip Masonry, total written wrong on purpose
05 byte-identical duplicate of 01
plus a blank printable form for real handwriting.
"""
import hashlib, os, random, shutil, subprocess
from decimal import Decimal, ROUND_HALF_UP
from reportlab.lib.pagesizes import letter
from reportlab.pdfgen import canvas
from reportlab.lib import colors
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from PIL import Image, ImageFilter, ImageDraw, ImageEnhance
import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "out")
os.makedirs(OUT, exist_ok=True)
pdfmetrics.registerFont(TTFont("Hand", os.path.join(HERE, "caveat.ttf")))
pdfmetrics.registerFont(TTFont("Hand2", os.path.join(HERE, "homemade-apple.ttf")))

W, H = letter
BILL_TO = ["Craig's Design and Landscaping Services", "123 Sierra Way", "San Pablo, CA 87999"]
TAX = Decimal("0.0825")
C = lambda x: Decimal(x).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
money = lambda d: f"${d:,.2f}"


def totals(lines, taxable=True):
    sub = sum(C(Decimal(q) * Decimal(p)) for _, q, p in lines)
    tax = C(sub * TAX) if taxable else Decimal("0.00")
    return sub, tax, sub + tax


def printed_invoice(path, v):
    c = canvas.Canvas(path, pagesize=letter)
    c.setTitle(f"Invoice {v['number']} - {v['vendor']}")
    c.setAuthor(v["vendor"])
    # header band
    c.setFillColor(colors.HexColor(v["color"]))
    c.rect(0, H - 90, W, 90, stroke=0, fill=1)
    c.setFillColor(colors.white)
    c.setFont("Helvetica-Bold", 20)
    c.drawString(50, H - 50, v["vendor"])
    c.setFont("Helvetica", 9)
    c.drawString(50, H - 68, "  |  ".join(v["addr"]))
    c.setFont("Helvetica-Bold", 26)
    c.drawRightString(W - 50, H - 55, "INVOICE")

    c.setFillColor(colors.black)
    y = H - 130
    c.setFont("Helvetica-Bold", 10)
    c.drawString(50, y, "BILL TO")
    c.setFont("Helvetica", 10)
    for i, l in enumerate(BILL_TO):
        c.drawString(50, y - 15 - i * 13, l)
    meta = [("Invoice #", v["number"]), ("Invoice date", v["date"]), ("Terms", v["terms"]), ("Due date", v["due"])]
    if v.get("po"):
        meta.append(("PO #", v["po"]))
    for i, (k, val) in enumerate(meta):
        c.setFont("Helvetica-Bold", 10)
        c.drawRightString(W - 150, y - i * 15, k)
        c.setFont("Helvetica", 10)
        c.drawString(W - 140, y - i * 15, val)

    # table
    y = H - 250
    c.setFillColor(colors.HexColor("#eeeeee"))
    c.rect(50, y - 6, W - 100, 20, stroke=0, fill=1)
    c.setFillColor(colors.black)
    c.setFont("Helvetica-Bold", 10)
    c.drawString(58, y, "Description")
    c.drawRightString(390, y, "Qty")
    c.drawRightString(470, y, "Unit price")
    c.drawRightString(W - 58, y, "Amount")
    c.setFont("Helvetica", 10)
    for desc, q, p in v["lines"]:
        y -= 22
        c.drawString(58, y, desc)
        c.drawRightString(390, y, str(q))
        c.drawRightString(470, y, money(Decimal(p)))
        c.drawRightString(W - 58, y, money(C(Decimal(q) * Decimal(p))))
    y -= 12
    c.line(50, y, W - 50, y)
    sub, tax, tot = totals(v["lines"], v.get("taxable", True))
    rows = [("Subtotal", sub), (f"Sales tax ({TAX*100:.2f}%)", tax), ("TOTAL DUE", tot)]
    for i, (k, val) in enumerate(rows):
        y -= 20
        bold = k == "TOTAL DUE"
        c.setFont("Helvetica-Bold" if bold else "Helvetica", 11 if bold else 10)
        c.drawRightString(470, y, k)
        c.drawRightString(W - 58, y, money(val))
    c.setFont("Helvetica", 9)
    c.setFillColor(colors.HexColor("#555555"))
    c.drawString(50, 90, v["footer"])
    c.drawString(50, 76, "Demonstration document for That's Automated portfolio. Not a real invoice.")
    c.save()
    return sub, tax, tot


def raster(pdf, png, dpi=150):
    base = png[:-4]
    subprocess.run(["pdftoppm", "-png", "-r", str(dpi), "-singlefile", pdf, base], check=True)
    return Image.open(png).convert("RGB")


def find_coeffs(dst, src):
    A = []
    for (x, y), (X, Y) in zip(dst, src):
        A.append([x, y, 1, 0, 0, 0, -X * x, -X * y])
        A.append([0, 0, 0, x, y, 1, -Y * x, -Y * y])
    A = np.array(A, dtype=float)
    B = np.array(src, dtype=float).reshape(8)
    return np.linalg.solve(A, B).tolist()


def phone_photo(page, out, seed):
    rnd = random.Random(seed)
    pw, ph = page.size
    cw, ch = int(pw * 1.35), int(ph * 1.25)
    # wood-ish desk background
    bg = np.zeros((ch, cw, 3), dtype=np.float32)
    bg[:] = (122, 92, 64)
    stripes = (np.sin(np.linspace(0, 60, cw))[None, :] * 10 + np.random.RandomState(seed).normal(0, 6, (ch, cw)))
    bg += stripes[..., None]
    canvas_img = Image.fromarray(np.clip(bg, 0, 255).astype(np.uint8))
    # destination quad: skewed, rotated, perspective
    ox, oy = cw * 0.14, ch * 0.08
    dst = [(ox + pw * 0.06, oy + ph * 0.03), (ox + pw * 1.02, oy - ph * 0.01),
           (ox + pw * 1.08, oy + ph * 1.02), (ox - pw * 0.02, oy + ph * 0.97)]
    coeffs = find_coeffs(dst, [(0, 0), (pw, 0), (pw, ph), (0, ph)])
    warped = page.transform((cw, ch), Image.PERSPECTIVE, coeffs, Image.BICUBIC, fillcolor=(0, 0, 0))
    mask = Image.new("L", page.size, 255).transform((cw, ch), Image.PERSPECTIVE, coeffs, Image.BICUBIC, fillcolor=0)
    shadow = mask.filter(ImageFilter.GaussianBlur(18))
    dark = Image.new("RGB", (cw, ch), (40, 30, 20))
    canvas_img = Image.composite(dark, canvas_img, shadow.point(lambda p: int(p * 0.55)))
    canvas_img.paste(warped, (0, 0), mask)
    # uneven lighting: brighter top-left, darker bottom-right
    yy, xx = np.mgrid[0:ch, 0:cw]
    light = 1.08 - 0.28 * ((xx / cw) * 0.6 + (yy / ch) * 0.4)
    arr = np.asarray(canvas_img, dtype=np.float32) * light[..., None]
    arr += np.random.RandomState(seed + 1).normal(0, 4, arr.shape)
    img = Image.fromarray(np.clip(arr, 0, 255).astype(np.uint8))
    img = img.filter(ImageFilter.GaussianBlur(0.8))
    img = ImageEnhance.Color(img).enhance(0.92)
    img.save(out, "JPEG", quality=78)


def handwritten(pdf_path, blank_path):
    """Pre-printed invoice pad filled in by hand. Written total is $40 high on purpose."""
    lines = [("Flagstone patio - labor", 16, "65.00"), ("Mortar, sand, gravel", 1, "212.50")]
    real_total = sum(C(Decimal(q) * Decimal(p)) for _, q, p in lines)
    written_total = real_total + Decimal("40.00")

    def form(c, fill):
        c.setStrokeColor(colors.HexColor("#1f3b73"))
        c.setFillColor(colors.HexColor("#1f3b73"))
        c.setFont("Helvetica-Bold", 22)
        c.drawString(50, H - 60, "Tim Philip Masonry")
        c.setFont("Helvetica", 9)
        c.drawString(50, H - 76, "Stone - Brick - Patios - Retaining Walls  |  San Pablo, CA")
        c.setFont("Helvetica-Bold", 14)
        c.drawRightString(W - 100, H - 60, "INVOICE  No.")
        c.line(W - 96, H - 62, W - 50, H - 62)
        c.setLineWidth(0.8)
        labels = [("Date", H - 120), ("Sold to", H - 150), ("Address", H - 180)]
        for lab, y in labels:
            c.setFont("Helvetica", 10)
            c.drawString(50, y, lab)
            c.line(110, y - 2, W - 50, y - 2)
        top = H - 220
        c.rect(50, 170, W - 100, top - 170)
        c.line(50, top - 22, W - 50, top - 22)
        for x in (340, 410, 480):
            c.line(x, 170, x, top)
        c.setFont("Helvetica-Bold", 9)
        for x, t in ((58, "DESCRIPTION"), (348, "QTY"), (418, "PRICE"), (488, "AMOUNT")):
            c.drawString(x, top - 15, t)
        for i in range(1, 11):
            y = top - 22 - i * 26
            if y > 170:
                c.setStrokeColor(colors.HexColor("#9fb0d0"))
                c.line(50, y, W - 50, y)
        c.setStrokeColor(colors.HexColor("#1f3b73"))
        c.setFont("Helvetica-Bold", 11)
        c.drawRightString(470, 145, "TOTAL")
        c.rect(480, 135, W - 530, 24)
        c.setFont("Helvetica", 8)
        c.drawString(50, 110, "Thank you for your business. Payment due on receipt.")
        c.drawString(50, 98, "Demonstration document for That's Automated portfolio. Not a real invoice.")
        if not fill:
            return
        ink = colors.HexColor("#1a1a6e")
        c.setFillColor(ink)
        rnd = random.Random(7)
        def hw(x, y, s, size=20, font="Hand"):
            c.setFont(font, size)
            c.saveState()
            c.translate(x, y)
            c.rotate(rnd.uniform(-1.8, 1.2))
            c.drawString(0, 0, s)
            c.restoreState()
        hw(W - 90, H - 60, "117", 24)
        hw(120, H - 118, "9/22/26", 22)
        hw(120, H - 148, "Craig's Design + Landscaping", 21)
        hw(120, H - 178, "123 Sierra Way, San Pablo", 21)
        for i, (d, q, p) in enumerate(lines):
            y = top - 22 - (i + 1) * 26 + 7
            hw(58, y, d, 20)
            hw(355, y, str(q), 20)
            hw(418, y, p, 20)
            hw(488, y, f"{C(Decimal(q) * Decimal(p)):,.2f}", 20)
        hw(58, top - 22 - 4 * 26 + 7, "(labor - no tax)", 18)
        hw(488, 141, f"{written_total:,.2f}", 22)
        hw(380, 60, "Tim P.", 26, "Hand2")

    c = canvas.Canvas(pdf_path, pagesize=letter)
    c.setTitle("Invoice 117 - Tim Philip Masonry")
    form(c, True)
    c.save()
    c = canvas.Canvas(blank_path, pagesize=letter)
    c.setTitle("Blank handwritten invoice form")
    form(c, False)
    c.save()
    return real_total, written_total


def scan_look(page, out, seed):
    """Flatbed/phone-scan look: slight rotation, off-white paper, grain."""
    img = page.rotate(-1.3, resample=Image.BICUBIC, expand=True, fillcolor=(236, 232, 222))
    arr = np.asarray(img, dtype=np.float32)
    paper = np.array([244, 240, 229], dtype=np.float32)
    arr = np.minimum(arr, paper)  # tint white to paper
    arr += np.random.RandomState(seed).normal(0, 5, arr.shape)
    Image.fromarray(np.clip(arr, 0, 255).astype(np.uint8)).filter(ImageFilter.GaussianBlur(0.5)).save(out, "JPEG", quality=80)


INVOICES = {
    "01": dict(vendor="Norton Lumber and Building Materials", color="#2e5e3e",
               addr=["4410 Industrial Pkwy, Richmond, CA 94804", "(510) 555-0142", "ar@nortonlumber.example"],
               number="NL-20417", date="09/15/2026", terms="Net 30", due="10/15/2026", po="CDL-1182",
               lines=[("2x4x8 SPF stud", 120, "4.18"), ('1/2" CDX plywood 4x8 sheet', 24, "38.95"),
                      ("Galvanized deck screws, 5 lb box", 6, "32.50")],
               footer="Remit to: Norton Lumber, PO Box 2210, Richmond, CA 94802. 1.5% monthly charge on past-due balances."),
    "02": dict(vendor="Hicks Hardware", color="#8a2d1f",
               addr=["88 Main St, San Pablo, CA 94806", "(510) 555-0199", "billing@hickshardware.example"],
               number="HH-8832", date="09/18/2026", terms="Net 15", due="10/03/2026", po="",
               lines=[('Irrigation valve, 1"', 8, "24.99"), ('PVC pipe Sch 40, 1" x 10 ft', 20, "7.45"),
                      ('Drip tubing 1/2", 500 ft roll', 2, "64.00")],
               footer="Questions about this invoice? Call the counter at (510) 555-0199."),
    "03": dict(vendor="Ellis Equipment Rental", color="#c47a12",
               addr=["1200 Harbor Way, Richmond, CA 94801", "(510) 555-0175", "rentals@ellisequip.example"],
               number="ER-5510", date="09/20/2026", terms="Due on receipt", due="09/20/2026", po="CDL-1190",
               lines=[("Mini excavator, daily rate", 2, "385.00"), ("Delivery and pickup", 1, "150.00"),
                      ("Damage waiver", 1, "57.75")],
               footer="Equipment returned after 5 PM is billed an additional day."),
}

if __name__ == "__main__":
    tmp = os.path.join(HERE, "tmp"); os.makedirs(tmp, exist_ok=True)
    summary = {}
    p1 = os.path.join(OUT, "01-norton-lumber-NL-20417.pdf")
    summary["01"] = printed_invoice(p1, INVOICES["01"])
    p2 = os.path.join(OUT, "02-hicks-hardware-HH-8832.pdf")
    summary["02"] = printed_invoice(p2, INVOICES["02"])
    p3pdf = os.path.join(tmp, "03-source.pdf")
    summary["03"] = printed_invoice(p3pdf, INVOICES["03"])
    phone_photo(raster(p3pdf, os.path.join(tmp, "03.png")), os.path.join(OUT, "03-ellis-rental-ER-5510-phone-photo.jpg"), 3)
    p4pdf = os.path.join(tmp, "04-source.pdf")
    summary["04"] = handwritten(p4pdf, os.path.join(OUT, "blank-handwritten-invoice-form.pdf"))
    scan_look(raster(p4pdf, os.path.join(tmp, "04.png")), os.path.join(OUT, "04-tim-philip-masonry-117-handwritten.jpg"), 4)
    shutil.copyfile(p1, os.path.join(OUT, "05-norton-lumber-NL-20417-resent.pdf"))
    for k, v in summary.items():
        print(k, [str(x) for x in v])
    for f in sorted(os.listdir(OUT)):
        h = hashlib.sha256(open(os.path.join(OUT, f), "rb").read()).hexdigest()
        print(h[:16], os.path.getsize(os.path.join(OUT, f)), f)
