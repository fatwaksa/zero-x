import os
import json
import asyncio
import logging
import requests
import re
import random
from datetime import datetime, timedelta
from bs4 import BeautifulSoup
from aiogram import Bot, Dispatcher, F
from aiogram.filters import Command
from aiogram.types import Message
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup

# --- الإعدادات ---
TOKEN = os.getenv("BOT_TOKEN") 
# تأكد من وضع التوكن الخاص بك هنا إذا كنت تشغل الملف محلياً، أو اتركه os.getenv إذا كنت تستخدم استضافة
# TOKEN = "YOUR_BOT_TOKEN_HERE" 

# إعداد السجل (Logging) لمعرفة الأخطاء
logging.basicConfig(level=logging.INFO)

# --- نظام إدارة المحاولات (RateLimiter) ---
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
            self.data[user_id] = {"count": 0, "reset_time": (now + timedelta(hours=self.reset_hours)).isoformat()}
            self._save_data()
            return True, self.max_attempts
        
        user_data = self.data[user_id]
        reset_time = datetime.fromisoformat(user_data["reset_time"])
        
        if now > reset_time:
            self.data[user_id] = {"count": 0, "reset_time": (now + timedelta(hours=self.reset_hours)).isoformat()}
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

# --- الكلاس المطور (IGResetMaster) ---
class IGResetMaster:
    def __init__(self, email, proxy_file="proxies.txt"):
        self.email = email.lower().strip()
        self.proxy_file = proxy_file
        self.proxies = self._load_proxies()
        self.base_url = "https://www.instagram.com"
        # قائمة User-Agents حديثة
        self.user_agents = [
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36",
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:122.0) Gecko/20100101 Firefox/122.0"
        ]

    def _load_proxies(self):
        # إذا الملف غير موجود أو فارغ، نرجع قائمة فارغة (بدون أخطاء)
        if os.path.exists(self.proxy_file):
            try:
                with open(self.proxy_file, "r") as f:
                    return [line.strip() for line in f if line.strip()]
            except:
                return []
        return []

    def _get_random_proxy(self):
        if not self.proxies:
            return None
        p = random.choice(self.proxies)
        # دعم تنسيق البروكسي البسيط ip:port
        if not p.startswith("http"):
             return {"http": f"http://{p}", "https": f"http://{p}"}
        return {"http": p, "https": p}

    def _extract_token(self, session, html):
        # محاولة 1: من الكوكيز
        token = session.cookies.get('csrftoken')
        if token: return token
        
        # محاولة 2: Regex JSON
        match = re.search(r'"csrf_token":"([^"]+)"', html)
        if match: return match.group(1)
        
        # محاولة 3: Regex JavaScript Config
        match_config = re.search(r'csrf_token\\":\\"([^"]+)\\"', html)
        if match_config: return match_config.group(1)

        # محاولة 4: BeautifulSoup
        try:
            soup = BeautifulSoup(html, 'html.parser')
            meta = soup.find('input', {'name': 'csrfmiddlewaretoken'})
            return meta.get('value') if meta else None
        except:
            return None

    def attempt(self):
        session = requests.Session()
        proxy = self._get_random_proxy()
        
        if proxy:
            session.proxies = proxy
            print(f"Using Proxy: {proxy}") # للتجربة

        ua = random.choice(self.user_agents)
        
        # ترويسات محسنة لتجنب الكشف
        session.headers.update({
            'User-Agent': ua,
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8',
            'Accept-Language': 'en-US,en;q=0.9',
            'Upgrade-Insecure-Requests': '1',
            'Sec-Fetch-Site': 'same-origin',
            'Sec-Fetch-Mode': 'navigate',
            'Sec-Fetch-Dest': 'document',
            'Connection': 'keep-alive'
        })

        try:
            # الخطوة 1: زيارة الصفحة الرئيسية للحصول على الكوكيز الأولية
            session.get(f"{self.base_url}/", timeout=20)
            
            # الخطوة 2: زيارة صفحة الريسيت
            reset_url = f"{self.base_url}/accounts/password/reset/"
            res = session.get(reset_url, timeout=20)
            
            token = self._extract_token(session, res.text)
            if not token:
                # إذا فشل استخراج التوكين، غالباً IP محظور
                return False, "IP Blocked (No Token)"

            # تحديث الترويسات لطلب الـ AJAX
            headers = {
                'X-CSRFToken': token,
                'X-Requested-With': 'XMLHttpRequest',
                'Referer': reset_url,
                'Content-Type': 'application/x-www-form-urlencoded',
                'X-IG-App-ID': '936619743392459', # معرف تطبيق انستجرام ويب
                'X-Instagram-AJAX': '1',
                'Origin': self.base_url
            }
            
            data = {
                'email_or_username': self.email,
                'csrfmiddlewaretoken': token
            }
            
            # الخطوة 3: إرسال طلب POST
            response = session.post(
                f"{self.base_url}/accounts/account_recovery_send_ajax/", 
                data=data, 
                headers=headers, 
                timeout=20
            )
            
            if response.status_code == 200:
                try:
                    out = response.json()
                    if out.get('status') == 'ok':
                        return True, "Success"
                    # التحقق مما إذا كان انستجرام يطلب تحقق كابتشا أو غيره
                    if 'checkpoint_url' in out:
                         return False, "Checkpoint Required (Captcha)"
                    return False, out.get('message', 'Rejected by IG')
                except:
                    return False, "Invalid JSON Response"
            
            elif response.status_code == 429:
                return False, "429" # إشارة خاصة للحظر
            
            elif response.status_code == 403:
                return False, "403 Forbidden (IP Ban)"

            return False, f"HTTP {response.status_code}"
            
        except Exception as e:
            return False, str(e)


# --- نظام البوت ---
class Form(StatesGroup):
    email = State()

bot = Bot(token=TOKEN)
dp = Dispatcher()
limiter = RateLimiter()

@dp.message(Command("start"))
async def cmd_start(message: Message, state: FSMContext):
    allowed, info = limiter.check_user(message.from_user.id)
    if not allowed:
        return await message.answer(f"⛔️ انتهت محاولاتك. عد مجدداً بتاريخ: {info}")
    
    # تم إصلاح المسافة البادئة (Indentation) هنا
    await message.answer(
        f"🚀 أهلاً بك {message.from_user.first_name} في بوت Instagram Reset\n\n"
        "📧 أرسل البريد الإلكتروني (Email) أو اليوزر لبدء العملية.\n"
        f"🔢 المحاولات المتبقية: {info}\n"
    )
    await state.set_state(Form.email)

@dp.message(Form.email)
async def handle_email(message: Message, state: FSMContext):
    user_id = message.from_user.id
    email = message.text.strip()
    
    # تحقق بسيط من صحة المدخل
    if len(email) < 3:
        return await message.answer("⚠️ يرجى إدخال بريد أو يوزر صحيح.")

    status_msg = await message.answer(f"⏳ جاري محاولة استعادة: `{email}` ...")
    
    # تشغيل العملية في Thread منفصل لعدم تجميد البوت
    master = IGResetMaster(email)
    success, result = await asyncio.to_thread(master.attempt)
    
    await state.clear()
    
    if success:
        limiter.increment_usage(user_id)
        await status_msg.edit_text(
            f"✅ **تم الإرسال بنجاح!**\n\n"
            f"📩 الحساب: `{email}`\n"
            f"ℹ️ تفقد البريد الوارد أو الرسائل غير المرغوبة (Spam)."
        )
    else:
        # معالجة ذكية للأخطاء
        if "429" in result:
            # لا نخصم محاولة من المستخدم لأن الخطأ من السيرفر
            await status_msg.edit_text(
                "❌ **السيرفر مشغول جداً (429)**\n"
                "⚠️ لم يتم خصم محاولة. يرجى الانتظار 5-10 دقائق والمحاولة مرة أخرى."
            )
        elif "IP Blocked" in result:
             await status_msg.edit_text("❌ فشل: IP السيرفر محظور حالياً من انستجرام.")
        else:
            # نخصم محاولة لأن الطلب وصل وانستجرام رفضه (مثل إيميل خطأ)
            limiter.increment_usage(user_id)
            await status_msg.edit_text(f"❌ فشل الإرسال\nالسبب: {result}")

async def main():
    print("Bot started...")
    await dp.start_polling(bot)

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("Bot stopped")
