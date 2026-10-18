import argparse
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch


class PortableBuildTests(unittest.TestCase):
    def test_running_bundle_rejected_before_any_source_or_state_is_changed(self):
        root=Path(__file__).resolve().parent
        spec=importlib.util.spec_from_file_location('portable_build',root/'scripts/build-portable.py');build=importlib.util.module_from_spec(spec);spec.loader.exec_module(build)
        version=json.loads((root/'electron-ui/package.json').read_text('utf-8'))['version']
        with tempfile.TemporaryDirectory() as temporary:
            output=Path(temporary);stage=output/'vtest';bundle=stage/f'Apex-Clipper-{version}-Windows-x64';resources=bundle/'resources';(resources/'runtime').mkdir(parents=True)
            (resources/'runtime/runtime-layout.json').write_text('{}','utf-8');module=resources/'hud_enrichment.py';module.write_bytes(b'previous running source')
            state=stage/'.apex-build.json';state.write_text('{"status":"succeeded"}','utf-8');before={file:file.read_bytes() for file in [module,state]}
            args=argparse.Namespace(stage='vtest',refresh=True,shared_runtime_source=None,electron='unused',runtime_source=None)
            with patch.object(build,'OUT',output),patch.object(build,'verified_shared_source'),patch.object(build,'assert_bundle_not_running',side_effect=RuntimeError('目标应用正在运行')),self.assertRaisesRegex(RuntimeError,'正在运行'):build.build(args)
            self.assertFalse(hasattr(args,'managed_stage'));self.assertTrue(all(file.read_bytes()==content for file,content in before.items()))

    def test_refresh_rejected_by_archive_preflight_preserves_previous_success(self):
        root=Path(__file__).resolve().parent
        spec=importlib.util.spec_from_file_location('portable_build',root/'scripts/build-portable.py');build=importlib.util.module_from_spec(spec);spec.loader.exec_module(build)
        version=json.loads((root/'electron-ui/package.json').read_text('utf-8'))['version']
        with tempfile.TemporaryDirectory() as temporary:
            output=Path(temporary);stage=output/'vtest';bundle=stage/f'Apex-Clipper-{version}-Windows-x64';resources=bundle/'resources';(resources/'runtime').mkdir(parents=True)
            (resources/'runtime/runtime-layout.json').write_text('{}','utf-8');(resources/'FILES.sha256.json').write_text('{}','utf-8')
            state=stage/'.apex-build.json';state.write_text('{"status":"succeeded"}','utf-8');archive=stage/(bundle.name+'.zip');archive.write_bytes(b'previous successful package')
            report=stage/'validation-report.json';report.write_text(json.dumps({'sha256':'outdated'}),'utf-8');before={file:file.read_bytes() for file in [state,archive,report]}
            args=argparse.Namespace(stage='vtest',refresh=True,shared_runtime_source=None,electron='unused',runtime_source=None)
            with patch.object(build,'OUT',output),self.assertRaisesRegex(RuntimeError,'ZIP'):build.build(args)
            self.assertFalse(hasattr(args,'managed_stage'))
            self.assertTrue(all(file.read_bytes()==content for file,content in before.items()))


if __name__=='__main__':unittest.main()
