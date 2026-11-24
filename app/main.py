import json
import os
import time
import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

from fastapi import (
    FastAPI,
    Depends,
    HTTPException,
    Request,
    Response,
    UploadFile,
    File,
    WebSocket,
    WebSocketDisconnect,
    status,
)
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.database import engine, Base, get_db, SessionLocal
from app.models import (
    Restaurant,
    User,
    Category,
    MenuItem,
    DiningTable,
    Order,
    WaiterCall,
)
from app.auth import (
    verify_password,
    create_access_token,
    get_current_user,
    require_owner,
)
from app.seed import seed_demo_data
from app.utils import (
    generate_secret_token,
    generate_qr_card_png,
    optimize_image_to_webp,
    haversine_meters,
    format_kot_message,
    build_whatsapp_url,
    get_local_lan_ip,
    get_candidate_lan_ips,
    get_client_ip,
    resolve_public_base_url,
)

BASE_DIR = Path(__file__).resolve().parent.parent
TEMPLATES_DIR = BASE_DIR / "templates"
UPLOADS_DIR = BASE_DIR / "static" / "uploads"
UPLOADS_DIR.mkdir(parents=True, exist_ok=True)


class ConnectionManager:
    def __init__(self):
        self.admin_sockets: list[WebSocket] = []
        self.bridge_sockets: list[WebSocket] = []

    async def connect_admin(self, ws: WebSocket):
        await ws.accept()
        self.admin_sockets.append(ws)

    def disconnect_admin(self, ws: WebSocket):
        if ws in self.admin_sockets:
            self.admin_sockets.remove(ws)

    async def broadcast_admin(self, payload: dict):
        dead = []
        for ws in self.admin_sockets:
            try:
                await ws.send_json(payload)
            except Exception:
                dead.append(ws)
        for ws in dead:
            self.disconnect_admin(ws)

    async def connect_bridge(self, ws: WebSocket):
        await ws.accept()
        self.bridge_sockets.append(ws)

    def disconnect_bridge(self, ws: WebSocket):
        if ws in self.bridge_sockets:
            self.bridge_sockets.remove(ws)

    async def send_to_bridge(self, payload: dict) -> bool:
        sent = False
        dead = []
        for ws in self.bridge_sockets:
            try:
                await ws.send_json(payload)
                sent = True
            except Exception:
                dead.append(ws)
        for ws in dead:
            self.disconnect_bridge(ws)
        return sent


ws_manager = ConnectionManager()


@asynccontextmanager
async def lifespan(app: FastAPI):
    Base.metadata.create_all(bind=engine)
    db = SessionLocal()
    try:
        from sqlalchemy import text
        try:
            db.execute(text("ALTER TABLE restaurants ADD COLUMN require_table_pin BOOLEAN DEFAULT 1"))
            db.commit()
        except Exception:
            db.rollback()
        seed_demo_data(db)
    finally:
        db.close()
    yield


app = FastAPI(title="Restaurant QR Digital Menu & POS-Lite", lifespan=lifespan)
app.mount("/static", StaticFiles(directory=str(BASE_DIR / "static")), name="static")


# -------------------- Pydantic Schemas --------------------

class LoginRequest(BaseModel):
    username: str
    password: str


class CartItemIn(BaseModel):
    item_id: int
    qty: int
    variant_name: Optional[str] = None
    addon_names: list[str] = []
    note: str = ""


class CheckoutRequest(BaseModel):
    order_type: str  # DINE_IN | DELIVERY
    table_number: Optional[str] = None
    table_token: Optional[str] = None
    table_pin: Optional[str] = None
    customer_name: str = ""
    customer_phone: str = ""
    customer_address: str = ""
    special_instructions: str = ""
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    items: list[CartItemIn]


class WaiterCallRequest(BaseModel):
    table_number: str
    table_token: str
    call_type: str  # CALL_WAITER | REQUEST_BILL


class CategoryIn(BaseModel):
    name: str
    name_ur: str = ""
    sort_order: int = 0


class MenuItemIn(BaseModel):
    category_id: int
    name: str
    name_ur: str = ""
    description: str = ""
    base_price: int
    image_url: str = ""
    is_available: bool = True
    is_popular: bool = False
    is_spicy: bool = False
    is_veg: bool = False
    variants: list[dict] = []
    addons: list[dict] = []


class TableIn(BaseModel):
    table_number: str
    label: str


class OrderStatusIn(BaseModel):
    status: str


class SettingsIn(BaseModel):
    name: str
    whatsapp_number: str
    address: str
    latitude: float
    longitude: float
    geo_radius_meters: int
    delivery_radius_km: float
    active_table_pin: str
    require_table_pin: bool = True
    cod_cap_pkr: int
    delivery_fee_pkr: int
    tax_percent: float


class WifiControlIn(BaseModel):
    wifi_ssid: str
    wifi_only_menu_mode: bool
    wifi_speed_limit_mbps: int
    wifi_router_model: str


# -------------------- HTML Pages --------------------

@app.get("/", response_class=HTMLResponse)
def root_redirect():
    return RedirectResponse(url="/menu")


@app.get("/menu", response_class=HTMLResponse)
def public_delivery_menu():
    html = (TEMPLATES_DIR / "menu.html").read_text(encoding="utf-8")
    return HTMLResponse(content=html)


@app.get("/t/{table_slug}", response_class=HTMLResponse)
def table_menu_page(table_slug: str, db: Session = Depends(get_db)):
    # Expected format: 04-x89k
    parts = table_slug.split("-", 1)
    if len(parts) != 2:
        return HTMLResponse(
            content="<h1>Invalid Table QR</h1><p>Please scan a valid table QR code.</p>",
            status_code=404,
        )
    table_number, token = parts[0], parts[1]
    table = (
        db.query(DiningTable)
        .filter(
            DiningTable.table_number == table_number,
            DiningTable.secret_token == token,
            DiningTable.is_active == True,
        )
        .first()
    )
    if not table:
        return HTMLResponse(
            content="""
            <!DOCTYPE html>
            <html><head><meta name="viewport" content="width=device-width,initial-scale=1">
            <title>Expired QR</title>
            <script src="https://cdn.tailwindcss.com"></script></head>
            <body class="bg-gray-50 flex items-center justify-center min-h-screen p-6">
              <div class="bg-white rounded-2xl shadow-lg p-8 max-w-sm text-center">
                <div class="text-4xl mb-3">⚠️</div>
                <h1 class="text-xl font-bold text-gray-900 mb-2">Invalid or Expired Table QR</h1>
                <p class="text-gray-600 text-sm mb-5">This table QR code has been reset or does not exist. Please ask the restaurant staff or open the delivery menu.</p>
                <a href="/menu" class="inline-block bg-orange-600 text-white px-5 py-2.5 rounded-xl font-semibold text-sm">Open Delivery Menu</a>
              </div>
            </body></html>
            """,
            status_code=404,
        )
    html = (TEMPLATES_DIR / "menu.html").read_text(encoding="utf-8")
    return HTMLResponse(content=html)


@app.get("/admin/login", response_class=HTMLResponse)
def admin_login_page():
    html = (TEMPLATES_DIR / "admin_login.html").read_text(encoding="utf-8")
    return HTMLResponse(content=html)


@app.get("/admin", response_class=HTMLResponse)
def admin_dashboard_page(request: Request, db: Session = Depends(get_db)):
    token = request.cookies.get("admin_token")
    if not token:
        return RedirectResponse(url="/admin/login")
    try:
        get_current_user(request, None, db)
    except HTTPException:
        return RedirectResponse(url="/admin/login")
    html = (TEMPLATES_DIR / "admin.html").read_text(encoding="utf-8")
    return HTMLResponse(content=html)


# -------------------- Public API --------------------

@app.get("/api/menu")
def get_public_menu(
    table_number: Optional[str] = None,
    token: Optional[str] = None,
    db: Session = Depends(get_db),
):
    restaurant = db.query(Restaurant).first()
    if not restaurant:
        raise HTTPException(status_code=404, detail="Restaurant not configured")

    table_info = None
    if table_number and token:
        t = (
            db.query(DiningTable)
            .filter(
                DiningTable.restaurant_id == restaurant.id,
                DiningTable.table_number == table_number,
                DiningTable.secret_token == token,
                DiningTable.is_active == True,
            )
            .first()
        )
        if t:
            table_info = {"table_number": t.table_number, "label": t.label}

    categories = (
        db.query(Category)
        .filter(Category.restaurant_id == restaurant.id, Category.is_active == True)
        .order_by(Category.sort_order.asc(), Category.id.asc())
        .all()
    )
    items = (
        db.query(MenuItem)
        .filter(MenuItem.restaurant_id == restaurant.id)
        .order_by(MenuItem.sort_order.asc(), MenuItem.id.asc())
        .all()
    )

    return {
        "restaurant": {
            "name": restaurant.name,
            "address": restaurant.address,
            "whatsapp_number": restaurant.whatsapp_number,
            "latitude": restaurant.latitude,
            "longitude": restaurant.longitude,
            "geo_radius_meters": restaurant.geo_radius_meters,
            "delivery_radius_km": restaurant.delivery_radius_km,
            "cod_cap_pkr": restaurant.cod_cap_pkr,
            "delivery_fee_pkr": restaurant.delivery_fee_pkr,
            "tax_percent": restaurant.tax_percent,
            "primary_color": restaurant.primary_color,
            "require_table_pin": bool(restaurant.require_table_pin),
        },
        "table": table_info,
        "categories": [
            {"id": c.id, "name": c.name, "name_ur": c.name_ur} for c in categories
        ],
        "items": [
            {
                "id": i.id,
                "category_id": i.category_id,
                "name": i.name,
                "name_ur": i.name_ur,
                "description": i.description,
                "base_price": i.base_price,
                "image_url": i.image_url,
                "is_available": i.is_available,
                "is_popular": i.is_popular,
                "is_spicy": i.is_spicy,
                "is_veg": i.is_veg,
                "variants": json.loads(i.variants_json or "[]"),
                "addons": json.loads(i.addons_json or "[]"),
            }
            for i in items
        ],
    }


@app.post("/api/menu/items/{item_id}/view")
def track_item_view(item_id: int, db: Session = Depends(get_db)):
    item = db.query(MenuItem).filter(MenuItem.id == item_id).first()
    if item:
        item.view_count += 1
        db.commit()
    return {"ok": True}


@app.post("/api/waiter-call")
async def create_waiter_call(payload: WaiterCallRequest, db: Session = Depends(get_db)):
    restaurant = db.query(Restaurant).first()
    table = (
        db.query(DiningTable)
        .filter(
            DiningTable.restaurant_id == restaurant.id,
            DiningTable.table_number == payload.table_number,
            DiningTable.secret_token == payload.table_token,
            DiningTable.is_active == True,
        )
        .first()
    )
    if not table:
        raise HTTPException(status_code=403, detail="Invalid table token")

    if payload.call_type not in ("CALL_WAITER", "REQUEST_BILL"):
        raise HTTPException(status_code=400, detail="Invalid call type")

    call = WaiterCall(
        restaurant_id=restaurant.id,
        table_number=table.table_number,
        call_type=payload.call_type,
    )
    db.add(call)
    db.commit()
    db.refresh(call)

    await ws_manager.broadcast_admin(
        {
            "event": "waiter_call",
            "data": {
                "id": call.id,
                "table_number": call.table_number,
                "call_type": call.call_type,
                "created_at": call.created_at.isoformat(),
            },
        }
    )
    return {"ok": True, "message": "Staff has been notified!"}


@app.post("/api/orders/checkout")
async def checkout_order(
    payload: CheckoutRequest,
    request: Request,
    db: Session = Depends(get_db),
):
    restaurant = db.query(Restaurant).first()
    if not restaurant:
        raise HTTPException(status_code=404, detail="Restaurant not found")

    if not payload.items:
        raise HTTPException(status_code=400, detail="Cart is empty")

    client_ip = get_client_ip(request)

    # Layer 4: Backend Rate-Limiting (10-minute cooldown per IP; scoped by table for DINE_IN)
    cooldown_cutoff = datetime.now(timezone.utc) - timedelta(minutes=10)
    cooldown_query = db.query(Order).filter(
        Order.restaurant_id == restaurant.id,
        Order.client_ip == client_ip,
        Order.created_at >= cooldown_cutoff,
    )
    if payload.order_type == "DINE_IN" and payload.table_number:
        cooldown_query = cooldown_query.filter(Order.table_number == payload.table_number)
    recent_order = cooldown_query.order_by(Order.created_at.desc()).first()
    if recent_order:
        # Handle naive vs aware datetime from SQLite
        created = recent_order.created_at
        if created.tzinfo is None:
            created = created.replace(tzinfo=timezone.utc)
        elapsed_sec = (datetime.now(timezone.utc) - created).total_seconds()
        if elapsed_sec < 600:
            mins_left = max(1, int((600 - elapsed_sec) // 60) + 1)
            raise HTTPException(
                status_code=429,
                detail=f"Cooldown active: Please wait {mins_left} minute(s) before placing another order.",
            )

    table_id = None
    if payload.order_type == "DINE_IN":
        table = (
            db.query(DiningTable)
            .filter(
                DiningTable.restaurant_id == restaurant.id,
                DiningTable.table_number == payload.table_number,
                DiningTable.secret_token == payload.table_token,
                DiningTable.is_active == True,
            )
            .first()
        )
        if not table:
            raise HTTPException(status_code=403, detail="Invalid or expired table QR token")
        table_id = table.id

        # Layer 2: Dynamic Table PIN check (when enabled in Admin Settings)
        if restaurant.require_table_pin and (payload.table_pin or "").strip() != restaurant.active_table_pin.strip():
            raise HTTPException(
                status_code=403,
                detail="Incorrect Table PIN. Please check the 4-digit PIN on your table stand.",
            )
    elif payload.order_type == "DELIVERY":
        if not payload.customer_name.strip() or not payload.customer_phone.strip() or not payload.customer_address.strip():
            raise HTTPException(
                status_code=400,
                detail="Name, phone number, and delivery address are required for delivery.",
            )
    else:
        raise HTTPException(status_code=400, detail="Invalid order type")

    # Layer 3: Browser Geo-Fencing verification (soft check for indoor GPS)
    geo_verified = False
    if payload.latitude is not None and payload.longitude is not None:
        dist_m = haversine_meters(
            restaurant.latitude,
            restaurant.longitude,
            payload.latitude,
            payload.longitude,
        )
        if payload.order_type == "DINE_IN":
            geo_verified = dist_m <= restaurant.geo_radius_meters
        else:
            if dist_m > restaurant.delivery_radius_km * 1000:
                raise HTTPException(
                    status_code=400,
                    detail=f"Sorry, your location is outside our {restaurant.delivery_radius_km} km delivery zone.",
                )
            geo_verified = True

    # Server-side price verification (prevents tampering)
    verified_items = []
    subtotal = 0
    for cart_item in payload.items:
        if cart_item.qty <= 0:
            continue
        db_item = (
            db.query(MenuItem)
            .filter(MenuItem.id == cart_item.item_id, MenuItem.restaurant_id == restaurant.id)
            .first()
        )
        if not db_item:
            raise HTTPException(status_code=400, detail=f"Item ID {cart_item.item_id} not found")
        if not db_item.is_available:
            raise HTTPException(status_code=400, detail=f"{db_item.name} is currently Out of Stock")

        unit_price = db_item.base_price
        variants = json.loads(db_item.variants_json or "[]")
        if cart_item.variant_name and variants:
            matched_v = next((v for v in variants if v["name"] == cart_item.variant_name), None)
            if matched_v:
                unit_price = int(matched_v["price"])

        addons = json.loads(db_item.addons_json or "[]")
        addons_total = 0
        valid_addons = []
        for a_name in cart_item.addon_names:
            matched_a = next((a for a in addons if a["name"] == a_name), None)
            if matched_a:
                addons_total += int(matched_a["price"])
                valid_addons.append(a_name)

        line_total = (unit_price + addons_total) * cart_item.qty
        subtotal += line_total
        verified_items.append(
            {
                "item_id": db_item.id,
                "name": db_item.name,
                "qty": cart_item.qty,
                "variant": cart_item.variant_name,
                "addons": valid_addons,
                "note": cart_item.note.strip(),
                "unit_price": unit_price + addons_total,
                "line_total": line_total,
            }
        )

    if not verified_items:
        raise HTTPException(status_code=400, detail="No valid items in cart")

    delivery_fee = restaurant.delivery_fee_pkr if payload.order_type == "DELIVERY" else 0
    tax_amount = int(round(subtotal * (restaurant.tax_percent / 100.0)))
    net_total = subtotal + delivery_fee + tax_amount
    cod_verification_required = (
        payload.order_type == "DELIVERY" and net_total > restaurant.cod_cap_pkr
    )

    order_code = f"ORD-{int(time.time()) % 100000}-{uuid.uuid4().hex[:3].upper()}"

    order = Order(
        order_code=order_code,
        restaurant_id=restaurant.id,
        table_id=table_id,
        table_number=payload.table_number if payload.order_type == "DINE_IN" else None,
        order_type=payload.order_type,
        customer_name=payload.customer_name.strip(),
        customer_phone=payload.customer_phone.strip(),
        customer_address=payload.customer_address.strip(),
        items_json=json.dumps(verified_items),
        special_instructions=payload.special_instructions.strip(),
        subtotal=subtotal,
        delivery_fee=delivery_fee,
        tax_amount=tax_amount,
        net_total=net_total,
        cod_verification_required=cod_verification_required,
        geo_verified=geo_verified,
        status="PENDING",
        client_ip=client_ip,
    )
    db.add(order)
    db.commit()
    db.refresh(order)

    kot_message = format_kot_message(
        order_code=order.order_code,
        order_type=order.order_type,
        table_number=order.table_number,
        customer_name=order.customer_name,
        customer_phone=order.customer_phone,
        customer_address=order.customer_address,
        items=verified_items,
        special_instructions=order.special_instructions,
        subtotal=subtotal,
        delivery_fee=delivery_fee,
        tax_amount=tax_amount,
        net_total=net_total,
        cod_verification_required=cod_verification_required,
    )
    whatsapp_url = build_whatsapp_url(restaurant.whatsapp_number, kot_message)

    await ws_manager.broadcast_admin(
        {
            "event": "new_order",
            "data": {
                "id": order.id,
                "order_code": order.order_code,
                "order_type": order.order_type,
                "table_number": order.table_number,
                "net_total": order.net_total,
                "status": order.status,
                "created_at": order.created_at.isoformat(),
            },
        }
    )

    return {
        "order_code": order.order_code,
        "subtotal": subtotal,
        "delivery_fee": delivery_fee,
        "tax_amount": tax_amount,
        "net_total": net_total,
        "cod_verification_required": cod_verification_required,
        "geo_verified": geo_verified,
        "kot_message": kot_message,
        "whatsapp_url": whatsapp_url,
    }


# -------------------- Auth API --------------------

@app.post("/api/auth/login")
def admin_login(payload: LoginRequest, response: Response, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.username == payload.username).first()
    if not user or not verify_password(payload.password, user.password_hash):
        raise HTTPException(status_code=401, detail="Invalid username or password")

    token = create_access_token({"sub": user.username, "role": user.role})
    response = JSONResponse(
        content={"ok": True, "username": user.username, "role": user.role, "token": token}
    )
    response.set_cookie(
        key="admin_token",
        value=token,
        httponly=True,
        samesite="lax",
        max_age=86400,
    )
    return response


@app.post("/api/auth/logout")
def admin_logout():
    response = JSONResponse(content={"ok": True})
    response.delete_cookie("admin_token")
    return response


@app.get("/api/auth/me")
def admin_me(current_user: User = Depends(get_current_user)):
    return {"username": current_user.username, "role": current_user.role}


# -------------------- Admin Orders & Waiter Calls --------------------

@app.get("/api/admin/orders")
def list_orders(current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    orders = (
        db.query(Order)
        .filter(Order.restaurant_id == current_user.restaurant_id)
        .order_by(Order.created_at.desc())
        .limit(100)
        .all()
    )
    return [
        {
            "id": o.id,
            "order_code": o.order_code,
            "order_type": o.order_type,
            "table_number": o.table_number,
            "customer_name": o.customer_name,
            "customer_phone": o.customer_phone,
            "customer_address": o.customer_address,
            "items": json.loads(o.items_json or "[]"),
            "special_instructions": o.special_instructions,
            "subtotal": o.subtotal,
            "delivery_fee": o.delivery_fee,
            "tax_amount": o.tax_amount,
            "net_total": o.net_total,
            "cod_verification_required": o.cod_verification_required,
            "geo_verified": o.geo_verified,
            "status": o.status,
            "created_at": o.created_at.isoformat(),
        }
        for o in orders
    ]


@app.patch("/api/admin/orders/{order_id}/status")
def update_order_status(
    order_id: int,
    payload: OrderStatusIn,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    allowed = {"PENDING", "CONFIRMED", "PREPARING", "COMPLETED", "CANCELLED"}
    if payload.status not in allowed:
        raise HTTPException(status_code=400, detail="Invalid order status")
    order = (
        db.query(Order)
        .filter(Order.id == order_id, Order.restaurant_id == current_user.restaurant_id)
        .first()
    )
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")
    order.status = payload.status
    db.commit()
    return {"ok": True, "status": order.status}


@app.get("/api/admin/waiter-calls")
def list_waiter_calls(current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    calls = (
        db.query(WaiterCall)
        .filter(WaiterCall.restaurant_id == current_user.restaurant_id, WaiterCall.status == "OPEN")
        .order_by(WaiterCall.created_at.desc())
        .all()
    )
    return [
        {
            "id": c.id,
            "table_number": c.table_number,
            "call_type": c.call_type,
            "created_at": c.created_at.isoformat(),
        }
        for c in calls
    ]


@app.patch("/api/admin/waiter-calls/{call_id}/resolve")
def resolve_waiter_call(
    call_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    call = (
        db.query(WaiterCall)
        .filter(WaiterCall.id == call_id, WaiterCall.restaurant_id == current_user.restaurant_id)
        .first()
    )
    if not call:
        raise HTTPException(status_code=404, detail="Waiter call not found")
    call.status = "RESOLVED"
    db.commit()
    return {"ok": True}


# -------------------- Admin Menu & 1-Click Stock --------------------

@app.post("/api/admin/categories")
def create_category(
    payload: CategoryIn,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    cat = Category(
        restaurant_id=current_user.restaurant_id,
        name=payload.name,
        name_ur=payload.name_ur,
        sort_order=payload.sort_order,
    )
    db.add(cat)
    db.commit()
    db.refresh(cat)
    return {"id": cat.id, "name": cat.name, "name_ur": cat.name_ur}


@app.post("/api/admin/items")
def create_menu_item(
    payload: MenuItemIn,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    item = MenuItem(
        restaurant_id=current_user.restaurant_id,
        category_id=payload.category_id,
        name=payload.name,
        name_ur=payload.name_ur,
        description=payload.description,
        base_price=payload.base_price,
        image_url=payload.image_url,
        is_available=payload.is_available,
        is_popular=payload.is_popular,
        is_spicy=payload.is_spicy,
        is_veg=payload.is_veg,
        variants_json=json.dumps(payload.variants),
        addons_json=json.dumps(payload.addons),
    )
    db.add(item)
    db.commit()
    db.refresh(item)
    return {"id": item.id, "name": item.name}


@app.put("/api/admin/items/{item_id}")
def update_menu_item(
    item_id: int,
    payload: MenuItemIn,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    item = (
        db.query(MenuItem)
        .filter(MenuItem.id == item_id, MenuItem.restaurant_id == current_user.restaurant_id)
        .first()
    )
    if not item:
        raise HTTPException(status_code=404, detail="Item not found")
    item.category_id = payload.category_id
    item.name = payload.name
    item.name_ur = payload.name_ur
    item.description = payload.description
    item.base_price = payload.base_price
    item.image_url = payload.image_url
    item.is_available = payload.is_available
    item.is_popular = payload.is_popular
    item.is_spicy = payload.is_spicy
    item.is_veg = payload.is_veg
    item.variants_json = json.dumps(payload.variants)
    item.addons_json = json.dumps(payload.addons)
    db.commit()
    return {"ok": True}


@app.patch("/api/admin/items/{item_id}/toggle-stock")
def toggle_item_stock(
    item_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    item = (
        db.query(MenuItem)
        .filter(MenuItem.id == item_id, MenuItem.restaurant_id == current_user.restaurant_id)
        .first()
    )
    if not item:
        raise HTTPException(status_code=404, detail="Item not found")
    item.is_available = not item.is_available
    db.commit()
    return {"ok": True, "is_available": item.is_available}


@app.delete("/api/admin/items/{item_id}")
def delete_menu_item(
    item_id: int,
    current_user: User = Depends(require_owner),
    db: Session = Depends(get_db),
):
    item = (
        db.query(MenuItem)
        .filter(MenuItem.id == item_id, MenuItem.restaurant_id == current_user.restaurant_id)
        .first()
    )
    if not item:
        raise HTTPException(status_code=404, detail="Item not found")
    db.delete(item)
    db.commit()
    return {"ok": True}


@app.post("/api/admin/upload-image")
async def upload_item_image(
    file: UploadFile = File(...),
    current_user: User = Depends(get_current_user),
):
    raw = await file.read()
    try:
        webp_bytes = optimize_image_to_webp(raw)
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid image file")

    filename = f"{uuid.uuid4().hex[:12]}.webp"
    dest = UPLOADS_DIR / filename
    dest.write_bytes(webp_bytes)
    return {"image_url": f"/static/uploads/{filename}"}


# -------------------- Admin Tables & QR Code Manager --------------------

@app.get("/api/admin/tables")
def list_tables(current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    tables = (
        db.query(DiningTable)
        .filter(DiningTable.restaurant_id == current_user.restaurant_id)
        .order_by(DiningTable.table_number.asc())
        .all()
    )
    return [
        {
            "id": t.id,
            "table_number": t.table_number,
            "label": t.label,
            "secret_token": t.secret_token,
            "slug": f"{t.table_number}-{t.secret_token}",
            "is_active": t.is_active,
        }
        for t in tables
    ]


@app.post("/api/admin/tables")
def create_table(
    payload: TableIn,
    current_user: User = Depends(require_owner),
    db: Session = Depends(get_db),
):
    t = DiningTable(
        restaurant_id=current_user.restaurant_id,
        table_number=payload.table_number.strip(),
        label=payload.label.strip(),
        secret_token=generate_secret_token(4),
    )
    db.add(t)
    db.commit()
    db.refresh(t)
    return {"id": t.id, "slug": f"{t.table_number}-{t.secret_token}"}


@app.post("/api/admin/tables/{table_id}/reset-token")
def reset_table_token(
    table_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    table = (
        db.query(DiningTable)
        .filter(DiningTable.id == table_id, DiningTable.restaurant_id == current_user.restaurant_id)
        .first()
    )
    if not table:
        raise HTTPException(status_code=404, detail="Table not found")
    table.secret_token = generate_secret_token(4)
    db.commit()
    return {"ok": True, "secret_token": table.secret_token, "slug": f"{table.table_number}-{table.secret_token}"}


@app.get("/api/admin/network-info")
def get_network_info(request: Request, current_user: User = Depends(get_current_user)):
    lan_ip = get_local_lan_ip()
    candidates = get_candidate_lan_ips()
    scheme = request.headers.get("x-forwarded-proto", "").split(",")[0].strip() or request.url.scheme or "http"
    port = request.url.port
    port_suffix = f":{port}" if port and not ((scheme == "http" and port == 80) or (scheme == "https" and port == 443)) else ""
    host = request.url.hostname or "127.0.0.1"
    is_local_host = host in ("127.0.0.1", "localhost", "0.0.0.0")
    return {
        "lan_ip": lan_ip,
        "candidate_ips": candidates,
        "candidate_urls": [f"{scheme}://{ip}{port_suffix}" for ip in candidates],
        "lan_base_url": resolve_public_base_url(request),
        "is_local_host": is_local_host,
    }


@app.get("/api/admin/tables/{table_id}/qr.png")
def download_table_qr(
    table_id: int,
    request: Request,
    base_url: Optional[str] = None,
    inline: int = 0,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    table = (
        db.query(DiningTable)
        .filter(DiningTable.id == table_id, DiningTable.restaurant_id == current_user.restaurant_id)
        .first()
    )
    if not table:
        raise HTTPException(status_code=404, detail="Table not found")

    restaurant = db.query(Restaurant).filter(Restaurant.id == current_user.restaurant_id).first()
    resolved_base = resolve_public_base_url(request, base_url)

    qr_url = f"{resolved_base}/t/{table.table_number}-{table.secret_token}"
    png_bytes = generate_qr_card_png(qr_url, restaurant.name, table.label)

    headers = {}
    if not inline:
        headers["Content-Disposition"] = f'attachment; filename="table-{table.table_number}-qr.png"'

    return Response(
        content=png_bytes,
        media_type="image/png",
        headers=headers,
    )


# -------------------- Admin Settings, Wi-Fi Bridge & Analytics --------------------

@app.get("/api/admin/settings")
def get_settings(current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    r = db.query(Restaurant).filter(Restaurant.id == current_user.restaurant_id).first()
    return {
        "name": r.name,
        "whatsapp_number": r.whatsapp_number,
        "address": r.address,
        "latitude": r.latitude,
        "longitude": r.longitude,
        "geo_radius_meters": r.geo_radius_meters,
        "delivery_radius_km": r.delivery_radius_km,
        "active_table_pin": r.active_table_pin,
        "require_table_pin": bool(r.require_table_pin),
        "cod_cap_pkr": r.cod_cap_pkr,
        "delivery_fee_pkr": r.delivery_fee_pkr,
        "tax_percent": r.tax_percent,
        "wifi_ssid": r.wifi_ssid,
        "wifi_only_menu_mode": r.wifi_only_menu_mode,
        "wifi_speed_limit_mbps": r.wifi_speed_limit_mbps,
        "wifi_router_model": r.wifi_router_model,
        "wifi_bridge_status": r.wifi_bridge_status,
        "wifi_bridge_note": r.wifi_bridge_note,
    }


@app.put("/api/admin/settings")
def update_settings(
    payload: SettingsIn,
    current_user: User = Depends(require_owner),
    db: Session = Depends(get_db),
):
    r = db.query(Restaurant).filter(Restaurant.id == current_user.restaurant_id).first()
    r.name = payload.name
    r.whatsapp_number = payload.whatsapp_number
    r.address = payload.address
    r.latitude = payload.latitude
    r.longitude = payload.longitude
    r.geo_radius_meters = payload.geo_radius_meters
    r.delivery_radius_km = payload.delivery_radius_km
    r.active_table_pin = payload.active_table_pin
    r.require_table_pin = payload.require_table_pin
    r.cod_cap_pkr = payload.cod_cap_pkr
    r.delivery_fee_pkr = payload.delivery_fee_pkr
    r.tax_percent = payload.tax_percent
    db.commit()
    return {"ok": True}


@app.post("/api/admin/wifi-control")
async def update_wifi_control(
    payload: WifiControlIn,
    current_user: User = Depends(require_owner),
    db: Session = Depends(get_db),
):
    r = db.query(Restaurant).filter(Restaurant.id == current_user.restaurant_id).first()
    r.wifi_ssid = payload.wifi_ssid
    r.wifi_only_menu_mode = payload.wifi_only_menu_mode
    r.wifi_speed_limit_mbps = payload.wifi_speed_limit_mbps
    r.wifi_router_model = payload.wifi_router_model

    # Check ISP router limitation note
    if "PTCL" in payload.wifi_router_model or "StormFiber" in payload.wifi_router_model:
        r.wifi_bridge_note = (
            "ISP Router Notice: PTCL/StormFiber routers often lock Guest Wi-Fi or URL filtering. "
            "Only Speed Limit may apply unless a secondary Access Point is connected."
        )
    else:
        r.wifi_bridge_note = ""

    db.commit()

    pushed = await ws_manager.send_to_bridge(
        {
            "command": "apply_wifi_policy",
            "ssid": r.wifi_ssid,
            "only_menu_mode": r.wifi_only_menu_mode,
            "speed_limit_mbps": r.wifi_speed_limit_mbps,
            "router_model": r.wifi_router_model,
        }
    )
    return {"ok": True, "bridge_connected": pushed, "note": r.wifi_bridge_note}


@app.get("/api/admin/analytics")
def get_analytics(current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    orders = (
        db.query(Order)
        .filter(Order.restaurant_id == current_user.restaurant_id)
        .all()
    )
    confirmed = [o for o in orders if o.status in ("CONFIRMED", "PREPARING", "COMPLETED")]
    total_revenue = sum(o.net_total for o in confirmed)
    dine_in_count = sum(1 for o in confirmed if o.order_type == "DINE_IN")
    delivery_count = sum(1 for o in confirmed if o.order_type == "DELIVERY")

    dish_counts: dict[str, int] = {}
    for o in confirmed:
        for it in json.loads(o.items_json or "[]"):
            dish_counts[it["name"]] = dish_counts.get(it["name"], 0) + it["qty"]

    top_dishes = sorted(
        [{"name": k, "qty": v} for k, v in dish_counts.items()],
        key=lambda x: x["qty"],
        reverse=True,
    )[:5]

    most_viewed = (
        db.query(MenuItem)
        .filter(MenuItem.restaurant_id == current_user.restaurant_id)
        .order_by(MenuItem.view_count.desc())
        .limit(5)
        .all()
    )

    return {
        "total_orders": len(orders),
        "confirmed_orders": len(confirmed),
        "pending_orders": sum(1 for o in orders if o.status == "PENDING"),
        "total_revenue_pkr": total_revenue,
        "dine_in_orders": dine_in_count,
        "delivery_orders": delivery_count,
        "top_dishes": top_dishes,
        "most_viewed": [{"name": i.name, "views": i.view_count} for i in most_viewed],
    }


# -------------------- WebSockets --------------------

@app.websocket("/ws/admin")
async def admin_websocket(ws: WebSocket):
    await ws_manager.connect_admin(ws)
    try:
        while True:
            await ws.receive_text()
    except WebSocketDisconnect:
        ws_manager.disconnect_admin(ws)


@app.websocket("/ws/bridge")
async def bridge_websocket(ws: WebSocket):
    await ws_manager.connect_bridge(ws)
    db = SessionLocal()
    try:
        r = db.query(Restaurant).first()
        if r:
            r.wifi_bridge_status = "online"
            db.commit()
        await ws_manager.broadcast_admin({"event": "bridge_status", "status": "online"})
        while True:
            msg = await ws.receive_text()
            data = json.loads(msg)
            if data.get("type") == "status_update" and r:
                r.wifi_bridge_note = data.get("note", "")
                db.commit()
                await ws_manager.broadcast_admin(
                    {"event": "bridge_status", "status": "online", "note": r.wifi_bridge_note}
                )
    except WebSocketDisconnect:
        ws_manager.disconnect_bridge(ws)
        r = db.query(Restaurant).first()
        if r:
            r.wifi_bridge_status = "offline"
            db.commit()
        await ws_manager.broadcast_admin({"event": "bridge_status", "status": "offline"})
    finally:
        db.close()
