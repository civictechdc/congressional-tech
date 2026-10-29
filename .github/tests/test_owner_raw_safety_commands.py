"""Check the executable owner instructions locally without invoking any service."""
from pathlib import Path
import re
import subprocess

import pytest

ROOT = Path(__file__).resolve().parents[2]
DOCUMENT = ROOT/'docs/measurements/engine-first-20261027/owner-raw-safety.md'


def blocks():
    return re.findall(r'```sh\n(.*?)\n```', DOCUMENT.read_text(), re.S)


def test_owner_commands_are_valid_bash_and_embedded_python():
    for index, block in enumerate(blocks()):
        result = subprocess.run(['bash', '-n'], input=block, text=True, capture_output=True)
        assert result.returncode == 0, (index, result.stderr)
        for source in re.findall(r"<<'PY'\n(.*?)\nPY", block, re.S):
            compile(source, str(DOCUMENT), 'exec')


@pytest.mark.parametrize('after,success', [
    ('[{"key":"bodies/a","size":1,"etag":"same"},{"key":"bodies/b","size":2,"etag":"new"}]',True),
    ('[{"key":"bodies/a","size":1,"etag":"changed"}]',False),
    ('[]',False),
])
def test_owner_inventory_comparison_allows_only_additions(tmp_path, after, success):
    before = tmp_path/'before.json'
    current = tmp_path/'after.json'
    before.write_text('[{"key":"bodies/a","size":1,"etag":"same"}]')
    current.write_text(after)
    setup = blocks()[0]
    # Run the actual documented comparison function, with no service commands.
    function = 'unchanged() {' + setup.split('unchanged() {',1)[1].split('\n}',1)[0] + '\n}'
    result = subprocess.run(['bash','-c',function+'\nunchanged "$1" "$2"','test',str(before),str(current)],
                            capture_output=True,text=True)
    assert (result.returncode == 0) == success


def test_owner_readback_checks_require_both_exact_indefinite_prefixes(tmp_path):
    document = DOCUMENT.read_text()
    pattern = re.search(r"jq -e '(\.success and \(\.result\.rules as \$rules.*?)'",document,re.S)[1]
    valid = '{"success":true,"result":{"rules":[{"prefix":"bodies/","enabled":true,"condition":{"type":"Indefinite"}},{"prefix":"provenance/","enabled":true,"condition":{"type":"Indefinite"}}]}}'
    for value, expected in [(valid,True),(valid.replace('provenance/','receipts/'),False),
                             (valid.replace('Indefinite','Age'),False),(valid.replace('true','false',1),False)]:
        result = subprocess.run(['jq','-e',pattern],input=value,text=True,capture_output=True)
        assert (result.returncode==0) == expected, result.stderr
