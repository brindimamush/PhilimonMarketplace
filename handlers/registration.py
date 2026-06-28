# handlers/registration.py
import logging
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardRemove, ReplyKeyboardMarkup, KeyboardButton
from telegram.ext import ContextTypes, ConversationHandler
from database.session import db_transaction
from database.models import User, SellerProfile
from keyboards.buyer import get_buyer_home_keyboard
from keyboards.seller import get_seller_home_keyboard
from utils.helpers import get_text, get_user_lang
from config import ADMIN_TELEGRAM_ID

logger = logging.getLogger(__name__)

# Expanded Conversation States
SELECT_LANG, SELECT_ROLE, AGREE_RULES, SHARE_PHONE, FULL_NAME, BUSINESS_NAME, LOCATION, CATEGORY, SHOP_NUMBER = range(9)

async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id == ADMIN_TELEGRAM_ID:
        return
    lang = get_user_lang(update.effective_user.id)
    await update.message.reply_text(get_text(lang, "help_text"), parse_mode="Markdown")

async def cmd_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    telegram_id = update.effective_user.id
    if telegram_id == ADMIN_TELEGRAM_ID:
        from handlers.admin_menu import admin_menu
        return await admin_menu(update, context)

    with db_transaction() as db:
        user = db.query(User).filter(User.telegram_id == telegram_id).first()
        if not user:
            return await start(update, context)
        lang = user.language
        role = user.role
        status = user.status

    if role == 'buyer':
        await update.message.reply_text(get_text(lang, "welcome_back"), reply_markup=get_buyer_home_keyboard(lang))
    elif role == 'seller' and status == 'active':
        await update.message.reply_text(get_text(lang, "welcome_back"), reply_markup=get_seller_home_keyboard(lang))
    else:
        await update.message.reply_text(get_text(lang, "pending_admin"))

async def cmd_language(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id == ADMIN_TELEGRAM_ID:
        return
    keyboard = [
        [InlineKeyboardButton("🇬🇧 English", callback_data="lang_en"),
         InlineKeyboardButton("🇪🇹 አማርኛ", callback_data="lang_am")]
    ]
    await update.message.reply_text("Please select your language / እባክዎ ቋንቋዎን ይምረጡ:", reply_markup=InlineKeyboardMarkup(keyboard))
    return SELECT_LANG

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    telegram_id = update.effective_user.id

    if telegram_id == ADMIN_TELEGRAM_ID:
        try:
            with db_transaction() as db:
                admin = db.query(User).filter(User.telegram_id == telegram_id).first()
                if not admin:
                    new_admin = User(
                        telegram_id=telegram_id,
                        username=update.effective_user.username,
                        role='admin',
                        status='active'
                    )
                    db.add(new_admin)
        except Exception as e:
            logger.error(f"Admin creation failed: {e}")
        await update.message.reply_text("👋 Welcome, Admin.\nUse /admin to open the dashboard or /dashboard for stats.")
        return ConversationHandler.END

    with db_transaction() as db:
        user = db.query(User).filter(User.telegram_id == telegram_id).first()
        user_exists = user is not None

    if user_exists:
        await cmd_menu(update, context)
        return ConversationHandler.END

    keyboard = [
        [InlineKeyboardButton("🇬🇧 English", callback_data="lang_en"),
         InlineKeyboardButton("🇪🇹 አማርኛ", callback_data="lang_am")]
    ]
    await update.message.reply_text("Welcome! Please select your language:\nእንኳን ደህና መጡ! እባክዎ ቋንቋዎን ይምረጡ፡", reply_markup=InlineKeyboardMarkup(keyboard))
    return SELECT_LANG

async def handle_language_selection(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    lang_choice = query.data.split("_")[1]
    context.user_data['lang'] = lang_choice

    try:
        with db_transaction() as db:
            user = db.query(User).filter(User.telegram_id == update.effective_user.id).first()
            if user:
                user.language = lang_choice
                lang = lang_choice
                user_exists = True
            else:
                user_exists = False
    except Exception as e:
        logger.error(f"handle_language_selection failed: {e}")
        user_exists = False

    if user_exists:
        await query.message.delete()
        class FakeUpdate:
            effective_user = update.effective_user
            message = query.message
        await cmd_menu(FakeUpdate, context)
        return ConversationHandler.END

    keyboard = [
        [InlineKeyboardButton(get_text(lang_choice, "buyer_btn"), callback_data="role_buyer"),
         InlineKeyboardButton(get_text(lang_choice, "seller_btn"), callback_data="role_seller")]
    ]
    await query.edit_message_text(get_text(lang_choice, "select_mode"), reply_markup=InlineKeyboardMarkup(keyboard))
    return SELECT_ROLE

async def handle_role_selection(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    target_role = query.data.split("_")[1]
    context.user_data['target_role'] = target_role

    with db_transaction() as db:
        user = db.query(User).filter(User.telegram_id == update.effective_user.id).first()
        lang = user.language if user else context.user_data.get('lang', 'en')

    rule_key = "buyer_rules" if target_role == "buyer" else "seller_rules"
    keyboard = [[InlineKeyboardButton(get_text(lang, "agree_btn"), callback_data="rules_agree")]]
    await query.edit_message_text(get_text(lang, rule_key), parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(keyboard))
    return AGREE_RULES

async def handle_rules_agreement(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    target_role = context.user_data.get('target_role')

    with db_transaction() as db:
        user = db.query(User).filter(User.telegram_id == update.effective_user.id).first()
        lang = user.language if user else context.user_data.get('lang', 'en')
        has_phone = user.phone if user else None

    await query.message.delete()

    if has_phone and target_role == 'seller':
        await context.bot.send_message(
            chat_id=query.message.chat_id,
            text=get_text(lang, "seller_bus_name"),
            reply_markup=ReplyKeyboardRemove()
        )
        return BUSINESS_NAME

    contact_btn = [[KeyboardButton(text=get_text(lang, "share_phone"), request_contact=True)]]
    reply_markup = ReplyKeyboardMarkup(contact_btn, resize_keyboard=True, one_time_keyboard=True)
    await context.bot.send_message(
        chat_id=query.message.chat_id,
        text=get_text(lang, "share_phone_prompt"),
        reply_markup=reply_markup
    )
    return SHARE_PHONE

async def process_contact(update: Update, context: ContextTypes.DEFAULT_TYPE):
    contact = update.message.contact
    lang = context.user_data.get('lang', 'en')

    if contact.user_id != update.effective_user.id:
        await update.message.reply_text(get_text(lang, "reject_forwarded_contact"))
        return SHARE_PHONE

    phone = contact.phone_number.replace("+", "")
    if not phone.startswith("251"):
        await update.message.reply_text("❌ Only Ethiopian phone numbers starting with '251' are accepted.")
        return SHARE_PHONE

    target_role = context.user_data.get('target_role')

    try:
        with db_transaction() as db:
            new_user = User(
                telegram_id=update.effective_user.id,
                username=update.effective_user.username,
                phone=phone,
                language=lang,
                role=target_role,
                status='active' if target_role == 'buyer' else 'pending'
            )
            db.add(new_user)
    except Exception as e:
        logger.error(f"process_contact user creation failed: {e}")
        await update.message.reply_text("❌ Registration error. Please try again.")
        return SHARE_PHONE

    await update.message.reply_text(get_text(lang, "enter_full_name"), reply_markup=ReplyKeyboardRemove())
    return FULL_NAME

async def process_full_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    full_name = update.message.text
    lang = context.user_data.get('lang', 'en')
    target_role = context.user_data.get('target_role')

    try:
        with db_transaction() as db:
            user = db.query(User).filter(User.telegram_id == update.effective_user.id).first()
            if user:
                user.full_name = full_name
    except Exception as e:
        logger.error(f"process_full_name failed: {e}")

    if target_role == 'buyer':
        await update.message.reply_text(get_text(lang, "reg_success_buyer"), reply_markup=get_buyer_home_keyboard(lang))
        return ConversationHandler.END
    else:
        await update.message.reply_text(get_text(lang, "seller_bus_name"), reply_markup=ReplyKeyboardRemove())
        return BUSINESS_NAME

async def seller_business_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['business_name'] = update.message.text
    lang = get_user_lang(update.effective_user.id)
    await update.message.reply_text(get_text(lang, "seller_loc"))
    return LOCATION

async def seller_location(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['location'] = update.message.text
    lang = get_user_lang(update.effective_user.id)
    await update.message.reply_text(get_text(lang, "seller_cat"))
    return CATEGORY

async def seller_category(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['category'] = update.message.text
    lang = get_user_lang(update.effective_user.id)
    await update.message.reply_text(get_text(lang, "seller_shop_num"))
    return SHOP_NUMBER

async def seller_shop_number(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['shop_number'] = update.message.text
    lang = get_user_lang(update.effective_user.id)

    # Step 1: Save to DB — if this fails, show error and stay in the step
    profile_data = {}
    user_name = None
    user_id = None
    try:
        with db_transaction() as db:
            user = db.query(User).filter(User.telegram_id == update.effective_user.id).first()
            profile = SellerProfile(
                user_id=user.id,
                business_name=context.user_data['business_name'],
                location=context.user_data['location'],
                category=context.user_data['category'],
                shop_number=context.user_data['shop_number']
            )
            db.add(profile)
            user.status = 'pending'
            db.flush()
            user_name = user.full_name
            user_id = user.id
            profile_data = {
                'business_name': profile.business_name,
                'shop_number': profile.shop_number,
                'category': profile.category,
                'location': profile.location,
                'phone': user.phone,
            }
    except Exception as e:
        logger.error(f"seller_shop_number DB save failed: {e}")
        await update.message.reply_text("❌ Registration error. Please try again.")
        return SHOP_NUMBER

    # Step 2: Notify seller — DB is already committed, flow continues regardless
    await update.message.reply_text(get_text(lang, "seller_app_submitted"), reply_markup=ReplyKeyboardRemove())

    # Step 3: Notify admin — best-effort, log failure but don't break the flow
    try:
        admin_kb = [
            [InlineKeyboardButton("Approve ✅", callback_data=f"adm_app_{user_id}"),
             InlineKeyboardButton("Reject ❌", callback_data=f"adm_rej_{user_id}")]
        ]
        admin_text = (
            f"🆕 *New Seller Request*\n\n"
            f"**Name:** {user_name}\n"
            f"**Business:** {profile_data['business_name']}\n"
            f"**Shop No:** {profile_data['shop_number']}\n"
            f"**Category:** {profile_data['category']}\n"
            f"**Location:** {profile_data['location']}\n"
            f"**Phone:** {profile_data['phone']}"
        )
        await context.bot.send_message(
            chat_id=ADMIN_TELEGRAM_ID,
            text=admin_text,
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup(admin_kb)
        )
    except Exception as e:
        logger.error(f"seller_shop_number admin notification failed (profile saved OK): {e}")

    return ConversationHandler.END

async def switch_mode(update: Update, context: ContextTypes.DEFAULT_TYPE):
    tg_id = update.effective_user.id

    try:
        lang = 'en'
        action = None
        with db_transaction() as db:
            user = db.query(User).filter(User.telegram_id == tg_id).first()
            if not user:
                return
            lang = user.language

            if user.role == 'buyer':
                profile = db.query(SellerProfile).filter(SellerProfile.user_id == user.id).first()
                if profile:
                    if user.status == 'active':
                    # Has an approved seller profile — switch to seller
                        user.role = 'seller'
                        action = 'to_seller'
                    elif user.status == 'pending':
                        # Profile exists but waiting for admin approval
                        action = 'pending_approval'
                else:
                    # No profile yet, or profile pending approval
                    action = 'need_profile'

            elif user.role == 'seller':
                if user.status == 'pending':
                    # Newly registered seller waiting for admin approval
                    # Don't switch — just remind them they're pending
                    action = 'pending_approval'
                else:
                    # Active seller switching back to buyer
                    user.role = 'buyer'
                    action = 'to_buyer'

        if action == 'to_seller':
            await update.message.reply_text(get_text(lang, "switched_seller"), reply_markup=get_seller_home_keyboard(lang))
        elif action == 'to_buyer':
            await update.message.reply_text(get_text(lang, "switched_buyer"), reply_markup=get_buyer_home_keyboard(lang))
        elif action == 'pending_approval':
            await update.message.reply_text(get_text(lang, "pending_admin"))
        elif action == 'need_profile':
            keyboard = [[InlineKeyboardButton(get_text(lang, "apply_seller_btn"), callback_data="role_seller")]]
            await update.message.reply_text(get_text(lang, "need_seller_acc"), reply_markup=InlineKeyboardMarkup(keyboard))
    except Exception as e:
        logger.error(f"switch_mode failed for user {tg_id}: {e}")
        await update.message.reply_text("❌ Error switching mode. Please try again.")