export interface DocumentBox {
  x: number;
  y: number;
  width: number;
  height: number;
}

export const DOCUMENT_DURATION: number;
export const DOCUMENT_EASE: readonly [number, number, number, number];
export function documentEase(progress: number): number;
export function mixBox(from: DocumentBox, to: DocumentBox, progress: number): DocumentBox;
/** An inert, aria-hidden copy of a surface for the flight layer: no ids, no data-v4-* markers. */
export function cleanClone(node: HTMLElement): HTMLElement;
export function createDocumentMotion(): {
  transition(fromRoute: string, toRoute: string, id: string, update: () => void): boolean;
  sync(): void;
  cancel(): void;
  readonly active: boolean;
};
