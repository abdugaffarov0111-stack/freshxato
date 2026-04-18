# bot.py
# pip install python-telegram-bot asyncpg

import os
import re
import asyncio
import asyncpg
from datetime import datetime, timedelta
from collections import defaultdict
from telegram import Update, BotCommand
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes
from dotenv import load_dotenv

load_dotenv()

# ==================== SOZLAMALAR ====================
BOT_TOKEN = os.getenv("BOT_TOKEN", "8321131397:AAH1LgiIB1nmMNY_BBLhp5sKOE_blYsPfWk")
DATABASE_URL = os.getenv("DATABASE_URL")

# Pool obyekti (api/index.py dan o'rnatiladi)
db_pool = None

async def get_pool():
    global db_pool
    if db_pool is None:
        db_pool = await asyncpg.create_pool(DATABASE_URL, ssl="require")
    return db_pool

# ==================== MA'LUMOTLAR BILAN ISHLASH ====================

async def get_all_xatolar():
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch("SELECT ism, sana, qoshilgan FROM xatolar")
        return [dict(r) for r in rows]

async def add_xato(ism, sana):
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            "INSERT INTO xatolar (ism, sana) VALUES ($1, $2)",
            ism.capitalize(), sana
        )

async def delete_last_xato():
    pool = await get_pool()
    async with pool.acquire() as conn:
        # Oxirgi qo'shilganini topib o'chirish
        row = await conn.fetchrow("SELECT id, ism, sana FROM xatolar ORDER BY qoshilgan DESC LIMIT 1")
        if row:
            await conn.execute("DELETE FROM xatolar WHERE id = $1", row['id'])
            return dict(row)
    return None

# ==================== HISOBOT LOGIKASI ====================

async def hisobot_yaratish(davr="hafta"):
    xatolar = await get_all_xatolar()
    endi = datetime.now()

    if davr == "hafta":
        bosh = endi - timedelta(days=7)
        nom = "HAFTALIK"
    elif davr == "oy":
        bosh = endi.replace(day=1, hour=0, minute=0, second=0)
        nom = "OYLIK"
    else:
        bosh = endi.replace(hour=0, minute=0, second=0)
        nom = "BUGUNGI"

    # PostgreSQL da sana 'date' obyektidir
    filtered = [
        x for x in xatolar
        if (x["sana"] if isinstance(x["sana"], datetime) else datetime.combine(x["sana"], datetime.min.time())) >= bosh
    ]

    if not filtered:
        return "📭 Bu davrda xato topilmadi."

    stat = defaultdict(lambda: {"jami": 0, "kunlar": defaultdict(int)})
    for x in filtered:
        sana_str = x["sana"].strftime("%Y-%m-%d") if not isinstance(x["sana"], str) else x["sana"]
        stat[x["ism"]]["jami"] += 1
        stat[x["ism"]]["kunlar"][sana_str] += 1

    matn = f"📊 *{nom} HISOBOT*\n"
    matn += f"📅 {bosh.strftime('%d.%m.%Y')} — {endi.strftime('%d.%m.%Y')}\n"
    matn += "━━━━━━━━━━━━━━━━━━━━\n\n"
    matn += f"🔢 Jami: *{len(filtered)} ta xato*\n"
    matn += f"👥 Xodimlar: *{len(stat)} ta*\n\n"

    for ism, s in sorted(stat.items(), key=lambda x: -x[1]["jami"]):
        emoji = "🔴" if s["jami"] >= 5 else "🟡" if s["jami"] >= 3 else "🟢"
        matn += f"{emoji} *{ism}* — {s['jami']} ta xato\n"
        for kun in sorted(s["kunlar"]):
            # kun allaqachon string yoki date
            kun_fmt = datetime.strptime(kun, "%Y-%m-%d").strftime("%d.%m.%Y") if isinstance(kun, str) else kun.strftime("%d.%m.%Y")
            matn += f"   📍 {kun_fmt}: {s['kunlar'][kun]} ta\n"
        matn += "\n"

    matn += "━━━━━━━━━━━━━━━━━━━━\n✅ Hisobot tayyor"
    return matn


async def xodim_stat(ism):
    xatolar = await get_all_xatolar()
    endi = datetime.now()

    mine = [x for x in xatolar if x["ism"].lower() == ism.lower()]
    if not mine:
        return f"❌ *{ism}* bo'yicha yozuv topilmadi."

    bugun_str = endi.date()
    bugun = sum(1 for x in mine if x["sana"] == bugun_str)
    
    hafta_bosh = endi.date() - timedelta(days=7)
    hafta = sum(1 for x in mine if x["sana"] >= hafta_bosh)
    
    oy_bosh = endi.date().replace(day=1)
    oy = sum(1 for x in mine if x["sana"] >= oy_bosh)
    
    jami = len(mine)

    matn = f"👤 *{ism.capitalize()}* statistikasi\n"
    matn += "━━━━━━━━━━━━━━━━━━━━\n"
    matn += f"📅 Bugun:    *{bugun} ta*\n"
    matn += f"📆 Bu hafta: *{hafta} ta*\n"
    matn += f"🗓 Bu oy:    *{oy} ta*\n"
    matn += f"📊 Jami:     *{jami} ta*\n\n"
    matn += "📋 *So'nggi yozuvlar:*\n"

    for x in sorted(mine, key=lambda x: x["qoshilgan"], reverse=True)[:5]:
        kun_fmt = x["sana"].strftime("%d.%m.%Y")
        matn += f"  • {kun_fmt}: 1 ta\n"

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
        "Kanalda `#ism` yozsangiz, o'sha xodimga 1 xato qo'shiladi.\n\n"
        "Masalan: `#aziz` → Azizga 1 xato\n\n"
        "*Buyruqlar:*\n"
        "/hafta — haftalik hisobot\n"
        "/oy — oylik hisobot\n"
        "/bugun — bugungi hisobot\n"
        "/stat aziz — Aziz statistikasi\n"
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
    await javob_yuborish(update, f"🗑 O'chirildi:\n👤 {oxirgi['ism']} | 📅 {kun_fmt}")


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

    teglar = re.findall(r'#([a-zA-Z\u0400-\u04FFa-zA-Z]+)', matn)
    if not teglar:
        return

    bugun = datetime.now().date()
    bugun_fmt = datetime.now().strftime("%d.%m.%Y")
    qoshilganlar = []

    for teg in teglar:
        ism = teg.capitalize()
        await add_xato(ism, bugun)

        xatolar = await get_all_xatolar()
        mine = [x for x in xatolar if x["ism"] == ism]
        
        b_jami = sum(1 for x in mine if x["sana"] == bugun)
        h_jami = sum(1 for x in mine if x["sana"] >= datetime.now().date() - timedelta(days=7))
        o_jami = sum(1 for x in mine if x["sana"] >= datetime.now().date().replace(day=1))

        qoshilganlar.append(
            f"👤 *{ism}*\n"
            f"   📅 Bugun ({bugun_fmt}): *{b_jami} ta*\n"
            f"   📆 Bu hafta: *{h_jami} ta*\n"
            f"   🗓 Bu oy: *{o_jami} ta*"
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