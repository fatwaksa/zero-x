import os
import json
import asyncio
import logging
import requests
import re
import random
from datetime import datetime, timedelta
from bs4 import BeautifulSoup
from aiogram import Bot, Dispatcher
from aiogram.filters import Command
from aiogram.types import Message
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup

# --- الإعدادات ---
TOKEN = os.getenv("BOT_TOKEN")

# --- نظام إدارة المحاولات (4 محاولات كل 24 ساعة) ---
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
            # مستخدم جديد
            self.data[user_id] = {
                "count": 0, 
                "reset_time": (now + timedelta(hours=self.reset_hours)).isoformat()
            }
            self._save_data()
            return True, self.max_attempts

        user_data = self.data[user_id]
        reset_time = datetime.fromisoformat(user_data["reset_time"])

        # هل انتهى وقت الانتظار؟ (مرت 24 ساعة)
        if now > reset_time:
            self.data[user_id] = {
                "count": 0, 
                "reset_time": (now + timedelta(hours=self.reset_hours)).isoformat()
            }
            self._save_data()
            return True, self.max_attempts

        # هل استهلك المحاولات؟
        if user_data["count"] < self.max_attempts:
            return True, self.max_attempts - user_data["count"]
        
        return False, reset_time.strftime("%Y-%m-%d %H:%M")

    def increment_usage(self, user_id):
        user_id = str(user_id)
        if user_id in self.data:
            self.data[user_id]["count"] += 1
            self._save_data()

# --- كلاس Reset Master (الكود الخاص بك تماماً) ---
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
        # إذا الملف غير موجود، يعود بقائمة فارغة ولا تحدث مشاكل
        if os.path.exists(self.proxy_file):
            with open(self.proxy_file, "r") as f:
                return [line.strip() for line in f if line.strip()]
        return []

    def _get_random_proxy(self):
        if not self.proxies: return None
        p = random.choice(self.proxies)
        return {"http": f"http://{p}", "https": f"http://{p}"}

    def _extract_token(self, session, html):
        # 1. من الكوكيز
        token = session.cookies.get('csrftoken')
        if token: return token
        # 2. من كود الصفحة (Regex)
        match = re.search(r'"csrf_token":"([^"]+)"', html)
        if match: return match.group(1)
        # 3. من BeautifulSoup
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
            # الخطوة 1: بناء الجلسة
            session.get(f"{self.base_url}/", timeout=15)
            
            # الخطوة 2: الدخول لصفحة الريسيت
            res = session.get(f"{self.base_url}/accounts/password/reset/", timeout=15)
            token = self._extract_token(session, res.text)
            
            if not token:
                # هذا الخطأ يحدث غالباً بسبب 429 في الصفحة الأولى
                return False, "IP Blocked (No Token)"

            # الخطوة 3: إرسال الطلب
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
                    return True, "Success! Check Email."
                return False, out.get('message', 'Rejected')
            elif response.status_code == 429:
                return False, "Rate Limit (Too many requests)"
            return False, f"Server Error: {response.status_code}"

        except Exception as e:
            return False, str(e)

# --- إعدادات البوت ---
class Form(StatesGroup):
    email = State()

bot = Bot(token=TOKEN)
dp = Dispatcher()
limiter = RateLimiter() # تهيئة نظام المحاولات

@dp.message(Command("start"))
async def start(message: Message, state: FSMContext):
    user_name = message.from_user.first_name
    
    # فحص الرصيد
    allowed, info = limiter.check_user(message.from_user.id)
    
    if not allowed:
        await message.answer(f"⛔️ **عفواً، استهلكت الـ 4 محاولات لهذا اليوم.**\n⏰ يمكنك المحاولة مجدداً بتاريخ: {info}")
        return

    # الترحيب
    welcome_text = (
        f"أهلاً بك {user_name} في بوت زيرو إكس\n"
        "لارسال رست انستقرام 🫆.\n\n"
        "ضع ايميل حسابك في الانستقرام 👨🏻‍💻.\n"
        f"🔢 المحاولات المتبقية: {info}"
    )
    await message.answer(welcome_text)
    await state.set_state(Form.email)

@dp.message(Form.email)
async def process_email(message: Message, state: FSMContext):
    user_id = message.from_user.id
    email = message.text.strip()
    
    # فحص مزدوج (للتأكد أن المستخدم لم يرسل عدة رسائل بسرعة)
    allowed, info = limiter.check_user(user_id)
    if not allowed:
        await message.answer("⛔️ انتهت محاولاتك اليومية.")
        await state.clear()
        return

    status_msg = await message.answer("⏳ جاري المعالجة...")

    # تشغيل كودك في الخلفية
    master = IGResetMaster(email)
    
    # استخدمنا to_thread لكي لا يتجمد البوت
    success, result = await asyncio.to_thread(master.attempt)

    await state.clear()

    if success:
        # خصم محاولة فقط عند النجاح
        limiter.increment_usage(user_id)
        remains = info - 1
        await status_msg.edit_text(
            f"✅ **تم الارسال الفعلي!**\n\n"
            f"👤 الحساب: `{email}`\n"
            f"📩 الحالة: {result}\n"
            f"📉 المتبقي لك: {remains} محاولات."
        )
    else:
        # معالجة الأخطاء
        if "Rate Limit" in result or "IP Blocked" in result:
             # لا نخصم محاولة إذا كان الخطأ من السيرفر (429)
             await status_msg.edit_text("⚠️ **السيرفر مشغول حالياً (429)**\nلم يتم خصم محاولة، الرجاء الانتظار قليلاً والمحاولة لاحقاً.")
        else:
            # نخصم محاولة إذا كان الرفض من انستقرام (مثل يوزر خطأ)
            limiter.increment_usage(user_id)
            remains = info - 1
            await status_msg.edit_text(f"❌ **فشل الإرسال**\n\nالسبب: {result}\n📉 المتبقي لك: {remains}")

async def main():
    logging.basicConfig(level=logging.INFO)
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
