export { WorkspaceClient } from './client';
export { workspaceGatewayTransport } from './gateway-adapter';
// WorkspacePanel is a recovery-test harness, not the production workbench.
export { bindWorkspaceSaveStatus, saveStatus, purposeText, recipientText } from './native-slots';
export { buildBrowserImport } from './import-browser';

export const integrationManifest = {
  package: 'W03',
  contract: 'expansion-v3-0aa98d5ebec838fd0e2b56a9eed2f32a51c6ec94dff526712083a589d858e510',
  backendFactory: 'career_lab.api.workspace_v2.install_workspace_operations',
  planHandler: 'career_lab.workspace.extension.workspace_plan',
  recoveryFactory: 'career_lab.api.workspace_integration.install_workspace_recovery',
  requires: ['formal Gateway registration', 'single W01 V2Store', 'existing v4 DOM slots'],
  status: 'formal_contract_migration_shared_mount_pending',
} as const;
