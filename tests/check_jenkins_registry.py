"""Check the manager-only Jenkins migration, agent builds and LAN registry."""
from pathlib import Path

import yaml

root = Path(__file__).resolve().parents[1]
plays = yaml.safe_load((root / 'playbooks/swarm.yml').read_text())
jenkins = yaml.safe_load((root / 'roles/jenkins/tasks/main.yml').read_text())
registry = yaml.safe_load((root / 'roles/local_docker_registry/tasks/main.yml').read_text())
dockerfile = (root / 'docker/jenkins-agents/Dockerfile').read_text()
bake = (root / 'docker/jenkins-agents/docker-bake.hcl').read_text()
controller_dockerfile = (root / 'docker/jenkins-controller/Dockerfile').read_text()
manager_roles = [
    task['ansible.builtin.include_role']['name']
    for task in plays[1]['tasks']
    if 'ansible.builtin.include_role' in task
]

assert plays[1]['hosts'] == 'container[0]'
assert {'jenkins', 'local_docker_registry'} <= set(manager_roles)
assert manager_roles.index('local_docker_registry') < manager_roles.index('jenkins')
assert all('local_docker_registry' not in str(play) and 'name: jenkins' not in str(play) for play in plays[2:])

agent_build = next(task['community.docker.docker_image'] for task in jenkins
                   if task['name'] == 'Construir y publicar las imágenes de agentes Jenkins')
dockerfile_copy = next(task['ansible.builtin.copy'] for task in jenkins
                       if task['name'] == 'Copiar el Dockerfile de los agentes al manager')
base_image = next(task['ansible.builtin.set_fact']['jenkins_controller_base_image'] for task in jenkins
                  if task['name'] == 'Elegir la imagen base compatible para el controller')
controller_build = next(task['community.docker.docker_image'] for task in jenkins
                        if task['name'] == 'Construir y publicar la imagen del controller Jenkins')
version_check = next(task['ansible.builtin.command'] for task in jenkins
                     if task['name'] == 'Consultar la versión del controller en la imagen')
uid_check = next(task['ansible.builtin.command'] for task in jenkins
                 if task['name'] == 'Consultar el UID efectivo del controller en la imagen')
migration = next(task for task in jenkins if task['name'] == 'Migrar el controller Jenkins al Swarm')
service = next(task['community.docker.docker_swarm_service'] for task in migration['block']
               if task['name'] == 'Desplegar Jenkins en el nodo que contiene su home')
native_stop = next(task['ansible.builtin.systemd_service'] for task in migration['block']
                   if task['name'] == 'Detener y deshabilitar el Jenkins nativo')
container = next(task['community.docker.docker_container'] for task in registry
                 if task['name'] == 'Ejecutar el registro Docker local')
registry_ready = next(task['ansible.builtin.uri'] for task in registry
                      if task['name'] == 'Esperar a que el registro Docker local responda')
daemon_config = next(task['ansible.builtin.copy'] for task in registry if task['name'] == 'Permitir el registro HTTP local en Docker')

assert agent_build['source'] == 'build' and agent_build['push'] is True
assert agent_build['build']['target'] == '{{ item.target }}'
assert agent_build['build']['platform'] == '{{ jenkins_agent_platform }}'
assert dockerfile_copy['src'].endswith('/docker/jenkins-agents/Dockerfile')
assert '-lts-jdk21' in base_image
assert controller_build['source'] == 'build' and controller_build['push'] is True
assert controller_build['build']['args']['JENKINS_UID'] == '{{ jenkins_uid.stdout }}'
assert controller_build['build']['args']['JENKINS_GID'] == '{{ jenkins_gid.stdout }}'
assert version_check['argv'][3:5] == ['--entrypoint', 'java']
assert version_check['argv'][-3:] == ['-jar', '/usr/share/jenkins/jenkins.war', '--version']
assert uid_check['argv'][-3:] == ['id', '{{ jenkins_runtime_image }}', '-u']
assert {'base', 'rsync', 'node'} <= {item['target'] for item in next(task for task in jenkins
                                                              if task['name'] == 'Construir y publicar las imágenes de agentes Jenkins')['loop']}
assert native_stop == {'name': 'jenkins', 'enabled': False, 'state': 'stopped'}
assert service['image'] == '{{ jenkins_runtime_image }}'
assert service['user'] == 'jenkins'
assert service['networks'] == ['{{ jenkins_agent_network }}']
assert service['mounts'] == [
    {'source': '{{ jenkins_home_directory }}', 'target': '/var/jenkins_home', 'type': 'bind'},
    {'source': '/var/run/docker.sock', 'target': '/var/run/docker.sock', 'type': 'bind'},
]
assert service['placement']['constraints'] == ['node.hostname == {{ server_hostname }}']
assert service['replicas'] == 1 and service['update_config']['order'] == 'stop-first'
assert {port['target_port'] for port in service['publish']} == {8080, 50000}
assert 'targets = ["base", "rsync", "node"]' in bake and 'jenkins-agent-base:' in bake
assert 'FROM base AS rsync' in dockerfile and 'FROM base AS node' in dockerfile
assert 'ENV REMOTING_OPTS="-workDir /tmp/jenkins-agent"' in dockerfile
assert 'JENKINS_AGENT_WORKDIR' not in dockerfile
assert 'install --directory --owner="${JENKINS_UID}"' in dockerfile
assert 'usermod --uid "${JENKINS_UID}" jenkins' in controller_dockerfile
assert "getent passwd \"${JENKINS_UID}\" | grep '^jenkins:'" in controller_dockerfile
assert daemon_config['dest'] == '/etc/docker/daemon.json'
assert container['published_ports'] == ['{{ local_docker_registry_address }}:{{ local_docker_registry_port }}:5000']
assert container['volumes'] == ['{{ local_docker_registry_data_directory }}:/var/lib/registry']
assert container['restart_policy'] == 'always'
assert registry_ready['url'].endswith('/v2/')
print('OK: Jenkins migration, agent publishing and LAN registry stay manager-only')
