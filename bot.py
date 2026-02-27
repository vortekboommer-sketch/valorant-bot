import discord
import aiohttp
import asyncio
import os
from datetime import datetime

# ─── CONFIG ───────────────────────────────────────────────────────────────────
DISCORD_TOKEN = os.environ["DISCORD_TOKEN"]
HENRIK_API_KEY = os.environ["HENRIK_API_KEY"]
CHANNEL_ID = 1310677185169850452
CHECK_INTERVAL = 61  # secondes entre chaque vérification

PLAYERS = [
    {"name": "zawn", "tag": "7627"},
    {"name": "miichaaa", "tag": "CACA"},
]

ASCENDANT_1_TIER = 24

RANK_EMOJIS = {
    "Iron": "🩶", "Bronze": "🟤", "Silver": "⚪",
    "Gold": "🟡", "Platinum": "🩵", "Diamond": "💎",
    "Ascendant": "🟢", "Immortal": "🔴", "Radiant": "✨", "Unranked": "⬛"
}

intents = discord.Intents.default()
client = discord.Client(intents=intents)


def get_rank_emoji(tier_name: str) -> str:
    for rank, emoji in RANK_EMOJIS.items():
        if rank in tier_name:
            return emoji
    return "🎮"


def calculate_rr_to_ascendant(current_tier: int, rr_in_tier: int) -> int | None:
    if current_tier >= ASCENDANT_1_TIER:
        return None
    tiers_restants = ASCENDANT_1_TIER - current_tier
    return (tiers_restants * 100) - rr_in_tier


async def fetch_puuid(session: aiohttp.ClientSession, name: str, tag: str) -> str | None:
    url = f"https://api.henrikdev.xyz/valorant/v1/account/{name}/{tag}"
    headers = {"Authorization": HENRIK_API_KEY}
    async with session.get(url, headers=headers) as resp:
        if resp.status != 200:
            print(f"⚠️ fetch_puuid {name}#{tag} → status {resp.status}")
            return None
        data = await resp.json()
        return data.get("data", {}).get("puuid")


async def fetch_last_match_id(session: aiohttp.ClientSession, name: str, tag: str, puuid: str) -> str | None:
    url = f"https://api.henrikdev.xyz/valorant/v2/by-puuid/mmr-history/eu/pc/{puuid}"
    headers = {"Authorization": HENRIK_API_KEY}
    async with session.get(url, headers=headers) as resp:
        if resp.status != 200:
            print(f"⚠️ fetch_last_match_id {name}#{tag} → status {resp.status}")
            return None
        data = await resp.json()
        history = data.get("data", {}).get("history", [])
        if history:
            return history[0].get("match_id")
        return None


async def fetch_mmr(session: aiohttp.ClientSession, name: str, tag: str, puuid: str) -> dict | None:
    url = f"https://api.henrikdev.xyz/valorant/v2/by-puuid/mmr-history/eu/pc/{puuid}"
    headers = {"Authorization": HENRIK_API_KEY}
    async with session.get(url, headers=headers) as resp:
        if resp.status != 200:
            print(f"⚠️ fetch_mmr {name}#{tag} → status {resp.status}")
            return None
        data = await resp.json()
        history = data.get("data", {}).get("history", [])
        if history:
            return history[0]
        return None


def build_embed(match_data: dict, rr_change: int | None, name: str, tag: str) -> discord.Embed:
    tier = match_data.get("tier", {})
    current_tier = tier.get("id", 0)
    tier_name = tier.get("name", "Unranked")
    rr_in_tier = match_data.get("rr", 0)

    rr_to_asc = calculate_rr_to_ascendant(current_tier, rr_in_tier)
    emoji = get_rank_emoji(tier_name)
    map_name = match_data.get("map", {}).get("name", "?")

    if rr_to_asc is None:
        title = f"{emoji} {name}#{tag} — Ascendant+ atteint !"
        color = discord.Color.green()
    else:
        title = f"{emoji} {name}#{tag} — Mise à jour du rang"
        color = discord.Color.blurple()

    embed = discord.Embed(title=title, color=color, timestamp=datetime.utcnow())
    embed.add_field(name="🎯 Rang actuel", value=f"**{tier_name}** — {rr_in_tier} RR", inline=True)

    if rr_change is not None:
        sign = "+" if rr_change > 0 else ""
        result = "✅ Victoire" if rr_change > 0 else "❌ Défaite" if rr_change < 0 else "🤝 Égalité"
        embed.add_field(name="📊 Dernière partie", value=f"{result} ({sign}{rr_change} RR)\n🗺️ {map_name}", inline=True)

    if rr_to_asc is not None:
        total_rr_needed = (ASCENDANT_1_TIER - current_tier) * 100
        progress_pct = max(0, min(100, int((1 - rr_to_asc / total_rr_needed) * 100)))
        filled = progress_pct // 10
        bar = "🟩" * filled + "⬛" * (10 - filled)
        embed.add_field(
            name="🏆 Avant Ascendant",
            value=f"**{rr_to_asc} RR restants**\n{bar} {progress_pct}%",
            inline=False
        )
    else:
        embed.add_field(name="🏆 Statut", value="Tu es déjà **Ascendant ou plus** ! GG 🎉", inline=False)

    embed.set_footer(text=f"Valorant Tracker • {name}#{tag}")
    return embed


async def monitor_player(session: aiohttp.ClientSession, player: dict, channel: discord.TextChannel):
    name = player["name"]
    tag = player["tag"]

    puuid = await fetch_puuid(session, name, tag)
    if not puuid:
        print(f"❌ Impossible de récupérer le PUUID de {name}#{tag}")
        return

    last_match_id = await fetch_last_match_id(session, name, tag, puuid)
    last_match_data = await fetch_mmr(session, name, tag, puuid)
    print(f"📌 {name}#{tag} — Dernier match : {last_match_id}")

    while not client.is_closed():
        await asyncio.sleep(CHECK_INTERVAL)
        try:
            new_match_id = await fetch_last_match_id(session, name, tag, puuid)
            if new_match_id and new_match_id != last_match_id:
                print(f"🎮 Nouvelle partie détectée pour {name}#{tag} : {new_match_id}")
                last_match_id = new_match_id
                new_match_data = await fetch_mmr(session, name, tag, puuid)
                if new_match_data is None:
                    continue
                rr_change = new_match_data.get("last_change")
                last_match_data = new_match_data
                embed = build_embed(new_match_data, rr_change, name, tag)
                await channel.send(embed=embed)
        except Exception as e:
            print(f"⚠️ Erreur pour {name}#{tag} : {e}")


async def monitor_loop():
    await client.wait_until_ready()
    channel = client.get_channel(CHANNEL_ID)
    if channel is None:
        print(f"❌ Salon introuvable (ID: {CHANNEL_ID})")
        return
    print(f"✅ Bot démarré — surveillance de {len(PLAYERS)} joueurs")
    async with aiohttp.ClientSession() as session:
        tasks = [monitor_player(session, player, channel) for player in PLAYERS]
        await asyncio.gather(*tasks)


@client.event
async def on_ready():
    print(f"🤖 Connecté en tant que {client.user}")
    client.loop.create_task(monitor_loop())


client.run(DISCORD_TOKEN)
