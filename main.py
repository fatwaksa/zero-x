import os
import random
import time
import asyncio
import requests
import re
from bs4 import BeautifulSoup
from aiogram import Bot, Dispatcher, types
from aiogram.filters import Command
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.context import FSMContext

TOKEN = os.getenv("BOT_TOKEN")  # ضع التوكن هنا

# ------------------------------
# FSM لإدارة الحالة
# ------------------------------
class Form(StatesGroup):
    email = State()

# ------------------------------
# نسخة البوت من IGResetMaster
# ------------------------------
class IGResetMaster:
    def __init__(self, email, proxies=None):
        self.email = email.lower().strip()
        self.proxies = proxies or []
        self.base_url = "https://www.instagram.com"
        self.user_agents = [
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Mozilla/5.0 (iPhone; CPU iPhone OS 17_2 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.2 Mobile/15E148 Safari/604.1",
            "Mozilla/5.0 (Linux; Android 10; SM-G981B) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/80.0.3987.162 Mobile Safari/537.36"
        ]

    def _get_random_proxy(self):
        if not self.proxies:
            return None
        p = random.choice(self.proxies)
        return {"http": f"http://{p}", "https": f"http://{p}"}

    def _extract_token(self, session, html):
        token = session.cookies.get('csrftoken')
        if token: return token
        match = re.search(r'"csrf_token":"([^"]+)"', html)
        if match: return match.group(1)
        soup = BeautifulSoup(html, 'html.parser')
        meta = soup.find('input', {'name': 'csrfmiddlewaretoken'})
        return meta.get('value') if meta else None

    def attempt(self):
        session = requests.Session()
        proxy = self._get_random_proxy()
        if proxy: session.proxies = proxy
        ua = random.choice(self.user_agents)
        session.headers.update({'User-Agent': ua, 'Accept-Language': 'en-US,en;q=0.9'})

        try:
            session.get(f"{self.base_url}/", timeout=15)
            res = session.get(f"{self.base_url}/accounts/password/reset/", timeout=15)
            token = self._extract_token(session, res.text)
            if not token:
                return False, "Token Error (Proxy Blocked?)"

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
                    return True, "✅ تم الإرسال بنجاح! تحقق من بريدك."
                return False, out.get('message', 'رفض الطلب')
            elif response.status_code == 429:
                return False, "❌ حظر مؤقت: الكثير من الطلبات"
            return False, f"Server Error: {response.status_code}"

        except Exception as e:
            return False, str(e)

# ------------------------------
# بوت Aiogram
# ------------------------------
bot = Bot(token=TOKEN)
dp = Dispatcher()

@dp.message(Command("start"))
async def start_cmd(msg: types.Message, state: FSMContext):
    await msg.answer("🚀 أهلاً بك! أدخل بريد الحساب لإعادة التعيين:")
    await state.set_state(Form.email)

@dp.message(Form.email)
async def handle_email(msg: types.Message, state: FSMContext):
    email = msg.text.strip()
    await msg.answer(f"⏳ جاري محاولة إعادة التعيين للبريد: {email}")

    master = IGResetMaster(email)
    success, result = await asyncio.to_thread(master.attempt)

    if success:
        await msg.answer(f"✅ تم الإرسال بنجاح للبريد: {email}")
    else:
        await msg.answer(f"❌ فشل الإرسال\nالسبب: {result}\n💡 حاول لاحقاً أو استخدم بروكسي")

    await state.clear()

# ------------------------------
# تشغيل البوت
# ------------------------------
async def main():
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
