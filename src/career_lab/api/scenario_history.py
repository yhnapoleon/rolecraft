"""Immutable scenario content for historical reads; never executes archived runtime code."""
from pathlib import Path
import hashlib
import shutil
from career_lab.contracts.v2 import FileRef, SessionBindings, ProtocolError, read_file
from career_lab.scenarios.v2.loader import load_package
from career_lab.scenarios.v2.module import ScenarioModule

def load_immutable_content(root):
    """Validate original bytes and references without re-rendering them with newer authorship code."""
    import json, yaml
    from career_lab.contracts.v2 import ScenarioBundle,MaterialV2,FactV2,RoleSpecV2,AssistantConfig
    from career_lab.scenarios.v2.loader import ScenarioPackage
    root=Path(root).resolve();raw=(root/'manifest.json').read_bytes();bundle=ScenarioBundle.model_validate_json(raw)
    contents={ref.path:read_file(root,ref) for ref in bundle.files}
    rules=yaml.safe_load(contents['scenario.yaml']);locale=json.loads(contents.get('locale.json',b'{}'))
    if rules['scenario_id']!=bundle.id or rules['revision']!=bundle.revision:raise ProtocolError('scenario_archive_invalid',status=503)
    if tuple(RoleSpecV2.model_validate(r) for r in json.loads(contents['roles.json']))!=bundle.role_specs:raise ProtocolError('scenario_archive_invalid',status=503)
    if AssistantConfig.model_validate_json(contents['baseline.json'])!=bundle.baseline_config:raise ProtocolError('scenario_archive_invalid',status=503)
    materials=tuple(MaterialV2.model_validate(m) for m in json.loads(contents['materials.json']))
    facts=tuple(FactV2.model_validate(f) for f in json.loads(contents['facts.json']))
    if len({(m.id,m.version) for m in materials})!=len(materials):raise ProtocolError('scenario_archive_invalid',status=503)
    for material in materials:
        text=contents[rules['material_files'][material.id][str(material.version)]].decode()
        for fragment in material.fragments:
            ref=fragment.ref
            if ref.object_id!=material.id or ref.version!=material.version or ref.kind!='material' or ref.span_start is None or text[ref.span_start:ref.span_end]!=fragment.text or ref.quote!=fragment.text:
                raise ProtocolError('scenario_archive_invalid',status=503)
    return ScenarioPackage(root,bundle,hashlib.sha256(raw).hexdigest(),materials,facts,rules,locale.get('locale','zh'),locale)

class HistoricalScenarioReader:
    """Only the three audited read methods. No engine, assistant or mutation methods.

    Runtime source checks still apply to the live ScenarioModule. Historical reads
    validate the original manifest and every declared file, and use stored state.
    """
    snapshot = ScenarioModule.snapshot
    reference = ScenarioModule.reference
    materials = ScenarioModule.materials
    list_tests = ScenarioModule.list_tests
    def __init__(self, root):
        self.package=load_immutable_content(Path(root)); self.work_language=self.package.locale
        self.files={f.path:f for f in self.package.bundle.files}
        self.bindings=SessionBindings(scenario=FileRef(path='manifest.json',sha256=self.package.content_hash),runtime=self.files['runtime/bundle.json'],evaluation=self.files['runtime/evaluation.json'])
    def check_bindings(self, bindings):
        if bindings!=self.bindings:raise ProtocolError('scenario_archive_unavailable',status=409)
        read_file(self.package.root,bindings.scenario)

class ScenarioReadCatalog:
    def __init__(self, current, archive):
        self.current=current; self.archive=Path(archive) if archive else None; self.cache={}
        if self.archive:self.preserve(current.package.root)
    def preserve(self, root):
        package=load_immutable_content(Path(root)); target=self.archive/package.content_hash
        if target.exists():
            existing=HistoricalScenarioReader(target)
            if existing.package.content_hash!=package.content_hash:raise ProtocolError('scenario_archive_invalid',status=503)
            return target
        self.archive.mkdir(parents=True,exist_ok=True)
        import tempfile
        with tempfile.TemporaryDirectory(prefix='.capture-',dir=self.archive) as temporary:
            stage=Path(temporary)/'content';stage.mkdir()
            (stage/'manifest.json').write_bytes((package.root/'manifest.json').read_bytes())
            for ref in package.bundle.files:
                path=stage/ref.path;path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(read_file(package.root,ref))
            HistoricalScenarioReader(stage)
            try:stage.rename(target)
            except FileExistsError:HistoricalScenarioReader(target)
        return target
    def resolve(self, bindings):
        if bindings==self.current.bindings:return self.current
        key=bindings.scenario.sha256
        if not self.archive:raise ProtocolError('scenario_archive_unavailable',status=409)
        if key not in self.cache:
            root=self.archive/key
            if not root.is_dir():raise ProtocolError('scenario_archive_unavailable',status=409)
            self.cache[key]=HistoricalScenarioReader(root)
        self.cache[key].check_bindings(bindings)
        return self.cache[key]
