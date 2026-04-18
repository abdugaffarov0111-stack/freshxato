import os
import asyncio
from fastapi import FastAPI, Request
from telegram import Update
from telegram.ext import Application
from bot import setup_application, BOT_TOKEN

app = FastAPI()

# PTB Application yaratish
# Webhook holatida polling ishlatilmaydi
telegram_app = Application.builder().token(BOT_TOKEN).build()
setup_application(telegram_app)

@app.on_event("startup")
async def startup():
    # Botni ishga tushirish (polling-siz)
    await telegram_app.initialize()
    await telegram_app.start()

@app.on_event("shutdown")
async def shutdown():
    await telegram_app.stop()
    await telegram_app.shutdown()

@app.post("/api/index")
async def webhook(request: Request):
    # Telegramdan kelgan JSON dan Update obyektini yaratish
    data = await request.json()
    update = Update.de_json(data, telegram_app.bot)
    
    # Xabarni PTB ga uzatish
    await telegram_app.process_update(update)
    
    return {"ok": True}

@app.get("/")
async def root():
    return {"message": "Xato Bot ishlamoqda!"}
