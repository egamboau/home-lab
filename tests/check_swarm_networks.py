"""Check the shared Swarm network defaults and non-destructive guard."""
from pathlib import Path

import yaml

root = Path(__file__).resolve().parents[1]
defaults = yaml.safe_load((root / 'roles/docker_swarm_networks/defaults/main.yml').read_text())
tasks = yaml.safe_load((root / 'roles/docker_swarm_networks/tasks/main.yml').read_text())
cloudflared = yaml.safe_load((root / 'roles/cloudflared/tasks/main.yml').read_text())

assert defaults['docker_swarm_networks'] == [
    {'name': 'public-ingress', 'driver': 'overlay', 'attachable': True},
]
create = tasks[-1]['community.docker.docker_network']
assert create['scope'] == 'swarm' and create['appends'] is True and create['state'] == 'present'
assert tasks[-1]['when'] == 'not item.exists'
assert any('ControlAvailable' in str(task) for task in tasks)
assert any('no se recreará' in task.get('ansible.builtin.assert', {}).get('fail_msg', '') for task in tasks)
secret = cloudflared[-2]['community.docker.docker_secret']
service = cloudflared[-1]['community.docker.docker_swarm_service']
assert secret['rolling_versions'] is True and secret['versions_to_keep'] == 2
assert service['networks'] == ['{{ cloudflared_network }}']
assert service['args'][-2:] == ['--token-file', '/run/secrets/cloudflared_token']
assert service['secrets'][0]['filename'] == '/run/secrets/cloudflared_token'
assert service['secrets'][0]['mode'] == 0o444
ignored = (root / '.gitignore').read_text().splitlines()
assert 'secrets/*' in ignored or 'secrets/cloudflared_token' in ignored
print('OK: shared network and cloudflared secret-backed service')
