"""Compose existing reviewed source compilation and the existing EB backend."""
import copy
from pathlib import Path
import shutil
import tempfile

from .common import ROOT, read, require, save, seal, sha
from .idf import parse
from .runtime_release import fixed_rows, reviewed_runtime, validate_compiled
from .source_case import compile_source_case
from .request_support import syntax_failures


def compile_case(case,out,*,root=ROOT,today=None):
    root=Path(root).resolve()
    require(not syntax_failures(case,root),'FORMAL_INPUT_SCHEMA',syntax_failures(case,root))
    identifier=case['environment']['physics_configuration_id']
    record,plan,template,domain,release=reviewed_runtime(identifier,root=root,today=today)
    require(not Path(out).is_symlink(),'OUTPUT_EXISTS')
    out=Path(out).resolve();require(out.is_relative_to(root),'FORMAL_CASE_OUTPUT_OUTSIDE_PROJECT')
    require(not out.exists() and not out.is_symlink(),'OUTPUT_EXISTS')
    out.parent.mkdir(parents=True,exist_ok=True)
    with tempfile.TemporaryDirectory(dir=out.parent,prefix='.reviewed-EB-') as temporary:
        temporary=Path(temporary)
        source=temporary/'reviewed_source'
        compile_source_case(case,source,root=root,today=today)
        require(fixed_rows(parse((source/'in.idf').read_text()))==fixed_rows(plan['new_model_rows']),
            'FORMAL_CASE_FIXED_SOURCE_CHANGED')
        spec=copy.deepcopy(template)
        spec['model']={'path':str((source/'in.idf').relative_to(root)),'sha256':sha(source/'in.idf')}
        spec_path=temporary/'FIXTURE.json';save(spec_path,spec)
        from .joint_case_runtime import compile_joint_case
        stage=temporary/'compiled'
        # This is the shared assembly/controller compiler. Formal authority is
        # supplied by the physical and runtime releases checked above.
        compile_joint_case({'path':str(spec_path.relative_to(root)),'sha256':sha(spec_path)},case,stage,
            mode='engineering_reference',root=root)
        shutil.copytree(source,stage/'reviewed_source')
        spec['model']={'path':str((out/'in.idf').relative_to(root)),'sha256':sha(stage/'in.idf')}
        save(stage/'FIXTURE.json',spec);save(stage/'SOURCE_RUNTIME_RELEASE.json',release)
        receipt=seal(stage,{'schema':'national_idf.compiled_reviewed_six_CASE.v1',
            'execution_mode':'formal','physics_configuration_id':identifier,
            'physical_definition_sha256':release['physical_definition_sha256'],
            'source_compilation_reviewed':True,'formal_runtime_authorized':True,
            'formal_admitted':True,'engine_started':False,'six_devices_bound':True})
        require(not out.exists() and not out.is_symlink(),'OUTPUT_EXISTS');stage.rename(out)
    return receipt


def run_case(compiled,out,*,root=ROOT,today=None,tank_diagnostics=None):
    compiled=Path(compiled).resolve()
    validate_compiled(compiled,root=root,today=today)
    from .joint_case_runtime import run_joint_case
    return run_joint_case(compiled,out,mode='formal',root=root,tank_diagnostics=tank_diagnostics)
