"""Check Docker package selection without installing anything or using SSH."""
from pathlib import Path
import subprocess
import tempfile

import yaml

root = Path(__file__).resolve().parents[1]
tasks = yaml.safe_load((root / 'playbooks/tasks/docker.yml').read_text())
selection = tasks[1]
removal = tasks[2]['ansible.builtin.command']
for packages, expected in [
    ([], []),
    (['installed docker.io', 'installed docker-cli', 'installed containerd', 'installed runc'],
     ['docker.io', 'docker-cli', 'containerd', 'runc']),
    (['installed docker-ce', 'installed containerd.io', 'installed docker-buildx-plugin'], []),
    (['unpacked docker.io', 'half-configured docker-cli', 'unpacked containerd', 'unpacked runc'],
     ['docker.io', 'docker-cli', 'containerd', 'runc']),
    (['config-files docker.io', 'not-installed runc', 'installed openssh-server'], []),
    (['half-installed docker-buildx', 'triggers-awaited containerd', 'triggers-pending runc'],
     ['docker-buildx', 'containerd', 'runc']),
]:
    test = [{'hosts': 'localhost', 'gather_facts': False,
             'vars': {'docker_package_states': {'stdout_lines': packages}, 'expected': expected},
             'tasks': [selection,
                       {'ansible.builtin.set_fact': {'removal_argv': removal['argv']}},
                       {'ansible.builtin.assert': {'that': [
                           'docker_conflicting_packages | sort == expected | sort',
                           "removal_argv[:2] == ['dpkg', '--remove']",
                           'removal_argv[2:] | sort == expected | sort']}}]}]
    with tempfile.NamedTemporaryFile(mode='w', suffix='.yml') as config:
        yaml.safe_dump(test, config)
        config.flush()
        result = subprocess.run(
            ['ansible-playbook', '-i', 'localhost,', '-c', 'local', config.name],
            capture_output=True, text=True,
        )
    assert result.returncode == 0, result.stdout + result.stderr
print('OK: fresh, installed, partially configured and removed Docker packages')
