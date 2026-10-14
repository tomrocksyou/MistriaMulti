"""Opt-in Windows integration test against a running host test world.

Enable MMAPI debug before launching the game. Pass the host's room code.
This temporarily changes one empty farm tile and restores it in finally.
It never saves the game. No second game installation is required, but this
does not replace a two-computer playtest.
"""
import argparse
import json
import os
from pathlib import Path
import socket
import subprocess
import tempfile
import threading
import time
import uuid


def read(path):
    return json.loads(path.read_text(encoding='utf-8'))


def write(path, value):
    temp = path.with_suffix('.live-test.tmp')
    temp.write_text(json.dumps(value, separators=(',', ':')), encoding='utf-8')
    os.replace(temp, path)


def wait(check, seconds=15):
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        if check():
            return
        time.sleep(.05)
    raise AssertionError('Live-game check timed out')


class Game:
    def __init__(self, data):
        self.root = data / 'mod_data/mmapi'
        self.previous = read(self.root / 'control.json')

    def batch(self, commands):
        control = read(self.root / 'control.json')
        rev = max(control.get('rev', 0), read(self.root / 'state.json')['applied_rev']) + 1
        control.update(rev=rev, commands=commands)
        write(self.root / 'control.json', control)
        def applied():
            try:
                return read(self.root / 'state.json')['applied_rev'] >= rev
            except (OSError, ValueError):
                return False
        wait(applied, 8)
        return read(self.root / 'state.json').get('last_call')

    def call(self, name, *args):
        value = self.batch([{'op': 'call', 'fn': 'mistrimulti.' + name, 'args': list(args)}])
        assert value and 'error' not in value, value
        assert value['target'] == 'fn:mistrimulti.' + name, value
        return value.get('result')

    def restore_controls(self):
        state = read(self.root / 'state.json')
        self.previous.update(rev=state['applied_rev'] + 1, commands=[])
        write(self.root / 'control.json', self.previous)


class Peer:
    def __init__(self, helper, root, code, port, frame, player_id=1):
        self.root, self.frame = root, frame
        self.player_id = player_id
        self.frame.update(v=1, id=player_id, epoch=uuid.uuid4().hex, active=True, a=[0]*8)
        self.ack = 0
        self.next_event = 1
        self.pending = None
        self.events = {}
        self.lock = threading.Lock()
        self.done = threading.Event()
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
            sock.bind(('127.0.0.1', 0))
            local = sock.getsockname()[1]
        self.process = subprocess.Popen([str(helper), 'join', str(local), str(player_id), code,
                                        str(root), '127.0.0.1', str(port)],
                                        creationflags=subprocess.CREATE_NO_WINDOW)
        self.thread = threading.Thread(target=self.run, daemon=True)
        self.thread.start()

    def run(self):
        while not self.done.wait(.05):
            with self.lock:
                try:
                    host = read(self.root / 'rx_0.json')
                    event = host.get('q')
                    if event:
                        self.frame['a'][0] = max(self.frame['a'][0], event['s'])
                        self.events[event['s']] = event
                    self.ack = host.get('a', [0]*8)[self.player_id]
                    if self.pending and self.ack >= self.pending['s']:
                        self.pending = None
                except (OSError, ValueError):
                    pass
                frame = dict(self.frame)
                if self.pending:
                    frame['q'] = self.pending
                temp = self.root / 'peer.tmp'
                temp.write_bytes(('1\n' if self.pending else '0\n').encode() +
                                 json.dumps(frame, separators=(',', ':')).encode())
                os.replace(temp, self.root / 'tx.frame')

    def move(self, **fields):
        with self.lock:
            self.frame.update(fields)

    def event(self, kind, data):
        with self.lock:
            assert self.pending is None
            seq = self.next_event
            self.next_event += 1
            self.pending = {'s': seq, 'k': kind, 'd': data}
        wait(lambda: self.ack >= seq)
        wait(lambda: self.pending is None)

    def close(self):
        self.done.set()
        self.thread.join(timeout=2)
        (self.root / 'stop.flag').write_text('stop')
        try:
            self.process.wait(timeout=3)
        except subprocess.TimeoutExpired:
            self.process.terminate()
            self.process.wait(timeout=3)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--room-code', required=True)
    parser.add_argument('--port', type=int, default=7777)
    parser.add_argument('--helper', type=Path, default=Path(__file__).resolve().parents[1]/'build/mistrimulti-helper.exe')
    parser.add_argument('--data-dir', type=Path, default=Path(os.environ.get('LOCALAPPDATA', '.'))/'FieldsOfMistria')
    options = parser.parse_args()
    if os.name != 'nt':
        parser.error('This live-game driver currently targets Windows.')
    game = Game(options.data_dir)
    control = read(options.data_dir / 'mod_data/mistrimulti/control.json')
    assert control['enabled'] and control['mode'] == 'host', 'Launch an enabled host test world first.'
    host_path = options.data_dir / 'mod_data/mistrimulti/bridge_0/tx.frame'
    host = json.loads(host_path.read_text(encoding='utf-8').split('\n', 1)[1])
    initial = game.call('inspect')
    assert not initial['ghosts'], 'Disconnect other players before this test.'
    assert initial['room'].startswith('farm:'), 'Stand on the farm in a test world.'
    frame = {'room': host['room'], 'x': host['x']+32, 'y': host['y'], 'z': 0,
             'c': 3, 'ba': 0, 'ma': -1, 'att': -1, 'name': 'Integration test peer'}
    peer, original = None, None
    results = []
    temporary = tempfile.TemporaryDirectory(prefix='live-game-')
    try:
        tmp = temporary.name
        peer = Peer(options.helper.resolve(), Path(tmp), options.room_code, options.port, frame)
        wait(lambda: bool(game.call('inspect')['ghosts']))
        first = game.call('inspect')['ghosts'][0]
        wait(lambda: game.call('inspect')['ghosts'][0]['draws'] > first['draws'])
        results.append('Remote character creation and actual draw callbacks')
        peer.move(x=host['x']+48, y=host['y']+8, ba=2, c=1)
        def moved():
            p = game.call('inspect')['ghosts'][0]
            return abs(p['x']-(host['x']+48)) < .5 and abs(p['y']-(host['y']+8)) < .5 and p['ba']==2 and p['c']==1
        wait(moved)
        results.append('Interpolated position, walking animation and facing')
        peer.move(room='different-room')
        wait(lambda: not game.call('inspect')['ghosts'])
        peer.move(room=host['room'], ba=0)
        wait(lambda: bool(game.call('inspect')['ghosts']))
        results.append('Room exit cleanup and room re-entry')
        wait(lambda: any(e['k']=='terrain_snapshot' for e in peer.events.values()))
        # Find an empty host soil/dirt tile from the acknowledged baseline.
        candidates = {(t['x'],t['y']) for e in list(peer.events.values())
                      if e['k']=='terrain_snapshot' for t in e['d']['tiles']}
        for x, y in sorted(candidates, key=lambda p:(p[0]*8-host['x'])**2+(p[1]*8-host['y'])**2):
            tile = game.call('tile', x, y)
            if tile['tile'] and not tile['occupied']:
                original = tile['tile']
                break
        assert original is not None, 'No empty terrain test tile found.'
        x, y = original['x'], original['y']
        peer.move(room='farm:undefined', x=x*8, y=y*8)
        soil = dict(original, g=initial['soil'], w=False)
        wet = dict(soil, w=True)
        peer.event('terrain_request', {'before':original,'tiles':[soil]})
        wait(lambda: game.call('tile', x, y)['tile']==soil)
        peer.event('terrain_request', {'before':soil,'tiles':[wet]})
        wait(lambda: game.call('tile', x, y)['tile']==wet)
        results.append('Host soil and watering requests with acknowledgements')
        peer.event('terrain_request', {'before':dict(wet,g=initial['dirt'],w=False),'tiles':[original]})
        assert game.call('tile', x, y)['tile']==wet
        peer.event('terrain_commit', {'tiles':[original]})
        assert game.call('tile', x, y)['tile']==wet
        peer.move(x=-10000,y=-10000)
        peer.event('terrain_request', {'before':wet,'tiles':[original]})
        assert game.call('tile', x, y)['tile']==wet
        results.append('Conflict correction, host-only commit and reach checks')
        peer.move(x=x*8,y=y*8)
        peer.event('terrain_request', {'before':wet,'tiles':[original]})
        wait(lambda: game.call('tile', x, y)['tile']==original)
        guarded = game.batch([
            {'op':'set','path':'global.__mistrimulti.mode','value':'join'},
            {'op':'call','fn':'mistrimulti.apply','args':[wet]},
            {'op':'call','fn':'mistrimulti.apply','args':[original]},
            {'op':'call','fn':'mistrimulti.guard','args':[]},
            {'op':'set','path':'global.__mistrimulti.mode','value':'host'},
            {'op':'set','path':'global.__mistrimulti.dirty_world','value':False}])
        assert guarded['result'] is False, guarded
        assert game.call('guard') is None
        results.append('Guest save guard blocks replicated terrain; host guard permits saving')
        peer.close()
        peer = None
        wait(lambda: not game.call('inspect')['ghosts'], 15)
        results.append('Disconnect expiry clears the remote character')
    finally:
        if peer:
            peer.close()
        if original:
            assert game.call('apply', original) is True
            assert game.call('tile', original['x'], original['y'])['tile']==original
        game.restore_controls()
        temporary.cleanup()
    for result in results:
        print('PASS:', result)


if __name__ == '__main__':
    main()
