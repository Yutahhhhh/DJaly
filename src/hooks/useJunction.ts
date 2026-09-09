import { useSyncExternalStore } from 'react';
import { junctionState } from '@/services/junction/state';
export function useJunction() { return useSyncExternalStore(junctionState.subscribe, junctionState.get, () => null); }
