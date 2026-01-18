import os
import json
import time
import random
import asyncio
import logging
import requests
import re
from datetime import datetime, timedelta
from bs4 import BeautifulSoup
from aiogram import Bot, Dispatcher, types
from aiogram.filters import Command
from aiogram.types import Message
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup

# --- الإعدادات ---
TOKEN = os.getenv("BOT_TOKEN")

# قائمة البروكسيات (مدمجة لضمان العمل)
PROXY_LIST_RAW = """
104.16.109.201:80
103.160.204.92:80
66.235.200.49:80
23.227.39.16:80
172.67.77.203:80
103.160.204.17:80
103.160.204.11:80
103.160.204.52:80
103.160.204.87:80
185.176.24.12:80
45.67.215.254:80
103.160.204.47:80
103.160.204.90:80
103.160.204.19:80
185.176.24.174:80
103.160.204.76:80
188.42.88.243:80
190.93.246.15:80
104.20.36.8:80
31.12.75.89:80
23.227.39.128:80
23.227.39.208:80
172.67.181.92:80
46.254.93.99:80
154.83.2.80:80
91.193.59.85:80
23.227.39.14:80
185.176.26.39:80
45.131.208.57:80
104.17.233.39:80
198.41.203.79:80
104.17.189.79:80
45.67.215.140:80
45.194.53.78:80
91.193.58.111:80
46.254.92.16:80
173.245.49.50:80
45.131.208.76:80
104.18.190.53:80
104.17.137.84:80
172.67.179.169:80
172.67.254.47:80
185.176.24.10:80
198.41.207.78:80
154.197.75.157:80
190.93.245.33:80
154.197.75.152:80
154.197.75.150:80
154.197.75.151:80
154.197.75.156:80
154.197.75.159:80
184.168.47.49:80
172.67.71.37:80
108.162.193.229:80
104.17.128.227:80
108.162.193.222:80
108.162.193.224:80
195.85.23.103:80
108.162.193.225:80
108.162.193.221:80
172.67.70.118:80
108.162.193.223:80
108.162.193.227:80
198.41.198.154:80
104.25.190.51:80
172.67.229.11:80
46.254.92.10:80
159.246.55.1:80
162.159.242.183:80
104.26.13.218:80
104.21.13.218:80
162.159.242.161:80
164.38.155.61:80
162.159.242.189:80
162.159.242.102:80
162.159.242.131:80
162.159.242.147:80
162.159.242.172:80
162.159.242.136:80
45.67.215.162:80
195.85.23.236:80
154.92.9.212:80
91.193.59.156:80
5.10.247.193:80
164.38.155.96:80
5.10.244.193:80
45.131.6.68:80
104.17.196.97:80
188.132.222.15:8080
"""

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
            self.data[user_id] = {"count": 0, "reset_time": str(now + timedelta(hours=self.reset_hours))}
            self._save_data()
            return True, self.max_attempts

        user_data = self.data[user_id]
        reset_time = datetime.fromisoformat(user_data["reset_time"])

        if now > reset_time:
            # إعادة تعيين الوقت والعداد
            self.data[user_id] = {"count": 0, "reset_time": str(now + timedelta(hours=self.reset_hours))}
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

# --- كلاس الريسيت (نفس كودك مع تحسين التكرار) ---
class IGResetMaster:
    def __init__(self, email):
        self.email = email.lower().strip()
        self.proxies = [p.strip() for p in PROXY_LIST_RAW.split('\n') if p.strip()]
        self.base_url = "https://www.instagram.com"
        self.user_agents = [
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Mozilla/5.0 (iPhone; CPU iPhone OS 17_2 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.2 Mobile/15E148 Safari/604.1",
            "Mozilla/5.0 (Linux; Android 10; SM-G981B) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/80.0.3987.162 Mobile Safari/537.36"
        ]

    def _get_random_proxy(self):
        if not self.proxies: return None
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

    # دالة المحاولة الذكية (تلف على البروكسيات حتى تنجح)
    def execute_smartly(self):
        # سنحاول 15 مرة ببروكسيات مختلفة قبل الاستسلام
        max_internal_retries = 15 
        
        for i in range(max_internal_retries):
            session = requests.Session()
            proxy = self._get_random_proxy()
            if proxy: session.proxies.update(proxy)
            
            ua = random.choice(self.user_agents)
            session.headers.update({
                'User-Agent': ua, 
                'Accept-Language': 'en-US,en;q=0.9',
                'X-Requested-With': 'XMLHttpRequest'
            })

            try:
                # تقليل وقت الانتظار لتجربة بروكسيات أكثر بسرعة
                session.get(f"{self.base_url}/", timeout=5)
                res = session.get(f"{self.base_url}/accounts/password/reset/", timeout=5)
                token = self._extract_token(session, res.text)
                
                if not token:
                    continue # بروكسي فاشل، جرب التالي

                headers = {
                    'X-CSRFToken': token,
                    'Referer': f'{self.base_url}/accounts/password/reset/',
                    'Content-Type': 'application/x-www-form-urlencoded'
                }
                data = {'email_or_username': self.email, 'csrfmiddlewaretoken': token}
                
                response = session.post(
                    f"{self.base_url}/accounts/account_recovery_send_ajax/", 
                    data=data, headers=headers, timeout=10
                )
                
                if response.status_code == 200:
                    out = response.json()
                    if out.get('status') == 'ok':
                        return True, "تم الإرسال بنجاح! تفقد بريدك."
                    else:
                        msg = out.get('message', '')
                        # إذا قال انستقرام المستخدم غير موجود، نتوقف ولا نكرر
                        if 'found' in msg or 'valid' in msg:
                            return False, f"خطأ في اليوزر: {msg}"
                        return False, msg # خطأ آخر من انستقرام
                
                elif response.status_code == 429:
                    continue # محظور، جرب بروكسي آخر فوراً

            except Exception:
                continue # خطأ اتصال، جرب بروكسي آخر

        return False, "فشلت الاتصالات، السيرفرات مشغولة جداً."

# --- البوت ---
class Form(StatesGroup):
    email = State()

bot = Bot(token=TOKEN)
dp = Dispatcher()
limiter = RateLimiter()

@dp.message(Command("start"))
async def start(message: Message, state: FSMContext):
    user_name = message.from_user.first_name
    
    # التحقق من الرصيد قبل البدء
    allowed, info = limiter.check_user(message.from_user.id)
    
    if not allowed:
        await message.answer(f"⛔️ **عفواً، لقد استهلكت محاولاتك لليوم.**\n\nيمكنك المحاولة مجدداً بعد: {info}")
        return

    # الترحيب المطلوب
    welcome_text = (
        f"أهلاً بك {user_name} في بوت زيرو إكس\n"
        "لارسال رست انستقرام 🫆.\n\n"
        "ضع ايميل حسابك في الانستقرام 👨🏻‍💻.\n"
        f"⚡️ المحاولات المتبقية لك اليوم: {info}"
    )
    await message.answer(welcome_text)
    await state.set_state(Form.email)

@dp.message(Form.email)
async def process_reset(message: Message, state: FSMContext):
    user_id = message.from_user.id
    allowed, info = limiter.check_user(user_id)
    
    if not allowed:
        await message.answer("⛔️ انتهت محاولاتك اليومية.")
        await state.clear()
        return

    email = message.text.strip()
    status_msg = await message.answer("🔄 جاري الاتصال بالسيرفرات وتجاوز الحماية...")

    # تشغيل الكود الثقيل في خيط منفصل
    master = IGResetMaster(email)
    success, result = await asyncio.to_thread(master.execute_smartly)

    if success:
        limiter.increment_usage(user_id) # خصم محاولة فقط عند النجاح
        await status_msg.edit_text(
            f"✅ **تم الارسال الفعلي!**\n\n"
            f"👤 الحساب: `{email}`\n"
            f"📩 النتيجة: {result}\n"
            f"📉 المحاولات المتبقية: {info - 1}"
        )
    else:
        # لو فشل بسبب أن اليوزر غلط، نخصم محاولة أيضاً
        if "خطأ في اليوزر" in result:
             limiter.increment_usage(user_id)
             await status_msg.edit_text(f"❌ **فشل الإرسال**\n\nالسبب: {result}")
        else:
             # لو فشل بسبب البروكسيات لا نخصم من رصيده
             await status_msg.edit_text(f"⚠️ **فشل الاتصال**\n\nالسبب: {result}\nحاول مرة أخرى، لم يتم خصم المحاولة.")
    
    await state.clear()

async def main():
    logging.basicConfig(level=logging.INFO)
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
