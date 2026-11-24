import io
import math
import secrets
import socket
import string
from urllib.parse import quote
import qrcode
from PIL import Image, ImageDraw, ImageFont


def get_local_lan_ip() -> str:
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.settimeout(0.5)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return "127.0.0.1"


def generate_secret_token(length: int = 4) -> str:
    alphabet = string.ascii_lowercase + string.digits
    return "".join(secrets.choice(alphabet) for _ in range(length))


def haversine_meters(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    r = 6371000  # Earth radius in meters
    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2) ** 2
    return 2 * r * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def optimize_image_to_webp(image_bytes: bytes, max_width: int = 800, quality: int = 80) -> bytes:
    img = Image.open(io.BytesIO(image_bytes))
    if img.mode in ("RGBA", "P"):
        img = img.convert("RGB")
    if img.width > max_width:
        ratio = max_width / float(img.width)
        new_height = int(float(img.height) * ratio)
        img = img.resize((max_width, new_height), Image.Resampling.LANCZOS)
    out = io.BytesIO()
    img.save(out, format="WEBP", quality=quality, method=6)
    return out.getvalue()


def generate_qr_card_png(url: str, restaurant_name: str, table_label: str) -> bytes:
    qr = qrcode.QRCode(
        version=1,
        error_correction=qrcode.constants.ERROR_CORRECT_H,
        box_size=14,
        border=2,
    )
    qr.add_data(url)
    qr.make(fit=True)
    qr_img = qr.make_image(fill_color="#111827", back_color="white").convert("RGB")

    qr_w, qr_h = qr_img.size
    card_w = qr_w + 120
    card_h = qr_h + 220

    card = Image.new("RGB", (card_w, card_h), "#ffffff")
    draw = ImageDraw.Draw(card)

    # Outer accent border
    draw.rectangle([12, 12, card_w - 13, card_h - 13], outline="#ea580c", width=6)

    font_lg = ImageFont.load_default(size=32)
    font_md = ImageFont.load_default(size=24)
    font_sm = ImageFont.load_default(size=18)

    # Header: Restaurant Name
    draw.text((card_w // 2, 52), restaurant_name[:28], fill="#111827", font=font_lg, anchor="mm")
    draw.text((card_w // 2, 88), "SCAN FOR DIGITAL MENU", fill="#ea580c", font=font_sm, anchor="mm")

    # Paste QR
    card.paste(qr_img, (60, 115))

    # Footer: Table Label
    draw.text((card_w // 2, qr_h + 150), table_label, fill="#111827", font=font_lg, anchor="mm")
    draw.text((card_w // 2, qr_h + 188), "No App Required • Instant Order", fill="#6b7280", font=font_md, anchor="mm")

    buf = io.BytesIO()
    card.save(buf, format="PNG")
    return buf.getvalue()


def format_kot_message(
    order_code: str,
    order_type: str,
    table_number: str | None,
    customer_name: str,
    customer_phone: str,
    customer_address: str,
    items: list[dict],
    special_instructions: str,
    subtotal: int,
    delivery_fee: int,
    tax_amount: int,
    net_total: int,
    cod_verification_required: bool = False,
) -> str:
    header = "*NEW TABLE ORDER*" if order_type == "DINE_IN" else "*NEW DELIVERY ORDER*"
    lines = [f"{header} — #{order_code}"]

    if order_type == "DINE_IN":
        lines.append(f"*Table:* {table_number}")
    else:
        lines.append(f"*Customer:* {customer_name}")
        lines.append(f"*Phone:* {customer_phone}")
        lines.append(f"*Address:* {customer_address}")

    lines.append("────────────────────")
    for item in items:
        qty = item["qty"]
        name = item["name"]
        variant = f" [{item['variant']}]" if item.get("variant") else ""
        addons = f" (+{', '.join(item['addons'])})" if item.get("addons") else ""
        note = f" ({item['note']})" if item.get("note") else ""
        line_total = item["line_total"]
        lines.append(f"• {qty}x {name}{variant}{addons}{note} — PKR {line_total:,}")

    lines.append("────────────────────")
    if special_instructions:
        lines.append(f"*Instructions:* {special_instructions}")

    lines.append(f"*Subtotal:* PKR {subtotal:,}")
    if order_type == "DELIVERY":
        lines.append(f"*Delivery Fee:* PKR {delivery_fee:,}")
    if tax_amount > 0:
        lines.append(f"*Tax:* PKR {tax_amount:,}")
    lines.append(f"*Net Total:* *PKR {net_total:,}*")

    if cod_verification_required:
        lines.append("⚠️ _Order exceeds COD limit — Advance payment/confirmation required._")

    return "\n".join(lines)


def build_whatsapp_url(whatsapp_number: str, message: str) -> str:
    clean_num = "".join(ch for ch in whatsapp_number if ch.isdigit())
    return f"https://wa.me/{clean_num}?text={quote(message)}"
