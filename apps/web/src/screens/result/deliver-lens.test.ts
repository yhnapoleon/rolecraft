import {it,expect,vi} from 'vitest';
import {openLensForDelivery} from './deliver-lens';
import {lensOn,setLens} from '../../features/recognition-native/lens';
it.each([false,true])('delivery never changes explicit technical preference %s',on=>{setLens(on);const sheet={querySelector:vi.fn(),addEventListener:vi.fn()} as unknown as HTMLDialogElement;openLensForDelivery(sheet);expect(lensOn()).toBe(on);expect(sheet.addEventListener).not.toHaveBeenCalled();expect(sheet.querySelector).not.toHaveBeenCalled();});
