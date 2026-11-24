import io
import math
import secrets
import socket
import string
from urllib.parse import quote
import qrcode
from PIL import Image, ImageDraw, ImageFont


def _is_private_lan_ip(ip: str) -> tuple[int, str]:
    """Return priority tuple (lower is better) for sorting candidate LAN IPs."""
    if ip.startswith("192.168."):
        return (0, ip)
    if ip.startswith("10."):
        return (1, ip)
    parts = ip.split(".")
    if len(parts) == 4 and parts[0] == "172":
        try:
            second = int(parts[1])
            if 16 <= second <= 31:
                return (2, ip)
        except ValueError:
            pass
    return (3, ip)


def get_candidate_lan_ips() -> list[str]:
    candidates: list[str] = []

    def add_ip(ip: str):
        if (
            ip
            and not ip.startswith("127.")
            and not ip.startswith("169.254.")
            and ip != "0.0.0.0"
            and ":" not in ip
            and ip not in candidates
        ):
            candidates.append(ip)

    # 1. UDP routing probes (works without sending packets; include LAN gateways for offline mode)
    for target in ("8.8.8.8", "192.168.1.1", "192.168.0.1", "192.168.100.1", "10.0.0.1"):
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.settimeout(0.3)
            s.connect((target, 80))
            add_ip(s.getsockname()[0])
            s.close()
        except Exception:
            pass

    # 2. Hostname address resolution (picks up active NICs when offline)
    try:
        hostname = socket.gethostname()
        for info in socket.getaddrinfo(hostname, None, socket.AF_INET):
            add_ip(info[4][0])
    except Exception:
        pass

    try:
        for ip in socket.gethostbyname_ex(socket.gethostname())[2]:
            add_ip(ip)
    except Exception:
        pass

    candidates.sort(key=_is_private_lan_ip)
    return candidates


def get_local_lan_ip() -> str:
    candidates = get_candidate_lan_ips()
    return candidates[0] if candidates else "127.0.0.1"


def get_client_ip(request) -> str:
    """Extract real client IP, respecting reverse-proxy headers when present."""
    for header in ("cf-connecting-ip", "x-real-ip", "x-forwarded-for"):
        val = request.headers.get(header)
        if val:
            first_ip = val.split(",")[0].strip()
            if first_ip:
                return first_ip
    return request.client.host if request.client else "unknown"


def resolve_public_base_url(request, explicit_base_url: str | None = None) -> str:
    """Resolve the base URL for QR codes, replacing localhost/127.0.0.1 with the LAN IP."""
    if explicit_base_url and explicit_base_url.strip():
        return explicit_base_url.strip().rstrip("/")

    forwarded_proto = request.headers.get("x-forwarded-proto", "").split(",")[0].strip()
    forwarded_host = request.headers.get("x-forwarded-host", "").split(",")[0].strip()
    if forwarded_host:
        scheme = forwarded_proto or request.url.scheme or "http"
        return f"{scheme}://{forwarded_host}".rstrip("/")

    host = request.url.hostname or "127.0.0.1"
    scheme = request.url.scheme or "http"
    port = request.url.port

    if host in ("127.0.0.1", "localhost", "0.0.0.0"):
        host = get_local_lan_ip()

    if port and not ((scheme == "http" and port == 80) or (scheme == "https" and port == 443)):
        return f"{scheme}://{host}:{port}"
    return f"{scheme}://{host}"


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
