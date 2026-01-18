import os
import random
import asyncio
import re
import logging
import httpx
from bs4 import BeautifulSoup
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.context import FSMContext
from aiogram.fsm.storage.memory import MemoryStorage
from dotenv import load_dotenv

# تحميل الإعدادات
load_dotenv()
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(message)s')
logger = logging.getLogger(__name__)

TOKEN = os.getenv("BOT_TOKEN")

# ------------------------------
# منطق IGResetMaster المعدل للبوت
# ------------------------------
class IGResetMaster:
    def __init__(self, email):
        self.email = email.lower().strip()
        self.base_url = "https://www.instagram.com"
        self.user_agents = [
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Mozilla/5.0 (iPhone; CPU iPhone OS 17_2 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.2 Mobile/15E148 Safari/604.1"
        ]

    async def attempt(self, proxy=None):
        proxy_config = {"http://": f"http://{proxy}", "https://": f"http://{proxy}"} if proxy else None
        
        async with httpx.AsyncClient(proxies=proxy_config, timeout=20.0, follow_redirects=True) as client:
            ua = random.choice(self.user_agents)
            client.headers.update({'User-Agent': ua, 'Accept-Language': 'en-US,en;q=0.9'})

            try:
                # خطوة 1: بناء الجلسة
                await client.get(f"{self.base_url}/")
                
                # خطوة 2: صفحة الريسيت والتوكن
                res = await client.get(f"{self.base_url}/accounts/password/reset/")
                
                # استخراج التوكن
                token = client.cookies.get('csrftoken')
                if not token:
                    match = re.search(r'"csrf_token":"([^"]+)"', res.text)
                    token = match.group(1) if match else None
                
                if not token:
                    return False, "مشكلة في التوكن (البروكسي محظور)"

                # خطوة 3: الطلب
                headers = {
                    'X-CSRFToken': token,
                    'X-Requested-With': 'XMLHttpRequest',
                    'Referer': f'{self.base_url}/accounts/password/reset/',
                    'Content-Type': 'application/x-www-form-urlencoded'
                }
                data = {'email_or_username': self.email, 'csrfmiddlewaretoken': token}
                
                response = await client.post(
                    f"{self.base_url}/accounts/account_recovery_send_ajax/",
                    data=data, headers=headers
                )
                
                if response.status_code == 200:
                    out = response.json()
                    if out.get('status') == 'ok':
                        return True, "✅ تم النجاح! افحص البريد."
                    return False, out.get('message', 'تم الرفض')
                elif response.status_code == 429:
                    return False, "⏳ ضغط كبير (Rate Limit)"
                return False, f"خطأ خادم: {response.status_code}"

            except Exception as e:
                return False, f"خطأ تقني: {str(e)}"

# ------------------------------
# إعدادات البوت
# ------------------------------
class Form(StatesGroup):
    waiting_for_email = State()
    waiting_for_attempts = State()

storage = MemoryStorage()
bot = Bot(token=TOKEN)
dp = Dispatcher(storage=storage)

# الكيبورد
def get_main_kb():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔐 بدء الإرسال", callback_data="start_reset")],
        [InlineKeyboardButton(text="ℹ️ شرح الاستخدام", callback_data="help")]
    ])

@dp.message(Command("start"))
async def start(message: types.Message):
    await message.answer("🤖 أهلاً بك في بوت IG Reset المطور.\nاضغط على الزر أدناه للبدء:", reply_markup=get_main_kb())

@dp.callback_query(F.data == "start_reset")
async def ask_email(callback: CallbackQuery, state: FSMContext):
    await callback.message.answer("📧 أرسل البريد الإلكتروني المستهدف:")
    await state.set_state(Form.waiting_for_email)

@dp.message(Form.waiting_for_email)
async def process_email(message: types.Message, state: FSMContext):
    await state.update_data(email=message.text)
    await message.answer("🔢 كم عدد المحاولات المطلوبة؟ (1-10):")
    await state.set_state(Form.waiting_for_attempts)

@dp.message(Form.waiting_for_attempts)
async def process_run(message: types.Message, state: FSMContext):
    if not message.text.isdigit():
        return await message.answer("❌ أرسل رقماً فقط!")
    
    attempts = int(message.text)
    data = await state.get_data()
    email = data['email']
    await state.clear()

    status_msg = await message.answer(f"🚀 جاري العمل على {email}...")
    master = IGResetMaster(email)

    for i in range(attempts):
        await status_msg.edit_text(f"⏳ محاولة {i+1} من {attempts}...")
        
        success, result = await master.attempt()
        
        if success:
            await message.answer(f"🎯 **نجاح!**\nالبريد: {email}\nالنتيجة: {result}")
            break
        else:
            await message.answer(f"❌ **فشل في المحاولة {i+1}:**\n{result}")
            if i < attempts - 1:
                wait = random.randint(30, 60)
                await asyncio.sleep(wait)

    await message.answer("🏁 انتهت جميع العمليات.", reply_markup=get_main_kb())

# ------------------------------
# تشغيل
# ------------------------------
async def main():
    logger.info("Bot is running...")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
