#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
TELEGRAM BOT CONTROLLER - VERSI STANDALONE
Tanpa Redis, tanpa database eksternal
Semua state disimpan di memory dan file JSON
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
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Any
from collections import defaultdict
import traceback

# ==================== KONFIGURASI ====================
TELEGRAM_BOT_TOKEN = "8945238760:AAF0hDSJVRrwbvfrYiZK6BpjumuHDnDIztE"  # GANTI DENGAN TOKEN ASLI ANDA
ALLOWED_USER_IDS = [8086581937]  # GANTI DENGAN ID TELEGRAM ANDA
# ====================================================

# ==================== LIBRARY ====================
try:
    from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, ParseMode
    from telegram.ext import Application, CommandHandler, CallbackQueryHandler, ContextTypes
    from telegram.constants import ChatAction
except ImportError:
    print("❌ Library python-telegram-bot tidak terinstall!")
    print("   Jalankan: pip install python-telegram-bot==20.6")
    sys.exit(1)

# ==================== LOGGING ====================
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# ==================== STATE MANAGER (TANPA REDIS) ====================
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
        """Load state dari file JSON jika ada"""
        try:
            if os.path.exists(self.state_file):
                with open(self.state_file, 'r') as f:
                    saved = json.load(f)
                    # Merge dengan default
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
        """Simpan state ke file JSON"""
        try:
            with open(self.state_file, 'w') as f:
                json.dump(self.data, f, indent=2, default=str)
        except Exception as e:
            logger.error(f"Failed to save state: {e}")
    
    def get_metrics(self) -> Dict:
        """Ambil metrik"""
        with self.lock:
            return self.data["metrics"].copy()
    
    def update_metrics(self, **kwargs):
        """Update metrik"""
        with self.lock:
            for key, value in kwargs.items():
                if key in self.data["metrics"]:
                    self.data["metrics"][key] = value
            self.data["metrics"]["last_updated"] = datetime.now().isoformat()
            self._save_state()
    
    def add_worker(self, worker_id: str, info: Dict):
        """Tambah atau update worker"""
        with self.lock:
            self.data["workers"][worker_id] = info
            self.data["metrics"]["total_sessions"] = len(self.data["workers"])
            self._save_state()
    
    def remove_worker(self, worker_id: str):
        """Hapus worker"""
        with self.lock:
            if worker_id in self.data["workers"]:
                del self.data["workers"][worker_id]
            self.data["metrics"]["total_sessions"] = len(self.data["workers"])
            self._save_state()
    
    def get_workers(self) -> Dict:
        """Ambil semua worker"""
        with self.lock:
            return self.data["workers"].copy()
    
    def add_pairing_code(self, phone: str, code: str):
        """Tambah kode pairing"""
        with self.lock:
            entry = {
                "phone": phone,
                "code": code,
                "timestamp": datetime.now().isoformat()
            }
            self.data["pairing_codes"].insert(0, entry)
            # Simpan maksimal 100
            if len(self.data["pairing_codes"]) > 100:
                self.data["pairing_codes"] = self.data["pairing_codes"][:100]
            self.data["system"]["total_processed"] += 1
            self._save_state()
    
    def add_delivery_log(self, phone: str, code: str, channel: str):
        """Tambah log pengiriman"""
        with self.lock:
            entry = {
                "to": phone,
                "code": code,
                "channel": channel,
                "timestamp": datetime.now().isoformat()
            }
            self.data["delivery_logs"].insert(0, entry)
            if len(self.data["delivery_logs"]) > 100:
                self.data["delivery_logs"] = self.data["delivery_logs"][:100]
            self._save_state()
    
    def get_delivery_logs(self, limit: int = 20) -> List:
        """Ambil log pengiriman"""
        with self.lock:
            return self.data["delivery_logs"][:limit]
    
    def get_pairing_codes(self, limit: int = 10) -> List:
        """Ambil kode pairing terbaru"""
        with self.lock:
            return self.data["pairing_codes"][:limit]
    
    def update_config(self, **kwargs):
        """Update konfigurasi"""
        with self.lock:
            for key, value in kwargs.items():
                if key in self.data["config"]:
                    self.data["config"][key] = value
            self._save_state()
    
    def get_config(self) -> Dict:
        """Ambil konfigurasi"""
        with self.lock:
            return self.data["config"].copy()
    
    def set_running(self, status: bool):
        """Set status running"""
        with self.lock:
            self.data["system"]["is_running"] = status
            self._save_state()
    
    def is_running(self) -> bool:
        """Cek status running"""
        with self.lock:
            return self.data["system"]["is_running"]
    
    def reset_all(self):
        """Reset semua data (hati-hati!)"""
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

# ==================== WORKER SIMULATOR (TANPA REDIS) ====================
class WorkerSimulator:
    """Simulasi worker tanpa Redis - menggunakan thread"""
    
    def __init__(self, state_manager: StateManager):
        self.state = state_manager
        self.running_workers = {}
        self.worker_threads = {}
        self.worker_counter = 0
        self.lock = threading.Lock()
    
    def start_workers(self, count: int, target: str):
        """Mulai worker baru"""
        if count > self.state.get_config()["max_workers"]:
            count = self.state.get_config()["max_workers"]
        
        for i in range(count):
            worker_id = f"worker_{self.worker_counter + i + 1}"
            thread = threading.Thread(
                target=self._run_worker,
                args=(worker_id, target),
                daemon=True
            )
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
        """Fungsi yang dijalankan worker di thread terpisah"""
        import time
        
        max_retries = self.state.get_config()["max_retries"]
        attempts = 0
        
        while worker_id in self.running_workers:
            try:
                attempts += 1
                self.running_workers[worker_id]["attempts"] = attempts
                
                # Simulasi proses pairing (delay 2-5 detik)
                time.sleep(random.uniform(2, 5))
                
                # Simulasi 80% sukses, 15% gagal, 5% rate limit
                roll = random.random()
                
                if roll < 0.80:  # Success
                    code = ''.join(random.choices(string.digits, k=8))
                    self.state.add_pairing_code(target, code)
                    self.state.update_metrics(
                        success_count=self.state.get_metrics()["success_count"] + 1,
                        total_attempts=self.state.get_metrics()["total_attempts"] + 1
                    )
                    # Simulasi pengiriman
                    channel = random.choice(["SMS", "Telegram", "Email", "WhatsApp"])
                    self.state.add_delivery_log(target, code, channel)
                    logger.info(f"✅ {worker_id} → Code {code} for {target} via {channel}")
                    
                elif roll < 0.95:  # Failed
                    self.state.update_metrics(
                        failed_count=self.state.get_metrics()["failed_count"] + 1,
                        total_attempts=self.state.get_metrics()["total_attempts"] + 1
                    )
                    logger.warning(f"❌ {worker_id} failed for {target}")
                    
                else:  # Rate limited
                    self.state.update_metrics(
                        rate_limit_count=self.state.get_metrics()["rate_limit_count"] + 1
                    )
                    logger.warning(f"🚫 {worker_id} rate limited for {target}")
                    # Cooldown
                    time.sleep(self.state.get_config()["cooldown_seconds"])
                
                # Update worker status di state
                self.running_workers[worker_id]["last_heartbeat"] = datetime.now().isoformat()
                self.state.add_worker(worker_id, self.running_workers[worker_id])
                
            except Exception as e:
                logger.error(f"Worker {worker_id} error: {e}")
                if attempts >= max_retries:
                    break
                time.sleep(5)
        
        # Worker selesai
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
        """Hentikan semua worker"""
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
        """Restart worker tertentu"""
        if worker_id in self.running_workers:
            target = self.running_workers[worker_id]["target"]
            # Hapus worker lama
            del self.running_workers[worker_id]
            if worker_id in self.worker_threads:
                del self.worker_threads[worker_id]
            self.state.remove_worker(worker_id)
            
            # Buat worker baru dengan ID yang sama
            thread = threading.Thread(
                target=self._run_worker,
                args=(worker_id, target),
                daemon=True
            )
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
        """Ambil status semua worker"""
        return {
            "active": len(self.running_workers),
            "workers": self.running_workers.copy()
        }

# ==================== TELEGRAM BOT ====================
class PairingBot:
    """Main bot class tanpa Redis"""
    
    def __init__(self):
        self.state = StateManager()
        self.worker = WorkerSimulator(self.state)
        self.application = None
        self.bot_username = "WhatsAppPairingBot"
    
    def setup_application(self):
        """Setup aplikasi Telegram bot"""
        self.application = Application.builder().token(TELEGRAM_BOT_TOKEN).build()
        
        # Register command handlers
        self.application.add_handler(CommandHandler("start", self.start_command))
        self.application.add_handler(CommandHandler("status", self.status_command))
        self.application.add_handler(CommandHandler("start_spam", self.start_spam_command))
        self.application.add_handler(CommandHandler("stop_spam", self.stop_spam_command))
        self.application.add_handler(CommandHandler("stats", self.stats_command))
        self.application.add_handler(CommandHandler("config", self.config_command))
        self.application.add_handler(CommandHandler("restart_worker", self.restart_worker_command))
        self.application.add_handler(CommandHandler("logs", self.logs_command))
        self.application.add_handler(CommandHandler("reset", self.reset_command))
        
        # Register callback handler
        self.application.add_handler(CallbackQueryHandler(self.callback_handler))
        
        # Register error handler
        self.application.add_error_handler(self._error_handler)
        
        logger.info("✅ Bot application setup complete")
        return self.application
    
    # ==================== COMMAND HANDLERS ====================
    
    async def start_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handler untuk /start"""
        user_id = update.effective_user.id
        if user_id not in ALLOWED_USER_IDS:
            await update.message.reply_text("⛔ *Access Denied*\nAnda tidak memiliki akses ke bot ini.", parse_mode=ParseMode.MARKDOWN)
            return
        
        status = "🟢 RUNNING" if self.state.is_running() else "🔴 STOPPED"
        
        welcome_text = f"""
🤖 *WHATSAPP PAIRING BOT* - STANDALONE

*Status:* {status}
*Active Workers:* `{self.state.get_metrics()['active_workers']}`
*Total Processed:* `{self.state.get_metrics()['total_attempts']}`

*Commands:*
• `/status` - Status sistem & worker
• `/start_spam [jumlah] [target]` - Mulai spam
• `/stop_spam` - Hentikan semua worker
• `/stats` - Statistik lengkap
• `/config` - Lihat konfigurasi
• `/restart_worker [id]` - Restart worker
• `/logs` - Lihat log terbaru
• `/reset` - Reset semua data

*TANPA REDIS - Semua data di memory & file JSON*
        """
        
        keyboard = [
            [
                InlineKeyboardButton("📊 Status", callback_data="status"),
                InlineKeyboardButton("📈 Stats", callback_data="stats")
            ],
            [
                InlineKeyboardButton("▶️ Start Spam", callback_data="start_spam"),
                InlineKeyboardButton("⏹ Stop", callback_data="stop_spam")
            ],
            [
                InlineKeyboardButton("📋 Logs", callback_data="logs"),
                InlineKeyboardButton("⚙️ Config", callback_data="config")
            ]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await update.message.reply_text(welcome_text, parse_mode=ParseMode.MARKDOWN, reply_markup=reply_markup)
    
    async def status_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handler untuk /status"""
        user_id = update.effective_user.id
        if user_id not in ALLOWED_USER_IDS:
            await update.message.reply_text("⛔ Access Denied")
            return
        
        await update.message.chat.send_action(action=ChatAction.TYPING)
        
        metrics = self.state.get_metrics()
        workers = self.state.get_workers()
        config = self.state.get_config()
        
        status_text = f"""
📊 *SYSTEM STATUS* - {self.bot_username}

━━━━━━━━━━━━━━━━━━━━━━
*METRICS*
━━━━━━━━━━━━━━━━━━━━━━
• Status      : `{"🟢 RUNNING" if self.state.is_running() else "🔴 STOPPED"}`
• Active      : `{metrics.get('active_workers', 0)}/{config.get('max_workers', 50)}`
• Success     : `{metrics.get('success_count', 0)}`
• Failed      : `{metrics.get('failed_count', 0)}`
• Rate Limit  : `{metrics.get('rate_limit_count', 0)}`
• Total       : `{metrics.get('total_attempts', 0)}`

━━━━━━━━━━━━━━━━━━━━━━
*WORKERS* ({len(workers)} aktif)
━━━━━━━━━━━━━━━━━━━━━━
"""
        
        if workers:
            for wid, info in list(workers.items())[:10]:
                status_text += f"• `{wid}` → {info.get('target', 'N/A')} (attempts: {info.get('attempts', 0)})\n"
            if len(workers) > 10:
                status_text += f"_... dan {len(workers) - 10} lainnya_"
        else:
            status_text += "_Tidak ada worker aktif_"
        
        status_text += f"""
━━━━━━━━━━━━━━━━━━━━━━
⏱️ *Updated*: `{datetime.now().strftime('%H:%M:%S')}`
💾 *Storage*: `bot_state.json`
        """
        
        keyboard = [[
            InlineKeyboardButton("🔄 Refresh", callback_data="status"),
            InlineKeyboardButton("📋 Detail", callback_data="detail_status")
        ]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await update.message.reply_text(status_text, parse_mode=ParseMode.MARKDOWN, reply_markup=reply_markup)
    
    async def start_spam_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handler untuk /start_spam [jumlah] [target]"""
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
        
        # Start worker
        started = self.worker.start_workers(jumlah, target)
        
        confirmation = f"""
✅ *SPAM STARTED*

• Workers : `{started}`
• Target  : `{target}`
• Max     : `{config.get('max_workers', 50)}`

Gunakan `/status` untuk monitor progres.
Kode pairing akan muncul di `/stats` dan `/logs`.
        """
        
        await update.message.reply_text(confirmation, parse_mode=ParseMode.MARKDOWN)
    
    async def stop_spam_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handler untuk /stop_spam"""
        user_id = update.effective_user.id
        if user_id not in ALLOWED_USER_IDS:
            await update.message.reply_text("⛔ Access Denied")
            return
        
        await update.message.chat.send_action(action=ChatAction.TYPING)
        
        stopped = self.worker.stop_all_workers()
        
        await update.message.reply_text(
            f"🛑 *STOPPED*\n\n{stopped} worker dihentikan.\nStatus: 🔴 STOPPED",
            parse_mode=ParseMode.MARKDOWN
        )
    
    async def stats_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handler untuk /stats"""
        user_id = update.effective_user.id
        if user_id not in ALLOWED_USER_IDS:
            await update.message.reply_text("⛔ Access Denied")
            return
        
        await update.message.chat.send_action(action=ChatAction.TYPING)
        
        metrics = self.state.get_metrics()
        codes = self.state.get_pairing_codes(10)
        logs = self.state.get_delivery_logs(5)
        
        total = metrics.get('total_attempts', 0)
        success_rate = round((metrics.get('success_count', 0) / max(total, 1)) * 100, 1)
        
        stats_text = f"""
📈 *COMPLETE STATISTICS*

━━━━━━━━━━━━━━━━━━━━━━
*SUMMARY*
━━━━━━━━━━━━━━━━━━━━━━
• Total Attempts : `{total}`
• Success        : `{metrics.get('success_count', 0)}`
• Failed         : `{metrics.get('failed_count', 0)}`
• Rate Limited   : `{metrics.get('rate_limit_count', 0)}`
• Success Rate   : `{success_rate}%`

━━━━━━━━━━━━━━━━━━━━━━
*RECENT CODES* (10)
━━━━━━━━━━━━━━━━━━━━━━
"""
        
        for code in codes[:10]:
            stats_text += f"• `{code.get('code', 'N/A')}` → {code.get('phone', 'Unknown')}\n"
        
        if not codes:
            stats_text += "_Belum ada kode pairing yang dihasilkan_"
        
        stats_text += f"""
━━━━━━━━━━━━━━━━━━━━━━
*RECENT DELIVERIES* (5)
━━━━━━━━━━━━━━━━━━━━━━
"""
        
        for log in logs[:5]:
            stats_text += f"• {log.get('to', 'N/A')} → {log.get('code', 'N/A')} via {log.get('channel', 'N/A')}\n"
        
        if not logs:
            stats_text += "_Belum ada pengiriman_"
        
        stats_text += f"""
━━━━━━━━━━━━━━━━━━━━━━
⏱️ *Updated*: `{datetime.now().strftime('%H:%M:%S')}`
        """
        
        await update.message.reply_text(stats_text, parse_mode=ParseMode.MARKDOWN)
    
    async def config_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handler untuk /config"""
        user_id = update.effective_user.id
        if user_id not in ALLOWED_USER_IDS:
            await update.message.reply_text("⛔ Access Denied")
            return
        
        config = self.state.get_config()
        
        config_text = f"""
⚙️ *CURRENT CONFIGURATION*
Max Workers : {config.get('max_workers', 50)}
Default Target : {config.get('default_target', 'N/A')}
Cooldown : {config.get('cooldown_seconds', 60)}s
Max Retries : {config.get('max_retries', 5)}

*Ubah konfigurasi:*
`/set_config max_workers 100`
`/set_config default_target 6281234567890`

*Reset semua data:* `/reset`
        """
        
        keyboard = [[
            InlineKeyboardButton("🔄 Reset Config", callback_data="reset_config")
        ]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await update.message.reply_text(config_text, parse_mode=ParseMode.MARKDOWN, reply_markup=reply_markup)
    
    async def restart_worker_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handler untuk /restart_worker [id]"""
        user_id = update.effective_user.id
        if user_id not in ALLOWED_USER_IDS:
            await update.message.reply_text("⛔ Access Denied")
            return
        
        args = context.args
        if not args:
            await update.message.reply_text("❌ Usage: `/restart_worker [worker_id]`", parse_mode=ParseMode.MARKDOWN)
            return
        
        worker_id = args[0]
        success = self.worker.restart_worker(worker_id)
        
        if success:
            await update.message.reply_text(f"🔄 Worker `{worker_id}` restarted.", parse_mode=ParseMode.MARKDOWN)
        else:
            await update.message.reply_text(f"❌ Worker `{worker_id}` not found.", parse_mode=ParseMode.MARKDOWN)
    
    async def logs_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handler untuk /logs"""
        user_id = update.effective_user.id
        if user_id not in ALLOWED_USER_IDS:
            await update.message.reply_text("⛔ Access Denied")
            return
        
        args = context.args
        limit = 10
        if args and args[0].isdigit():
            limit = min(int(args[0]), 50)
        
        logs = self.state.get_delivery_logs(limit)
        
        if not logs:
            await update.message.reply_text("📭 *No logs available*", parse_mode=ParseMode.MARKDOWN)
            return
        
        log_text = "📋 *DELIVERY LOGS*\n\n"
        for i, log in enumerate(logs[:limit], 1):
            log_text += f"`{i}. {log.get('timestamp', 'N/A')}`\n"
            log_text += f"   📱 {log.get('to', 'Unknown')} → {log.get('code', 'N/A')}\n"
            log_text += f"   📡 {log.get('channel', 'Unknown')}\n\n"
        
        await update.message.reply_text(log_text, parse_mode=ParseMode.MARKDOWN)
    
    async def reset_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handler untuk /reset - reset semua data"""
        user_id = update.effective_user.id
        if user_id not in ALLOWED_USER_IDS:
            await update.message.reply_text("⛔ Access Denied")
            return
        
        # Stop semua worker dulu
        self.worker.stop_all_workers()
        
        # Reset state
        self.state.reset_all()
        
        await update.message.reply_text(
            "🔄 *RESET COMPLETE*\n\nSemua data telah direset.\nWorker dihentikan.\nStatistik dikosongkan.",
            parse_mode=ParseMode.MARKDOWN
        )
    
    # ==================== CALLBACK HANDLERS ====================
    
    async def callback_handler(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handler untuk callback query"""
        query = update.callback_query
        await query.answer()
        
        user_id = update.effective_user.id
        if user_id not in ALLOWED_USER_IDS:
            await query.edit_message_text("⛔ Access Denied")
            return
        
        data = query.data
        
        if data == "status":
            await self._send_status(query)
        elif data == "detail_status":
            await self._send_detail_status(query)
        elif data == "stats":
            await self._send_stats(query)
        elif data == "start_spam":
            await self._send_start_prompt(query)
        elif data == "stop_spam":
            await self._handle_stop(query)
        elif data == "logs":
            await self._send_logs(query)
        elif data == "config":
            await self._send_config(query)
        elif data == "reset_config":
            await self._handle_reset_config(query)
        elif data.startswith("start_"):
            # start_10, start_25, start_50, start_100
            count = int(data.split("_")[1]) if data.split("_")[1].isdigit() else 10
            config = self.state.get_config()
            target = config.get("default_target", "6281234567890")
            started = self.worker.start_workers(count, target)
            await query.edit_message_text(
                f"✅ Started `{started}` workers to `{target}`",
                parse_mode=ParseMode.MARKDOWN
            )
    
    async def _send_status(self, query):
        """Kirim status"""
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
• Workers: `{len(workers)}`
        """
        
        keyboard = [[
            InlineKeyboardButton("🔄 Refresh", callback_data="status"),
            InlineKeyboardButton("📋 Detail", callback_data="detail_status")
        ]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await query.edit_message_text(text, parse_mode=ParseMode.MARKDOWN, reply_markup=reply_markup)
    
    async def _send_detail_status(self, query):
        """Kirim detail worker"""
        workers = self.state.get_workers()
        
        if not workers:
            await query.edit_message_text("📭 No active workers", parse_mode=ParseMode.MARKDOWN)
            return
        
        text = "📋 *WORKER DETAILS*\n\n"
        for wid, info in list(workers.items())[:20]:
            text += f"• `{wid}`\n"
            text += f"  Target: {info.get('target', 'N/A')}\n"
            text += f"  Attempts: {info.get('attempts', 0)}\n"
            text += f"  Started: {info.get('started_at', 'N/A')[:16]}\n\n"
        
        if len(workers) > 20:
            text += f"_... dan {len(workers) - 20} lainnya_"
        
        keyboard = [[
            InlineKeyboardButton("🔙 Back", callback_data="status")
        ]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await query.edit_message_text(text, parse_mode=ParseMode.MARKDOWN, reply_markup=reply_markup)
    
    async def _send_stats(self, query):
        """Kirim statistik"""
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
        
        await query.edit_message_text(text, parse_mode=ParseMode.MARKDOWN)
    
    async def _send_start_prompt(self, query):
        """Tampilkan prompt start spam"""
        config = self.state.get_config()
        
        keyboard = [
            [
                InlineKeyboardButton("10 Workers", callback_data="start_10"),
                InlineKeyboardButton("25 Workers", callback_data="start_25"),
                InlineKeyboardButton("50 Workers", callback_data="start_50")
            ],
            [
                InlineKeyboardButton("100 Workers", callback_data="start_100")
            ],
            [
                InlineKeyboardButton("🔙 Back", callback_data="status")
            ]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await query.edit_message_text(
            f"▶️ *START SPAM*\n\nPilih jumlah worker:\n\n*Target:* `{config.get('default_target', 'N/A')}`\n*Max:* `{config.get('max_workers', 50)}`",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=reply_markup
        )
    
    async def _handle_stop(self, query):
        """Handle stop"""
        stopped = self.worker.stop_all_workers()
        await query.edit_message_text(f"🛑 Stopped `{stopped}` workers", parse_mode=ParseMode.MARKDOWN)
    
    async def _send_logs(self, query):
        """Kirim logs"""
        logs = self.state.get_delivery_logs(10)
        
        if not logs:
            await query.edit_message_text("📭 No logs", parse_mode=ParseMode.MARKDOWN)
            return
        
        text = "📋 *RECENT LOGS*\n\n"
        for log in logs[:10]:
            text += f"• {log.get('to', 'N/A')} → {log.get('code', 'N/A')} via {log.get('channel', 'N/A')}\n"
            text += f"  `{log.get('timestamp', 'N/A')}`\n"
        
        await query.edit_message_text(text, parse_mode=ParseMode.MARKDOWN)
    
    async def _send_config(self, query):
        """Kirim config"""
        config = self.state.get_config()
        
        text = f"""
⚙️ *CONFIG*
• Max Workers: `{config.get('max_workers', 50)}`
• Default Target: `{config.get('default_target', 'N/A')}`
• Cooldown: `{config.get('cooldown_seconds', 60)}s`
• Max Retries: `{config.get('max_retries', 5)}`
        """
        
        keyboard = [[
            InlineKeyboardButton("🔙 Back", callback_data="status")
        ]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await query.edit_message_text(text, parse_mode=ParseMode.MARKDOWN, reply_markup=reply_markup)
    
    async def _handle_reset_config(self, query):
        """Reset config ke default"""
        self.state.update_config(
            max_workers=50,
            default_target="6281234567890",
            cooldown_seconds=60,
            max_retries=5
        )
        await query.edit_message_text("✅ Config reset to default", parse_mode=ParseMode.MARKDOWN)
    
    # ==================== ERROR HANDLER ====================
    
    async def _error_handler(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Global error handler"""
        logger.error(f"Update {update} caused error: {context.error}")
        traceback.print_exception(type(context.error), context.error, context.error.__traceback__)

# ==================== MAIN ====================

async def main():
    """Entry point utama"""
    print("="*60)
    print("  WHATSAPP PAIRING BOT - STANDALONE VERSION")
    print("  TANPA REDIS - LANGSUNG RUN")
    print("="*60)
    print()
    
    # Cek token
    if TELEGRAM_BOT_TOKEN == "7741123456:AAHdflkjsdflkjsdflkjsdflkjsdflkjsdflk":
        print("⚠️  PERHATIAN: Token bot masih default!")
        print("   Edit file dan ganti TELEGRAM_BOT_TOKEN dengan token asli dari @BotFather")
        print("   Juga ganti ALLOWED_USER_IDS dengan ID Telegram Anda")
        print()
        print("   Dapatkan token: https://t.me/BotFather")
        print("   Dapatkan ID: https://t.me/userinfobot")
        print()
        choice = input("   Lanjutkan dengan token dummy? (y/n): ")
        if choice.lower() != 'y':
            print("❌ Bot dihentikan. Silakan edit token terlebih dahulu.")
            sys.exit(1)
    
    bot = PairingBot()
    app = bot.setup_application()
    
    print("✅ Bot started!")
    print(f"📱 Bot username: @{bot.bot_username}")
    print(f"👤 Authorized users: {ALLOWED_USER_IDS}")
    print(f"💾 State file: bot_state.json")
    print()
    print("📋 Commands:")
    print("   /start - Menu utama")
    print("   /status - Status sistem")
    print("   /start_spam [jumlah] [target] - Mulai spam")
    print("   /stop_spam - Hentikan semua")
    print("   /stats - Statistik")
    print("   /config - Konfigurasi")
    print("   /logs - Log pengiriman")
    print("   /reset - Reset semua data")
    print()
    print("🔄 Bot running... Press Ctrl+C to stop")
    print("="*60)
    
    try:
        # Start bot
        await app.initialize()
        await app.start()
        await app.updater.start_polling(allowed_updates=Update.ALL_TYPES)
        
        # Keep running
        while True:
            await asyncio.sleep(1)
            
    except KeyboardInterrupt:
        print("\n⏹️  Shutting down...")
        await app.updater.stop()
        await app.stop()
        await app.shutdown()
        print("✅ Bot stopped")
    except Exception as e:
        print(f"❌ Fatal error: {e}")
        traceback.print_exc()

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n👋 Bot terminated by user")
        sys.exit(0)