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

# إعدادات التسجيل والتحميل
load_dotenv()
logging.basicConfig(level=logging.ERROR) # تقليل التسجيل لزيادة الأداء
TOKEN = os.getenv("BOT_TOKEN")

class IGResetMaster:
    def __init__(self, target):
        self.target = target.lower().strip()
        self.base_url = "https://www.instagram.com"

    def get_random_proxy(self):
        try:
            with open("proxies.txt", "r") as f:
                proxies = [line.strip() for line in f if line.strip()]
            return random.choice(proxies) if proxies else None
        except FileNotFoundError:
            return None

    async def attempt(self):
        proxy = self.get_random_proxy()
        # تنسيق البروكسي ليدعم النوعين http و https
        proxies = {"http://": f"http://{proxy}", "https://": f"http://{proxy}"} if proxy else None
        
        # استخدام مهلة زمنية صارمة جداً (5 ثواني) لمنع تعليق البوت
        async with httpx.AsyncClient(proxies=proxies, timeout=5.0, follow_redirects=True) as client:
            client.headers.update({
                'User-Agent': "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                'Accept-Language': 'en-US,en;q=0.9',
                'X-Requested-With': 'XMLHttpRequest',
                'Referer': f'{self.base_url}/accounts/password/reset/'
            })

            try:
                # 1. جلب التوكن والكوكيز (الخطوة الأهم)
                res = await client.get(f"{self.base_url}/accounts/password/reset/")
                csrf = client.cookies.get('csrftoken')
                
                # إذا لم يظهر في الكوكيز، نبحث عنه في الصفحة
                if not csrf:
                    match = re.search(r'"csrf_token":"([^"]+)"', res.text)
                    csrf = match.group(1) if match else None

                if not csrf:
                    return False, "بروكسي محظور (No CSRF)"

                # 2. إرسال طلب الريسيت الفعلي
                client.headers.update({'X-CSRFToken': csrf})
                data = {
                    'email_or_username': self.target,
                    'csrfmiddlewaretoken': csrf
                }
                
                # استخدام رابط الـ AJAX الرسمي والأسرع
                post_url = f"{self.base_url}/accounts/account_recovery_send_ajax/"
                response = await client.post(post_url, data=data)
                
                if response.status_code == 200:
                    resp_json = response.json()
                    if resp_json.get('status') == 'ok':
                        return True, "✅ تم إرسال الرابط بنجاح"
                    return False, f"❌ رفض: {resp_json.get('message', 'خطأ غير معروف')}"
                
                return False, f"⚠️ كود {response.status_code}"

            except Exception:
                return False, "🔌 البروكسي ميت أو بطيء"

# --- إعدادات البوت ---
class Form(StatesGroup):
    target = State()
    count = State()

bot = Bot(token=TOKEN)
dp = Dispatcher(storage=MemoryStorage())

@dp.message(Command("start"))
async def start(message: types.Message):
    kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="🚀 ابدأ الإرسال", callback_data="run")]])
    await message.answer("🛠 **IG Master V3**\nأداة إعادة تعيين إنستغرام الاحترافية.", reply_markup=kb)

@dp.callback_query(F.data == "run")
async def ask_target(callback: CallbackQuery, state: FSMContext):
    await callback.message.answer("🎯 أدخل اليوزر أو البريد:")
    await state.set_state(Form.target)

@dp.message(Form.target)
async def get_target(message: types.Message, state: FSMContext):
    await state.update_data(target=message.text)
    await message.answer("🔢 عدد المحاولات (مثلاً 5):")
    await state.set_state(Form.count)

@dp.message(Form.count)
async def process_run(message: types.Message, state: FSMContext):
    if not message.text.isdigit(): return
    
    attempts = int(message.text)
    data = await state.get_data()
    target = data['target']
    await state.clear()

    # لتجنب حظر تليغرام، لا نستخدم edit_text بكثرة
    log_msg = await message.answer(f"⏳ جاري بدء العملية لـ {target}...")
    master = IGResetMaster(target)

    for i in range(attempts):
        # تحديث الحالة كل محاولتين فقط لتقليل الضغط على تليغرام
        if i % 2 == 0:
            try: await log_msg.edit_text(f"🚀 معالجة المحاولة {i+1} من {attempts}...")
            except: pass

        success, result = await master.attempt()
        
        if success:
            await message.answer(f"✨ **نجاح!**\nالهدف: {target}\nالنتيجة: {result}")
            break
        else:
            logging.info(f"فشل محاولة {i+1}: {result}")
            # انتظار بسيط جداً للتبديل للبروكسي التالي
            await asyncio.sleep(0.3)

    await message.answer("🏁 انتهت جميع المحاولات.")

async def main():
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
