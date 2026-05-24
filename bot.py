from __future__ import annotations

import asyncio
import logging
import os
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from logging.handlers import RotatingFileHandler
from pathlib import Path

import discord
from discord import app_commands
from discord.ext import commands
from dotenv import load_dotenv
from mcrcon import MCRcon

from storage import VerificationStore


USERNAME_RE = re.compile(r"^[A-Za-z0-9_]{3,16}$")
ROOT = Path(__file__).resolve().parent
DATA_DIR = ROOT / "data"
LOG_DIR = ROOT / "logs"


@dataclass(frozen=True)
class Settings:
    discord_token: str
    discord_guild_id: int | None
    verify_channel_id: int | None
    allow_dm_verify: bool
    approval_channel_id: int | None
    verified_role_id: int | None
    require_admin_approval: bool
    rcon_host: str
    rcon_port: int
    rcon_password: str
    minecraft_server_ip: str
    minecraft_server_port: int
    announce_in_minecraft: bool


def env_bool(name: str, default: bool = False) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "y", "on"}


def env_int(name: str) -> int | None:
    value = os.getenv(name)
    if not value:
        return None
    return int(value)


def load_settings() -> Settings:
    load_dotenv()
    token = os.getenv("DISCORD_TOKEN", "").strip()
    rcon_password = os.getenv("RCON_PASSWORD", "").strip()
    if not token:
        raise RuntimeError("DISCORD_TOKEN is required in .env")
    if not rcon_password:
        raise RuntimeError("RCON_PASSWORD is required in .env")

    return Settings(
        discord_token=token,
        discord_guild_id=env_int("DISCORD_GUILD_ID"),
        verify_channel_id=env_int("VERIFY_CHANNEL_ID"),
        allow_dm_verify=env_bool("ALLOW_DM_VERIFY", True),
        approval_channel_id=env_int("APPROVAL_CHANNEL_ID"),
        verified_role_id=env_int("VERIFIED_ROLE_ID"),
        require_admin_approval=env_bool("REQUIRE_ADMIN_APPROVAL", False),
        rcon_host=os.getenv("RCON_HOST", "127.0.0.1").strip(),
        rcon_port=int(os.getenv("RCON_PORT", "25575")),
        rcon_password=rcon_password,
        minecraft_server_ip=os.getenv("MINECRAFT_SERVER_IP", "서버주소미설정").strip(),
        minecraft_server_port=int(os.getenv("MINECRAFT_SERVER_PORT", "25565")),
        announce_in_minecraft=env_bool("ANNOUNCE_IN_MINECRAFT", False),
    )


def setup_logging() -> None:
    LOG_DIR.mkdir(exist_ok=True)
    handler = RotatingFileHandler(
        LOG_DIR / "bot.log",
        maxBytes=2_000_000,
        backupCount=5,
        encoding="utf-8",
    )
    formatter = logging.Formatter(
        "[%(asctime)s] %(levelname)s %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    handler.setFormatter(formatter)
    console = logging.StreamHandler()
    console.setFormatter(formatter)
    logging.basicConfig(level=logging.INFO, handlers=[handler, console])


def is_valid_username(username: str) -> bool:
    return USERNAME_RE.fullmatch(username) is not None


def parse_dm_username(content: str) -> str | None:
    text = content.strip()
    if not text:
        return None
    lowered = text.lower()
    if lowered in {"help", "도움말", "인증", "/verify", "!verify"}:
        return None
    for prefix in ("/verify ", "!verify ", "verify "):
        if lowered.startswith(prefix):
            text = text[len(prefix) :].strip()
            break
    if " " in text or "\n" in text:
        return None
    return text


class WhitelistBot(commands.Bot):
    def __init__(self, settings: Settings, store: VerificationStore):
        intents = discord.Intents.default()
        intents.guilds = True
        intents.members = settings.verified_role_id is not None
        intents.message_content = settings.allow_dm_verify
        super().__init__(command_prefix="!", intents=intents)
        self.settings = settings
        self.store = store
        self.log = logging.getLogger("whitelist-bot")

    async def setup_hook(self) -> None:
        self.add_view(ApprovalView(self))
        guild = discord.Object(id=self.settings.discord_guild_id) if self.settings.discord_guild_id else None
        if guild:
            self.tree.copy_global_to(guild=guild)
            try:
                await self.tree.sync(guild=guild)
                self.log.info("Synced slash commands to guild_id=%s", self.settings.discord_guild_id)
            except discord.Forbidden:
                self.log.warning(
                    "Could not sync guild slash commands for guild_id=%s. "
                    "Check DISCORD_GUILD_ID and invite the bot with the applications.commands scope. "
                    "DM verification can still work if ALLOW_DM_VERIFY=true.",
                    self.settings.discord_guild_id,
                )
            if self.settings.allow_dm_verify:
                await self.tree.sync()
                self.log.info("Synced global slash commands for DM usage")
        else:
            await self.tree.sync()
            self.log.info("Synced global slash commands")

    async def on_ready(self) -> None:
        self.log.info("Logged in as %s (%s)", self.user, self.user.id if self.user else "unknown")

    async def on_message(self, message: discord.Message) -> None:
        if message.author.bot:
            return
        if not isinstance(message.channel, discord.DMChannel):
            await self.process_commands(message)
            return
        if not self.settings.allow_dm_verify:
            await message.channel.send("현재 DM 인증은 비활성화되어 있습니다. Discord 서버의 인증 채널을 사용해주세요.")
            return

        username = parse_dm_username(message.content)
        if not username:
            await message.channel.send(
                "Minecraft Java 닉네임만 보내주세요.\n"
                "예시: `Steve` 또는 `/verify Steve`\n"
                "닉네임은 3~16자의 영문, 숫자, 언더스코어만 가능합니다."
            )
            return

        ok, response = await submit_verification(self, discord_user=message.author, username=username)
        await message.channel.send(response)
        if not ok:
            self.log.info("DM_VERIFY_REJECTED discord_id=%s minecraft=%s response=%s", message.author.id, username, response)

    async def run_rcon(self, command: str) -> str:
        def execute() -> str:
            with MCRcon(self.settings.rcon_host, self.settings.rcon_password, port=self.settings.rcon_port) as rcon:
                return rcon.command(command)

        return await asyncio.to_thread(execute)

    async def add_to_whitelist(self, username: str) -> str:
        response = await self.run_rcon(f"whitelist add {username}")
        if self.settings.announce_in_minecraft:
            await self.run_rcon(f"say {username} 님이 whitelist에 등록되었습니다.")
        return response

    async def remove_from_whitelist(self, username: str) -> str:
        return await self.run_rcon(f"whitelist remove {username}")

    async def assign_verified_role(self, member: discord.Member) -> None:
        if not self.settings.verified_role_id:
            return
        role = member.guild.get_role(self.settings.verified_role_id)
        if not role:
            self.log.warning("Verified role id=%s not found", self.settings.verified_role_id)
            return
        await member.add_roles(role, reason="Minecraft whitelist verification completed")


async def require_verify_channel(interaction: discord.Interaction, settings: Settings) -> bool:
    if interaction.guild is None:
        if settings.allow_dm_verify:
            return True
        await interaction.response.send_message("현재 DM 인증은 비활성화되어 있습니다. Discord 서버의 인증 채널을 사용해주세요.")
        return False
    if not settings.verify_channel_id:
        return True
    if interaction.channel_id == settings.verify_channel_id:
        return True
    await interaction.response.send_message("이 명령어는 지정된 인증 채널에서만 사용할 수 있습니다.", ephemeral=True)
    return False


async def complete_verification(
    bot: WhitelistBot,
    *,
    discord_user: discord.User | discord.Member,
    guild: discord.Guild | None,
    username: str,
    approved_by: discord.User | discord.Member | None = None,
) -> tuple[bool, str]:
    existing_user = bot.store.get_by_discord_id(str(discord_user.id))
    if existing_user:
        return False, f"이미 Minecraft 닉네임 `{existing_user['minecraft_name']}`로 등록되어 있습니다."

    existing_name = bot.store.get_by_minecraft_name(username)
    if existing_name:
        return False, f"Minecraft 닉네임 `{username}`은 이미 다른 Discord 계정으로 등록되어 있습니다."

    try:
        rcon_response = await bot.add_to_whitelist(username)
    except Exception:
        bot.log.exception("RCON whitelist add failed discord_id=%s minecraft=%s", discord_user.id, username)
        return False, "Minecraft 서버와 연결할 수 없습니다. 잠시 후 다시 시도하거나 운영진에게 문의하세요."

    target_guild = guild
    if target_guild is None and bot.settings.discord_guild_id:
        target_guild = bot.get_guild(bot.settings.discord_guild_id)
    member = target_guild.get_member(discord_user.id) if target_guild else None
    if member:
        try:
            await bot.assign_verified_role(member)
        except discord.Forbidden:
            bot.log.warning("Missing permission to assign verified role discord_id=%s", discord_user.id)
        except Exception:
            bot.log.exception("Failed to assign verified role discord_id=%s", discord_user.id)

    bot.store.add_verified_user(
        discord_id=str(discord_user.id),
        discord_name=str(discord_user),
        minecraft_name=username,
        verified_at=datetime.now(timezone.utc).isoformat(),
        approved_by=str(approved_by.id) if approved_by else None,
        rcon_response=rcon_response,
    )
    bot.log.info(
        "WHITELIST_ADD_SUCCESS discord_id=%s minecraft=%s approved_by=%s response=%s",
        discord_user.id,
        username,
        approved_by.id if approved_by else "auto",
        rcon_response,
    )
    return True, (
        f"등록 완료: Minecraft 닉네임 `{username}`가 whitelist에 추가되었습니다.\n"
        f"서버 주소: `{bot.settings.minecraft_server_ip}:{bot.settings.minecraft_server_port}`"
    )


async def submit_verification(
    bot: WhitelistBot,
    *,
    discord_user: discord.User | discord.Member,
    username: str,
    guild: discord.Guild | None = None,
) -> tuple[bool, str]:
    username = username.strip()
    if not is_valid_username(username):
        return False, "닉네임 형식이 올바르지 않습니다. Minecraft Java 닉네임은 3~16자의 영문, 숫자, 언더스코어만 사용할 수 있습니다."

    existing_user = bot.store.get_by_discord_id(str(discord_user.id))
    if existing_user:
        return False, f"이미 Minecraft 닉네임 `{existing_user['minecraft_name']}`로 등록되어 있습니다. 변경이 필요하면 운영진에게 문의하세요."

    existing_name = bot.store.get_by_minecraft_name(username)
    if existing_name:
        return False, f"Minecraft 닉네임 `{username}`은 이미 등록되어 있습니다. 오타가 아니라면 운영진에게 문의하세요."

    bot.log.info("VERIFY_REQUEST discord_id=%s discord_name=%s minecraft=%s", discord_user.id, discord_user, username)

    if bot.settings.require_admin_approval:
        if not bot.settings.approval_channel_id:
            return False, "운영진 승인 채널이 설정되지 않았습니다. 운영진에게 문의하세요."
        request_id = bot.store.create_pending_request(
            discord_id=str(discord_user.id),
            discord_name=str(discord_user),
            minecraft_name=username,
            requested_at=datetime.now(timezone.utc).isoformat(),
        )
        approval_channel = bot.get_channel(bot.settings.approval_channel_id)
        if approval_channel is None:
            try:
                approval_channel = await bot.fetch_channel(bot.settings.approval_channel_id)
            except discord.DiscordException:
                approval_channel = None
        if not isinstance(approval_channel, discord.TextChannel):
            return False, "운영진 승인 채널을 찾을 수 없습니다. 운영진에게 문의하세요."
        embed = discord.Embed(title="Minecraft whitelist 승인 요청", color=discord.Color.blurple())
        embed.add_field(name="Discord 사용자", value=f"<@{discord_user.id}> (`{discord_user.id}`)", inline=False)
        embed.add_field(name="Minecraft 닉네임", value=f"`{username}`", inline=False)
        embed.set_footer(text=f"request_id={request_id}")
        await approval_channel.send(embed=embed, view=ApprovalView(bot))
        return True, "등록 요청이 운영진에게 전달되었습니다. 승인되면 DM으로 안내됩니다."

    return await complete_verification(bot, discord_user=discord_user, guild=guild, username=username)


class ApprovalView(discord.ui.View):
    def __init__(self, bot: WhitelistBot):
        super().__init__(timeout=None)
        self.bot = bot

    @discord.ui.button(
        label="승인",
        style=discord.ButtonStyle.success,
        custom_id="whitelist_approval:approve",
    )
    async def approve(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        if not interaction.user.guild_permissions.manage_guild:
            await interaction.response.send_message("관리자 권한이 필요한 작업입니다.", ephemeral=True)
            return
        request_id = _message_request_id(interaction.message)
        if not request_id:
            await interaction.response.send_message("승인 요청 정보를 찾을 수 없습니다.", ephemeral=True)
            return
        request = self.bot.store.get_pending_request(request_id)
        if not request:
            await interaction.response.send_message("이미 처리되었거나 만료된 요청입니다.", ephemeral=True)
            return
        user = await self.bot.fetch_user(int(request["discord_id"]))
        ok, message = await complete_verification(
            self.bot,
            discord_user=user,
            guild=interaction.guild,
            username=request["minecraft_name"],
            approved_by=interaction.user,
        )
        self.bot.store.mark_request_decided(request_id, "approved" if ok else "failed", str(interaction.user.id))
        await interaction.response.edit_message(content=f"{message}\n처리자: {interaction.user.mention}", view=None)
        try:
            await user.send(message)
        except discord.Forbidden:
            pass

    @discord.ui.button(
        label="거절",
        style=discord.ButtonStyle.danger,
        custom_id="whitelist_approval:reject",
    )
    async def reject(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        if not interaction.user.guild_permissions.manage_guild:
            await interaction.response.send_message("관리자 권한이 필요한 작업입니다.", ephemeral=True)
            return
        request_id = _message_request_id(interaction.message)
        if not request_id:
            await interaction.response.send_message("승인 요청 정보를 찾을 수 없습니다.", ephemeral=True)
            return
        request = self.bot.store.get_pending_request(request_id)
        if not request:
            await interaction.response.send_message("이미 처리되었거나 만료된 요청입니다.", ephemeral=True)
            return
        self.bot.store.mark_request_decided(request_id, "rejected", str(interaction.user.id))
        user = await self.bot.fetch_user(int(request["discord_id"]))
        message = f"`{request['minecraft_name']}` whitelist 등록 요청이 운영진에 의해 거절되었습니다."
        await interaction.response.edit_message(content=f"{message}\n처리자: {interaction.user.mention}", view=None)
        try:
            await user.send(message)
        except discord.Forbidden:
            pass


def _message_request_id(message: discord.Message | None) -> int | None:
    if not message or not message.embeds:
        return None
    footer = message.embeds[0].footer.text or ""
    if not footer.startswith("request_id="):
        return None
    return int(footer.removeprefix("request_id="))


settings = load_settings()
setup_logging()
DATA_DIR.mkdir(exist_ok=True)
store = VerificationStore(DATA_DIR / "verified_users.db")
bot = WhitelistBot(settings, store)


@bot.tree.command(name="verify", description="Minecraft 닉네임을 whitelist에 등록합니다.")
@app_commands.describe(username="Minecraft Java Edition 닉네임")
async def verify(interaction: discord.Interaction, username: str) -> None:
    username = username.strip()
    if not await require_verify_channel(interaction, bot.settings):
        return
    ephemeral = interaction.guild is not None
    await interaction.response.defer(ephemeral=ephemeral)
    ok, message = await submit_verification(bot, discord_user=interaction.user, guild=interaction.guild, username=username)
    await interaction.followup.send(message, ephemeral=ephemeral and not ok)


def admin_only() -> app_commands.check:
    async def predicate(interaction: discord.Interaction) -> bool:
        permissions = getattr(interaction.user, "guild_permissions", None)
        if permissions and permissions.manage_guild:
            return True
        await interaction.response.send_message("관리자 권한이 필요한 명령어입니다.", ephemeral=True)
        return False

    return app_commands.check(predicate)


@bot.tree.command(name="whitelist-add", description="관리자가 Minecraft 닉네임을 whitelist에 직접 추가합니다.")
@app_commands.describe(username="Minecraft Java Edition 닉네임")
@admin_only()
async def whitelist_add(interaction: discord.Interaction, username: str) -> None:
    username = username.strip()
    if not is_valid_username(username):
        await interaction.response.send_message("닉네임 형식이 올바르지 않습니다.", ephemeral=True)
        return
    await interaction.response.defer(ephemeral=True)
    try:
        response = await bot.add_to_whitelist(username)
    except Exception:
        bot.log.exception("Admin whitelist add failed minecraft=%s", username)
        await interaction.followup.send("Minecraft 서버와 연결할 수 없습니다.", ephemeral=True)
        return
    await interaction.followup.send(f"`{username}` 추가 완료\nRCON 응답: `{response}`", ephemeral=True)


@bot.tree.command(name="whitelist-remove", description="관리자가 Minecraft 닉네임을 whitelist에서 제거합니다.")
@app_commands.describe(username="Minecraft Java Edition 닉네임")
@admin_only()
async def whitelist_remove(interaction: discord.Interaction, username: str) -> None:
    username = username.strip()
    if not is_valid_username(username):
        await interaction.response.send_message("닉네임 형식이 올바르지 않습니다.", ephemeral=True)
        return
    await interaction.response.defer(ephemeral=True)
    try:
        response = await bot.remove_from_whitelist(username)
    except Exception:
        bot.log.exception("Admin whitelist remove failed minecraft=%s", username)
        await interaction.followup.send("Minecraft 서버와 연결할 수 없습니다.", ephemeral=True)
        return
    bot.store.remove_by_minecraft_name(username)
    await interaction.followup.send(f"`{username}` 제거 완료\nRCON 응답: `{response}`", ephemeral=True)


@bot.tree.command(name="whitelist-check", description="등록된 Discord/Minecraft 매핑을 확인합니다.")
@app_commands.describe(username="Minecraft Java Edition 닉네임")
@admin_only()
async def whitelist_check(interaction: discord.Interaction, username: str) -> None:
    record = bot.store.get_by_minecraft_name(username.strip())
    if not record:
        await interaction.response.send_message("봇 DB에 등록된 기록이 없습니다.", ephemeral=True)
        return
    await interaction.response.send_message(
        f"Minecraft: `{record['minecraft_name']}`\nDiscord: `{record['discord_name']}` (`{record['discord_id']}`)\n등록일: `{record['verified_at']}`",
        ephemeral=True,
    )


@bot.tree.command(name="whitelist-list", description="최근 등록된 whitelist 사용자 목록을 봅니다.")
@admin_only()
async def whitelist_list(interaction: discord.Interaction) -> None:
    rows = bot.store.list_verified_users(limit=20)
    if not rows:
        await interaction.response.send_message("등록된 사용자가 없습니다.", ephemeral=True)
        return
    lines = [f"- `{row['minecraft_name']}` / {row['discord_name']} / {row['verified_at']}" for row in rows]
    await interaction.response.send_message("\n".join(lines), ephemeral=True)


if __name__ == "__main__":
    bot.run(settings.discord_token)