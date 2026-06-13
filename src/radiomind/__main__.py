"""Enable `python -m radiomind ...` as an alias for the `radiomind` CLI.

CLIProductSmoke-1b (F5): users reach for `python -m radiomind` by reflex
when the console script isn't on PATH; without this the failure was an
opaque "No module named radiomind.__main__". Delegate to the same Click
entry point as the installed script.
"""
from radiomind.cli.main import cli

if __name__ == "__main__":
    cli()
