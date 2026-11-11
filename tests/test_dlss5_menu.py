"""External settings stay in native Graphics, match the bridge, and never enter the game ini."""
import ast
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[1]


def main():
    menu = (ROOT / 'gpu/vk/vk_menu.cpp').read_text()
    header = (ROOT / 'gpu/vk/dlss5_controls.h').read_text()
    adapter = ast.parse((ROOT / 'scripts/dlss5_api.py').read_text())
    assignment = next(node for node in adapter.body if isinstance(node, ast.Assign)
                      and any(isinstance(target, ast.Name) and target.id == 'SETTINGS' for target in node.targets))
    expected = {ast.literal_eval(key): (int(ast.literal_eval(value.elts[0]) * (100 if value.elts[2].id == 'float' else 1)),
                                      int(ast.literal_eval(value.elts[1]) * (100 if value.elts[2].id == 'float' else 1)))
                for key, value in zip(assignment.value.keys, assignment.value.values)}
    specs = re.findall(r'\{"(\w+)",(-?\d+),(\d+),(true|false)\}', header)
    names = re.search(r'enum Setting \{(.*?)Count \}', header, re.S).group(1)
    names = [name.strip() for name in names.split(',') if name.strip()]
    assert len(specs) == len(names) == len(expected) == 19
    assert {key: (int(lo), int(hi)) for key, lo, hi, _ in specs} == expected
    defaults_assignment = next(node for node in adapter.body if isinstance(node, ast.Assign)
                               and any(isinstance(target, ast.Name) and target.id == 'DEFAULT_SETTINGS' for target in node.targets))
    python_defaults = ast.literal_eval(defaults_assignment.value)
    assert set(python_defaults) == set(expected)
    native_defaults = [int(value) for value in re.search(r'defaults\{\{(.*?)\}\}', header, re.S).group(1).split(',')]
    assert len(native_defaults) == len(specs)
    kinds = {ast.literal_eval(key): value.elts[2].id for key, value in zip(assignment.value.keys, assignment.value.values)}
    assert native_defaults == [round(python_defaults[key] * (100 if kinds[key] == 'float' else 1)) for key, *_ in specs]
    assert 'preferences = dict(DEFAULT_SETTINGS)' in (ROOT / 'scripts/dlss5_api.py').read_text()
    rows = re.findall(r'\{TAB_GRAPHICS, "[^"]+", &dlss5_control.values\[d5::(\w+)\], (-?\d+), (\d+),.*?nullptr, false, true\}', menu, re.S)
    assert len(rows) == 19, 'All settings must be native rows, without restart or native preset ownership'
    actual = {name: (int(lo), int(hi)) for name, lo, hi in rows}
    assert actual == {name: (int(spec[1]), int(spec[2])) for name, spec in zip(names, specs)}
    assert '"DLSS5 enhancement", nullptr' in menu
    assert '"Advanced enhancement", &dlss5_control.advanced' in menu
    assert '"Reset DLSS5 settings", nullptr, 0, 0, 0, nullptr' in menu
    assert 'if (dlss5_reset_press(r, press[7], press[5], mine))' in menu
    assert 'const bool ready = dlss5_control.can_reset();' in menu
    assert 'choice_cell(c, va, vb, label, selected, false, false, !ready);' in menu

    assert 'dlss5_control.configured() && (setting<0 || !d5::specs[setting].advanced || dlss5_control.advanced)' in menu
    assert 'if(dlss5_control.setting(value)>=0)return !dlss5_control.available();' in menu
    save = menu[menu.index('void save() {'):menu.index('void set_row(')]
    assert 'if(dlss5_row(r))continue;' in save
    load = menu[menu.index('void menu_init() {'):menu.index('void menu_tick() {')]
    assert '!r.value || dlss5_row(r) || strcmp(line, ini_key(r))' in load
    host = (ROOT / 'host/posix/display_sdl.c').read_text()
    assert 'dlss5_menu_open' not in host and 'HOS_DLSS5_MENU' not in host
    assert not re.search(r'scancode\s*==\s*67\b', host), 'F10 must retain generic key delivery'
    assert 'HOS_DLSS5_CONTROL' in (ROOT / 'scripts/dlss5_api.py').read_text()
    print('DLSS5 menu: all 19 native rows, matching bounds, advanced visibility, separate persistence and F10 passed')


if __name__ == '__main__':
    main()
