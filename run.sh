#!/usr/bin/env bash
set -euo pipefail

cd -- "$(dirname -- "${BASH_SOURCE[0]}")"
export ANSIBLE_CONFIG="$PWD/ansible.cfg"
ansible-galaxy collection install -r "$PWD/requirements.yml"
exec ansible-playbook -i "$PWD/inventory.yml" "$PWD/site.yml" "$@"
