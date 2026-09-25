"""Exercise adoption, append and idempotence locally, without Samba or SSH."""
from pathlib import Path
import subprocess
import tempfile
import yaml

root = Path(__file__).resolve().parents[1]
play = yaml.safe_load((root / 'playbooks/samba.yml').read_text())[0]
fragment = (root / 'playbooks/files/samba/server1/smb.conf').read_text().strip()
marked = '# BEGIN ANSIBLE MANAGED DATA\n' + fragment + '\n# END ANSIBLE MANAGED DATA\n'
for old_share, suffix in [('', '[other]\npath = /keep\n'),
                          ('[data]\npath = /old\n', '[other]\npath = /keep\n'),
                          ('[data]\npath = /old', ''),
                          (marked + '\n' + marked, ''),
                          (marked.rstrip(), ''),
                          (marked * 3, '[other]\npath = /keep\n')]:
    with tempfile.TemporaryDirectory() as directory:
        target = Path(directory) / 'smb.conf'
        prefix = '[global]\nworkgroup = EXAMPLE\n'
        target.write_text(prefix + old_share + suffix)
        tasks = yaml.safe_load(yaml.safe_dump(play['tasks'][1:6]))
        tasks[0]['ansible.builtin.slurp']['src'] = str(target)
        for task in tasks[1:]:
            module = next(key for key in task if key.startswith('ansible.builtin.'))
            task[module]['path'] = str(target)
            task[module].pop('validate')  # testparm validates on the actual server.
            task.pop('notify', None)
        tasks[-1]['ansible.builtin.blockinfile']['block'] = fragment
        test = Path(directory) / 'test.yml'
        test.write_text(yaml.safe_dump([{'hosts': 'localhost', 'gather_facts': False, 'vars': {'ansible_remote_tmp': directory + '/tmp'}, 'tasks': tasks}]))
        for attempt in range(2):
            result = subprocess.run(['ansible-playbook', '-i', 'localhost,', '-c', 'local', str(test)],
                                    capture_output=True, text=True)
            assert result.returncode == 0, result.stdout + result.stderr
            content = target.read_text()
            assert content.count('[data]') == 1 and fragment in content, content
            assert prefix in content and suffix in content, content
            if attempt:
                assert 'changed=0' in result.stdout, result.stdout
print('OK: Samba adoption, append, other sections preserved and idempotence')
