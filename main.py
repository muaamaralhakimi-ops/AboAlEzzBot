"""
╔══════════════════════════════════════════════════════════════╗
║           نظام أبو سعود — النسخة الكاملة للتشغيل           ║
╚══════════════════════════════════════════════════════════════╝
"""

import logging, os, re, asyncio, signal, sys, threading, time
from http.server import HTTPServer, BaseHTTPRequestHandler
import httpx
from replit import db
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, BotCommand
from telegram.ext import (ApplicationBuilder, ContextTypes, MessageHandler,
                           CommandHandler, filters, CallbackQueryHandler)
from telegram.error import Conflict, NetworkError, TimedOut

logging.basicConfig(level=logging.INFO)

# ══════════════════════════════════════════════════════════════
#                     ⚙️  إعدادات المشروع
# ══════════════════════════════════════════════════════════════

# معرّف الجروب العام للأدمن (أبو سعود)
ADMIN_GROUP_ID = -1003803368309 

# قاموس الموظفين وجروباتهم الخاصة
WORKERS = {
    1062337898: {"name": "أحمد الحماطي", "group": -1003221600280},
    6219102740: {"name": "أمين الحماطي", "group": -1003504555117},
    5423134568: {"name": "محمد منير",    "group": -1003779057465},
    1426253253: {"name": "طه",            "group": -1003723842645},
    857492707:  {"name": "صلاح",          "group": -1003888913270},
    8270215782: {"name": "جواد",          "group": -1003777276939},
    7356581068: {"name": "صفوت",          "group": -1003737530468},
    6673262691: {"name": "أحمد ياسين",   "group": -1003629656178},
}

DB_PREFIX = "v31"

# ══════════════════════════════════════════════════════════════
#              💰 أسعار الاشتراكات (ثابتة حسب طلبك)
# ══════════════════════════════════════════════════════════════

PRICES = {
    'uni':      12.5,   # يونيفرس
    'hulk':     20.0,   # هولك
    'world':    12.5,   # وورد كوب
    'ibo1':     25.0,   # ايبو سنة
    'ibo_life': 50.0,   # ايبو مدى الحياة
}

# أنماط التعرف الذكي على الرسائل
LINE2 = [
    ('ibo_life', 'ايبو مدى الحياة', 50.0, r'(\d+)\s*(?:2\s*ibo\b|ibo\s*2\b|ibo_life|ايبو\s*مد[ىي])'),
    ('ibo1',     'ايبو سنة',        25.0, r'(\d+)\s*(?:1\s*ibo\b|ibo\s*1\b|ibo1|ايبو\s*سن[هة])'),
    ('hulk',     'هولك',            20.0, r'(\d+)\s*(?:hu(?:lk)?\b|هولك|هلك)'),
    ('uni',      'يونيفرس',         12.5, r'(\d+)\s*(?:un(?:i(?:verse)?)?\b|يونفرس|يونيفرس)'),
    ('world',    'وورد كوب',        12.5, r'(\d+)\s*(?:wo(?:rld)?\b|وورد\s*(?:كوب)?|ورد)'),
    ('ibo1',     'ايبو سنة',        25.0, r'(\d+)\s*(?:ibo\b|ايبو)'),
]

# ══════════════════════════════════════════════════════════════
#                     📦 الحالة ومعالجة الحسابات
# ══════════════════════════════════════════════════════════════

pending_deductions = {}
processed_messages = set()

def _db_key(uid): return f"{DB_PREFIX}_w_{uid}"

def get_acc(uid: int) -> dict:
    base = {
        'total': 0.0, 'subs_cost': 0.0, 'deductions': [],
        'uni': 0, 'hulk': 0, 'world': 0, 'ibo1': 0, 'ibo_life': 0,
        'name': WORKERS.get(uid, {}).get('name', 'موظف'),
    }
    data = db.get(_db_key(uid))
    if data: base.update(dict(data))
    return base

def build_settlement_text(acc: dict, is_done: bool = False):
    total = float(acc.get('total', 0.0))
    tax = total * 0.15
    after_tax = total - tax
    comm = after_tax * 0.025
    net = after_tax - comm
    
    # حساب تكلفة النقاط التراكمية
    subs_total = (acc.get('hulk',0)*20 + acc.get('uni',0)*12.5 + 
                  acc.get('world',0)*12.5 + acc.get('ibo1',0)*25 + 
                  acc.get('ibo_life',0)*50)
    
    deductions = sum(d['amount'] for d in acc.get('deductions', []))
    final = net - subs_total - deductions

    txt = (f"💳 تقرير تصفية الحساب - أبو سعود\n"
           f"👤 الموظف: {acc['name']}\n"
           f"________________\n"
           f"💰 إجمالي الإيصالات: {total:.2f}\n"
           f"🧾 ضريبة (15%): {tax:.2f}\n"
           f"💸 عمولة (2.5%): {comm:.2f}\n"
           f"💎 تكلفة النقاط: {subs_total:.2f}\n"
           f"➖ الخصومات: {deductions:.2f}\n"
           f"________________\n"
           f"✅ المستحق الصافي: {final:.2f}")
    if is_done: txt += "\n🔄 تم إصفار الحساب"
    return txt

# ══════════════════════════════════════════════════════════════
#                     📩 معالجة الرسائل والأزرار
# ══════════════════════════════════════════════════════════════

async def handle_msg(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    if uid not in WORKERS: return
    
    text = update.message.text or update.message.caption or ""
    # منطق تحليل المبالغ والنقاط من ملفك
    nums = re.findall(r"(\d+(?:\.\d+)?)", text)
    val = float(nums[0]) if nums else 0.0
    
    acc = get_acc(uid)
    acc['total'] += val
    db[_db_key(uid)] = acc
    
    resp = (f"👤 {WORKERS[uid]['name']}\n"
            f"________________\n"
            f"💰 تم تسجيل: {val:.2f}\n"
            f"📈 التراكمي: {acc['total']:.2f}")
    
    kb = InlineKeyboardMarkup([[InlineKeyboardButton("💳 تصفية", callback_data=f"ask_{uid}")]])
    await update.message.reply_text(resp, reply_markup=kb)

async def callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if query.data.startswith("ask_"):
        uid = int(query.data.split("_")[1])
        txt = build_settlement_text(get_acc(uid))
        await query.message.reply_text(txt)

# ══════════════════════════════════════════════════════════════
#                     🚀 تشغيل البوت
# ══════════════════════════════════════════════════════════════

if __name__ == '__main__':
    token = "8582053913:AAGvZCfTlTDr9FR-hILzB_EVT1PXalk5zlU"
    application = ApplicationBuilder().token(token).build()
    
    application.add_handler(MessageHandler(filters.ALL & (~filters.COMMAND), handle_msg))
    application.add_handler(CallbackQueryHandler(callback_handler))
    
    print("🚀 بوت أبو سعود جاهز للعمل...")
    application.run_polling()
