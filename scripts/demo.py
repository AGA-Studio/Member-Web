"""Deterministic demo-data helpers shared by the seed and the simulator.

Both scripts write the same kind of rows, so the fixed card-code generator lives
here: `services.customer_service.generate_code` uses `secrets` and would give a
different dataset on every fresh run, while the demo cards are printed and
carried by QR, so they must come out the same.
"""

import hashlib

from services.customer_service import CODE_ALPHABET, CODE_LENGTH, CODE_PREFIX


def demo_code(namespace: str, index: int) -> str:
    """Card code of a generated customer, in the contract's format.

    `docs/REVISION.md` (Numeración) fixes it: `MP-` plus five characters from the
    alphabet without `0/O/1/I/L`, and **not sequential**. Hashing the fixed
    inputs keeps the dataset reproducible without looking correlative. The
    namespace (`seed:sol`, `simulate:aurora`) keeps generated customers apart.
    """
    digest = hashlib.sha256(f"{namespace}:{index}".encode()).digest()
    tail = "".join(CODE_ALPHABET[byte % len(CODE_ALPHABET)] for byte in digest[:CODE_LENGTH])
    return f"{CODE_PREFIX}{tail}"
