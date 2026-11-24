from datetime import datetime, timezone
from sqlalchemy import (
    Column,
    Integer,
    String,
    Float,
    Boolean,
    Text,
    DateTime,
    ForeignKey,
)
from sqlalchemy.orm import relationship
from app.database import Base


def utcnow():
    return datetime.now(timezone.utc)


class Restaurant(Base):
    __tablename__ = "restaurants"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(150), nullable=False)
    slug = Column(String(100), unique=True, index=True, nullable=False)
    whatsapp_number = Column(String(30), nullable=False)  # e.g. 923001234567
    address = Column(String(300), default="")
    latitude = Column(Float, default=31.5204)   # Default Lahore coords
    longitude = Column(Float, default=74.3587)
    geo_radius_meters = Column(Integer, default=100)
    delivery_radius_km = Column(Float, default=10.0)
    active_table_pin = Column(String(10), default="1234")
    require_table_pin = Column(Boolean, default=True)
    cod_cap_pkr = Column(Integer, default=3500)
    delivery_fee_pkr = Column(Integer, default=150)
    tax_percent = Column(Float, default=0.0)
    primary_color = Column(String(20), default="#ea580c")
    logo_url = Column(String(300), default="")

    # Local Wi-Fi Bridge settings
    wifi_ssid = Column(String(100), default="Restaurant_Guest")
    wifi_only_menu_mode = Column(Boolean, default=False)
    wifi_speed_limit_mbps = Column(Integer, default=2)
    wifi_router_model = Column(String(100), default="TP-Link / Generic")
    wifi_bridge_status = Column(String(30), default="offline")
    wifi_bridge_note = Column(String(300), default="")

    categories = relationship("Category", back_populates="restaurant", cascade="all, delete-orphan")
    items = relationship("MenuItem", back_populates="restaurant", cascade="all, delete-orphan")
    tables = relationship("DiningTable", back_populates="restaurant", cascade="all, delete-orphan")
    orders = relationship("Order", back_populates="restaurant", cascade="all, delete-orphan")


class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    restaurant_id = Column(Integer, ForeignKey("restaurants.id"), nullable=False)
    username = Column(String(80), unique=True, index=True, nullable=False)
    password_hash = Column(String(255), nullable=False)
    role = Column(String(20), default="owner")  # owner | manager
    created_at = Column(DateTime, default=utcnow)


class Category(Base):
    __tablename__ = "categories"

    id = Column(Integer, primary_key=True, index=True)
    restaurant_id = Column(Integer, ForeignKey("restaurants.id"), nullable=False)
    name = Column(String(100), nullable=False)
    name_ur = Column(String(100), default="")
    sort_order = Column(Integer, default=0)
    is_active = Column(Boolean, default=True)

    restaurant = relationship("Restaurant", back_populates="categories")
    items = relationship("MenuItem", back_populates="category", cascade="all, delete-orphan")


class MenuItem(Base):
    __tablename__ = "menu_items"

    id = Column(Integer, primary_key=True, index=True)
    restaurant_id = Column(Integer, ForeignKey("restaurants.id"), nullable=False)
    category_id = Column(Integer, ForeignKey("categories.id"), nullable=False)
    name = Column(String(150), nullable=False)
    name_ur = Column(String(150), default="")
    description = Column(Text, default="")
    base_price = Column(Integer, nullable=False)  # PKR
    image_url = Column(String(300), default="")
    is_available = Column(Boolean, default=True)
    is_popular = Column(Boolean, default=False)
    is_spicy = Column(Boolean, default=False)
    is_veg = Column(Boolean, default=False)
    variants_json = Column(Text, default="[]")  # [{"name": "Half", "price": 1200}, ...]
    addons_json = Column(Text, default="[]")    # [{"name": "Extra Cheese", "price": 150}, ...]
    view_count = Column(Integer, default=0)
    sort_order = Column(Integer, default=0)

    restaurant = relationship("Restaurant", back_populates="items")
    category = relationship("Category", back_populates="items")


class DiningTable(Base):
    __tablename__ = "dining_tables"

    id = Column(Integer, primary_key=True, index=True)
    restaurant_id = Column(Integer, ForeignKey("restaurants.id"), nullable=False)
    table_number = Column(String(20), nullable=False)  # e.g. "01", "04"
    label = Column(String(50), nullable=False)         # e.g. "Table 04 (Window)"
    secret_token = Column(String(16), nullable=False)  # e.g. "x89k"
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=utcnow)

    restaurant = relationship("Restaurant", back_populates="tables")


class Order(Base):
    __tablename__ = "orders"

    id = Column(Integer, primary_key=True, index=True)
    order_code = Column(String(30), unique=True, index=True, nullable=False)
    restaurant_id = Column(Integer, ForeignKey("restaurants.id"), nullable=False)
    table_id = Column(Integer, ForeignKey("dining_tables.id"), nullable=True)
    table_number = Column(String(20), nullable=True)
    order_type = Column(String(20), nullable=False)  # DINE_IN | DELIVERY

    customer_name = Column(String(120), default="")
    customer_phone = Column(String(40), default="")
    customer_address = Column(Text, default="")
    items_json = Column(Text, nullable=False)
    special_instructions = Column(Text, default="")

    subtotal = Column(Integer, nullable=False)
    delivery_fee = Column(Integer, default=0)
    tax_amount = Column(Integer, default=0)
    net_total = Column(Integer, nullable=False)

    cod_verification_required = Column(Boolean, default=False)
    geo_verified = Column(Boolean, default=False)
    status = Column(String(20), default="PENDING")  # PENDING | CONFIRMED | PREPARING | COMPLETED | CANCELLED
    client_ip = Column(String(64), default="")
    created_at = Column(DateTime, default=utcnow)

    restaurant = relationship("Restaurant", back_populates="orders")


class WaiterCall(Base):
    __tablename__ = "waiter_calls"

    id = Column(Integer, primary_key=True, index=True)
    restaurant_id = Column(Integer, ForeignKey("restaurants.id"), nullable=False)
    table_number = Column(String(20), nullable=False)
    call_type = Column(String(30), nullable=False)  # CALL_WAITER | REQUEST_BILL
    status = Column(String(20), default="OPEN")     # OPEN | RESOLVED
    created_at = Column(DateTime, default=utcnow)
