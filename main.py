import os, re, random, asyncio, time
import requests
from bs4 import BeautifulSoup
from aiogram import Bot, Dispatcher
from aiogram.filters import Command
from aiogram.types import Message
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup

TOKEN = os.getenv("BOT_TOKEN")

# ====== منطقك الأصلي بدون تعديل ======
class IGResetMaster:
    def __init__(self, email, proxy_file="proxies.txt"):
        self.email = email.lower().strip()
        self.proxy_file = proxy_file
        self.proxies = self._load_proxies()
        self.base_url = "https://www.instagram.com"
        self.user_agents = [
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            "Mozilla/5.0 (iPhone; CPU iPhone OS 17_2 like Mac OS X)",
            "Mozilla/5.0 (Linux; Android 10)"
        ]

    def _load_proxies(self):
        if os.path.exists(self.proxy_file):
            with open(self.proxy_file) as f:
                return [x.strip() for x in f if x.strip()]
        return []

    def _get_proxy(self):
        if not self.proxies: return None
        p = random.choice(self.proxies)
        return {"http": f"http://{p}", "https": f"http://{p}"}

    def _extract_token(self, session, html):
        token = session.cookies.get("csrftoken")
        if token: return token
        m = re.search(r'"csrf_token":"([^"]+)"', html)
        if m: return m.group(1)
        soup = BeautifulSoup(html, "html.parser")
        i = soup.find("input", {"name": "csrfmiddlewaretoken"})
        return i.get("value") if i else None

    def attempt(self):
        s = requests.Session()
        proxy = self._get_proxy()
        if proxy: s.proxies = proxy

        s.headers.update({
            "User-Agent": random.choice(self.user_agents),
            "Accept-Language": "en-US,en;q=0.9"
        })

        s.get(self.base_url, timeout=15)
        r = s.get(f"{self.base_url}/accounts/password/reset/", timeout=15)
        token = self._extract_token(s, r.text)

        if not token:
            return False, "Token Error / Proxy Block"

        res = s.post(
            f"{self.base_url}/accounts/account_recovery_send_ajax/",
            data={"email_or_username": self.email, "csrfmiddlewaretoken": token},
            headers={"X-CSRFToken": token, "X-Requested-With": "XMLHttpRequest"},
            timeout=15
        )

        if res.status_code == 200:
            j = res.json()
            return (True, "Success") if j.get("status") == "ok" else (False, j.get("message"))
        if res.status_code == 429:
            return False, "Rate Limit (429)"
        return False, f"HTTP {res.status_code}"

# ====== FSM ======
class Form(StatesGroup):
    email = State()

bot = Bot(TOKEN)
dp = Dispatcher()

@dp.message(Command("start"))
async def start(m: Message, state: FSMContext):
    await m.answer("📧 أرسل إيميل حساب انستقرام:")
    await state.set_state(Form.email)

@dp.message(Form.email)
async def handle(m: Message, state: FSMContext):
    await state.clear()
    msg = await m.answer("⏳ جاري المحاولة...")

    success, result = await asyncio.to_thread(
        IGResetMaster(m.text.strip()).attempt
    )

    if success:
        await msg.edit_text("✅ تم إرسال الريست بنجاح\n📩 تفقد بريدك")
    else:
        await msg.edit_text(f"❌ فشل الإرسال\nالسبب: {result}")

async def main():
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
