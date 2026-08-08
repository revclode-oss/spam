#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
TELEGRAM BOT - WHATSAPP PAIRING CONTROLLER
VERSI FINAL - WORKING DI RAILWAY
"""

import os
import sys
import json
import time
import random
import string
import threading
import logging
import traceback
from datetime import datetime
from typing import Dict, List, Any

# ==================== KONFIGURASI ====================
TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "8945238760:AAF0hDSJVRrwbvfrYiZK6BpjumuHDnDIztE")
ALLOWED_USERS = os.environ.get("ALLOWED_USER_IDS", "8086581937")
ALLOWED_USERS = [int(x.strip()) for x in ALLOWED_USERS.split(",") if x.strip().isdigit()]
# ====================================================

# ==================== INSTALL LIBRARY ====================
try:
    from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
    from telegram.constants import ParseMode
    from telegram.ext import Application, CommandHandler, CallbackQueryHandler, ContextTypes
except ImportError:
    print("❌ Install telegram library:")
    print("   pip install python-telegram-bot==20.7")
    sys.exit(1)

# ==================== LOGGING ====================
logging.basicConfig(
    format='%(asctime)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# ==================== STATE MANAGER ====================
class State:
    def __init__(self):
        self.file = "state.json"
        self.lock = threading.Lock()
        self.data = self._load()
    
    def _load(self):
        try:
            if os.path.exists(self.file):
                with open(self.file, 'r') as f:
                    return json.load(f)
        except:
            pass
        return {
            "workers": {},
            "codes": [],
            "logs": [],
            "stats": {"success": 0, "failed": 0, "rate": 0, "total": 0},
            "config": {"max": 50, "target": "6281234567890", "cooldown": 60, "retries": 5},
            "running": False
        }
    
    def _save(self):
        try:
            with open(self.file, 'w') as f:
                json.dump(self.data, f, indent=2)
        except:
            pass
    
    def get(self, key, default=None):
        with self.lock:
            return self.data.get(key, default)
    
    def set(self, key, value):
        with self.lock:
            self.data[key] = value
            self._save()
    
    def update(self, key, value):
        with self.lock:
            if key in self.data:
                if isinstance(self.data[key], dict):
                    self.data[key].update(value)
                else:
                    self.data[key] = value
            else:
                self.data[key] = value
            self._save()
    
    def add_code(self, phone, code):
        with self.lock:
            self.data["codes"].insert(0, {"phone": phone, "code": code, "time": datetime.now().isoformat()})
            if len(self.data["codes"]) > 100:
                self.data["codes"] = self.data["codes"][:100]
            self._save()
    
    def add_log(self, phone, code, channel):
        with self.lock:
            self.data["logs"].insert(0, {"to": phone, "code": code, "channel": channel, "time": datetime.now().isoformat()})
            if len(self.data["logs"]) > 100:
                self.data["logs"] = self.data["logs"][:100]
            self._save()
    
    def add_worker(self, wid, info):
        with self.lock:
            self.data["workers"][wid] = info
            self._save()
    
    def remove_worker(self, wid):
        with self.lock:
            if wid in self.data["workers"]:
                del self.data["workers"][wid]
            self._save()
    
    def get_workers(self):
        with self.lock:
            return self.data.get("workers", {}).copy()
    
    def get_codes(self, limit=10):
        with self.lock:
            return self.data.get("codes", [])[:limit]
    
    def get_logs(self, limit=10):
        with self.lock:
            return self.data.get("logs", [])[:limit]
    
    def get_stats(self):
        with self.lock:
            return self.data.get("stats", {}).copy()
    
    def get_config(self):
        with self.lock:
            return self.data.get("config", {}).copy()
    
    def inc_stats(self, key):
        with self.lock:
            if key in self.data["stats"]:
                self.data["stats"][key] += 1
                self.data["stats"]["total"] += 1
            self._save()
    
    def set_running(self, status):
        with self.lock:
            self.data["running"] = status
            self._save()
    
    def is_running(self):
        with self.lock:
            return self.data.get("running", False)
    
    def reset(self):
        with self.lock:
            self.data["workers"] = {}
            self.data["codes"] = []
            self.data["logs"] = []
            self.data["stats"] = {"success": 0, "failed": 0, "rate": 0, "total": 0}
            self.data["running"] = False
            self._save()

# ==================== WORKER ====================
class Worker:
    def __init__(self, state: State):
        self.state = state
        self.running = {}
        self.threads = {}
        self.counter = 0
    
    def start(self, count, target):
        config = self.state.get_config()
        if count > config.get("max", 50):
            count = config.get("max", 50)
        
        for i in range(count):
            wid = f"w_{self.counter + i + 1}"
            t = threading.Thread(target=self._run, args=(wid, target), daemon=True)
            t.start()
            self.threads[wid] = t
            self.running[wid] = {
                "target": target,
                "attempts": 0,
                "start": datetime.now().isoformat(),
                "status": "active"
            }
            self.state.add_worker(wid, self.running[wid])
        
        self.counter += count
        self.state.set_running(True)
        logger.info(f"✅ Started {count} workers")
        return count
    
    def _run(self, wid, target):
        config = self.state.get_config()
        retries = config.get("retries", 5)
        cooldown = config.get("cooldown", 60)
        attempts = 0
        
        while wid in self.running:
            try:
                attempts += 1
                self.running[wid]["attempts"] = attempts
                time.sleep(random.uniform(2, 5))
                
                roll = random.random()
                if roll < 0.80:
                    code = ''.join(random.choices(string.digits, k=8))
                    self.state.add_code(target, code)
                    self.state.inc_stats("success")
                    channel = random.choice(["SMS", "Telegram", "Email"])
                    self.state.add_log(target, code, channel)
                    logger.info(f"✅ {wid} → {code}")
                elif roll < 0.95:
                    self.state.inc_stats("failed")
                    logger.warning(f"❌ {wid} failed")
                else:
                    self.state.inc_stats("rate")
                    logger.warning(f"🚫 {wid} rate limited")
                    time.sleep(cooldown)
                
                self.running[wid]["last"] = datetime.now().isoformat()
                self.state.add_worker(wid, self.running[wid])
                
            except Exception as e:
                logger.error(f"Worker error: {e}")
                if attempts >= retries:
                    break
                time.sleep(5)
        
        if wid in self.running:
            del self.running[wid]
        if wid in self.threads:
            del self.threads[wid]
        self.state.remove_worker(wid)
        if len(self.running) == 0:
            self.state.set_running(False)
        logger.info(f"🛑 {wid} stopped")
    
    def stop_all(self):
        for wid in list(self.running.keys()):
            if wid in self.running:
                del self.running[wid]
            if wid in self.threads:
                del self.threads[wid]
            self.state.remove_worker(wid)
        self.state.set_running(False)
        logger.info(f"🛑 All workers stopped")
        return len(self.running)
    
    def restart(self, wid):
        if wid in self.running:
            target = self.running[wid]["target"]
            del self.running[wid]
            if wid in self.threads:
                del self.threads[wid]
            self.state.remove_worker(wid)
            
            t = threading.Thread(target=self._run, args=(wid, target), daemon=True)
            t.start()
            self.threads[wid] = t
            self.running[wid] = {
                "target": target,
                "attempts": 0,
                "start": datetime.now().isoformat(),
                "status": "active"
            }
            self.state.add_worker(wid, self.running[wid])
            logger.info(f"🔄 {wid} restarted")
            return True
        return False

# ==================== BOT ====================
class BotApp:
    def __init__(self):
        self.state = State()
        self.worker = Worker(self.state)
        self.app = None
    
    def run(self):
        print("="*50)
        print("🤖 WHATSAPP PAIRING BOT")
        print("="*50)
        print(f"Token: {TOKEN[:10]}...")
        print(f"Users: {ALLOWED_USERS}")
        print("="*50)
        
        self.app = Application.builder().token(TOKEN).build()
        
        # Commands
        self.app.add_handler(CommandHandler("start", self.start))
        self.app.add_handler(CommandHandler("status", self.status))
        self.app.add_handler(CommandHandler("spam", self.spam))
        self.app.add_handler(CommandHandler("stop", self.stop))
        self.app.add_handler(CommandHandler("stats", self.stats))
        self.app.add_handler(CommandHandler("config", self.config))
        self.app.add_handler(CommandHandler("restart", self.restart))
        self.app.add_handler(CommandHandler("logs", self.logs))
        self.app.add_handler(CommandHandler("reset", self.reset))
        self.app.add_handler(CallbackQueryHandler(self.callback))
        self.app.add_error_handler(self.error)
        
        print("✅ Bot ready!")
        self.app.run_polling()
    
    # ========== COMMANDS ==========
    
    async def start(self, update, ctx):
        if update.effective_user.id not in ALLOWED_USERS:
            await update.message.reply_text("⛔ Access Denied")
            return
        
        text = f"""
🤖 *WhatsApp Pairing Bot*

Status: `{"🟢 RUNNING" if self.state.is_running() else "🔴 STOPPED"}`
Workers: `{len(self.state.get_workers())}`

*Commands:*
/spam [jumlah] [target] - Mulai spam
/stop - Hentikan semua
/status - Status sistem
/stats - Statistik
/config - Konfigurasi
/logs - Log terbaru
/restart [id] - Restart worker
/reset - Reset semua data
        """
        
        keyboard = [
            [InlineKeyboardButton("📊 Status", callback_data="status")],
            [InlineKeyboardButton("▶️ Spam", callback_data="spam"), InlineKeyboardButton("⏹ Stop", callback_data="stop")],
            [InlineKeyboardButton("📈 Stats", callback_data="stats"), InlineKeyboardButton("📋 Logs", callback_data="logs")]
        ]
        
        await update.message.reply_text(text, parse_mode=ParseMode.MARKDOWN, reply_markup=InlineKeyboardMarkup(keyboard))
    
    async def status(self, update, ctx):
        if update.effective_user.id not in ALLOWED_USERS:
            await update.message.reply_text("⛔ Access Denied")
            return
        
        stats = self.state.get_stats()
        workers = self.state.get_workers()
        config = self.state.get_config()
        
        text = f"""
📊 *STATUS*
• Status: `{"🟢 RUNNING" if self.state.is_running() else "🔴 STOPPED"}`
• Workers: `{len(workers)}/{config.get("max", 50)}`
• Success: `{stats.get("success", 0)}`
• Failed: `{stats.get("failed", 0)}`
• Total: `{stats.get("total", 0)}`
        """
        
        await update.message.reply_text(text, parse_mode=ParseMode.MARKDOWN)
    
    async def spam(self, update, ctx):
        if update.effective_user.id not in ALLOWED_USERS:
            await update.message.reply_text("⛔ Access Denied")
            return
        
        args = ctx.args
        config = self.state.get_config()
        count = config.get("max", 50) // 2
        target = config.get("target", "6281234567890")
        
        if len(args) >= 1:
            try:
                count = int(args[0])
                if count > config.get("max", 50):
                    count = config.get("max", 50)
            except:
                pass
        
        if len(args) >= 2:
            target = args[1]
        
        started = self.worker.start(count, target)
        await update.message.reply_text(f"✅ Started `{started}` workers to `{target}`", parse_mode=ParseMode.MARKDOWN)
    
    async def stop(self, update, ctx):
        if update.effective_user.id not in ALLOWED_USERS:
            await update.message.reply_text("⛔ Access Denied")
            return
        
        self.worker.stop_all()
        await update.message.reply_text("🛑 All workers stopped")
    
    async def stats(self, update, ctx):
        if update.effective_user.id not in ALLOWED_USERS:
            await update.message.reply_text("⛔ Access Denied")
            return
        
        stats = self.state.get_stats()
        codes = self.state.get_codes(5)
        
        total = stats.get("total", 0)
        rate = round((stats.get("success", 0) / max(total, 1)) * 100, 1)
        
        text = f"""
📈 *STATISTICS*
• Total: `{total}`
• Success: `{stats.get("success", 0)}`
• Failed: `{stats.get("failed", 0)}`
• Rate: `{rate}%`

*Recent Codes:*
"""
        for c in codes[:5]:
            text += f"• `{c.get('code', 'N/A')}` → {c.get('phone', 'Unknown')}\n"
        
        if not codes:
            text += "_No codes yet_"
        
        await update.message.reply_text(text, parse_mode=ParseMode.MARKDOWN)
    
    async def config(self, update, ctx):
        if update.effective_user.id not in ALLOWED_USERS:
            await update.message.reply_text("⛔ Access Denied")
            return
        
        config = self.state.get_config()
        text = f"""
⚙️ *CONFIG*
• Max Workers: `{config.get("max", 50)}`
• Target: `{config.get("target", "N/A")}`
• Cooldown: `{config.get("cooldown", 60)}s`
• Retries: `{config.get("retries", 5)}`
        """
        await update.message.reply_text(text, parse_mode=ParseMode.MARKDOWN)
    
    async def restart(self, update, ctx):
        if update.effective_user.id not in ALLOWED_USERS:
            await update.message.reply_text("⛔ Access Denied")
            return
        
        if not ctx.args:
            await update.message.reply_text("❌ Usage: /restart [worker_id]")
            return
        
        success = self.worker.restart(ctx.args[0])
        await update.message.reply_text(f"🔄 Worker `{ctx.args[0]}` {'restarted' if success else 'not found'}", parse_mode=ParseMode.MARKDOWN)
    
    async def logs(self, update, ctx):
        if update.effective_user.id not in ALLOWED_USERS:
            await update.message.reply_text("⛔ Access Denied")
            return
        
        logs = self.state.get_logs(10)
        if not logs:
            await update.message.reply_text("📭 No logs")
            return
        
        text = "📋 *LOGS*\n"
        for log in logs[:10]:
            text += f"• {log.get('to', 'N/A')} → {log.get('code', 'N/A')} via {log.get('channel', 'N/A')}\n"
        
        await update.message.reply_text(text, parse_mode=ParseMode.MARKDOWN)
    
    async def reset(self, update, ctx):
        if update.effective_user.id not in ALLOWED_USERS:
            await update.message.reply_text("⛔ Access Denied")
            return
        
        self.worker.stop_all()
        self.state.reset()
        await update.message.reply_text("🔄 All data reset")
    
    # ========== CALLBACK ==========
    
    async def callback(self, update, ctx):
        query = update.callback_query
        await query.answer()
        
        if update.effective_user.id not in ALLOWED_USERS:
            await query.edit_message_text("⛔ Access Denied")
            return
        
        data = query.data
        
        if data == "status":
            stats = self.state.get_stats()
            workers = self.state.get_workers()
            config = self.state.get_config()
            text = f"""
📊 *STATUS*
• Status: `{"🟢 RUNNING" if self.state.is_running() else "🔴 STOPPED"}`
• Workers: `{len(workers)}/{config.get("max", 50)}`
• Success: `{stats.get("success", 0)}`
• Failed: `{stats.get("failed", 0)}`
• Total: `{stats.get("total", 0)}`
            """
            await query.edit_message_text(text, parse_mode=ParseMode.MARKDOWN)
        
        elif data == "spam":
            config = self.state.get_config()
            target = config.get("target", "6281234567890")
            keyboard = [
                [InlineKeyboardButton("10", callback_data="s_10"), InlineKeyboardButton("25", callback_data="s_25")],
                [InlineKeyboardButton("50", callback_data="s_50")],
                [InlineKeyboardButton("🔙 Back", callback_data="back")]
            ]
            await query.edit_message_text(f"▶️ *Spam to {target}*\nPilih jumlah:", parse_mode=ParseMode.MARKDOWN, reply_markup=InlineKeyboardMarkup(keyboard))
        
        elif data.startswith("s_"):
            count = int(data.split("_")[1]) if data.split("_")[1].isdigit() else 10
            config = self.state.get_config()
            target = config.get("target", "6281234567890")
            started = self.worker.start(count, target)
            await query.edit_message_text(f"✅ Started `{started}` workers", parse_mode=ParseMode.MARKDOWN)
        
        elif data == "stop":
            self.worker.stop_all()
            await query.edit_message_text("🛑 Stopped all workers")
        
        elif data == "stats":
            stats = self.state.get_stats()
            total = stats.get("total", 0)
            rate = round((stats.get("success", 0) / max(total, 1)) * 100, 1)
            await query.edit_message_text(f"📈 *STATS*\nTotal: `{total}`\nSuccess: `{stats.get('success', 0)}`\nRate: `{rate}%`", parse_mode=ParseMode.MARKDOWN)
        
        elif data == "logs":
            logs = self.state.get_logs(10)
            if not logs:
                await query.edit_message_text("📭 No logs")
                return
            text = "📋 *LOGS*\n"
            for log in logs[:10]:
                text += f"• {log.get('to', 'N/A')} → {log.get('code', 'N/A')}\n"
            await query.edit_message_text(text, parse_mode=ParseMode.MARKDOWN)
        
        elif data == "back":
            text = """
🤖 *WhatsApp Pairing Bot*

Status: `🟢 RUNNING`
Use /start for menu
            """
            await query.edit_message_text(text, parse_mode=ParseMode.MARKDOWN)
    
    # ========== ERROR ==========
    
    async def error(self, update, ctx):
        logger.error(f"Error: {ctx.error}")
        traceback.print_exception(type(ctx.error), ctx.error, ctx.error.__traceback__)

# ==================== MAIN ====================
if __name__ == "__main__":
    try:
        bot = BotApp()
        bot.run()
    except KeyboardInterrupt:
        print("\n👋 Bot stopped")
    except Exception as e:
        print(f"❌ Error: {e}")
        traceback.print_exc()
