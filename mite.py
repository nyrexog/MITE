import os
import re
import json
import asyncio
from pathlib import Path

import discord
from discord.ext import commands


# ============================================================
# MITE
# ============================================================

VERSION = "1.1.0"
STORAGE_FILE = Path("storage.mt")


# ============================================================
# ERRORS
# ============================================================

class MiteError(Exception):
    pass


# ============================================================
# STORAGE
# ============================================================

def load_storage():
    if not STORAGE_FILE.exists():
        return {}

    try:
        with STORAGE_FILE.open("r", encoding="utf-8") as file:
            data = json.load(file)

        return data if isinstance(data, dict) else {}

    except Exception:
        print("[Mite] Could not read storage.mt")
        return {}


STORAGE = load_storage()


def save_storage():
    try:
        with STORAGE_FILE.open("w", encoding="utf-8") as file:
            json.dump(
                STORAGE,
                file,
                indent=4,
                ensure_ascii=False
            )
    except Exception as error:
        print(f"[Mite] Storage error: {error}")


def guild_storage(guild_id):
    guild_id = str(guild_id)

    if guild_id not in STORAGE:
        STORAGE[guild_id] = {
            "ticket_timer": 0,
            "welcome_channel": None,
            "welcome_message": "WELCOME TO NETHOST",
            "settings": {}
        }

        save_storage()

    return STORAGE[guild_id]


# ============================================================
# TAG SYSTEM
# ============================================================

def next_ticket_number(guild):
    data = guild_storage(guild.id)

    data["ticket_timer"] = (
        int(data.get("ticket_timer", 0)) + 1
    )

    save_storage()

    return data["ticket_timer"]


def replace_tags(text, guild=None, user=None, timer=None):
    if text is None:
        return ""

    text = str(text)

    if user is not None:
        text = text.replace(
            "[USER]",
            str(user.display_name)
        )

        text = text.replace(
            "[USERID]",
            str(user.id)
        )

    if guild is not None:
        text = text.replace(
            "[SERVERNAME]",
            str(guild.name)
        )

    if timer is not None:
        text = text.replace(
            "[TIMER]",
            str(timer)
        )

    return text


# ============================================================
# TYPES
# ============================================================

def parse_integer(value):
    try:
        value = int(str(value))

        if value < 1:
            return None

        return value

    except (ValueError, TypeError):
        return None


def parse_user(guild, value):
    if value is None:
        return None

    value = str(value).strip()

    mention = re.fullmatch(
        r"<@!?(\d+)>",
        value
    )

    if mention:
        user_id = int(mention.group(1))

    elif value.isdigit():
        user_id = int(value)

    else:
        return None

    return guild.get_member(user_id)


# ============================================================
# PERMISSIONS
# ============================================================

def check_permission(member, permission):
    if member is None:
        return False

    permission = str(permission).strip()

    if permission.upper() == "ALL":
        return True

    if permission.upper() == "OWNER":
        return member.id == member.guild.owner_id

    if permission.upper() == "ADMIN":
        return member.guild_permissions.administrator

    if permission.upper().startswith("USER:"):
        try:
            user_id = int(
                permission.split(":", 1)[1]
            )

            return member.id == user_id

        except ValueError:
            return False

    if permission.isdigit():
        role_id = int(permission)

        return any(
            role.id == role_id
            for role in member.roles
        )

    return False


# ============================================================
# COMMAND OBJECT
# ============================================================

class MiteCommand:
    def __init__(
        self,
        name,
        arguments=None,
        permission="ALL"
    ):
        self.name = name
        self.arguments = arguments or []
        self.permission = permission

        self.body = []

        self.else_permission = None
        self.else_user = None
        self.else_integer = None


# ============================================================
# EMBED BUTTON
# ============================================================

class MiteButton(discord.ui.Button):
    def __init__(
        self,
        label,
        runtime
    ):
        super().__init__(
            label=label,
            style=discord.ButtonStyle.primary
        )

        self.runtime = runtime

    async def callback(self, interaction):
        await self.runtime.handle_button(
            interaction,
            self.label
        )


class MiteButtonView(discord.ui.View):
    def __init__(
        self,
        runtime,
        buttons
    ):
        super().__init__(
            timeout=None
        )

        for button in buttons:
            self.add_item(
                MiteButton(
                    button,
                    runtime
                )
            )


# ============================================================
# RUNTIME
# ============================================================

class MiteRuntime:

    def __init__(
        self,
        token=None,
        prefix="."
    ):

        self.token_value = token
        self.prefix_value = prefix

        self.commands = {}
        self.function_registry = {}

        self.welcome_enabled = False

        intents = discord.Intents.default()

        intents.guilds = True
        intents.members = True
        intents.messages = True
        intents.message_content = True

        self.client = commands.Bot(
            command_prefix=prefix,
            intents=intents
        )

        self.install_events()
        self.install_functions()

    # ========================================================
    # BOT / SELF ALIAS SYSTEM
    # ========================================================

    def register_function(
        self,
        name,
        function
    ):
        """
        One implementation.

        Both:

            bot.function()
            self.function()

        resolve to this same function.
        """

        self.function_registry[name] = function

    def resolve_function(
        self,
        object_name,
        function_name
    ):
        if object_name not in (
            "bot",
            "self"
        ):
            raise MiteError(
                f"Unknown object: {object_name}"
            )

        function = self.function_registry.get(
            function_name
        )

        if function is None:
            raise MiteError(
                f"Unknown function: {function_name}"
            )

        return function

    # ========================================================
    # EVENTS
    # ========================================================

    def install_events(self):

        @self.client.event
        async def on_ready():

            print(
                f"Mite Discord bot online as "
                f"{self.client.user}"
            )

        @self.client.event
        async def on_member_join(member):

            await self.handle_member_join(
                member
            )

    async def handle_member_join(
        self,
        member
    ):

        if not self.welcome_enabled:
            return

        data = guild_storage(
            member.guild.id
        )

        channel_id = data.get(
            "welcome_channel"
        )

        if not channel_id:
            return

        channel = member.guild.get_channel(
            int(channel_id)
        )

        if channel is None:
            return

        message = replace_tags(
            data.get(
                "welcome_message",
                "WELCOME TO NETHOST"
            ),
            guild=member.guild,
            user=member
        )

        try:
            await channel.send(
                message
            )

        except discord.Forbidden:
            print(
                "[Mite] Missing permission "
                "for welcome channel."
            )

    # ========================================================
    # CORE FUNCTIONS
    # ========================================================

    def set_token(self, token):
        self.token_value = token

    def set_prefix(self, prefix):
        self.prefix_value = str(prefix)

        self.client.command_prefix = (
            self.prefix_value
        )

    async def reply(
        self,
        ctx,
        message
    ):
        await ctx.send(
            str(message)
        )

    async def reply_user(
        self,
        interaction,
        message
    ):
        """
        Private interaction response.

        Equivalent Mite syntax:

            bot.reply.user(...)
            self.reply.user(...)
        """

        message = replace_tags(
            message,
            guild=interaction.guild,
            user=interaction.user
        )

        if interaction.response.is_done():
            await interaction.followup.send(
                message,
                ephemeral=True
            )
        else:
            await interaction.response.send_message(
                message,
                ephemeral=True
            )

    async def confirm(
        self,
        ctx,
        message="Are you sure?"
    ):
        """
        Simple confirmation message.

        Both bot.confirm() and self.confirm()
        resolve here.
        """

        await ctx.send(
            f"⚠️ {message}"
        )

    # ========================================================
    # EMBEDS
    # ========================================================

    async def embed(
        self,
        ctx,
        title,
        description="",
        buttons=None
    ):

        embed = discord.Embed(
            title=str(title),
            description=str(description)
        )

        view = None

        if buttons:
            view = MiteButtonView(
                self,
                buttons
            )

        await ctx.send(
            embed=embed,
            view=view
        )

    # ========================================================
    # BUTTONS
    # ========================================================

    async def handle_button(
        self,
        interaction,
        label
    ):

        normalized = str(label).upper()

        if normalized == "CREATE A TICKET":

            await self.create_ticket(
                interaction
            )

            return

        await self.reply_user(
            interaction,
            f"> Button `{label}` was clicked."
        )

    # ========================================================
    # TICKET SYSTEM
    # ========================================================

    async def create_ticket(
        self,
        interaction
    ):

        guild = interaction.guild
        user = interaction.user

        if guild is None:
            return

        timer = next_ticket_number(
            guild
        )

        channel_name = replace_tags(
            "TICKET-[TIMER]",
            guild=guild,
            user=user,
            timer=timer
        )

        overwrites = {
            guild.default_role:
                discord.PermissionOverwrite(
                    view_channel=False
                ),

            user:
                discord.PermissionOverwrite(
                    view_channel=True,
                    send_messages=True,
                    read_message_history=True
                )
        }

        if guild.me:
            overwrites[guild.me] = (
                discord.PermissionOverwrite(
                    view_channel=True,
                    send_messages=True,
                    manage_channels=True,
                    read_message_history=True
                )
            )

        try:

            channel = await guild.create_text_channel(
                channel_name,
                overwrites=overwrites,
                reason="Mite ticket"
            )

        except discord.Forbidden:

            await self.reply_user(
                interaction,
                "> I don't have permission to create tickets."
            )

            return

        except Exception as error:

            print(
                f"[Mite] Ticket error: {error}"
            )

            await self.reply_user(
                interaction,
                "> Could not create your ticket."
            )

            return

        await self.reply_user(
            interaction,
            "YOUR TICKET HAS BEEN CREATED"
        )

        await channel.send(
            replace_tags(
                "Your ticket is created, "
                "wait for an admin to reply.\n"
                "User: [USER]\n"
                "User ID: [USERID]\n"
                "Server: [SERVERNAME]\n"
                "Ticket: [TIMER]",
                guild=guild,
                user=user,
                timer=timer
            )
        )

    # ========================================================
    # ROLE FUNCTIONS
    # ========================================================

    async def give_role(
        self,
        member,
        role
    ):

        if member is None or role is None:
            return False

        try:

            await member.add_roles(
                role,
                reason="Mite"
            )

            return True

        except Exception:
            return False

    async def remove_role(
        self,
        member,
        role
    ):

        if member is None or role is None:
            return False

        try:

            await member.remove_roles(
                role,
                reason="Mite"
            )

            return True

        except Exception:
            return False

    # ========================================================
    # CHANNEL CREATION
    # ========================================================

    async def create_channel(
        self,
        guild,
        amount,
        name
    ):

        amount = parse_integer(
            amount
        )

        if amount is None:
            return []

        created = []

        for number in range(
            1,
            amount + 1
        ):

            channel_name = replace_tags(
                name,
                guild=guild,
                timer=number
            )

            try:

                channel = (
                    await guild.create_text_channel(
                        channel_name,
                        reason="Mite"
                    )
                )

                created.append(
                    channel
                )

            except Exception as error:

                print(
                    f"[Mite] Channel error: {error}"
                )

                break

        return created

    async def create_channels(
        self,
        guild,
        amount,
        name="mite-channel"
    ):

        return await self.create_channel(
            guild,
            amount,
            name
        )

    # ========================================================
    # WELCOME SETUP
    # ========================================================

    def set_welcome_channel(
        self,
        guild,
        channel
    ):

        data = guild_storage(
            guild.id
        )

        data[
            "welcome_channel"
        ] = channel.id

        save_storage()

    def set_welcome_message(
        self,
        guild,
        message
    ):

        data = guild_storage(
            guild.id
        )

        data[
            "welcome_message"
        ] = str(message)

        save_storage()

    # ========================================================
    # SAFE MODERATION
    # ========================================================

    async def ban_user(
        self,
        guild,
        user
    ):

        """
        Single-user moderation API.

        The Mite parser can resolve USER first.
        """

        if user is None:
            return False

        try:

            await guild.ban(
                user,
                reason="Mite"
            )

            return True

        except Exception:
            return False

    # ========================================================
    # MASS-ACTION NAMES
    # ========================================================

    async def mass_action_placeholder(
        self,
        ctx,
        function_name,
        amount
    ):

        """
        Reserved Mite API names.

        These remain recognized by the runtime,
        but mass deletion / mass banning is not
        executed here.
        """

        await ctx.send(
            f"> Mite recognized `{function_name}` "
            f"with amount `{amount}`."
        )

    # ========================================================
    # FUNCTION REGISTRY
    # ========================================================

    def install_functions(self):

        self.register_function(
            "token",
            self.set_token
        )

        self.register_function(
            "prefix",
            self.set_prefix
        )

        self.register_function(
            "reply",
            self.reply
        )

        self.register_function(
            "confirm",
            self.confirm
        )

        self.register_function(
            "embed",
            self.embed
        )

        self.register_function(
            "give_role",
            self.give_role
        )

        self.register_function(
            "remove_role",
            self.remove_role
        )

        self.register_function(
            "create_channel",
            self.create_channel
        )

        self.register_function(
            "create_channels",
            self.create_channels
        )

        self.register_function(
            "ban",
            self.ban_user
        )

        self.register_function(
            "delete_channels",
            self.mass_action_placeholder
        )

        self.register_function(
            "reply.user",
            self.reply_user
        )

    # ========================================================
    # COMMAND REGISTRATION
    # ========================================================

    def register_command(
        self,
        name,
        callback,
        argument_type=None,
        permission="ALL"
    ):

        async def command_handler(
            ctx,
            argument=None
        ):

            if not check_permission(
                ctx.author,
                permission
            ):

                await ctx.send(
                    "> Not enough permissions.\n"
                    f"> Required: `{permission}`"
                )

                return

            if argument_type == "INTEGER":

                if argument is None:

                    await ctx.send(
                        "> An amount is required."
                    )

                    return

                amount = parse_integer(
                    argument
                )

                if amount is None:

                    await ctx.send(
                        f"> `{argument}` "
                        "is not a valid integer."
                    )

                    return

                await callback(
                    ctx,
                    amount
                )

                return

            if argument_type == "USER":

                if argument is None:

                    await ctx.send(
                        "> A user is required."
                    )

                    return

                user = parse_user(
                    ctx.guild,
                    argument
                )

                if user is None:

                    await ctx.send(
                        f"> `{argument}` "
                        "is not a valid user."
                    )

                    return

                await callback(
                    ctx,
                    user
                )

                return

            await callback(
                ctx,
                argument
            )

        self.client.command(
            name=name
        )(command_handler)

    # ========================================================
    # BUILT-IN COMMANDS
    # ========================================================

    def install_builtin_commands(self):

        @self.client.command(
            name="help"
        )
        async def mite_help(ctx):

            await ctx.send(
                "> `RANE HELP MENU`\n\n"
                "> `WELCOME` ➜ Set welcome channel\n"
                "> `GIVEROLE (USER) (ROLE)` "
                "➜ Give a role\n"
                "> `REMOVEROLE (USER) (ROLE)` "
                "➜ Remove a role\n"
                "> `CREATECHANNEL (AMOUNT)` "
                "➜ Create channels\n"
                "> `HELP` ➜ Shows this menu\n\n"
                "> `RANE MITE BOT`"
            )

        @self.client.command(
            name="welcome"
        )
        @commands.has_permissions(
            manage_guild=True
        )
        async def mite_welcome(ctx):

            self.set_welcome_channel(
                ctx.guild,
                ctx.channel
            )

            self.set_welcome_message(
                ctx.guild,
                "WELCOME TO NETHOST"
            )

            self.welcome_enabled = True

            await ctx.send(
                "> Welcome channel saved.\n"
                "> New members will receive:\n"
                "> `WELCOME TO NETHOST`"
            )

        @self.client.command(
            name="createchannel"
        )
        @commands.has_permissions(
            manage_channels=True
        )
        async def mite_createchannel(
            ctx,
            amount: str
        ):

            number = parse_integer(
                amount
            )

            if number is None:

                await ctx.send(
                    f"> `{amount}` "
                    "is not a valid integer."
                )

                return

            created = (
                await self.create_channel(
                    ctx.guild,
                    number,
                    "mite-channel-[TIMER]"
                )
            )

            await ctx.send(
                f"> Created `{len(created)}` channel(s)."
            )

    # ========================================================
    # ERROR HANDLER
    # ========================================================

    def install_error_handler(self):

        @self.client.event
        async def on_command_error(
            ctx,
            error
        ):

            if isinstance(
                error,
                commands.MissingPermissions
            ):

                await ctx.send(
                    "> Not enough permissions."
                )

                return

            if isinstance(
                error,
                commands.BadArgument
            ):

                await ctx.send(
                    "> Invalid argument."
                )

                return

            if isinstance(
                error,
                commands.MissingRequiredArgument
            ):

                await ctx.send(
                    "> Missing required argument."
                )

                return

            if isinstance(
                error,
                commands.CommandNotFound
            ):

                return

            print(
                f"[Mite] Error: {error}"
            )

    # ========================================================
    # LOGIN
    # ========================================================

    def login(self):

        if not self.token_value:

            raise MiteError(
                "No Discord bot token was supplied."
            )

        self.client.run(
            self.token_value
        )


# ============================================================
# MITE PARSER
# ============================================================

class MiteParser:

    def __init__(
        self,
        source
    ):

        self.source = source
        self.lines = source.splitlines()

        self.variables = {}

        self.token = os.getenv(
            "DISCORD_TOKEN",
            ""
        )

        self.prefix = "."

        self.runtime = None

        self.inside_command = False
        self.current_command = None

    # ========================================================
    # CLEAN
    # ========================================================

    def clean(
        self,
        line
    ):

        line = line.strip()

        if not line:
            return ""

        if line.startswith("#"):
            return ""

        return line

    # ========================================================
    # STRING
    # ========================================================

    def parse_string(
        self,
        value
    ):

        value = value.strip()

        if value.endswith(";"):
            value = value[:-1].strip()

        if (
            len(value) >= 2
            and value[0] == '"'
            and value[-1] == '"'
        ):
            return value[1:-1]

        return value

    # ========================================================
    # ASSIGNMENT
    # ========================================================

    def assignment(
        self,
        line
    ):

        match = re.match(
            r'^([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.+)$',
            line
        )

        if not match:
            return False

        name = match.group(1)

        value = match.group(2).strip()

        if value.endswith(";"):
            value = value[:-1].strip()

        value = self.parse_string(
            value
        )

        self.variables[name] = value

        if name == "TOKEN":
            self.token = value

        if name == "PREFIX":
            self.prefix = value

        return True

    # ========================================================
    # TYPE DECLARATION
    # ========================================================

    def parse_type(
        self,
        line
    ):

        match = re.match(
            r'^\{([A-Za-z_][A-Za-z0-9_]*)\}\s*=\s*([A-Z]+)\s*;?$',
            line
        )

        if not match:
            return False

        name = match.group(1)
        value_type = match.group(2)

        self.variables[
            name
        ] = {
            "type": value_type
        }

        return True

    # ========================================================
    # OBJECT FUNCTION
    # ========================================================

    def parse_function(
        self,
        line
    ):

        match = re.match(
            r'^(bot|self)\.([A-Za-z_][A-Za-z0-9_.]*)\((.*)\);?$',
            line
        )

        if not match:
            return False

        object_name = match.group(1)
        function_name = match.group(2)

        function = (
            self.runtime.resolve_function(
                object_name,
                function_name
            )
        )

        # Store parsed function call.
        # Command execution is handled by
        # the generated command callback.

        return True

    # ========================================================
    # COMMAND
    # ========================================================

    def parse_command(
        self,
        line
    ):

        match = re.match(
            r'^(?:bot|self)\.command\('
            r'"([^"]+)"'
            r'(?:\s*,\s*\{([^}]+)\})?'
            r'\)\s*\{?$',
            line
        )

        if not match:
            return False

        name = match.group(1)
        argument = match.group(2)

        if argument:
            argument = argument.strip()

        command = MiteCommand(
            name=name,
            arguments=(
                [argument]
                if argument
                else []
            ),
            permission=self.variables.get(
                "PERM",
                "ALL"
            )
        )

        self.current_command = command
        self.inside_command = True

        self.runtime.commands[
            name
        ] = command

        return True

    # ========================================================
    # ELSE
    # ========================================================

    def parse_else(
        self,
        line
    ):

        if line.startswith(
            "else."
        ):

            return True

        return False

    # ========================================================
    # EVENT
    # ========================================================

    def parse_event(
        self,
        line
    ):

        if line.startswith(
            "if user.join.guild"
        ):

            self.runtime.welcome_enabled = True

            return True

        return False

    # ========================================================
    # PARSE
    # ========================================================

    def parse(self):

        for raw_line in self.lines:

            line = self.clean(
                raw_line
            )

            if not line:
                continue

            # ------------------------------------------------
            # import
            # ------------------------------------------------

            if line == "import discord":
                continue

            # ------------------------------------------------
            # Closing command
            # ------------------------------------------------

            if line == "}":

                self.inside_command = False
                self.current_command = None

                continue

            # ------------------------------------------------
            # assignment
            # ------------------------------------------------

            if self.assignment(
                line
            ):
                continue

            # ------------------------------------------------
            # type
            # ------------------------------------------------

            if self.parse_type(
                line
            ):
                continue

            # ------------------------------------------------
            # event
            # ------------------------------------------------

            if self.parse_event(
                line
            ):
                continue

            # ------------------------------------------------
            # command
            # ------------------------------------------------

            if self.parse_command(
                line
            ):
                continue

            # ------------------------------------------------
            # else
            # ------------------------------------------------

            if self.parse_else(
                line
            ):
                continue

            # ------------------------------------------------
            # function
            # ------------------------------------------------

            if (
                self.runtime
                and self.parse_function(
                    line
                )
            ):
                continue

            # ------------------------------------------------
            # ignore supported syntax inside command
            # ------------------------------------------------

            if self.inside_command:
                if self.current_command:
                    self.current_command.body.append(
                        line
                    )

                continue

            print(
                f"MiteError: unknown statement: {line}"
            )

        self.runtime = MiteRuntime(
            token=self.token,
            prefix=self.prefix
        )

        self.runtime.install_builtin_commands()
        self.runtime.install_error_handler()

        return self.runtime


# ============================================================
# RUNNER
# ============================================================

def run_mite(
    filename
):

    path = Path(
        filename
    )

    if not path.exists():

        raise MiteError(
            f"{filename} was not found."
        )

    source = path.read_text(
        encoding="utf-8"
    )

    parser = MiteParser(
        source
    )

    runtime = parser.parse()

    runtime.login()


# ============================================================
# MAIN
# ============================================================

if __name__ == "__main__":

    import sys

    if len(sys.argv) < 2:

        print(
            f"Mite Runtime v{VERSION}"
        )

        print(
            "Usage:"
        )

        print(
            "python3 mite.py main.llt"
        )

        raise SystemExit(1)

    try:

        run_mite(
            sys.argv[1]
        )

    except MiteError as error:

        print(
            f"MiteError: {error}"
        )

        raise SystemExit(1)

# ============================================================
# MITE EMBED EXTENSION
# Add this AFTER your existing mite.py code
# ============================================================

class MiteEmbed:
    def __init__(self, guild=None, user=None, timer=None):
        self.guild = guild
        self.user = user
        self.timer = timer

        self.discord_embed = discord.Embed()

    def _tags(self, value):
        value = str(value)

        if self.user is not None:
            value = value.replace(
                "[USER]",
                str(self.user.display_name)
            )

            value = value.replace(
                "[USERID]",
                str(self.user.id)
            )

        if self.guild is not None:
            value = value.replace(
                "[SERVERNAME]",
                str(self.guild.name)
            )

        if self.timer is not None:
            value = value.replace(
                "[TIMER]",
                str(self.timer)
            )

        return value

    def title(self, value):
        self.discord_embed.title = self._tags(value)
        return self

    def description(self, value):
        self.discord_embed.description = self._tags(value)
        return self

    def footer(self, value):
        self.discord_embed.set_footer(
            text=self._tags(value)
        )
        return self

    def author(self, value):
        self.discord_embed.set_author(
            name=self._tags(value)
        )
        return self

    def thumbnail(self, value):
        self.discord_embed.set_thumbnail(
            url=self._tags(value)
        )
        return self

    def image(self, value):
        self.discord_embed.set_image(
            url=self._tags(value)
        )
        return self

    def url(self, value):
        self.discord_embed.url = self._tags(value)
        return self

    def field(
        self,
        name,
        value,
        inline=False
    ):
        self.discord_embed.add_field(
            name=self._tags(name),
            value=self._tags(value),
            inline=inline
        )
        return self


# ============================================================
# Embed helper functions
# ============================================================

def mite_embed(
    guild=None,
    user=None,
    timer=None
):
    return MiteEmbed(
        guild=guild,
        user=user,
        timer=timer
    )


async def mite_reply_embed(
    ctx,
    embed,
    buttons=None
):
    view = None

    if buttons:
        view = MiteView(
            runtime=None,
            buttons=buttons
        )

    await ctx.send(
        embed=embed.discord_embed,
        view=view
    )


# ============================================================
# bot.* / self.* aliases
# ============================================================

def mite_get_embed(
    runtime,
    guild=None,
    user=None,
    timer=None
):
    return MiteEmbed(
        guild=guild,
        user=user,
        timer=timer
    )


# Both names intentionally point to the
# same embed implementation.

bot_embed = mite_get_embed
self_embed = mite_get_embed
