import sys
import os
import re

try:
    import discord
except ImportError:
    discord = None


class MiteError(Exception):
    pass


variables = {}
bot = None
bot_token = None


def parse_value(value):
    value = value.strip()

    # String
    if len(value) >= 2 and value[0] == '"' and value[-1] == '"':
        return value[1:-1]

    # Boolean
    if value == "true":
        return True

    if value == "false":
        return False

    # Integer
    if re.fullmatch(r"-?\d+", value):
        return int(value)

    # Float
    if re.fullmatch(r"-?\d+\.\d+", value):
        return float(value)

    # List
    if value.startswith("[") and value.endswith("]"):
        inside = value[1:-1].strip()

        if not inside:
            return []

        parts = []
        current = ""
        quoted = False

        for char in inside:
            if char == '"':
                quoted = not quoted

            if char == "," and not quoted:
                parts.append(current.strip())
                current = ""
            else:
                current += char

        parts.append(current.strip())

        return [parse_value(x) for x in parts]

    # Environment variable
    env_match = re.fullmatch(
        r'import\.env\("([^"]+)"\s*;?\)',
        value
    )

    if env_match:
        name = env_match.group(1)
        result = os.getenv(name)

        if result is None:
            raise MiteError(
                f"environment variable '{name}' was not found"
            )

        return result

    # Import file
    import_match = re.fullmatch(
        r'import\("([^"]+)"\s*;?\)',
        value
    )

    if import_match:
        return load_import(import_match.group(1))

    return value


def load_import(filename):
    if not os.path.exists(filename):
        raise MiteError(f"file '{filename}' was not found")

    imported = {}

    with open(filename, "r", encoding="utf-8") as file:
        for line in file:
            line = line.strip()

            if not line or line.startswith("#"):
                continue

            if "=" not in line:
                continue

            name, value = line.split("=", 1)

            imported[name.strip()] = parse_value(value)

    return imported


def resolve(value):
    value = value.strip()

    # Variable lookup:
    # NAME;
    match = re.fullmatch(
        r"([A-Za-z_][A-Za-z0-9_]*)\s*;",
        value
    )

    if match:
        name = match.group(1)

        if name not in variables:
            raise MiteError(
                f"variable '{name}' was not found"
            )

        return variables[name]

    return parse_value(value)


def split_arguments(text):
    arguments = []
    current = ""
    quoted = False
    brackets = 0

    for char in text:

        if char == '"':
            quoted = not quoted

        if not quoted:

            if char in "[(":
                brackets += 1

            elif char in "])":
                brackets -= 1

            if char == "," and brackets == 0:
                arguments.append(current.strip())
                current = ""
                continue

        current += char

    if current.strip():
        arguments.append(current.strip())

    return arguments


# -----------------------------
# DISCORD
# -----------------------------

def discord_create():
    global bot

    if discord is None:
        raise MiteError(
            "discord.py is not installed. "
            "Install it with: pip install discord.py"
        )

    intents = discord.Intents.default()
    intents.message_content = True

    bot = discord.Client(intents=intents)

    @bot.event
    async def on_ready():
        print(
            f"Mite Discord bot logged in as "
            f"{bot.user}"
        )

    @bot.event
    async def on_message(message):

        if message.author == bot.user:
            return

        if message.content == "!mite":
            await message.channel.send(
                "Hello from Mite!"
            )


def discord_login(token):
    global bot

    if discord is None:
        raise MiteError(
            "discord.py is not installed."
        )

    if bot is None:
        discord_create()

    if not token:
        raise MiteError(
            "Discord token is empty."
        )

    print("Starting Discord bot...")

    bot.run(token)


# -----------------------------
# FUNCTIONS
# -----------------------------

def execute_function(line):

    global bot_token

    # print(...)
    match = re.fullmatch(
        r"print\((.*)\)",
        line
    )

    if match:

        args = split_arguments(match.group(1))

        values = []

        for arg in args:
            values.append(resolve(arg))

        print(*values)

        return True

    # bot.token(...)
    match = re.fullmatch(
        r"bot\.token\((.*)\)",
        line
    )

    if match:

        bot_token = resolve(
            match.group(1)
        )

        return True

    # bot.login()
    match = re.fullmatch(
        r"bot\.login\(\)",
        line
    )

    if match:

        if bot_token is None:
            raise MiteError(
                "bot.token(...) must be called first"
            )

        discord_login(bot_token)

        return True

    # bot.login(TOKEN;)
    match = re.fullmatch(
        r"bot\.login\((.*)\)",
        line
    )

    if match:

        token = resolve(
            match.group(1)
        )

        discord_login(token)

        return True

    return False


def execute_line(line):

    line = line.strip()

    if not line:
        return

    if line.startswith("#"):
        return

    # Function
    if execute_function(line):
        return

    # Variable assignment
    match = re.fullmatch(
        r"([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.+)",
        line
    )

    if match:

        name = match.group(1)
        value = match.group(2)

        result = parse_value(value)

        # import(...) can return a dictionary
        if isinstance(result, dict):
            variables.update(result)

        else:
            variables[name] = result

        return

    raise MiteError(
        f"unknown statement: {line}"
    )


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

        for line_number, line in enumerate(
            file,
            1
        ):

            try:
                execute_line(line)

            except MiteError as error:

                raise MiteError(
                    f"{filename}:{line_number}: {error}"
                )


def main():

    if len(sys.argv) != 2:

        print(
            "Mite Programming Language"
        )

        print(
            "Usage: python3 mite.py <file.llt>"
        )

        sys.exit(1)

    try:

        run_file(
            sys.argv[1]
        )

    except MiteError as error:

        print(
            f"MiteError: {error}"
        )

        sys.exit(1)


if __name__ == "__main__":
    main()
