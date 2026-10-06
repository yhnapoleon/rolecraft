export { WorkspaceClient } from './client';
export { WorkspacePanel, BrowserImportPicker, ImportPreview } from './WorkspacePanel';
export { buildBrowserImport } from './import-browser';

export const integrationManifest = {
  package: 'W03',
  contract: 'draft-391f39156eba1a56b7fbb1228484e5e31143027bfe637bf45fb029ec369d222e',
  backendFactory: 'career_lab.api.workspace_v2.create_router',
  serviceFactory: 'career_lab.workspace.service.create_service',
  tableRegistration: 'career_lab.storage.workspace_v2.register_tables',
  requires: ['trusted AuthContext', 'W01 WorkspaceAuthority adapter', 'existing workbench mount'],
  status: 'implementation_only_unmounted',
} as const;
