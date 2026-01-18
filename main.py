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

# --- جلب التوكن ---
TOKEN = os.getenv("BOT_TOKEN") 

class IGResetEngine:
    def __init__(self, target):
        self.target = target.lower().strip()
        self.session = requests.Session()
        self.base_url = "https://www.instagram.com"
        
        # قائمة متصفحات متنوعة لتجنب الكشف
        self.user_agents = [
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36",
            "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Mozilla/5.0 (iPhone; CPU iPhone OS 17_1 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.1 Mobile/15E148 Safari/604.1"
        ]
        self.session.headers.update({'User-Agent': random.choice(self.user_agents)})

    async def execute(self, status_callback):
        try:
            await status_callback("🔍 جاري فحص الحماية وتسخين الجلسة...")
            # إضافة تأخير عشوائي بسيط لمحاكاة البشر
            await asyncio.sleep(random.uniform(2, 4))
            
            res = self.session.get(f"{self.base_url}/accounts/password/reset/", timeout=15)
            
            if res.status_code == 429:
                return False, "السيرفر مضغوط (429): إنستقرام تطلب الانتظار قليلاً قبل المحاولة مرة أخرى."
                
            token = self._extract_csrf(res.text)

            if not token:
                return False, "Security Wall: فشل استخراج التوكن. قد يكون الآي بي محظوراً مؤقتاً."

            await status_callback(f"🚀 يتم الآن محاولة إرسال الرست...")
            await asyncio.sleep(random.uniform(1, 3))

            post_headers = {
                'X-CSRFToken': token,
                'X-IG-App-ID': '936619743392459',
                'X-ASBD-ID': '129477',
                'X-Requested-With': 'XMLHttpRequest',
                'Referer': f"{self.base_url}/accounts/password/reset/",
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
                return False, "خطأ 429: تم إرسال طلبات كثيرة جداً. انتظر 5 دقائق وحاول مجدداً."

            return False, f"استجابة غير متوقعة ({response.status_code})."
            
        except Exception as e:
            return False, f"مشكلة فنية: {str(e)[:40]}"

    def _extract_csrf(self, html):
        match = re.search(r'\"csrf_token\":\"(.*?)\"', html)
        if not match: match = re.search(r'csrf_token\\":\\"(.*?)\\"', html)
        return match.group(1) if match else None

# --- الفلو الخاص بالبوت (نفسه مع تحسين الرسائل) ---
class ResetStates(StatesGroup):
    waiting_for_email = State()

bot = Bot(token=TOKEN)
dp = Dispatcher()

@dp.message(Command("start"))
async def start_cmd(message: Message, state: FSMContext):
    user_name = message.from_user.full_name
    await message.answer(f"اهلاً بك {user_name} في بوت زيرو إكس\nلارسال رست انستقرام 🫆.\n\nضع ايميل حسابك في الانستقرام 👨🏻‍💻.")
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
        await message.answer(f"✅ **تم الارسال الفعلي!**\n\n👤 الحساب: {target}\n📩 النتيجة: {result_text}")
    else:
        # تحسين شكل رسالة الخطأ
        await message.answer(f"⚠️ **فشل الإرسال**\n\nالسبب: {result_text}")

async def main():
    logging.basicConfig(level=logging.INFO)
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
