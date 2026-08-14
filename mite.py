import sys
import os
import re


class MiteError(Exception):
    pass


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

    # Number
    if re.fullmatch(r"-?\d+", value):
        return int(value)

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

    # Import
    match = re.fullmatch(r'import\("([^"]+)"\s*;?\)', value)

    if match:
        filename = match.group(1)
        return load_import(filename)

    return value


def load_import(filename):
    if not os.path.exists(filename):
        raise MiteError(f"file '{filename}' was not found")

    variables = {}

    with open(filename, "r", encoding="utf-8") as file:
        for line in file:
            line = line.strip()

            if not line or line.startswith("#"):
                continue

            if "=" not in line:
                continue

            name, value = line.split("=", 1)
            name = name.strip()
            value = value.strip()

            variables[name] = parse_value(value)

    return variables


def resolve(value, variables):
    value = value.strip()

    # NAME;
    match = re.fullmatch(r"([A-Za-z_][A-Za-z0-9_]*)\s*;", value)

    if match:
        name = match.group(1)

        if name not in variables:
            raise MiteError(f"variable '{name}' was not found")

        return variables[name]

    # Normal value
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


def execute_line(line, variables):
    line = line.strip()

    if not line or line.startswith("#"):
        return

    # Variable assignment
    assignment = re.fullmatch(
        r"([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.+)",
        line
    )

    if assignment:
        name = assignment.group(1)
        value = assignment.group(2)

        variables[name] = resolve(value, variables)
        return

    # print(...)
    match = re.fullmatch(r"print\((.*)\)", line)

    if match:
        args = split_arguments(match.group(1))

        values = []

        for arg in args:
            arg = arg.strip()

            if arg.endswith(";"):
                values.append(resolve(arg, variables))
            else:
                values.append(parse_value(arg))

        print(*values)
        return

    raise MiteError(f"unknown statement: {line}")


def run_file(filename):
    if not os.path.exists(filename):
        raise MiteError(f"file '{filename}' was not found")

    variables = {}

    with open(filename, "r", encoding="utf-8") as file:
        for line_number, line in enumerate(file, 1):
            try:
                execute_line(line, variables)
            except MiteError as error:
                raise MiteError(
                    f"{filename}:{line_number}: {error}"
                )


def main():
    if len(sys.argv) != 2:
        print("Mite")
        print("Usage: mite.py <file.llt>")
        sys.exit(1)

    try:
        run_file(sys.argv[1])
    except MiteError as error:
        print(f"MiteError: {error}")
        sys.exit(1)


if __name__ == "__main__":
    main()