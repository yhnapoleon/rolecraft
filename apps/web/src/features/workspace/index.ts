export { WorkspaceClient } from './client';
// WorkspacePanel is a recovery-test harness, not the production workbench.
export { bindWorkspaceSaveStatus, saveStatus, purposeText, recipientText } from './native-slots';
export { buildBrowserImport } from './import-browser';

export const integrationManifest = {
  package: 'W03',
  contract: 'expansion-v3-df634361108035579f72dd9238665cea3e86f564effcd00e918290c82f3a1b66',
  backendFactory: 'career_lab.api.workspace_v2.install_workspace_operations',
  planHandler: 'career_lab.workspace.extension.workspace_plan',
  requires: ['formal Gateway registration', 'single W01 V2Store', 'existing v4 DOM slots'],
  status: 'formal_contract_migration_shared_mount_pending',
} as const;
