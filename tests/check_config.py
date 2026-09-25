"""Run with the same Python environment as ansible-playbook (includes PyYAML)."""
from pathlib import Path
import subprocess
import tempfile
import re

import yaml

root = Path(__file__).resolve().parents[1]
tasks = yaml.safe_load((root / 'playbooks/storage.yml').read_text())[0]['pre_tasks'][:2]
disk = {'uuid': '1111-2222', 'path': '/srv/disks/data1', 'fstype': 'ext4'}
cases = [
    ('valid', [disk], True),
    ('mnt path', [{**disk, 'path': '/mnt/disk1'}], True),
    ('pool collision', [{**disk, 'path': '/mnt/data'}], False),
    ('mnt root', [{**disk, 'path': '/mnt'}], False),
    ('path traversal', [{**disk, 'path': '/mnt/../etc'}], False),
    ('empty', [], False),
    ('duplicate', [disk, disk], False),
    ('system path', [{**disk, 'path': '/'}], False),
    ('invalid uuid', [{**disk, 'uuid': '../sda'}], False),
    ('invalid filesystem', [{**disk, 'fstype': 'unknown'}], False),
]
for name, disks, expected in cases:
    play = [{'hosts': 'localhost', 'gather_facts': False, 'vars': {
        'ansible_facts': {'distribution': 'Debian', 'distribution_major_version': '13'},
        'mergerfs_disks': disks,
    }, 'tasks': tasks}]
    with tempfile.NamedTemporaryFile(mode='w', suffix='.yml') as config:
        yaml.safe_dump(play, config)
        config.flush()
        result = subprocess.run(
            ['ansible-playbook', '-i', 'localhost,', '-c', 'local', config.name],
            capture_output=True, text=True,
        )
    assert (result.returncode == 0) == expected, result.stdout + result.stderr
    print(f'OK: {name}')

# Exercise Ansible's real host selection without connecting to any server.
inventory = {'all': {'hosts': {'other': {}}, 'children': {
    'container': {'hosts': {'combined': {}, 'compute': {}}},
    'storage': {'hosts': {'combined': {}, 'disks': {}}},
}}}
with tempfile.NamedTemporaryFile(mode='w', suffix='.yml') as config:
    yaml.safe_dump(inventory, config)
    config.flush()
    result = subprocess.run(
        ['ansible-playbook', '-i', config.name, str(root / 'site.yml'), '--list-hosts'],
        capture_output=True, text=True, check=True,
    )
selections = [
    set(re.findall(r'^      (\S+)$', section, re.MULTILINE))
    for section in result.stdout.split('  play #')[1:]
]
assert selections == [
    {'combined', 'disks', 'compute', 'other'},
    {'combined', 'disks'}, {'combined', 'disks'},
    {'combined', 'disks'}, {'combined', 'compute'},
    {'combined', 'compute'}, {'combined'}, {'compute'},
], result.stdout
print('OK: common (all hosts), storage, container, manager and worker host selection')

hostname_check = yaml.safe_load((root / 'playbooks/common.yml').read_text())[0]['pre_tasks'][0]
for hostname, expected in [('server1', True), ('media-server', True),
                           ('server.local', False), ('', False), ('-server', False),
                           ('a' * 64, False)]:
    play = [{'hosts': 'localhost', 'gather_facts': False, 'vars': {
        'ansible_facts': {'distribution': 'Debian', 'distribution_major_version': '13'},
        'server_hostname': hostname,
    }, 'tasks': [hostname_check]}]
    with tempfile.NamedTemporaryFile(mode='w', suffix='.yml') as config:
        yaml.safe_dump(play, config)
        config.flush()
        result = subprocess.run(
            ['ansible-playbook', '-i', 'localhost,', '-c', 'local', config.name],
            capture_output=True, text=True,
        )
    assert (result.returncode == 0) == expected, result.stdout + result.stderr
print('OK: valid and invalid server hostnames')
