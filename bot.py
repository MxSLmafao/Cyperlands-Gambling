import discord
from discord.ext import commands, tasks
import random
import json
import os
import yaml
import asyncio
import math
from discord.ext.commands import BucketType
from datetime import datetime, timedelta

# Load configuration from config.yml
with open('config.yml', 'r') as f:
    config = yaml.safe_load(f)

TOKEN = config['token']
DEFAULT_CURRENCY = config['default_currency']
ADMINS = [int(admin_id) for admin_id in config['admins']]
ALLOWED_CHANNELS = config['allowed_channels']
DM_FORWARD_CHANNEL_ID = int(config['dm_forward_channel_id'])

ROB_AMOUNT_PERCENT = config['rob']['rob_amount']
FAIL_DEDUCTION_PERCENT = config['rob']['fail_deduction']
ROB_COOLDOWN = config['rob']['cooldown']
LOTTERY_TICKET_PRICE = config['lottery_ticket_price']

intents = discord.Intents.default()
intents.message_content = True
intents.guilds = True
intents.members = True
intents.messages = True  # Ensure intents for messages are enabled

bot = commands.Bot(command_prefix='$', intents=intents)

# Load or initialize user data
if os.path.exists('users.json'):
    with open('users.json', 'r') as f:
        users = json.load(f)
else:
    users = {}

# Initialize locks for commands to prevent double execution
command_locks = {
    'new_user': asyncio.Lock(),
    'check_balance': asyncio.Lock(),
    'give': asyncio.Lock(),
    'add': asyncio.Lock(),
    'remove': asyncio.Lock(),
    'clear': asyncio.Lock(),
    'ban': asyncio.Lock(),
    'rob': asyncio.Lock(),
    'lottery': asyncio.Lock(),
    'leaderboard': asyncio.Lock(),
    'reset': asyncio.Lock()
}

def save_users():
    with open('users.json', 'w') as f:
        json.dump(users, f)

@bot.event
async def on_ready():
    print(f'Bot connected as {bot.user}')
    leaderboard_reset.start()  # Start the weekly leaderboard reset task

def is_allowed_channel(ctx):
    return str(ctx.channel.id) in ALLOWED_CHANNELS

def is_admin(ctx):
    return ctx.author.id in ADMINS

# Custom Help Command with Embed
class CustomHelpCommand(commands.HelpCommand):
    def __init__(self):
        super().__init__()

    async def send_bot_help(self, mapping):
        ctx = self.context
        embed = discord.Embed(title="Help - Available Commands", color=discord.Color.blue())
        embed.description = "Here are the commands you can use with this bot. Admin-only commands are marked with 🛠️."

        for cog, commands in mapping.items():
            for command in commands:
                if command.hidden:
                    continue
                if is_admin(ctx) or command.name not in ['add', 'remove', 'clear', 'reset', 'force_reset']:
                    is_admin_command = command.name in ['add', 'remove', 'clear', 'reset', 'force_reset']
                    admin_icon = " 🛠️" if is_admin_command else ""
                    embed.add_field(name=f"`{ctx.prefix}{command.name}`{admin_icon}", value=command.help or "No description", inline=False)

        await ctx.send(embed=embed)

    async def send_command_help(self, command):
        ctx = self.context
        embed = discord.Embed(title=f"Help - {command.name}", description=command.help or "No description", color=discord.Color.blue())
        await ctx.send(embed=embed)

bot.help_command = CustomHelpCommand()

# $check command - Check your balance or another user's balance
@bot.command(name='check', help='Check your current Aura balance or another user\'s balance.')
@commands.check(is_allowed_channel)
async def check_aura(ctx, member: discord.Member = None):
    async with command_locks['check_balance']:
        user = member if member else ctx.author
        user_id = str(user.id)

        if user_id in users:
            balance = users[user_id]['balance']
            await ctx.send(f"{user.mention} has {balance} Aura.")
        else:
            await ctx.send(f"{user.mention} does not have an account. Use $new to create one.")

# $rob command - Rob another user with a random success chance
@bot.command(name='rob', help='Rob another user for a percentage of their Aura with a random chance of success.')
@commands.check(is_allowed_channel)
@commands.cooldown(1, ROB_COOLDOWN, BucketType.user)  # Cooldown taken from config.yml
async def rob(ctx, member: discord.Member):
    async with command_locks['rob']:
        print(f"Rob command invoked by {ctx.author} to rob {member}")  # Debug statement
        robber_id = str(ctx.author.id)
        victim_id = str(member.id)

        if robber_id not in users:
            await ctx.send(f"{ctx.author.mention} You do not have an account. Use $new to create one.")
            return

        if victim_id not in users:
            await ctx.send(f"{ctx.author.mention} The user you are trying to rob does not have an account.")
            return

        if robber_id == victim_id:
            await ctx.send(f"{ctx.author.mention} You cannot rob yourself.")
            return

        robber_balance = users[robber_id]['balance']
        victim_balance = users[victim_id]['balance']

        if victim_balance == 0:
            await ctx.send(f"{ctx.author.mention} The user you are trying to rob has no Aura.")
            return

        rob_amount = math.floor(ROB_AMOUNT_PERCENT * victim_balance)
        success_chance = random.random() < random.random()  # Random success chance

        if success_chance:
            users[robber_id]['balance'] += rob_amount
            users[victim_id]['balance'] -= rob_amount
            save_users()
            await ctx.send(f"{member.mention}, you just got fanum taxed by {ctx.author.mention}!")
        else:
            fail_amount = math.floor(FAIL_DEDUCTION_PERCENT * robber_balance)
            users[robber_id]['balance'] -= fail_amount
            save_users()
            await ctx.send(f"{ctx.author.mention}, damn bro ain't him - {fail_amount} Aura!")

@rob.error
async def rob_error(ctx, error):
    if isinstance(error, commands.BadArgument):
        await ctx.send(f"{ctx.author.mention} Please enter a valid user mention or user ID.")
    elif isinstance(error, commands.MissingRequiredArgument):
        await ctx.send(f"{ctx.author.mention} Please specify a user to rob.")
    elif isinstance(error, commands.CommandOnCooldown):
        await ctx.send(f"{ctx.author.mention} You can use this command again in {round(error.retry_after, 2)} seconds.")

# $leaderboard / $top command - Show the top 10 users
@bot.command(name='leaderboard', aliases=['top'], help='Show the top 10 users in the leaderboard.')
@commands.check(is_allowed_channel)
async def leaderboard(ctx):
    async with command_locks['leaderboard']:
        sorted_users = sorted(users.items(), key=lambda x: x[1]['balance'], reverse=True)[:10]
        if sorted_users:
            embed = discord.Embed(title="Leaderboard - Top 10", color=discord.Color.blue())
            for i, (user_id, data) in enumerate(sorted_users, start=1):
                user = bot.get_user(int(user_id))
                embed.add_field(name=f"{i}. {user.display_name if user else 'Unknown'}", value=f"Aura: {data['balance']}", inline=False)
            await ctx.send(embed=embed)
        else:
            await ctx.send("No users found on the leaderboard.")

# $reset command - Admin command to reset a specific user's balance
@bot.command(name='reset', help='Admin command to reset a user\'s balance to the default value.')
@commands.check(is_admin)
async def reset_balance(ctx, member: discord.Member):
    async with command_locks['reset']:
        user_id = str(member.id)
        if user_id in users:
            users[user_id]['balance'] = DEFAULT_CURRENCY
            save_users()
            await ctx.send(f"{member.mention}'s balance has been reset to {DEFAULT_CURRENCY} Aura.")
        else:
            await ctx.send(f"{member.mention} does not have an account.")

# Reset leaderboard every week (resets everyone’s Aura balance)
@tasks.loop(hours=168)  # 168 hours = 1 week
async def leaderboard_reset():
    now = datetime.now()
    print(f"Leaderboard reset started at {now}")
    for user_id in users:
        users[user_id]['balance'] = DEFAULT_CURRENCY  # Reset everyone's balance to the default value
    save_users()
    print("Leaderboard has been reset.")

# Manually invoke the leaderboard reset (for debugging)
@bot.command(name='force_reset', help='Force reset the leaderboard (Admin only).')
@commands.check(is_admin)
async def force_reset(ctx):
    await leaderboard_reset()
    await ctx.send("Leaderboard has been forcefully reset.")

@bot.command(name='give', help='Give the specified amount of Aura to another user.')
@commands.check(is_allowed_channel)
async def give(ctx, amount: int, member: discord.Member):
    async with command_locks['give']:
        giver_id = str(ctx.author.id)
        receiver_id = str(member.id)

        if giver_id not in users:
            await ctx.send(f"{ctx.author.mention} You do not have an account. Use $new to create one.")
            return

        if receiver_id not in users:
            await ctx.send(f"{member.mention} does not have an account.")
            return

        if users[giver_id]['balance'] < amount:
            await ctx.send(f"{ctx.author.mention} You do not have enough Aura to give {amount}.")
            return

        users[giver_id]['balance'] -= amount
        users[receiver_id]['balance'] += amount
        save_users()

        await ctx.send(f"{ctx.author.mention} gave {amount} Aura to {member.mention}!")

@give.error
async def give_error(ctx, error):
    if isinstance(error, commands.BadArgument):
        await ctx.send(f"{ctx.author.mention} Please enter a valid amount and user ID.")
    elif isinstance(error, commands.MissingRequiredArgument):
        await ctx.send(f"{ctx.author.mention} Please specify an amount and user ID.")

@bot.command(name='add', help='Add the specified amount of Aura to a user (Admin only).')
@commands.check(is_admin)
async def add(ctx, amount: int, member: discord.Member):
    async with command_locks['add']:
        receiver_id = str(member.id)

        if receiver_id not in users:
            users[receiver_id] = {'balance': DEFAULT_CURRENCY}
        
        users[receiver_id]['balance'] += amount
        save_users()

        await ctx.send(f"{ctx.author.mention} {amount} Aura has been added to {member.mention}'s account.")

@add.error
async def add_error(ctx, error):
    if isinstance(error, commands.BadArgument):
        await ctx.send(f"{ctx.author.mention} Please enter a valid amount and user ID.")
    elif isinstance(error, commands.MissingRequiredArgument):
        await ctx.send(f"{ctx.author.mention} Please specify an amount and user ID.")

@bot.command(name='remove', help='Remove the specified amount of Aura from a user (Admin only).')
@commands.check(is_admin)
async def remove(ctx, amount: int, member: discord.Member):
    async with command_locks['remove']:
        receiver_id = str(member.id)

        if receiver_id not in users:
            await ctx.send(f"{member.mention} does not have an account.")
            return

        if users[receiver_id]['balance'] < amount:
            await ctx.send(f"{ctx.author.mention} {member.mention} does not have enough Aura to remove {amount}.")
            return

        users[receiver_id]['balance'] -= amount
        save_users()

        await ctx.send(f"{ctx.author.mention} {amount} Aura has been removed from {member.mention}'s account.")

@remove.error
async def remove_error(ctx, error):
    if isinstance(error, commands.BadArgument):
        await ctx.send(f"{ctx.author.mention} Please enter a valid amount and user ID.")
    elif isinstance(error, commands.MissingRequiredArgument):
        await ctx.send(f"{ctx.author.mention} Please specify an amount and user ID.")

@bot.command(name='clear', help='Clear the specified number of messages (Admin only).')
@commands.check(is_admin)
async def clear(ctx, amount: int):
    async with command_locks['clear']:
        await ctx.channel.purge(limit=amount + 1)  # +1 to include the clear command message
        confirmation_message = await ctx.send("Boss, evidence has been cleared!")
        await asyncio.sleep(3)
        await confirmation_message.delete()

@clear.error
async def clear_error(ctx, error):
    if isinstance(error, commands.MissingPermissions):
        await ctx.send(f"{ctx.author.mention} You do not have permission to use this command.")
    elif isinstance(error, commands.BadArgument):
        await ctx.send(f"{ctx.author.mention} Please enter a valid number of messages to clear.")
    elif isinstance(error, commands.MissingRequiredArgument):
        await ctx.send(f"{ctx.author.mention} Please specify the number of messages to clear.")

@bot.event
async def on_message(message):
    if isinstance(message.channel, discord.DMChannel) and not message.author.bot:
        guild = bot.guilds[0]  # Assuming the bot is only in one guild
        member = guild.get_member(message.author.id)
        if member and (message.author.id in ADMINS or any(role.id in ADMINS for role in member.roles)):
            channel = bot.get_channel(DM_FORWARD_CHANNEL_ID)
            if channel:
                await channel.send(f"**{member.display_name}**: {message.content}")
    await bot.process_commands(message)

bot.run(TOKEN)
