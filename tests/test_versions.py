"""The mod's version appears in three places; they must agree (a forgotten one shows the wrong version on screen)."""
import re
from pathlib import Path

root = Path(__file__).resolve().parent.parent
manifest = re.search(r'^version = "([^"]+)"', (root / "mod/mistrimulti/manifest.toml").read_text(), re.M).group(1)
boot = re.search(r'mmapi_mod_declare\("mistrimulti", "([^"]+)"\)', (root / "mod/mistrimulti/gml/MistriMultiBoot.gml").read_text()).group(1)
ui = re.search(r'function mistrimulti_mod_version\(\) \{ return "([^"]+)"; \}', (root / "mod/mistrimulti/gml/MistriMultiUpdateUI.gml").read_text()).group(1)
release = (root / "release/latest.txt").read_text().splitlines()[0].split()[1]
assert manifest == boot == ui == release, (manifest, boot, ui, release)
print("PASS: the mod version is the same everywhere:", manifest)
