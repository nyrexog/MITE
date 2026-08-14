import sys
import os
import re
import asyncio

try:
    import discord
except ImportError:
    discord = None


class MiteError(Exception):
    pass


variables = {}
commands = {}

bot_token = None
bot_prefix = "!"

discord_bot = None
current_message = None


# ============================================================
# VALUE PARSER
# ============================================================

def parse_value(value):
    value = value.strip()

    # String
    if len(value) >= 2 and value[0] == '"' and value[-1] == '"':
        return value[1:-1]

    # Integer
    if re.fullmatch(r"-?\d+", value):
        return int(value)

    # Float
    if re.fullmatch(r"-?\d+\.\d+", value):
        return float(value)

    # Boolean
    if value == "true":
        return True

    if value == "false":
        return False

    # Environment variable
    match = re.fullmatch(
        r'import\.env\("([^"]+)"\s*;?\)',
        value
    )

    if match:
        env_name = match.group(1)
        result = os.getenv(env_name)

        if result is None:
            raise MiteError(
                f"environment variable '{env_name}' was not found"
            )

        return result

    # Variable lookup
    match = re.fullmatch(
        r'([A-Za-z_][A-Za-z0-9_]*)\s*;',
        value
    )

    if match:
        name = match.group(1)

        if name not in variables:
            raise MiteError(
                f"variable '{name}' was not found"
            )

        return variables[name]

    # List
    if value.startswith("[") and value.endswith("]"):
        inside = value[1:-1].strip()

        if not inside:
            return []

        parts = split_arguments(inside)

        return [parse_value(part) for part in parts]

    return value


# ============================================================
# EXPRESSION / REPLY PARSER
# ============================================================

def evaluate_expression(expression):
    expression = expression.strip()

    parts = []
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

        # Variable reference: NAME;
        if not quoted:
            match = re.match(
                r'([A-Za-z_][A-Za-z0-9_]*)\s*;',
                expression[i:]
            )

            if match:
                if current.strip():
                    parts.append(current.strip())

                name = match.group(1)

                if name not in variables:
                    raise MiteError(
                        f"variable '{name}' was not found"
                    )

                parts.append(str(variables[name]))

                i += match.end()
                current = ""
                continue

        current += char
        i += 1

    if current.strip():
        parts.append(current.strip())

    result = ""

    for part in parts:
        part = part.strip()

        if (
            len(part) >= 2
            and part[0] == '"'
            and part[-1] == '"'
        ):
            result += part[1:-1]
        else:
            result += part

    return result


def split_arguments(text):
    result = []
    current = ""
    quoted = False
    brackets = 0

    for char in text:

        if char == '"':
            quoted = not quoted

        if not quoted:

            if char in "([{":
                brackets += 1

            elif char in ")]}":
                brackets -= 1

            if char == "," and brackets == 0:
                result.append(current.strip())
                current = ""
                continue

        current += char

    if current.strip():
        result.append(current.strip())

    return result


# ============================================================
# DISCORD
# ============================================================

def setup_discord():

    global discord_bot

    if discord is None:
        raise MiteError(
            "discord.py is not installed. "
            "Run: pip install -U discord.py"
        )

    intents = discord.Intents.default()

    # Needed for reading message content.
    intents.message_content = True

    discord_bot = discord.Client(
        intents=intents
    )

    @discord_bot.event
    async def on_ready():

        print(
            f"Mite Discord bot online as "
            f"{discord_bot.user}"
        )

    @discord_bot.event
    async def on_message(message):

        global current_message

        if message.author == discord_bot.user:
            return

        if not message.content.startswith(bot_prefix):
            return

        content = message.content[
            len(bot_prefix):
        ].strip()

        if not content:
            return

        pieces = content.split()

        command_name = pieces[0].lower()

        args = pieces[1:]

        if command_name not in commands:
            return

        current_message = message

        try:

            await execute_command(
                command_name,
                args
            )

        except Exception as error:

            print(
                f"Mite command error: {error}"
            )

        finally:

            current_message = None


async def execute_command(name, args):

    body = commands[name]

    for statement in body:

        await execute_statement(
            statement,
            args
        )


async def execute_statement(statement, args):

    statement = statement.strip()

    if not statement:
        return

    # bot.reply(...)
    match = re.fullmatch(
        r'bot\.reply\((.*)\)\s*;?',
        statement,
        re.DOTALL
    )

    if match:

        expression = match.group(1)

        text = evaluate_expression(
            expression
        )

        if current_message is not None:

            await current_message.channel.send(
                text
            )

        return

    # print(...)
    match = re.fullmatch(
        r'print\((.*)\)\s*;?',
        statement,
        re.DOTALL
    )

    if match:

        expression = match.group(1)

        print(
            evaluate_expression(expression)
        )

        return

    raise MiteError(
        f"unknown command statement: {statement}"
    )


# ============================================================
# MITE STATEMENTS
# ============================================================

def execute_normal_line(line):

    line = line.strip()

    if not line:
        return

    if line.startswith("#"):
        return

    # import discord
    if line == "import discord":
        setup_discord()
        return

    # print(...)
    match = re.fullmatch(
        r'print\((.*)\)\s*;?',
        line
    )

    if match:

        print(
            evaluate_expression(
                match.group(1)
            )
        )

        return

    # bot.token(...)
    match = re.fullmatch(
        r'bot\.token\((.*)\)\s*;?',
        line
    )

    if match:

        global bot_token

        bot_token = parse_value(
            match.group(1)
        )

        return

    # bot.prefix(...)
    match = re.fullmatch(
        r'bot\.prefix\((.*)\)\s*;?',
        line
    )

    if match:

        global bot_prefix

        bot_prefix = parse_value(
            match.group(1)
        )

        return

    # bot.login()
    if re.fullmatch(
        r'bot\.login\(\)\s*;?',
        line
    ):

        if discord_bot is None:
            setup_discord()

        if not bot_token:
            raise MiteError(
                "bot.token(...) must be called before bot.login()"
            )

        discord_bot.run(
            bot_token
        )

        return

    # Variable assignment
    match = re.fullmatch(
        r'([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.+)',
        line
    )

    if match:

        name = match.group(1)
        value = match.group(2).strip()

        variables[name] = parse_value(
            value
        )

        return

    raise MiteError(
        f"unknown statement: {line}"
    )


# ============================================================
# FILE PARSER
# ============================================================

def run_file(filename):

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
        # bot.command("name") {
        # ----------------------------------------------------

        command_match = re.fullmatch(
            r'bot\.command\("([^"]+)"\)\s*\{',
            line
        )

        if command_match:

            command_name = (
                command_match.group(1).lower()
            )

            body = []

            i += 1

            while i < len(lines):

                current = lines[i].strip()

                if current == "}":
                    break

                if current:
                    body.append(current)

                i += 1

            if i >= len(lines):
                raise MiteError(
                    f"command '{command_name}' "
                    f"has no closing }}"
                )

            commands[command_name] = body

            i += 1
            continue

        execute_normal_line(line)

        i += 1


# ============================================================
# MAIN
# ============================================================

def main():

    if len(sys.argv) != 2:

        print(
            "Mite Programming Language"
        )

        print(
            "Usage: python3 mite.py <file.llt>"
        )

        sys.exit(1)

    filename = sys.argv[1]

    try:

        run_file(filename)

    except MiteError as error:

        print(
            f"MiteError: {error}"
        )

        sys.exit(1)


if __name__ == "__main__":
    main()
