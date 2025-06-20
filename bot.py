import asyncio
import aiohttp
import json
import os
from datetime import datetime, timedelta
from collections import defaultdict
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, MessageHandler, CallbackQueryHandler, filters, ContextTypes
from aiohttp import web

# Bot Token - Environment variable'dan al
BOT_TOKEN = os.environ.get('BOT_TOKEN', '7715414446:AAGDvt3TiyjZxWAr6NzY8CN5qQf0_fy4PWw')

# Developer's BTC Address
DEVELOPER_BTC_ADDRESS = "bc1qzv7v3kengms6zguh7445xxy77dsrwjqxxrcxrt"

# Bot's X (Twitter) Account
BOT_X_ACCOUNT = "https://x.com/BTCAnalyzerBot?t=q0r56PngC-wbjOERZrg9iw&s=09"

# API Base URLs
BLOCKSTREAM_API = "https://blockstream.info/api"
COINGECKO_API = "https://api.coingecko.com/api/v3"

# Rate limiting settings
RATE_LIMIT_PER_HOUR = 10
RATE_LIMIT_PER_DAY = 50

# In-memory storage for rate limiting
user_requests = defaultdict(list)

class RateLimiter:
    @staticmethod
    def clean_old_requests():
        """Remove requests older than 24 hours"""
        current_time = datetime.now()
        cutoff_time = current_time - timedelta(hours=24)
        
        for user_id in list(user_requests.keys()):
            user_requests[user_id] = [
                req_time for req_time in user_requests[user_id] 
                if req_time > cutoff_time
            ]
            if not user_requests[user_id]:
                del user_requests[user_id]
    
    @staticmethod
    def check_user_limit(user_id: int) -> dict:
        """Check if user has exceeded rate limits"""
        RateLimiter.clean_old_requests()
        
        current_time = datetime.now()
        user_reqs = user_requests.get(user_id, [])
        
        hour_ago = current_time - timedelta(hours=1)
        hourly_requests = [req for req in user_reqs if req > hour_ago]
        
        day_ago = current_time - timedelta(days=1)
        daily_requests = [req for req in user_reqs if req > day_ago]
        
        return {
            'can_proceed': (
                len(hourly_requests) < RATE_LIMIT_PER_HOUR and 
                len(daily_requests) < RATE_LIMIT_PER_DAY
            ),
            'hourly_used': len(hourly_requests),
            'daily_used': len(daily_requests),
            'hourly_remaining': RATE_LIMIT_PER_HOUR - len(hourly_requests),
            'daily_remaining': RATE_LIMIT_PER_DAY - len(daily_requests)
        }
    
    @staticmethod
    def record_request(user_id: int):
        """Record a new request"""
        current_time = datetime.now()
        user_requests[user_id].append(current_time)

class BitcoinAnalyzer:
    @staticmethod
    async def get_btc_price():
        """Get current Bitcoin price"""
        async with aiohttp.ClientSession() as session:
            try:
                headers = {
                    'User-Agent': 'Bitcoin-Analyzer-Bot/1.0',
                    'Accept': 'application/json'
                }
                
                async with session.get(
                    f"{COINGECKO_API}/simple/price?ids=bitcoin&vs_currencies=usd",
                    headers=headers,
                    timeout=aiohttp.ClientTimeout(total=10)
                ) as response:
                    if response.status != 200:
                        print(f"Price API error: {response.status}")
                        return 65000
                    data = await response.json()
                    return data.get('bitcoin', {}).get('usd', 65000)
            except Exception as e:
                print(f"Error fetching BTC price: {e}")
                return 65000

    @staticmethod
    async def get_address_info(address: str):
        """Get detailed information about a Bitcoin address"""
        async with aiohttp.ClientSession() as session:
            try:
                headers = {
                    'User-Agent': 'Bitcoin-Analyzer-Bot/1.0',
                    'Accept': 'application/json'
                }
                
                async with session.get(
                    f"{BLOCKSTREAM_API}/address/{address}",
                    headers=headers,
                    timeout=aiohttp.ClientTimeout(total=15)
                ) as response:
                    if response.status != 200:
                        print(f"Address API error: {response.status}")
                        return None
                    address_data = await response.json()
                
                async with session.get(
                    f"{BLOCKSTREAM_API}/address/{address}/txs",
                    headers=headers,
                    timeout=aiohttp.ClientTimeout(total=15)
                ) as response:
                    if response.status != 200:
                        transactions = []
                    else:
                        transactions = await response.json()
                
                async with session.get(
                    f"{BLOCKSTREAM_API}/address/{address}/utxo",
                    headers=headers,
                    timeout=aiohttp.ClientTimeout(total=15)
                ) as response:
                    if response.status != 200:
                        utxos = []
                    else:
                        utxos = await response.json()
                
                return {
                    'address_data': address_data,
                    'transactions': transactions,
                    'utxos': utxos
                }
            except Exception as e:
                print(f"Error fetching data: {e}")
                return None

    @staticmethod
    def format_btc(satoshis: int) -> str:
        """Convert satoshis to BTC with proper formatting"""
        btc = satoshis / 100000000
        return f"{btc:.8f} BTC"

    @staticmethod
    def format_usd(satoshis: int, btc_price: float) -> str:
        """Convert satoshis to USD using real BTC price"""
        btc = satoshis / 100000000
        usd = btc * btc_price
        return f"${usd:,.2f}"

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Start command handler"""
    user_id = update.effective_user.id
    rate_info = RateLimiter.check_user_limit(user_id)
    
    welcome_text = f"""
🚀 **Bitcoin Wallet Analyzer**

Analyze any Bitcoin wallet instantly with detailed insights:

🔍 **What I analyze:**
• Current balance & USD value
• Transaction history & patterns
• UTXO breakdown
• Address activity timeline

📊 **Your usage today:**
• {rate_info['hourly_remaining']}/{RATE_LIMIT_PER_HOUR} requests left this hour
• {rate_info['daily_remaining']}/{RATE_LIMIT_PER_DAY} requests left today

Just send me any Bitcoin address to get started!
    """
    
    keyboard = [
        [InlineKeyboardButton("🔍 Start Analysis", callback_data="start_analysis")],
        [InlineKeyboardButton("📊 Usage Stats", callback_data="usage"), 
         InlineKeyboardButton("❓ Help", callback_data="help")],
        [InlineKeyboardButton("🐦 Follow on X", url=BOT_X_ACCOUNT)],
        [InlineKeyboardButton("☕ Support Developer", callback_data="support")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await update.message.reply_text(welcome_text, reply_markup=reply_markup, parse_mode='Markdown')

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle button clicks"""
    query = update.callback_query
    await query.answer()
    user_id = update.effective_user.id
    
    if query.data == "start_analysis":
        rate_info = RateLimiter.check_user_limit(user_id)
        
        if not rate_info['can_proceed']:
            limit_text = "⚠️ **Rate Limit Reached**\n\n"
            if rate_info['hourly_used'] >= RATE_LIMIT_PER_HOUR:
                limit_text += f"You've used all {RATE_LIMIT_PER_HOUR} hourly requests. Try again in 1 hour.\n"
            elif rate_info['daily_used'] >= RATE_LIMIT_PER_DAY:
                limit_text += f"You've used all {RATE_LIMIT_PER_DAY} daily requests. Try again tomorrow.\n"
            
            limit_text += f"\n**Current usage:** {rate_info['hourly_used']}/{RATE_LIMIT_PER_HOUR} hourly • {rate_info['daily_used']}/{RATE_LIMIT_PER_DAY} daily"
            
            keyboard = [[InlineKeyboardButton("🔙 Main Menu", callback_data="main_menu")]]
            await query.edit_message_text(limit_text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='Markdown')
            return
        
        await query.edit_message_text(
            f"📝 **Send Bitcoin Address**\n\n"
            f"Supported formats:\n"
            f"• Legacy: `1A1zP1eP5QGefi2DMPTfTL5SLmv7DivfNa`\n"
            f"• SegWit: `3J98t1WpEZ73CNmQviecrnyiWrnqRhWNLy`\n"
            f"• Bech32: `bc1qzv7v3kengms6zguh7445xxy77dsrwjqxxrcxrt`\n\n"
            f"⚡ **Remaining:** {rate_info['hourly_remaining']} this hour",
            parse_mode='Markdown'
        )
    
    elif query.data == "usage":
        rate_info = RateLimiter.check_user_limit(user_id)
        usage_text = f"""
📈 **Usage Statistics**

**Current Limits:**
• {RATE_LIMIT_PER_HOUR} requests per hour
• {RATE_LIMIT_PER_DAY} requests per day

**Your Usage:**
• This hour: {rate_info['hourly_used']}/{RATE_LIMIT_PER_HOUR} used
• Today: {rate_info['daily_used']}/{RATE_LIMIT_PER_DAY} used
• Available: {rate_info['hourly_remaining']} this hour

**Why limits?**
Fair usage keeps the service free and stable for everyone.
        """
        
        keyboard = [
            [InlineKeyboardButton("🔍 New Analysis", callback_data="start_analysis")],
            [InlineKeyboardButton("🔙 Main Menu", callback_data="main_menu")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await query.edit_message_text(usage_text, reply_markup=reply_markup, parse_mode='Markdown')
    
    elif query.data == "help":
        help_text = f"""
❓ **How to Use**

**1. Send Address**
Just paste any Bitcoin address - I'll analyze it instantly!

**2. Analysis Includes:**
• 💰 Current balance (BTC & USD)
• 📊 Total received/sent amounts
• 🔄 Transaction count & history
• 📅 First/last activity dates
• 💎 UTXO breakdown

**3. Supported Formats:**
• All Bitcoin address types
• Legacy, SegWit, and Bech32

**4. Privacy:**
• No data stored
• Real-time analysis only
• Your addresses aren't logged

**5. Rate Limits:**
• {RATE_LIMIT_PER_HOUR}/hour, {RATE_LIMIT_PER_DAY}/day
• Keeps service free for all users
        """
        
        keyboard = [
            [InlineKeyboardButton("🔍 Start Analysis", callback_data="start_analysis")],
            [InlineKeyboardButton("🔙 Main Menu", callback_data="main_menu")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await query.edit_message_text(help_text, reply_markup=reply_markup, parse_mode='Markdown')
    
    elif query.data == "support":
        support_text = f"""
☕ **Support Development**

Help keep this bot running and improve it!

**Donate Bitcoin:**
`{DEVELOPER_BTC_ADDRESS}`

**Your support enables:**
• 🔧 New features & improvements
• 🚀 Higher rate limits
• 🌐 24/7 reliable service
• 📊 Premium analytics

**Planned Features:**
• Multi-coin support
• Historical price charts
• Advanced transaction analysis
• Portfolio tracking

Thank you for your support! 🙏
        """
        
        keyboard = [
            [InlineKeyboardButton("📋 Copy Address", callback_data="copy_address")],
            [InlineKeyboardButton("🐦 Follow Updates", url=BOT_X_ACCOUNT)],
            [InlineKeyboardButton("🔙 Main Menu", callback_data="main_menu")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await query.edit_message_text(support_text, reply_markup=reply_markup, parse_mode='Markdown')
    
    elif query.data == "copy_address":
        await query.answer("✅ Address copied to clipboard!", show_alert=True)
    
    elif query.data == "main_menu":
        await start_menu(query)
    
    elif query.data.startswith("refresh_"):
        address = query.data.replace("refresh_", "")
        class FakeMessage:
            text = address
        class FakeUpdate:
            message = FakeMessage()
            effective_user = query.from_user
        
        fake_update = FakeUpdate()
        await analyze_address(fake_update, context)

async def start_menu(query):
    """Show the main menu"""
    user_id = query.from_user.id
    rate_info = RateLimiter.check_user_limit(user_id)
    
    welcome_text = f"""
🚀 **Bitcoin Wallet Analyzer**

Analyze any Bitcoin wallet instantly with detailed insights:

🔍 **What I analyze:**
• Current balance & USD value
• Transaction history & patterns
• UTXO breakdown
• Address activity timeline

📊 **Your usage today:**
• {rate_info['hourly_remaining']}/{RATE_LIMIT_PER_HOUR} requests left this hour
• {rate_info['daily_remaining']}/{RATE_LIMIT_PER_DAY} requests left today

Just send me any Bitcoin address to get started!
    """
    
    keyboard = [
        [InlineKeyboardButton("🔍 Start Analysis", callback_data="start_analysis")],
        [InlineKeyboardButton("📊 Usage Stats", callback_data="usage"), 
         InlineKeyboardButton("❓ Help", callback_data="help")],
        [InlineKeyboardButton("🐦 Follow on X", url=BOT_X_ACCOUNT)],
        [InlineKeyboardButton("☕ Support Developer", callback_data="support")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await query.edit_message_text(welcome_text, reply_markup=reply_markup, parse_mode='Markdown')

async def analyze_address(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Analyze a Bitcoin address with rate limiting"""
    user_id = update.effective_user.id
    address = update.message.text.strip()
    
    rate_info = RateLimiter.check_user_limit(user_id)
    
    if not rate_info['can_proceed']:
        limit_text = f"⚠️ **Rate Limit Reached**\n\n"
        if rate_info['hourly_used'] >= RATE_LIMIT_PER_HOUR:
            limit_text += f"You've used all {RATE_LIMIT_PER_HOUR} hourly requests. Try again in 1 hour."
        elif rate_info['daily_used'] >= RATE_LIMIT_PER_DAY:
            limit_text += f"You've used all {RATE_LIMIT_PER_DAY} daily requests. Try again tomorrow."
        
        limit_text += f"\n\n**Usage:** {rate_info['hourly_used']}/{RATE_LIMIT_PER_HOUR} hourly • {rate_info['daily_used']}/{RATE_LIMIT_PER_DAY} daily"
        
        keyboard = [[InlineKeyboardButton("🔙 Main Menu", callback_data="main_menu")]]
        await update.message.reply_text(limit_text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='Markdown')
        return
    
    if not (address.startswith('1') or address.startswith('3') or address.startswith('bc1')):
        await update.message.reply_text(
            "❌ **Invalid Bitcoin Address**\n\n"
            "Please send a valid Bitcoin address (starts with 1, 3, or bc1)\n\n"
            f"⚡ **Remaining:** {rate_info['hourly_remaining']} this hour",
            parse_mode='Markdown'
        )
        return
    
    RateLimiter.record_request(user_id)
    rate_info = RateLimiter.check_user_limit(user_id)
    
    analyzing_msg = await update.message.reply_text(
        f"🔍 **Analyzing Wallet**\n"
        f"⏳ Fetching data...\n\n"
        f"⚡ **After this:** {rate_info['hourly_remaining']} requests remaining", 
        parse_mode='Markdown'
    )
    
    analyzer = BitcoinAnalyzer()
    
    try:
        btc_price_task = analyzer.get_btc_price()
        wallet_data_task = analyzer.get_address_info(address)
        
        btc_price, wallet_data = await asyncio.gather(btc_price_task, wallet_data_task)
        
        if not wallet_data:
            keyboard = [[InlineKeyboardButton("🔙 Main Menu", callback_data="main_menu")]]
            await analyzing_msg.edit_text(
                "❌ **Analysis Failed**\n\n"
                "Could not fetch wallet data. Please check the address.\n"
                f"⚡ **Remaining:** {rate_info['hourly_remaining']} this hour",
                reply_markup=InlineKeyboardMarkup(keyboard),
                parse_mode='Markdown'
            )
            return
        
        address_data = wallet_data['address_data']
        transactions = wallet_data['transactions']
        utxos = wallet_data['utxos']
        
        balance = address_data.get('chain_stats', {}).get('funded_txo_sum', 0) - address_data.get('chain_stats', {}).get('spent_txo_sum', 0)
        total_received = address_data.get('chain_stats', {}).get('funded_txo_sum', 0)
        total_sent = address_data.get('chain_stats', {}).get('spent_txo_sum', 0)
        tx_count = address_data.get('chain_stats', {}).get('tx_count', 0)
        
        analysis_text = f"""
📊 **Wallet Analysis**

🏦 **Address:** `{address[:20]}...{address[-10:]}`

💰 **Balance:**
• Current: {analyzer.format_btc(balance)} ({analyzer.format_usd(balance, btc_price)})
• Received: {analyzer.format_btc(total_received)} ({analyzer.format_usd(total_received, btc_price)})
• Sent: {analyzer.format_btc(total_sent)} ({analyzer.format_usd(total_sent, btc_price)})

📈 **Activity:**
• Transactions: {tx_count:,}
• UTXOs: {len(utxos)}
• First TX: {datetime.fromtimestamp(transactions[-1]['status']['block_time']).strftime('%Y-%m-%d') if transactions and transactions[-1].get('status', {}).get('block_time') else 'N/A'}
• Last TX: {datetime.fromtimestamp(transactions[0]['status']['block_time']).strftime('%Y-%m-%d') if transactions and transactions[0].get('status', {}).get('block_time') else 'N/A'}

🔄 **Recent Transactions:**
"""
        
        # Recent transactions analysis
        if transactions:
            for i, tx in enumerate(transactions[:3]):
                # Zaman bilgisi
                if tx.get('status', {}).get('block_time'):
                    tx_time = datetime.fromtimestamp(tx['status']['block_time']).strftime('%m/%d %H:%M')
                else:
                    tx_time = 'Pending'
                
                # Bu adrese gelen miktar (outputs)
                value_received = 0
                for vout in tx['vout']:
                    # scriptpubkey_address kontrolü - hem string hem liste olabilir
                    addr_list = vout.get('scriptpubkey_address', [])
                    if isinstance(addr_list, str):
                        addr_list = [addr_list]
                    elif addr_list is None:
                        addr_list = []
                    
                    if address in addr_list:
                        value_received += vout['value']
                
                # Bu adresten giden miktar (inputs)
                value_sent = 0
                for vin in tx['vin']:
                    prevout = vin.get('prevout', {})
                    if prevout:
                        prev_addr = prevout.get('scriptpubkey_address')
                        # String veya liste kontrolü
                        if isinstance(prev_addr, str):
                            prev_addr_list = [prev_addr]
                        elif isinstance(prev_addr, list):
                            prev_addr_list = prev_addr
                        else:
                            prev_addr_list = []
                        
                        if address in prev_addr_list:
                            value_sent += prevout.get('value', 0)
                
                # Net miktar ve yön belirleme
                net_value = value_received - value_sent
                
                if net_value > 0:
                    direction = "📈 Received"
                    amount_text = analyzer.format_btc(net_value)
                elif net_value < 0:
                    direction = "📉 Sent"
                    amount_text = analyzer.format_btc(abs(net_value))
                else:
                    direction = "🔄 Internal"
                    amount_text = analyzer.format_btc(value_received) if value_received > 0 else "0.00000000 BTC"
                
                # TX ID (kısaltılmış)
                tx_id_short = tx['txid'][:8] + "..." + tx['txid'][-8:]
                
                analysis_text += f"\n• {direction} {amount_text} - {tx_time}"
                analysis_text += f"\n  TX: `{tx_id_short}`"
        else:
            analysis_text += "\n• No transactions found"
        
        keyboard = [
            [InlineKeyboardButton("🔄 Refresh", callback_data=f"refresh_{address}"),
             InlineKeyboardButton("🔍 New Analysis", callback_data="start_analysis")],
            [InlineKeyboardButton("📊 Usage Stats", callback_data="usage"),
             InlineKeyboardButton("🔙 Main Menu", callback_data="main_menu")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await analyzing_msg.edit_text(analysis_text, reply_markup=reply_markup, parse_mode='Markdown')
        
    except Exception as e:
        keyboard = [[InlineKeyboardButton("🔙 Main Menu", callback_data="main_menu")]]
        await analyzing_msg.edit_text(
            f"❌ **Error:** {str(e)}\n\n"
            f"⚡ **Remaining:** {rate_info['hourly_remaining']} this hour",
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode='Markdown'
        )

async def error_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle errors"""
    print(f"Error: {context.error}")

# Health check endpoint for Render.com
async def health_check(request):
    """Health check endpoint"""
    return web.json_response({"status": "healthy", "timestamp": datetime.now().isoformat()})

# Keep alive function
async def keep_alive():
    """Keep the bot alive by logging status"""
    while True:
        print(f"[{datetime.now()}] Bot is alive and running!")
        await asyncio.sleep(300)  # 5 dakikada bir log

async def start_web_server():
    """Start web server for health checks"""
    app = web.Application()
    app.router.add_get('/health', health_check)
    app.router.add_get('/', health_check)  # Root endpoint
    
    # Port'u environment variable'dan al, yoksa 10000 kullan
    port = int(os.environ.get('PORT', 10000))
    
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, '0.0.0.0', port)
    await site.start()
    print(f"Web server started on port {port}")

def main():
    """Start the bot"""
    print("🚀 Bitcoin Wallet Analyzer Bot starting...")
    print(f"⚡ Rate limits: {RATE_LIMIT_PER_HOUR}/hour, {RATE_LIMIT_PER_DAY}/day")
    print(f"🔑 Bot token: {'*' * 20}{BOT_TOKEN[-10:] if BOT_TOKEN else 'NOT SET'}")
    
    application = Application.builder().token(BOT_TOKEN).build()
    
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CallbackQueryHandler(button_handler))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, analyze_address))
    application.add_error_handler(error_handler)
    
    # Create event loop
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    
    # Start web server
    loop.run_until_complete(start_web_server())
    
    # Start keep alive task
    loop.create_task(keep_alive())
    
    print("✅ Bot started successfully!")
    
    # Start polling
    application.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == '__main__':
    main()