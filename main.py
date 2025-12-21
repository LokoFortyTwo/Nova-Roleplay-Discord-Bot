#!/usr/bin/env python3
# ╔════════════════════════════════════════════════════╗
# ║               CJ DEV 2025 - NOVA ROLEPLAY BOT      ║
# ╚════════════════════════════════════════════════════╝

import discord
from discord.ext import commands, tasks
import json, os, requests, asyncio
from datetime import datetime
from typing import Optional
import random

try:
    import mysql.connector
    from mysql.connector import Error
    MYSQL_AVAILABLE = True
except ImportError:
    MYSQL_AVAILABLE = False
    Error = Exception

# ╔════════════════════════════════════════════════════╗
# ║                   CONFIGURATION                   ║
# ╚════════════════════════════════════════════════════╝
config_path = os.path.join(os.path.dirname(__file__), 'config.json')
try:
    with open(config_path, 'r', encoding='utf-8') as f:
        config = json.load(f)
except FileNotFoundError:
    print("❌ config.json introuvable")
    exit(1)

DISCORD_BOT_TOKEN = os.getenv("DISCORD_BOT_TOKEN")
MYSQL_HOST = os.getenv("MYSQL_HOST")
MYSQL_USER = os.getenv("MYSQL_USER")
MYSQL_PASSWORD = os.getenv("MYSQL_PASSWORD")
MYSQL_DATABASE = os.getenv("MYSQL_DATABASE")
MYSQL_PORT = int(os.getenv("MYSQL_PORT", "3306"))

ADMIN_ROLE_IDS = [
    1342882966686404628, 1342883276066652223, 1372313750224376008,
    1411835985666244688, 1370558513180311582, 1413711444096061510
]

RUN_BOT = os.getenv("RUN_BOT", "0") == "1"
DISABLE_BACKGROUND_TASKS = os.getenv("DISABLE_BACKGROUND_TASKS", "0") == "1"
DISABLE_MYSQL = os.getenv("DISABLE_MYSQL", "1") == "1"

# ╔════════════════════════════════════════════════════╗
# ║                    DATABASE MANAGER                ║
# ╚════════════════════════════════════════════════════╝
class DatabaseManager:
    def __init__(self):
        self.connection_params = {
            'host': MYSQL_HOST,
            'user': MYSQL_USER,
            'password': MYSQL_PASSWORD,
            'database': MYSQL_DATABASE,
            'port': MYSQL_PORT,
            'autocommit': True,
            'charset': 'utf8mb4'
        }

    async def initialize(self):
        if DISABLE_MYSQL or not MYSQL_AVAILABLE:
            return False
        try:
            if not all([MYSQL_HOST, MYSQL_USER, MYSQL_PASSWORD, MYSQL_DATABASE]):
                return False
            connection = mysql.connector.connect(**self.connection_params)
            if connection.is_connected():
                connection.close()
                return True
        except Error as e:
            print(f"⚠️ Erreur MySQL: {e}")
            return False
        return False

db_manager = DatabaseManager()

# ╔════════════════════════════════════════════════════╗
# ║                    NOVA ROLEPLAY BOT               ║
# ╚════════════════════════════════════════════════════╝
class NovaBot(commands.Bot):
    def __init__(self):
        intents = discord.Intents.default()
        intents.message_content = True
        intents.guilds = True
        intents.members = True
        super().__init__(
            command_prefix=config['bot_settings']['prefix'],
            intents=intents,
            description=config['bot_settings']['description']
        )
        self.server_online = False
        self.player_count = 0
        self.max_players = 64
        self.db_available = False
        self.last_f8_sent = None

    async def setup_hook(self):
        self.db_available = await db_manager.initialize()
        await self.tree.sync()
        print(f"✅ Commandes synchronisées pour {self.user}")

    async def on_ready(self):
        print(f"🚀 {self.user} connecté à Discord")
        if not DISABLE_BACKGROUND_TASKS:
            if not self.update_status.is_running():
                self.update_status.start()
            if not self.send_f8_auto.is_running():
                self.send_f8_auto.start()
        await self.update_status_once()

    @tasks.loop(minutes=5)
    async def update_status(self):
        await self.update_status_once()

    async def update_status_once(self):
        try:
            server_info = await self.get_fivem_server_info()
            self.server_online = server_info['online']
            self.player_count = server_info['players']
            self.max_players = server_info['max_players']

            if server_info['online']:
                status_text = f"🟢 {self.player_count}/{self.max_players} joueurs sur Nova Roleplay"
                await self.change_presence(
                    status=discord.Status.online,
                    activity=discord.Activity(type=discord.ActivityType.watching, name=status_text)
                )
            else:
                await self.change_presence(
                    status=discord.Status.idle,
                    activity=discord.Activity(type=discord.ActivityType.watching, name="🔴 Serveur hors ligne...")
                )
        except Exception as e:
            print(f"Erreur statut: {e}")
            self.server_online = False

    async def get_fivem_server_info(self):
        try:
            loop = asyncio.get_event_loop()
            response = await loop.run_in_executor(
                None,
                lambda: requests.get(f"http://{config['server_info']['fivem_ip']}:30120/info.json", timeout=5)
            )
            if response.status_code == 200:
                data = response.json()
                return {
                    'online': True,
                    'players': data.get('clients', 29),
                    'max_players': data.get('sv_maxclients', 128),
                    'server_name': data.get('hostname', 'Nova Roleplay')
                }
        except:
            pass
        return {'online': False, 'players': 0, 'max_players': 64, 'server_name': 'Nova Roleplay'}

    # ╔════════════════════════════════════════════════════╗
    # ║                     F8 AUTO                        ║
    # ╚════════════════════════════════════════════════════╝
    @tasks.loop(minutes=1)
    async def send_f8_auto(self):
        now = datetime.now()
        hour, minute = now.hour, now.minute
        valid_hours = list(range(0, 24, 2))  # Toutes les 2h : 0,2,4,...,22

        if hour in valid_hours and minute == 0:
            if self.last_f8_sent == hour:
                return
            channel_id = 1365802556957134858
            channel = self.get_channel(channel_id)
            if channel:
                fivem_ip = config['server_info']['fivem_ip']
                embed = discord.Embed(
                    title="Connexion F8 - Nova Roleplay",
                    description=f"Ouvre FiveM, appuie sur **F8**, et tape :\n\n`connect {fivem_ip}`",
                    color=int(config['colors']['success'], 16)
                )
                embed.set_footer(text=f"Depuis ton client FiveM • {now.strftime('%H:%M')}")
                await channel.send(embed=embed)
                self.last_f8_sent = hour
                print(f"✅ F8 envoyé à {now.strftime('%H:%M')}")

bot = NovaBot()

# ╔════════════════════════════════════════════════════╗
# ║                     COMMANDES                      ║
# ╚════════════════════════════════════════════════════╝

def has_admin_role(interaction: discord.Interaction) -> bool:
    return any(role.id in ADMIN_ROLE_IDS for role in getattr(interaction.user, 'roles', []))

@bot.tree.command(name="f8", description="Connexion auto au serveur")
async def f8(interaction: discord.Interaction):
    fivem_ip = config['server_info']['fivem_ip']
    embed = discord.Embed(
        title="Connexion F8 - Nova Roleplay",
        description=f"Ouvre FiveM, appuie sur **F8**, et tape :\n\n`connect {fivem_ip}`",
        color=int(config['colors']['success'], 16)
    )
    embed.set_footer(text="Depuis ton client FiveM")
    await interaction.response.send_message(embed=embed)

@bot.tree.command(name="donation", description="Infos donation Nova Roleplay")
async def donation(interaction: discord.Interaction):
    embed = discord.Embed(
        title="💵 Donation Nova Roleplay",
        description=f"Soutenez le serveur par virement Interac: `{config['server_info']['donation_info']}`",
        color=int(config['colors']['primary'], 16)
    )
    embed.timestamp = datetime.now()
    await interaction.response.send_message(embed=embed)

@bot.tree.command(name="annonce", description="[ADMIN] Envoyer une annonce")
async def annonce(interaction: discord.Interaction, titre: str, message: str):
    if not has_admin_role(interaction):
        await interaction.response.send_message("❌ Accès refusé", ephemeral=True)
        return
    embed = discord.Embed(title=f"📢 {titre}", description=message, color=int(config['colors']['primary'], 16))
    embed.timestamp = datetime.now()
    await interaction.response.send_message(embed=embed)

@bot.tree.command(name="clear", description="[ADMIN] Supprime un nombre de messages")
async def clear(interaction: discord.Interaction, nombre: int):
    if not has_admin_role(interaction):
        await interaction.response.send_message("❌ Accès refusé", ephemeral=True)
        return
    deleted = await interaction.channel.purge(limit=nombre)
    await interaction.response.send_message(f"🧹 {len(deleted)} messages supprimés.", ephemeral=True)

@bot.tree.command(name="restart", description="[ADMIN] Annonce un redémarrage serveur")
async def restart(interaction: discord.Interaction):
    if not has_admin_role(interaction):
        await interaction.response.send_message("❌ Accès refusé", ephemeral=True)
        return
    embed = discord.Embed(
        title="⚙️ Redémarrage en cours",
        description="Le serveur **Nova Roleplay** redémarre, revenez dans quelques minutes.",
        color=int(config['colors']['danger'], 16)
    )
    embed.timestamp = datetime.now()
    await interaction.response.send_message(embed=embed)

# ╔════════════════════════════════════════════════════╗
# ║                     MAIN                           ║
# ╚════════════════════════════════════════════════════╝
def main():
    if not DISCORD_BOT_TOKEN:
        print("❌ Token Discord manquant")
        exit(1)
    if not RUN_BOT:
        print("ℹ️ Bot désactivé (RUN_BOT=0)")
        return
    bot.run(DISCORD_BOT_TOKEN)

if __name__ == "__main__":
    main()
