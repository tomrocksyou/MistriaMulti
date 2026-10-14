"""Opt-in persistence test against a running host test world with MMAPI debug enabled.

Creates temporary player records and restores any temporary character changes.
Uses real assembly helpers to test inactive joins, transfers and reconnects.
"""
import argparse
import copy
import json
import os
from pathlib import Path
import tempfile
import time
import uuid

from test_live_game import Game, Peer, read, wait, write


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--room-code', required=True)
    parser.add_argument('--port', type=int, default=7777)
    parser.add_argument('--data-dir', type=Path, default=Path(os.environ.get('LOCALAPPDATA', '.'))/'FieldsOfMistria')
    parser.add_argument('--helper', type=Path, default=Path(__file__).resolve().parents[1]/'build/mistrimulti-helper.exe')
    args = parser.parse_args()
    game = Game(args.data_dir)
    debug_control = read(game.root/'control.json')
    debug_control['watch_paths'] = list(debug_control.get('watch_paths', [])) + ['global.__check_achievements']
    write(game.root/'control.json', debug_control)
    wait(lambda: 'global.__check_achievements' in read(game.root/'state.json').get('watches', {}))
    achievements = read(game.root/'state.json')['watches']['global.__check_achievements']
    game.batch([{'op':'set','path':'global.__check_achievements','value':False}])
    status = game.call('player_data')
    assert status['ready'], 'Enter a host test world first.'
    control = read(args.data_dir/'mod_data/mistrimulti/control.json')
    bridge = args.data_dir/'mod_data/mistrimulti/bridge_0'
    def mask():
        return read(bridge/'status.json')['mask']
    assert control['mode'] == 'host' and not mask(), 'Disconnect other players before testing.'
    world = status['world']
    baseline = status['profile']
    # The debug agent limits nested output depth. Read the outfit separately.
    baseline['character']['look'] = game.call('character')['look']
    uid = 'local:' + uuid.uuid4().hex
    uid_b = 'local:' + uuid.uuid4().hex
    world_path = args.data_dir/'mod_data/mistrimulti/worlds'/world
    player_file = world_path/'players'/f'{uid.replace(":", "_")}.json'
    player_file_b = player_file.with_name(f'{uid_b.replace(":", "_")}.json')
    peers = []
    result = []
    with tempfile.TemporaryDirectory(prefix='player-data-') as temporary:
        def connect(identity, slot):
            path = Path(temporary)/str(uuid.uuid4())
            path.mkdir()
            peer = Peer(args.helper.resolve(), path, args.room_code, args.port,
                        {'uid':identity, 'name':'Persistence test', 'room':'test-room',
                         'x':0, 'y':0, 'z':0, 'c':0, 'ba':0, 'ma':-1, 'att':-1}, slot)
            peer.move(active=False)
            peers.append(peer)
            wait(lambda: mask() & (1 << slot))
            peer.event('profile_request', {'uid':identity, 'world':world})
            return peer

        def chunks(peer, profile, revision, stop_before_last=False):
            text = json.dumps(profile, separators=(',', ':'), ensure_ascii=False)
            parts = [text[i:i+1536] for i in range(0, len(text), 1536)]
            transaction = str(uuid.uuid4())
            for index, part in enumerate(parts):
                if stop_before_last and index == len(parts)-1:
                    break
                peer.event('profile_update', {'uid':profile['uid'],'world':world,'to':0,
                    'peer_epoch':peer.frame['epoch'],'revision':revision,'transfer':transaction,
                    'total':len(parts),'index':index,'text':part})
            return len(parts)

        try:
            assert game.call('checkpoint') is True
            saved_host = game.call('player_load', baseline['uid'])
            assert saved_host['data']['stats'] == baseline['stats']
            result.append('Native host checkpoint persists inventory, stats and relationships')
            first = connect(uid, 1)
            wait(lambda: any(e['k']=='profile_start' for e in list(first.events.values())))
            profile = copy.deepcopy(baseline)
            profile['uid'] = profile['character']['uid'] = uid
            profile['character']['name'] = 'Test player'
            profile['stats']['gold'] = 123
            profile['relations'][0]['hearts'] = 17
            profile['relations'][0]['status'] = 'dating'
            count = chunks(first, profile, 1, stop_before_last=True)
            assert count > 1 and not player_file.exists()
            result.append('Interrupted multipart upload does not publish an incomplete player record')
            chunks(first, profile, 1)
            wait(lambda: player_file.exists())
            wait(lambda: any(e['k']=='profile_saved' for e in list(first.events.values())))
            stored = read(player_file)
            assert stored['revision']==1 and stored['data']==profile
            result.append('Inactive guest handshake and multipart upload save an exact host record')

            invalid = copy.deepcopy(profile)
            invalid['inventory'][0]['count'] = -1
            before = player_file.read_bytes()
            assert game.call('player_store', uid, 2, invalid) is False
            wrong_world = copy.deepcopy(profile)
            wrong_world['world'] += '_different'
            assert game.call('player_store', uid, 2, wrong_world) is False
            assert player_file.read_bytes() == before
            result.append('Invalid inventory and wrong-world records cannot overwrite saved progress')

            # A reconnect in another slot still receives the same identity's record.
            first.close()
            peers.remove(first)
            wait(lambda: not (mask() & 2), 16)
            time.sleep(1.2)
            second = connect(uid, 2)
            def received():
                events = [e['d'] for e in list(second.events.values()) if e['k']=='profile_record']
                if not events or len(events) < events[0]['total']:
                    return None
                parts = {e['index']:e['text'] for e in events}
                if len(parts) != events[0]['total']:
                    return None
                return json.loads(''.join(parts[i] for i in range(len(parts))))
            wait(lambda: received() == profile, 30)
            result.append('Reconnect in a different player slot downloads the exact saved character')

            third = connect(uid_b, 1)
            wait(lambda: any(e['k']=='profile_start' for e in list(third.events.values())))
            independent = copy.deepcopy(profile)
            independent['uid'] = independent['character']['uid'] = uid_b
            independent['stats']['gold'] = 456
            independent['relations'][0]['status'] = 'best_friend'
            chunks(third, independent, 1)
            wait(lambda: player_file_b.exists())
            assert read(player_file)['data'] == profile and read(player_file_b)['data'] == independent
            result.append('Different player identities retain separate money and relationship status')

            profile['stats']['gold'] = 789
            chunks(second, profile, 2)
            wait(lambda: read(player_file)['revision'] == 2)
            valid_primary = player_file.read_bytes()
            player_file.write_text('{broken', encoding='utf-8')
            recovered = game.call('player_load', uid)
            assert recovered['revision'] == 1 and recovered['data']['stats']['gold'] == 123
            player_file.write_bytes(valid_primary)
            result.append('A damaged primary record falls back to its last valid backup')

            isolated_world = world + '_integration_' + uuid.uuid4().hex
            isolated_path = world_path.with_name(isolated_world)
            (isolated_path/'players').mkdir(parents=True)
            try:
                game.batch([
                    {'op':'set','path':'global.__mistrimulti.player_ready','value':False},
                    {'op':'set','path':'global.__mistrimulti.world_key','value':isolated_world},
                    {'op':'set','path':'global.__mistrimulti.world_path','value':str(isolated_path)}])
                assert game.call('player_load', uid) is None
                other_world = copy.deepcopy(profile)
                other_world['world'] = isolated_world
                other_world['stats']['gold'] = 321
                assert game.call('player_store', uid, 1, other_world) is True
                assert game.call('player_load', uid)['data']['stats']['gold'] == 321
            finally:
                game.batch([
                    {'op':'set','path':'global.__mistrimulti.world_key','value':world},
                    {'op':'set','path':'global.__mistrimulti.world_path','value':str(world_path)},
                    {'op':'set','path':'global.__mistrimulti.player_ready','value':True}])
                for file in (isolated_path/'players').iterdir():
                    file.unlink()
                (isolated_path/'players').rmdir()
                isolated_path.rmdir()
            assert game.call('player_load', uid)['data']['stats']['gold'] == 789
            result.append('The same identity has separate player records in different hosted worlds')

            restored = copy.deepcopy(profile)
            restored['uid'] = restored['character']['uid'] = baseline['uid']
            assert game.call('player_restore', restored) is True
            applied = game.call('player_data')['profile']
            applied['character']['look'] = game.call('character')['look']
            for field in ['stats','inventory','armor','xp','perks','spells','relations','character']:
                assert applied[field] == restored[field], field
            result.append('Native character restore applies inventory, equipment, skills and independent relationships')
        finally:
            for peer in peers:
                peer.close()
            try:
                assert game.call('player_restore', baseline) is True
                assert game.call('checkpoint') is True
            finally:
                game.batch([{'op':'set','path':'global.__check_achievements','value':achievements}])
                for path in [player_file, player_file_b]:
                    for suffix in ['', '.bak', '.tmp']:
                        Path(str(path)+suffix).unlink(missing_ok=True)
                game.restore_controls()
    for line in result:
        print('PASS:', line)


if __name__ == '__main__':
    main()
