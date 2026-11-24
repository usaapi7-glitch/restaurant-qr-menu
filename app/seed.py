import json
from sqlalchemy.orm import Session
from app.models import Restaurant, User, Category, MenuItem, DiningTable
from app.auth import hash_password
from app.utils import generate_secret_token


def seed_demo_data(db: Session):
    if db.query(Restaurant).first():
        return

    restaurant = Restaurant(
        name="Lahori Spice & Grill",
        slug="lahori-spice",
        whatsapp_number="923001234567",
        address="MM Alam Road, Gulberg III, Lahore",
        latitude=31.5102,
        longitude=74.3441,
        geo_radius_meters=120,
        delivery_radius_km=12.0,
        active_table_pin="4580",
        cod_cap_pkr=3500,
        delivery_fee_pkr=150,
        tax_percent=0.0,
        primary_color="#ea580c",
        wifi_ssid="LahoriSpice_Guest",
        wifi_only_menu_mode=False,
        wifi_speed_limit_mbps=2,
        wifi_router_model="TP-Link Archer C6",
        wifi_bridge_status="offline",
    )
    db.add(restaurant)
    db.flush()

    owner = User(
        restaurant_id=restaurant.id,
        username="owner",
        password_hash=hash_password("owner123"),
        role="owner",
    )
    manager = User(
        restaurant_id=restaurant.id,
        username="manager",
        password_hash=hash_password("manager123"),
        role="manager",
    )
    db.add_all([owner, manager])

    categories_data = [
        ("Burgers & Fast Food", "برگر اور فاسٹ فوڈ", 1),
        ("BBQ & Karahi", "باربی کیو اور کڑاہی", 2),
        ("Biryani & Rice", "بریانی اور چاول", 3),
        ("Beverages", "مشروبات", 4),
        ("Desserts", "میٹھا", 5),
    ]
    cat_map = {}
    for name, name_ur, order in categories_data:
        cat = Category(restaurant_id=restaurant.id, name=name, name_ur=name_ur, sort_order=order)
        db.add(cat)
        db.flush()
        cat_map[name] = cat.id

    items_data = [
        {
            "category_id": cat_map["Burgers & Fast Food"],
            "name": "Crispy Zinger Burger",
            "name_ur": "کرسپی زنگر برگر",
            "description": "Crunchy fried chicken thigh fillet with cheddar cheese, iceberg lettuce & signature garlic mayo.",
            "base_price": 650,
            "image_url": "https://images.unsplash.com/photo-1568901346375-23c9450c58cd?auto=format&fit=crop&w=600&q=80",
            "is_popular": True,
            "is_spicy": True,
            "variants": [{"name": "Single Patty", "price": 650}, {"name": "Double Decker", "price": 950}],
            "addons": [{"name": "Extra Cheese", "price": 120}, {"name": "Fries & Drink Combo", "price": 300}],
        },
        {
            "category_id": cat_map["Burgers & Fast Food"],
            "name": "Smoky Beef Smash Burger",
            "name_ur": "سموکی بیف سمیش برگر",
            "description": "Juicy double smashed beef patty with caramelized onions and smoky BBQ sauce.",
            "base_price": 850,
            "image_url": "https://images.unsplash.com/photo-1550547660-d9450f859349?auto=format&fit=crop&w=600&q=80",
            "is_popular": True,
            "variants": [{"name": "Regular", "price": 850}, {"name": "Monster Double", "price": 1250}],
            "addons": [{"name": "Jalapenos", "price": 80}, {"name": "Extra Cheese", "price": 120}],
        },
        {
            "category_id": cat_map["BBQ & Karahi"],
            "name": "Special Chicken Karahi",
            "name_ur": "سپیشل چکن کڑاہی",
            "description": "Fresh chicken cooked in traditional iron wok with tomatoes, ginger, green chilies & desi ghee.",
            "base_price": 1350,
            "image_url": "https://images.unsplash.com/photo-1603894584373-5ac82b2ae398?auto=format&fit=crop&w=600&q=80",
            "is_popular": True,
            "is_spicy": True,
            "variants": [{"name": "Half (500g)", "price": 1350}, {"name": "Full (1kg)", "price": 2500}],
            "addons": [{"name": "Roghni Naan (2 pcs)", "price": 180}, {"name": "Mint Raita", "price": 100}],
        },
        {
            "category_id": cat_map["BBQ & Karahi"],
            "name": "Chicken Malai Boti",
            "name_ur": "چکن ملائی بوٹی",
            "description": "Melt-in-mouth boneless chicken cubes marinated in fresh cream, yogurt, and mild spices.",
            "base_price": 950,
            "image_url": "https://images.unsplash.com/photo-1599487488170-d11ec9c172f0?auto=format&fit=crop&w=600&q=80",
            "is_popular": False,
            "variants": [{"name": "6 Pieces", "price": 950}, {"name": "12 Pieces", "price": 1800}],
            "addons": [{"name": "Garlic Naan", "price": 100}, {"name": "Imli Chutney", "price": 60}],
        },
        {
            "category_id": cat_map["BBQ & Karahi"],
            "name": "Mutton Seekh Kabab",
            "name_ur": "مٹن سیخ کباب",
            "description": "Charcoal-grilled spiced mutton skewers served with onion rings and tamarind sauce.",
            "base_price": 1100,
            "image_url": "https://images.unsplash.com/photo-1544025162-d76694265947?auto=format&fit=crop&w=600&q=80",
            "is_available": False,  # Demo out-of-stock item
            "is_spicy": True,
            "variants": [{"name": "4 Skewers", "price": 1100}, {"name": "8 Skewers", "price": 2100}],
            "addons": [{"name": "Paratha", "price": 120}],
        },
        {
            "category_id": cat_map["Biryani & Rice"],
            "name": "Karachi Chicken Dum Biryani",
            "name_ur": "کراچی چکن دم بریانی",
            "description": "Aromatic basmati rice layered with spicy masala chicken, saffron, and crispy fried onions.",
            "base_price": 550,
            "image_url": "https://images.unsplash.com/photo-1563379091339-03b21ab4a4f8?auto=format&fit=crop&w=600&q=80",
            "is_popular": True,
            "is_spicy": True,
            "variants": [{"name": "Single Plate", "price": 550}, {"name": "Double / Family", "price": 1050}],
            "addons": [{"name": "Extra Aloo", "price": 60}, {"name": "Zeera Raita", "price": 90}],
        },
        {
            "category_id": cat_map["Biryani & Rice"],
            "name": "Vegetable Pulao",
            "name_ur": "سبزی پلاؤ",
            "description": "Fragrant basmati rice cooked with seasonal garden vegetables and whole spices.",
            "base_price": 450,
            "image_url": "https://images.unsplash.com/photo-1596797038530-2c107229654b?auto=format&fit=crop&w=600&q=80",
            "is_veg": True,
            "variants": [{"name": "Single Plate", "price": 450}],
            "addons": [{"name": "Mint Raita", "price": 90}],
        },
        {
            "category_id": cat_map["Beverages"],
            "name": "Fresh Mint Margarita",
            "name_ur": "فریش منٹ مارگریٹا",
            "description": "Chilled blended fresh mint leaves, lemon juice, black salt, and sparkling soda.",
            "base_price": 280,
            "image_url": "https://images.unsplash.com/photo-1513558161293-cdaf765ed2fd?auto=format&fit=crop&w=600&q=80",
            "is_popular": True,
            "is_veg": True,
            "variants": [{"name": "Regular Glass", "price": 280}, {"name": "1L Pitcher", "price": 750}],
            "addons": [],
        },
        {
            "category_id": cat_map["Beverages"],
            "name": "Peshawari Karak Chai",
            "name_ur": "پشاوری کڑک چائے",
            "description": "Rich slow-brewed cardamom milk tea served piping hot.",
            "base_price": 150,
            "image_url": "https://images.unsplash.com/photo-1561336313-0bd5e0b27ec8?auto=format&fit=crop&w=600&q=80",
            "is_veg": True,
            "variants": [{"name": "Single Cup", "price": 150}, {"name": "4-Cup Kettle", "price": 520}],
            "addons": [],
        },
        {
            "category_id": cat_map["Desserts"],
            "name": "Hot Gulab Jamun (3 pcs)",
            "name_ur": "گرم گلاب جامن",
            "description": "Soft golden milk dumplings soaked in warm rose-cardamom syrup, topped with pistachios.",
            "base_price": 320,
            "image_url": "https://images.unsplash.com/photo-1666190092159-3171cf0fbb12?auto=format&fit=crop&w=600&q=80",
            "is_veg": True,
            "variants": [{"name": "3 Pieces", "price": 320}, {"name": "6 Pieces", "price": 600}],
            "addons": [{"name": "Vanilla Ice Cream Scoop", "price": 150}],
        },
    ]

    for idx, item in enumerate(items_data, start=1):
        db.add(
            MenuItem(
                restaurant_id=restaurant.id,
                category_id=item["category_id"],
                name=item["name"],
                name_ur=item.get("name_ur", ""),
                description=item["description"],
                base_price=item["base_price"],
                image_url=item["image_url"],
                is_available=item.get("is_available", True),
                is_popular=item.get("is_popular", False),
                is_spicy=item.get("is_spicy", False),
                is_veg=item.get("is_veg", False),
                variants_json=json.dumps(item.get("variants", [])),
                addons_json=json.dumps(item.get("addons", [])),
                sort_order=idx,
            )
        )

    for t_num in ["01", "02", "03", "04", "05"]:
        token = "x89k" if t_num == "04" else generate_secret_token(4)
        db.add(
            DiningTable(
                restaurant_id=restaurant.id,
                table_number=t_num,
                label=f"Table {t_num}",
                secret_token=token,
            )
        )

    db.commit()
