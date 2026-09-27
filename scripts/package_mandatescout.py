"""Package reviewed public-source artifacts; never include AGY sessions or credentials."""
from pathlib import Path
import hashlib
import json
import zipfile

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'deliverables' / 'MandateScout-review.zip'
files = set()
for name in ['README.md', 'DEMO.md', 'PRODUCT_SPEC.md', 'Start-MandateScout.cmd']:
    files.add(ROOT / name)
for pattern in ['product/*.py', 'product/README.md', 'product/requirements.txt',
                'product/static/**/*', 'product/data/**/*',
                'product/cache/registry/*', 'product/cache/websites/*',
                'benchmarks/results.json', 'benchmarks/RESULTS.md',
                'benchmarks/run_benchmark.py', 'benchmarks/collector_snapshot.py',
                'benchmarks/cache/**/*']:
    files.update(p for p in ROOT.glob(pattern) if p.is_file() and '__pycache__' not in p.parts)
for name in ['pitch.html', 'example-brief.md', 'buyer-brief.md', 'PARENT_QA.md', 'agent-run.json']:
    files.add(ROOT / 'deliverables' / 'mandatescout' / name)
for run_id in ['run_20260926_203346_d9ab05', 'run_20260927_020133_2514c0']:
    files.add(ROOT / 'product' / 'cache' / 'runs' / f'{run_id}.json')
missing = [str(p.relative_to(ROOT)) for p in files if not p.is_file()]
if missing:
    raise SystemExit(f'Missing deliverables: {missing}')
manifest = []
with zipfile.ZipFile(OUT, 'w', zipfile.ZIP_DEFLATED) as z:
    for path in sorted(files):
        relative = path.relative_to(ROOT).as_posix()
        data = path.read_bytes()
        z.writestr(relative, data)
        manifest.append({'file': relative, 'bytes': len(data), 'sha256': hashlib.sha256(data).hexdigest()})
    z.writestr('MANIFEST.json', json.dumps(manifest, indent=2))
with zipfile.ZipFile(OUT) as z:
    assert z.testzip() is None
receipt = {'archive': OUT.name, 'files': len(files), 'bytes': OUT.stat().st_size,
           'sha256': hashlib.sha256(OUT.read_bytes()).hexdigest()}
(OUT.parent / 'MandateScout-review-receipt.json').write_text(json.dumps(receipt, indent=2))
print(json.dumps(receipt))
