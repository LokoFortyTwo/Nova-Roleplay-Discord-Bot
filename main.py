import os
import json
import asyncio
import aiohttp
import discord
from discord.ext import commands, tasks
from datetime import datetime
from typing import Dict, Optional


config_path = os.path.join(os.path.dirname(__file__), "config.json")
try:
    with open(config_path, "r", encoding="utf-8") as f:
        config = json.load(f)
except FileNotFoundError:
    print("config.json introuvable")
    raise SystemExit(1)

DISCORD_BOT_TOKEN = os.getenv("DISCORD_BOT_TOKEN")
RUN_BOT = os.getenv("RUN_BOT", "0") == "1"
DISABLE_BACKGROUND_TASKS = os.getenv("DISABLE_BACKGROUND_TASKS", "0") == "1"


class VoteView(discord.ui.View):
    def __init__(self, question: str, options: Dict[str, int]):
        super().__init__(timeout=None)
        self.question = question
        self.options = options
        self.voters: Dict[int, str] = {}
        for label in options.keys():
            self.add_item(VoteButton(label))

    def total_votes(self) -> int:
        return sum(self.options.values())

    def render_embed(self) -> discord.Embed:
        total = self.total_votes()
        embed = discord.Embed(
            title="Vote",
            description=self.question,
            color=int(config["colors"]["primary"], 16),
            timestamp=datetime.now(),
        )
        lines = []
        for label, count in self.options.items():
            pct = (count / total * 100.0) if total > 0 else 0.0
            lines.append(f"{label} : {count} ({pct:.0f}%)")
        embed.add_field(name="Resultats", value="\n".join(lines) if lines else "Aucun vote", inline=False)
        embed.set_footer(text=f"Total: {total}")
        return embed


class VoteButton(discord.ui.Button):
    def __init__(self, label: str):
        super().__init__(label=label, style=discord.ButtonStyle.secondary)

    async def callback(self, interaction: discord.Interaction):
        view: VoteView = self.view  # type: ignore
        if interaction.user is None:
            return

        uid = interaction.user.id
        choice = self.label

        prev = view.voters.get(uid)
        if prev == choice:
            await interaction.response.send_message("Tu as deja vote pour ce choix.", ephemeral=True)
            return

        if prev is not None:
            if prev in view.options and view.options[prev] > 0:
                view.options[prev] -= 1

        view.voters[uid] = choice
        view.options[choice] = view.options.get(choice, 0) + 1

        await interaction.response.edit_message(embed=view.render_embed(), view=view)


class NovaBot(commands.Bot):
    def __init__(self):
        intents = discord.Intents.default()
        intents.guilds = True
        super().__init__(
            command_prefix=config["bot_settings"]["prefix"],
            intents=intents,
            description=config["bot_settings"]["description"],
        )

        self.server_online = False
        self.player_count = 0
        self.max_players = 64

        self._fivem_host = config["server_info"]["fivem_ip"]
        self._fivem_base = f"http://{self._fivem_host}:30120"
        self.http: Optional[aiohttp.ClientSession] = None

    async def setup_hook(self):
        self.http = aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=6))
        await self.tree.sync()
        print(f"Commandes synchronisees pour {self.user}")

    async def close(self):
        try:
            if self.http and not self.http.closed:
                await self.http.close()
        finally:
            await super().close()

    async def on_ready(self):
        print(f"{self.user} connecte")
        if not DISABLE_BACKGROUND_TASKS and not self.update_status.is_running():
            self.update_status.start()
        await self.update_status_once()

    async def _get_json(self, path: str):
        if not self.http:
            raise RuntimeError("HTTP session not ready")
        url = f"{self._fivem_base}{path}"
        async with self.http.get(url) as r:
            r.raise_for_status()
            return await r.json()

    async def get_fivem_server_info(self):
        for path in ("/dynamic.json", "/info.json"):
            try:
                data = await self._get_json(path)
                return {
                    "online": True,
                    "players": int(data.get("clients", 0)),
                    "max_players": int(data.get("sv_maxclients", 64)),
                    "server_name": data.get("hostname", "Nova Roleplay"),
                }
            except Exception:
                pass

        try:
            data = await self._get_json("/players.json")
            if isinstance(data, list):
                return {
                    "online": True,
                    "players": len(data),
                    "max_players": 64,
                    "server_name": "Nova Roleplay",
                }
        except Exception:
            pass

        return {
            "online": False,
            "players": 0,
            "max_players": 64,
            "server_name": "Nova Roleplay",
        }

    @tasks.loop(minutes=2)
    async def update_status(self):
        await self.update_status_once()

    async def update_status_once(self):
        try:
            server_info = await self.get_fivem_server_info()
            self.server_online = server_info["online"]
            self.player_count = server_info["players"]
            self.max_players = server_info["max_players"]
        except Exception:
            self.server_online = False
            self.player_count = 0
            self.max_players = 64

        if self.server_online:
            status_text = f"{self.player_count}/{self.max_players} joueurs"
            await self.change_presence(
                status=discord.Status.online,
                activity=discord.Activity(type=discord.ActivityType.watching, name=status_text),
            )
        else:
            await self.change_presence(
                status=discord.Status.idle,
                activity=discord.Activity(type=discord.ActivityType.watching, name="Serveur hors ligne"),
            )


bot = NovaBot()


async def server_line() -> str:
    try:
        info = await bot.get_fivem_server_info()
        if info["online"]:
            return f"Joueurs en ligne: {info['players']}/{info['max_players']}"
        return "Serveur hors ligne"
    except Exception:
        return "Serveur hors ligne"


@bot.tree.command(name="f8", description="Connexion auto au serveur")
async def f8(interaction: discord.Interaction):
    fivem_ip = config["server_info"]["fivem_ip"]
    line = await server_line()
    embed = discord.Embed(
        title="Connexion F8",
        description=f"Ouvre FiveM, appuie sur F8, et tape:\n\nconnect {fivem_ip}\n\n{line}",
        color=int(config["colors"]["success"], 16),
        timestamp=datetime.now(),
    )
    await interaction.response.send_message(embed=embed)


@bot.tree.command(name="donation", description="Infos donation Nova Roleplay")
async def donation(interaction: discord.Interaction):
    line = await server_line()
    embed = discord.Embed(
        title="Donation",
        description=f"Virement Interac: {config['server_info']['donation_info']}\n\n{line}",
        color=int(config["colors"]["primary"], 16),
        timestamp=datetime.now(),
    )
    await interaction.response.send_message(embed=embed)


@bot.tree.command(name="vote", description="Creer un vote")
async def vote(
    interaction: discord.Interaction,
    question: str,
    choix1: str,
    choix2: str,
    choix3: str = "",
    choix4: str = "",
    choix5: str = "",
    choix6: str = "",
):
    opts = [choix1, choix2, choix3, choix4, choix5, choix6]
    labels = [o.strip() for o in opts if o and o.strip()]
    seen = set()
    clean = []
    for l in labels:
        if l.lower() in seen:
            continue
        seen.add(l.lower())
        clean.append(l)

    if len(clean) < 2:
        await interaction.response.send_message("Il faut au moins 2 choix.", ephemeral=True)
        return
    if len(clean) > 6:
        clean = clean[:6]

    options = {l: 0 for l in clean}
    view = VoteView(question=question, options=options)
    embed = view.render_embed()
    await interaction.response.send_message(embed=embed, view=view)


def main():
    if not DISCORD_BOT_TOKEN:
        print("Token Discord manquant")
        raise SystemExit(1)
    if not RUN_BOT:
        print("Bot desactive (RUN_BOT=0)")
        return
    bot.run(DISCORD_BOT_TOKEN)


if __name__ == "__main__":
    main()
