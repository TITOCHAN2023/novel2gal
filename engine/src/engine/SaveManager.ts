import type { SaveSlot } from './types';

const DB_NAME = 'novel2gal';
const STORE_NAME = 'saves';
const DB_VERSION = 1;

function openDB(): Promise<IDBDatabase> {
  return new Promise((resolve, reject) => {
    const req = indexedDB.open(DB_NAME, DB_VERSION);
    req.onupgradeneeded = () => {
      const db = req.result;
      if (!db.objectStoreNames.contains(STORE_NAME)) {
        db.createObjectStore(STORE_NAME, { keyPath: 'id' });
      }
    };
    req.onsuccess = () => resolve(req.result);
    req.onerror = () => reject(req.error);
  });
}

async function withDB<T>(mode: IDBTransactionMode, fn: (store: IDBObjectStore) => IDBRequest): Promise<T> {
  const db = await openDB();
  return new Promise((resolve, reject) => {
    const tx = db.transaction(STORE_NAME, mode);
    const req = fn(tx.objectStore(STORE_NAME));
    req.onsuccess = () => resolve(req.result as T);
    tx.oncomplete = () => db.close();
    tx.onerror = () => { db.close(); reject(tx.error); };
  });
}

export async function saveGame(slot: SaveSlot): Promise<void> {
  await withDB('readwrite', (store) => store.put(slot));
}

export async function loadGame(slotId: number): Promise<SaveSlot | null> {
  const result = await withDB<SaveSlot | undefined>('readonly', (store) => store.get(slotId));
  return result ?? null;
}

export async function listSaves(): Promise<SaveSlot[]> {
  const slots = await withDB<SaveSlot[]>('readonly', (store) => store.getAll());
  return slots.sort((a, b) => (b.timestamp || 0) - (a.timestamp || 0));
}

export async function deleteSave(slotId: number): Promise<void> {
  await withDB('readwrite', (store) => store.delete(slotId));
}
