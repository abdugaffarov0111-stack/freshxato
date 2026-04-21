import os
import re
import asyncio
import asyncpg
import pytz
from datetime import datetime, timedelta
from collections import defaultdict
from telegram import Update, BotCommand
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes
from dotenv import load_dotenv

load_dotenv()

# ==================== SOZLAMALAR ====================
TASHKENT_TZ = pytz.timezone("Asia/Tashkent")

XATO_KODLARI = {
    "x1": "-DOGOVOR", "dogovor": "-DOGOVOR",
    "x2": "-KOMMENT", "komment": "-KOMMENT", "koment": "-KOMMENT",
    "x3": "-KONTRAGENT", "kontragent": "-KONTRAGENT",
    "x4": "-NOMEKLATURA", "nomeklatura": "-NOMEKLATURA",
    "x5": "-KOLICHESTVO", "kolichestvo": "-KOLICHESTVO",
    "x6": "-PRIXOD", "prixod": "-PRIXOD",
    "x7": "-VOZVRAT", "vozvrat": "-VOZVRAT",
    "x8": "-SPISANIYA", "spisaniya": "-SPISANIYA",
    "x9": "-NAKLADNOY", "nakladnoy": "-NAKLADNOY",
    "x10": "-SUMMA", "summa": "-SUMMA"
}

def get_now():
    return datetime.now(TASHKENT_TZ)
BOT_TOKEN = os.getenv("BOT_TOKEN", "8321131397:AAH1LgiIB1nmMNY_BBLhp5sKOE_blYsPfWk")
DATABASE_URL = os.getenv("DATABASE_URL")

# Pool obyekti (api/index.py dan o'rnatiladi)
db_pool = None

async def get_pool():
    global db_pool
    if db_pool is None:
        db_pool = await asyncpg.create_pool(DATABASE_URL, ssl="require")
        # Schema update check
        async with db_pool.acquire() as conn:
            await conn.execute("""
                ALTER TABLE xatolar 
                ADD COLUMN IF NOT EXISTS xato_turi TEXT DEFAULT 'Umumiy xato';
            """)
    return db_pool

# ==================== MA'LUMOTLAR BILAN ISHLASH ====================

async def get_all_xatolar():
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch("SELECT ism, sana, xato_turi, qoshilgan FROM xatolar")
        return [dict(r) for r in rows]

async def add_xato(ism, sana, xato_turi="Umumiy xato"):
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            "INSERT INTO xatolar (ism, sana, xato_turi) VALUES ($1, $2, $3)",
            ism.capitalize(), sana, xato_turi
        )

async def delete_last_xato():
    pool = await get_pool()
    async with pool.acquire() as conn:
        # Oxirgi qo'shilganini topib o'chirish
        row = await conn.fetchrow("SELECT id, ism, sana, xato_turi FROM xatolar ORDER BY qoshilgan DESC LIMIT 1")
        if row:
            await conn.execute("DELETE FROM xatolar WHERE id = $1", row['id'])
            return dict(row)
    return None

# ==================== HISOBOT LOGIKASI ====================

async def hisobot_yaratish(davr="hafta"):
    xatolar = await get_all_xatolar()
    endi = get_now()

    if davr == "hafta":
        bosh = (endi - timedelta(days=7)).replace(hour=0, minute=0, second=0, microsecond=0)
        nom = "HAFTALIK"
    elif davr == "oy":
        bosh = endi.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        nom = "OYLIK"
    else:
        bosh = endi.replace(hour=0, minute=0, second=0, microsecond=0)
        nom = "BUGUNGI"

    # PostgreSQL da x["sana"] date obyektidir
    filtered = [
        x for x in xatolar
        if datetime.combine(x["sana"] if not isinstance(x["sana"], datetime) else x["sana"].date(), datetime.min.time()).replace(tzinfo=TASHKENT_TZ) >= bosh
    ]

    if not filtered:
        return "📭 Bu davrda xato topilmadi."

    stat = defaultdict(lambda: {"jami": 0, "xatolar": defaultdict(int)})
    for x in filtered:
        stat[x["ism"]]["jami"] += 1
        stat[x["ism"]]["xatolar"][x["xato_turi"]] += 1

    matn = f"📊 *{nom} HISOBOT*\n"
    matn += f"📅 {bosh.strftime('%d.%m.%Y')} — {endi.strftime('%d.%m.%Y')}\n"
    matn += "━━━━━━━━━━━━━━━━━━━━\n\n"
    matn += f"🔢 Jami: *{len(filtered)} ta xato*\n"
    matn += f"👥 Xodimlar: *{len(stat)} ta*\n\n"

    for ism, s in sorted(stat.items(), key=lambda x: -x[1]["jami"]):
        emoji = "🔴" if s["jami"] >= 5 else "🟡" if s["jami"] >= 3 else "🟢"
        ball = round(s["jami"] * 0.2, 1)
        matn += f"{emoji} *{ism}* — {s['jami']} ta xato (*{ball} ball*)\n"
        for xato, soni in sorted(s["xatolar"].items(), key=lambda x: -x[1]):
            matn += f"   • {xato}: {soni} ta\n"
        matn += "\n"

    matn += "━━━━━━━━━━━━━━━━━━━━\n✅ Hisobot tayyor"
    return matn


async def xodim_stat(ism):
    xatolar = await get_all_xatolar()
    endi = get_now().date()

    mine = [x for x in xatolar if x["ism"].lower() == ism.lower()]
    if not mine:
        return f"❌ *{ism}* bo'yicha yozuv topilmadi."

    bugun = sum(1 for x in mine if x["sana"] == endi)
    
    hafta_bosh = endi - timedelta(days=7)
    hafta = sum(1 for x in mine if x["sana"] >= hafta_bosh)
    
    oy_bosh = endi.replace(day=1)
    oy = sum(1 for x in mine if x["sana"] >= oy_bosh)
    
    jami = len(mine)
    jami_ball = round(jami * 0.2, 1)

    matn = f"👤 *{ism.capitalize()}* statistikasi\n"
    matn += "━━━━━━━━━━━━━━━━━━━━\n"
    matn += f"📅 Bugun:    *{bugun} ta*\n"
    matn += f"📆 Bu hafta: *{hafta} ta*\n"
    matn += f"🗓 Bu oy:    *{oy} ta*\n"
    matn += f"📊 Jami:     *{jami} ta* (*{jami_ball} ball*)\n\n"
    matn += "📋 *So'nggi yozuvlar:*\n"

    for x in sorted(mine, key=lambda x: x["qoshilgan"], reverse=True)[:10]:
        kun_fmt = x["sana"].strftime("%d.%m.%Y")
        matn += f"  • {kun_fmt}: {x['xato_turi']}\n"

    return matn


# ==================== BUYRUQ HANDLERLARI ====================

async def javob_yuborish(update: Update, matn: str):
    if update.channel_post:
        await update.channel_post.reply_text(matn, parse_mode="Markdown")
    elif update.message:
        await update.message.reply_text(matn, parse_mode="Markdown")


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    matn = (
        "👋 Salom! Men xato kuzatuv botiman.\n\n"
        "📌 *Ishlash tartibi:*\n"
        "Kanalda xodim ismini hashtag bilan yozing:\n"
        "`#ism -xato_kodi sana` (sana ixtiyoriy)\n\n"
        "Masalan:\n"
        "• `#aziz -x1` (Azizga -DOGOVOR xatosi)\n"
        "• `#olim -x3 15.04.2024` (Olimga 15-aprel uchun -KONTRAGENT xatosi)\n\n"
        "*Xato kodlari:*\n"
        "x1: -DOGOVOR, x2: -KOMMENT, x3: -KONTRAGENT, x4: -NOMEKLATURA, x5: -KOLICHESTVO, "
        "x6: -PRIXOD, x7: -VOZVRAT, x8: -SPISANIYA, x9: -NAKLADNOY, x10: -SUMMA\n\n"
        "⚠️ *Eslatma:* Faqat yuqoridagi 10 ta xato turi hisobga olinadi. Boshqa har qanday yozuv e'tiborsiz qoldiriladi.\n\n"
        "*Buyruqlar:*\n"
        "/hafta, /oy, /bugun — hisobotlar\n"
        "/stat ism — xodim statistikasi\n"
        "/hammasi — barcha xodimlar\n"
        "/ochir — oxirgi xatoni o'chirish"
    )
    await javob_yuborish(update, matn)


async def hafta_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await javob_yuborish(update, await hisobot_yaratish("hafta"))


async def oy_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await javob_yuborish(update, await hisobot_yaratish("oy"))


async def bugun_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await javob_yuborish(update, await hisobot_yaratish("bugun"))


async def stat_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await javob_yuborish(update, "Ism kiriting: `/stat aziz`")
        return
    ism = " ".join(context.args).strip()
    await javob_yuborish(update, await xodim_stat(ism))


async def ochir_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    oxirgi = await delete_last_xato()
    if not oxirgi:
        await javob_yuborish(update, "O'chiriladigan yozuv yo'q.")
        return
    kun_fmt = oxirgi["sana"].strftime("%d.%m.%Y")
    await javob_yuborish(update, f"🗑 O'chirildi:\n👤 {oxirgi['ism']} | 📅 {kun_fmt}\n📝 Xato: {oxirgi['xato_turi']}")


async def hammasi_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    xatolar = await get_all_xatolar()
    if not xatolar:
        await javob_yuborish(update, "Hali xato kiritilmagan.")
        return
    ismlar = sorted(set(x["ism"] for x in xatolar))
    matn = "👥 *Barcha xodimlar:*\n\n"
    for ism in ismlar:
        jami = sum(1 for x in xatolar if x["ism"] == ism)
        matn += f"• *{ism}* — {jami} ta xato\n"
    await javob_yuborish(update, matn)


# ==================== ASOSIY LOGIKA ====================

async def xabar_qabul(update: Update, context: ContextTypes.DEFAULT_TYPE):
    message = update.channel_post or update.message
    if not message or not message.text:
        return

    matn = message.text

    if matn.startswith("/"):
        buyruq = matn.split()[0].replace("/", "").split("@")[0].lower()
        args = matn.split()[1:] if len(matn.split()) > 1 else []
        context.args = args

        if buyruq == "hafta": await hafta_cmd(update, context)
        elif buyruq == "oy": await oy_cmd(update, context)
        elif buyruq == "bugun": await bugun_cmd(update, context)
        elif buyruq == "hammasi": await hammasi_cmd(update, context)
        elif buyruq == "stat": await stat_cmd(update, context)
        elif buyruq == "ochir": await ochir_cmd(update, context)
        elif buyruq == "start": await start(update, context)
        return

    # 1. Ismlarni topish (#id yoki #ism)
    teglar = re.findall(r'#([a-zA-Z\u0400-\u04FF0-9_]+)', matn)
    if not teglar:
        return

    # 2. Sanani topish (DD.MM.YYYY)
    sana_match = re.search(r'(\d{1,2})\.(\d{1,2})\.(\d{4})', matn)
    hozir = get_now()
    if sana_match:
        try:
            sana = datetime.strptime(sana_match.group(0), "%d.%m.%Y").date()
        except:
            sana = hozir.date()
    else:
        sana = hozir.date()

    # 3. Xato turini topish (-x1 yoki -matn)
    xato_turi = None
    xato_match = re.search(r'-([^\s#]+(?: [^\s#]+)*)', matn)
    if xato_match:
        raw_xato = xato_match.group(1).strip()
        # Sanani xato matni ichidan olib tashlash
        if sana_match:
            raw_xato = raw_xato.replace(sana_match.group(0), "").strip()
        
        # Kodlarni yoki nomlarni tekshirish
        xato_matni = raw_xato.lower()
        # Uzunroq kodlarni birinchi tekshirish (masalan x10 dan oldin x1 ni emas)
        for k in sorted(XATO_KODLARI.keys(), key=len, reverse=True):
            if xato_matni == k or xato_matni.startswith(k):
                xato_turi = XATO_KODLARI[k]
                break
    
    if not xato_turi:
        return

    qoshilganlar = []
    sana_fmt = sana.strftime("%d.%m.%Y")

    for teg in teglar:
        ism = teg.capitalize()
        await add_xato(ism, sana, xato_turi)

        xatolar = await get_all_xatolar()
        mine = [x for x in xatolar if x["ism"] == ism]
        
        # Statlarda hozirgi kun/hafta/oyni Toshkent vaqti bilan hisoblash
        bugun_date = hozir.date()
        b_jami = sum(1 for x in mine if x["sana"] == bugun_date)
        h_jami = sum(1 for x in mine if x["sana"] >= bugun_date - timedelta(days=7))
        o_jami = sum(1 for x in mine if x["sana"] >= bugun_date.replace(day=1))

        qoshilganlar.append(
            f"👤 *{ism}*\n"
            f"   📝 Xato: *{xato_turi}*\n"
            f"   📅 Sana: *{sana_fmt}*\n"
            f"   📊 Bugun: *{b_jami} ta* | Hafta: *{h_jami}* | Oy: *{o_jami}*"
        )

    javob = "✅ *Xato qayd etildi!*\n\n" + "\n\n".join(qoshilganlar)
    await javob_yuborish(update, javob)


# ==================== HANDLERLARNI QO'SHISH ====================

def setup_application(app: Application):
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("hafta", hafta_cmd))
    app.add_handler(CommandHandler("oy", oy_cmd))
    app.add_handler(CommandHandler("bugun", bugun_cmd))
    app.add_handler(CommandHandler("stat", stat_cmd))
    app.add_handler(CommandHandler("ochir", ochir_cmd))
    app.add_handler(CommandHandler("hammasi", hammasi_cmd))
    app.add_handler(MessageHandler(filters.ALL, xabar_qabul))
    
    async def set_cmds(application):
        await application.bot.set_my_commands([
            BotCommand("hafta", "Haftalik hisobot"),
            BotCommand("oy", "Oylik hisobot"),
            BotCommand("bugun", "Bugungi hisobot"),
            BotCommand("stat", "Xodim statistikasi"),
            BotCommand("hammasi", "Barcha xodimlar"),
            BotCommand("ochir", "Oxirgi xatoni o'chirish"),
            BotCommand("start", "Botni boshlash"),
        ])
    app.post_init = set_cmds

def main():
    app = Application.builder().token(BOT_TOKEN).build()
    setup_application(app)
    print("✅ Bot (polling) ishga tushdi!")
    app.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == "__main__":
    main()