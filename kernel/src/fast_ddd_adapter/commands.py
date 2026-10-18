from typing import Final, final


@final
class Unset:
    """Marks a PATCH command field the client did not send (distinct from an explicit None)."""

    _instance: "Unset | None" = None

    def __new__(cls) -> "Unset":
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __repr__(self) -> str:
        return "UNSET"

    def __bool__(self) -> bool:
        return False


UNSET: Final = Unset()


def merge[T](patched: "T | Unset", current: T) -> T:
    return current if isinstance(patched, Unset) else patched
