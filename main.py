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

# --- الإعدادات ---
TOKEN = os.getenv("BOT_TOKEN")

# --- محرك الريسيت القوي (من كودك مباشرة) ---
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
        token = session.cookies.get('csrftoken')
        if token: return token
        match = re.search(r'"csrf_token":"([^"]+)"', html)
        if match: return match.group(1)
        soup = BeautifulSoup(html, 'html.parser')
        meta = soup.find('input', {'name': 'csrfmiddlewaretoken'})
        return meta.get('value') if meta else None

    async def attempt(self):
        # تشغيل طلب الـ requests في خيط (thread) منفصل لمنع تجميد البوت
        return await asyncio.to_thread(self._sync_attempt)

    def _sync_attempt(self):
        session = requests.Session()
        # ملاحظة: إذا كان لديك بروكسيات ضعها هنا في قائمة
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

            # الخطوة 3: الإرسال
            headers = {
                'X-CSRFToken': token,
                'X-Requested-With': 'XMLHttpRequest',
                'Referer': f'{self.base_url}/accounts/password/reset/',
                'Content-Type': 'application/x-www-form-urlencoded'
            }
            data = {'email_or_username': self.email, 'csrfmiddlewaretoken': token}
            
            response = session.post(f"{self.base_url}/accounts/account_recovery_send_ajax/", 
                                   data=data, headers=headers, timeout=15)
            
            if response.status_code == 200:
                out = response.json()
                if out.get('status') == 'ok':
                    return True, "Success"
                return False, out.get('message', 'Rejected')
            elif response.status_code == 429:
                return False, "Rate Limit (429)"
            return False, f"Server Error: {response.status_code}"
        except Exception as e:
            return False, f"Connection Error: {str(e)[:30]}"

# --- نظام البوت ---
class ResetStates(StatesGroup):
    waiting_for_email = State()

bot = Bot(token=TOKEN)
dp = Dispatcher()

@dp.message(Command("start"))
async def start_cmd(message: Message, state: FSMContext):
    user_name = message.from_user.first_name
    await message.answer(f"اهلاً بك {user_name} في بوت زيرو إكس\nلارسال رست انستقرام 🫆.\n\nضع ايميل حسابك في الانستقرام 👨🏻‍💻.")
    await state.set_state(ResetStates.waiting_for_email)

@dp.message(ResetStates.waiting_for_email)
async def process_reset(message: Message, state: FSMContext):
    email = message.text.strip()
    status_msg = await message.answer("⏳ جاري معالجة الطلب، يرجى الانتظار...")
    
    # تنفيذ المحاولة
    master = IGResetMaster(email)
    success, msg = await master.attempt()
    
    await state.clear()

    if success:
        await status_msg.edit_text(f"✅ **تم الارسال الفعلي!**\n\n👤 الحساب: {email}\n📩 تم إرسال رابط إعادة التعيين بنجاح.")
    else:
        # إذا فشل بسبب 429 أو غيره، نخبر المستخدم بالسبب بوضوح
        error_map = {
            "Rate Limit (429)": "السيرفر مضغوط حالياً (429). انتظر 10 دقائق وحاول مجدداً.",
            "Success": "تم الإرسال بنجاح!"
        }
        final_error = error_map.get(msg, msg)
        await status_msg.edit_text(f"❌ **توجد مشكلة في الإرسال**\n\nالسبب: {final_error}")

async def main():
    logging.basicConfig(level=logging.INFO)
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
