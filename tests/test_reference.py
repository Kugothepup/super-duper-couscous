"""The reference scripts must stay exactly as the skill had them (D7)."""
import hashlib
from pathlib import Path

REFERENCE = Path(__file__).parent / "reference"


def test_reference_scripts_are_unchanged():
    listed = {}
    for line in (REFERENCE / "SHA256SUMS").read_text().splitlines():
        digest, name = line.split(maxsplit=1)
        listed[name] = digest
    scripts = {p.name for p in REFERENCE.iterdir() if p.suffix in (".py", ".js")}
    assert scripts == set(listed)
    for name, digest in listed.items():
        assert hashlib.sha256((REFERENCE / name).read_bytes()).hexdigest() == digest, name
