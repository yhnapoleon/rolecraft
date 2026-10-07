/** Public W01 wire types. Kept structurally identical to the frozen contracts.
 * Feature modules may retain generated private aliases; the host has no feature dependency. */
export type Command = { "expected_version": number; "expected_workspace_revision": number; "operation": string; "payload"?: Record<string, JsonValue>; "request_id": string; "schema_version": 2 };
export type EvidenceRefV2 = { "config_version"?: (number | null); "kind": string; "object_id": string; "observed_at_seq": number; "quote"?: (string | null); "schema_version"?: 2; "session_id": string; "span_end"?: (number | null); "span_start"?: (number | null); "valid_from_seq"?: number; "valid_until_seq"?: (number | null); "version": number };
export type ObjectRef = { "config_version"?: (number | null); "kind": string; "object_id": string; "schema_version"?: 2; "session_id": string; "version": number };
export type VersionPoint = { "business_seq": number; "schema_version"?: 2; "storage_revision": number; "workspace_revision": number };
export type JsonValue = unknown;
