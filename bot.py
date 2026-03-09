import discord
import aiohttp
import asyncio
import os
from datetime import datetime, timezone

# ─── CONFIG ───────────────────────────────────────────────────────────────────
DISCORD_TOKEN = os.environ["DISCORD_TOKEN"]
HENRIK_API_KEY = os.environ["HENRIK_API_KEY"]
CHANNEL_ID = 1310677185169850452
CHECK_INTERVAL = 60

PLAYERS = [
    {"name": "zawn", "tag": "7627"},
    {"name": "miichaaa", "tag": "CACA"},
]

ASCENDANT_1_TIER = 21

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


def calculate_rr_to_ascendant(current_tier: int, rr_in_tier: int):
    if current_tier >= ASCENDANT_1_TIER:
        return None
    return (ASCENDANT_1_TIER - current_tier) * 100 - rr_in_tier


def get_stats(history: list):
    # Stats 20 dernières games
    last20 = history[:20]
    wins20 = sum(1 for m in last20 if m.get("last_change", 0) > 0)
    losses20 = sum(1 for m in last20 if m.get("last_change", 0) < 0)
    total20 = wins20 + losses20
    wr20 = int((wins20 / total20) * 100) if total20 > 0 else 0
    rr_net20 = sum(m.get("last_change", 0) for m in last20)

    # Stats du jour (UTC)
    today = datetime.now(timezone.utc).date()
    today_games = [
        m for m in history
        if datetime.fromisoformat(m.get("date", "").replace("Z", "+00:00")).date() == today
    ]
    wins_today = sum(1 for m in today_games if m.get("last_change", 0) > 0)
    losses_today = sum(1 for m in today_games if m.get("last_change", 0) < 0)
    total_today = wins_today + losses_today
    wr_today = int((wins_today / total_today) * 100) if total_today > 0 else 0
    rr_net_today = sum(m.get("last_change", 0) for m in today_games)

    # Streak actuel
    streak = 0
    if history:
        last_change = history[0].get("last_change", 0)
        is_win_streak = last_change > 0
        for m in history:
            if (is_win_streak and m.get("last_change", 0) > 0) or (not is_win_streak and m.get("last_change", 0) < 0):
                streak += 1
            else:
                break

    return {
        "wins20": wins20, "losses20": losses20, "wr20": wr20, "rr_net20": rr_net20,
        "wins_today": wins_today, "losses_today": losses_today, "wr_today": wr_today,
        "rr_net_today": rr_net_today, "streak": streak,
        "is_win_streak": history[0].get("last_change", 0) > 0 if history else True
    }


async def fetch_puuid(session: aiohttp.ClientSession, name: str, tag: str) -> str | None:
    url = f"https://api.henrikdev.xyz/valorant/v1/account/{name}/{tag}"
    async with session.get(url, headers={"Authorization": HENRIK_API_KEY}) as resp:
        if resp.status != 200:
            print(f"⚠️ fetch_puuid {name}#{tag} → {resp.status}")
            return None
        return (await resp.json()).get("data", {}).get("puuid")


async def fetch_history(session: aiohttp.ClientSession, name: str, tag: str, puuid: str) -> list:
    url = f"https://api.henrikdev.xyz/valorant/v2/by-puuid/mmr-history/eu/pc/{puuid}"
    async with session.get(url, headers={"Authorization": HENRIK_API_KEY}) as resp:
        if resp.status != 200:
            print(f"⚠️ fetch_history {name}#{tag} → {resp.status}")
            return []
        data = await resp.json()
        return data.get("data", {}).get("history", [])


def build_embed(match_data: dict, name: str, tag: str, history: list) -> discord.Embed:
    tier = match_data.get("tier", {})
    current_tier = tier.get("id", 0)
    tier_name = tier.get("name", "Unranked")
    rr_in_tier = match_data.get("rr", 0)
    rr_change = match_data.get("last_change", 0)
    map_name = match_data.get("map", {}).get("name", "?")

    rr_to_asc = calculate_rr_to_ascendant(current_tier, rr_in_tier)
    emoji = get_rank_emoji(tier_name)
    sign = "+" if rr_change > 0 else ""
    result = "✅ Victoire" if rr_change > 0 else "❌ Défaite" if rr_change < 0 else "🤝 Égalité"
    color = discord.Color.green() if rr_change > 0 else discord.Color.red() if rr_change < 0 else discord.Color.greyple()

    title = f"{emoji} {name}#{tag} — {'Ascendant+ atteint !' if rr_to_asc is None else 'Mise à jour du rang'}"
    embed = discord.Embed(title=title, color=color, timestamp=datetime.utcnow())

    embed.add_field(name="🎯 Rang actuel", value=f"**{tier_name}** — {rr_in_tier} RR", inline=True)
    embed.add_field(name="📊 Dernière partie", value=f"{result} ({sign}{rr_change} RR)\n🗺️ {map_name}", inline=True)

    if rr_to_asc is not None:
        total = (ASCENDANT_1_TIER - current_tier) * 100
        pct = max(0, min(100, int((1 - rr_to_asc / total) * 100)))
        bar = "🟩" * (pct // 10) + "⬛" * (10 - pct // 10)
        embed.add_field(name="🏆 Avant Ascendant", value=f"**{rr_to_asc} RR restants**\n{bar} {pct}%", inline=False)
    else:
        embed.add_field(name="🏆 Statut", value="Tu es déjà **Ascendant ou plus** ! GG 🎉", inline=False)

    if history:
        stats = get_stats(history)

        # Streak
        streak_emoji = "🔥" if stats["is_win_streak"] and stats["streak"] > 1 else "💀" if not stats["is_win_streak"] and stats["streak"] > 1 else ""
        streak_text = f"{streak_emoji} Streak : {stats['streak']}x {'victoires' if stats['is_win_streak'] else 'défaites'}" if stats["streak"] > 1 else ""

        # 20 dernières games
        rr_sign20 = "+" if stats["rr_net20"] > 0 else ""
        embed.add_field(
            name="📈 20 dernières games",
            value=f"✅ {stats['wins20']}V — ❌ {stats['losses20']}D — **{stats['wr20']}% WR**\nRR net : {rr_sign20}{stats['rr_net20']}" + (f"\n{streak_text}" if streak_text else ""),
            inline=True
        )

        # Stats du jour
       total_today = stats["wins_today"] + stats["losses_today"]
        if total_today > 0:
            rr_sign_today = "+" if stats["rr_net_today"] > 0 else ""
            embed.add_field(
                name="📅 Aujourd'hui",
                value=f"✅ {stats['wins_today']}V — ❌ {stats['losses_today']}D — **{stats['wr_today']}% WR**\nRR net : {rr_sign_today}{stats['rr_net_today']}",
                inline=True
            )

    embed.set_footer(text=f"Valorant Tracker • {name}#{tag}")
    return embed


async def monitor_player(session: aiohttp.ClientSession, player: dict, channel: discord.TextChannel):
    name = player["name"]
    tag = player["tag"]

    puuid = await fetch_puuid(session, name, tag)
    if not puuid:
        print(f"❌ PUUID introuvable pour {name}#{tag}")
        return

    history = await fetch_history(session, name, tag, puuid)
    last_match_id = history[0].get("match_id") if history else None
    print(f"📌 {name}#{tag} — Dernier match : {last_match_id}")

    while not client.is_closed():
        await asyncio.sleep(CHECK_INTERVAL)
        try:
            new_history = await fetch_history(session, name, tag, puuid)
            if not new_history:
                continue
            new_match_id = new_history[0].get("match_id")
            if new_match_id and new_match_id != last_match_id:
                print(f"🎮 Nouvelle partie pour {name}#{tag} !")
                last_match_id = new_match_id
                embed = build_embed(new_history[0], name, tag, new_history)
                msg = await channel.send(embed=embed)
                await asyncio.sleep(300)
                await msg.delete()
        except Exception as e:
            print(f"⚠️ Erreur {name}#{tag} : {e}")


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
