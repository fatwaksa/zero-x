import os
import random
import asyncio
import re
import logging
from datetime import datetime
from typing import Dict, List, Optional

import httpx  # مكتبة Async قوية للطلبات
from bs4 import BeautifulSoup
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.context import FSMContext
from aiogram.fsm.storage.memory import MemoryStorage
from dotenv import load_dotenv

# تحميل متغيرات البيئة
load_dotenv()

# إعدادات التسجيل (Logging) - مهمة جداً في Railway لمراقبة الأخطاء
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# جلب التوكن من متغيرات البيئة
TOKEN = os.getenv("BOT_TOKEN")

# ------------------------------
# FSM لإدارة الحالة
# ------------------------------
class Form(StatesGroup):
    waiting_for_email = State()
    waiting_for_attempts = State()

# ------------------------------
# إدارة بيانات المستخدمين
# ------------------------------
class SessionManager:
    def __init__(self):
        self.users: Dict[int, Dict] = {}

    def start_session(self, user_id: int, email: str, total: int):
        self.users[user_id] = {
            'email': email,
            'total': total,
            'done': 0,
            'success': 0,
            'start': datetime.now()
        }

    def update(self, user_id: int, is_success: bool):
        if user_id in self.users:
            self.users[user_id]['done'] += 1
            if is_success:
                self.users[user_id]['success'] += 1

    def get(self, user_id: int):
        return self.users.get(user_id)

session_manager = SessionManager()

# ------------------------------
# محرك إعادة التعيين (Async Engine)
# ------------------------------
class IGResetEngine:
    def __init__(self, email: str):
        self.email = email.lower().strip()
        self.base_url = "https://www.instagram.com"
        self.user_agents = [
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/118.0.0.0 Safari/537.36",
            "Mozilla/5.0 (iPhone; CPU iPhone OS 17_1 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.1 Mobile/15E148 Safari/604.1"
        ]

    async def send_request(self) -> tuple:
        """تنفيذ طلب إعادة التعيين بشكل Async"""
        # استخدام AsyncClient بدلاً من requests.Session
        async with httpx.AsyncClient(timeout=20.0, follow_redirects=True) as client:
            ua = random.choice(self.user_agents)
            client.headers.update({
                'User-Agent': ua,
                'Accept-Language': 'en-US,en;q=0.9',
                'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
            })

            try:
                # 1. الدخول لصفحة البداية لجلب الكوكيز
                await client.get(f"{self.base_url}/")
                
                # 2. الدخول لصفحة الريسيت
                res = await client.get(f"{self.base_url}/accounts/password/reset/")
                csrf = client.cookies.get('csrftoken')
                
                if not csrf:
                    # محاولة استخراج التوكن من النص إذا لم يظهر في الكوكيز
                    match = re.search(r'"csrf_token":"([^"]+)"', res.text)
                    csrf = match.group(1) if match else None

                if not csrf:
                    return False, "⚠️ فشل جلب توكن الأمان (قد يكون الـ IP محظور)"

                # 3. إرسال الطلب الفعلي
                post_headers = {
                    'X-CSRFToken': csrf,
                    'X-Requested-With': 'XMLHttpRequest',
                    'Referer': f'{self.base_url}/accounts/password/reset/',
                    'Content-Type': 'application/x-www-form-urlencoded'
                }
                data = {
                    'email_or_username': self.email,
                    'csrfmiddlewaretoken': csrf
                }
                
                response = await client.post(
                    f"{self.base_url}/accounts/account_recovery_send_ajax/",
                    data=data,
                    headers=post_headers
                )
                
                if response.status_code == 200:
                    result = response.json()
                    if result.get('status') == 'ok':
                        return True, "✅ تم إرسال الرابط بنجاح!"
                    return False, f"❌ رد إنستجرام: {result.get('message', 'فشل غير معروف')}"
                
                elif response.status_code == 429:
                    return False, "⏳ حظر مؤقت (Rate Limit). انتظر قليلاً."
                else:
                    return False, f"🚫 خطأ خادم: {response.status_code}"

            except Exception as e:
                logger.error(f"Error for {self.email}: {e}")
                return False, f"⚠️ خطأ اتصال: {type(e).__name__}"

# ------------------------------
# واجهة البوت (Keyboards)
# ------------------------------
def main_menu():
    buttons = [
        [InlineKeyboardButton(text="🔐 بدء عملية ريسيت", callback_data="start_reset")],
        [InlineKeyboardButton(text="📊 الإحصائيات", callback_data="stats"),
         InlineKeyboardButton(text="🆘 مساعدة", callback_data="help")]
    ]
    return InlineKeyboardMarkup(inline_keyboard=buttons)

def cancel_btn():
    return InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="❌ إلغاء العملية", callback_data="cancel")]])

# ------------------------------
# handlers الأوامر
# ------------------------------
storage = MemoryStorage()
bot = Bot(token=TOKEN) if TOKEN else None
dp = Dispatcher(storage=storage)

@dp.message(Command("start"))
async def cmd_start(message: types.Message):
    await message.answer(
        f"🤖 مرحباً {message.from_user.first_name}!\n"
        "أنا بوت إعادة تعيين حسابات إنستجرام المطور.\n"
        "أستخدم تقنيات Async لضمان السرعة والقوة.",
        reply_markup=main_menu()
    )

@dp.callback_query(F.data == "start_reset")
async def start_flow(callback: CallbackQuery, state: FSMContext):
    await callback.message.edit_text("📧 أرسل الآن البريد الإلكتروني المستهدف:", reply_markup=cancel_btn())
    await state.set_state(Form.waiting_for_email)

@dp.message(Form.waiting_for_email)
async def get_email(message: types.Message, state: FSMContext):
    email = message.text.strip()
    if "@" not in email:
        return await message.answer("❌ عذراً، هذا البريد غير صالح. أعد الإرسال:")
    
    await state.update_data(email=email)
    await message.answer(f"✅ تم حفظ: {email}\n🔢 كم محاولة تريد؟ (1-10):", reply_markup=cancel_btn())
    await state.set_state(Form.waiting_for_attempts)

@dp.message(Form.waiting_for_attempts)
async def run_process(message: types.Message, state: FSMContext):
    if not message.text.isdigit():
        return await message.answer("❌ يرجى إرسال رقم فقط.")
    
    attempts = int(message.text)
    if not (1 <= attempts <= 10):
        return await message.answer("❌ يرجى اختيار رقم بين 1 و 10.")
    
    user_data = await state.get_data()
    email = user_data['email']
    await state.clear()
    
    msg = await message.answer(f"🚀 جاري بدء العمل على `{email}`...")
    session_manager.start_session(message.from_user.id, email, attempts)
    
    engine = IGResetEngine(email)
    
    for i in range(1, attempts + 1):
        await msg.edit_text(f"⏳ جاري تنفيذ المحاولة رقم ({i}/{attempts})...")
        
        success, response_text = await engine.send_request()
        session_manager.update(message.from_user.id, success)
        
        if success:
            await message.answer(f"🎯 **المحاولة {i}:** {response_text}")
            # إذا نجحت محاولة واحدة، غالباً لا نحتاج لإكمال الباقي فوراً لتجنب السبام
            break 
        else:
            await message.answer(f"⚠️ **المحاولة {i}:** {response_text}")
        
        # انتظار عشوائي بين المحاولات لتجنب الحظر
        if i < attempts:
            wait_time = random.randint(15, 40)
            await asyncio.sleep(wait_time)

    await message.answer("✅ اكتملت المهمة!", reply_markup=main_menu())

@dp.callback_query(F.data == "cancel")
async def cancel_action(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    await callback.message.edit_text("✅ تم إلغاء العملية الجارية.", reply_markup=main_menu())

@dp.callback_query(F.data == "help")
async def help_action(callback: CallbackQuery):
    help_text = (
        "❓ **كيفية الاستخدام:**\n"
        "1️⃣ اضغط على بدء إعادة تعيين.\n"
        "2️⃣ أرسل البريد الإلكتروني المراد استهدافه.\n"
        "3️⃣ حدد عدد المحاولات.\n\n"
        "⚠️ البوت مصمم لأغراض استرجاع الحسابات الشخصية فقط."
    )
    await callback.message.answer(help_text, reply_markup=main_menu())

@dp.callback_query(F.data == "stats")
async def stats_action(callback: CallbackQuery):
    data = session_manager.get(callback.from_user.id)
    if not data:
        return await callback.answer("❌ لا توجد بيانات سابقة لك.")
    
    stat_msg = (
        f"📊 **إحصائياتك الأخيرة:**\n"
        f"📧 الهدف: `{data['email']}`\n"
        f"✅ محاولات ناجحة: {data['success']}\n"
        f"🔄 إجمالي المحاولات: {data['done']}/{data['total']}\n"
        f"⏰ البدء: {data['start'].strftime('%H:%M:%S')}"
    )
    await callback.message.answer(stat_msg, reply_markup=main_menu())

# ------------------------------
# التشغيل النهائي
# ------------------------------
async def main():
    if not TOKEN:
        logger.error("BOT_TOKEN is missing! Please set it in Railway variables.")
        return
    logger.info("Bot is starting...")
    await dp.start_polling(bot)

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        logger.info("Bot stopped.")
