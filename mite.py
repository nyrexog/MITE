import sys
import os
import re
import shutil
import subprocess


class MiteError(Exception):
    pass


variables = {}
prefix_commands = {}
slash_commands = {}

bot_token = None
bot_prefix = "!"
discord_used = False


# ============================================================
# HELPERS
# ============================================================

def escape_python_string(value):
    return value.replace("\\", "\\\\").replace('"', '\\"')


def variable_expression(expression):
    expression = expression.strip()

    pieces = []
    current = ""
    quoted = False
    i = 0

    while i < len(expression):
        char = expression[i]

        if char == '"':
            quoted = not quoted
            current += char
            i += 1
            continue

        if not quoted:
            match = re.match(
                r'([A-Za-z_][A-Za-z0-9_]*)\s*;',
                expression[i:]
            )

            if match:
                if current.strip():
                    pieces.append(current.strip())

                pieces.append(
                    f"str({match.group(1)})"
                )

                i += match.end()
                current = ""
                continue

        current += char
        i += 1

    if current.strip():
        pieces.append(current.strip())

    if not pieces:
        return '""'

    return " + ".join(pieces)


def translate_value(value):
    value = value.strip()

    # import.env("NAME";)
    match = re.fullmatch(
        r'import\.env\("([^"]+)"\s*;?\)',
        value
    )

    if match:
        return (
            f'os.getenv("{escape_python_string(match.group(1))}")'
        )

    # String
    if (
        len(value) >= 2
        and value.startswith('"')
        and value.endswith('"')
    ):
        return value

    # Number
    if re.fullmatch(r"-?\d+(\.\d+)?", value):
        return value

    # Boolean
    if value == "true":
        return "True"

    if value == "false":
        return "False"

    # Variable
    match = re.fullmatch(
        r'([A-Za-z_][A-Za-z0-9_]*)\s*;',
        value
    )

    if match:
        return match.group(1)

    return variable_expression(value)


def compile_statement(statement, context):
    statement = statement.strip()

    if not statement:
        return []

    # bot.reply(...)
    match = re.fullmatch(
        r'bot\.reply\((.*)\)\s*;?',
        statement,
        re.DOTALL
    )

    if match:
        expression = variable_expression(
            match.group(1)
        )

        if context == "slash":
            return [
                f"    await interaction.response.send_message({expression})"
            ]

        return [
            f"    await message.channel.send({expression})"
        ]

    # print(...)
    match = re.fullmatch(
        r'print\((.*)\)\s*;?',
        statement,
        re.DOTALL
    )

    if match:
        expression = variable_expression(
            match.group(1)
        )

        return [
            f"    print({expression})"
        ]

    raise MiteError(
        f"unknown command statement: {statement}"
    )


# ============================================================
# READ MITE FILE
# ============================================================

def compile_mite(filename):
    global bot_token
    global bot_prefix
    global discord_used

    if not os.path.exists(filename):
        raise MiteError(
            f"file '{filename}' was not found"
        )

    with open(
        filename,
        "r",
        encoding="utf-8"
    ) as file:
        lines = file.readlines()

    i = 0

    while i < len(lines):

        line = lines[i].strip()

        if not line or line.startswith("#"):
            i += 1
            continue

        # ----------------------------------------------------
        # import discord
        # ----------------------------------------------------

        if line == "import discord":
            discord_used = True
            i += 1
            continue

        # ----------------------------------------------------
        # bot.prefix(...)
        # ----------------------------------------------------

        match = re.fullmatch(
            r'bot\.prefix\((.*)\)\s*;?',
            line
        )

        if match:
            bot_prefix = translate_value(
                match.group(1)
            )

            i += 1
            continue

        # ----------------------------------------------------
        # bot.token(...)
        # ----------------------------------------------------

        match = re.fullmatch(
            r'bot\.token\((.*)\)\s*;?',
            line
        )

        if match:
            bot_token = translate_value(
                match.group(1)
            )

            i += 1
            continue

        # ----------------------------------------------------
        # bot.command("name") {
        # Prefix command
        # ----------------------------------------------------

        match = re.fullmatch(
            r'bot\.command\("([^"]+)"\)\s*\{',
            line
        )

        if match:

            command_name = match.group(1).lower()

            body = []

            i += 1

            while i < len(lines):

                body_line = lines[i].strip()

                if body_line == "}":
                    break

                if body_line:
                    body.append(body_line)

                i += 1

            if i >= len(lines):
                raise MiteError(
                    f"prefix command '{command_name}' "
                    f"is missing }}"
                )

            prefix_commands[command_name] = body

            i += 1
            continue

        # ----------------------------------------------------
        # bot.slash("name") {
        # Slash command
        # ----------------------------------------------------

        match = re.fullmatch(
            r'bot\.slash\("([^"]+)"\)\s*\{',
            line
        )

        if match:

            command_name = match.group(1).lower()

            body = []

            i += 1

            while i < len(lines):

                body_line = lines[i].strip()

                if body_line == "}":
                    break

                if body_line:
                    body.append(body_line)

                i += 1

            if i >= len(lines):
                raise MiteError(
                    f"slash command '{command_name}' "
                    f"is missing }}"
                )

            slash_commands[command_name] = body

            i += 1
            continue

        # ----------------------------------------------------
        # bot.login()
        # ----------------------------------------------------

        if re.fullmatch(
            r'bot\.login\(\)\s*;?',
            line
        ):
            i += 1
            continue

        # ----------------------------------------------------
        # Variable
        # ----------------------------------------------------

        match = re.fullmatch(
            r'([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.+)',
            line
        )

        if match:

            name = match.group(1)
            value = match.group(2)

            variables[name] = translate_value(value)

            i += 1
            continue

        # ----------------------------------------------------
        # print()
        # ----------------------------------------------------

        match = re.fullmatch(
            r'print\((.*)\)\s*;?',
            line,
            re.DOTALL
        )

        if match:

            expression = variable_expression(
                match.group(1)
            )

            variables.setdefault(
                "__prints__",
                []
            )

            variables[
                "__prints__"
            ].append(expression)

            i += 1
            continue

        raise MiteError(
            f"line {i + 1}: unknown statement: {line}"
        )


# ============================================================
# PYTHON GENERATOR
# ============================================================

def generate_python():

    if discord_used and bot_token is None:
        raise MiteError(
            "bot.token(...) is required"
        )

    python = []

    python.append("# Generated by Mite")
    python.append("# Do not edit this file.")
    python.append("")
    python.append("import os")
    python.append("")

    # --------------------------------------------------------
    # Variables
    # --------------------------------------------------------

    for name, value in variables.items():

        if name == "__prints__":
            continue

        python.append(
            f"{name} = {value}"
        )

    python.append("")

    # --------------------------------------------------------
    # Prints
    # --------------------------------------------------------

    if "__prints__" in variables:

        for expression in variables["__prints__"]:
            python.append(
                f"print({expression})"
            )

        python.append("")

    if not discord_used:
        return "\n".join(python)

    # --------------------------------------------------------
    # Discord imports
    # --------------------------------------------------------

    python.append("import logging")
    python.append("import discord")
    python.append("from discord import app_commands")
    python.append("")

    # Hide discord.py logs.
    python.append(
        'logging.getLogger("discord").setLevel(logging.CRITICAL)'
    )

    python.append("")

    python.append(
        f"PREFIX = {bot_prefix}"
    )

    python.append(
        f"TOKEN = {bot_token}"
    )

    python.append("")

    # --------------------------------------------------------
    # Discord client
    # --------------------------------------------------------

    python.append(
        "intents = discord.Intents.default()"
    )

    python.append(
        "intents.message_content = True"
    )

    python.append("")

    python.append(
        "client = discord.Client(intents=intents)"
    )

    python.append(
        "tree = app_commands.CommandTree(client)"
    )

    python.append("")

    # --------------------------------------------------------
    # Prefix commands
    # --------------------------------------------------------

    python.append("PREFIX_COMMANDS = {}")
    python.append("")

    for command_name, body in prefix_commands.items():

        safe_name = re.sub(
            r'[^A-Za-z0-9_]',
            '_',
            command_name
        )

        python.append(
            f"async def mite_prefix_{safe_name}(message, args):"
        )

        if not body:
            python.append("    pass")
        else:
            for statement in body:
                python.extend(
                    compile_statement(
                        statement,
                        "prefix"
                    )
                )

        python.append("")

        python.append(
            f'PREFIX_COMMANDS["{escape_python_string(command_name)}"] = mite_prefix_{safe_name}'
        )

        python.append("")

    # --------------------------------------------------------
    # Slash commands
    # --------------------------------------------------------

    for command_name, body in slash_commands.items():

        safe_name = re.sub(
            r'[^A-Za-z0-9_]',
            '_',
            command_name
        )

        python.append(
            "@tree.command("
            f'name="{escape_python_string(command_name)}"'
            ")"
        )

        python.append(
            f"async def mite_slash_{safe_name}(interaction: discord.Interaction):"
        )

        if not body:
            python.append("    pass")
        else:
            for statement in body:
                python.extend(
                    compile_statement(
                        statement,
                        "slash"
                    )
                )

        python.append("")

    # --------------------------------------------------------
    # Ready event
    # --------------------------------------------------------

    python.append("@client.event")
    python.append("async def on_ready():")

    python.append(
        '    print("Mite")'
    )

    python.append(
        '    print("------------------------------")'
    )

    python.append(
        '    print("Runtime     : Discord")'
    )

    python.append(
        '    print("Bot         : " + str(client.user))'
    )

    python.append(
        '    print("Status      : Online")'
    )

    python.append(
        '    print("Prefix      : " + PREFIX)'
    )

    python.append(
        '    print("Prefix cmds : " + str(len(PREFIX_COMMANDS)))'
    )

    python.append(
        '    print("Slash cmds  : " + str(len(tree.get_commands())))'
    )

    python.append(
        '    print("------------------------------")'
    )

    python.append(
        '    print("Mite is ready.")'
    )

    python.append("")

    # --------------------------------------------------------
    # Sync slash commands
    # --------------------------------------------------------

    python.append("@client.event")
    python.append("async def setup_hook():")

    python.append(
        "    await tree.sync()"
    )

    python.append("")

    # --------------------------------------------------------
    # Prefix message handler
    # --------------------------------------------------------

    python.append("@client.event")
    python.append("async def on_message(message):")

    python.append(
        "    if message.author == client.user:"
    )

    python.append(
        "        return"
    )

    python.append("")

    python.append(
        "    if not message.content.startswith(PREFIX):"
    )

    python.append(
        "        return"
    )

    python.append("")

    python.append(
        "    content = message.content[len(PREFIX):].strip()"
    )

    python.append("")

    python.append(
        "    if not content:"
    )

    python.append(
        "        return"
    )

    python.append("")

    python.append(
        "    pieces = content.split()"
    )

    python.append(
        "    command_name = pieces[0].lower()"
    )

    python.append(
        "    args = pieces[1:]"
    )

    python.append("")

    python.append(
        "    if command_name not in PREFIX_COMMANDS:"
    )

    python.append(
        "        return"
    )

    python.append("")

    python.append(
        "    await PREFIX_COMMANDS[command_name](message, args)"
    )

    python.append("")

    # --------------------------------------------------------
    # Start
    # --------------------------------------------------------

    python.append(
        "client.run(TOKEN)"
    )

    return "\n".join(python)


# ============================================================
# MAIN
# ============================================================

def main():

    if len(sys.argv) != 2:

        print("Mite Programming Language")
        print("Usage: python3 mite.py main.llt")

        sys.exit(1)

    source_file = sys.argv[1]

    try:

        print("Mite")
        print("Reading:", source_file)

        compile_mite(source_file)

        # ----------------------------------------------------
        # Create runner
        # ----------------------------------------------------

        base_directory = os.path.dirname(
            os.path.abspath(source_file)
        )

        runner = os.path.join(
            base_directory,
            "runner"
        )

        if os.path.exists(runner):
            shutil.rmtree(runner)

        os.makedirs(runner)

        print("Created runner/")

        # ----------------------------------------------------
        # Generate Python
        # ----------------------------------------------------

        output_file = os.path.join(
            runner,
            "main.py"
        )

        generated = generate_python()

        with open(
            output_file,
            "w",
            encoding="utf-8"
        ) as file:
            file.write(generated)

        print("Generated runner/main.py")
        print("Starting Mite program...")

        # ----------------------------------------------------
        # Run
        # ----------------------------------------------------

        result = subprocess.run(
            [
                sys.executable,
                output_file
            ]
        )

        sys.exit(result.returncode)

    except MiteError as error:

        print(
            f"MiteError: {error}"
        )

        sys.exit(1)


if __name__ == "__main__":
    main()
