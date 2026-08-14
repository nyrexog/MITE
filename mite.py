import os
import re
import sys
import subprocess


class MiteError(Exception):
    pass


VARS = {}
COMMANDS = {}
SLASH_COMMANDS = {}

TOKEN = None
PREFIX = '"!"'
ACTIVITY = None


TYPES = {
    "INTEGER",
    "ALPHA",
    "BOOLEAN",
    "USER",
    "CHANNEL",
    "ROLE",
}


def parts(s):
    out = []
    cur = ""
    quote = False

    for c in s:
        if c == '"':
            quote = not quote
            cur += c

        elif c == ";" and not quote:
            if cur.strip():
                out.append(cur.strip())
            cur = ""

        else:
            cur += c

    if cur.strip():
        out.append(cur.strip())

    return out


def expr(s):
    s = s.strip().rstrip(";").strip()

    m = re.fullmatch(
        r'import\.env\("([^"]+)"\)',
        s
    )

    if m:
        return f'os.getenv({m.group(1)!r})'

    if s in VARS:
        return VARS[s]

    if re.fullmatch(r"-?\d+", s):
        return s

    if s.startswith('"') and s.endswith('"'):
        return s

    bits = re.findall(
        r'"(?:\\.|[^"\\])*"|[A-Za-z_]\w*',
        s
    )

    if not bits:
        return '""'

    return " + ".join(
        b if b.startswith('"') else f"str({b})"
        for b in bits
    )


def block(lines, start):
    result = []
    depth = 1
    i = start

    while i < len(lines):

        line = lines[i].strip()

        if "{" in line:
            depth += line.count("{")

        if "}" in line:
            depth -= line.count("}")

            if depth == 0:
                return result, i

        result.append(line)
        i += 1

    raise MiteError("missing }")


def parse_type(line):
    m = re.fullmatch(
        r'\{([A-Za-z_]\w*)\}\s*=\s*([A-Z]+)\s*;?',
        line
    )

    if not m:
        return None

    name = m.group(1)
    type_name = m.group(2)

    if type_name not in TYPES:
        raise MiteError(
            f"unknown type: {type_name}"
        )

    return name, type_name


def validation_code(name, type_name):
    code = []

    if type_name == "INTEGER":

        code += [
            f"    try:",
            f"        {name} = int({name})",
            "    except (ValueError, TypeError):",
            f"        await send_reply("
            f"'The ' + str({name}) + "
            f"' is not a number')",
            "        return",
        ]

    elif type_name == "ALPHA":

        code += [
            f"    if not str({name}).isalpha():",
            f"        await send_reply("
            f"'The ' + str({name}) + "
            f"' contains invalid characters')",
            "        return",
        ]

    elif type_name == "BOOLEAN":

        code += [
            f"    if str({name}).lower() not in "
            "('true', 'false'):",
            f"        await send_reply("
            f"'The ' + str({name}) + "
            f"' is not a boolean')",
            "        return",
            f"    {name} = "
            f"str({name}).lower() == 'true'",
        ]

    elif type_name == "USER":

        code += [
            f"    {name} = resolve_member("
            f"message.guild, {name})",
            f"    if {name} is None:",
            f"        await send_reply("
            f"'User not found.')",
            "        return",
        ]

    elif type_name == "CHANNEL":

        code += [
            f"    {name} = resolve_channel("
            f"message.guild, {name})",
            f"    if {name} is None:",
            f"        await send_reply("
            f"'Channel not found.')",
            "        return",
        ]

    elif type_name == "ROLE":

        code += [
            f"    {name} = resolve_role("
            f"message.guild, {name})",
            f"    if {name} is None:",
            f"        await send_reply("
            f"'Role not found.')",
            "        return",
        ]

    return code


def embed(lines, start):

    body, end = block(
        lines,
        start + 1
    )

    data = {
        "title": "None",
        "description": "None",
        "fields": []
    }

    for line in body:

        m = re.fullmatch(
            r'title\((.*)\)\s*;?',
            line
        )

        if m:
            data["title"] = expr(
                m.group(1)
            )
            continue

        m = re.fullmatch(
            r'description\((.*)\)\s*;?',
            line
        )

        if m:
            data["description"] = expr(
                m.group(1)
            )
            continue

        m = re.fullmatch(
            r'field\((.*)\)\s*;?',
            line
        )

        if m:

            a = parts(
                m.group(1)
            )

            if len(a) >= 2:

                data["fields"].append(
                    (
                        expr(a[0]),
                        expr(a[1])
                    )
                )

            continue

        raise MiteError(
            f"unknown embed statement: {line}"
        )

    return data, end


def emit_embed(data, target):

    out = [
        "    e = discord.Embed(",
        f"        title={data['title']},",
        f"        description={data['description']}",
        "    )",
    ]

    for n, v in data["fields"]:

        out.append(
            f"    e.add_field("
            f"name={n}, "
            f"value={v}, "
            f"inline=False)"
        )

    if target == "interaction":

        out.append(
            "    await send_embed(e)"
        )

    else:

        out.append(
            "    await message.channel.send("
            "embed=e)"
        )

    return out


def compile_body(body, target, validations=None):

    if validations is None:
        validations = []

    out = []

    for name, type_name in validations:

        out += validation_code(
            name,
            type_name
        )

    i = 0

    while i < len(body):

        line = body[i].strip()

        if not line:

            i += 1
            continue

        # Reply
        m = re.fullmatch(
            r'(?:self\.)?reply\((.*)\)\s*;?',
            line
        )

        if m:

            out.append(
                f"    await send_reply("
                f"{expr(m.group(1))})"
            )

            i += 1
            continue

        # Embed
        if line in (
            "self.reply.embed {",
            "self.embed {"
        ):

            data, end = embed(
                body,
                i
            )

            out += emit_embed(
                data,
                target
            )

            i = end + 1
            continue

        # Else reply
        m = re.fullmatch(
            r'else\.self\.reply\((.*)\)\s*;?',
            line
        )

        if m:

            out.append(
                f"    await send_reply("
                f"{expr(m.group(1))})"
            )

            i += 1
            continue

        # RPC
        m = re.fullmatch(
            r'self\.rpc\.activity\((.*)\)\s*;?',
            line
        )

        if m:

            a = parts(
                m.group(1)
            )

            if len(a) >= 2:

                out.append(
                    f"    await set_activity("
                    f"{expr(a[0])}, "
                    f"{expr(a[1])})"
                )

            i += 1
            continue

        # Ban
        m = re.fullmatch(
            r'self\.ban\((.*)\)\s*;?',
            line
        )

        if m:

            value = expr(
                m.group(1)
            )

            out += [
                f"    target = resolve_member("
                f"message.guild, {value})",

                "    if target is None:",

                "        await send_reply("
                "'User not found.')",

                "        return",

                "    try:",

                "        await target.ban("
                "reason='Mite command')",

                "    except discord.Forbidden:",

                "        await send_reply("
                "'NOT ENOUGH PERMS')",

                "        return",
            ]

            i += 1
            continue

        # Kick
        m = re.fullmatch(
            r'self\.kick\((.*)\)\s*;?',
            line
        )

        if m:

            value = expr(
                m.group(1)
            )

            out += [
                f"    target = resolve_member("
                f"message.guild, {value})",

                "    if target is None:",

                "        await send_reply("
                "'User not found.')",

                "        return",

                "    try:",

                "        await target.kick("
                "reason='Mite command')",

                "    except discord.Forbidden:",

                "        await send_reply("
                "'NOT ENOUGH PERMS')",

                "        return",
            ]

            i += 1
            continue

        # Delete current channel
        if re.fullmatch(
            r'self\.delete_channel\(\)\s*;?',
            line
        ):

            out += [
                "    try:",

                "        await message.channel.delete("
                "reason='Mite command')",

                "    except discord.Forbidden:",

                "        await send_reply("
                "'NOT ENOUGH PERMS')",

                "        return",
            ]

            i += 1
            continue

        # Delete multiple channels
        m = re.fullmatch(
            r'self\.delete_channels\((.*)\)\s*;?',
            line
        )

        if m:

            amount = expr(
                m.group(1)
            )

            out += [
                f"    amount = int({amount})",

                "    if amount <= 0:",

                "        await send_reply("
                "'Amount must be greater than 0.')",

                "        return",

                "    amount = min(amount, 10)",

                "    count = 0",

                "    for channel in "
                "list(message.guild.channels)[:amount]:",

                "        try:",

                "            await channel.delete("
                "reason='Mite command')",

                "            count += 1",

                "        except discord.Forbidden:",

                "            pass",

                "    await send_reply("
                "f'Deleted {count} channels.')",
            ]

            i += 1
            continue

        raise MiteError(
            f"unknown statement: {line}"
        )

    return out


def parse(filename):

    global TOKEN
    global PREFIX
    global ACTIVITY

    with open(
        filename,
        encoding="utf-8"
    ) as f:

        lines = f.readlines()

    i = 0

    while i < len(lines):

        line = lines[i].strip()

        if (
            not line
            or line.startswith("#")
            or line == "import discord"
        ):

            i += 1
            continue

        # Variable
        m = re.fullmatch(
            r'([A-Za-z_]\w*)\s*=\s*(.+)',
            line
        )

        if m:

            VARS[m.group(1)] = expr(
                m.group(2)
            )

            i += 1
            continue

        # Token
        m = re.fullmatch(
            r'self\.token\((.*)\)\s*;?',
            line
        )

        if m:

            TOKEN = expr(
                m.group(1)
            )

            i += 1
            continue

        # Prefix
        m = re.fullmatch(
            r'self\.prefix\((.*)\)\s*;?',
            line
        )

        if m:

            PREFIX = expr(
                m.group(1)
            )

            i += 1
            continue

        # RPC
        m = re.fullmatch(
            r'self\.rpc\.activity\((.*)\)\s*;?',
            line
        )

        if m:

            a = parts(
                m.group(1)
            )

            if len(a) >= 2:

                ACTIVITY = (
                    expr(a[0]),
                    expr(a[1])
                )

            i += 1
            continue

        # Command
        m = re.fullmatch(
            r'self\.(command|slash)'
            r'\("([^"]+)"'
            r'(?:\s*,\s*(.*))?\)'
            r'\s*\{',
            line
        )

        if m:

            kind, name, raw = m.groups()

            args = []

            if raw:

                args = [
                    x.strip()
                    .strip("{} ")
                    for x in raw.split(",")
                ]

            body, end = block(
                lines,
                i + 1
            )

            validations = []

            cleaned_body = []

            for bline in body:

                parsed = parse_type(
                    bline
                )

                if parsed:

                    validations.append(
                        parsed
                    )

                else:

                    cleaned_body.append(
                        bline
                    )

            item = (
                args,
                validations,
                cleaned_body
            )

            if kind == "command":

                COMMANDS[name] = item

            else:

                SLASH_COMMANDS[name] = item

            i = end + 1
            continue

        # Login
        if re.fullmatch(
            r'self\.login\(\)\s*;?',
            line
        ):

            i += 1
            continue

        raise MiteError(
            f"{filename}:{i + 1}: "
            f"unknown statement: {line}"
        )

    if TOKEN is None:

        raise MiteError(
            "self.token(...) is required"
        )


def generate():

    py = [

        "import os",

        "import discord",

        "from discord import app_commands",

        "",

        f"TOKEN = {TOKEN}",

        f"PREFIX = {PREFIX}",

        "",

        "intents = discord.Intents.default()",

        "intents.message_content = True",

        "intents.members = True",

        "",

        "client = discord.Client("
        "intents=intents)",

        "tree = app_commands.CommandTree("
        "client)",

        "",

        "async def set_activity(kind, text):",

        "    kinds = {",

        "        'Playing': discord.Game("
        "name=text),",

        "        'Watching': discord.Activity("
        "type=discord.ActivityType.watching,"
        "name=text),",

        "        'Listening': discord.Activity("
        "type=discord.ActivityType.listening,"
        "name=text),",

        "        'Competing': discord.Activity("
        "type=discord.ActivityType.competing,"
        "name=text),",

        "    }",

        "    activity = kinds.get("
        "kind, discord.Game(name=text))",

        "    await client.change_presence("
        "activity=activity)",

        "",

        "def resolve_member(guild, value):",

        "    s = str(value).strip('<@!>')",

        "    try:",

        "        return guild.get_member(int(s))",

        "    except Exception:",

        "        return None",

        "",

        "def resolve_channel(guild, value):",

        "    s = str(value).strip('<#>')",

        "    try:",

        "        return guild.get_channel(int(s))",

        "    except Exception:",

        "        return None",

        "",

        "def resolve_role(guild, value):",

        "    s = str(value).strip('<@&>')",

        "    try:",

        "        return guild.get_role(int(s))",

        "    except Exception:",

        "        return None",

        "",
    ]

    # Prefix commands
    for name, item in COMMANDS.items():

        args, validations, body = item

        fn = re.sub(
            r'\W+',
            '_',
            name
        )

        py += [

            f"async def cmd_{fn}("
            "message, values):",

            "    async def send_reply(text):",

            "        await message.channel.send("
            "text)",
        ]

        for n, arg in enumerate(args):

            py.append(
                f"    {arg} = "
                f"values[{n}] "
                f"if len(values) > {n} "
                f"else ''"
            )

        py += compile_body(
            body,
            "message",
            validations
        )

        py += [""]

    # Slash commands
    for name, item in SLASH_COMMANDS.items():

        args, validations, body = item

        fn = re.sub(
            r'\W+',
            '_',
            name
        )

        params = ", ".join(
            f"{arg}: str"
            for arg in args
        )

        if params:
            params = ", " + params

        py += [

            f'@tree.command(name="{name}")',

            f"async def slash_{fn}("
            f"interaction: discord.Interaction"
            f"{params}):",

            "    async def send_reply(text):",

            "        if interaction.response.is_done():",

            "            await interaction.followup.send("
            "text)",

            "        else:",

            "            await interaction.response.send_message("
            "text)",

            "",

            "    async def send_embed(e):",

            "        if interaction.response.is_done():",

            "            await interaction.followup.send("
            "embed=e)",

            "        else:",

            "            await interaction.response.send_message("
            "embed=e)",
        ]

        # Slash values are already supplied by Discord.
        for arg, type_name in validations:

            py += validation_code(
                arg,
                type_name
            )

        py += compile_body(
            body,
            "interaction",
            []
        )

        py += [""]

    py += [

        "@client.event",

        "async def on_ready():",
    ]

    if ACTIVITY:

        py.append(
            f"    await set_activity("
            f"{ACTIVITY[0]}, "
            f"{ACTIVITY[1]})"
        )

    py += [

        "    await tree.sync()",

        "    print('Mite')",

        "    print('Bot: ' + str(client.user))",

        "    print('Status: Online')",

        "    print('Mite is ready.')",

        "",

        "@client.event",

        "async def on_message(message):",

        "    if message.author == client.user:",

        "        return",

        "",

        "    if not message.content.startswith(PREFIX):",

        "        return",

        "",

        "    p = message.content[len(PREFIX):].split()",

        "",

        "    if not p:",

        "        return",

        "",

        "    name = p[0].lower()",

        "    values = p[1:]",

        "",
    ]

    for name in COMMANDS:

        fn = re.sub(
            r'\W+',
            '_',
            name
        )

        py += [

            f"    if name == {name!r}:",

            f"        await cmd_{fn}("
            "message, values)",

            "        return",
        ]

    py += [

        "",

        "client.run(TOKEN)",
    ]

    return "\n".join(py)


def main():

    if len(sys.argv) != 2:

        print(
            "Usage: python3 mite.py main.llt"
        )

        return 1

    try:

        parse(
            sys.argv[1]
        )

        runner = os.path.join(
            os.path.dirname(
                os.path.abspath(
                    sys.argv[1]
                )
            ),
            "runner"
        )

        os.makedirs(
            runner,
            exist_ok=True
        )

        output = os.path.join(
            runner,
            "main.py"
        )

        with open(
            output,
            "w",
            encoding="utf-8"
        ) as f:

            f.write(
                generate()
            )

        print("Mite")
        print("Created runner/main.py")
        print("Starting...")

        return subprocess.call(
            [
                sys.executable,
                output
            ]
        )

    except MiteError as e:

        print(
            "MiteError:",
            e
        )

        return 1


if __name__ == "__main__":
    raise SystemExit(
        main()
    )
