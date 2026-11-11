"""The CI workflows keep their hardening (.github/workflows/*.yml), read as text (standard library only):

- every action is pinned by its full commit (owner/repo@<40 hex>), or is a workflow of this repository (./);
- every workflow sets its token's permissions at the top;
- every checkout leaves no token behind (persist-credentials: false), except the release record job's, which pushes;
- no ${{ ... }} of event data, inputs or other untrusted text inside a run: script (it is pasted into the script before
  bash reads it): such values go through env: and are quoted there;
- a pull_request_target workflow never checks out code (it runs with the base repository's token for forks' pull
  requests).

    python -I -B tests/test_workflow_hardening.py
"""
import re
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WORKFLOWS = ROOT / ".github" / "workflows"

# (what a run: script may expand with ${{ }}: runner paths and values the workflow itself sets)
RUN_SAFE = re.compile(r"^(runner\.(temp|os|arch)|github\.(workspace|run_id|run_number|run_attempt|sha)|env\.[A-Za-z_][A-Za-z0-9_]*)$")
# (checkouts that keep their token on purpose: file name -> how many)
PERSISTED = {"release.yml": 1}


def problems(path):
    text = path.read_text(encoding="utf-8")
    lines = text.splitlines()
    found = []
    if not re.search(r"^permissions:", text, re.M):
        found.append("%s: no top-level permissions:" % path.name)
    for n, line in enumerate(lines, 1):
        m = re.match(r"^\s*(?:-\s+)?uses:\s*(\S+)", line)
        if m and not m.group(1).startswith("./") and not re.fullmatch(r"[\w.-]+/[\w./-]+@[0-9a-f]{40}", m.group(1)):
            found.append("%s:%d: %s is not pinned by its full commit" % (path.name, n, m.group(1)))
    # checkouts: the step's lines, up to the next step
    persisted = 0
    for n, line in enumerate(lines, 1):
        if not re.match(r"^\s*(?:-\s+)?uses:\s*actions/checkout@", line):
            continue
        indent = len(line) - len(line.lstrip(" -"))
        step = []
        for later in lines[n:]:
            if later.strip() and (re.match(r"^\s*- ", later) and len(later) - len(later.lstrip(" ")) < indent or
                                  len(later) - len(later.lstrip(" ")) < indent - 2):
                break
            step.append(later)
        step = "\n".join(step)
        if re.search(r"persist-credentials:\s*true", step):
            persisted += 1
        elif not re.search(r"persist-credentials:\s*false", step):
            found.append("%s:%d: a checkout without persist-credentials: false" % (path.name, n))
    if persisted > PERSISTED.get(path.name, 0):
        found.append("%s: %d checkouts keep their token (persist-credentials: true)" % (path.name, persisted))
    # run: scripts
    i = 0
    while i < len(lines):
        m = re.match(r"^(\s*)(?:-\s+)?run:\s*(.*)$", lines[i])
        if m:
            indent, first = len(m.group(1)), m.group(2).strip()
            body = []
            if first in ("|", ">", "|-", ">-", "|+", ">+", ""):
                j = i + 1
                while j < len(lines) and (not lines[j].strip() or len(lines[j]) - len(lines[j].lstrip()) > indent):
                    body.append((j + 1, lines[j]))
                    j += 1
            else:
                body = [(i + 1, first)]
            for n, line in body:
                for expr in re.findall(r"\$\{\{(.*?)\}\}", line):
                    if not RUN_SAFE.match(expr.strip()):
                        found.append("%s:%d: ${{ %s }} inside a run: script (pass it through env:)" % (path.name, n, expr.strip()))
        i += 1
    if re.search(r"^\s*pull_request_target:", text, re.M) and re.search(r"uses:\s*actions/checkout@", text):
        found.append("%s: pull_request_target with a checkout" % path.name)
    return found


class WorkflowHardening(unittest.TestCase):
    def test_the_workflows(self):
        files = sorted(WORKFLOWS.glob("*.yml"))
        self.assertGreater(len(files), 3)
        found = [p for f in files for p in problems(f)]
        self.assertEqual(found, [], "\n".join(found))

    def test_dependabot_proposes_the_pinned_packages_after_a_cooldown(self):
        text = (ROOT / ".github" / "dependabot.yml").read_text(encoding="utf-8")
        entries = re.split(r"\n  - package-ecosystem: ", text)[1:]
        kinds = {e.split("\n", 1)[0].strip(): e for e in entries}
        self.assertIn("github-actions", kinds)
        self.assertIn("pip", kinds, "the pinned Python packages (requirements.txt) have no Dependabot entry")
        self.assertIn("/nx2", kinds["pip"], "nx2/prompt_requirements.txt is not watched")
        for kind, e in kinds.items():
            self.assertRegex(e, r"cooldown:\s*\n\s*default-days: [1-9]", kind + ": no cooldown")
        csproj = "".join(p.read_text(encoding="utf-8") for p in (ROOT / "builder").rglob("*.csproj"))
        if "<PackageReference" in csproj:
            self.assertIn("nuget", kinds, "the builder has NuGet packages and no Dependabot entry for them")

    def test_the_check_finds_each_kind(self):
        bad = """on:
  pull_request_target:
jobs:
  a:
    steps:
      - uses: actions/checkout@v4
        with:
          fetch-depth: 1
      - uses: someone/thing@main
      - name: x
        run: |
          echo "${{ github.event.pull_request.title }}"
          echo ${{ runner.temp }}
      - run: echo ${{ inputs.tag }}
"""
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "bad.yml"
            path.write_text(bad, encoding="utf-8")
            found = "\n".join(problems(path))
        for what in ("no top-level permissions", "someone/thing@main is not pinned", "actions/checkout@v4 is not pinned",
                     "without persist-credentials", "github.event.pull_request.title", "inputs.tag",
                     "pull_request_target with a checkout"):
            self.assertIn(what, found)
        self.assertNotIn("runner.temp", found)
        # (a step's persist-credentials is its own: the next checkout's does not count for it)
        pin = "a" * 40
        two = ("permissions: {}\njobs:\n  a:\n    steps:\n      - uses: actions/checkout@%s\n        with:\n"
               "          fetch-depth: 1\n      - name: next\n        uses: actions/checkout@%s\n        with:\n"
               "          persist-credentials: false\n" % (pin, pin))
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "two.yml"
            path.write_text(two, encoding="utf-8")
            self.assertEqual(problems(path), ["two.yml:5: a checkout without persist-credentials: false"])


if __name__ == "__main__":
    sys.exit(unittest.main())
