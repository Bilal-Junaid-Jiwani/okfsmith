# okfsmith.core — API contract

Core is the foundation every other slice builds on. **Rules:** no network
calls, stdlib + declared dependencies only, never reject a document for
unknown frontmatter keys (OKF v0.2 §11).

```python
from okfsmith.core import Bundle, Concept, frontmatter, indexlog, spec
```

## `okfsmith.core.spec` — OKF v0.2 constants

```python
spec.RESERVED_FILES            # {"index.md", "log.md"} — never concept documents
spec.REQUIRED_KEY              # "type" — the only always-required frontmatter key
spec.VALID_STATUSES            # frozenset({"draft", "stable", "deprecated"})
spec.OKF_VERSION               # "0.2" — stamp for the root index.md frontmatter
spec.UNVERIFIED / spec.MACHINE_CONFIRMED / spec.HUMAN_REVIEWED
spec.HUMAN_PREFIX              # "human:"

spec.trust_tier(frontmatter) -> str
# Derives "unverified" | "machine-confirmed" | "human-reviewed" from the
# `verified` key (§5.3). A bare mapping counts as a one-element list (§5.2);
# any `human:<id>` actor in `verified[].by` → "human-reviewed".

spec.is_human_actor(actor: str) -> bool   # True iff actor starts with "human:"
spec.actor_name(actor: str) -> str        # "human:ada" -> "ada"; bare names unchanged
spec.utc_now_iso() -> str                # ISO-8601 now, UTC, explicit offset (+00:00)
spec.today_iso() -> str                  # today as "YYYY-MM-DD" (log.md headings)
```

## `okfsmith.core.frontmatter` — parse / serialize

```python
frontmatter.parse_frontmatter(text: str) -> tuple[dict, str]
# Splits a document into (frontmatter, body). Never raises on weird input:
# missing delimiters or non-mapping YAML -> ({}, text). Unknown keys preserved.

frontmatter.serialize_frontmatter(frontmatter: dict, body: str = "") -> str
# Serializes back to `---`-delimited YAML + body. Round-trip safe:
# parse_frontmatter(serialize_frontmatter(fm, body)) == (fm, body).
# Key insertion order is preserved (sort_keys=False).
```

## `okfsmith.core.bundle` — Bundle / Concept

```python
@dataclass
class Concept:
    id: str          # "finance/revenue" — rel path minus .md, forward slashes
    path: Path       # absolute on-disk path of the .md file
    frontmatter: dict
    body: str

class Bundle:
    def __init__(self, root: str | Path) -> None: ...
    # Creates a handle; reads nothing. `index_text` / `log_text` hold the raw
    # root index.md / log.md text once loaded or generated (None if absent).

    @classmethod
    def load(cls, root: str | Path) -> Bundle: ...
    # Walks root, parsing every *.md into Concepts. index.md/log.md are
    # skipped as concepts (at any depth); root copies feed index_text/log_text.

    def write_concept(self, concept_id: str, frontmatter: dict, body: str) -> Concept: ...
    # Slugifies concept_id segment-by-segment -> path (e.g. "Notes/Hello World"
    # -> "notes/hello-world.md"), creates parent dirs, writes the file, and
    # registers it. Returned Concept.id is the slugified id.

    def iter_concepts(self) -> Iterator[Concept]: ...
    # All concepts, sorted by id (deterministic).

    def get(self, concept_id: str) -> Concept | None: ...
    # Lookup by id; None when absent.

bundle.slugify(value: str) -> str
bundle.concept_path_for(root: Path, concept_id: str) -> Path
```

## `okfsmith.core.indexlog` — index.md / log.md

```python
indexlog.LOG_KINDS  # frozenset({"Creation", "Update", "Deprecation"})

indexlog.ensure_index(bundle: Bundle, subdir: str = "") -> Path
# Generates/refreshes index.md for subdir ("" = root). Entries look like:
#   * [Title](path) - description        (description omitted when absent)
# Links are forward-slash, relative to the index, WITHOUT the .md suffix.
# Root index lists every concept recursively; subdir indexes list their subtree.
# Only the ROOT index carries frontmatter: exactly `okf_version: "0.2"`.

indexlog.append_log(bundle: Bundle, subdir: str = "", kind: str = "Update",
                    message: str = "") -> Path
# Appends `* **Kind**: message` under a `## YYYY-MM-DD` heading (UTC), newest
# first — a missing today-heading is created at the top of the file.
# Raises ValueError for a kind outside LOG_KINDS.
```

## Versioning

`okfsmith.__version__` is the single source of truth (`"0.1.0"`);
`pyproject.toml` carries the same version for packaging.
