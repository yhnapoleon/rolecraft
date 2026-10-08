export { WorkspaceClient } from './client';
export { workspaceGatewayTransport } from './gateway-adapter';
// WorkspacePanel is a recovery-test harness, not the production workbench.
export { bindWorkspaceSaveStatus, saveStatus, purposeText, recipientText } from './native-slots';
export { buildBrowserImport } from './import-browser';

export const integrationManifest = {
  package: 'W03',
  contract: 'expansion-v3-5edc886f3e862b53b11c19dbcf9955042d02c7ff18dd4ecf51fee8bb3d7c108c',
  backendFactory: 'career_lab.api.workspace_v2.install_workspace_operations',
  planHandler: 'career_lab.workspace.extension.workspace_plan',
  recoveryFactory: 'career_lab.api.workspace_integration.install_workspace_recovery',
  requires: ['formal Gateway registration', 'single W01 V2Store', 'existing v4 DOM slots'],
  status: 'formal_contract_migration_shared_mount_pending',
} as const;
