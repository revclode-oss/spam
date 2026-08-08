#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
TELEGRAM BOT CONTROLLER - RAILWAY VERSION
Tanpa Redis - Langsung Run
"""

import asyncio
import json
import logging
import os
import sys
import time
import threading
import random
import string
from datetime import datetime
from typing import Dict, List, Any
from collections import defaultdict
import traceback

# ==================== KONFIGURASI DARI ENVIRONMENT ====================
# Railway menggunakan environment variables
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "7741123456:AAHdflkjsdflkjsdflkjsdflkjsdflkjsdflk")
ALLOWED_USER_IDS = os.environ.get("ALLOWED_USER_IDS", "123456789")
# Parse ALLOWED_USER_IDS (bisa multiple IDs dipisah koma)
ALLOWED_USER_IDS = [int(x.strip()) for x in ALLOWED_USER_IDS.split(",") if x.strip().isdigit()]
# ====================================================

# ==================== LIBRARY ====================
try:
    from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, ParseMode
    from telegram.ext import Application, CommandHandler, CallbackQueryHandler, ContextTypes
    from telegram.constants import ChatAction
except ImportError as e:
    print(f"❌ Library error: {e}")
    print("   Jalankan: pip install python-telegram-bot==20.6")
    sys.exit(1)

# ==================== LOGGING ====================
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# ==================== STATE MANAGER ====================
class StateManager:
    """Menyimpan semua state di memory dan backup ke file JSON"""
    
    def __init__(self):
        self.state_file = "bot_state.json"
        self.data = {
            "metrics": {
                "active_workers": 0,
                "total_sessions": 0,
                "success_count": 0,
                "failed_count": 0,
                "rate_limit_count": 0,
                "total_attempts": 0,
                "last_updated": None
            },
            "workers": {},
            "pairing_codes": [],
            "delivery_logs": [],
            "active_sessions": {},
            "config": {
                "max_workers": 50,
                "default_target": "6281234567890",
                "cooldown_seconds": 60,
                "max_retries": 5
            },
            "system": {
                "started_at": datetime.now().isoformat(),
                "is_running": False,
                "total_processed": 0
            }
        }
        self.lock = threading.Lock()
        self._load_state()
    
    def _load_state(self):
        try:
            if os.path.exists(self.state_file):
                with open(self.state_file, 'r') as f:
                    saved = json.load(f)
                    for key in self.data:
                        if key in saved:
                            if isinstance(self.data[key], dict) and isinstance(saved[key], dict):
                                self.data[key].update(saved[key])
                            else:
                                self.data[key] = saved[key]
                    logger.info(f"✅ State loaded from {self.state_file}")
        except Exception as e:
            logger.warning(f"Could not load state: {e}")
    
    def _save_state(self):
        try:
            with open(self.state_file, 'w') as f:
                json.dump(self.data, f, indent=2, default=str)
        except Exception as e:
            logger.error(f"Failed to save state: {e}")
    
    def get_metrics(self) -> Dict:
        with self.lock:
            return self.data["metrics"].copy()
    
    def update_metrics(self, **kwargs):
        with self.lock:
            for key, value in kwargs.items():
                if key in self.data["metrics"]:
                    self.data["metrics"][key] = value
            self.data["metrics"]["last_updated"] = datetime.now().isoformat()
            self._save_state()
    
    def add_worker(self, worker_id: str, info: Dict):
        with self.lock:
            self.data["workers"][worker_id] = info
            self.data["metrics"]["total_sessions"] = len(self.data["workers"])
            self._save_state()
    
    def remove_worker(self, worker_id: str):
        with self.lock:
            if worker_id in self.data["workers"]:
                del self.data["workers"][worker_id]
            self.data["metrics"]["total_sessions"] = len(self.data["workers"])
            self._save_state()
    
    def get_workers(self) -> Dict:
        with self.lock:
            return self.data["workers"].copy()
    
    def add_pairing_code(self, phone: str, code: str):
        with self.lock:
            entry = {"phone": phone, "code": code, "timestamp": datetime.now().isoformat()}
            self.data["pairing_codes"].insert(0, entry)
            if len(self.data["pairing_codes"]) > 100:
                self.data["pairing_codes"] = self.data["pairing_codes"][:100]
            self.data["system"]["total_processed"] += 1
            self._save_state()
    
    def add_delivery_log(self, phone: str, code: str, channel: str):
        with self.lock:
            entry = {"to": phone, "code": code, "channel": channel, "timestamp": datetime.now().isoformat()}
            self.data["delivery_logs"].insert(0, entry)
            if len(self.data["delivery_logs"]) > 100:
                self.data["delivery_logs"] = self.data["delivery_logs"][:100]
            self._save_state()
    
    def get_delivery_logs(self, limit: int = 20) -> List:
        with self.lock:
            return self.data["delivery_logs"][:limit]
    
    def get_pairing_codes(self, limit: int = 10) -> List:
        with self.lock:
            return self.data["pairing_codes"][:limit]
    
    def update_config(self, **kwargs):
        with self.lock:
            for key, value in kwargs.items():
                if key in self.data["config"]:
                    self.data["config"][key] = value
            self._save_state()
    
    def get_config(self) -> Dict:
        with self.lock:
            return self.data["config"].copy()
    
    def set_running(self, status: bool):
        with self.lock:
            self.data["system"]["is_running"] = status
            self._save_state()
    
    def is_running(self) -> bool:
        with self.lock:
            return self.data["system"]["is_running"]
    
    def reset_all(self):
        with self.lock:
            self.data["metrics"] = {
                "active_workers": 0,
                "total_sessions": 0,
                "success_count": 0,
                "failed_count": 0,
                "rate_limit_count": 0,
                "total_attempts": 0,
                "last_updated": None
            }
            self.data["workers"] = {}
            self.data["pairing_codes"] = []
            self.data["delivery_logs"] = []
            self.data["system"]["total_processed"] = 0
            self._save_state()

# ==================== WORKER SIMULATOR ====================
class WorkerSimulator:
    def __init__(self, state_manager: StateManager):
        self.state = state_manager
        self.running_workers = {}
        self.worker_threads = {}
        self.worker_counter = 0
        self.lock = threading.Lock()
    
    def start_workers(self, count: int, target: str):
        if count > self.state.get_config()["max_workers"]:
            count = self.state.get_config()["max_workers"]
        
        for i in range(count):
            worker_id = f"worker_{self.worker_counter + i + 1}"
            thread = threading.Thread(target=self._run_worker, args=(worker_id, target), daemon=True)
            thread.start()
            self.worker_threads[worker_id] = thread
            self.running_workers[worker_id] = {
                "status": "active",
                "target": target,
                "attempts": 0,
                "started_at": datetime.now().isoformat(),
                "proxy": f"proxy_{random.randint(1, 10)}"
            }
            self.state.add_worker(worker_id, self.running_workers[worker_id])
        
        self.worker_counter += count
        self.state.update_metrics(active_workers=len(self.running_workers))
        self.state.set_running(True)
        
        logger.info(f"Started {count} workers targeting {target}")
        return count
    
    def _run_worker(self, worker_id: str, target: str):
        import time
        max_retries = self.state.get_config()["max_retries"]
        attempts = 0
        
        while worker_id in self.running_workers:
            try:
                attempts += 1
                self.running_workers[worker_id]["attempts"] = attempts
                time.sleep(random.uniform(2, 5))
                roll = random.random()
                
                if roll < 0.80:
                    code = ''.join(random.choices(string.digits, k=8))
                    self.state.add_pairing_code(target, code)
                    self.state.update_metrics(
                        success_count=self.state.get_metrics()["success_count"] + 1,
                        total_attempts=self.state.get_metrics()["total_attempts"] + 1
                    )
                    channel = random.choice(["SMS", "Telegram", "Email", "WhatsApp"])
                    self.state.add_delivery_log(target, code, channel)
                    logger.info(f"✅ {worker_id} → Code {code} for {target} via {channel}")
                elif roll < 0.95:
                    self.state.update_metrics(
                        failed_count=self.state.get_metrics()["failed_count"] + 1,
                        total_attempts=self.state.get_metrics()["total_attempts"] + 1
                    )
                    logger.warning(f"❌ {worker_id} failed for {target}")
                else:
                    self.state.update_metrics(
                        rate_limit_count=self.state.get_metrics()["rate_limit_count"] + 1
                    )
                    logger.warning(f"🚫 {worker_id} rate limited for {target}")
                    time.sleep(self.state.get_config()["cooldown_seconds"])
                
                self.running_workers[worker_id]["last_heartbeat"] = datetime.now().isoformat()
                self.state.add_worker(worker_id, self.running_workers[worker_id])
            except Exception as e:
                logger.error(f"Worker {worker_id} error: {e}")
                if attempts >= max_retries:
                    break
                time.sleep(5)
        
        if worker_id in self.running_workers:
            del self.running_workers[worker_id]
        if worker_id in self.worker_threads:
            del self.worker_threads[worker_id]
        self.state.remove_worker(worker_id)
        self.state.update_metrics(active_workers=len(self.running_workers))
        if len(self.running_workers) == 0:
            self.state.set_running(False)
        logger.info(f"🛑 Worker {worker_id} stopped")
    
    def stop_all_workers(self):
        worker_ids = list(self.running_workers.keys())
        for wid in worker_ids:
            if wid in self.running_workers:
                del self.running_workers[wid]
            if wid in self.worker_threads:
                del self.worker_threads[wid]
            self.state.remove_worker(wid)
        self.state.update_metrics(active_workers=0)
        self.state.set_running(False)
        logger.info(f"🛑 All {len(worker_ids)} workers stopped")
        return len(worker_ids)
    
    def restart_worker(self, worker_id: str):
        if worker_id in self.running_workers:
            target = self.running_workers[worker_id]["target"]
            del self.running_workers[worker_id]
            if worker_id in self.worker_threads:
                del self.worker_threads[worker_id]
            self.state.remove_worker(worker_id)
            thread = threading.Thread(target=self._run_worker, args=(worker_id, target), daemon=True)
            thread.start()
            self.worker_threads[worker_id] = thread
            self.running_workers[worker_id] = {
                "status": "active",
                "target": target,
                "attempts": 0,
                "started_at": datetime.now().isoformat(),
                "proxy": f"proxy_{random.randint(1, 10)}"
            }
            self.state.add_worker(worker_id, self.running_workers[worker_id])
            logger.info(f"🔄 Worker {worker_id} restarted")
            return True
        return False
    
    def get_status(self) -> Dict:
        return {"active": len(self.running_workers), "workers": self.running_workers.copy()}

# ==================== TELEGRAM BOT ====================
class PairingBot:
    def __init__(self):
        self.state = StateManager()
        self.worker = WorkerSimulator(self.state)
        self.application = None
        self.bot_username = "WhatsAppPairingBot"
    
    def setup_application(self):
        self.application = Application.builder().token(TELEGRAM_BOT_TOKEN).build()
        self.application.add_handler(CommandHandler("start", self.start_command))
        self.application.add_handler(CommandHandler("status", self.status_command))
        self.application.add_handler(CommandHandler("start_spam", self.start_spam_command))
        self.application.add_handler(CommandHandler("stop_spam", self.stop_spam_command))
        self.application.add_handler(CommandHandler("stats", self.stats_command))
        self.application.add_handler(CommandHandler("config", self.config_command))
        self.application.add_handler(CommandHandler("restart_worker", self.restart_worker_command))
        self.application.add_handler(CommandHandler("logs", self.logs_command))
        self.application.add_handler(CommandHandler("reset", self.reset_command))
        self.application.add_handler(CallbackQueryHandler(self.callback_handler))
        self.application.add_error_handler(self._error_handler)
        logger.info("✅ Bot application setup complete")
        return self.application
    
    async def start_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        user_id = update.effective_user.id
        if user_id not in ALLOWED_USER_IDS:
            await update.message.reply_text("⛔ *Access Denied*", parse_mode=ParseMode.MARKDOWN)
            return
        
        status = "🟢 RUNNING" if self.state.is_running() else "🔴 STOPPED"
        welcome_text = f"""
🤖 *WHATSAPP PAIRING BOT* - RAILWAY

*Status:* {status}
*Active Workers:* `{self.state.get_metrics()['active_workers']}`
*Total Processed:* `{self.state.get_metrics()['total_attempts']}`

*Commands:*
• `/status` - Status sistem
• `/start_spam [jumlah] [target]` - Mulai spam
• `/stop_spam` - Hentikan semua
• `/stats` - Statistik lengkap
• `/config` - Konfigurasi
• `/logs` - Log terbaru
• `/reset` - Reset semua data
        """
        keyboard = [
            [InlineKeyboardButton("📊 Status", callback_data="status"), InlineKeyboardButton("📈 Stats", callback_data="stats")],
            [InlineKeyboardButton("▶️ Start Spam", callback_data="start_spam"), InlineKeyboardButton("⏹ Stop", callback_data="stop_spam")],
            [InlineKeyboardButton("📋 Logs", callback_data="logs"), InlineKeyboardButton("⚙️ Config", callback_data="config")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await update.message.reply_text(welcome_text, parse_mode=ParseMode.MARKDOWN, reply_markup=reply_markup)
    
    async def status_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        user_id = update.effective_user.id
        if user_id not in ALLOWED_USER_IDS:
            await update.message.reply_text("⛔ Access Denied")
            return
        await update.message.chat.send_action(action=ChatAction.TYPING)
        metrics = self.state.get_metrics()
        workers = self.state.get_workers()
        config = self.state.get_config()
        status_text = f"""
📊 *SYSTEM STATUS*
• Status: `{"🟢 RUNNING" if self.state.is_running() else "🔴 STOPPED"}`
• Active: `{metrics.get('active_workers', 0)}/{config.get('max_workers', 50)}`
• Success: `{metrics.get('success_count', 0)}`
• Failed: `{metrics.get('failed_count', 0)}`
• Total: `{metrics.get('total_attempts', 0)}`
• Workers: `{len(workers)}`
⏱️ Updated: `{datetime.now().strftime('%H:%M:%S')}`
        """
        keyboard = [[InlineKeyboardButton("🔄 Refresh", callback_data="status")]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await update.message.reply_text(status_text, parse_mode=ParseMode.MARKDOWN, reply_markup=reply_markup)
    
    async def start_spam_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        user_id = update.effective_user.id
        if user_id not in ALLOWED_USER_IDS:
            await update.message.reply_text("⛔ Access Denied")
            return
        args = context.args
        config = self.state.get_config()
        jumlah = config.get("max_workers") // 2
        target = config.get("default_target")
        if len(args) >= 1:
            try:
                jumlah = int(args[0])
                if jumlah > config.get("max_workers", 50):
                    jumlah = config.get("max_workers", 50)
            except:
                pass
        if len(args) >= 2:
            target = args[1]
        await update.message.chat.send_action(action=ChatAction.TYPING)
        started = self.worker.start_workers(jumlah, target)
        await update.message.reply_text(f"✅ *SPAM STARTED*\n\nWorkers: `{started}`\nTarget: `{target}`", parse_mode=ParseMode.MARKDOWN)
    
    async def stop_spam_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        user_id = update.effective_user.id
        if user_id not in ALLOWED_USER_IDS:
            await update.message.reply_text("⛔ Access Denied")
            return
        await update.message.chat.send_action(action=ChatAction.TYPING)
        stopped = self.worker.stop_all_workers()
        await update.message.reply_text(f"🛑 *STOPPED*\n\n{stopped} worker dihentikan.", parse_mode=ParseMode.MARKDOWN)
    
    async def stats_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        user_id = update.effective_user.id
        if user_id not in ALLOWED_USER_IDS:
            await update.message.reply_text("⛔ Access Denied")
            return
        await update.message.chat.send_action(action=ChatAction.TYPING)
        metrics = self.state.get_metrics()
        codes = self.state.get_pairing_codes(5)
        total = metrics.get('total_attempts', 0)
        rate = round((metrics.get('success_count', 0) / max(total, 1)) * 100, 1)
        text = f"""
📈 *STATISTICS*
• Total: `{total}`
• Success: `{metrics.get('success_count', 0)}`
• Failed: `{metrics.get('failed_count', 0)}`
• Rate: `{rate}%`

*Recent Codes:*
"""
        for code in codes[:5]:
            text += f"• `{code.get('code', 'N/A')}` → {code.get('phone', 'Unknown')}\n"
        if not codes:
            text += "_No codes yet_"
        await update.message.reply_text(text, parse_mode=ParseMode.MARKDOWN)
    
    async def config_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        user_id = update.effective_user.id
        if user_id not in ALLOWED_USER_IDS:
            await update.message.reply_text("⛔ Access Denied")
            return
        config = self.state.get_config()
        await update.message.reply_text(f"""
⚙️ *CONFIG*
• Max Workers: `{config.get('max_workers', 50)}`
• Default Target: `{config.get('default_target', 'N/A')}`
• Cooldown: `{config.get('cooldown_seconds', 60)}s`
• Max Retries: `{config.get('max_retries', 5)}`
        """, parse_mode=ParseMode.MARKDOWN)
    
    async def restart_worker_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        user_id = update.effective_user.id
        if user_id not in ALLOWED_USER_IDS:
            await update.message.reply_text("⛔ Access Denied")
            return
        args = context.args
        if not args:
            await update.message.reply_text("❌ Usage: `/restart_worker [worker_id]`", parse_mode=ParseMode.MARKDOWN)
            return
        success = self.worker.restart_worker(args[0])
        await update.message.reply_text(f"🔄 Worker `{args[0]}` {'restarted' if success else 'not found'}", parse_mode=ParseMode.MARKDOWN)
    
    async def logs_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        user_id = update.effective_user.id
        if user_id not in ALLOWED_USER_IDS:
            await update.message.reply_text("⛔ Access Denied")
            return
        logs = self.state.get_delivery_logs(10)
        if not logs:
            await update.message.reply_text("📭 No logs available")
            return
        text = "📋 *RECENT LOGS*\n\n"
        for log in logs[:10]:
            text += f"• {log.get('to', 'N/A')} → {log.get('code', 'N/A')} via {log.get('channel', 'N/A')}\n"
        await update.message.reply_text(text, parse_mode=ParseMode.MARKDOWN)
    
    async def reset_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        user_id = update.effective_user.id
        if user_id not in ALLOWED_USER_IDS:
            await update.message.reply_text("⛔ Access Denied")
            return
        self.worker.stop_all_workers()
        self.state.reset_all()
        await update.message.reply_text("🔄 *RESET COMPLETE*", parse_mode=ParseMode.MARKDOWN)
    
    async def callback_handler(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        query = update.callback_query
        await query.answer()
        user_id = update.effective_user.id
        if user_id not in ALLOWED_USER_IDS:
            await query.edit_message_text("⛔ Access Denied")
            return
        data = query.data
        if data == "status":
            metrics = self.state.get_metrics()
            workers = self.state.get_workers()
            config = self.state.get_config()
            text = f"""
📊 *SYSTEM STATUS*
• Status: `{"🟢 RUNNING" if self.state.is_running() else "🔴 STOPPED"}`
• Active: `{metrics.get('active_workers', 0)}/{config.get('max_workers', 50)}`
• Success: `{metrics.get('success_count', 0)}`
• Failed: `{metrics.get('failed_count', 0)}`
• Total: `{metrics.get('total_attempts', 0)}`
            """
            keyboard = [[InlineKeyboardButton("🔄 Refresh", callback_data="status")]]
            await query.edit_message_text(text, parse_mode=ParseMode.MARKDOWN, reply_markup=InlineKeyboardMarkup(keyboard))
        elif data == "stats":
            metrics = self.state.get_metrics()
            codes = self.state.get_pairing_codes(5)
            total = metrics.get('total_attempts', 0)
            rate = round((metrics.get('success_count', 0) / max(total, 1)) * 100, 1)
            text = f"📈 *STATS*\nTotal: `{total}`\nSuccess: `{metrics.get('success_count', 0)}`\nRate: `{rate}%`"
            await query.edit_message_text(text, parse_mode=ParseMode.MARKDOWN)
        elif data == "start_spam":
            keyboard = [
                [InlineKeyboardButton("10 Workers", callback_data="start_10"), InlineKeyboardButton("25 Workers", callback_data="start_25")],
                [InlineKeyboardButton("50 Workers", callback_data="start_50")],
                [InlineKeyboardButton("🔙 Back", callback_data="status")]
            ]
            await query.edit_message_text("▶️ *START SPAM*\nPilih jumlah worker:", parse_mode=ParseMode.MARKDOWN, reply_markup=InlineKeyboardMarkup(keyboard))
        elif data.startswith("start_"):
            count = int(data.split("_")[1]) if data.split("_")[1].isdigit() else 10
            config = self.state.get_config()
            target = config.get("default_target", "6281234567890")
            started = self.worker.start_workers(count, target)
            await query.edit_message_text(f"✅ Started `{started}` workers to `{target}`", parse_mode=ParseMode.MARKDOWN)
        elif data == "stop_spam":
            stopped = self.worker.stop_all_workers()
            await query.edit_message_text(f"🛑 Stopped `{stopped}` workers", parse_mode=ParseMode.MARKDOWN)
        elif data == "logs":
            logs = self.state.get_delivery_logs(10)
            if not logs:
                await query.edit_message_text("📭 No logs")
                return
            text = "📋 *LOGS*\n"
            for log in logs[:10]:
                text += f"• {log.get('to', 'N/A')} → {log.get('code', 'N/A')}\n"
            await query.edit_message_text(text, parse_mode=ParseMode.MARKDOWN)
        elif data == "config":
            config = self.state.get_config()
            await query.edit_message_text(f"⚙️ *CONFIG*\nMax Workers: `{config.get('max_workers', 50)}`\nTarget: `{config.get('default_target', 'N/A')}`", parse_mode=ParseMode.MARKDOWN)
    
    async def _error_handler(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        logger.error(f"Update {update} caused error: {context.error}")
        traceback.print_exception(type(context.error), context.error, context.error.__traceback__)

# ==================== MAIN ====================
async def main():
    print("="*60)
    print("  WHATSAPP PAIRING BOT - RAILWAY VERSION")
    print("  TANPA REDIS - LANGSUNG RUN")
    print("="*60)
    
    if TELEGRAM_BOT_TOKEN == "7741123456:AAHdflkjsdflkjsdflkjsdflkjsdflkjsdflk":
        print("⚠️  WARNING: Using default token!")
        print("   Set environment variable: TELEGRAM_BOT_TOKEN")
    
    print(f"✅ Authorized users: {ALLOWED_USER_IDS}")
    print("🔄 Bot running...")
    
    bot = PairingBot()
    app = bot.setup_application()
    
    await app.initialize()
    await app.start()
    await app.updater.start_polling(allowed_updates=Update.ALL_TYPES)
    
    # Keep running
    while True:
        await asyncio.sleep(1)

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n👋 Bot stopped")
        sys.exit(0)
