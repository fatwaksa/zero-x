import os
import re
import random
import logging
import asyncio
import requests
from bs4 import BeautifulSoup
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
from aiogram.types import Message
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup

# --- الإعدادات --- جلب التوكن من Railway
TOKEN = os.getenv("BOT_TOKEN")

# --- كلاس منطق الإرسال (مبني على كودك الأصلي) ---
class IGResetMaster:
    def __init__(self, email):
        self.email = email.lower().strip()
        self.base_url = "https://www.instagram.com"
        self.user_agents = [
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Mozilla/5.0 (iPhone; CPU iPhone OS 17_2 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.2 Mobile/15E148 Safari/604.1",
            "Mozilla/5.0 (Linux; Android 10; SM-G981B) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/80.0.3987.162 Mobile Safari/537.36"
        ]

    def _extract_token(self, session, html):
        # محاكاة المنطق الخاص بك لاستخراج التوكن بأمان
        token = session.cookies.get('csrftoken')
        if token: return token
        match = re.search(r'"csrf_token":"([^"]+)"', html)
        if match: return match.group(1)
        soup = BeautifulSoup(html, 'html.parser')
        meta = soup.find('input', {'name': 'csrfmiddlewaretoken'})
        return meta.get('value') if meta else None

    async def run_attempt(self):
        # استخدام asyncio.to_thread لتجنب تجميد البوت أثناء طلبات الـ HTTP
        return await asyncio.to_thread(self._execute)

    def _execute(self):
        session = requests.Session()
        ua = random.choice(self.user_agents)
        session.headers.update({'User-Agent': ua, 'Accept-Language': 'en-US,en;q=0.9'})

        try:
            # الخطوة 1: بناء الجلسة
            session.get(f"{self.base_url}/", timeout=15)
            # الخطوة 2: صفحة الريسيت
            res = session.get(f"{self.base_url}/accounts/password/reset/", timeout=15)
            token = self._extract_token(session, res.text)
            
            if not token:
                return False, "مشكلة في توكن الأمان (IP Blocked)"

            # الخطوة 3: إرسال طلب الريسيت
            headers = {
                'X-CSRFToken': token,
                'X-Requested-With': 'XMLHttpRequest',
                'Referer': f'{self.base_url}/accounts/password/reset/',
                'Content-Type': 'application/x-www-form-urlencoded'
            }
            data = {'email_or_username': self.email, 'csrfmiddlewaretoken': token}
            
            response = session.post(
                f"{self.base_url}/accounts/account_recovery_send_ajax/", 
                data=data, headers=headers, timeout=15
            )
            
            if response.status_code == 200:
                out = response.json()
                if out.get('status') == 'ok':
                    return True, "Success"
                return False, out.get('message', 'Rejected')
            elif response.status_code == 429:
                return False, "Rate Limit (429)"
            return False, f"Server Error: {response.status_code}"
        except Exception as e:
            return False, f"خطأ في الاتصال: {str(e)[:30]}"

# --- إعدادات حالات البوت ---
class Form(StatesGroup):
    waiting_for_email = State()

bot = Bot(token=TOKEN)
dp = Dispatcher()

# --- الترحيب المخصص ---
@dp.message(Command("start"))
async def start_cmd(message: Message, state: FSMContext):
    user_name = message.from_user.first_name
    welcome_text = (
        f"أهلاً بك {user_name} في بوت زيرو إكس\n"
        "لارسال رست انستقرام 🫆.\n\n"
        "ضع ايميل حسابك في الانستقرام 👨🏻‍💻."
    )
    await message.answer(welcome_text)
    await state.set_state(Form.waiting_for_email)

# --- معالجة الإيميل ---
@dp.message(Form.waiting_for_email)
async def process_email(message: Message, state: FSMContext):
    email = message.text.strip()
    status_msg = await message.answer("⏳ جاري محاولة إرسال الرست...")

    # تشغيل المنطق
    master = IGResetMaster(email)
    success, result = await master.run_attempt()
    
    await state.clear() # إنهاء الحالة للبدء من جديد عند الرغبة

    if success:
        await status_msg.edit_text(
            f"✅ **تم الارسال الفعلي!**\n\n"
            f"👤 الحساب: `{email}`\n"
            f"📥 تفقد بريدك الآن (الوارد أو المزعج)."
        )
    else:
        # معالجة الأخطاء
        error_msg = "حدث خطأ غير متوقع."
        if "429" in result:
            error_msg = "تم حظر الآي بي مؤقتاً (429). انتظر 10 دقائق وحاول مجدداً."
        elif "Rejected" in result:
            error_msg = "رفض إنستقرام الطلب، تأكد من صحة اليوزر/الإيميل."
        else:
            error_msg = result

        await status_msg.edit_text(f"❌ **توجد مشكلة في الإرسال**\n\nالسبب: {error_msg}")

# --- تشغيل البوت ---
async def main():
    logging.basicConfig(level=logging.INFO)
    print("🚀 بوت زيرو إكس يعمل الآن...")
    await dp.start_polling(bot)

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        pass
