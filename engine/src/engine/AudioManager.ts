/**
 * 简易音频管理器 — 管理 BGM 和 SFX 的播放/切换/音量
 */
export class AudioManager {
  private bgmElement: HTMLAudioElement | null = null;
  private currentBgmSrc = '';
  private bgmVolume = 0.7;
  private sfxVolume = 0.8;

  setBgmVolume(v: number) {
    this.bgmVolume = v;
    if (this.bgmElement) this.bgmElement.volume = v;
  }

  setSfxVolume(v: number) {
    this.sfxVolume = v;
  }

  playBgm(src: string) {
    if (!src) {
      this.stopBgm();
      return;
    }
    if (src === this.currentBgmSrc && this.bgmElement && !this.bgmElement.paused) {
      return; // 同一曲目已在播放
    }
    this.stopBgm();
    this.currentBgmSrc = src;
    this.bgmElement = new Audio(src);
    this.bgmElement.loop = true;
    this.bgmElement.volume = this.bgmVolume;
    this.bgmElement.play().catch(() => {
      // 浏览器可能在用户交互前阻止自动播放
    });
  }

  stopBgm() {
    if (this.bgmElement) {
      this.bgmElement.pause();
      this.bgmElement.src = '';
      this.bgmElement = null;
    }
    this.currentBgmSrc = '';
  }

  /** 淡出 BGM（duration ms） */
  fadeOutBgm(duration = 1000): Promise<void> {
    return new Promise((resolve) => {
      if (!this.bgmElement) {
        resolve();
        return;
      }
      const el = this.bgmElement;
      const startVol = el.volume;
      const step = startVol / (duration / 50);
      const interval = setInterval(() => {
        el.volume = Math.max(0, el.volume - step);
        if (el.volume <= 0) {
          clearInterval(interval);
          this.stopBgm();
          resolve();
        }
      }, 50);
    });
  }

  playSfx(src: string) {
    const audio = new Audio(src);
    audio.volume = this.sfxVolume;
    audio.play().catch(() => {});
  }
}

export const audioManager = new AudioManager();
