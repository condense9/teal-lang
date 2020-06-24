"""Top-level utilities for loading Teal code"""
import sys
from pathlib import Path

from .machine.executable import Executable
from .teal_compiler import tl_compile
from .teal_parser.parser import tl_parse, TealSyntaxError, token_column
from .cli.interface import bad, neutral


def compile_text(text: str) -> Executable:
    "Parse and compile a Teal program"
    return tl_compile(tl_parse(text))


def error_msg(text, exc, filename) -> str:
    """Get an error message explaining why compilation failed"""
    msg = bad(f"{filename}:{exc.token.lineno} ~ {exc.msg}")
    line = text.split("\n")[exc.token.lineno - 1]
    msg += neutral(f"\n\n {line}\n")
    msg += " " * (token_column(text, exc.token.index) - 1) + "^"
    return msg


def compile_file(filename: Path) -> Executable:
    "Compile a Teal file, creating an Executable ready to be used"
    with open(filename, "r") as f:
        text = f.read()

    try:
        return compile_text(text)
    except TealSyntaxError as exc:
        print(error_msg(text, exc, filename))
        sys.exit(1)


if __name__ == "__main__":
    import sys
    import pprint

    with open(sys.argv[1], "r") as f:
        text = f.read()

    debug = len(sys.argv) > 2 and sys.argv[2] == "-d"
    exe = tl_compile(tl_parse(text, debug_lex=debug))

    print(exe.listing())
