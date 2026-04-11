import { create } from 'zustand';

const API_BASE = `http://${window.location.hostname}:8080`;

export interface StoryEntry {
  id: string;
  title: string;
  author: string;
  filename: string;
  created_at: string;
  updated_at: string;
  status: 'uploading' | 'parsing' | 'generating' | 'ready' | 'error' | 'queued';
  progress: {
    phase: number;
    phase_name: string;
    detail: string;
    percent: number;
  };
  error: string | null;
  stats: {
    chapters: number;
    chunks: number;
    characters: number;
    scenes: number;
  };
}

interface LauncherState {
  stories: StoryEntry[];
  currentStoryId: string | null;
  loading: boolean;

  fetchStories: () => Promise<void>;
  selectStory: (id: string) => void;
  clearStory: () => void;
  uploadBook: (file: File) => Promise<string | null>;
  deleteStory: (id: string) => Promise<boolean>;
  updateStoryFromWS: (storyId: string, patch: Partial<StoryEntry>) => void;
}

export const useLauncherStore = create<LauncherState>((set, get) => ({
  stories: [],
  currentStoryId: null,
  loading: false,

  fetchStories: async () => {
    set({ loading: true });
    try {
      const resp = await fetch(`${API_BASE}/api/stories`);
      if (!resp.ok) {
        console.warn(`[launcherStore] fetchStories HTTP ${resp.status}`);
        set({ loading: false });
        return;
      }
      const data = await resp.json();
      set({ stories: data.stories || [], loading: false });
    } catch (e) {
      console.warn('[launcherStore] fetchStories 网络错误:', e);
      set({ loading: false });
    }
  },

  selectStory: (id) => set({ currentStoryId: id }),
  clearStory: () => set({ currentStoryId: null }),

  uploadBook: async (file) => {
    const form = new FormData();
    form.append('file', file);
    try {
      const resp = await fetch(`${API_BASE}/api/stories/upload`, { method: 'POST', body: form });
      if (!resp.ok) {
        console.warn(`[launcherStore] uploadBook HTTP ${resp.status}`);
        return null;
      }
      const data = await resp.json();
      if (data.success) {
        await get().fetchStories();
        return data.story_id as string;
      }
      console.warn('[launcherStore] uploadBook 失败:', data.error || data);
      return null;
    } catch (e) {
      console.warn('[launcherStore] uploadBook 网络错误:', e);
      return null;
    }
  },

  deleteStory: async (id) => {
    try {
      const resp = await fetch(`${API_BASE}/api/stories/${id}`, { method: 'DELETE' });
      if (!resp.ok) {
        console.warn(`[launcherStore] deleteStory HTTP ${resp.status}`);
        return false;
      }
      const data = await resp.json();
      if (data.success) {
        set((s) => ({ stories: s.stories.filter((st) => st.id !== id) }));
        return true;
      }
      return false;
    } catch (e) {
      console.warn('[launcherStore] deleteStory 网络错误:', e);
      return false;
    }
  },

  updateStoryFromWS: (storyId, patch) => {
    set((s) => ({
      stories: s.stories.map((st) =>
        st.id === storyId ? { ...st, ...patch } : st
      ),
    }));
  },
}));
