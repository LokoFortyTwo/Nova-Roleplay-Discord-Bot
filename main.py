import os
import json
import asyncio
import requests
import discord
from discord.ext import commands, tasks
from datetime import datetime


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
    def __init__(self, question: str, options: list[str]):
        super().__init__(timeout=None)
        self.question = question
        self.options = {opt: 0 for opt in options}
        self.voters: dict[int, str] = {}
        for opt in options:
            self.add_item(VoteButton(opt))

    def _embed(self) -> discord.Embed:
        total = sum(self.options.values())
        embed = discord.Embed(
            title="Vote",
            description=self.question,
            color=int(config["colors"]["primary"], 16),
            timestamp=datetime.now(),
        )
        if total <= 0:
            embed.add_field(name="Resultats", value="Aucun vote", inline=False)
            return embed

        lines = []
        for k, v in self.options.items():
            pct = int((v / total) * 100) if total else 0
            lines.append(f"{k} : {v} ({pct}%)")
        embed.add_field(name="Resultats", value="\n".join(lines), inline=False)
        embed.set_footer(text=f"Total: {total}")
        return embed


class VoteButton(discord.ui.Button):
    def __init__(self, label: str):
        super().__init__(label=label, style=discord.ButtonStyle.secondary)

    async def callback(self, interaction: discord.Interaction):
        view: VoteView = self.view  # type: ignore
        uid = interaction.user.id

        choice = str(self.label)
        prev = view.voters.get(uid)

        if prev == choice:
            await interaction.response.send_message("Tu as deja vote pour ce choix.", ephemeral=True)
            return

        if prev is not None and prev in view.options and view.options[prev] > 0:
            view.options[prev] -= 1

        view.voters[uid] = choice
        view.options[choice] = view.options.get(choice, 0) + 1

        await interaction.response.edit_message(embed=view._embed(), view=view)


class NovaBot(commands.Bot):
    def __init__(self):
        intents = discord.Intents.default()
        intents.guilds = True
        intents.members = True

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

    async def setup_hook(self):
        await self.tree.sync()
        print(f"Commandes synchronisees pour {self.user}")

    async def on_ready(self):
        print(f"{self.user} connecte")
        await self.update_status_once()
        if not DISABLE_BACKGROUND_TASKS:
            if not self.update_status.is_running():
                self.update_status.start()

    def _fetch_json(self, url: str, timeout: int = 5):
        r = requests.get(url, timeout=timeout)
        r.raise_for_status()
        return r.json()

    async def _get_json(self, path: str, timeout: int = 5):
        loop = asyncio.get_event_loop()
        url = f"{self._fivem_base}{path}"
        return await loop.run_in_executor(None, lambda: self._fetch_json(url, timeout=timeout))

    async def get_fivem_server_info(self):
        for path in ("/dynamic.json", "/info.json"):
            try:
                data = await self._get_json(path, timeout=5)
                return {
                    "online": True,
                    "players": int(data.get("clients", 0)),
                    "max_players": int(data.get("sv_maxclients", 64)),
                    "server_name": data.get("hostname", "Nova Roleplay"),
                }
            except Exception:
                pass

        try:
            data = await self._get_json("/players.json", timeout=5)
            if isinstance(data, list):
                return {
                    "online": True,
                    "players": len(data),
                    "max_players": 64,
                    "server_name": "Nova Roleplay",
                }
        except Exception:
            pass

        return {"online": False, "players": 0, "max_players": 64, "server_name": "Nova Roleplay"}

    @tasks.loop(minutes=2)
    async def update_status(self):
        await self.update_status_once()

    async def update_status_once(self):
        try:
            info = await self.get_fivem_server_info()
            self.server_online = info["online"]
            self.player_count = info["players"]
            self.max_players = info["max_players"]
        except Exception:
            self.server_online = False
            self.player_count = 0
            self.max_players = 64

        if self.server_online:
            name = f"{self.player_count}/{self.max_players} joueurs"
            await self.change_presence(
                status=discord.Status.online,
                activity=discord.Activity(type=discord.ActivityType.watching, name=name),
            )
        else:
            await self.change_presence(
                status=discord.Status.idle,
                activity=discord.Activity(type=discord.ActivityType.watching, name="Serveur hors ligne"),
            )

    async def server_line(self) -> str:
        try:
            info = await self.get_fivem_server_info()
            if info["online"]:
                return f"Joueurs en ligne: {info['players']}/{info['max_players']}"
            return "Serveur hors ligne"
        except Exception:
            return "Serveur hors ligne"


bot = NovaBot()


@bot.tree.command(name="f8", description="Connexion auto au serveur")
async def f8(interaction: discord.Interaction):
    fivem_ip = config["server_info"]["fivem_ip"]
    line = await bot.server_line()
    embed = discord.Embed(
        title="Connexion F8",
        description=f"Ouvre FiveM, appuie sur F8, et tape:\n\nconnect {fivem_ip}\n\n{line}",
        color=int(config["colors"]["success"], 16),
        timestamp=datetime.now(),
    )
    await interaction.response.send_message(embed=embed)


@bot.tree.command(name="donation", description="Infos donation Nova Roleplay")
async def donation(interaction: discord.Interaction):
    line = await bot.server_line()
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
    raw = [choix1, choix2, choix3, choix4, choix5, choix6]
    opts = []
    seen = set()
    for x in raw:
        x = (x or "").strip()
        if not x:
            continue
        k = x.lower()
        if k in seen:
            continue
        seen.add(k)
        opts.append(x)

    if len(opts) < 2:
        await interaction.response.send_message("Il faut au moins 2 choix.", ephemeral=True)
        return

    if len(opts) > 6:
        opts = opts[:6]

    view = VoteView(question, opts)
    await interaction.response.send_message(embed=view._embed(), view=view)


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
