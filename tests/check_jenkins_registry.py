"""Check that Jenkins and the LAN registry run only on the manager."""
from pathlib import Path

import yaml

root = Path(__file__).resolve().parents[1]
plays = yaml.safe_load((root / 'playbooks/swarm.yml').read_text())
jenkins = yaml.safe_load((root / 'roles/jenkins/tasks/main.yml').read_text())
registry = yaml.safe_load((root / 'roles/local_docker_registry/tasks/main.yml').read_text())
manager_roles = [
    task['ansible.builtin.include_role']['name']
    for task in plays[1]['tasks']
    if 'ansible.builtin.include_role' in task
]

assert plays[1]['hosts'] == 'container[0]'
assert {'jenkins', 'local_docker_registry'} <= set(manager_roles)
assert all('local_docker_registry' not in str(play) and 'name: jenkins' not in str(play) for play in plays[2:])
docker_access = next(task['ansible.builtin.user'] for task in jenkins if task['name'] == 'Permitir que Jenkins use Docker')
jenkins_package = next(task['ansible.builtin.apt'] for task in jenkins if task['name'] == 'Instalar o actualizar Jenkins')
container = registry[-1]['community.docker.docker_container']
daemon_config = next(task['ansible.builtin.copy'] for task in registry if task['name'] == 'Permitir el registro HTTP local en Docker')
assert docker_access['groups'] == 'docker' and docker_access['append'] is True
assert jenkins_package['name'] == 'jenkins' and jenkins_package['state'] == 'latest'
assert daemon_config['dest'] == '/etc/docker/daemon.json'
assert container['published_ports'] == ['{{ local_docker_registry_address }}:{{ local_docker_registry_port }}:5000']
assert container['volumes'] == ['{{ local_docker_registry_data_directory }}:/var/lib/registry']
assert container['restart_policy'] == 'always'
print('OK: Jenkins and LAN registry are manager-only with local persistence')
