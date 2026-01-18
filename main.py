import os
import random
import asyncio
import re
import logging
import httpx
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.context import FSMContext
from aiogram.fsm.storage.memory import MemoryStorage
from dotenv import load_dotenv

load_dotenv()
logging.basicConfig(level=logging.INFO)

TOKEN = os.getenv("BOT_TOKEN")

# ------------------------------
# نظام جلب البروكسيات من الملف
# ------------------------------
def get_random_proxy():
    try:
        with open("proxies.txt", "r") as f:
            proxies = f.read().splitlines()
        if proxies:
            return random.choice(proxies)
    except FileNotFoundError:
        return None
    return None

class IGResetMaster:
    def __init__(self, email):
        self.email = email.lower().strip()
        self.base_url = "https://www.instagram.com"

    async def attempt(self):
        proxy = get_random_proxy()
        proxy_config = {"http://": f"http://{proxy}", "https://": f"http://{proxy}"} if proxy else None
        
        # استخدام مهلة زمنية (Timeout) قصيرة لعدم التعليق
        async with httpx.AsyncClient(proxies=proxy_config, timeout=10.0, follow_redirects=True) as client:
            ua = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36"
            client.headers.update({'User-Agent': ua, 'Accept-Language': 'en-US,en;q=0.9'})

            try:
                # الخطوة الأولى: الحصول على صفحة الريسيت والتوكن بسرعة
                res = await client.get(f"{self.base_url}/accounts/password/reset/")
                token = client.cookies.get('csrftoken')
                
                if not token:
                    # محاولة استخراج التوكن من النص إذا لم يوجد في الكوكيز
                    match = re.search(r'csrf_token\\":\\"([^\\"]+)\\"', res.text)
                    token = match.group(1) if match else None

                if not token:
                    return False, "بروكسي ضعيف (لم يستخرج التوكن)"

                headers = {
                    'X-CSRFToken': token,
                    'X-Requested-With': 'XMLHttpRequest',
                    'Referer': f'{self.base_url}/accounts/password/reset/',
                    'Content-Type': 'application/x-www-form-urlencoded'
                }
                data = {'email_or_username': self.email, 'csrfmiddlewaretoken': token}
                
                # إرسال الطلب الفعلي
                response = await client.post(
                    f"{self.base_url}/api/v1/accounts/send_password_reset_email/", # المسار الأحدث للـ API
                    data=data, headers=headers
                )
                
                if response.status_code == 200:
                    return True, "✅ تم الإرسال بنجاح!"
                elif response.status_code == 429:
                    return False, "⏳ حظر مؤقت للـ IP (Rate Limit)"
                else:
                    return False, f"فشل (Status: {response.status_code})"

            except Exception as e:
                return False, "خطأ في الاتصال بالبروكسي"

# ------------------------------
# منطق البوت المعدل للسرعة
# ------------------------------
class Form(StatesGroup):
    waiting_for_email = State()
    waiting_for_attempts = State()

storage = MemoryStorage()
bot = Bot(token=TOKEN)
dp = Dispatcher(storage=storage)

@dp.message(Command("start"))
async def start(message: types.Message):
    await message.answer("🚀 **IG Reset Master Pro**\nنظام الإرسال السريع بالبروكسيات جاهز.", 
                         reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                             [InlineKeyboardButton(text="🔐 بدء العملية", callback_data="start_reset")]
                         ]))

@dp.callback_query(F.data == "start_reset")
async def ask_email(callback: CallbackQuery, state: FSMContext):
    await callback.message.answer("📧 أرسل البريد المستهدف:")
    await state.set_state(Form.waiting_for_email)

@dp.message(Form.waiting_for_email)
async def process_email(message: types.Message, state: FSMContext):
    await state.update_data(email=message.text)
    await message.answer("🔢 عدد المحاولات (السرعة تعتمد على البروكسيات):")
    await state.set_state(Form.waiting_for_attempts)

@dp.message(Form.waiting_for_attempts)
async def process_run(message: types.Message, state: FSMContext):
    if not message.text.isdigit(): return
    
    attempts = int(message.text)
    data = await state.get_data()
    email = data['email']
    await state.clear()

    status_msg = await message.answer(f"🔎 جاري فحص الاتصال لـ {email}...")
    master = IGResetMaster(email)

    success_count = 0
    for i in range(attempts):
        await status_msg.edit_text(f"🚀 محاولة رقم {i+1} جارية الآن...")
        
        # تنفيذ المحاولة
        success, result = await master.attempt()
        
        if success:
            await message.answer(f"🎯 **نجاح باهر!**\nالنتيجة: {result}")
            success_count += 1
            break # توقف عند النجاح
        else:
            # إذا فشل البروكسي، لا ننتظر طويلاً، ننتقل للذي يليه فوراً
            await message.answer(f"⚠️ محاولة {i+1} فشلت: {result}\nجاري التبديل لبروكسي آخر...")
            await asyncio.sleep(1) # وقت قصير جداً للتبديل

    await message.answer(f"🏁 العملية انتهت.\nنجاح: {success_count}\nفشل: {attempts - success_count}")

async def main():
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
