import { type ClassValue, clsx } from 'clsx';
import { extendTailwindMerge } from 'tailwind-merge';

// Our classes carry the tw: prefix; tailwind-merge needs to know it to dedupe them.
const merge = extendTailwindMerge({ prefix: 'tw' });

export function cn(...inputs: ClassValue[]) {
  return merge(clsx(inputs));
}
