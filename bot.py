import discord
import aiohttp
import asyncio
import os
from datetime import datetime, timezone

DISCORD_TOKEN = os.environ["DISCORD_TOKEN"]
HENRIK_API_KEY = os.environ["HENRIK_API_KEY"]
CHANNEL_ID = 1310677185169850452
CHECK_INTERVAL = 60
DELETE_AFTER = 180  # secondes avant suppression du message

PLAYERS = [
    {"name": "pardon",   "tag": "7627", "goal": "ascendant"},
    {"name": "talvez",   "tag": "0610", "goal": "ascendant"},
    {"name": "Horuuuss", "tag": "EUWW", "goal": "diamond"},
]

ASCENDANT_1_TIER = 21
DIAMOND_1_TIER   = 18  # Diamond 1

RANK_EMOJIS = {
    "Iron": "🩶", "Bronze": "🟤", "Silver": "⚪",
    "Gold": "🟡", "Platinum": "🩵", "Diamond": "💎",
    "Ascendant": "🟢", "Immortal": "🔴", "Radiant": "✨", "Unranked": "⬛"
}

intents = discord.Intents.default()
client = discord.Client(intents=intents)

# Flag pour éviter le double lancement de monitor_loop
_monitor_started = False


def get_rank_emoji(tier_name):
    for rank, emoji in RANK_EMOJIS.items():
        if rank in tier_name:
            return emoji
    return "🎮"


def calculate_rr_to_goal(current_tier, rr_in_tier, goal):
    """Retourne (rr_restants, goal_tier, goal_label) selon l'objectif du joueur."""
    if goal == "diamond":
        target_tier  = DIAMOND_1_TIER
        target_label = "Diamond"
    else:
        target_tier  = ASCENDANT_1_TIER
        target_label = "Ascendant"

    if current_tier >= target_tier:
        return None, target_tier, target_label

    return (target_tier - current_tier) * 100 - rr_in_tier, target_tier, target_label


def get_stats(history):
    last20 = history[:20]
    wins20 = sum(1 for m in last20 if m.get("last_change", 0) > 0)
    losses20 = sum(1 for m in last20 if m.get("last_change", 0) < 0)
    total20 = wins20 + losses20
    wr20 = int((wins20 / total20) * 100) if total20 > 0 else 0
    rr_net20 = sum(m.get("last_change", 0) for m in last20)

    today = datetime.now(timezone.utc).date()
    today_games = []
    for m in history:
        try:
            d = datetime.fromisoformat(m.get("date", "").replace("Z", "+00:00")).date()
            if d == today:
                today_games.append(m)
        except Exception:
            pass

    wins_today = sum(1 for m in today_games if m.get("last_change", 0) > 0)
    losses_today = sum(1 for m in today_games if m.get("last_change", 0) < 0)
    total_today = wins_today + losses_today
    wr_today = int((wins_today / total_today) * 100) if total_today > 0 else 0
    rr_net_today = sum(m.get("last_change", 0) for m in today_games)

    streak = 0
    is_win_streak = history[0].get("last_change", 0) > 0 if history else True
    for m in history:
        change = m.get("last_change", 0)
        if (is_win_streak and change > 0) or (not is_win_streak and change < 0):
            streak += 1
        else:
            break

    return {
        "wins20": wins20, "losses20": losses20, "wr20": wr20, "rr_net20": rr_net20,
        "wins_today": wins_today, "losses_today": losses_today,
        "wr_today": wr_today, "rr_net_today": rr_net_today,
        "total_today": total_today, "streak": streak, "is_win_streak": is_win_streak
    }


async def fetch_puuid(session, name, tag):
    url = f"https://api.henrikdev.xyz/valorant/v1/account/{name}/{tag}"
    async with session.get(url, headers={"Authorization": HENRIK_API_KEY}) as resp:
        if resp.status != 200:
            print(f"⚠️ fetch_puuid {name}#{tag} → {resp.status}")
            return None
        return (await resp.json()).get("data", {}).get("puuid")


async def fetch_history(session, name, tag, puuid):
    url = f"https://api.henrikdev.xyz/valorant/v2/by-puuid/mmr-history/eu/pc/{puuid}"
    async with session.get(url, headers={"Authorization": HENRIK_API_KEY}) as resp:
        if resp.status != 200:
            print(f"⚠️ fetch_history {name}#{tag} → {resp.status}")
            return []
        data = await resp.json()
        return data.get("data", {}).get("history", [])


def build_embed(match_data, name, tag, history, goal="ascendant"):
    tier = match_data.get("tier", {})
    current_tier = tier.get("id", 0)
    tier_name = tier.get("name", "Unranked")
    rr_in_tier = match_data.get("rr", 0)
    rr_change = match_data.get("last_change", 0)
    map_name = match_data.get("map", {}).get("name", "?")

    rr_to_goal, target_tier, target_label = calculate_rr_to_goal(current_tier, rr_in_tier, goal)
    emoji = get_rank_emoji(tier_name)
    sign = "+" if rr_change > 0 else ""
    result = "✅ Victoire" if rr_change > 0 else "❌ Défaite" if rr_change < 0 else "🤝 Égalité"
    color = discord.Color.green() if rr_change > 0 else discord.Color.red() if rr_change < 0 else discord.Color.greyple()
    title = f"{emoji} {name}#{tag} — {f'{target_label}+ atteint !' if rr_to_goal is None else 'Mise à jour du rang'}"

    embed = discord.Embed(title=title, color=color, timestamp=datetime.utcnow())
    embed.add_field(name="🎯 Rang actuel", value=f"**{tier_name}** — {rr_in_tier} RR", inline=True)
    embed.add_field(name="📊 Dernière partie", value=f"{result} ({sign}{rr_change} RR)\n🗺️ {map_name}", inline=True)

    if rr_to_goal is not None:
        total = (target_tier - current_tier) * 100
        pct = max(0, min(100, int((1 - rr_to_goal / total) * 100)))
        bar = "🟩" * (pct // 10) + "⬛" * (10 - pct // 10)
        embed.add_field(name=f"🏆 Avant {target_label}", value=f"**{rr_to_goal} RR restants**\n{bar} {pct}%", inline=False)
    else:
        embed.add_field(name="🏆 Statut", value=f"Tu es déjà **{target_label} ou plus** ! GG 🎉", inline=False)

    if history:
        stats = get_stats(history)
        rr_sign20 = "+" if stats["rr_net20"] > 0 else ""
        streak_text = ""
        if stats["streak"] > 1:
            streak_emoji = "🔥" if stats["is_win_streak"] else "💀"
            streak_text = f"\n{streak_emoji} Streak : {stats['streak']}x {'victoires' if stats['is_win_streak'] else 'défaites'}"
        embed.add_field(
            name="📈 20 dernières games",
            value=f"✅ {stats['wins20']}V — ❌ {stats['losses20']}D — **{stats['wr20']}% WR**\nRR net : {rr_sign20}{stats['rr_net20']}{streak_text}",
            inline=True
        )
        if stats["total_today"] > 0:
            rr_sign_today = "+" if stats["rr_net_today"] > 0 else ""
            embed.add_field(
                name="📅 Aujourd'hui",
                value=f"✅ {stats['wins_today']}V — ❌ {stats['losses_today']}D — **{stats['wr_today']}% WR**\nRR net : {rr_sign_today}{stats['rr_net_today']}",
                inline=True
            )

    embed.set_footer(text=f"Valorant Tracker • {name}#{tag}")
    return embed


async def delete_after(msg, delay):
    await asyncio.sleep(delay)
    try:
        await msg.delete()
    except Exception as e:
        print(f"⚠️ Erreur suppression : {e}")


async def monitor_player(session, player, channel):
    name = player["name"]
    tag  = player["tag"]
    goal = player.get("goal", "ascendant")

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
                embed = build_embed(new_history[0], name, tag, new_history, goal)
                msg = await channel.send(embed=embed)
                asyncio.ensure_future(delete_after(msg, DELETE_AFTER))
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
    global _monitor_started
    print(f"🤖 Connecté en tant que {client.user}")
    # Empêche le double lancement si on_ready est appelé plusieurs fois
    if not _monitor_started:
        _monitor_started = True
        client.loop.create_task(monitor_loop())


client.run(DISCORD_TOKEN)
