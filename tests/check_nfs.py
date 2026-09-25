"""Validate client restrictions and render exports without NFS or SSH."""
from pathlib import Path
import subprocess
import tempfile
import yaml

root = Path(__file__).resolve().parents[1]
play = yaml.safe_load((root / 'playbooks/nfs.yml').read_text())[0]
tournament = next(task['ansible.builtin.file'] for task in play['tasks']
                  if task['name'] == 'Crear el directorio NFS tournament')
assert tournament == {'path': '/mnt/data/tournament', 'state': 'directory',
                      'owner': '1000', 'group': '1000', 'mode': '0770'}
for address, success in [('192.168.1.20', True), ('*', False),
                         ('192.168.1.0/24', False), ('999.1.1.1', False)]:
    with tempfile.TemporaryDirectory() as folder:
        inventory = {'all': {'hosts': {'localhost': {'ansible_connection': 'local'}},
                            'children': {'container': {'hosts': {
                                'worker': {'swarm_advertise_addr': address}}}}}}
        inv = Path(folder) / 'inventory.yml'
        inv.write_text(yaml.safe_dump(inventory))
        export = Path(folder) / 'data.exports'
        tasks = play['pre_tasks'][:2] + [{'ansible.builtin.template': {
            'src': str(root / 'playbooks/templates/nfs-data.exports.j2'),
            'dest': str(export)}}]
        test = Path(folder) / 'test.yml'
        test.write_text(yaml.safe_dump([{'hosts': 'localhost', 'gather_facts': False,
            'vars': {'ansible_remote_tmp': folder + '/tmp'}, 'tasks': tasks}]))
        result = subprocess.run(['ansible-playbook', '-i', str(inv), str(test)],
                                capture_output=True, text=True)
        assert (result.returncode == 0) == success, result.stdout + result.stderr
        if success:
            content = export.read_text()
            exports = [line for line in content.splitlines()
                       if line and not line.startswith('#')]
            assert len(exports) == 2, content
            assert exports[0].startswith('/mnt/data '), content
            assert exports[1].startswith('/mnt/data/tournament '), content
            assert '/mnt/data 192.168.1.20(rw,sync,no_subtree_check,mountpoint,no_root_squash,fsid=' in content, content
            assert '/mnt/data/tournament 192.168.1.20(rw,sync,no_root_squash,' in content, content
            assert content.count('(rw,') == 2, content
print('OK: explicit container IPs, rw, no_root_squash and invalid clients rejected')
