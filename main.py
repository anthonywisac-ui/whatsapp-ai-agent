import os
import re
import aiohttp
import traceback
import random
from dotenv import load_dotenv
from fastapi import FastAPI, Request
from fastapi.responses import PlainTextResponse, HTMLResponse
import uvicorn

load_dotenv()

app = FastAPI()

VERIFY_TOKEN = os.getenv("WHATSAPP_WEBHOOK_VERIFICATION_TOKEN")
WHATSAPP_TOKEN = os.getenv("WHATSAPP_TOKEN")
WHATSAPP_PHONE_NUMBER_ID = os.getenv("WHATSAPP_PHONE_NUMBER_ID")
GROQ_API_KEY = os.getenv("GROQ_API_KEY")

print(f"Token: {WHATSAPP_TOKEN[:20] if WHATSAPP_TOKEN else 'MISSING'}...")
print(f"Phone ID: {WHATSAPP_PHONE_NUMBER_ID}")

# ----------------------------
# SESSION STORE (in-memory)
# ----------------------------
customer_sessions = {}

def new_session():
    return {
        "stage": "ai_chat",
        "order": {},              # {item_id: {"item": {...}, "qty": int}}
        "delivery_type": "",
        "address": "",
        "name": "",
        "payment": "",
        "last_added": None,
        "current_cat": None,
        "pending_combo": [],
        "conversation": [],
        "upsell_declined": False, # once they decline, reduce upsells
    }

def get_session(sender):
    if sender not in customer_sessions:
        customer_sessions[sender] = new_session()
    return customer_sessions[sender]

# ----------------------------
# MENU (Wild Bites)
# ----------------------------
MENU = {
    "deals": {
        "name": "🔥 Deals (Best Value)",
        "items": {
            "DL1": {"name": "Burger Combo Add-on", "price": 4.99, "emoji": "🔥", "desc": "Add fries + soda to any burger"},
            "DL2": {"name": "Double Smash Meal Deal", "price": 18.99, "emoji": "🍔", "desc": "Smash burger + fries + soda"},
            "DL3": {"name": "Pizza + Wings Deal", "price": 21.99, "emoji": "🍕", "desc": "Any 12” pizza + 6 wings"},
            "DL4": {"name": "Family Pizza Deal", "price": 29.99, "emoji": "👨‍👩‍👧‍👦", "desc": "2 pizzas + 2 sodas"},
            "DL5": {"name": "Ribs Night Deal", "price": 21.99, "emoji": "🍖", "desc": "Half rack + 2 sides + soda"},
            "DL6": {"name": "Fish & Chips Combo", "price": 18.49, "emoji": "🐟", "desc": "Fish & chips + soda"},
        }
    },

    "fastfood": {
        "name": "🍔 Burgers & Fast Food",
        "items": {
            "FF1": {"name": "Classic Smash Burger", "price": 12.99, "emoji": "🍔", "desc": "Double patty, special sauce, lettuce"},
            "FF2": {"name": "Crispy Chicken Sandwich", "price": 11.99, "emoji": "🍗", "desc": "Crispy fried chicken, pickles, mayo"},
            "FF3": {"name": "BBQ Bacon Burger", "price": 14.99, "emoji": "🥓", "desc": "Beef patty, bacon, BBQ sauce, onion rings"},
            "FF4": {"name": "Veggie Delight Burger", "price": 10.99, "emoji": "🥬", "desc": "Plant-based patty, avocado, fresh veggies"},
            "FF5": {"name": "Spicy Jalapeño Burger", "price": 13.99, "emoji": "🌶️", "desc": "Beef patty, jalapeños, pepper jack cheese"},
        }
    },

    "pizza": {
        "name": "🍕 Pizza (12”)",
        "items": {
            "PZ1": {"name": "Margherita Classic", "price": 13.99, "emoji": "🍕", "desc": "Fresh mozzarella, tomato, basil"},
            "PZ2": {"name": "BBQ Chicken Pizza", "price": 15.99, "emoji": "🍗", "desc": "Grilled chicken, BBQ sauce, red onions"},
            "PZ3": {"name": "Meat Lovers Supreme", "price": 17.99, "emoji": "🥩", "desc": "Pepperoni, sausage, beef, bacon"},
            "PZ4": {"name": "Veggie Garden Pizza", "price": 14.99, "emoji": "🥦", "desc": "Bell peppers, mushrooms, olives, onions"},
            "PZ5": {"name": "Buffalo Chicken Pizza", "price": 16.99, "emoji": "🔥", "desc": "Buffalo sauce, chicken, ranch drizzle"},
        }
    },

    "bbq": {
        "name": "🍖 BBQ",
        "items": {
            "BB1": {"name": "Half Rack Ribs", "price": 18.99, "emoji": "🍖", "desc": "Smoky ribs, BBQ glaze (choose 2 sides)"},
            "BB2": {"name": "Full Rack Ribs", "price": 29.99, "emoji": "🍖", "desc": "Full rack (choose 2 sides)"},
            "BB3": {"name": "Pulled Pork Sandwich", "price": 12.99, "emoji": "🥪", "desc": "Slow-cooked pork, slaw, BBQ sauce"},
            "BB4": {"name": "Smoked Brisket Plate", "price": 19.99, "emoji": "🥩", "desc": "Sliced brisket (choose 2 sides)"},
            "BB5": {"name": "BBQ Chicken Plate", "price": 16.99, "emoji": "🍗", "desc": "BBQ chicken (choose 2 sides)"},
        }
    },

    "fish": {
        "name": "🐟 Fish & Seafood",
        "items": {
            "FS1": {"name": "Fish & Chips (Cod)", "price": 15.99, "emoji": "🐟", "desc": "Beer-battered cod, fries, tartar"},
            "FS2": {"name": "Blackened Salmon Plate", "price": 19.99, "emoji": "🍣", "desc": "Rice + side salad, lemon butter"},
            "FS3": {"name": "Shrimp Basket", "price": 16.99, "emoji": "🍤", "desc": "Crispy shrimp, fries, cocktail sauce"},
            "FS4": {"name": "Fish Sandwich", "price": 13.49, "emoji": "🥪", "desc": "Fried cod, lettuce, pickles, tartar"},
        }
    },

    "sides": {
        "name": "🍟 Sides & Snacks",
        "items": {
            "SD1": {"name": "Crispy French Fries", "price": 3.99, "emoji": "🍟", "desc": "Golden & crispy, seasoned salt"},
            "SD2": {"name": "Onion Rings", "price": 4.99, "emoji": "⭕", "desc": "Beer battered, crispy"},
            "SD3": {"name": "Mac & Cheese Bites", "price": 5.99, "emoji": "🧀", "desc": "Creamy inside, crispy outside"},
            "SD4": {"name": "Chicken Wings (6pc)", "price": 8.99, "emoji": "🍗", "desc": "Buffalo or BBQ sauce"},
            "SD5": {"name": "Loaded Nachos", "price": 7.99, "emoji": "🌮", "desc": "Cheese, jalapeños, sour cream, salsa"},
            "SD6": {"name": "Caesar Salad", "price": 6.99, "emoji": "🥗", "desc": "Romaine, croutons, parmesan"},
        }
    },

    "drinks": {
        "name": "🥤 Drinks & Shakes",
        "items": {
            "DR1": {"name": "Coca Cola", "price": 2.99, "emoji": "🥤", "desc": "Ice cold, 16oz"},
            "DR2": {"name": "Pepsi", "price": 2.99, "emoji": "🥤", "desc": "Ice cold, 16oz"},
            "DR3": {"name": "Fresh Orange Juice", "price": 4.99, "emoji": "🍊", "desc": "Freshly squeezed, 12oz"},
            "DR4": {"name": "Mango Lassi", "price": 5.99, "emoji": "🥭", "desc": "Fresh mango, yogurt, cardamom"},
            "DR5": {"name": "Strawberry Milkshake", "price": 6.99, "emoji": "🍓", "desc": "Real strawberries, thick & creamy"},
            "DR6": {"name": "Lemonade", "price": 3.99, "emoji": "🍋", "desc": "Fresh squeezed, 16oz"},
            "DR7": {"name": "Iced Coffee", "price": 4.99, "emoji": "☕", "desc": "Cold brew, milk, sugar"},
            "DR8": {"name": "Water (Bottle)", "price": 1.99, "emoji": "💧", "desc": "500ml spring water"},
        }
    },

    "desserts": {
        "name": "🍰 Desserts",
        "items": {
            "DS1": {"name": "Chocolate Lava Cake", "price": 6.99, "emoji": "🍫", "desc": "Warm, gooey center, vanilla ice cream"},
            "DS2": {"name": "NY Cheesecake", "price": 5.99, "emoji": "🍰", "desc": "Classic NY style, strawberry topping"},
            "DS3": {"name": "Oreo Milkshake", "price": 7.99, "emoji": "🥛", "desc": "Thick shake, crushed Oreos, whipped cream"},
            "DS4": {"name": "Brownie Sundae", "price": 6.99, "emoji": "🍨", "desc": "Warm brownie, vanilla ice cream, choc sauce"},
        }
    }
}

# For legacy combo mapping (still used as fallback)
UPSELL_COMBOS = {
    "FF1": ["SD1", "DR1"],
    "FF2": ["SD1", "DR1"],
    "FF3": ["SD2", "DR1"],
    "PZ1": ["SD4", "DR6"],
    "PZ3": ["SD4", "DR1"],
    "FS1": ["DR1"],
}

MENU_SUMMARY = """
Wild Bites Restaurant Menu (US):
🔥 Deals: Burger combo add-on, pizza+wings, family deals
🍔 Burgers: Classic Smash, Crispy Chicken, BBQ Bacon, Veggie, Spicy Jalapeño
🍕 Pizza (12”): Margherita, BBQ Chicken, Meat Lovers, Veggie, Buffalo Chicken
🍖 BBQ: Ribs, Brisket, Pulled Pork, BBQ Chicken
🐟 Fish: Fish & chips, Salmon, Shrimp basket, Fish sandwich
🥤 Drinks: Coke/Pepsi, lemonade, shakes, iced coffee
🍟 Sides: Fries, onion rings, wings, nachos, salad
🍰 Desserts: Lava cake, cheesecake, brownie sundae
Hours: 10am-11pm daily | Delivery: 30-45 mins | Pickup: 15-20 mins | Free delivery over $25
"""

# ----------------------------
# ORDER UTILITIES
# ----------------------------
def get_order_total(order):
    return sum(v["item"]["price"] * v["qty"] for v in order.values())

def get_order_text(order):
    if not order:
        return "Empty cart"
    lines = []
    for item_id, v in order.items():
        item = v["item"]
        qty = v["qty"]
        subtotal = item["price"] * qty
        lines.append(f"{item['emoji']} {item['name']} x{qty} — ${subtotal:.2f}")
    return "\n".join(lines)

def has_any_side(order):
    return any(k.startswith("SD") for k in order.keys())

def has_any_drink(order):
    return any(k.startswith("DR") for k in order.keys())

def is_burger(item_id): return item_id.startswith("FF")
def is_pizza(item_id): return item_id.startswith("PZ")
def is_bbq(item_id): return item_id.startswith("BB")
def is_fish(item_id): return item_id.startswith("FS")

def find_item(item_id):
    for cat_key, cat_data in MENU.items():
        if item_id in cat_data["items"]:
            return cat_key, cat_data["items"][item_id]
    return None, None

def guess_category(text_lower: str):
    t = text_lower
    if any(w in t for w in ["deal", "combo", "offer", "special"]): return "deals"
    if any(w in t for w in ["burger", "smash", "bacon", "jalap", "cheese burger", "cheeseburger", "chicken sandwich"]): return "fastfood"
    if any(w in t for w in ["pizza", "pepperoni", "margherita", "slice", "meat lovers"]): return "pizza"
    if any(w in t for w in ["bbq", "ribs", "brisket", "pulled pork"]): return "bbq"
    if any(w in t for w in ["fish", "salmon", "shrimp", "seafood", "chips"]): return "fish"
    if any(w in t for w in ["drink", "coke", "pepsi", "shake", "lemonade", "iced coffee"]): return "drinks"
    if any(w in t for w in ["dessert", "cake", "cheesecake", "brownie", "sweet"]): return "desserts"
    if any(w in t for w in ["side", "fries", "wings", "nachos", "rings"]): return "sides"
    return None

# ----------------------------
# WEBHOOK
# ----------------------------
@app.get("/webhook")
async def verify_webhook(request: Request):
    params = dict(request.query_params)
    if params.get("hub.verify_token") == VERIFY_TOKEN:
        return PlainTextResponse(params.get("hub.challenge", ""))
    return PlainTextResponse("Forbidden", status_code=403)

@app.post("/webhook")
async def handle_webhook(request: Request):
    data = await request.json()
    try:
        entry = data["entry"][0]["changes"][0]["value"]

        if "messages" in entry:
            message = entry["messages"][0]
            sender = message["from"]
            msg_type = message.get("type", "")

            if msg_type == "text":
                text = message["text"]["body"].strip()
                print(f"MSG: {text} from {sender}")
                await handle_flow(sender, text)

            elif msg_type == "interactive":
                interactive = message["interactive"]
                if interactive["type"] == "button_reply":
                    btn_id = interactive["button_reply"]["id"]
                    print(f"BTN: {btn_id} from {sender}")
                    await handle_flow(sender, btn_id, is_button=True)
                elif interactive["type"] == "list_reply":
                    list_id = interactive["list_reply"]["id"]
                    print(f"LIST: {list_id} from {sender}")
                    await handle_flow(sender, list_id, is_button=True)

    except Exception as e:
        print(f"ERROR: {e}\n{traceback.format_exc()}")

    return {"status": "ok"}

# ----------------------------
# FLOW HANDLER
# ----------------------------
async def handle_flow(sender, text, is_button=False):
    session = get_session(sender)
    stage = session["stage"]
    text_lower = text.lower().strip()

    # RESET
    if text_lower in ["restart", "reset", "start over", "clear", "cancel all"]:
        customer_sessions[sender] = new_session()
        await send_text_message(sender, "👋 Hey! Wild Bites here. What are you craving today? 😄")
        await send_main_menu(sender, {})
        return

    if text in ["SHOW_MENU", "BACK_MENU", "ADD_MORE"]:
        session["stage"] = "menu"
        await send_main_menu(sender, session["order"])
        return
		
    # Quick cart commands: "remove FF1", "qty FF1 2"
    m_remove = re.match(r"^(remove|delete)\s+([a-z0-9]+)$", text_lower)
    m_qty = re.match(r"^(qty|quantity)\s+([a-z0-9]+)\s+(\d+)$", text_lower)
    if m_remove:
        item_id = m_remove.group(2).upper()
        if item_id in session["order"]:
            del session["order"][item_id]
            await send_text_message(sender, f"✅ Removed {item_id}.")
        await send_cart_view(sender, session["order"])
        return

    if m_qty:
        item_id = m_qty.group(2).upper()
        qty = int(m_qty.group(3))
        if qty <= 0:
            if item_id in session["order"]:
                del session["order"][item_id]
        else:
            cat, item = find_item(item_id)
            if item:
                session["order"][item_id] = {"item": item, "qty": qty}
        await send_cart_view(sender, session["order"])
        return

    # CATEGORY BUTTONS (universal)
    cat_map = {
        "CAT_DEALS": "deals",
        "CAT_FASTFOOD": "fastfood",
        "CAT_PIZZA": "pizza",
        "CAT_BBQ": "bbq",
        "CAT_FISH": "fish",
        "CAT_SIDES": "sides",
        "CAT_DRINKS": "drinks",
        "CAT_DESSERTS": "desserts",
    }
    if text in cat_map:
        cat_key = cat_map[text]
        session["stage"] = "items"
        session["current_cat"] = cat_key
        await send_category_items(sender, cat_key, session["order"])
        return

# ITEM ADD (universal)
    if text.startswith("ADD_"):
        item_id = text.replace("ADD_", "").upper()
        cat, found_item = find_item(item_id)

        if found_item:
            if item_id in session["order"]:
                session["order"][item_id]["qty"] += 1
            else:
                session["order"][item_id] = {"item": found_item, "qty": 1}

            session["last_added"] = item_id
            session["stage"] = "qty_control"

            # BBQ plates: ask sides (doesn't block flow)
            if item_id in ["BB1", "BB2", "BB4", "BB5"]:
                await send_text_message(sender, "Quick one 😄 Pick 2 sides: mac & cheese, fries, slaw, baked beans, or salad.")

            # SMART UPSELL (only if not declined)
            if not session.get("upsell_declined", False):
                if is_burger(item_id) and not (has_any_side(session["order"]) and has_any_drink(session["order"])) and len(session["order"]) <= 2:
                    await send_quick_combo_upsell(sender)
                    return

                if is_pizza(item_id) and "SD4" not in session["order"] and len(session["order"]) <= 2:
                    await send_quick_upsell(sender, "SD4", "🍗 Want to add 6 wings? Most people grab wings with pizza 😄")
                    return

                if is_fish(item_id) and len(session["order"]) <= 2:
                    await send_quick_text_upsell(sender, "Extra tartar/cocktail sauce for +$1? (Reply YES or NO)")
                    await send_qty_control(sender, item_id, found_item, session["order"])
                    return

            await send_qty_control(sender, item_id, found_item, session["order"])
            return

    # QTY CONTROL
    if text in ["QTY_PLUS", "QTY_MINUS"]:
        item_id = session.get("last_added")
        if item_id and item_id in session["order"]:
            if text == "QTY_PLUS":
                session["order"][item_id]["qty"] += 1
            else:
                if session["order"][item_id]["qty"] > 1:
                    session["order"][item_id]["qty"] -= 1
                else:
                    del session["order"][item_id]

        if item_id and item_id in session["order"]:
            await send_qty_control(sender, item_id, session["order"][item_id]["item"], session["order"])
        else:
            session["stage"] = "menu"
            await send_main_menu(sender, session["order"])
        return

    # QUICK UPSELL BUTTONS
    if text == "SKIP_UPSELL":
        session["upsell_declined"] = True
        last = session.get("last_added")
        if last and last in session["order"]:
            await send_qty_control(sender, last, session["order"][last]["item"], session["order"])
        else:
            await send_main_menu(sender, session["order"])
        return

    if text == "ADD_COMBO_DL1":
        deal_item = MENU["deals"]["items"]["DL1"]
        if "DL1" not in session["order"]:
            session["order"]["DL1"] = {"item": deal_item, "qty": 1}
        last = session.get("last_added")
        if last and last in session["order"]:
            await send_qty_control(sender, last, session["order"][last]["item"], session["order"])
        else:
            await send_cart_view(sender, session["order"])
        return

    # CHECKOUT
    if text == "CHECKOUT":
        if session["order"]:
            session["stage"] = "upsell_check"
            await send_dessert_upsell(sender, session["order"])
        else:
            await send_text_message(sender, "🛒 Your cart is empty! Add some items first 😊")
            await send_main_menu(sender, session["order"])
        return

    # UNIVERSAL
    if text == "VIEW_CART":
        await send_cart_view(sender, session["order"])
        return

    if text in ["ADD_MORE", "BACK_MENU", "SHOW_MENU"]:
        session["stage"] = "menu"
        await send_main_menu(sender, session["order"])
        return

    # Dessert upsell
    if text in ["YES_UPSELL", "NO_UPSELL"]:
        if text == "YES_UPSELL":
            session["stage"] = "items"
            session["current_cat"] = "desserts"
            await send_category_items(sender, "desserts", session["order"])
        else:
            session["stage"] = "confirm"
            await send_order_summary(sender, session["order"])
        return

    # Confirm / Cancel
    if text == "CONFIRM_ORDER":
        session["stage"] = "get_name"
        await send_text_message(sender, "👤 *What's your name?* (First name is perfect 😊)")
        return

    if text == "CANCEL_ORDER":
        customer_sessions[sender] = new_session()
        await send_text_message(sender, "❌ Order cancelled. No worries!\n\nType *menu* to start again.")
        return

    # Delivery/Pickup
    if text in ["DELIVERY", "PICKUP"]:
        if text == "DELIVERY":
            session["delivery_type"] = "delivery"
            session["stage"] = "address"
            name = session.get("name", "")
            await send_text_message(sender, f"📍 Hey {name}! What’s your delivery address?\nExample: 123 Main St, New York, NY 10001")
        else:
            session["delivery_type"] = "pickup"
            session["stage"] = "payment"
            await send_payment_buttons(sender, session.get("name", ""))
        return

    # Payment
    if text in ["CASH", "CARD", "APPLE_PAY"]:
        payment_map = {"CASH": "💵 Cash", "CARD": "💳 Card", "APPLE_PAY": "📱 Apple/Google Pay"}
        session["payment"] = payment_map[text]
        await send_order_confirmed(sender, session)
        customer_sessions[sender] = new_session()
        return

    # Stage-specific
    if stage == "get_name":
        session["name"] = text.strip().title()[:30]
        session["stage"] = "delivery"
        await send_delivery_buttons(sender, session["name"])
        return

    if stage == "address":
        session["address"] = text.strip()
        session["stage"] = "payment"
        await send_text_message(sender, "✅ Got it! Now choose a payment method 👇")
        await send_payment_buttons(sender, session.get("name", ""))
        return

    # Greetings / menu intent
    if text_lower in ["hi", "hello", "hey", "menu", "order", "start", "salam", "hola"]:
        session["stage"] = "menu"
        greeting = await get_ai_response(sender, text, "User greeted. Reply with ONE friendly line, then guide to menu.")
        await send_text_message(sender, greeting)
        await send_main_menu(sender, session["order"])
        return

    # Intent router
    cat_guess = guess_category(text_lower)
    if cat_guess:
        await send_text_message(sender, "Got you 👍 Tap an item to add it to your cart:")
        session["stage"] = "items"
        session["current_cat"] = cat_guess
        await send_category_items(sender, cat_guess, session["order"])
        return

    # Fish sauce yes/no
    if text_lower in ["yes", "yeah", "yep"] and session.get("last_added", "").startswith("FS"):
        await send_text_message(sender, "Perfect — I’ll add extra sauce on the side ✅")
        await send_cart_view(sender, session["order"])
        return

    if text_lower in ["no", "nope", "nah"] and session.get("last_added", "").startswith("FS"):
        await send_text_message(sender, "No problem 😄")
        await send_cart_view(sender, session["order"])
        return

    # AI fallback
    reply = await get_ai_response(sender, text)
    await send_text_message(sender, reply)

    session["conversation"].append(text)
    if len(session["conversation"]) >= 2:
        await send_menu_suggestion(sender)
        session["conversation"] = []

async def send_main_menu(sender, current_order=None):
    current_order = current_order or {}
    total = get_order_total(current_order)
    cart_text = ""
    if current_order:
        count = sum(v["qty"] for v in current_order.values())
        cart_text = f"\n\n🛒 *Cart: {count} item(s) — ${total:.2f}*"

    url = f"https://graph.facebook.com/v18.0/{WHATSAPP_PHONE_NUMBER_ID}/messages"
    headers = {"Authorization": f"Bearer {WHATSAPP_TOKEN}", "Content-Type": "application/json"}
    payload = {
        "messaging_product": "whatsapp",
        "to": sender,
        "type": "interactive",
        "interactive": {
            "type": "list",
            "header": {"type": "text", "text": "🍽️ Wild Bites Restaurant"},
            "body": {"text": f"What are you craving today? 😋{cart_text}\n\nTap a category below 👇"},
            "footer": {"text": "🚀 Fast Delivery | Fresh Food | Best Value"},
            "action": {
                "button": "📋 Browse Menu",
                "sections": [
                    {"title": "🔥 Start Here", "rows": [
                        {"id": "CAT_DEALS", "title": "🔥 Deals (Best Value)", "description": "Combos & bundles — save money"},
                    ]},
                    {"title": "🍽️ Main", "rows": [
                        {"id": "CAT_FASTFOOD", "title": "🍔 Burgers & Fast Food", "description": "Smash burgers, chicken — from $10.99"},
                        {"id": "CAT_PIZZA", "title": "🍕 Pizza (12”)", "description": "Classic & specialty — from $13.99"},
                        {"id": "CAT_BBQ", "title": "🍖 BBQ", "description": "Ribs, brisket, pulled pork"},
                        {"id": "CAT_FISH", "title": "🐟 Fish & Seafood", "description": "Fish & chips, salmon, shrimp"},
                    ]},
                    {"title": "🥤 Extras", "rows": [
                        {"id": "CAT_SIDES", "title": "🍟 Sides & Snacks", "description": "Fries, wings, nachos — from $3.99"},
                        {"id": "CAT_DRINKS", "title": "🥤 Drinks & Shakes", "description": "Soda, lemonade, shakes — from $1.99"},
                        {"id": "CAT_DESSERTS", "title": "🍰 Desserts", "description": "Cakes, sundaes — from $5.99"},
                    ]},
                ]
            }
        }
    }

    async with aiohttp.ClientSession() as s:
        async with s.post(url, json=payload, headers=headers) as r:
            _ = await r.text()

# ===== CHUNK 2 START: send_category_items =====
async def send_category_items(sender, cat_key, current_order):
    cat = MENU[cat_key]
    total = get_order_total(current_order)
    cart_text = f"\n\n🛒 Cart Total: ${total:.2f}" if current_order else ""

    rows = []
    for item_id, item in cat["items"].items():
        in_cart = current_order.get(item_id, {}).get("qty", 0)
        cart_indicator = f" ✅x{in_cart}" if in_cart else ""
        rows.append({
            "id": f"ADD_{item_id}",
            "title": f"{item['emoji']} {item['name']}{cart_indicator}",
            "description": f"${item['price']:.2f} • {item['desc']}"
        })

    url = f"https://graph.facebook.com/v18.0/{WHATSAPP_PHONE_NUMBER_ID}/messages"
    headers = {"Authorization": f"Bearer {WHATSAPP_TOKEN}", "Content-Type": "application/json"}
    payload = {
        "messaging_product": "whatsapp",
        "to": sender,
        "type": "interactive",
        "interactive": {
            "type": "list",
            "header": {"type": "text", "text": cat["name"]},
            "body": {"text": f"Tap any item to add to your cart 👇{cart_text}"},
            "footer": {"text": "✅ in cart shows what you've already added"},
            "action": {
                "button": "Select Item",
                "sections": [{"title": cat["name"], "rows": rows}]
            }
        }
    }

    async with aiohttp.ClientSession() as s:
        async with s.post(url, json=payload, headers=headers) as r:
            _ = await r.text()
# ===== CHUNK 2 END =====

# ===== CHUNK 3 START: send_qty_control =====
async def send_qty_control(sender, item_id, item, order):
    qty = order.get(item_id, {}).get("qty", 1)
    subtotal = item["price"] * qty
    total = get_order_total(order)
    order_text = get_order_text(order)

    url = f"https://graph.facebook.com/v18.0/{WHATSAPP_PHONE_NUMBER_ID}/messages"
    headers = {"Authorization": f"Bearer {WHATSAPP_TOKEN}", "Content-Type": "application/json"}
    payload = {
        "messaging_product": "whatsapp",
        "to": sender,
        "type": "interactive",
        "interactive": {
            "type": "button",
            "header": {"type": "text", "text": f"✅ {item['emoji']} Added to Cart!"},
            "body": {
                "text": (
                    f"*{item['name']}*\n"
                    f"Qty: {qty} × ${item['price']:.2f} = *${subtotal:.2f}*\n\n"
                    f"{'─'*20}\n📋 *Your Order:*\n{order_text}\n"
                    f"{'─'*20}\n💰 *Total: ${total:.2f}*"
                )
            },
            "footer": {"text": "Wild Bites Restaurant"},
            "action": {
                "buttons": [
                    {"type": "reply", "reply": {"id": "QTY_MINUS", "title": "➖ Remove One"}},
                    {"type": "reply", "reply": {"id": "QTY_PLUS", "title": "➕ Add One More"}},
                    {"type": "reply", "reply": {"id": "ADD_MORE", "title": "🍽️ Add More Items"}},
                ]
            }
        }
    }

    async with aiohttp.ClientSession() as s:
        async with s.post(url, json=payload, headers=headers) as r:
            _ = await r.text()

    await send_checkout_prompt(sender, total)
# ===== CHUNK 3 END =====
# ===== CHUNK 4 START: send_checkout_prompt =====
async def send_checkout_prompt(sender, total):
    url = f"https://graph.facebook.com/v18.0/{WHATSAPP_PHONE_NUMBER_ID}/messages"
    headers = {"Authorization": f"Bearer {WHATSAPP_TOKEN}", "Content-Type": "application/json"}
    payload = {
        "messaging_product": "whatsapp",
        "to": sender,
        "type": "interactive",
        "interactive": {
            "type": "button",
            "body": {"text": "Ready to place your order? 🚀"},
            "action": {
                "buttons": [
                    {"type": "reply", "reply": {"id": "CHECKOUT", "title": f"✅ Checkout ${total:.2f}"}},
                    {"type": "reply", "reply": {"id": "VIEW_CART", "title": "🛒 View Cart"}},
                ]
            }
        }
    }
    async with aiohttp.ClientSession() as s:
        async with s.post(url, json=payload, headers=headers) as r:
            _ = await r.text()
# ===== CHUNK 4 END =====
# ===== CHUNK 5 START: send_dessert_upsell =====
async def send_dessert_upsell(sender, order):
    total = get_order_total(order)

    url = f"https://graph.facebook.com/v18.0/{WHATSAPP_PHONE_NUMBER_ID}/messages"
    headers = {"Authorization": f"Bearer {WHATSAPP_TOKEN}", "Content-Type": "application/json"}
    payload = {
        "messaging_product": "whatsapp",
        "to": sender,
        "type": "interactive",
        "interactive": {
            "type": "button",
            "header": {"type": "text", "text": "🍰 Save room for dessert?"},
            "body": {"text": f"Your order is ${total:.2f}.\n\nWant to add a dessert? 😍"},
            "footer": {"text": "Wild Bites Restaurant"},
            "action": {
                "buttons": [
                    {"type": "reply", "reply": {"id": "YES_UPSELL", "title": "🍰 Yes, show desserts"}},
                    {"type": "reply", "reply": {"id": "NO_UPSELL", "title": "✅ No, continue"}},
                ]
            }
        }
    }
    async with aiohttp.ClientSession() as s:
        async with s.post(url, json=payload, headers=headers) as r:
            _ = await r.text()
# ===== CHUNK 5 END =====
# ===== CHUNK 6 START: send_cart_view =====
async def send_cart_view(sender, order):
    if not order:
        await send_text_message(sender, "🛒 Your cart is empty!\n\nType *menu* to browse options 😊")
        return

    total = get_order_total(order)
    order_text = get_order_text(order)

    url = f"https://graph.facebook.com/v18.0/{WHATSAPP_PHONE_NUMBER_ID}/messages"
    headers = {"Authorization": f"Bearer {WHATSAPP_TOKEN}", "Content-Type": "application/json"}
    payload = {
        "messaging_product": "whatsapp",
        "to": sender,
        "type": "interactive",
        "interactive": {
            "type": "button",
            "header": {"type": "text", "text": "🛒 Your Cart"},
            "body": {"text": f"{order_text}\n\n{'─'*25}\n💰 *Subtotal: ${total:.2f}*"},
            "footer": {"text": "Wild Bites Restaurant"},
            "action": {
                "buttons": [
                    {"type": "reply", "reply": {"id": "CHECKOUT", "title": f"✅ Checkout ${total:.2f}"}},
                    {"type": "reply", "reply": {"id": "ADD_MORE", "title": "➕ Add More"}},
                    {"type": "reply", "reply": {"id": "CANCEL_ORDER", "title": "❌ Clear Cart"}},
                ]
            }
        }
    }
    async with aiohttp.ClientSession() as s:
        async with s.post(url, json=payload, headers=headers) as r:
            _ = await r.text()
# ===== CHUNK 6 END =====
# ===== CHUNK 7 START: send_order_summary =====
async def send_order_summary(sender, order):
    total = get_order_total(order)
    tax = total * 0.08
    grand_total = total + tax
    order_text = get_order_text(order)

    url = f"https://graph.facebook.com/v18.0/{WHATSAPP_PHONE_NUMBER_ID}/messages"
    headers = {"Authorization": f"Bearer {WHATSAPP_TOKEN}", "Content-Type": "application/json"}
    payload = {
        "messaging_product": "whatsapp",
        "to": sender,
        "type": "interactive",
        "interactive": {
            "type": "button",
            "header": {"type": "text", "text": "📋 Order Summary"},
            "body": {
                "text": (
                    f"{order_text}\n\n{'─'*25}\n"
                    f"💰 Subtotal: ${total:.2f}\n"
                    f"📊 Tax (8%): ${tax:.2f}\n"
                    f"{'─'*25}\n"
                    f"💵 *Total: ${grand_total:.2f}*\n\n"
                    f"Ready to confirm? ✅"
                )
            },
            "footer": {"text": "Wild Bites Restaurant"},
            "action": {
                "buttons": [
                    {"type": "reply", "reply": {"id": "CONFIRM_ORDER", "title": "✅ Confirm"}},
                    {"type": "reply", "reply": {"id": "ADD_MORE", "title": "➕ Add More"}},
                    {"type": "reply", "reply": {"id": "CANCEL_ORDER", "title": "❌ Cancel"}},
                ]
            }
        }
    }
    async with aiohttp.ClientSession() as s:
        async with s.post(url, json=payload, headers=headers) as r:
            _ = await r.text()
# ===== CHUNK 7 END =====
# ===== CHUNK 8 START: delivery + payment buttons =====
async def send_delivery_buttons(sender, name):
    url = f"https://graph.facebook.com/v18.0/{WHATSAPP_PHONE_NUMBER_ID}/messages"
    headers = {"Authorization": f"Bearer {WHATSAPP_TOKEN}", "Content-Type": "application/json"}
    payload = {
        "messaging_product": "whatsapp",
        "to": sender,
        "type": "interactive",
        "interactive": {
            "type": "button",
            "header": {"type": "text", "text": f"🚚 Hey {name}! Delivery or pickup?"},
            "body": {"text": "🚚 Delivery (30–45 mins)\n🏪 Pickup (15–20 mins)"},
            "footer": {"text": "Wild Bites Restaurant"},
            "action": {
                "buttons": [
                    {"type": "reply", "reply": {"id": "DELIVERY", "title": "🚚 Delivery"}},
                    {"type": "reply", "reply": {"id": "PICKUP", "title": "🏪 Pickup"}},
                ]
            }
        }
    }
    async with aiohttp.ClientSession() as s:
        async with s.post(url, json=payload, headers=headers) as r:
            _ = await r.text()

async def send_payment_buttons(sender, name):
    url = f"https://graph.facebook.com/v18.0/{WHATSAPP_PHONE_NUMBER_ID}/messages"
    headers = {"Authorization": f"Bearer {WHATSAPP_TOKEN}", "Content-Type": "application/json"}
    payload = {
        "messaging_product": "whatsapp",
        "to": sender,
        "type": "interactive",
        "interactive": {
            "type": "button",
            "header": {"type": "text", "text": "💳 How would you like to pay?"},
            "body": {"text": "Choose your payment method:"},
            "footer": {"text": "Wild Bites Restaurant"},
            "action": {
                "buttons": [
                    {"type": "reply", "reply": {"id": "CASH", "title": "💵 Cash"}},
                    {"type": "reply", "reply": {"id": "CARD", "title": "💳 Card"}},
                    {"type": "reply", "reply": {"id": "APPLE_PAY", "title": "📱 Apple/Google Pay"}},
                ]
            }
        }
    }
    async with aiohttp.ClientSession() as s:
        async with s.post(url, json=payload, headers=headers) as r:
            _ = await r.text()
# ===== CHUNK 8 END =====
# ===== CHUNK 9 START: send_order_confirmed =====
async def send_order_confirmed(sender, session_data):
    order = session_data.get("order", {})
    total = get_order_total(order)
    tax = total * 0.08
    grand_total = total + tax
    order_text = get_order_text(order)

    delivery_type = session_data.get("delivery_type", "pickup")
    address = session_data.get("address", "")
    payment = session_data.get("payment", "Cash")
    name = session_data.get("name", "Customer")

    order_id = random.randint(10000, 99999)
    eta = "30-45 minutes" if delivery_type == "delivery" else "15-20 minutes"

    msg = f"""🎉 *Order Confirmed, {name}!*

📋 *Order #{order_id}*

{order_text}

{'─'*25}
💰 Subtotal: ${total:.2f}
📊 Tax (8%): ${tax:.2f}
{'─'*25}
💵 *Total: ${grand_total:.2f}*

{'🚚 Delivery to: ' + address if delivery_type == 'delivery' else '🏪 Store Pickup'}
💳 Payment: {payment}
⏱️ Ready in: *{eta}*

Thank you for choosing Wild Bites! 🍔
Type *Hi* to order again anytime!"""

    await send_text_message(sender, msg)
# ===== CHUNK 9 END =====

# ----------------------------
# AI RESPONSE (Groq)
# ----------------------------
async def get_ai_response(sender, user_message, extra_instruction=""):
    system_prompt = f"""You are Alex, a friendly customer service rep at Wild Bites Restaurant in the US.

Your personality:
- Warm, friendly, helpful — like a real human staff member
- Casual but professional
- Use emojis naturally (not too many)
- Short responses — max 3-4 sentences
- Ask only ONE question at a time
- If someone asks about food, recommend something specific
- If someone asks about hours: "We're open 10am-11pm daily"
- If someone asks about location: "We deliver citywide and have a pickup location downtown"
- NEVER say you're an AI or bot
- Reply in the same language the user writes in

{MENU_SUMMARY}

{extra_instruction}"""

    headers = {
        "Authorization": f"Bearer {GROQ_API_KEY}",
        "Content-Type": "application/json"
    }
    payload = {
        "model": "llama-3.1-8b-instant",
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_message}
        ],
        "temperature": 0.7,
        "max_tokens": 180
    }
    try:
        async with aiohttp.ClientSession() as s:
            async with s.post(
                "https://api.groq.com/openai/v1/chat/completions",
                json=payload,
                headers=headers
            ) as r:
                result = await r.json()
                return result["choices"][0]["message"]["content"]
    except Exception as e:
        print(f"AI Error: {e}")
        return "Sorry—quick question: is this for delivery or pickup? 🙂"


# ── SEND FUNCTIONS ────────────────────────────────────────────────────

async def send_text_message(to, message):
    url = f"https://graph.facebook.com/v18.0/{WHATSAPP_PHONE_NUMBER_ID}/messages"
    headers = {"Authorization": f"Bearer {WHATSAPP_TOKEN}", "Content-Type": "application/json"}
    payload = {"messaging_product": "whatsapp", "to": to, "type": "text", "text": {"body": message}}
    async with aiohttp.ClientSession() as s:
        async with s.post(url, json=payload, headers=headers) as r:
            _ = await r.text()
            print(f"Text sent to {to} ({r.status})")


async def send_menu_suggestion(sender):
    url = f"https://graph.facebook.com/v18.0/{WHATSAPP_PHONE_NUMBER_ID}/messages"
    headers = {"Authorization": f"Bearer {WHATSAPP_TOKEN}", "Content-Type": "application/json"}
    payload = {
        "messaging_product": "whatsapp",
        "to": sender,
        "type": "interactive",
        "interactive": {
            "type": "button",
            "body": {"text": "Want to place an order? 🍔 Tap below to browse the menu."},
            "footer": {"text": "Wild Bites Restaurant"},
            "action": {"buttons": [
                {"type": "reply", "reply": {"id": "SHOW_MENU", "title": "📋 Show Menu"}},
            ]}
        }
    }
    async with aiohttp.ClientSession() as s:
        async with s.post(url, json=payload, headers=headers) as r:
            _ = await r.text()
            print("Menu suggestion sent")


# NOTE: Reuse your existing send_main_menu() / send_category_items() / send_qty_control()
# If those are also broken indentation, they must be fixed too.

@app.post("/twilio-call")
async def twilio_call(request: Request):
    twiml = """<?xml version="1.0" encoding="UTF-8"?>
<Response>
  <Say voice="alice">Welcome to Wild Bites Restaurant. Please send us a WhatsApp message to place your order. Thank you!</Say>
</Response>"""
    return HTMLResponse(content=twiml, media_type="application/xml")


@app.post("/twilio-sms")
async def twilio_sms(request: Request):
    form = await request.form()
    print(f"SMS: {form.get('Body')} from {form.get('From')}")
    return {"status": "ok"}


if __name__ == "__main__":
    port = int(os.getenv("PORT", "8000"))
    uvicorn.run(app, host="0.0.0.0", port=port, log_level="info")