"""Deterministic attester stub: checks that a receipt's executed_sql equals the
sanctioned computation bound with the claimed parameters.

This file is intentionally NOT markdown: the validator must ignore non-.md
files (they are not concept documents, SPEC §3.1) and must NOT require
frontmatter on them (SPEC §11 rule 1 applies to .md files only).
"""


def attest(receipt: dict, computation: str, parameters: dict) -> bool:
    bound = computation
    for name, value in parameters.items():
        bound = bound.replace("@" + name, str(value))
    return receipt.get("executed_sql") == bound
