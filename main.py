import os
import json
import asyncio
import random
import requests
import re
from datetime import datetime, timedelta
from bs4 import BeautifulSoup
from aiogram import Bot, Dispatcher
from aiogram.filters import Command
from aiogram.types import Message
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup

# --- الإعدادات ---
TOKEN = os.getenv("BOT_TOKEN")

# --- نظام إدارة المحاولات ---
class RateLimiter:
    def __init__(self, filename="limits.json"):
        self.filename = filename
        self.max_attempts = 4
        self.reset_hours = 24
        self.data = self._load_data()

    def _load_data(self):
        if os.path.exists(self.filename):
            try:
                with open(self.filename, 'r') as f:
                    return json.load(f)
            except:
                return {}
        return {}

    def _save_data(self):
        with open(self.filename, 'w') as f:
            json.dump(self.data, f)

    def check_user(self, user_id):
        user_id = str(user_id)
        now = datetime.now()
        if user_id not in self.data:
            self.data[user_id] = {
                "count": 0,
                "reset_time": (now + timedelta(hours=self.reset_hours)).isoformat()
            }
            self._save_data()
            return True, self.max_attempts
        user_data = self.data[user_id]
        reset_time = datetime.fromisoformat(user_data["reset_time"])
        if now > reset_time:
            self.data[user_id] = {
                "count": 0,
                "reset_time": (now + timedelta(hours=self.reset_hours)).isoformat()
            }
            self._save_data()
            return True, self.max_attempts
        if user_data["count"] < self.max_attempts:
            return True, self.max_attempts - user_data["count"]
        return False, reset_time.strftime("%Y-%m-%d %H:%M")

    def increment_usage(self, user_id):
        user_id = str(user_id)
        if user_id in self.data:
            self.data[user_id]["count"] += 1
            self._save_data()

# --- كلاس إعادة تعيين Instagram ---
class IGResetMaster:
    def __init__(self, email, proxy_file="proxies.txt"):
        self.email = email.lower().strip()
        self.proxy_file = proxy_file
        self.proxies = self._load_proxies()
        self.base_url = "https://www.instagram.com"
        self.user_agents = [
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Mozilla/5.0 (iPhone; CPU iPhone OS 17_2 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.2 Mobile/15E148 Safari/604.1",
            "Mozilla/5.0 (Linux; Android 10; SM-G981B) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/80.0.3987.162 Mobile Safari/537.36"
        ]

    def _load_proxies(self):
        if os.path.exists(self.proxy_file):
            with open(self.proxy_file, "r") as f:
                return [line.strip() for line in f if line.strip()]
        return []

    def _get_random_proxy(self):
        if not self.proxies:
            return None
        p = random.choice(self.proxies)
        return {"http": f"http://{p}", "https": f"http://{p}"}

    def _extract_token(self, session, html):
        token = session.cookies.get('csrftoken')
        if token:
            return token
        match = re.search(r'"csrf_token":"([^"]+)"', html)
        if match:
            return match.group(1)
        soup = BeautifulSoup(html, 'html.parser')
        meta = soup.find('input', {'name': 'csrfmiddlewaretoken'})
        return meta.get('value') if meta else None

    def attempt(self):
        session = requests.Session()
        proxy = self._get_random_proxy()
        if proxy:
            session.proxies = proxy
        ua = random.choice(self.user_agents)
        session.headers.update({'User-Agent': ua, 'Accept-Language': 'en-US,en;q=0.9'})
        try:
            session.get(f"{self.base_url}/", timeout=15)
            res = session.get(f"{self.base_url}/accounts/password/reset/", timeout=15)
            token = self._extract_token(session, res.text)
            if not token:
                return False, "Token Error (IP Blocked)"
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
                return False, "429"
            return False, f"HTTP {response.status_code}"
        except Exception as e:
            return False, str(e)

# --- نظام FSM للبوت ---
class Form(StatesGroup):
    email = State()

bot = Bot(token=TOKEN)
dp = Dispatcher()
limiter = RateLimiter()

# --- أمر البداية ---
@dp.message(Command("start"))
async def cmd_start(message: Message, state: FSMContext):
    allowed, info = limiter.check_user(message.from_user.id)
    if not allowed:
        return await message.answer(f"⛔️ انتهت محاولاتك. عد مجدداً بتاريخ: {info}")

    # رسالة ترحيب محسنة مع رابط القناة
await message.answer(
    f"🚀 أهلاً بك {message.from_user.first_name} في بوت زيرو إكس – Instagram Reset 👋\n\n"
    "👋 استعد لإعادة تعيين كلمة مرور حسابك على Instagram بكل سهولة.\n\n"
    "📧 أدخل إيميل حسابك للبدء.\n"
    f"🔢 المحاولات المتبقية لك: {info}\n\n"
    "💡 البوت مجاني 100٪ | [قناتي](https://t.me/i3azz)\n"
    "⚠️ يمنع بيع أو إعادة نشر البوت للحفاظ على أمان الجميع.",
    parse_mode=ParseMode.MARKDOWN
)

    # تعيين الحالة ضمن نفس البلوك
    await state.set_state(Form.email)

# --- التعامل مع البريد الإلكتروني ---
@dp.message(Form.email)
async def handle_email(message: Message, state: FSMContext):
    user_id = message.from_user.id
    email = message.text.strip()
    status_msg = await message.answer("⏳ جاري الإرسال...")

    master = IGResetMaster(email)
    success, result = await asyncio.to_thread(master.attempt)

    await state.clear()
    if success:
        limiter.increment_usage(user_id)
        await status_msg.edit_text(f"✅ تم الإرسال بنجاح!\nالحساب: `{email}`\nتفقد بريدك الآن.")
    else:
        if "429" in result:
            await status_msg.edit_text("❌ فشل: حظر مؤقت (429)\nلم يتم خصم محاولة، انتظر 10 دقائق.")
        else:
            limiter.increment_usage(user_id)
            await status_msg.edit_text(f"❌ فشل الإرسال\nالسبب: {result}")

# --- تشغيل البوت ---
async def main():
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
