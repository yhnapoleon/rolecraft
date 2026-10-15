import type { ObjectRef } from '../workspace/contract-types';

/** One key per exact object version (and configuration number). */
export const exactRefKey = (ref: ObjectRef) =>
  [ref.session_id, ref.kind, ref.object_id, ref.version, ref.config_version ?? ''].join(':');
