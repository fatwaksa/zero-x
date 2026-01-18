import logging
import asyncio
import random
import re
import os
import requests
from typing import Optional
from bs4 import BeautifulSoup
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
from aiogram.types import Message
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup

# --- الإعدادات الأساسية ---
TOKEN = os.getenv("BOT_TOKEN")

class IGResetEngine:
    def __init__(self, target):
        self.target = target.lower().strip()
        self.session = requests.Session()
        self.base_url = "https://www.instagram.com"
        
        # قائمة متصفحات حديثة جداً لمحاكاة حقيقية
        self.user_agents = [
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Mozilla/5.0 (iPhone; CPU iPhone OS 17_2 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.2 Mobile/15E148 Safari/604.1",
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_2_1) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Mozilla/5.0 (Linux; Android 14; SM-S918B) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Mobile Safari/537.36"
        ]
        
    def _extract_token(self, html):
        """استخراج توكن الأمان بأكثر من طريقة لضمان النجاح"""
        # الطريقة 1: من الكوكيز
        token = self.session.cookies.get('csrftoken')
        if token: return token
        
        # الطريقة 2: البحث في كود الصفحة (Regex)
        match = re.search(r'"csrf_token":"([^"]+)"', html)
        if match: return match.group(1)
        
        # الطريقة 3: من الـ HTML مباشرة
        soup = BeautifulSoup(html, 'html.parser')
        meta = soup.find('input', {'name': 'csrfmiddlewaretoken'})
        return meta.get('value') if meta else None

    async def execute(self, status_callback):
        try:
            # تحديث الـ User-Agent لكل طلب
            ua = random.choice(self.user_agents)
            self.session.headers.update({
                'User-Agent': ua,
                'Accept': '*/*',
                'Accept-Language': 'en-US,en;q=0.9',
                'X-Requested-With': 'XMLHttpRequest',
                'Referer': f"{self.base_url}/accounts/password/reset/"
            })

            await status_callback("🔍 جاري فحص الحماية وتسخين الجلسة...")
            
            # الخطوة 1: بناء الكوكيز (زيارة الصفحة الرئيسية)
            self.session.get(f"{self.base_url}/", timeout=15)
            await asyncio.sleep(random.uniform(1.5, 3))

            # الخطوة 2: الدخول لصفحة الريسيت واستخراج التوكن
            res = self.session.get(f"{self.base_url}/accounts/password/reset/", timeout=15)
            
            if res.status_code == 429:
                return False, "خطأ 429: إنستقرام حظرت الآي بي حالياً. انتظر قليلاً."

            token = self._extract_token(res.text)
            if not token:
                return False, "فشل استخراج التوكن (قد يكون السيرفر محظوراً)."

            await status_callback(f"🚀 يتم الآن محاولة إرسال الرست...")
            await asyncio.sleep(random.uniform(2, 4))

            # الخطوة 3: إرسال الطلب النهائي
            post_headers = {
                'X-CSRFToken': token,
                'Content-Type': 'application/x-www-form-urlencoded'
            }
            data = {'email_or_username': self.target, 'csrfmiddlewaretoken': token}

            response = self.session.post(
                f"{self.base_url}/accounts/account_recovery_send_ajax/",
                data=data, headers=post_headers, timeout=20
            )

            if response.status_code == 200:
                resp_json = response.json()
                if resp_json.get('status') == 'ok':
                    return True, "تم إرسال رابط إعادة التعيين بنجاح! تفقد بريدك."
                return False, resp_json.get('message', 'المستخدم غير موجود أو محظور.')
            
            if response.status_code == 429:
                return False, "خطأ 429: تم إرسال طلبات كثيرة. انتظر 5 دقائق وحاول مجدداً."

            return False, f"استجابة غير متوقعة من السيرفر ({response.status_code})."

        except Exception as e:
            return False, f"مشكلة تقنية: {str(e)[:40]}"

# --- الفلو الخاص بالبوت ---
class ResetStates(StatesGroup):
    waiting_for_email = State()

bot = Bot(token=TOKEN)
dp = Dispatcher()

@dp.message(Command("start"))
async def start_cmd(message: Message, state: FSMContext):
    user_name = message.from_user.first_name
    await message.answer(
        f"اهلاً بك {user_name} في بوت زيرو إكس\n"
        "لارسال رست انستقرام 🫆.\n\n"
        "ضع ايميل حسابك في الانستقرام 👨🏻‍💻."
    )
    await state.set_state(ResetStates.waiting_for_email)

@dp.message(ResetStates.waiting_for_email)
async def process_reset(message: Message, state: FSMContext):
    target = message.text.strip()
    status_msg = await message.answer("⏳ جاري معالجة طلبك...")
    
    async def update_status(text):
        try: await status_msg.edit_text(text)
        except: pass

    engine = IGResetEngine(target)
    success, result_text = await engine.execute(update_status)
    await state.clear()

    if success:
        await message.answer(
            f"✅ **تم الارسال الفعلي!**\n\n"
            f"👤 الحساب: {target}\n"
            f"📩 النتيجة: {result_text}\n\n"
            "افحص البريد الوارد أو الـ Junk."
        )
    else:
        await message.answer(
            f"❌ **فشل الإرسال**\n\n"
            f"السبب: {result_text}\n\n"
            "💡 نصيحة: إذا كنت تستخدم Railway، حاول تغيير وقت المحاولة أو استخدم يوزر نيم بدلاً من الإيميل."
        )

async def main():
    logging.basicConfig(level=logging.INFO)
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
