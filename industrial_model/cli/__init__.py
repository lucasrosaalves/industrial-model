from collections.abc import Sequence


def main(argv: Sequence[str] | None = None) -> int:
    try:
        from .main import main as _main
    except ImportError as exc:
        if exc.name == "typer":
            print(
                "The generator CLI requires optional dependencies. "
                "Install them with: pip install 'industrial-model[cli]'"
            )
            return 1
        raise

    return _main(argv)


__all__ = ["main"]
