import asyncio
import time
import re
import os
import random
from telethon import TelegramClient, events
from telethon.tl.functions.messages import ImportChatInviteRequest
from telethon.tl.functions.messages import GetDialogsRequest
from telethon.tl.types import InputPeerEmpty

API_ID = 24268062  # Telegram API ID
API_HASH = 'aaab3d4a5ab8f7b3024a3edbd88cabf7'  # Telegram API HASH
SESSION = 'eden_session'
OTP_GROUP_FILE = 'otp_group.txt'
NUMBERS_FILE = 'number.txt'

def clear():
    os.system('cls' if os.name == 'nt' else 'clear')

async def login_flow():
    clear()
    print('=== Eden OTP Automation ===')
    phone = input('Enter your Telegram phone number (with country code): ')
    client = TelegramClient(SESSION, API_ID, API_HASH)
    await client.start(phone=phone)
    if await client.is_user_authorized():
        print('Login successful!')
        return client
    else:
        print('Login failed. Exiting.')
        return None

def parse_telegram_link(link):
    """
    Parses a Telegram link to extract the chat ID and topic ID.
    Example: https://t.me/c/3646225906/2 -> Chat ID: -1003646225906, Topic ID: 2
    """
    chat_id = None
    topic_id = None
    
    # Handle private channel/group links: https://t.me/c/123456789/123
    match = re.search(r't\.me/c/(\d+)(?:/(\d+))?', link)
    if match:
        chat_id = int("-100" + match.group(1))
        if match.group(2):
            topic_id = int(match.group(2))
        return chat_id, topic_id
    
    # Handle public links: https://t.me/username/123
    match = re.search(r't\.me/([^/]+)(?:/(\d+))?', link)
    if match:
        chat_id = match.group(1)
        if match.group(2):
            topic_id = int(match.group(2))
        return chat_id, topic_id
        
    return link, None

def extract_otp(text):
    """
    Extracts a 6-digit OTP from text, handling formats like 123456 or 123-456.
    """
    if not text:
        return None
    # Look for 6 digits with optional separator (hyphen, space, etc.)
    match = re.search(r'(\d{3})[\s-]?(\d{3})', text)
    if match:
        return match.group(1) + match.group(2)
    # Fallback for any 6 consecutive digits
    match = re.search(r'(\d{6})', text)
    if match:
        return match.group(1)
    return None

async def check_otp_monitoring(client):
    print('\n--- LIVE OTP MONITORING ---')
    if not os.path.exists(OTP_GROUP_FILE):
        print('OTP group link not set. Please add OTP group first.')
        return
    with open(OTP_GROUP_FILE) as f:
        group_link = f.read().strip()
    
    chat_id, topic_id = parse_telegram_link(group_link)
    
    try:
        group_entity = await client.get_entity(chat_id)
        title = getattr(group_entity, 'title', str(chat_id))
        if topic_id:
            print(f'Monitoring group: {title} (Topic ID: {topic_id})')
        else:
            print(f'Monitoring group: {title}')
    except Exception as e:
        print(f'Could not access group: {e}')
        return

    print('Showing live messages (Press Ctrl+C to stop monitoring and return to menu)...')
    
    async def live_handler(event):
        # If it's a topic group, filter by topic ID (reply_to_msg_id)
        if topic_id and event.message.reply_to:
            if event.message.reply_to.reply_to_msg_id != topic_id:
                return
        
        sender = await event.get_sender()
        name = getattr(sender, 'first_name', 'Unknown')
        
        # Check message text
        msg_text = event.raw_text
        otp_in_text = extract_otp(msg_text)
        
        # Check buttons
        otp_in_button = None
        if event.message.reply_markup:
            for row in event.message.reply_markup.rows:
                for button in row.buttons:
                    otp_in_button = extract_otp(button.text)
                    if otp_in_button:
                        break
                if otp_in_button:
                    break
        
        display_text = msg_text.replace('\n', ' ')
        if otp_in_button:
            print(f'[{time.strftime("%H:%M:%S")}] {name}: {display_text} | [BUTTON OTP: {otp_in_button}]')
        elif otp_in_text:
            print(f'[{time.strftime("%H:%M:%S")}] {name}: {display_text} | [TEXT OTP: {otp_in_text}]')
        else:
            print(f'[{time.strftime("%H:%M:%S")}] {name}: {display_text}')

    handler = client.add_event_handler(live_handler, events.NewMessage(chats=group_entity))
    
    try:
        while True:
            await asyncio.sleep(1)
    except (KeyboardInterrupt, asyncio.CancelledError):
        print('\nStopping live monitoring...')
    finally:
        client.remove_event_handler(handler)

async def start_task(client):
    print('Starting task...')
    if not os.path.exists(OTP_GROUP_FILE):
        print('OTP group link not set. Please add OTP group first.')
        return
    with open(OTP_GROUP_FILE) as f:
        group_link = f.read().strip()
    
    chat_id, topic_id = parse_telegram_link(group_link)
    
    if isinstance(chat_id, str) and not chat_id.startswith('-100'):
        try:
            await client(ImportChatInviteRequest(chat_id))
            print(f'Joined OTP group: {group_link}')
        except Exception:
            pass

    if not os.path.exists(NUMBERS_FILE):
        print('number.txt not found. Please add file first.')
        return
    
    with open(NUMBERS_FILE) as f:
        numbers = [line.strip() for line in f if line.strip()]
    if not numbers:
        print('No numbers found in number.txt.')
        return
    print(f'Loaded {len(numbers)} numbers.')
    random.shuffle(numbers)

    try:
        group_entity = await client.get_entity(chat_id)
    except Exception as e:
        print(f'Could not find OTP group: {e}')
        return

    bot_link = 'wsotp200bot'
    bot_entity = await client.get_entity(bot_link)

    results = {}
    processed_count = 0
    otps = {}
    pending = set()
    last_group_activity = time.time()

    async def otp_handler(event):
        nonlocal last_group_activity
        last_group_activity = time.time()
        
        if topic_id and event.message.reply_to:
            if event.message.reply_to.reply_to_msg_id != topic_id:
                return
                
        msg_text = event.raw_text
        
        # Collect all possible OTPs from text and buttons
        found_otps = []
        
        # Check text
        otp_text = extract_otp(msg_text)
        if otp_text:
            found_otps.append(otp_text)
            
        # Check buttons
        if event.message.reply_markup:
            for row in event.message.reply_markup.rows:
                for button in row.buttons:
                    otp_btn = extract_otp(button.text)
                    if otp_btn:
                        found_otps.append(otp_btn)

        if not found_otps:
            return

        for number in list(pending):
            last3 = number[-3:]
            if last3 in msg_text:
                for otp in found_otps:
                    if otps.get(number) != otp:
                        otps[number] = otp
                        print(f'\r[GROUP] {time.strftime("%H:%M:%S")} | OTP found for {number}: {otp}    ')
                        break
    
    handler = client.add_event_handler(otp_handler, events.NewMessage(chats=group_entity))

    try:
        batch_size = 4
        numbers_left = numbers.copy()
        while numbers_left:
            batch = random.sample(numbers_left, min(batch_size, len(numbers_left)))
            pending.update(batch)
            for number in batch:
                await client.send_message(bot_entity, number)
                print(f'[BOT] {time.strftime("%H:%M:%S")} | Sent number to bot: {number}')
            
            start_time = time.time()
            spinner = ['|', '/', '-', '\\']
            spin_idx = 0
            last_status = {n: '' for n in batch}
            
            while pending and time.time() - start_time < 240:
                # Check bot messages for all pending numbers in the batch
                async for msg in client.iter_messages(bot_entity, limit=20):
                    for number in list(pending):
                        if number in msg.raw_text:
                            if 'In Progress' in msg.raw_text:
                                if last_status[number] != msg.raw_text:
                                    last_status[number] = msg.raw_text
                                if number in otps:
                                    otp = otps[number]
                                    print(f'\r[BOT] {time.strftime("%H:%M:%S")} | Replied OTP for {number}: {otp}    ')
                                    await client.send_message(bot_entity, otp, reply_to=msg.id)
                                    results[number] = 'success'
                                    processed_count += 1
                                    pending.remove(number)
                            elif any(x in msg.raw_text.lower() for x in ['try later', 'submit this number again', 'invalid']):
                                print(f'\r[BOT] {time.strftime("%H:%M:%S")} | {number}: {msg.raw_text.splitlines()[0]}    ')
                                results[number] = 'invalid'
                                pending.remove(number)
                                break
                
                # Connection Heartbeat: Check if we've seen any group activity recently
                group_status = "🟢 Active" if time.time() - last_group_activity < 30 else "🟡 Idle"
                
                # Update progress line
                status_summary = ", ".join([f"{n[-3:]}: {last_status[n].split(':')[-1].strip() if last_status[n] else 'Waiting'}" for n in batch if n in pending])
                print(f'\r[INFO] {time.strftime("%H:%M:%S")} | {spinner[spin_idx % 4]} Group: {group_status} | Monitoring: {status_summary}    ', end='', flush=True)
                spin_idx += 1
                await asyncio.sleep(5)
            
            print() # Newline after batch
            for number in batch:
                if number not in results:
                    print(f'[TIMEOUT] {time.strftime("%H:%M:%S")} | No OTP for {number} after 4 minutes.')
                    results[number] = 'timeout'
                    if number in pending:
                        pending.remove(number)
                if number in numbers_left:
                    numbers_left.remove(number)
            
            print(f'[PROGRESS] {time.strftime("%H:%M:%S")} | {processed_count}/{len(numbers)} successful')
            
        print('[DONE] All numbers processed.')
    finally:
        client.remove_event_handler(handler)

async def main():
    client = await login_flow()
    if not client:
        return
    while True:
        print('\nMenu:')
        print('1. Add OTP Group')
        print('2. Add File')
        print('3. Start Task')
        print('4. Status')
        print('5. /check (Confirm OTP Monitoring)')
        print('6. Exit')
        choice = input('Select an option: ')
        if choice == '1':
            group_link = input('Paste OTP group link: ').strip()
            with open(OTP_GROUP_FILE, 'w') as f:
                f.write(group_link)
            print('OTP group link saved.')
        elif choice == '2':
            if os.path.exists(NUMBERS_FILE):
                print('number.txt found and loaded.')
            else:
                print('number.txt not found. Please create it with one number per line (with country code).')
        elif choice == '3':
            await start_task(client)
        elif choice == '4':
            print('Status not implemented yet.')
        elif choice == '5' or choice.lower() == '/check':
            await check_otp_monitoring(client)
        elif choice == '6':
            print('Goodbye!')
            break
        else:
            print('Invalid option. Try again.')

if __name__ == '__main__':
    asyncio.run(main())
