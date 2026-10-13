"""Verify a real, running guest's saved character and remote-player opacity.

Requires MMAPI debug enabled before launching Join.bat, a loaded test world,
and a connected host. --reopen also exercises the automatic creator/reload
path; press Continue in the game when the test asks.
"""
import argparse
import json
import os
from pathlib import Path

from test_live_game import Game, read, wait


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--data-dir', type=Path, default=Path(os.environ.get('LOCALAPPDATA', '.'))/'FieldsOfMistria')
    parser.add_argument('--reopen', action='store_true')
    args = parser.parse_args()
    data = args.data_dir / 'mod_data/mistrimulti'
    control = read(data / 'control.json')
    assert control['enabled'] and control['mode'] == 'join', 'Launch a guest test world first.'
    slot = control['id']
    game = Game(args.data_dir)
    current = game.call('character')
    profile_path = Path(current['profile_path'])
    saved = read(profile_path)
    assert saved['uid'] == current['uid'] == control['uid']
    def frame():
        return json.loads((data / f'bridge_{slot}/tx.frame').read_text(encoding='utf-8').split('\n',1)[1])
    try:
        current = game.call('character')
        assert not current['pending'] and not current['open'], 'Finish character creation first.'
        assert current['look'] == saved['look']
        assert current['name'] == saved['name'] and current['birthday'] == saved['birthday']
        assert frame()['active'] is True
        print('PASS: Chosen guest name, birthday and outfit match the independent profile')
        remote = game.call('inspect')['ghosts']
        assert remote, 'Connect a host in the same room before the opacity check.'
        for p in remote:
            assert p['draws'] > 0 and p['opacity'] == p['opacity_min'] == p['opacity_max'] == 1, p
        print('PASS: Remote characters stay fully opaque across rendered frames')
        if args.reopen:
            game.batch([{'op':'set','path':'global.__mistrimulti.character_owner','value':None}])
            wait(lambda: game.call('character')['open'])
            editing = game.call('character')
            assert editing['pending'] and editing['edited_look'] == saved['look']
            wait(lambda: frame()['active'] is False)
            print('PASS: Creator reloads the saved outfit and withholds presence until completion')
            print('Press Continue in the game to finish this check.', flush=True)
            wait(lambda: not game.call('character')['pending'], 180)
            wait(lambda: frame()['active'] is True)
            assert game.call('character')['look'] == read(profile_path)['look']
            print('PASS: Completing the creator republishes the chosen character')
    finally:
        game.restore_controls()


if __name__ == '__main__':
    main()
