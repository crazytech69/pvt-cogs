"""
MIT License

Copyright (c) 2022-present japandotorg

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
"""

import datetime
import logging
from io import BytesIO
from typing import Any, Dict, Final, List, Literal, Optional, Type, TypeVar

import discord
from redbot.core import Config, checks, commands, modlog
from redbot.core.bot import Red
from redbot.core.utils.chat_formatting import box, humanize_list, inline, pagify

from .utils import auth_check, get_user_confirmation

RequestType = Literal["discord_deleted_user", "owner", "user", "user_strict"]

RTT = TypeVar("RTT", bound="RequestType")

log = logging.getLogger("red.seina-cogs.globalban")


class GlobalBan(commands.Cog):
    """
    Global Ban a user across multiple servers.
    """

    __author__: List[str] = ["inthedark.org#0666"]
    __version__: Final[str] = "0.1.2"

    def __init__(self, bot: Red, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.bot: Red = bot

        self.config: Config = Config.get_conf(self, identifier=66642069)
        self.config.register_global(banned={}, opted=[])
        self.config.register_guild(banlist=[])

        if gadmin := bot.get_cog("GlobalAdmin"):
            gadmin.register_perm("globalban")

    async def cog_load(self) -> None:
        await self.bot.wait_until_red_ready()

    def format_help_for_context(self, ctx: commands.Context) -> str:
        pre_processed = super().format_help_for_context(ctx) or ""
        n = "\n" if "\n\n" not in pre_processed else ""
        text: List[str] = [
            f"{pre_processed}{n}",
            f"Cog Version: **{self.__version__}**",
            f"Author: {humanize_list(self.__author__)}",
        ]
        return "\n".join(text)

    async def red_get_data_for_user(self, *, user_id: int) -> Dict[str, BytesIO]:
        """
        Get a user's personal data.
        """
        data = f"No data is stored for user with ID {user_id}.\n"
        return {"user_data.txt": BytesIO(data.encode())}

    async def red_delete_data_for_user(
        self, *, requester: Type[RTT], user_id: int
    ) -> Dict[str, BytesIO]:
        """
        Delete a user's personal data.

        No personal data is stored in this cog.
        """
        data = f"No data is stored for user with ID {user_id}.\n"
        return {"user_data.txt": BytesIO(data.encode())}

    @commands.group(aliases=["gb", "gban"], invoke_without_command=True)
    async def globalban(self, ctx: commands.Context) -> None:
        """
        Global ban related commands.
        """
        if ctx.invoked_subcommand is None:
            return await ctx.send_help()

    @globalban.command()
    @checks.admin_or_permissions(administrator=True)
    async def optin(self, ctx: commands.Context) -> None:
        """
        Opt your server in to the Global Ban system.
        """
        async with self.config.opted() as opted:
            if ctx.guild.id in opted:
                await ctx.send("This guild is already opted in.")
                return
            if not await get_user_confirmation(
                ctx,
                "This will ban all users on the global ban list. Are you sure you want to opt in?",
            ):
                return
            opted.append(ctx.guild.id)
        ban_entries = [entry async for entry in ctx.guild.bans()]
        await self.config.guild(ctx.guild).banlist.set([be.user.id for be in ban_entries])
        async with ctx.typing():
            await self.update_gbs(ctx)
        await ctx.tick()

    @globalban.command()
    @checks.admin_or_permissions(administrator=True)
    async def optout(self, ctx: commands.Context) -> None:
        """
        Opt your server out of the Global Ban system.
        """
        async with self.config.opted() as opted:
            if ctx.guild.id not in opted:
                await ctx.send("This guild is already opted out.")
                return
            if not await get_user_confirmation(
                ctx,
                "This will remove all bans that intersect"
                " with the global ban list. Are you sure"
                " you want to opt out?",
            ):
                return
            opted.remove(ctx.guild.id)
        async with ctx.typing():
            await self.remove_gbs_guild(ctx.guild.id)
        await ctx.tick()

    @globalban.command()
    @auth_check("globalban")
    async def ban(
        self, ctx: commands.Context, user_id: int, *, reason: Optional[str] = ""
    ) -> None:
        """
        Globally Ban a user across all opted-in servers.
        """
        async with self.config.banned() as banned:
            banned[str(user_id)] = reason
        async with ctx.typing():
            await self.update_gbs(ctx)
        await ctx.tick()

    @globalban.command()
    @auth_check("globalban")
    async def editreason(
        self, ctx: commands.Context, user_id: int, *, reason: Optional[str] = ""
    ) -> None:
        """Edit a user's ban reason."""
        async with self.config.banned() as banned:
            if str(user_id) not in banned:
                await ctx.send("This user is not banned.")
                return
            if reason == "" and not await get_user_confirmation(
                ctx, "Are you sure you want to remove the reason?"
            ):
                return
            banned[str(user_id)] = reason
        await ctx.tick()

    @globalban.command()
    @auth_check("globalban")
    @checks.bot_has_permissions(ban_members=True)
    async def unban(self, ctx: commands.Context, user_id: int) -> None:
        """Globally Unban a user across all opted-in servers."""
        async with self.config.banned() as banned:
            if str(user_id) in banned:
                del banned[str(user_id)]
        async with ctx.typing():
            await self.remove_gbs_user(user_id)
        await ctx.tick()

    @globalban.command(name="list")
    @auth_check("globalban")
    async def _list(self, ctx: commands.Context) -> None:
        """Check who're on the global ban list."""
        o = "\n".join(k + "\t" + v for k, v in (await self.config.banned()).items())
        if not o:
            await ctx.send(inline("There are no banned users."))
            return
        for page in pagify(o):
            await ctx.send(box(page))

    async def update_gbs(self, ctx: commands.Context) -> None:
        for gid in await self.config.opted():
            guild = self.bot.get_guild(int(gid))

            if guild is None:
                continue

            for uid, reason in (await self.config.banned()).items():
                try:
                    ban_entries = [entry async for entry in guild.bans()]
                    if int(uid) in [b.user.id for b in ban_entries]:
                        async with self.config.guild(guild).banlist() as banlist:
                            if int(uid) not in banlist:
                                banlist.append(uid)
                        continue
                except (AttributeError, discord.Forbidden):
                    log.exception(f"Error with guild with id '{gid}'")
                    continue
                m = guild.get_member(int(uid))

                try:
                    if m is None:
                        try:
                            await guild.ban(
                                discord.Object(id=uid),
                                reason=f"Global ban initiated by {ctx.author} with the reason: {reason}",
                                delete_message_days=0,
                            )
                        except discord.errors.NotFound:
                            pass
                    else:
                        await guild.ban(
                            m,
                            reason=f"Global ban initiated by {ctx.author} with the reason: {reason}",
                            delete_message_days=0,
                        )

                    await modlog.create_case(
                        bot=self.bot,
                        guild=guild,
                        created_at=datetime.datetime.now(datetime.timezone.utc),
                        action_type="globalban",
                        user=m,
                        reason=f"Global ban initiated by {ctx.author} with the reason: {reason}",
                    )

                except discord.Forbidden:
                    log.warning(f"Failed to ban user with ID {uid} in guild {guild.name}")

    async def remove_gbs_guild(self, gid: int) -> None:
        guild = self.bot.get_guild(int(gid))

        for ban in await guild.bans():
            user = ban.user

            if (
                str(user.id) not in await self.config.banned()
                or user.id in await self.config.guild(guild).banlist()
            ):
                continue

            try:
                await guild.unban(user)
            except discord.Forbidden:
                pass

    async def remove_gbs_user(self, uid: int) -> None:
        for gid in await self.config.opted():
            guild: discord.Guild = self.bot.get_guild(int(gid))

            if guild is None:
                continue

            if uid in await self.config.guild(guild).banlist():
                continue

            try:
                ban_entries = [entry async for entry in guild.bans()]
                users = [b.user for b in ban_entries if b.user.id == int(uid)]
            except (AttributeError, discord.Forbidden):
                log.exception(f"Error with guild with id '{gid}'")
                continue

            if users:
                try:
                    await guild.unban(users[0])
                except discord.Forbidden:
                    pass
