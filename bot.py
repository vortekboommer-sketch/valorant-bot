import discord
import aiohttp
import asyncio
import os
from datetime import datetime

# ─── CONFIG ───────────────────────────────────────────────────────────────────
DISCORD_TOKEN = "MTQ3NjY4Njg1ODQ1NjEzNzcyOA.GB7Tvi.YbM4XdAXvHZbSvkWeLtzjA8xXG2f_xGEtvO7VQ"
CHANNEL_ID = 1310677185169850452
RIOT_NAME = "zawn"
RIOT_TAG = "7627"
CHECK_INTERVAL = 60  # secondes entre chaque vérification

# Tiers Valorant (0-based index selon l'API Henrik)
# Ascendant 1 = tier 24
ASCENDANT_1_TIER = 24

TIER_NAMES = {
    0: "Unranked",
    3: "Iron 1", 4: "Iron 2", 5: "Iron 3",
    6: "Bronze 1", 7: "Bronze 2", 8: "Bronze 3",
    9: "Silver 1", 10: "Silver 2", 11: "Silver 3",
    12: "Gold 1", 13: "Gold 2", 14: "Gold 3",
    15: "Platinum 1", 16: "Platinum 2", 17: "Platinum 3",
    18: "Diamond 1", 19: "Diamond 2", 20: "Diamond 3",
    21: "Ascendant 1", 22: "Ascendant 2", 23: "Ascendant 3",
    24: "Immortal 1", 25: "Immortal 2", 26: "Immortal 3",
    27: "Radiant"
}

RANK_EMOJIS = {
    "Iron": "🩶", "Bronze": "🟤", "Silver": "⚪",
    "Gold": "🟡", "Platinum": "🩵", "Diamond": "💎",
    "Ascendant": "🟢", "Immortal": "🔴", "Radiant": "✨", "Unranked": "⬛"
}

# ─── BOT ──────────────────────────────────────────────────────────────────────
intents = discord.Intents.default()
client = discord.Client(intents=intents)

last_match_id = None
last_mmr_data = None


def get_rank_emoji(tier_name: str) -> str:
    for rank, emoji in RANK_EMOJIS.items():
        if rank in tier_name:
            return emoji
    return "🎮"


def calculate_rr_to_ascendant(current_tier: int, rr_in_tier: int) -> int | None:
    """Calcule les RR restants avant Ascendant 1. Retourne None si déjà Ascendant+."""
    if current_tier >= ASCENDANT_1_TIER:
        return None  # Déjà Ascendant ou plus
    tiers_restants = ASCENDANT_1_TIER - current_tier
    return (tiers_restants * 100) - rr_in_tier


async def fetch_mmr(session: aiohttp.ClientSession) -> dict | None:
    url = f"https://api.henrikdev.xyz/valorant/v3/mmr/eu/pc/{RIOT_NAME}/{RIOT_TAG}"
    async with session.get(url) as resp:
        if resp.status != 200:
            return None
        data = await resp.json()
        return data.get("data")


async def fetch_last_match_id(session: aiohttp.ClientSession) -> str | None:
    url = f"https://api.henrikdev.xyz/valorant/v1/mmr-history/eu/pc/{RIOT_NAME}/{RIOT_TAG}"
    async with session.get(url) as resp:
        if resp.status != 200:
            return None
        data = await resp.json()
        matches = data.get("data", [])
        if matches:
            return matches[0].get("match_id")
        return None


def build_embed(mmr_data: dict, rr_change: int | None) -> discord.Embed:
    current_tier = mmr_data.get("current", {}).get("tier", {}).get("id", 0)
    rr_in_tier = mmr_data.get("current", {}).get("rr", 0)
    tier_name = mmr_data.get("current", {}).get("tier", {}).get("name", "Unranked")
    peak = mmr_data.get("peak", {})

    rr_to_asc = calculate_rr_to_ascendant(current_tier, rr_in_tier)
    emoji = get_rank_emoji(tier_name)

    if rr_to_asc is None:
        title = f"{emoji} {RIOT_NAME}#{RIOT_TAG} — Ascendant+ atteint !"
        color = discord.Color.green()
    else:
        title = f"{emoji} {RIOT_NAME}#{RIOT_TAG} — Mise à jour du rang"
        color = discord.Color.blurple()

    embed = discord.Embed(title=title, color=color, timestamp=datetime.utcnow())
    embed.add_field(name="🎯 Rang actuel", value=f"**{tier_name}** — {rr_in_tier} RR", inline=True)

    if rr_change is not None:
        sign = "+" if rr_change > 0 else ""
        result = "✅ Victoire" if rr_change > 0 else "❌ Défaite" if rr_change < 0 else "🤝 Égalité"
        embed.add_field(name="📊 Dernière partie", value=f"{result} ({sign}{rr_change} RR)", inline=True)

    if rr_to_asc is not None:
        # Barre de progression
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

    embed.set_footer(text=f"Valorant Tracker • {RIOT_NAME}#{RIOT_TAG}")
    return embed


async def monitor_loop():
    global last_match_id, last_mmr_data

    await client.wait_until_ready()
    channel = client.get_channel(CHANNEL_ID)

    if channel is None:
        print(f"❌ Salon introuvable (ID: {CHANNEL_ID})")
        return

    print(f"✅ Bot démarré — surveillance de {RIOT_NAME}#{RIOT_TAG}")

    async with aiohttp.ClientSession() as session:
        # Init : récupère le dernier match connu sans envoyer de message
        last_match_id = await fetch_last_match_id(session)
        last_mmr_data = await fetch_mmr(session)
        print(f"📌 Dernier match connu : {last_match_id}")

        while not client.is_closed():
            await asyncio.sleep(CHECK_INTERVAL)
            try:
                new_match_id = await fetch_last_match_id(session)

                if new_match_id and new_match_id != last_match_id:
                    print(f"🎮 Nouvelle partie détectée : {new_match_id}")
                    last_match_id = new_match_id

                    new_mmr = await fetch_mmr(session)
                    if new_mmr is None:
                        continue

                    # Calcul du changement de RR
                    rr_change = None
                    if last_mmr_data:
                        old_rr = last_mmr_data.get("current", {}).get("rr", 0)
                        old_tier = last_mmr_data.get("current", {}).get("tier", {}).get("id", 0)
                        new_rr = new_mmr.get("current", {}).get("rr", 0)
                        new_tier = new_mmr.get("current", {}).get("tier", {}).get("id", 0)
                        tier_diff = (new_tier - old_tier) * 100
                        rr_change = (new_rr - old_rr) + tier_diff

                    last_mmr_data = new_mmr
                    embed = build_embed(new_mmr, rr_change)
                    await channel.send(embed=embed)

            except Exception as e:
                print(f"⚠️ Erreur dans la boucle : {e}")


@client.event
async def on_ready():
    print(f"🤖 Connecté en tant que {client.user}")
    client.loop.create_task(monitor_loop())


client.run(DISCORD_TOKEN)
