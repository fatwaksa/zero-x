import os
import random
import asyncio
import re
import json
import logging
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple
from urllib.parse import urlparse

import httpx
from bs4 import BeautifulSoup
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.context import FSMContext
from aiogram.fsm.storage.memory import MemoryStorage
from dotenv import load_dotenv

# تحميل متغيرات البيئة
load_dotenv()

# إعدادات التسجيل
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

TOKEN = os.getenv("BOT_TOKEN")

# ------------------------------
# FSM لإدارة الحالة
# ------------------------------
class Form(StatesGroup):
    waiting_for_email = State()
    waiting_for_attempts = State()

# ------------------------------
# إدارة بيانات المستخدمين مع تجنب الحظر
# ------------------------------
class RateLimiter:
    def __init__(self):
        self.user_attempts: Dict[int, Dict] = {}
        self.proxy_pool: List[str] = []
        self.load_proxies()
        
    def load_proxies(self):
        """تحميل البروكسيات من مصادر مختلفة"""
        try:
            # مصدر 1: ملف محلي
            if os.path.exists("proxies.txt"):
                with open("proxies.txt", "r") as f:
                    self.proxy_pool.extend([line.strip() for line in f if line.strip()])
            
            # مصدر 2: بروكسيات عامة مجانية (مثال)
            free_proxies = [
                "51.158.68.68:8811",
                "51.158.68.133:8811",
                "51.158.186.242:8811",
            ]
            self.proxy_pool.extend(free_proxies)
            
            logger.info(f"تم تحميل {len(self.proxy_pool)} بروكسي")
        except Exception as e:
            logger.error(f"خطأ في تحميل البروكسيات: {e}")
    
    def get_rotating_proxy(self):
        """الحصول على بروكسي دوار"""
        if not self.proxy_pool:
            return None
        return random.choice(self.proxy_pool)
    
    def can_make_request(self, user_id: int) -> Tuple[bool, Optional[int]]:
        """التحقق إذا كان المستخدم يمكنه إرسال طلب"""
        now = datetime.now()
        
        if user_id not in self.user_attempts:
            self.user_attempts[user_id] = {
                'last_request': now - timedelta(minutes=5),
                'request_count': 0,
                'cooldown_until': None
            }
        
        user_data = self.user_attempts[user_id]
        
        # التحقق من فترة التهدئة
        if user_data.get('cooldown_until') and now < user_data['cooldown_until']:
            wait_seconds = int((user_data['cooldown_until'] - now).total_seconds())
            return False, wait_seconds
        
        # إعادة تعيين العد إذا مرت فترة
        if now - user_data['last_request'] > timedelta(minutes=10):
            user_data['request_count'] = 0
        
        # الحد: 3 طلبات كل 10 دقائق
        if user_data['request_count'] >= 3:
            user_data['cooldown_until'] = now + timedelta(minutes=5)
            return False, 300
        
        user_data['request_count'] += 1
        user_data['last_request'] = now
        
        return True, None

rate_limiter = RateLimiter()

# ------------------------------
# محرك إعادة التععيد المحسن
# ------------------------------
class IGResetMasterPro:
    def __init__(self, email: str):
        self.email = email.lower().strip()
        self.base_url = "https://www.instagram.com"
        self.session_cookies = None
        self.session_headers = None
        
        # قائمة User Agents موسعة
        self.user_agents = [
            # Chrome على Windows
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36",
            
            # Firefox
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:121.0) Gecko/20100101 Firefox/121.0",
            
            # Safari على Mac
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.2 Safari/605.1.15",
            
            # Chrome على Mac
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            
            # iPhone
            "Mozilla/5.0 (iPhone; CPU iPhone OS 17_2 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.2 Mobile/15E148 Safari/604.1",
            
            # Android
            "Mozilla/5.0 (Linux; Android 10; SM-G981B) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/80.0.3987.162 Mobile Safari/537.36",
        ]
    
    def _extract_csrf_token(self, html: str) -> Optional[str]:
        """استخراج CSRF Token بطرق متعددة"""
        methods = [
            # Method 1: من meta tag
            lambda: re.search(r'meta content="([^"]+)" name="csrf-token"', html),
            # Method 2: من JSON في الصفحة
            lambda: re.search(r'"csrf_token":"([^"]+)"', html),
            # Method 3: من input hidden
            lambda: re.search(r'name="csrfmiddlewaretoken" value="([^"]+)"', html),
            # Method 4: من config
            lambda: re.search(r'"csrfToken":"([^"]+)"', html),
        ]
        
        for method in methods:
            match = method()
            if match:
                return match.group(1)
        
        return None
    
    async def _create_session(self, use_proxy: bool = True) -> httpx.AsyncClient:
        """إنشاء جلسة جديدة مع إعدادات متقدمة"""
        # إعدادات HTTP Client
        client_params = {
            "timeout": httpx.Timeout(30.0),
            "follow_redirects": True,
            "headers": {
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
                "Accept-Language": "en-US,en;q=0.9,ar;q=0.8",
                "Accept-Encoding": "gzip, deflate, br",
                "Connection": "keep-alive",
                "Upgrade-Insecure-Requests": "1",
            }
        }
        
        # إضافة بروكسي إذا كان متاحاً
        if use_proxy:
            proxy = rate_limiter.get_rotating_proxy()
            if proxy:
                client_params["proxies"] = {
                    "http://": f"http://{proxy}",
                    "https://": f"http://{proxy}"
                }
                logger.info(f"Using proxy: {proxy}")
        
        client = httpx.AsyncClient(**client_params)
        
        # User-Agent عشوائي
        client.headers.update({
            "User-Agent": random.choice(self.user_agents),
            "Sec-Ch-Ua": '"Not_A Brand";v="8", "Chromium";v="120"',
            "Sec-Ch-Ua-Mobile": "?0",
            "Sec-Ch-Ua-Platform": '"Windows"',
        })
        
        return client
    
    async def send_reset_request(self, attempt_number: int = 1) -> Tuple[bool, str]:
        """إرسال طلب إعادة التعيين مع التعامل مع الحظر"""
        try:
            # التحقق من Rate Limit أولاً
            can_request, wait_time = rate_limiter.can_make_request(hash(self.email))
            if not can_request:
                return False, f"⏳ انتظر {wait_time} ثانية قبل المحاولة التالية"
            
            # إنشاء جلسة جديدة لكل محاولة
            async with await self._create_session() as client:
                # الخطوة 1: زيارة الصفحة الرئيسية
                await client.get(f"{self.base_url}/")
                await asyncio.sleep(random.uniform(2, 4))  # تأخير طبيعي
                
                # الخطوة 2: زيارة صفحة تسجيل الدخول أولاً
                login_page = await client.get(f"{self.base_url}/accounts/login/")
                await asyncio.sleep(random.uniform(1, 3))
                
                # الخطوة 3: زيارة صفحة إعادة التعيين
                reset_page = await client.get(
                    f"{self.base_url}/accounts/password/reset/",
                    headers={
                        "Referer": f"{self.base_url}/accounts/login/",
                    }
                )
                
                # استخراج التوكن
                csrf_token = self._extract_csrf_token(reset_page.text)
                if not csrf_token:
                    # محاولة استخراج التوكن من الكوكيز
                    csrf_token = client.cookies.get("csrftoken")
                
                if not csrf_token:
                    return False, "❌ لم يتم العثور على توكن الأمان"
                
                # إعداد البيانات للطلب
                headers = {
                    "X-CSRFToken": csrf_token,
                    "X-Requested-With": "XMLHttpRequest",
                    "X-IG-App-ID": "936619743392459",
                    "X-Instagram-AJAX": "1",
                    "Content-Type": "application/x-www-form-urlencoded",
                    "Referer": f"{self.base_url}/accounts/password/reset/",
                    "Origin": self.base_url,
                    "Sec-Fetch-Dest": "empty",
                    "Sec-Fetch-Mode": "cors",
                    "Sec-Fetch-Site": "same-origin",
                }
                
                data = {
                    "email_or_username": self.email,
                    "csrfmiddlewaretoken": csrf_token,
                }
                
                # تأخير عشوائي قبل الإرسال
                await asyncio.sleep(random.uniform(3, 6))
                
                # إرسال الطلب
                response = await client.post(
                    f"{self.base_url}/accounts/account_recovery_send_ajax/",
                    data=data,
                    headers=headers
                )
                
                # تحليل الرد
                if response.status_code == 200:
                    try:
                        result = response.json()
                        if result.get("status") == "ok":
                            return True, "✅ تم إرسال رابط إعادة التعيين بنجاح! تحقق من بريدك."
                        else:
                            msg = result.get("message", "فشل غير معروف")
                            return False, f"❌ {msg}"
                    except json.JSONDecodeError:
                        # Instagram قد يعيد صفحة HTML بدلاً من JSON
                        if "تم إرسال" in response.text or "sent" in response.text.lower():
                            return True, "✅ تم إرسال رابط إعادة التعيين بنجاح!"
                        return False, "⚠️ استجابة غير متوقعة من Instagram"
                
                elif response.status_code == 429:
                    # Rate Limit - حظر مؤقت
                    retry_after = response.headers.get("Retry-After", "60")
                    return False, f"⏳ Instagram حظر الطلب. حاول بعد {retry_after} ثانية"
                
                elif response.status_code in [400, 403, 404]:
                    return False, f"🚫 خطأ {response.status_code}: قد يكون البريد غير صحيح"
                
                else:
                    return False, f"⚠️ خطأ {response.status_code}: {response.text[:100]}"
                    
        except httpx.TimeoutException:
            return False, "⏱️ انتهت المهلة. تحقق من اتصال الإنترنت"
        except httpx.ProxyError:
            return False, "🔒 خطأ في البروكسي. جرب محاولة أخرى"
        except Exception as e:
            logger.error(f"خطأ غير متوقع: {str(e)}")
            return False, f"⚠️ خطأ: {type(e).__name__}"

# ------------------------------
# إدارة الجلسات المحسنة
# ------------------------------
class SessionManagerPro:
    def __init__(self):
        self.active_sessions: Dict[int, Dict] = {}
        self.user_history: Dict[int, List] = {}
    
    def start_session(self, user_id: int, email: str, attempts: int):
        session_id = f"{user_id}_{int(datetime.now().timestamp())}"
        self.active_sessions[user_id] = {
            'id': session_id,
            'email': email,
            'total_attempts': attempts,
            'completed_attempts': 0,
            'successful': 0,
            'failed': 0,
            'start_time': datetime.now(),
            'status': 'running'
        }
        
        if user_id not in self.user_history:
            self.user_history[user_id] = []
        
        return session_id
    
    def update_session(self, user_id: int, success: bool, message: str):
        if user_id in self.active_sessions:
            session = self.active_sessions[user_id]
            session['completed_attempts'] += 1
            
            if success:
                session['successful'] += 1
                session['status'] = 'success'
            else:
                session['failed'] += 1
            
            # حفظ في التاريخ
            self.user_history[user_id].append({
                'time': datetime.now(),
                'success': success,
                'message': message,
                'session_id': session['id']
            })
    
    def get_session_stats(self, user_id: int) -> Optional[Dict]:
        return self.active_sessions.get(user_id)
    
    def get_user_history(self, user_id: int, limit: int = 5) -> List:
        return self.user_history.get(user_id, [])[-limit:]

session_manager = SessionManagerPro()

# ------------------------------
# واجهة البوت
# ------------------------------
def get_main_keyboard():
    keyboard = [
        [InlineKeyboardButton(text="🔐 إعادة تعيين كلمة المرور", callback_data="start_reset")],
        [InlineKeyboardButton(text="📊 إحصائياتي", callback_data="my_stats"),
         InlineKeyboardButton(text="🔄 المحاولات السابقة", callback_data="history")],
        [InlineKeyboardButton(text="⚙️ الإعدادات", callback_data="settings"),
         InlineKeyboardButton(text="🆘 المساعدة", callback_data="help")]
    ]
    return InlineKeyboardMarkup(inline_keyboard=keyboard)

def get_cancel_keyboard():
    keyboard = [[InlineKeyboardButton(text="❌ إلغاء العملية", callback_data="cancel")]]
    return InlineKeyboardMarkup(inline_keyboard=keyboard)

# ------------------------------
# تهيئة البوت
# ------------------------------
storage = MemoryStorage()
bot = Bot(token=TOKEN) if TOKEN else None
dp = Dispatcher(storage=storage)

# ------------------------------
# Handlers
# ------------------------------
@dp.message(Command("start"))
async def cmd_start(message: types.Message):
    welcome = """
    🤖 **بوت إعادة تعيين إنستجرام المحترف**

    **المميزات الجديدة:**
    ✅ نظام تجنب الحظر (Rate Limit Protection)
    ✅ بروكسيات دوارة تلقائياً
    ✅ تأخيرات ذكية بين المحاولات
    ✅ سجل كامل للمحاولات
    ✅ إحصائيات مفصلة

    **نصائح للاستخدام:**
    • استخدم 1-2 محاولة فقط في البداية
    • إذا ظهر حظر، انتظر 5-10 دقائق
    • البروكسيات تتغير تلقائياً

    اختر من الأزرار أدناه 👇
    """
    await message.answer(welcome, reply_markup=get_main_keyboard())

@dp.callback_query(F.data == "start_reset")
async def start_reset_handler(callback: CallbackQuery, state: FSMContext):
    await callback.message.edit_text(
        "📧 **أدخل البريد الإلكتروني لحساب إنستجرام:**\n\n"
        "⚠️ ملاحظة: استخدم بريداً صحيحاً ومسجلاً في إنستجرام",
        reply_markup=get_cancel_keyboard()
    )
    await state.set_state(Form.waiting_for_email)
    await callback.answer()

@dp.message(Form.waiting_for_email)
async def process_email(message: types.Message, state: FSMContext):
    email = message.text.strip()
    
    # التحقق من صحة البريد
    if "@" not in email or "." not in email:
        await message.answer("❌ بريد إلكتروني غير صالح. حاول مرة أخرى:", 
                           reply_markup=get_cancel_keyboard())
        return
    
    await state.update_data(email=email)
    await message.answer(
        f"✅ البريد: `{email}`\n\n"
        "🔢 **كم محاولة تريد؟**\n"
        "• 1-2 محاولة: آمنة وتجنب الحظر\n"
        "• 3-5 محاولات: متوسطة الخطورة\n"
        "• أكثر من 5: عالية الخطورة (قد تحظر)",
        reply_markup=get_cancel_keyboard()
    )
    await state.set_state(Form.waiting_for_attempts)

@dp.message(Form.waiting_for_attempts)
async def process_attempts(message: types.Message, state: FSMContext):
    try:
        attempts = int(message.text.strip())
        if attempts < 1 or attempts > 10:
            await message.answer("❌ الرجاء إدخال رقم بين 1 و 10:", 
                               reply_markup=get_cancel_keyboard())
            return
    except ValueError:
        await message.answer("❌ الرجاء إدخال رقم صحيح:", 
                           reply_markup=get_cancel_keyboard())
        return
    
    user_data = await state.get_data()
    email = user_data['email']
    await state.clear()
    
    # بدء الجلسة
    session_id = session_manager.start_session(message.from_user.id, email, attempts)
    
    # إرسال رسالة البدء
    status_msg = await message.answer(
        f"🚀 **بدء العملية**\n\n"
        f"• البريد: `{email}`\n"
        f"• المحاولات: {attempts}\n"
        f"• المعرف: `{session_id[:8]}...`\n\n"
        "⏳ جاري الإعداد..."
    )
    
    # تنفيذ المحاولات
    engine = IGResetMasterPro(email)
    
    for attempt_num in range(1, attempts + 1):
        try:
            # تحديث حالة المحاولة
            await status_msg.edit_text(
                f"🔄 **المحاولة {attempt_num}/{attempts}**\n"
                f"البريد: `{email}`\n\n"
                f"⏳ جاري الإرسال..."
            )
            
            # تنفيذ المحاولة
            success, result = await engine.send_reset_request(attempt_num)
            
            # تحديث الجلسة
            session_manager.update_session(message.from_user.id, success, result)
            
            # إرسال نتيجة المحاولة
            if success:
                await message.answer(
                    f"✅ **المحاولة {attempt_num} ناجحة!**\n"
                    f"{result}\n\n"
                    f"🎯 تم إرسال رابط إعادة التعيين بنجاح!"
                )
                # إذا نجحت، نتوقف إلا إذا طلب المستخدم المزيد
                if attempts > 1:
                    continue_option = InlineKeyboardMarkup(inline_keyboard=[[
                        InlineKeyboardButton(text="🔄 استكمال المحاولات", callback_data="continue"),
                        InlineKeyboardButton(text="⏹ إيقاف", callback_data="stop")
                    ]])
                    await message.answer(
                        "هل تريد استكمال المحاولات المتبقية؟",
                        reply_markup=continue_option
                    )
                    # هنا يمكن إضافة منطق للانتظار لرد المستخدم
                break
            else:
                await message.answer(
                    f"⚠️ **المحاولة {attempt_num}:**\n"
                    f"{result}\n\n"
                    f"📝 المحاولات التالية ستكون بعد تأخير..."
                )
                
                # تأخير ذكي بين المحاولات
                if attempt_num < attempts:
                    delay = random.randint(30, 90)  # 30-90 ثانية
                    await status_msg.edit_text(
                        f"⏸️ **انتظار {delay} ثانية**\n"
                        f"قبل المحاولة {attempt_num + 1}"
                    )
                    await asyncio.sleep(delay)
        
        except Exception as e:
            logger.error(f"خطأ في المحاولة {attempt_num}: {e}")
            await message.answer(f"❌ خطأ غير متوقع في المحاولة {attempt_num}")
            await asyncio.sleep(30)
    
    # إرسال النتائج النهائية
    stats = session_manager.get_session_stats(message.from_user.id)
    if stats:
        summary = (
            f"📊 **النتائج النهائية**\n\n"
            f"• البريد: `{stats['email']}`\n"
            f"• المحاولات المطلوبة: {stats['total_attempts']}\n"
            f"• المحاولات المنفذة: {stats['completed_attempts']}\n"
            f"• الناجحة: {stats['successful']}\n"
            f"• الفاشلة: {stats['failed']}\n"
            f"• المدة: {(datetime.now() - stats['start_time']).seconds} ثانية\n\n"
            f"{'✅ نجحت العملية' if stats['successful'] > 0 else '⚠️ لم تنجح أي محاولة'}"
        )
        await message.answer(summary, reply_markup=get_main_keyboard())
    
    await status_msg.delete()

@dp.callback_query(F.data == "cancel")
async def cancel_handler(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    await callback.message.edit_text(
        "✅ تم إلغاء العملية",
        reply_markup=get_main_keyboard()
    )
    await callback.answer()

@dp.callback_query(F.data == "my_stats")
async def stats_handler(callback: CallbackQuery):
    stats = session_manager.get_session_stats(callback.from_user.id)
    if stats:
        message = (
            f"📊 **إحصائيات الجلسة النشطة**\n\n"
            f"• البريد: `{stats['email']}`\n"
            f"• الحالة: {stats['status']}\n"
            f"• الناجحة: {stats['successful']}/{stats['completed_attempts']}\n"
            f"• المدة: {(datetime.now() - stats['start_time']).seconds} ثانية"
        )
    else:
        message = "📭 لا توجد جلسة نشطة حالياً"
    
    await callback.message.answer(message, reply_markup=get_main_keyboard())
    await callback.answer()

@dp.callback_query(F.data == "history")
async def history_handler(callback: CallbackQuery):
    history = session_manager.get_user_history(callback.from_user.id, 5)
    
    if not history:
        await callback.message.answer("📭 لا توجد محاولات سابقة", reply_markup=get_main_keyboard())
        await callback.answer()
        return
    
    history_text = "📜 **آخر 5 محاولات:**\n\n"
    for i, attempt in enumerate(reversed(history), 1):
        emoji = "✅" if attempt['success'] else "❌"
        time_str = attempt['time'].strftime("%H:%M")
        history_text += f"{i}. {emoji} {time_str}: {attempt['message'][:50]}...\n"
    
    await callback.message.answer(history_text, reply_markup=get_main_keyboard())
    await callback.answer()

@dp.callback_query(F.data == "help")
async def help_handler(callback: CallbackQuery):
    help_text = """
    🆘 **دليل الاستخدام وحل المشاكل**

    **مشكلة Rate Limit (الحظر المؤقت):**
    1. انتظر 5-10 دقائق بين المحاولات
    2. استخدم 1-2 محاولة فقط
    3. البروكسيات تتغير تلقائياً

    **لماذا لا تنجح المحاولات؟**
    • البريد غير مسجل في إنستجرام
    • الحساب محذوف أو معطل
    • IP محظور من إنستجرام
    • تحتاج إلى بروكسيات جيدة

    **نصائح للنجاح:**
    • تأكد من صحة البريد
    • استخدم بريداً نشطاً
    • جرب في أوقات مختلفة
    • أضف بروكسيات في ملف proxies.txt

    **لإضافة بروكسيات:**
    1. أنشئ ملف proxies.txt
    2. أضف بروكسي كل سطر
    3. الصيغة: ip:port
    """
    await callback.message.answer(help_text, reply_markup=get_main_keyboard())
    await callback.answer()

@dp.callback_query(F.data == "settings")
async def settings_handler(callback: CallbackQuery):
    proxy_count = len(rate_limiter.proxy_pool)
    settings_text = f"""
    ⚙️ **إعدادات النظام**

    • البروكسيات المتاحة: {proxy_count}
    • نظام الحماية: نشط ✅
    • الحد الأقصى: 3 محاولات/10 دقائق
    • التأخير التلقائي: 30-90 ثانية

    **لتحسين الأداء:**
    1. أضف بروكسيات في proxies.txt
    2. استخدم محاولات قليلة
    3. انتظر بين الجلسات
    """
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔄 تحديث البروكسيات", callback_data="refresh_proxies")],
        [InlineKeyboardButton(text="🔙 رجوع", callback_data="back_to_main")]
    ])
    
    await callback.message.answer(settings_text, reply_markup=keyboard)
    await callback.answer()

@dp.callback_query(F.data == "refresh_proxies")
async def refresh_proxies_handler(callback: CallbackQuery):
    old_count = len(rate_limiter.proxy_pool)
    rate_limiter.load_proxies()
    new_count = len(rate_limiter.proxy_pool)
    
    await callback.message.answer(
        f"🔄 تم تحديث البروكسيات\n"
        f"• السابق: {old_count}\n"
        f"• الجديد: {new_count}\n"
        f"• المضاف: {new_count - old_count}",
        reply_markup=get_main_keyboard()
    )
    await callback.answer()

@dp.callback_query(F.data == "back_to_main")
async def back_handler(callback: CallbackQuery):
    await callback.message.edit_text(
        "🤖 **بوت إعادة تعيين إنستجرام المحترف**\n\n"
        "اختر من القائمة:",
        reply_markup=get_main_keyboard()
    )
    await callback.answer()

# ------------------------------
# التشغيل الرئيسي
# ------------------------------
async def main():
    if not TOKEN:
        logger.error("❌ BOT_TOKEN غير موجود!")
        logger.info("📝 كيفية الحصول على التوكن:")
        logger.info("1. اذهب إلى @BotFather في تيليجرام")
        logger.info("2. أرسل /newbot")
        logger.info("3. اتبع التعليمات")
        logger.info("4. ضع التوكن في متغير BOT_TOKEN")
        return
    
    logger.info("🤖 بدء تشغيل البوت...")
    logger.info(f"📊 البروكسيات المتاحة: {len(rate_limiter.proxy_pool)}")
    
    try:
        await dp.start_polling(bot)
    except Exception as e:
        logger.error(f"خطأ في تشغيل البوت: {e}")
    finally:
        logger.info("⏹ إيقاف البوت...")

if __name__ == "__main__":
    asyncio.run(main())
