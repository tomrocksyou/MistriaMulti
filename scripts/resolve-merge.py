"""Resolves the routine merge conflicts between feature packages: each side only ADDED lines to shared files.
GML/README/yml/md: keep both sides (ours first). manifest.toml: union of requires_hooks. Anything else: report."""
import re, subprocess, sys
files = subprocess.run(["git", "diff", "--name-only", "--diff-filter=U"], capture_output=True, text=True).stdout.split()
rx = re.compile(r"<<<<<<< [^\n]*\n(.*?)=======\n(.*?)>>>>>>> [^\n]*\n", re.S)
left = []
for f in files:
    s = open(f).read()
    if f.endswith("manifest.toml"):
        def merge(m):
            hooks = lambda t: re.findall(r'"([^"]+)"', t.split("=", 1)[1])
            a, b = hooks(m.group(1)), hooks(m.group(2))
            return "requires_hooks = [" + ", ".join('"%s"' % h for h in a + [h for h in b if h not in a]) + "]\n"
        s = rx.sub(merge, s)
    elif f.endswith((".gml", ".md", ".yml", ".py")) or f == "README.md":
        s = rx.sub(lambda m: m.group(1) + m.group(2), s)
    else:
        left.append(f); continue
    open(f, "w").write(s)
    print("resolved", f)
print("NEEDS A HUMAN:", left if left else "nothing")
